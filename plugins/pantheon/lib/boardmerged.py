"""Задачи, у которых PR уже слит, а они не закрыты (metis-0768): строки сводки board-auto.md.

Новых запросов к gh нет: PR берутся из кэша `pantheon autoclose fetch` (STATE/autoclose-prs.json, ключ merged) и из
журнала карточки («PR #N»); связь задачи с PR — как в autoclose.close_checked (номер из журнала, репозиторий её
направления) плюс «Closes» в теле PR (autoclose.closing_ids). Задача doing/review, слитый PR старше суток, у PR нет
«часть» в теле, открытого PR задачи нет → (id, номер, дней, статус, неотмечено пунктов «Готово, когда», их номера).
Номера (metis-1193) — чтобы по строке сводки было видно, какие пункты ждут приёмки argus: на PR другой задачи с
«пункт N <id>» в теле (autoclose.tick_named) или отметки при закрытии задачи.

merged_stuck (metis-1255) — задачи review, висящие дольше STUCK_DAYS суток после слияния PR (связь только по Closes,
ветке или строке autoclose в журнале), для тревоги pantheon check (хвост «сверка»):
сводка board-auto.md показывает только 5 строк и не будит, а такая задача неделями ждёт пунктов «Готово, когда».

Модули tasks (T) и autoclose (A) передаёт вызывающий: файл сам их не грузит.
"""
import re

DAY = 86400
MIN_DAYS = 1  # слит минимум столько полных суток назад — иначе тик autoclose ещё сам закроет


def _in_direction(f, direction, repo_dirs):
    """PR f = (время, репозиторий, PR) из репозитория направления задачи; без repo_dirs — любой."""
    return not repo_dirs or direction in repo_dirs.get(f[1], ())


def merged_open(tasks, cache, t, T, A, repo_dirs=None, open_ids=()):
    """tasks — T.load_tasks, cache — содержимое autoclose-prs.json, t — «сейчас». repo_dirs — {репозиторий: {направления}}
    (пусто или None — без привязки к направлению). open_ids — задачи с открытым PR (работа ещё идёт). → список
    (id, номер PR, дней, статус, неотмечено, номера неотмеченных), самые давние слияния первыми."""
    merged = cache.get("merged") if isinstance(cache, dict) and isinstance(cache.get("merged"), dict) else {}
    by_num, by_close = {}, {}  # номер → [(время слияния, репо, PR)]; задача → то же по «Closes»
    for repo, rows in sorted(merged.items()):
        for pr in rows if isinstance(rows, list) else []:
            if not isinstance(pr, dict) or not isinstance(pr.get("number"), int) or isinstance(pr.get("number"), bool):
                continue
            if any(not isinstance(pr.get(k), (str, type(None))) for k in ("body", "headRefName")) or A.is_part(pr.get("body")):
                continue
            ts = A.merged_ts(pr.get("mergedAt"))
            if ts is None:
                continue
            by_num.setdefault(pr["number"], []).append((ts, repo, pr))
            for tid in A.closing_ids(pr.get("headRefName"), pr.get("body")):
                by_close.setdefault(tid, []).append((ts, repo, pr))
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in ("doing", "review") or tid in open_ids:
            continue
        d = head.get("direction")
        found = [f for f in by_close.get(tid, []) if _in_direction(f, d, repo_dirs)]
        for x in T._journal(body):
            for n in A.JOURNAL_PR_RE.findall(x[2]):
                found += [f for f in by_num.get(int(n), []) if _in_direction(f, d, repo_dirs)]
        found = [f for f in found if f[0] <= t]
        if not found:
            continue
        ts, _, pr = max(found, key=lambda f: (f[0], f[1], f[2]["number"]))
        days = int((t - ts) // DAY)
        if days >= MIN_DAYS:
            out.append((tid, pr["number"], days, head["status"], T.unchecked_criteria(head, body),
                        tuple(T.unchecked_numbers(head, body))))
    return sorted(out, key=lambda r: (-r[2], r[0]))


STUCK_DAYS = 3  # metis-1255: задача висит после слияния столько суток — тревога (хвост «сверка»)
NOTE_RE = re.compile(r"PR #(\d+) \([^)]*\) слит, неотмечено \d+")  # строка autoclose.close_pr при неотмеченных пунктах
ITEM_TEXT = 60


def merged_stuck(tasks, cache, t, T, A, repo_dirs=None, open_ids=(), days=STUCK_DAYS):
    """Задачи review с неотмеченными пунктами «Готово, когда», чей PR слит больше days суток назад (metis-1255), →
    [(id, ключ, «<id>: текст»)] для хвоста «сверка» pantheon check. Связь с PR — только надёжная: id задачи в Closes или
    в ветке слитого PR из репозитория её направления (кэш fetch, A.closing_ids, без «часть») или строка autoclose «PR #N
    (…) слит, неотмечено K» в журнале — она переживает выход PR из кэша (в нём последние 100 слитых). Простое упоминание
    PR в журнале («числа в теле PR 70/70») не связь: merged_open его берёт для сводки, а тревога по нему была бы ложной.
    Возраст — от самого свежего такого слияния. Ключ — id задачи: один на задачу, пока она висит, смена PR его не
    меняет. Задачи до CRITERIA_FROM (пункты не считаются) и doing не берутся. Текст называет неотмеченные пункты."""
    merged = cache.get("merged") if isinstance(cache, dict) and isinstance(cache.get("merged"), dict) else {}
    by_close = {}  # задача → [(время слияния, номер PR)] по Closes и ветке
    for repo, rows in sorted(merged.items()):
        for pr in rows if isinstance(rows, list) else []:
            if not isinstance(pr, dict) or not isinstance(pr.get("number"), int) or isinstance(pr.get("number"), bool):
                continue
            if any(not isinstance(pr.get(k), (str, type(None))) for k in ("body", "headRefName")) or A.is_part(pr.get("body")):
                continue
            ts = A.merged_ts(pr.get("mergedAt"))
            for tid in A.closing_ids(pr.get("headRefName"), pr.get("body")) if ts is not None else []:
                d = (tasks.get(tid) or (None, {}, ""))[1].get("direction")
                if _in_direction((ts, repo), d, repo_dirs):
                    by_close.setdefault(tid, []).append((ts, pr["number"]))
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") != "review" or tid in open_ids:
            continue
        nums = T.unchecked_numbers(head, body)
        found = [f for f in by_close.get(tid, []) if f[0] <= t]
        found += [(x[0], int(m.group(1))) for x in T._journal(body) if x[0] is not None and (m := NOTE_RE.search(x[2]))]
        if not nums or not found or t - max(found)[0] < days * DAY:
            continue
        ts, n = max(found)
        crit = T.done_criteria(body)
        items = ", ".join(f"п.{i} «{' '.join(crit[i - 1][1].split())[:ITEM_TEXT]}»" for i in nums)
        out.append((tid, tid, f"{tid}: PR #{n} слит {int((t - ts) // DAY)} сут назад, неотмечено {len(nums)}: {items}"))
    return out
