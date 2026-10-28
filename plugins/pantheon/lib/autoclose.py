"""Автозакрытие задач при слиянии их PR (metis-0308). Для всех направлений, без участия ролей.

Два прохода. fetch (`pantheon autoclose fetch`, отдельная задача расписания, с пределом времени FETCH_BUDGET на весь
проход) спрашивает gh про слитые и открытые PR репозиториев из [merge_repos] policy.toml и пишет кэш STATE/autoclose-prs.json.
run (лёгкий тик) читает только кэш, в сеть не ходит. Задачу (`<префикс>-NNNN`) закрывает только PR из репозитория её
направления, и только если её номер в имени ветки или после «Closes/Fixes» в теле: упоминание («См. также») не считается.
Слитый PR закрывает такую задачу: status done, closed —
день слияния, release — «PR #N → коммит» (версия плагина, если PR поднял plugin.json), actual — из учёта по задачам
(metrics/tasks.jsonl, metis-0294), нет замера — «нет замера»; в журнал задачи — строка с CLOSED_BY_MERGE.
В теле PR слово «часть» — PR закрывает только часть задачи: задача не закрывается.
Неотмеченные пункты «Готово, когда» (задачи с T.CRITERIA_FROM, metis-0503): слитый PR без «часть» ставит review и
строку «слит, неотмечено N», а не done — хвосты не теряются; закрыть — отметить пункты, `pantheon task split` или --force.
Открытый PR, который так же закрывает задачу (без «часть»), ставит задаче todo/doing её направления review — один раз
на PR (строка REVIEW_MARK в журнале).
Обработанные PR отмечены в STATE/autoclose.json; задачу, уже закрытую этим PR (строка в журнале), второй раз не трогаем. Заодно проход запоминает, у каких
задач есть открытый PR: без него «review больше суток» на доске — повод для внимания.

Модуль без обращения к pantheon.py: тесты зовут его напрямую.
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
PART_RE = re.compile(r"(?<!\w)часть(?!\w)", re.I)
FETCH_BUDGET = 240     # секунд на весь сетевой проход (fetch): дольше не ждём, остаток репозиториев — в следующий раз
FIRST_LOOKBACK = 48 * 3600  # первый проход (нет состояния) смотрит назад на столько: старые упоминания задач не трогаем
KEEP = 500             # отметок обработанных PR в состоянии
LIMIT = 100
NO_METRIC = "нет замера"
REVIEW_MARK = "открыт → review"  # строка журнала задачи, которой открытый PR поставил review (тот же текст в boardstatus.py)
VERSION_RE = re.compile(r'^\+\s*"version"\s*:\s*"([^"]+)"')
DIFF_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)")


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


def closing_ids(branch, body):
    """Номера задач, которые PR закрывает: id в имени ветки или «Closes/Fixes <id>» в теле. Простое упоминание
    («См. также», «зависит от», «часть») — нет."""
    body = body or ""
    return find_ids(branch, *[m.group(1) for m in CLOSE_RE.finditer(body) if not NEG_BEFORE_RE.search(body[:m.start()])])


def is_part(body):
    return bool(PART_RE.search(body or ""))


def gh_exe(env=None):
    """gh: PANTHEON_GH (тесты подставляют поддельный) или первый в PATH."""
    e = env if env is not None else os.environ
    return e.get("PANTHEON_GH") or shutil.which("gh", path=e.get("PATH"))


def gh_json(args, env=None, timeout=90):
    """→ (данные, ошибка). gh нет или он упал — (None, текст)."""
    exe = gh_exe(env)
    if not exe:
        return None, "gh не найден в PATH"
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh не запустился: {type(e).__name__}"
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or f"код {r.returncode}").strip()[:200]
    try:
        return json.loads(r.stdout or "null"), None
    except ValueError:
        return None, "gh вернул не JSON"


def gh_text(args, env=None, timeout=90):
    exe = gh_exe(env)
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def merged_day(iso):
    """'2026-10-19T21:05:00Z' → '2026-10-20' (день слияния по часам этого Mac). Не разобрать — None."""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.astimezone() if d.tzinfo else d).strftime("%Y-%m-%d")


def merged_ts(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else d.astimezone().timestamp()


def plugin_versions(diff_text):
    """Диф PR → {плагин: новая версия} по строкам `+ "version": …` в .claude-plugin/plugin.json."""
    out, cur = {}, None
    for ln in (diff_text or "").splitlines():
        m = DIFF_RE.match(ln)
        if m:
            parts = m.group(2).split("/")
            cur = parts[-3] if m.group(2).endswith(".claude-plugin/plugin.json") and len(parts) >= 3 else None
            continue
        if cur:
            v = VERSION_RE.match(ln)
            if v:
                out[cur] = v.group(1)
    return out


def release_text(repo, pr):
    """release закрытой задачи: «PR #N → коммит»; PR поднял plugin.json — версия плагина (её собрал проход fetch)."""
    n = pr.get("number")
    sha = (pr.get("oid") or "")[:7]
    base = f"PR #{n} → {sha}" if sha else f"PR #{n}"
    vers = pr.get("versions")
    if isinstance(vers, dict) and vers:
        return "; ".join(f"{k} {v}" for k, v in sorted(vers.items())) + f" ({base})"
    return base


