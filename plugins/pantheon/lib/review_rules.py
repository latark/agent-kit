"""Пантеон: правило засчитывания вердиктов argus — ядро защит (Д3, metis-0858).

Одно правило для шлюза владельца (merge.gate, слияние PR ядра по Touch ID) и итога `pantheon review status`
(review_tally), чтобы они не разошлись (metis-0393). Раньше оно жило в lib/review.py, а тот не ядро: обычный PR в
review.py ослаблял бы шлюз ядра. Теперь файл в CORE_FILES шлюза guard, копии правила в review.py нет — это сверяет
plugins/guard/tests/test_core_deps.py.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла, имена из __all__ становятся
именами pantheon (P.review_records, P.review_accept_counts). Пути — через P в момент вызова, а не копией при
загрузке: merge.clean_env и тесты подменяют P.STATE.
"""
import json
import os
import re

__all__ = ["REVIEW_CHECKLIST", "OPUS_RAN", "RAN_MODEL", "review_accept_full", "review_accept_counts", "review_records",
           "carry_records", "review_decisions"]

# перечень проверенного в «принять» (Б6, guard 0.5.6): у accept все три поля обязательны и непусты, у reject — по
# желанию. Тот же разбор — в merge_gate.verdict_parse плагина guard (он и решает, будет ли запись)
REVIEW_CHECKLIST = {"opened": "открыл", "ran": "запустил", "unchecked": "не проверял"}
OPUS_RAN = re.compile(r"\s*модель:\s*claude-opus", re.I)   # как в шлюзе guard (metis-0176)
RAN_MODEL = re.compile(r"\s*модель:\s*(claude-[a-z0-9.-]*[a-z0-9])", re.I)  # ID модели из ran, как в шлюзе guard


def review_accept_full(r):
    """«Принять» с полным перечнем «открыл / запустил / не проверял» (Б6) — любая модель. Вне ядра шлюз guard считает
    такое «принять» (simplify п. 9); в PR ядра нужен ещё Opus — review_accept_counts."""
    c = r.get("checklist")
    return isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip() for k in REVIEW_CHECKLIST)


def review_accept_counts(r):
    """«Принять» в счёт шлюза ядра (metis-0176, Б6): полный перечень и --ran с «модель: claude-opus» в начале, а если хук
    guard записал модели из транскрипта argus (поле models) — все они claude-opus и среди них модель из ran (тот же ID
    или он с датой), как opus_problem шлюза guard. Поля models нет: у субагента argus (agent_id есть) с пометкой
    models_note — свой транскрипт не найден, не в счёт (metis-0489); у главной сессии argus или записи старше без
    пометки — судим по ran. Одно правило для шлюза владельца (merge.gate) и итога `review status` (review_tally),
    чтобы они не разошлись (metis-0393). Шлюз ядра владельца — только для PR ядра, там Opus обязателен."""
    c = r.get("checklist")
    if not (review_accept_full(r) and OPUS_RAN.match(c["ran"])):
        return False
    if "models" not in r:
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        return not (r.get("models_note") and by.get("agent_id"))
    seen = r["models"]
    if not isinstance(seen, list) or not all(isinstance(m, str) and m.startswith("claude-opus") for m in seen):
        return False   # пустой список отсеет any() ниже
    said = RAN_MODEL.match(c["ran"])
    said = said.group(1).lower() if said else ""
    return any(re.fullmatch(re.escape(said) + r"(-\d{8})?", m) for m in seen)


def review_records(repo=None, pr=None):
    """Записи журнала шлюза слияния (битые строки пропускаются); файл — симлинк или не читается — пусто."""
    try:
        fd = os.open(os.path.join(P.STATE, "merge-gate", "records.jsonl"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(rec, dict) or not isinstance(rec.get("repo"), list):
                continue
            if repo and repo.lower() not in [str(x).lower() for x in rec["repo"]]:
                continue
            if pr is not None and rec.get("pr") not in (pr, None):
                continue
            out.append(rec)
    return out



def carry_records(repo, pr):
    """Записи carry.jsonl шлюза guard на PR repo#pr по порядку записи: kind "carry" — перенос «принять» шлюзом gh pr
    merge (metis-0415), kind "decision" — решение о коде head при `pantheon merge request` (metis-0966). Битые строки
    пропускаются; файл — симлинк или не читается — пусто."""
    try:
        fd = os.open(os.path.join(P.STATE, "merge-gate", "carry.jsonl"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(rec, dict) and rec.get("pr") == pr and isinstance(rec.get("repo"), list) \
                    and repo.lower() in [str(x).lower() for x in rec["repo"]]:
                out.append(rec)
    return out


def review_decisions(repo, pr):
    """Решения шлюза guard о коде head PR repo#pr (metis-0966): записи kind "decision" (carry_records) по порядку
    записи. Их пишет только хук guard при `pantheon merge request` (merge_gate.request_decisions); записи без списков
    строк same и differs пропускаются."""
    return [r for r in carry_records(repo, pr) if r.get("kind") == "decision"
            and all(isinstance(r.get(k), list) and all(isinstance(x, str) for x in r[k]) for k in ("same", "differs"))]
