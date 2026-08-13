"""Views трёхслойных корректировок."""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_http_methods

from apps.panel.corrections.models import (
    CorrectionScope,
    CorrectObject,
    DisambiguationCase,
    EntityCreationPolicy,
    SpellingVariant,
    TextRewriteRule,
    VariantObjectLink,
)
from apps.panel.corrections.selectors import (
    open_disambiguation_cases,
    rewrite_rules_for_scope,
    usage_map,
)
from apps.panel.services.corrections.dictionaries import (
    import_dictionary,
    validate_dictionary_payload,
)
from apps.panel.services.corrections.disambiguation import list_resolvers
from apps.panel.services.corrections.disambiguation.manual import resolve_case_manually
from apps.panel.services.corrections.dto import RewriteRuleDTO
from apps.panel.services.corrections.links import approve_link, forbid_link, remove_link
from apps.panel.services.corrections.matching import get_or_create_scope, match_variant
from apps.panel.services.corrections.rewrite import apply_rewrite

logger = logging.getLogger("apps.panel.views.corrections")


def _scope_from_request(request: HttpRequest) -> CorrectionScope:
    key = request.GET.get("scope") or request.POST.get("scope") or "global"
    return get_or_create_scope(key, actor=request.user)


@staff_member_required
@require_http_methods(["GET", "POST"])
def corrections_l1(request: HttpRequest) -> HttpResponse:
    scope = _scope_from_request(request)
    sandbox_result = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_rule":
            rule_id = request.POST.get("rule_id")
            data = {
                "mode": request.POST.get("mode") or TextRewriteRule.Mode.EXACT,
                "search": request.POST.get("search", ""),
                "replacement": request.POST.get("replacement", ""),
                "priority": int(request.POST.get("priority") or 100),
                "enabled": request.POST.get("enabled") == "on",
                "preprocess": [
                    p.strip()
                    for p in (request.POST.get("preprocess") or "").split(",")
                    if p.strip()
                ],
            }
            if rule_id:
                rule = get_object_or_404(TextRewriteRule, pk=rule_id, scope=scope)
                for key, value in data.items():
                    setattr(rule, key, value)
                rule.updated_by = request.user
                rule.save()
                messages.success(request, gettext("Правило обновлено."))
            else:
                rule = TextRewriteRule(scope=scope, created_by=request.user, updated_by=request.user, **data)
                rule.save()
                messages.success(request, gettext("Правило создано."))
            return redirect(f"{request.path}?scope={scope.key}")

        if action == "delete_rule":
            rule = get_object_or_404(TextRewriteRule, pk=request.POST.get("rule_id"), scope=scope)
            rule.delete()
            messages.success(request, gettext("Правило удалено."))
            return redirect(f"{request.path}?scope={scope.key}")

        if action == "sandbox":
            text = request.POST.get("sandbox_text", "")
            rules = [
                RewriteRuleDTO(
                    id=r.id,
                    mode=r.mode,
                    search=r.search,
                    replacement=r.replacement,
                    preprocess=tuple(r.preprocess or []),
                    priority=r.priority,
                    enabled=r.enabled,
                )
                for r in rewrite_rules_for_scope(scope.id)
            ]
            sandbox_result = apply_rewrite(text, rules)

    rules = list(rewrite_rules_for_scope(scope.id))
    stats = usage_map("rule", [r.id for r in rules])
    for rule in rules:
        total, unique = stats.get(rule.id, (0, 0))
        rule.usage_total = total  # type: ignore[attr-defined]
        rule.usage_unique = unique  # type: ignore[attr-defined]

    return render(
        request,
        "panel/corrections/l1.html",
        {
            "active_nav": "corrections",
            "corrections_tab": "l1",
            "scope": scope,
            "scopes": CorrectionScope.objects.all(),
            "rules": rules,
            "modes": TextRewriteRule.Mode.choices,
            "sandbox_result": sandbox_result,
        },
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def corrections_l2(request: HttpRequest) -> HttpResponse:
    scope = _scope_from_request(request)
    entity_type = request.GET.get("entity_type") or request.POST.get("entity_type") or "teacher"
    match_result = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "import_dictionary":
            raw = request.POST.get("dictionary_json", "")
            try:
                payload = json.loads(raw)
                validate_dictionary_payload(payload)
                stats = import_dictionary(payload, actor=request.user)
                messages.success(
                    request,
                    gettext("Импорт: создано %(c)s, обновлено %(u)s, aliases %(a)s")
                    % {"c": stats["created"], "u": stats["updated"], "a": stats["aliases_linked"]},
                )
            except (json.JSONDecodeError, Exception) as exc:
                messages.error(request, str(exc))
            return redirect(f"{request.path}?scope={scope.key}&entity_type={entity_type}")

        if action == "sandbox":
            value = request.POST.get("sandbox_text", "")
            match_result = match_variant(
                value=value,
                entity_type=entity_type,
                scope_key=scope.key,
                actor=request.user,
            )

        if action == "approve_link":
            variant = get_object_or_404(SpellingVariant, pk=request.POST.get("variant_id"))
            obj = get_object_or_404(CorrectObject, pk=request.POST.get("object_id"))
            approve_link(variant=variant, correct_object=obj, actor=request.user)
            messages.success(request, gettext("Связь утверждена."))
            return redirect(f"{request.path}?scope={scope.key}&entity_type={entity_type}")

        if action == "forbid_link":
            variant = get_object_or_404(SpellingVariant, pk=request.POST.get("variant_id"))
            obj = get_object_or_404(CorrectObject, pk=request.POST.get("object_id"))
            forbid_link(variant=variant, correct_object=obj, actor=request.user)
            messages.success(request, gettext("Связь запрещена."))
            return redirect(f"{request.path}?scope={scope.key}&entity_type={entity_type}")

        if action == "remove_link":
            link = get_object_or_404(VariantObjectLink, pk=request.POST.get("link_id"))
            remove_link(link=link)
            messages.success(request, gettext("Связь удалена."))
            return redirect(f"{request.path}?scope={scope.key}&entity_type={entity_type}")

        if action == "ensure_policy":
            policy, _ = EntityCreationPolicy.objects.get_or_create(
                scope=scope,
                entity_type=entity_type,
                defaults={
                    "created_by": request.user,
                    "updated_by": request.user,
                },
            )
            policy.auto_link_threshold = float(request.POST.get("auto_link_threshold") or policy.auto_link_threshold)
            policy.suggest_threshold = float(request.POST.get("suggest_threshold") or policy.suggest_threshold)
            policy.confirmation_threshold = int(
                request.POST.get("confirmation_threshold") or policy.confirmation_threshold
            )
            policy.enabled = request.POST.get("enabled") == "on"
            policy.updated_by = request.user
            policy.full_clean()
            policy.save()
            messages.success(request, gettext("Политика сохранена."))
            return redirect(f"{request.path}?scope={scope.key}&entity_type={entity_type}")

    objects = list(
        CorrectObject.objects.filter(scope=scope, entity_type=entity_type).prefetch_related(
            "variant_links__variant"
        )
    )
    stats = usage_map("object", [o.id for o in objects])
    for obj in objects:
        total, unique = stats.get(obj.id, (0, 0))
        obj.usage_total = total  # type: ignore[attr-defined]
        obj.usage_unique = unique  # type: ignore[attr-defined]

    links = VariantObjectLink.objects.filter(
        variant__scope=scope, variant__entity_type=entity_type
    ).select_related("variant", "correct_object")
    policy = EntityCreationPolicy.objects.filter(scope=scope, entity_type=entity_type).first()

    return render(
        request,
        "panel/corrections/l2.html",
        {
            "active_nav": "corrections",
            "corrections_tab": "l2",
            "scope": scope,
            "scopes": CorrectionScope.objects.all(),
            "entity_type": entity_type,
            "objects": objects,
            "links": links,
            "policy": policy,
            "match_result": match_result,
        },
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def corrections_l3(request: HttpRequest) -> HttpResponse:
    scope = _scope_from_request(request)

    if request.method == "POST":
        action = request.POST.get("action")
        case = get_object_or_404(DisambiguationCase, pk=request.POST.get("case_id"), scope=scope)
        if action == "resolve":
            object_id = request.POST.get("object_id")
            obj = get_object_or_404(CorrectObject, pk=object_id) if object_id else None
            resolve_case_manually(case=case, correct_object=obj, actor=request.user)
            messages.success(request, gettext("Кейс обновлён."))
        return redirect(f"{request.path}?scope={scope.key}")

    cases = list(open_disambiguation_cases(scope.id))
    return render(
        request,
        "panel/corrections/l3.html",
        {
            "active_nav": "corrections",
            "corrections_tab": "l3",
            "scope": scope,
            "scopes": CorrectionScope.objects.all(),
            "cases": cases,
            "resolvers": list_resolvers(),
        },
    )


@staff_member_required
def corrections_index(request: HttpRequest) -> HttpResponse:
    return redirect("panel_corrections_l1")
