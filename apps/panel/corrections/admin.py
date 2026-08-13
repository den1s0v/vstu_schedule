"""Admin-регистрация моделей корректировок."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.panel.corrections.models import (
    CorrectionScope,
    CorrectionUsage,
    CorrectObject,
    DisambiguationCandidate,
    DisambiguationCase,
    EntityCreationPolicy,
    SpellingVariant,
    TextRewriteRule,
    VariantObjectLink,
)


class EditableAuditAdminMixin:
    """Заполнение created_by/updated_by в Django Admin."""

    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        if not change and getattr(obj, "created_by_id", None) is None:
            obj.created_by = request.user
        if hasattr(obj, "updated_by_id"):
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)  # type: ignore[misc]


@admin.register(CorrectionScope)
class CorrectionScopeAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "description")
    search_fields = ("key", "description")


@admin.register(TextRewriteRule)
class TextRewriteRuleAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "scope", "mode", "search", "replacement", "priority", "enabled")
    list_filter = ("mode", "enabled", "scope")
    search_fields = ("search", "replacement")


@admin.register(CorrectObject)
class CorrectObjectAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "scope", "entity_type", "canonical_value", "external_id", "origin")
    list_filter = ("entity_type", "origin", "scope")
    search_fields = ("canonical_value", "external_id")


@admin.register(SpellingVariant)
class SpellingVariantAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "scope", "entity_type", "value")
    list_filter = ("entity_type", "scope")
    search_fields = ("value",)


@admin.register(VariantObjectLink)
class VariantObjectLinkAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "variant", "correct_object", "status", "source", "score")
    list_filter = ("status", "source")
    raw_id_fields = ("variant", "correct_object")


@admin.register(EntityCreationPolicy)
class EntityCreationPolicyAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "scope",
        "entity_type",
        "auto_link_threshold",
        "suggest_threshold",
        "confirmation_threshold",
        "enabled",
    )
    list_filter = ("enabled", "scope")


class DisambiguationCandidateInline(admin.TabularInline):
    model = DisambiguationCandidate
    extra = 0
    raw_id_fields = ("correct_object",)


@admin.register(DisambiguationCase)
class DisambiguationCaseAdmin(EditableAuditAdminMixin, admin.ModelAdmin):
    list_display = ("id", "scope", "entity_type", "variant", "status", "selected_object")
    list_filter = ("status", "entity_type", "scope")
    raw_id_fields = ("variant", "selected_object")
    inlines = (DisambiguationCandidateInline,)


@admin.register(CorrectionUsage)
class CorrectionUsageAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "target_id", "input_fingerprint", "count", "updated_at")
    list_filter = ("kind",)
    search_fields = ("input_fingerprint",)
    readonly_fields = ("updated_at",)
