"""Замер «как сейчас» (ORD-06) и тот же замер через 4 недели работы системы (ORD-07, пересмотр R-rollback).

По git и локальным транскриптам Claude Code, без нового прогона и без текста переписки в отчёте: по каждому
направлению из ~/ai/pantheon/directions.toml и по неделям.

Запуск: python3 -I baseline.py [--end ГГГГ-ММ-ДД] [--weeks 4] [--out файл.md] [--note "почему этот период"]
  --end   первый день ПОСЛЕ периода (по умолчанию сегодня); недели — по 7 дней назад от него

Замер до запуска (решено 14.10): неделя 07.10–13.10 — `--end 2026-10-14 --weeks 1`. Через 4 недели работы системы
(R-rollback): `--end <system_start + 28 дней> --weeks 4`; сравнивать «в неделю» с неделей замера, остальное — на задачу.

Правила подсчёта (одни и те же для замера до запуска и после; меняются только вместе с решением в журнале):
  Разговор      — один основной транскрипт ~/.claude/projects/*/<id>.jsonl, начатый вами (entrypoint не sdk-*).
                  sdk-py и sdk-cli — автоматические прогоны (legal-watch, бот, claude -p): в задачи не входят,
                  их цена — отдельной колонкой.
  Направление   — по папке запуска (cwd первой записи) против folders в directions.toml; старые пути до переезда
                  14.10 (~/knowledge, ~/pantheon) и ~/projects/expert-corpus-data — к своим направлениям.
  Ваше сообщение — запись type=user с текстом от вас: не результат инструмента, не служебная вставка
                  (<command-…>, <local-command-…>, <task-notification>, «Caveat:», прерывание).
  Задача доведена до конца — разговор с хотя бы одним своим коммитом в репозитории направления; направление
                  задачи — по репозиторию коммита, а не по папке запуска (разговор из alexbroker, закоммитивший
                  в legal-watch, — задача themis-sources); неделя — по последнему коммиту.
  Коммит разговора — по вызову `git commit` в разговоре: папка из `git -C` или последнего `cd`, иначе папка
                  разговора; коммит этого репозитория с временем между вызовом и ответом (±5 с). Хеш из ответа
                  ([ветка abc1234]) тоже засчитывается.
  В активную неделю — доведённые задачи на неделю, в которой у направления был хоть один ваш разговор: тихие
                  недели темп не размывают.
  Разговор без коммита — исследование, документы, обсуждение: отдельная колонка, в «доведено» не входит.
  Сообщений на задачу — ваши сообщения в доведённых разговорах (медиана и среднее).
  Возврат на переделку — коммит-исправление (тип fix, hotfix или revert в начале сообщения; «исправ», «почин»,
                  «откат» в любом месте) в течение 7 дней после задачи, задевающий её файлы, из другого
                  разговора или без разговора.
  Поправки      — ваши сообщения в доведённом разговоре со словами «не так», «не то», «не работает», «переделай»,
                  «опять», «верни», «сломал», «ошибка», «неправильно» (второй признак переделки).
  Цена задачи   — эквивалент цен API (usage.py) всех ваших разговоров направления за период, с их субагентами,
                  делённая на доведённые задачи; цена разговора с задачами в нескольких направлениях — поровну
                  между ними, без задач — направлению по папке запуска.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from usage import cost, family  # noqa: E402  цены — одна таблица на оба скрипта

HOME = os.path.expanduser("~")
PANTHEON = os.environ.get("PANTHEON_HOME", os.path.join(HOME, "ai", "pantheon"))
PROJECTS = os.environ.get("BASELINE_TRANSCRIPTS", os.path.join(HOME, ".claude", "projects"))
ALIASES = {"~/knowledge": "mnemo-brain", "~/pantheon": "metis-pantheon",
           "~/projects/expert-corpus-data": "themis-sources"}
SERVICE = ("<command-", "<local-command-", "<task-notification", "Caveat:", "[Request interrupted",
           "<system-reminder>", "<bash-input>", "<bash-stdout>")
COMMIT_OUT = re.compile(r"\[[\w./-]+(?: \(root-commit\))? ([0-9a-f]{7,40})\] ")
FIX = re.compile(r"^(?:fix|hotfix|revert)\b|исправ|почин|откат", re.I)
REDO = re.compile(r"не так|не то\b|не работает|переделай|опять|верни|сломал|ошибк|неправильн", re.I)
RETURN_DAYS = 7


def ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def load_directions():
    with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
        dirs = tomllib.load(fh)["direction"]
    roots = []
    for d in dirs:
        for f in d.get("folders") or []:
            roots.append((os.path.realpath(os.path.expanduser(f)), d["name"]))
    for f, name in ALIASES.items():
        roots.append((os.path.realpath(os.path.expanduser(f)), name))
    roots.sort(key=lambda x: -len(x[0]))
    return {d["name"]: d.get("project") or d["name"] for d in dirs}, roots


def direction_of(cwd, roots):
    cwd = os.path.realpath(cwd or "")
    for root, name in roots:
        if cwd == root or cwd.startswith(root + os.sep):
            return name
    return None


def repos_of(roots):
    """Git-репозитории в папках направлений (до трёх уровней вглубь, без node_modules и скрытых папок)."""
    found = defaultdict(set)
    for root, name in roots:
        if not os.path.isdir(root):
            continue
        for cur, dirs, _ in os.walk(root):
            depth = cur[len(root):].count(os.sep)
            if os.path.isdir(os.path.join(cur, ".git")):
                found[name].add(cur)
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"] if depth < 3 else []
    return found


def commits_of(repo, since, until):
    out = subprocess.run(["git", "-C", repo, "log", "--all", "--no-merges", f"--since=@{int(since)}",
                          f"--until=@{int(until)}", "--format=%x1e%H%x1f%ct%x1f%s", "--name-only"],
                         capture_output=True, text=True, timeout=120).stdout
    result = []
    for chunk in out.split("\x1e")[1:]:
        head, _, files = chunk.partition("\n")
        sha, when, subject = head.split("\x1f", 2)
        result.append({"sha": sha, "t": int(when), "subject": subject, "repo": repo,
                       "files": {os.path.join(repo, x) for x in files.split("\n") if x.strip()}})
    return result


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def tool_results(content):
    if not isinstance(content, list):
        return ""
    parts = []
    for x in content:
        if isinstance(x, dict) and x.get("type") == "tool_result":
            c = x.get("content")
            parts.append(c if isinstance(c, str) else text_of(c))
    return "\n".join(parts)


def commit_dirs(cmd, cwd):
    """Папки, где команда делает git commit: `git -C <п> commit`, иначе последний `cd` перед ним, иначе папка
    разговора в момент вызова."""
    cur, found = cwd or "", []
    for seg in re.split(r"&&|\|\||;|\n", cmd or ""):
        seg = seg.strip()
        m = re.match(r"cd\s+(\"[^\"]+\"|'[^']+'|\S+)", seg)
        if m:
            cur = os.path.normpath(os.path.join(cur, os.path.expanduser(m.group(1).strip("\"'"))))
        if re.search(r"\bgit\b(?:\s+-C\s+\S+)?\s+commit\b", seg):
            m = re.search(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", seg)
            found.append(os.path.normpath(os.path.join(cur, os.path.expanduser(m.group(1).strip("\"'")))) if m else cur)
    return found


def parse_transcript(path, seen_req, seen_msg):
    """Один основной транскрипт и его субагенты → разговор: кто начал, где, когда, ваши сообщения, вызовы
    git commit (папка и время), цена по времени запросов. Текст переписки дальше этой функции не уходит."""
    conv = {"path": path, "entry": None, "cwd": None, "start": None, "end": None, "owner": [], "redo": 0,
            "hashes": set(), "calls": [], "cost": []}
    pending = {}  # id вызова git commit → (папки, время вызова)
    sid = os.path.splitext(os.path.basename(path))[0]
    files = [path] + glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "*.jsonl"))
    for i, f in enumerate(files):
        with open(f, errors="replace") as fh:
            for line in fh:
                is_user, is_asst = '"user"' in line, '"assistant"' in line  # быстрый отсев, точно — после разбора
                if not (is_user or is_asst) and conv["cwd"]:
                    if i == 0 and '"timestamp"' in line:
                        try:
                            t = ts(json.loads(line).get("timestamp"))
                        except ValueError:
                            t = None
                        if t:
                            conv["end"] = max(conv["end"] or t, t)
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = ts(d.get("timestamp"))
                if i == 0:
                    conv["entry"] = conv["entry"] or d.get("entrypoint")
                    conv["cwd"] = conv["cwd"] or d.get("cwd")
                    if t:
                        conv["start"] = min(conv["start"] or t, t)
                        conv["end"] = max(conv["end"] or t, t)
                m = d.get("message") or {}
                content = m.get("content")
                if d.get("type") == "assistant":
                    for x in content if isinstance(content, list) else []:
                        if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") == "Bash":
                            cmd = (x.get("input") or {}).get("command") or ""
                            if "commit" in cmd and t:
                                dirs = commit_dirs(cmd, d.get("cwd") or conv["cwd"])
                                if dirs:
                                    pending[x.get("id")] = (dirs, t)
                    if not m.get("usage"):
                        continue
                    key = d.get("requestId") or m.get("id")
                    fam = family(m.get("model"))
                    if key in seen_req or not fam or not t:
                        continue
                    seen_req.add(key)
                    conv["cost"].append((t, sum(cost(fam, m["usage"])[0].values())))
                elif d.get("type") == "user":
                    for x in content if isinstance(content, list) else []:
                        if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("tool_use_id") in pending:
                            dirs, t0 = pending.pop(x["tool_use_id"])
                            if not x.get("is_error") and t:
                                conv["calls"].append((dirs, t0, t))
                    conv["hashes"].update(COMMIT_OUT.findall(tool_results(content)))
                    if i:
                        continue
                    text = text_of(content).strip()
                    uid = d.get("uuid")
                    if (d.get("isMeta") or not text or text.startswith(SERVICE) or (uid and uid in seen_msg)
                            or d.get("isSidechain") or d.get("toolUseResult") is not None):
                        continue
                    if uid:
                        seen_msg.add(uid)
                    conv["owner"].append(t)
                    conv["redo"] += bool(REDO.search(text))
    return conv


def week_of(t, start):
    return int((t - start) // (7 * 86400))


def repo_for(path, repos):
    best = None
    for r in repos:
        if (path == r or path.startswith(r + os.sep)) and (best is None or len(r) > len(best)):
            best = r
    return best


def build(end_day, weeks):
    names, roots = load_directions()
    start = datetime.combine(end_day - timedelta(days=7 * weeks), datetime.min.time()).timestamp()
    stop = datetime.combine(end_day, datetime.min.time()).timestamp()

    commits, by_repo, repo_dir = [], defaultdict(list), {}
    for name, rs in repos_of(roots).items():
        for repo in rs:
            repo_dir[repo] = name
            for c in commits_of(repo, start - 7 * 86400, stop + RETURN_DAYS * 86400):
                c["dir"] = name
                commits.append(c)
                by_repo[repo].append(c)
    by_sha = {c["sha"]: c for c in commits}

    convs, seen_req, seen_msg = [], set(), set()
    for path in sorted(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))):
        if os.path.getmtime(path) < start:
            continue
        c = parse_transcript(path, seen_req, seen_msg)
        if not c["start"] or c["start"] >= stop or (c["end"] or 0) < start:
            continue
        c["dir"] = direction_of(c["cwd"], roots)
        c["auto"] = str(c["entry"] or "").startswith("sdk")
        c["commits"] = {sha for h in c["hashes"] for sha in by_sha if sha.startswith(h)}
        for dirs, t0, t1 in c["calls"]:
            for folder in dirs:
                repo = repo_for(os.path.realpath(folder), repo_dir)
                c["commits"].update(x["sha"] for x in by_repo.get(repo, []) if t0 - 5 <= x["t"] <= t1 + 5)
        convs.append(c)
    owner_of = {sha: id(c) for c in convs for sha in c["commits"]}

    rows = defaultdict(lambda: defaultdict(lambda: {"convs": 0, "done": 0, "nocommit": 0, "msgs": [], "redo": [],
                                                    "returned": 0, "cost": 0.0, "auto": 0.0, "commits": 0}))
    for c in convs:
        mine = [by_sha[s] for s in c["commits"] if start <= by_sha[s]["t"] < stop]
        tasks = defaultdict(list)  # направление → свои коммиты разговора в нём
        for x in mine:
            tasks[x["dir"]].append(x)
        if c["auto"] or not c["owner"]:
            for t, usd in c["cost"]:
                if start <= t < stop:
                    rows[c["dir"] or "—"][week_of(t, start)]["auto" if c["auto"] else "cost"] += usd
            continue
        # цена разговора — поровну между направлениями его задач; без задач — направлению по папке запуска
        targets = list(tasks) or [c["dir"] or "—"]
        for t, usd in c["cost"]:
            if start <= t < stop:
                for name in targets:
                    rows[name][week_of(t, start)]["cost"] += usd / len(targets)
        if not tasks:
            if start <= c["start"] < stop:
                cell = rows[c["dir"] or "—"][week_of(c["start"], start)]
                cell["convs"] += 1
                cell["nocommit"] += 1
            continue
        for name, done in tasks.items():
            last = max(x["t"] for x in done)
            cell = rows[name][week_of(last, start)]
            cell["convs"] += 1
            cell["done"] += 1
            cell["msgs"].append(len(c["owner"]) / len(tasks))
            cell["redo"].append(c["redo"] / len(tasks))
            touched = set().union(*(x["files"] for x in done))
            back = [x for x in commits if last < x["t"] <= last + RETURN_DAYS * 86400 and FIX.search(x["subject"])
                    and owner_of.get(x["sha"]) != id(c) and x["files"] & touched]
            cell["returned"] += bool(back)
    for cm in commits:
        if start <= cm["t"] < stop:
            rows[cm["dir"]][week_of(cm["t"], start)]["commits"] += 1
    return names, rows, start, stop


def fmt_money(x):
    return f"${x:,.0f}" if x >= 10 else f"${x:,.2f}"


def summary(cells, active=None):
    s = {"convs": 0, "done": 0, "nocommit": 0, "msgs": [], "redo": [], "returned": 0, "cost": 0.0, "auto": 0.0,
         "commits": 0, "active": active}
    cells = list(cells)
    if s["active"] is None:
        s["active"] = sum(1 for c in cells if c["convs"])
    for c in cells:
        for k in ("convs", "done", "nocommit", "returned", "commits"):
            s[k] += c[k]
        s["cost"] += c["cost"]
        s["auto"] += c["auto"]
        s["msgs"] += c["msgs"]
        s["redo"] += c["redo"]
    return s


def line(label, s, weeks):
    msgs = f"{median(s['msgs']):.0f} / {mean(s['msgs']):.1f}" if s["msgs"] else "—"
    redo = f"{mean(s['redo']):.1f}" if s["redo"] else "—"
    ret = f"{s['returned']} из {s['done']}" if s["done"] else "—"
    price = fmt_money(s["cost"] / s["done"]) if s["done"] else (f"— ({fmt_money(s['cost'])} без задач)" if s["cost"] else "—")
    per_week = f"{s['done'] / weeks:.1f}" if weeks else "—"
    per_active = f"{s['done'] / s['active']:.1f} ({s['active']} нед.)" if s["active"] else "—"
    return (f"| {label} | {s['convs']} | {s['done']} | {per_week} | {per_active} | {s['nocommit']} | {msgs} | {redo} | {ret} | "
            f"{price} | {s['commits']} | {fmt_money(s['auto']) if s['auto'] else '—'} |")


HEAD = ("| {0} | Ваших разговоров | Доведено до конца | В неделю | В активную неделю | Без коммита | Ваших сообщений "
        "на задачу (медиана / среднее) | Поправок на задачу | Возвращено на переделку | Цена задачи | Коммитов | "
        "Автоматика |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")


def report(names, rows, start, stop, weeks, note=None):
    d0, d1 = datetime.fromtimestamp(start), datetime.fromtimestamp(stop - 1)
    sha = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out = [f"# Замер «как сейчас»: {d0:%d.%m}–{d1:%d.%m.%Y}", "",
           f"Собран {date.today():%d.%m.%Y} скриптом `agent-kit/plugins/pantheon/scripts/baseline.py` ({sha or '—'}), "
           f"период — {weeks} нед. по 7 дней. Правила подсчёта — в конце и в шапке скрипта; через 4 недели работы "
           "системы тот же скрипт с теми же правилами даёт цифры для сравнения (пересмотр R-rollback).", ""]
    if note:
        out += [note, ""]
    out += ["## Итог за период", "", HEAD.format("Направление")]
    order = [n for n in names if n in rows] + (["—"] if "—" in rows else [])
    for n in order:
        label = f"{n} ({names[n]})" if n in names else "вне направлений"
        out.append(line(label, summary(rows[n].values()), weeks))
    active = sum(1 for w in range(weeks) if any(rows[n][w]["convs"] for n in order if n != "—" and w in rows[n]))
    out.append(line("**Всего**", summary((c for n in order for c in rows[n].values()), active), weeks))
    out += ["", "## По неделям", ""]
    for n in order:
        label = f"{n} ({names[n]})" if n in names else "вне направлений"
        out += [f"### {label}", "", HEAD.format("Неделя")]
        for w in range(weeks):
            a = datetime.fromtimestamp(start + w * 7 * 86400)
            b = datetime.fromtimestamp(start + (w + 1) * 7 * 86400 - 1)
            out.append(line(f"{a:%d.%m}–{b:%d.%m}", summary([rows[n][w]] if w in rows[n] else []), 1))
        out.append("")
    doc = (__doc__ or "").split("Правила подсчёта", 1)[1]
    out += ["## Правила подсчёта", "", "```text", "Правила подсчёта" + doc.rstrip(), "```", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Замер «как сейчас» по git и транскриптам Claude Code")
    ap.add_argument("--end", default=date.today().isoformat(), help="первый день после периода, ГГГГ-ММ-ДД")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--out", help="куда записать отчёт; без него — в вывод")
    ap.add_argument("--note", help="строка под заголовком: почему выбран этот период")
    args = ap.parse_args()
    end_day = date.fromisoformat(args.end)
    names, rows, start, stop = build(end_day, args.weeks)
    text = report(names, rows, start, stop, args.weeks, args.note)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"записано: {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
