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
           "carry_records", "review_decisions", "criteria_accepted", "criteria_probes", "criteria_tasks",
           "criteria_required", "criteria_unmarked", "review_criteria_gap"]

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


# --- пункты «Готово, когда» в шлюзе слияния (metis-1004, metis-1260) ----------------------------------------------
# Правило, какие отметки argus --criteria засчитаны на head PR (criteria_accepted, criteria_probes), каким пунктам
# отметка нужна (criteria_required) и отказ `pantheon merge request` без них (review_criteria_gap, его зовёт
# merge.py) — здесь, в ядре: обычный PR в review.py ослаблял бы шлюз ядра (test_core_deps). Данные — вне ядра: карточки
# задач и разбор отметки (tasks.py, P.tasks_mod), какие задачи PR называет (autoclose.py: closing_ids, is_part,
# named_items) и направления репозитория (policy.toml) — исключения с причиной в test_core_deps.py.
_SHA = re.compile(r"[0-9a-f]{40}")


def criteria_accepted(recs, pr, head, base, core):
    """Пункты, которые argus принял на head слияния PR (metis-1004) → {id задачи: {номер пункта: хеш}}. recs — журнал
    шлюза по PR (review_records). В счёт — «принять» argus на этот PR и ровно этот head, как у шлюза: последний вердикт
    своего рецензента (пара session_id, agent_id), полный перечень, а у PR ядра (core) ещё Opus (review_accept_counts),
    base записи — base PR (base_counts), без лживого поля «вернули» (returned_lie), позже каждого «вернуть» PR, кроме
    снятого «принять» того же рецензента на том же head (как _floor шлюза). Последний вердикт какого-нибудь
    рецензента на head — «вернуть» — не в счёт ничего. Пункт принят, если в засчитанных «принять» он есть, у всех —
    «да» или «проба» (T.CRITERION_OK, metis-1260) и один хеш. Переносов «принять» с прошлого head нет: запись другого
    head не отмечает ничего."""
    return {tid: {n: h for n, (h, _) in items.items()} for tid, items in _criteria_ok(recs, pr, head, base, core).items()}


def criteria_probes(recs, pr, head, base, core):
    """Принятые пункты (как criteria_accepted), у которых хоть одна засчитанная отметка — «проба» (metis-1260) →
    {id задачи: {номер: (хеш, опоры проб через «; »)}}: их проверяют вживую после выпуска (autoclose.ensure_probe)."""
    out = {}
    for tid, items in _criteria_ok(recs, pr, head, base, core).items():
        got = {n: (h, "; ".join(bases)) for n, (h, bases) in items.items() if bases}
        if got:
            out[tid] = got
    return out


def _criteria_ok(recs, pr, head, base, core):
    """Общее у criteria_accepted и criteria_probes → {id: {номер: (хеш, [опоры отметок «проба»])}}."""
    T = P.tasks_mod()
    out = {}
    for (tid, n), vs in sorted(_criteria_votes(recs, pr, head, base, core, T).items()):
        if all(v in T.CRITERION_OK for _, v, _ in vs) and len({h for h, _, _ in vs}) == 1:
            probes = list(dict.fromkeys(b for _, v, b in vs if v == T.CRITERION_PROBE))
            out.setdefault(tid, {})[n] = (vs[0][0], probes)
    return out