def actual_text(row):
    """Строка учёта по задаче (metrics/tasks.jsonl) → «$1.23 · 450k токенов · 2.1 ч»; пусто или нули — «нет замера»."""
    if not isinstance(row, dict):
        return NO_METRIC
    usd, tok, hours = row.get("usd") or 0, row.get("tokens_total") or 0, row.get("hours")
    if not usd and not tok:
        return NO_METRIC
    parts = []
    if usd:
        parts.append(f"${usd:.2f}")
    if tok:
        parts.append(f"{tok / 1000:.0f}k токенов" if tok >= 1000 else f"{tok} токенов")
    if hours:
        parts.append(f"{hours} ч")
    return " · ".join(parts) + (" (оценка)" if row.get("estimate") else "")


def load_state(p):
    try:
        with open(p, encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(p, st):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def open_pr_tasks(state_file):
    """id задач с открытым PR по последнему проходу; нет состояния — None (неизвестно)."""
    st = load_state(state_file)
    return set(st["open"]) if isinstance(st.get("open"), list) else None


def fetch(cache_file, state_file, t, repos, env=None, budget=FETCH_BUDGET, core=None):
    """Сетевой проход: gh по репозиториям → кэш cache_file. Только он зовёт gh; лёгкий тик (run) читает кэш.
    budget — секунд на весь проход: на каждый вызов gh остаётся не больше, чем осталось; не успел — ошибка по репозиторию.
    core — путь → ядро ли (merge.is_core): открытые PR в кэше (open_prs) несут пометку «задето ядро» для автоблока
    board.md (metis-0397). → ошибки по репозиториям {repo: текст}."""
    end = time.monotonic() + budget

    def left():
        return end - time.monotonic()

    done = load_state(state_file).get("done")
    done = done if isinstance(done, dict) else {}
    merged, opened, open_prs, errors = {}, {}, {}, {}
    for repo in sorted(set(repos)):
        if left() <= 1:
            errors[repo] = "не хватило времени прохода"
            continue
        data, err = gh_json(["pr", "list", "--repo", repo, "--state", "merged", "--limit", str(LIMIT), "--json",
                             "number,headRefName,body,mergedAt,mergeCommit,files"], env, timeout=min(90, left()))
        if err or not isinstance(data, list):
            errors[repo] = err or "ответ gh — не список"
            continue
        rows = []
        for pr in data:
            if not isinstance(pr, dict):
                continue
            row = {"number": pr.get("number"), "headRefName": pr.get("headRefName") or "", "body": (pr.get("body") or "")[:4000],
                   "mergedAt": pr.get("mergedAt"), "oid": ((pr.get("mergeCommit") or {}).get("oid") or "")}
            files = [f.get("path", "") for f in pr.get("files") or [] if isinstance(f, dict)]
            if f"{repo}#{pr.get('number')}" not in done and any(x.endswith(".claude-plugin/plugin.json") for x in files):
                if left() <= 1:
                    errors[f"{repo}#{pr.get('number')}"] = "не хватило времени на diff"
                    continue  # без версии PR не отдаём: закрытие подождёт следующего прохода
                row["versions"] = plugin_versions(gh_text(["pr", "diff", str(pr.get("number")), "--repo", repo], env,
                                                          timeout=min(90, left())))
            rows.append(row)
        merged[repo] = rows
        if left() > 1:
            o, _ = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", str(LIMIT), "--json",
                            "number,headRefName,headRefOid,body,files"], env, timeout=min(90, left()))
            if isinstance(o, list):
                opened[repo] = sorted({i for p in o if isinstance(p, dict) for i in find_ids(p.get("headRefName"), p.get("body"))})
                open_prs[repo] = [{"number": p.get("number"), "head": str(p.get("headRefOid") or "")[:40],
                                   "ids": find_ids(p.get("headRefName"), p.get("body")),
                                   "closes": closing_ids(p.get("headRefName"), p.get("body")),
                                   "part": is_part(p.get("body")),
                                   "core": bool(core) and any(core(f.get("path") or "") for f in p.get("files") or []
                                                              if isinstance(f, dict))}
                                  for p in o if isinstance(p, dict) and isinstance(p.get("number"), int)]
    save_state(cache_file, {"fetched": t, "merged": merged, "open": opened, "open_prs": open_prs, "errors": errors})
    return errors


