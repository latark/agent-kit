"""Автозакрытие задач при слиянии их PR (metis-0308). Для всех направлений, без участия ролей.

Плановый проход раз в MIN_GAP секунд спрашивает `gh pr list --state merged` по репозиториям из [merge_repos] policy.toml. Номер
задачи (`<префикс>-NNNN`) берётся из имени ветки и тела PR. Слитый PR закрывает такую задачу: status done, closed —
день слияния, release — «PR #N → коммит» (версия плагина, если PR поднял plugin.json), actual — из учёта по задачам
(metrics/tasks.jsonl, metis-0294), нет замера — «нет замера»; в журнал задачи — строка с CLOSED_BY_MERGE.
В теле PR слово «часть» — PR закрывает только часть задачи: задача не закрывается.
Обработанные PR отмечены в STATE/autoclose.json, повторный проход их не трогает. Заодно проход запоминает, у каких
задач есть открытый PR: без него «review больше суток» на доске — повод для внимания.

Модуль без tomllib и без обращения к pantheon.py: работает и на системном Python 3.9, тесты зовут его напрямую.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
PART_RE = re.compile(r"(?<!\w)часть(?!\w)", re.I)
MIN_GAP = 600          # не чаще раза в 10 минут: плановый проход бывает раз в 5, а gh ходит в сеть
FIRST_LOOKBACK = 48 * 3600  # первый проход (нет состояния) смотрит назад на столько: старые упоминания задач не трогаем
KEEP = 500             # отметок обработанных PR в состоянии
LIMIT = 100
NO_METRIC = "нет замера"
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


def release_text(repo, pr, env=None):
    n = pr.get("number")
    sha = ((pr.get("mergeCommit") or {}).get("oid") or "")[:7]
    base = f"PR #{n} → {sha}" if sha else f"PR #{n}"
    files = [f.get("path", "") for f in pr.get("files") or [] if isinstance(f, dict)]
    if any(p.endswith(".claude-plugin/plugin.json") for p in files):
        vers = plugin_versions(gh_text(["pr", "diff", str(n), "--repo", repo], env))
        if vers:
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


def run(pantheon, state_file, t, repos, T, env=None, actual_for=None, force=False):
    """Один проход. repos — ["владелец/репозиторий"], T — модуль tasks.py, actual_for(tid) → строка actual или None
    (вызывается после закрытия задачи: учёт пишет строку по закрытой). → (строки журнала, ошибки по репозиториям)."""
    st = load_state(state_file)
    if not force and st.get("last") and 0 <= t - float(st["last"]) < MIN_GAP:
        return [], {}
    done = st.get("done") if isinstance(st.get("done"), dict) else {}
    since = float(st["since"]) if st.get("since") is not None else t - FIRST_LOOKBACK
    log, errors, open_ids = [], {}, set()
    for repo in sorted(set(repos)):
        data, err = gh_json(["pr", "list", "--repo", repo, "--state", "merged", "--limit", str(LIMIT), "--json",
                             "number,title,headRefName,body,mergedAt,mergeCommit,files"], env)
        if err or not isinstance(data, list):
            errors[repo] = err or "ответ gh — не список"
            continue
        for pr in sorted(data, key=lambda p: str(p.get("mergedAt") or "")):
            key = f"{repo}#{pr.get('number')}"
            ts = merged_ts(pr.get("mergedAt"))
            if key in done or ts is None or ts < since:
                continue
            ok = True
            tasks = T.load_tasks(pantheon, T.WORK_TYPES)
            ids = [i for i in find_ids(pr.get("headRefName"), pr.get("body")) if i in tasks
                   and tasks[i][1].get("type") == "task" and tasks[i][1].get("status") in ("todo", "doing", "waiting", "review")]
            part = is_part(pr.get("body"))
            for tid in ids:
                try:
                    if part:
                        T.task_set(pantheon, t, tid, {}, actor="плановый проход",
                                   note=f"PR #{pr['number']} ({repo}) слит, в теле «часть» — задача не закрыта")
                        log.append(f"{tid}: PR #{pr['number']} слит, «часть» — не закрыта")
                        continue
                    head = tasks[tid][1]
                    day = merged_day(pr.get("mergedAt")) or T.now_iso(t)[:10]
                    changes = {"status": "done", "closed": day}
                    if not head.get("release"):
                        changes["release"] = release_text(repo, pr, env)
                    T.task_set(pantheon, t, tid, changes, actor="плановый проход",
                               note=f"{T.CLOSED_BY_MERGE} PR #{pr['number']} ({repo}) → "
                                    f"{((pr.get('mergeCommit') or {}).get('oid') or '')[:7]}, closed {day}")
                    if not head.get("actual"):
                        val = None
                        try:
                            val = actual_for(tid) if actual_for else None
                        except Exception:  # noqa: BLE001 — учёт не должен мешать закрытию
                            val = None
                        T.task_set(pantheon, t, tid, {"actual": val or NO_METRIC}, actor="плановый проход")
                    log.append(f"{tid}: закрыта по слиянию PR #{pr['number']} ({repo})")
                except ValueError as e:  # задача изменилась или шапка не прошла проверку — PR не отмечаем, повторим
                    ok = False
                    errors[f"{repo}#{pr.get('number')}"] = f"{tid}: {e}"
            if ok:
                done[key] = T.now_iso(t)
        opened, err = gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", str(LIMIT), "--json",
                               "number,headRefName,body"], env)
        if isinstance(opened, list):
            for pr in opened:
                open_ids.update(find_ids(pr.get("headRefName"), pr.get("body")))
    keep = dict(sorted(done.items(), key=lambda kv: kv[1])[-KEEP:])
    st.update(done=keep, last=t, since=since, open=sorted(open_ids) if not errors else (st.get("open") or sorted(open_ids)))
    save_state(state_file, st)
    return log, errors
