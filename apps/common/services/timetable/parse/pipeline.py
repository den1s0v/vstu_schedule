from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.models import FileVersion, TimetableFileImport
from apps.common.services.timetable.load.event_importer import EventImporter
from apps.common.services.timetable.load.reference_importer import ReferenceImporter

from .excel_parser import TimetableImportContext, parse_timetable_excel

logger = logging.getLogger(__name__)

_EXCEL_EXTENSIONS = {".xls", ".xlsx"}


@dataclass(frozen=True)
class TimetablePipelineResult:
    imported: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "imported": self.imported,
            "failed": self.failed,
            "skipped": self.skipped,
            "details": self.details,
        }


def run_saved_timetable_import_pipeline(
    context: TimetableImportContext,
    *,
    changed_only: bool = True,
    save_archive_schedules: bool = True,
    resource_ids: list[int] | None = None,
    resolver: Any | None = None,
    corrections_strict: bool = False,
    use_corrections: bool = False,
) -> TimetablePipelineResult:
    versions = _select_file_versions(changed_only=changed_only, resource_ids=resource_ids)
    imported = failed = skipped = 0
    details = []

    for file_version in versions:
        import_record = TimetableFileImport.objects.create(file_version=file_version)
        try:
            file_path = _local_file_path(file_version)
            if file_path.suffix.lower() not in _EXCEL_EXTENSIONS:
                _finish_import(
                    import_record,
                    TimetableFileImport.Status.SKIPPED,
                    result={"reason": "not_excel", "path": str(file_path)},
                )
                skipped += 1
                continue

            with transaction.atomic():
                parsed = parse_timetable_excel(file_path, context)
                ReferenceImporter.import_schedule(
                    json.dumps([parsed.schedule_metadata], ensure_ascii=False),
                    save_archive_schedules,
                )
                resolution_report = EventImporter.import_events(
                    json.dumps(parsed.event_payload, ensure_ascii=False),
                    resolver=resolver,
                    corrections_strict=corrections_strict,
                )
                result_payload: dict[str, Any] = {
                    "title": parsed.title,
                    "path": str(file_path),
                    "use_corrections": use_corrections,
                    "corrections_strict": corrections_strict,
                }
                if use_corrections and resolution_report is not None:
                    as_dict = getattr(resolution_report, "as_dict", None)
                    if callable(as_dict):
                        result_payload["resolution"] = as_dict()
                _finish_import(
                    import_record,
                    TimetableFileImport.Status.IMPORTED,
                    metadata=parsed.schedule_metadata,
                    result=result_payload,
                )
            imported += 1
        except Exception as exc:
            logger.exception(
                "Failed to import timetable file version %s",
                file_version.id,
            )
            _finish_import(
                import_record,
                TimetableFileImport.Status.FAILED,
                error=str(exc),
            )
            failed += 1

        details.append(
            {
                "file_version_id": file_version.id,
                "status": import_record.status,
                "error": import_record.error,
            }
        )

    return TimetablePipelineResult(
        imported=imported,
        failed=failed,
        skipped=skipped,
        details=details,
    )


def _select_file_versions(
    *,
    changed_only: bool,
    resource_ids: list[int] | None,
) -> list[FileVersion]:
    queryset = FileVersion.objects.select_related("resource").order_by("-timestamp", "-id")
    if resource_ids:
        queryset = queryset.filter(resource_id__in=resource_ids)
    if changed_only:
        queryset = queryset.exclude(timetable_imports__status=TimetableFileImport.Status.IMPORTED)
    return list(queryset)


def _local_file_path(file_version: FileVersion) -> Path:
    resource = file_version.resource
    filename = unquote(Path(urlparse(file_version.url or "").path).name)
    if not filename:
        raise ValueError(f"FileVersion {file_version.id} does not have a source filename.")
    base_dir = settings.DATA_STORAGE_DIR / (resource.path or resource.name)
    candidates = _local_file_candidates(base_dir, filename, file_version.mimetype)
    for path in candidates:
        if path.is_file():
            return path
    candidates_text = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Stored timetable file not found. Checked: {candidates_text}")


def _local_file_candidates(base_dir: Path, filename: str, mimetype: str | None) -> list[Path]:
    candidates = [base_dir / filename]
    if mimetype:
        suffix = mimetype if mimetype.startswith(".") else f".{mimetype}"
        converted_name = Path(filename).with_suffix(suffix).name
        converted_path = base_dir / converted_name
        if converted_path not in candidates:
            candidates.append(converted_path)
    return candidates


def _finish_import(
    import_record: TimetableFileImport,
    status: str,
    *,
    metadata: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    import_record.status = status
    import_record.finished_at = timezone.now()
    import_record.metadata = metadata or {}
    import_record.result = result or {}
    import_record.error = error
    import_record.save(update_fields=["status", "finished_at", "metadata", "result", "error"])
