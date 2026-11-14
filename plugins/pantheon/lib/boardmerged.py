"""Задачи, у которых PR уже слит, а они не закрыты (metis-0768): строки сводки board-auto.md.

Новых запросов к gh нет: PR берутся из кэша `pantheon autoclose fetch` (STATE/autoclose-prs.json, ключ merged) и из
журнала карточки («PR #N»); связь задачи с PR — как в autoclose.close_checked (номер из журнала, репозиторий её
направления) плюс «Closes» в теле PR (autoclose.closing_ids). Задача doing/review, слитый PR старше суток, у PR нет
«часть» в теле, открытого PR задачи нет → (id, номер, дней, статус, неотмечено пунктов «Готово, когда», их номера).
Номера (metis-1193) — чтобы по строке сводки было видно, какие пункты ждут приёмки argus: на PR другой задачи с
«пункт N <id>» в теле (autoclose.tick_named) или отметки при закрытии задачи.

Модули tasks (T) и autoclose (A) передаёт вызывающий: файл сам их не грузит.
"""
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
