"""Политика авто-создания CorrectObject через кластеризацию вариантов."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.panel.corrections.models import (
    CorrectionScope,
    CorrectObject,
    EntityCreationPolicy,
    SpellingVariant,
    VariantObjectLink,
)
from apps.panel.services.corrections.audit import stamp_create
from apps.panel.services.corrections.matching import similarity

logger = logging.getLogger("apps.panel.services.corrections")


@transaction.atomic
def maybe_create_from_cluster(
    *,
    scope: CorrectionScope,
    entity_type: str,
    seed_variant: SpellingVariant,
    policy: EntityCreationPolicy | None,
    actor: Any | None = None,
) -> CorrectObject | None:
    """
    Создать объект только если нет достаточно близких готовых кандидатов
    и накопился кластер похожих несвязанных вариантов.
    """
    if policy is None or not policy.enabled:
        return None

    # Unlinked variants of same type (no PENDING/APPROVED links)
    candidates = list(
        SpellingVariant.objects.filter(scope=scope, entity_type=entity_type)
        .exclude(
            object_links__status__in=[
                VariantObjectLink.Status.PENDING,
                VariantObjectLink.Status.APPROVED,
            ]
        )
        .distinct()
    )
    if seed_variant not in candidates:
        candidates.append(seed_variant)

    cluster = [
        v
        for v in candidates
        if similarity(seed_variant.value, v.value) >= policy.suggest_threshold
    ]
    if len(cluster) < policy.confirmation_threshold:
        logger.debug(
            "Кластер для %s слишком мал: %s < %s",
            seed_variant.value,
            len(cluster),
            policy.confirmation_threshold,
        )
        return None

    # Prefer longest / most frequent-looking canonical
    canonical = max(cluster, key=lambda v: (len(v.value), v.id)).value
    obj = CorrectObject(
        scope=scope,
        entity_type=entity_type,
        external_id="",
        canonical_value=canonical,
        origin=CorrectObject.Origin.CLUSTERED,
        metadata={"cluster_size": len(cluster)},
    )
    stamp_create(obj, actor)
    obj.save()

    for variant in cluster:
        link, created = VariantObjectLink.objects.get_or_create(
            variant=variant,
            correct_object=obj,
            defaults={
                "status": VariantObjectLink.Status.PENDING,
                "source": VariantObjectLink.Source.CLUSTER,
                "score": similarity(variant.value, canonical),
                "confirmation_count": 1,
            },
        )
        if created:
            stamp_create(link, actor)
            link.save(update_fields=["created_by", "updated_by"])
        elif link.status == VariantObjectLink.Status.FORBIDDEN:
            continue

    logger.info("Создан clustered CorrectObject #%s для %s", obj.id, entity_type)
    return obj