def journal_has(path, T, needle):
    return needle in (T.read(path)[1] or "")


def run(pantheon, state_file, cache_file, t, repo_dirs, T, actual_for=None):
    """Один проход по кэшу fetch, без сети. repo_dirs — {"владелец/репозиторий": {направления}}: задачу закрывает
    только PR из репозитория её направления. T — модуль tasks.py, actual_for(tid) → строка actual или None.
    → (строки журнала, ошибки). Тот же кэш второй раз не читается."""
    cache = load_state(cache_file)
    st = load_state(state_file)
    if cache.get("fetched") is None or st.get("seen") == cache.get("fetched"):
        return [], {}
    done = st.get("done") if isinstance(st.get("done"), dict) else {}
    since = float(st["since"]) if st.get("since") is not None else t - FIRST_LOOKBACK
    log, open_ids, finished = [], set(), False
    errors = dict(cache.get("errors") or {})
    merged = cache.get("merged") if isinstance(cache.get("merged"), dict) else {}
    try:
        for repo in sorted(repo_dirs):
            for pr in sorted(merged.get(repo) or [], key=lambda p: str(p.get("mergedAt") or "")):
                key = f"{repo}#{pr.get('number')}"
                ts = merged_ts(pr.get("mergedAt"))
                if key in done or ts is None or ts < since:
                    continue
                if close_pr(pantheon, t, repo, pr, repo_dirs[repo], T, actual_for, log, errors):
                    done[key] = T.now_iso(t)
            open_ids.update((cache.get("open") or {}).get(repo) or [])
        for repo in sorted(repo_dirs):
            for pr in (cache.get("open_prs") or {}).get(repo) or []:
                if isinstance(pr, dict):
                    review_pr(pantheon, t, repo, pr, repo_dirs[repo], T, log, errors)
        finished = True
    finally:  # сбой посреди прохода (не только ValueError): отметки уже обработанных PR не теряем, кэш прочтём заново
        keep = dict(sorted(done.items(), key=lambda kv: kv[1])[-KEEP:])
        st.update(done=keep, since=since, open=sorted(open_ids) if not errors else (st.get("open") or sorted(open_ids)))
        if finished:
            st["seen"] = cache.get("fetched")
        save_state(state_file, st)
    return log, errors


