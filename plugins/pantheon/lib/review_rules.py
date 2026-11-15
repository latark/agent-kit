"""Пантеон: правило засчитывания вердиктов argus — ядро защит (Д3, metis-0858).

Одно правило для шлюза владельца (merge.gate, слияние PR ядра по Touch ID) и итога `pantheon review status`
(review_tally), чтобы они не разошлись (metis-0393). Раньше оно жило в lib/review.py, а тот не ядро: обычный PR в
review.py ослаблял бы шлюз ядра. Теперь файл в CORE_FILES шлюза guard, копии правила в review.py нет — это сверяет
plugins/guard/tests/test_core_deps.py.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла, имена из __all__ становятся
именами pantheon (P.review_records, P.review_accept_counts). Пути — через P в момент вызова, а не копией при
загрузке: merge.clean_env и тесты подменяют P.STATE.

Ещё здесь (metis-1260, решение владельца 15.11): правило отметок «Готово, когда» в шлюзе merge request, разбор
тела и ветки PR (Closes, «часть», «пункт N <id>») и какие отметки засчитаны (CRITERION_OK). autoclose.py и
tasks.py грузят этот файл по пути рядом и берут их отсюда — без P: разбор и константы P не трогают. Функции
merge.py (base_counts, returned_lie, pr_files, window_core, repo_dirs) правило получает параметром M.
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


# --- разбор тела и ветки PR: какие задачи PR закрывает (metis-0308, 0583, 1193; ядро — metis-1260) -----------------
ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
# «часть» — только отдельным словом рядом с номером задачи: «часть metis-1051», «часть 1051», «часть задачи metis-1051»,
# «часть: metis-1051» (metis-1193). Номер — id с префиксом или цифры после № / # / «задачи» («часть №1051», «часть
# задачи 1051»); голое число («часть 100 строк», «часть 2026 года») — не номер. Между словом и номером — пробелы, знаки
# разметки (* _ ` ( [ # №, двоеточие, тире) и перед id не больше одного слова («часть работы metis-1051»). Слово в
# обычной фразе («личная часть карты», #441) PR частичным не делает.
_PART_GAP = r"[\s*_`(\[#№:—–-]*"
_PART_NUM = r"(?:[#№]|задачи" + _PART_GAP + r")\s*\d{3,}(?!\w)"
PART_RE = re.compile(r"(?<![^\W_])часть(?![^\W_])" + _PART_GAP + r"(?:(?:[^\W\d_]+" + _PART_GAP + r")?" + ID_RE.pattern
                     + r"|" + _PART_NUM + r")", re.I)


def find_ids(*texts):
    """Номера задач в порядке появления, без повторов."""
    out = []
    for text in texts:
        for m in ID_RE.finditer(text or ""):
            if m.group(0) not in out:
                out.append(m.group(0))
    return out


CLOSE_RE = re.compile(r"(?<!\w)(?i:close[sd]?|fix(?:es|ed)?|resolve[sd]?|закрыва(?:ет|ю)|закры(?:л|ла|ли|то)|исправля(?:ет|ю)|исправил[аи]?)"
                      r"\s*[:\-]?\s+(" + ID_RE.pattern + ")")
# перед глаголом отрицание («не закрывает», «пока не закрываю», «doesn't fix», «not closing») — PR задачу не закрывает
NEG_BEFORE_RE = re.compile(r"(?:(?<!\w)(?:не|нет|not|never|no)|n['’]t)\s+(?:\w+\s+)?$", re.I)


# после «Closes <id>» — список (metis-0583): «, <id>», «и <id>», «and <id>», «; <id>», «& <id>». Номер без префикса
# («Closes metis-0522, 0534 и 0535») берёт префикс прошлого id, если в нём столько же цифр и за ним конец, знак или «и»
LIST_NEXT_RE = re.compile(r"\s*(?:,|;|&|\s(?:и|and)(?=\s))\s*(?:(" + ID_RE.pattern + r")|(?<![\w-])(\d{3,})(?=$|[\s,;.()&]))", re.I)
BARE_END_RE = re.compile(r"\s*(?:$|[,;.()&—–-]|(?:и|and)\s)", re.I)


def _id_list(text, pos, first):
    """Номера после первого id списка «Closes a-1, a-2 и 0003» → [a-2, a-0003]; pos — конец первого id."""
    out, prev = [], first
    while True:
        m = LIST_NEXT_RE.match(text, pos)
        if not m:
            return out
        if m.group(1):
            prev = m.group(1)
        else:
            pre, num = prev.rsplit("-", 1)
            if len(m.group(2)) != len(num) or not BARE_END_RE.match(text, m.end()):
                return out  # «Closes metis-0522, 100 тестов» — число, а не номер задачи
            prev = f"{pre}-{m.group(2)}"
        out.append(prev)
        pos = m.end()


def closing_ids(branch, body):
    """Номера задач, которые PR закрывает: id в имени ветки или «Closes/Fixes <id>» в теле, со списком после него
    («Closes metis-0522, metis-0534 и 0535» — все три, metis-0583). Простое упоминание («См. также», «зависит от»,
    «часть») — нет."""
    body = body or ""
    ids = []
    for m in CLOSE_RE.finditer(body):
        if not NEG_BEFORE_RE.search(body[:m.start()]):
            ids += [m.group(1)] + _id_list(body, m.end(1), m.group(1))
    return find_ids(branch, *ids)


def is_part(body):
    return bool(PART_RE.search(body or ""))


# metis-1193: пункт задачи X, сделанный PR другой задачи (или проверяемый фактом после слияния — его принимают на
# следующем PR), argus принимает тем же --criteria на этом PR, а тело PR называет его: «пункт 3 metis-1050», «пункты
# 1, 2 и 4 metis-1117», «пункты 1, 2, и 4 metis-1117», «пункт 3 задачи metis-1050». Не «часть metis-X»: «часть» в теле оставляет открытыми и задачи из Closes (is_part).
ITEM_RE = re.compile(r"(?<!\w)пункт(?:ы|ов|ах)?\s+(\d{1,3}(?:\s*(?:,\s*и|,|и)\s*\d{1,3})*)\s+(?:задачи\s+)?("
                     + ID_RE.pattern + r")", re.I)


def named_items(body):
    """Пункты чужих задач, названные в теле PR (metis-1193) → {id: {номера}}."""
    out = {}
    for m in ITEM_RE.finditer(body or ""):
        out.setdefault(m.group(2), set()).update(int(x) for x in re.findall(r"\d+", m.group(1)))
    return out


# --- пункты «Готово, когда» в шлюзе слияния (metis-1004, metis-1260) ----------------------------------------------
# «да» и «проба» засчитаны, «нет» — нет (metis-1260); «проба» ещё даёт задачу-пробу после выпуска
CRITERION_PROBE, CRITERION_OK = "проба", ("да", "проба")
# Правило, какие отметки argus --criteria засчитаны на head PR (criteria_accepted, criteria_probes), каким пунктам
# отметка нужна (criteria_required) и отказ `pantheon merge request` без них (review_criteria_gap, его зовёт
# merge.py) — здесь, в ядре: обычный PR в review.py ослаблял бы шлюз ядра (test_core_deps). Вне ядра — только данные
# карточек задач и разбор значения --criteria (tasks.py через P.tasks_mod); направления репозитория из policy.toml даёт
# вызывающий (merge.repo_dirs через M или autoclose_repo_dirs в review.py) параметром dirs.
_SHA = re.compile(r"[0-9a-f]{40}")


def criteria_accepted(recs, pr, head, base, core, M):
    """Пункты, которые argus принял на head слияния PR (metis-1004) → {id задачи: {номер пункта: хеш}}. recs — журнал
    шлюза по PR (review_records). В счёт — «принять» argus на этот PR и ровно этот head, как у шлюза: последний вердикт
    своего рецензента (пара session_id, agent_id), полный перечень, а у PR ядра (core) ещё Opus (review_accept_counts),
    base записи — base PR (base_counts), без лживого поля «вернули» (returned_lie), позже каждого «вернуть» PR, кроме
    снятого «принять» того же рецензента на том же head (как _floor шлюза). Последний вердикт какого-нибудь
    рецензента на head — «вернуть» — не в счёт ничего. Пункт принят, если в засчитанных «принять» он есть, у всех —
    «да» или «проба» (T.CRITERION_OK, metis-1260) и один хеш. Переносов «принять» с прошлого head нет: запись другого
    head не отмечает ничего. M — модуль merge или его функции (base_counts, returned_lie): ядро берёт их параметром."""
    return {tid: {n: h for n, (h, _) in items.items()} for tid, items in _criteria_ok(recs, pr, head, base, core, M).items()}


def criteria_probes(recs, pr, head, base, core, M):
    """Принятые пункты (как criteria_accepted), у которых хоть одна засчитанная отметка — «проба» (metis-1260) →
    {id задачи: {номер: (хеш, опоры проб через «; »)}}: их проверяют вживую после выпуска (autoclose.ensure_probe)."""
    out = {}
    for tid, items in _criteria_ok(recs, pr, head, base, core, M).items():
        got = {n: (h, "; ".join(bases)) for n, (h, bases) in items.items() if bases}
        if got:
            out[tid] = got
    return out


def _criteria_ok(recs, pr, head, base, core, M):
    """Общее у criteria_accepted и criteria_probes → {id: {номер: (хеш, [опоры отметок «проба»])}}."""
    T = P.tasks_mod()
    out = {}
    for (tid, n), vs in sorted(_criteria_votes(recs, pr, head, base, core, T, M).items()):
        if all(v in CRITERION_OK for _, v, _ in vs) and len({h for h, _, _ in vs}) == 1:
            probes = list(dict.fromkeys(b for _, v, b in vs if v == CRITERION_PROBE))
            out.setdefault(tid, {})[n] = (vs[0][0], probes)
    return out


def _criteria_votes(recs, pr, head, base, core, T, M):
    """Отметки засчитанных «принять» на head (правило — criteria_accepted) → {(id, номер): [(хеш, отметка, опора)]}."""
    rules, full = M, review_accept_full
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


def criteria_required(repo, branch, body, dirs, loaded=None):
    """Пункты, которым нужна отметка argus в «принять» PR (metis-1260) → {id: {номер: хеш нынешнего текста}}:
    неотмеченные пункты открытых задач из Closes и ветки (autoclose.closing_ids; у PR «часть» — нет) и пункты «пункт N
    <id>» тела (named_items). Задача — направления репозитория PR из dirs ({направления} по [merge_repos] policy.toml,
    как у autoclose: чужую задачу PR не закрывает); dirs None — политика не читается или репозитория в ней нет — любого
    (строже). loaded — criteria_tasks()."""
    T, tasks = loaded or criteria_tasks()
    want = {} if is_part(body) else {tid: None for tid in closing_ids(branch, body)}
    for tid, nums in named_items(body).items():
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


def review_criteria_gap(repo, pr, sha, view, M):
    """Для `pantheon merge request` (metis-1260): у пунктов задач PR (criteria_required по телу и ветке view) нет
    отметки «да»/«проба» в засчитанных «принять» на head sha (criteria_accepted, хеш — нынешнего текста) → ("fail",
    причина) или None. Ядро — по файлам PR (window_core), файлы не получить — как ядро (строже). M — функции merge.py
    (base_counts, returned_lie, pr_files, window_core, repo_dirs): зовёт merge.py, файл ядра."""
    try:
        dirs = M.repo_dirs().get(repo.lower())
    except Exception:  # noqa: BLE001 — policy.toml не прочитан: строже, задачи любого направления
        dirs = None
    need = criteria_required(repo, view.get("headRefName") or "", view.get("body") or "", dirs)
    if not need:
        return None
    files = M.pr_files(repo, pr, view)
    core = files is None or any(M.window_core(f) for f in files)
    miss = criteria_unmarked(need, criteria_accepted(review_records(repo, pr), pr, sha, view.get("baseRefName"), core, M))
    return miss and ("fail", f"у пунктов «Готово, когда» {miss} нет отметки argus да|проба на head {sha[:12]} "
                             "(metis-1260) — нужен круг argus с --criteria на каждый")
