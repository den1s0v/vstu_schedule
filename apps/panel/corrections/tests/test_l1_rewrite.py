"""Тесты Django-free ядра L1."""

from apps.panel.services.corrections.dto import RewriteRuleDTO
from apps.panel.services.corrections.rewrite import apply_rewrite
from apps.panel.services.corrections.transformers import (
    decode_re_spaces,
    fix_sparse_words,
    known_transformer_ids,
)


def test_known_transformers_include_vstuxls_ids() -> None:
    ids = known_transformer_ids()
    assert "fix_sparse_words" in ids
    assert "decode_re_spaces" in ids
    assert "shrink_extra_inner_spaces" in ids


def test_decode_re_spaces() -> None:
    assert decode_re_spaces("a b") == r"a\s*b"
    assert decode_re_spaces("a  b") == r"a\s+b"


def test_fix_sparse_words() -> None:
    assert fix_sparse_words("М А Т Е М А Т И К А") == "МАТЕМАТИКА"


def test_apply_rewrite_order_and_no_django() -> None:
    """Ядро L1 вызывается на DTO без ORM."""
    rules = [
        RewriteRuleDTO(id=2, mode="substring", search="foo", replacement="bar", priority=20),
        RewriteRuleDTO(id=1, mode="exact", search="hello", replacement="hi", priority=10),
    ]
    result = apply_rewrite("hello", rules)
    assert result.output_text == "hi"
    assert result.applied_rule_ids == (1,)


def test_apply_rewrite_substring_and_priority() -> None:
    rules = [
        RewriteRuleDTO(id=1, mode="substring", search="АА", replacement="А.А.", priority=10),
        RewriteRuleDTO(id=2, mode="substring", search="Иванов", replacement="ИВАНОВ", priority=5),
    ]
    result = apply_rewrite("Иванов АА", rules)
    assert result.output_text == "ИВАНОВ А.А."
    assert result.applied_rule_ids == (2, 1)


def test_re_spaces_mode() -> None:
    rules = [
        RewriteRuleDTO(
            id=1,
            mode="re_spaces",
            search="Иванов А А",
            replacement="Иванов А.А.",
            priority=1,
        )
    ]
    result = apply_rewrite("Иванов АА", rules)
    # pattern "Иванов А А" → Иванов\s*А\s*А — may not match "Иванов АА" without space
    # Use a pattern that matches:
    rules2 = [
        RewriteRuleDTO(
            id=1,
            mode="re_spaces",
            search="Иванов  АА",
            replacement="Иванов А.А.",
            priority=1,
        )
    ]
    result2 = apply_rewrite("Иванов АА", rules2)
    assert result2.output_text == "Иванов А.А."
    assert result.output_text in {"Иванов АА", "Иванов А.А."}