def _criteria_votes(recs, pr, head, base, core, T):
    """Отметки засчитанных «принять» на head (правило — criteria_accepted) → {(id, номер): [(хеш, отметка, опора)]}."""
    rules, full = P.merge_mod(), review_accept_full
    ok = review_accept_counts if core else full
    head = str(head or "").lower()
    if not _SHA.fullmatch(head):
        return {}
    verdicts = [r for r in recs if r.get("kind") in ("accept", "reject") and r.get("pr") == pr
                and isinstance(r.get("by"), dict) and r["by"].get("agent_type") == "argus"
                and isinstance(r.get("sha"), str)]

    def who(r):
        return (r["by"].get("session_id") or "", r["by"].get("agent_id") or "")

    floor = -1
    for i, r in enumerate(verdicts):
        if r["kind"] == "reject" and not any(a["kind"] == "accept" and who(a) == who(r) and a["sha"].lower() ==
                                             r["sha"].lower() and full(a) for a in verdicts[i + 1:]):
            floor = i
    last = {}
    for i, r in enumerate(verdicts):
        if r["sha"].lower() == head:
            last[who(r)] = (i, r)
    if any(r["kind"] == "reject" for _, r in last.values()):
        return {}
    votes = {}
    for i, r in sorted(last.values(), key=lambda x: x[0]):
        if i <= floor or not ok(r) or not rules.base_counts(r, {"baseRefName": base}) or rules.returned_lie(r, verdicts):
            continue
        for v in r.get("criteria") if isinstance(r.get("criteria"), list) else []:
            got = T.parse_criterion(v)
            if got:
                votes.setdefault((got[0], got[1]), []).append((got[2], got[3], got[4]))
    return votes


def criteria_tasks():
    """(модуль tasks, задачи WORK_TYPES) — общее у criteria_required и review._accept_unmarked: задачи читаются один раз."""
    T = P.tasks_mod()
    return T, T.load_tasks(P.PANTHEON, T.WORK_TYPES)


def criteria_required(repo, branch, body, loaded=None):
    """Пункты, которым нужна отметка argus в «принять» PR (metis-1260) → {id: {номер: хеш нынешнего текста}}:
    неотмеченные пункты открытых задач из Closes и ветки (autoclose.closing_ids; у PR «часть» — нет) и пункты «пункт N
    <id>» тела (named_items). Задача — направления репозитория PR ([merge_repos] policy.toml, как у autoclose: чужую
    задачу PR не закрывает); политика не читается или репозитория в ней нет — любого (строже). loaded — criteria_tasks()."""
    (T, tasks), A = loaded or criteria_tasks(), P.autoclose_mod()
    try:
        dirs = P.autoclose_repo_dirs().get(repo.lower())
    except Exception:  # noqa: BLE001 — policy.toml не прочитан: строже, задачи любого направления
        dirs = None
    want = {} if A.is_part(body) else {tid: None for tid in A.closing_ids(branch, body)}
    for tid, nums in A.named_items(body).items():
        want[tid] = nums if want.get(tid, ()) is not None else None
    out = {}
    for tid, nums in want.items():
        _, head, text = tasks.get(tid, ("", {}, ""))
        if head.get("type") != "task" or head.get("status") in ("done", "dropped") \
                or (dirs is not None and head.get("direction") not in dirs):
            continue
        crit = T.done_criteria(text)
        got = {n: T.criterion_hash(crit[n - 1][1]) for n in T.unchecked_numbers(head, text) if nums is None or n in nums}
        if got:
            out[tid] = got
    return out


def criteria_unmarked(need, have):
    """Пункты need ({id: {номер: хеш}}) без отметки «да»/«проба» с тем же хешем в have → «id#N, …» или None."""
    miss = [f"{tid}#{n}" for tid, items in sorted(need.items()) for n, h in sorted(items.items())
            if (have.get(tid) or {}).get(n) != h]
    return ", ".join(miss) or None


def review_criteria_gap(repo, pr, sha, view):
    """Для `pantheon merge request` (metis-1260): у пунктов задач PR (criteria_required по телу и ветке view) нет
    отметки «да»/«проба» в засчитанных «принять» на head sha (criteria_accepted, хеш — нынешнего текста) → ("fail",
    причина) или None. Ядро — по файлам PR (window_core), файлы не получить — как ядро (строже)."""
    need = criteria_required(repo, view.get("headRefName") or "", view.get("body") or "")
    if not need:
        return None
    M = P.merge_mod()
    files = M.pr_files(repo, pr, view)
    core = files is None or any(M.window_core(f) for f in files)
    miss = criteria_unmarked(need, criteria_accepted(review_records(repo, pr), pr, sha, view.get("baseRefName"), core))
    return miss and ("fail", f"у пунктов «Готово, когда» {miss} нет отметки argus да|проба на head {sha[:12]} "
                             "(metis-1260) — нужен круг argus с --criteria на каждый")