def review_pr(pantheon, t, repo, pr, dirs, T, log, errors):
    """Открытый PR, который закрывает задачу (id в ветке или «Closes» в теле, без «часть»), → задача todo/doing его
    направления в review (metis-0397, п. 7). Строка REVIEW_MARK в журнале: этим PR уже ставили — второй раз не трогаем
    (владелец вернул задачу — тревога у прохода доски, lib/boardstatus.py)."""
    n = pr.get("number")
    if not isinstance(n, int) or pr.get("part") or not isinstance(pr.get("closes"), list):
        return
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    note = f"PR #{n} ({repo}) {REVIEW_MARK}"
    for tid in pr["closes"]:
        if not isinstance(tid, str):
            continue
        path, head, _ = tasks.get(tid, ("", {}, ""))
        if head.get("type") != "task" or head.get("direction") not in dirs or head.get("status") not in ("todo", "doing"):
            continue
        if journal_has(path, T, note):
            continue
        try:
            T.task_set(pantheon, t, tid, {"status": "review"}, actor="плановый проход", note=note)
            log.append(f"{tid}: review — открыт PR #{n} ({repo})")
        except ValueError as e:
            errors[f"{repo}#{n}"] = f"{tid}: {e}"


def close_pr(pantheon, t, repo, pr, dirs, T, actual_for, log, errors):
    """Слитый PR → закрытие его задач. → True, если PR обработан целиком (можно отметить), False — повторить."""
    n = pr.get("number")
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    ids = [i for i in closing_ids(pr.get("headRefName"), pr.get("body")) if i in tasks
           and tasks[i][1].get("type") == "task" and tasks[i][1].get("direction") in dirs
           and tasks[i][1].get("status") in ("todo", "doing", "waiting", "review")]
    part = is_part(pr.get("body"))
    ok = True
    for tid in ids:
        head = tasks[tid][1]
        try:
            if part:
                note = f"PR #{n} ({repo}) слит, в теле «часть» — задача не закрыта"
                if not journal_has(tasks[tid][0], T, note):
                    T.task_set(pantheon, t, tid, {}, actor="плановый проход", note=note)
                    log.append(f"{tid}: PR #{n} слит, «часть» — не закрыта")
                continue
            left = T.unchecked_criteria(head, tasks[tid][2])
            if left:  # хвосты «Готово, когда» не теряем (metis-0503): слитый PR без «часть» — на проверку, не в done
                note = f"PR #{n} ({repo}) слит, неотмечено {left}"
                if head.get("status") != "review" or not journal_has(tasks[tid][0], T, note):
                    T.task_set(pantheon, t, tid, {"status": "review"}, actor="плановый проход", note=note)
                    log.append(f"{tid}: PR #{n} слит, неотмечено {left} — review")
                continue
            mark = f"PR #{n} ({repo}) →"
            if journal_has(tasks[tid][0], T, T.CLOSED_BY_MERGE + " " + mark):
                continue  # этим PR задачу уже закрывали; владелец вернул её в работу — второй раз не трогаем
            day = merged_day(pr.get("mergedAt")) or T.now_iso(t)[:10]
            changes = {"status": "done", "closed": day}
            if not head.get("release"):
                changes["release"] = release_text(repo, pr)
            T.task_set(pantheon, t, tid, changes, actor="плановый проход",
                       note=f"{T.CLOSED_BY_MERGE} {mark} {(pr.get('oid') or '')[:7]}, closed {day}")
            if not head.get("actual"):
                val = None
                try:
                    val = actual_for(tid) if actual_for else None
                except Exception:  # noqa: BLE001 — учёт не должен мешать закрытию
                    val = None
                T.task_set(pantheon, t, tid, {"actual": val or NO_METRIC}, actor="плановый проход")
            log.append(f"{tid}: закрыта по слиянию PR #{n} ({repo})")
        except ValueError as e:  # задача изменилась или шапка не прошла проверку — PR не отмечаем, повторим
            ok = False
            errors[f"{repo}#{n}"] = f"{tid}: {e}"
    return ok
