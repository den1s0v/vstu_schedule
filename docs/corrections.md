# Трёхслойная система корректировок

См. также исходные черновики: [drafts/corrections-idea-v2.txt](drafts/corrections-idea-v2.txt),
[drafts/corrections.txt.py](drafts/corrections.txt.py).

## Слои

```text
raw text
  → L1 apply_rewrite (правила TextRewriteRule)
  → L2 match_variant (кандидаты CorrectObject, неоднозначность OK)
  → L3 open_case / resolve (ручной выбор или стратегия)
```

Клиент может вызывать любой поднабор через `run_pipeline(..., layers=("l1", "l2"))`.

| Слой | Назначение | Публичный API |
|------|------------|---------------|
| L1 | Детерминированная перезапись строк без контекста | `apply_rewrite` |
| L2 | Варианты ↔ объекты, словари, запреты/ручные связи | `match_variant`, `import_dictionary`, `approve_link`, `forbid_link` |
| L3 | Разрешение неоднозначности | `open_case`, `resolve_case_manually`, `CandidateResolver` |

Ядро L1 (`dto`, `transformers`, `rewrite`) не зависит от Django и не импортирует `vstuxls.string_matching`.
Трансформеры повторяют id/семантику vstuxls локально.

## Метрика L2

Схожесть и пороги `auto_link_threshold` / `suggest_threshold` — **[0.0, 1.0]**
(`JaroWinkler.normalized_similarity`). Левенштейн — только тайбрейкер.
`confirmation_threshold` — целое число вариантов в кластере.

Порядок: точное совпадение → нечёткие кандидаты → исключить `FORBIDDEN` →
единственный score ≥ auto_link связывает → иначе кандидаты ≥ suggest → иначе кластер/создание.

## Usage

`CorrectionUsage(kind=rule|object, target_id, input_fingerprint, count)`:

- **total** = сумма `count` по сущности;
- **unique** = число различных fingerprint.

Сырой текст не хранится.

## Контракт L3 resolver

```python
class CandidateResolver(Protocol):
    name: str
    def resolve(self, candidates, context: ResolutionContext) -> ResolutionResult: ...
```

`ResolutionContext` содержит generic `entities`, `relations`, `features`.
Зарегистрированы `passthrough` и заглушка `schedule_graph` (алгоритм позже).

## Размещение кода

- модели: `apps/panel/corrections/models/`, реэкспорт из `apps.panel.models`
- сервисы: `apps/panel/services/corrections/`
- UI: `apps/panel/views/corrections/`, шаблоны `panel/corrections/`
- документация этой архитектуры: этот файл
