"""Замер «как сейчас» (ORD-06) и тот же замер через 4 недели работы системы (ORD-07, пересмотр R-rollback).

По git и локальным транскриптам Claude Code, без нового прогона и без текста переписки в отчёте: по каждому
направлению из ~/ai/pantheon/directions.toml и по неделям.

Запуск: python3 -I baseline.py [--end ГГГГ-ММ-ДД] [--weeks 4] [--out файл.md] [--note "почему этот период"]
                                [--narrow] [--p1]
  --end    первый день ПОСЛЕ периода (по умолчанию сегодня); недели — по 7 дней назад от него
  --narrow добавить раздел «узко: задача кода в направлении» рядом с широким счётом (metis-0102, ревизия 16.10 F4)
  --p1     добавить раздел метрик P1: доля поручений, Skill, qmd, ожидание сообщений в очереди
  Без --narrow и --p1 отчёт тот же, что до metis-0102.

Замер до запуска (решено 14.10): неделя 07.10–13.10 — `--end 2026-10-14 --weeks 1`. Через 4 недели работы системы
(R-rollback): `--end <system_start + 28 дней> --weeks 4 --narrow --p1`; сравнивать «в неделю» с неделей замера,
остальное — на задачу.

Правила подсчёта (одни и те же для замера до запуска и после; меняются только вместе с решением в журнале):
  Разговор      — один основной транскрипт ~/.claude/projects/*/<id>.jsonl, начатый вами (entrypoint не sdk-*).
                  sdk-py и sdk-cli — автоматические прогоны (бот, claude -p): в задачи не входят,
                  их цена — отдельной колонкой.
  Направление   — по папке запуска (cwd первой записи) против folders в directions.toml; прежние пути папок
                  направления — поле old_folders там же — и встроенные ~/knowledge, ~/pantheon (старые пути до
                  переезда 14.10) — к своим направлениям.
  Ваше сообщение — запись type=user с текстом от вас: не результат инструмента, не служебная вставка
                  (<command-…>, <local-command-…>, <task-notification>, «Caveat:», прерывание).
  Задача доведена до конца — разговор с хотя бы одним своим коммитом в репозитории направления; направление
                  задачи — по репозиторию коммита, а не по папке запуска (разговор из папки направления, закоммитивший
                  в репозиторий другого направления, — задача направления-владельца репозитория); неделя — по последнему коммиту.
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

Узкий режим (--narrow): задача кода в направлении — то, о чём цель «2–3 ваших сообщения на задачу».
  Задача кода   — ваш разговор (не автоматика), открытый в папке направления, кроме metis-pantheon (это сборка
                  самой системы) и папок вне направлений, с хотя бы одним своим коммитом в репозиторий ЭТОГО же
                  направления. Коммиты разговора в другие направления узкий счёт не видит. Один разговор — одна
                  задача, как в широком счёте; неделя — по последнему коммиту в своём направлении.
  Сообщения     — ваши сообщения от первого (постановка) до последнего коммита задачи и ещё одно, если оно пришло
                  в течение 2 ч после него (приёмка). Последующее обсуждение не считается.
  Не ваше       — сверх широких правил: поручения и побудки Пантеона («[Пантеон: …]»), сообщения других сессий,
                  уведомления фоновых задач, слэш-команды (/clear, /compact и навыки) и записи, которые Claude Code
                  пометил не вашим вводом (origin.kind не human, promptSource sdk или system). Разговор, где ваших
                  сообщений нет вовсе, но есть свой коммит (роль запущена `pantheon start`), — задача с 0 сообщений.
  ≤ 3 сообщений — доля задач кода, уложившихся в цель «постановка, приёмка и иногда вопрос».

Метрики P1 (--p1): вызовы инструментов за период — по записям tool_use во всех транскриптах (основных и субагентов),
повтор того же id не считается; время — по записи вызова.
  Группы        — координаторы: основные сессии с ролью domain-coordinator; другие роли Пантеона: основные сессии
                  и субагенты с ролью из ~/.claude/agents, собранной `pantheon roles build` (hq, workshop, лиды,
                  dev-*, argus, …); ваши сессии: основные без роли и не автоматика; прочие субагенты (Explore,
                  general-purpose, …); автоматика: entrypoint sdk-* без роли Пантеона.
  Поручения     — вызовы Agent (и прежнего Task) — доля от всех вызовов группы.
  Skill         — вызовы инструмента Skill по группам. Навык, который вы вызвали сами слэш-командой, — не вызов
                  инструмента и здесь не считается.
  qmd           — вызовы инструментов mcp__qmd__* (и mcp__plugin_…qmd…__*).
  Ожидание в очереди — сообщение, пришедшее работающей сессии во время её хода (queue-operation enqueue), до того,
                  как сессия его взяла (dequeue или remove); не взятое до конца транскрипта — «не взято». Это
                  приближение «возраста неотвеченных сообщений»: сообщение закрытой сессии в её транскрипт не
                  попадает, а взятое в ход ещё не значит отвеченное по сути — точный возраст по транскриптам не
                  посчитать.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
try:
    import tomllib
except ImportError:  # системный python 3.9 на macOS
    sys.exit("pantheon: нужен Python 3.11+ (нет tomllib)")
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from usage import cost, family  # noqa: E402  цены — одна таблица на оба скрипта

HOME = os.path.expanduser("~")
PANTHEON = os.environ.get("PANTHEON_HOME", os.path.join(HOME, "ai", "pantheon"))
PROJECTS = os.environ.get("BASELINE_TRANSCRIPTS", os.path.join(HOME, ".claude", "projects"))
ALIASES = {"~/knowledge": "mnemo-brain", "~/pantheon": "metis-pantheon"}
SERVICE = ("<command-", "<local-command-", "<task-notification", "Caveat:", "[Request interrupted",
           "<system-reminder>", "<bash-input>", "<bash-stdout>")
COMMIT_OUT = re.compile(r"\[[\w./-]+(?: \(root-commit\))? ([0-9a-f]{7,40})\] ")
FIX = re.compile(r"^(?:fix|hotfix|revert)\b|исправ|почин|откат", re.I)
REDO = re.compile(r"не так|не то\b|не работает|переделай|опять|верни|сломал|ошибк|неправильн", re.I)
RETURN_DAYS = 7
# Узкий режим: сборка системы — не задача кода в направлении; не ваш ввод — как hooks/ctx.py NOT_OWNER
SYSTEM_DIRECTION = "metis-pantheon"
NOT_OWNER = ("[Пантеон:", "/goal [Пантеон:", "<cross-session-message", "Another Claude session sent a message",
             "<agent-message", "<task-notification", "[Cross-session", "Your claude.ai usage limit has reset",
             "<local-command-", "<command-name>", "<command-message>")
ACCEPT_WINDOW = 2 * 3600  # приёмка — ваше сообщение не позже 2 ч после последнего коммита задачи
FEW_MESSAGES = 3          # цель «2–3 сообщения»: постановка, приёмка и иногда вопрос
COORDINATOR = "domain-coordinator"
QMD = re.compile(r"^mcp__(?:plugin_\w*?_)?qmd__")
WAIT_ALERT = 600          # ожидание в очереди дольше 10 мин — порог дежурного (P3-1)
PEER = ("<cross-session-message", "Another Claude session", "[Cross-session", "<agent-message", "[Пантеон:",
        "/goal [Пантеон:")


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
        for f in [*(d.get("folders") or []), *(d.get("old_folders") or [])]:
            roots.append((os.path.realpath(os.path.expanduser(f)), d["name"]))
    for f, name in ALIASES.items():
        roots.append((os.path.realpath(os.path.expanduser(f)), name))
    roots.sort(key=lambda x: -len(x[0]))
    return {d["name"]: d.get("project") or d["name"] for d in dirs}, roots


def load_roles():
    """Роли Пантеона — файлы ~/.claude/agents, собранные `pantheon roles build`, и координатор."""
    roles = {COORDINATOR}
    for f in glob.glob(os.path.join(HOME, ".claude", "agents", "*.md")):
        try:
            with open(f, errors="replace") as fh:
                if "pantheon roles build" in fh.read(4000):
                    roles.add(os.path.splitext(os.path.basename(f))[0])
        except OSError:
            pass
    return roles


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


def message_kind(text):
    """Сообщение в очереди сессии: ваше, от другой сессии или Пантеона, служебное — без текста дальше."""
    text = (text or "").lstrip()
    if text.startswith(PEER):
        return "peer"
    if text.startswith(SERVICE) or text.startswith(NOT_OWNER):
        return "note"
    return "owner"


def parse_transcript(path, seen_req, seen_msg, seen_tool=None):
    """Один основной транскрипт и его субагенты → разговор: кто начал, где, когда, ваши сообщения, вызовы
    git commit (папка и время), цена по времени запросов, вызовы инструментов и очередь сообщений (для --p1).
    Текст переписки дальше этой функции не уходит."""
    conv = {"path": path, "entry": None, "cwd": None, "start": None, "end": None, "owner": [], "redo": 0,
            "hashes": set(), "calls": [], "cost": [], "owner_n": [], "setting": None, "tools": [], "types": {},
            "queue": []}
    seen_tool = set() if seen_tool is None else seen_tool
    pending = {}  # id вызова git commit → (папки, время вызова)
    sid = os.path.splitext(os.path.basename(path))[0]
    files = [path] + glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "*.jsonl"))

    def extra(d):  # только основной транскрипт: роль сессии и очередь сообщений
        kind = d.get("type")
        if kind == "agent-setting":
            conv["setting"] = conv["setting"] or d.get("agentSetting")
        elif kind == "queue-operation":
            content = d.get("content")
            content = content if isinstance(content, str) else text_of(content)
            conv["queue"].append((d.get("operation"), ts(d.get("timestamp")), message_kind(content) if content else None,
                                  hash(content) if content else None))

    for i, f in enumerate(files):
        if i:
            try:
                with open(os.path.splitext(f)[0] + ".meta.json") as fh:
                    conv["types"][i] = json.load(fh).get("agentType")
            except (OSError, ValueError, AttributeError):
                conv["types"][i] = None
        with open(f, errors="replace") as fh:
            for line in fh:
                is_user, is_asst = '"user"' in line, '"assistant"' in line  # быстрый отсев, точно — после разбора
                if not (is_user or is_asst) and conv["cwd"]:
                    if i == 0 and ('"agent-setting"' in line or '"queue-operation"' in line):
                        try:
                            extra(json.loads(line))
                        except ValueError:
                            pass
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
                    extra(d)
                    conv["entry"] = conv["entry"] or d.get("entrypoint")
                    conv["cwd"] = conv["cwd"] or d.get("cwd")
                    if t:
                        conv["start"] = min(conv["start"] or t, t)
                        conv["end"] = max(conv["end"] or t, t)
                m = d.get("message") or {}
                content = m.get("content")
                if d.get("type") == "assistant":
                    for x in content if isinstance(content, list) else []:
                        if isinstance(x, dict) and x.get("type") == "tool_use" and t and x.get("id") not in seen_tool:
                            seen_tool.add(x.get("id"))
                            conv["tools"].append((i, t, str(x.get("name") or "")))
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
                    origin = d.get("origin")
                    if t and not (text.startswith(NOT_OWNER)
                                  or (isinstance(origin, dict) and origin.get("kind") not in (None, "human"))
                                  or d.get("promptSource") in ("sdk", "system")):
                        conv["owner_n"].append(t)
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

    convs, seen_req, seen_msg, seen_tool = [], set(), set(), set()
    for path in sorted(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))):
        if os.path.getmtime(path) < start:
            continue
        c = parse_transcript(path, seen_req, seen_msg, seen_tool)
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
    narrow = defaultdict(lambda: defaultdict(list))  # узкий режим: направление → неделя → [сообщений на задачу]
    for c in convs:
        mine = [by_sha[s] for s in c["commits"] if start <= by_sha[s]["t"] < stop]
        tasks = defaultdict(list)  # направление → свои коммиты разговора в нём
        for x in mine:
            tasks[x["dir"]].append(x)
        narrow_task(narrow, c, tasks, start)
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
    return names, rows, start, stop, {"narrow": narrow, "p1": p1_stats(convs, start, stop)}


def narrow_task(narrow, c, tasks, start):
    """Узкий режим: разговор в папке направления (не сборка системы) со своим коммитом в репозиторий этого же
    направления — задача кода; ваши сообщения от постановки до последнего коммита и одно после него (приёмка)."""
    name = c["dir"]
    if c["auto"] or not name or name == SYSTEM_DIRECTION or name not in tasks:
        return
    last = max(x["t"] for x in tasks[name])
    before = [t for t in c["owner_n"] if t <= last]
    accept = any(last < t <= last + ACCEPT_WINDOW for t in c["owner_n"])
    narrow[name][week_of(last, start)].append(len(before) + accept)


def group_of(c, i, roles):
    if i == 0:
        if c["setting"] == COORDINATOR:
            return "coord"
        if c["setting"] in roles:
            return "role"
        return "auto" if c["auto"] else "owner"
    return "role" if c["types"].get(i) in roles else "sub"


def p1_stats(convs, start, stop):
    """Метрики P1 за период: вызовы инструментов по группам (всего, Agent/Task, Skill, qmd) и ожидание сообщений
    в очереди работающей сессии."""
    roles = load_roles()
    calls = defaultdict(lambda: {"calls": 0, "agent": 0, "skill": 0, "qmd": 0, "sessions": set()})
    waits = defaultdict(list)  # (группа, ваше|сессии) → [(секунд, взято ли)]
    for c in convs:
        for i, t, name in c["tools"]:
            if not start <= t < stop:
                continue
            cell = calls[group_of(c, i, roles)]
            cell["calls"] += 1
            cell["agent"] += name in ("Agent", "Task")
            cell["skill"] += name == "Skill"
            cell["qmd"] += bool(QMD.match(name))
            cell["sessions"].add((id(c), i))
        group, queue = group_of(c, 0, roles), []

        def record(t0, kind, wait, taken):
            if start <= t0 < stop and kind in ("owner", "peer"):
                waits[(group, kind)].append((max(wait, 0), taken))
        for op, t, kind, h in c["queue"]:
            if op == "enqueue" and t:
                queue.append((t, kind, h))
            elif op in ("dequeue", "remove") and queue and t:
                j = next((k for k, x in enumerate(queue) if op == "remove" and h is not None and x[2] == h), 0)
                t0, kind0, _ = queue.pop(j)
                record(t0, kind0, t - t0, True)
        for t0, kind0, _ in queue:
            record(t0, kind0, (c["end"] or t0) - t0, False)
    return {"calls": calls, "waits": waits}


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


def fmt_msgs(values):
    return f"{median(values):.0f} / {mean(values):.1f}" if values else "—"


def fmt_wait(sec):
    return f"{sec / 3600:.1f} ч" if sec >= 3600 else (f"{sec / 60:.0f} мин" if sec >= 60 else f"{sec:.0f} с")


def narrow_section(names, rows, narrow, start, weeks):
    out = ["## Узко: задача кода в направлении", "",
           "Широко — как в «Итог за период»: все ваши сообщения в любом вашем разговоре с коммитом. Узко — только "
           "разговор в папке направления (кроме metis-pantheon) со своим коммитом в репозиторий этого направления, и "
           f"только ваши сообщения от постановки до последнего коммита и приёмка. Цель — 2–3 сообщения; «≤ {FEW_MESSAGES}» — "
           "сколько задач в неё уложились.", "",
           "| Направление | Задач широко | Сообщений на задачу широко (медиана / среднее) | Задач кода узко | "
           f"Сообщений на задачу узко (медиана / среднее) | Задач с ≤ {FEW_MESSAGES} сообщениями |",
           "| --- | ---: | ---: | ---: | ---: | ---: |"]
    order = [n for n in names if n in rows or n in narrow] + (["—"] if "—" in rows else [])
    all_wide, all_narrow = [], []
    for n in order:
        label = f"{n} ({names[n]})" if n in names else "вне направлений"
        wide = summary(rows[n].values()) if n in rows else summary([])
        mine = [x for w in narrow.get(n, {}).values() for x in w]
        all_wide += wide["msgs"]
        all_narrow += mine
        if n == SYSTEM_DIRECTION or n == "—":
            tail = "— (сборка системы) | — | —" if n == SYSTEM_DIRECTION else "— | — | —"
        else:
            few = f"{sum(x <= FEW_MESSAGES for x in mine)} из {len(mine)}" if mine else "—"
            tail = f"{len(mine)} | {fmt_msgs(mine)} | {few}"
        out.append(f"| {label} | {wide['done']} | {fmt_msgs(wide['msgs'])} | {tail} |")
    few = f"{sum(x <= FEW_MESSAGES for x in all_narrow)} из {len(all_narrow)}" if all_narrow else "—"
    out.append(f"| **Всего** | {len(all_wide)} | {fmt_msgs(all_wide)} | {len(all_narrow)} | {fmt_msgs(all_narrow)} | {few} |")
    if weeks > 1:
        out += ["", "| Неделя | Задач кода узко | Сообщений на задачу узко (медиана / среднее) | "
                f"Задач с ≤ {FEW_MESSAGES} сообщениями |", "| --- | ---: | ---: | ---: |"]
        for w in range(weeks):
            a = datetime.fromtimestamp(start + w * 7 * 86400)
            b = datetime.fromtimestamp(start + (w + 1) * 7 * 86400 - 1)
            mine = [x for n in narrow for x in narrow[n].get(w, [])]
            few = f"{sum(x <= FEW_MESSAGES for x in mine)} из {len(mine)}" if mine else "—"
            out.append(f"| {a:%d.%m}–{b:%d.%m} | {len(mine)} | {fmt_msgs(mine)} | {few} |")
    return out + [""]


GROUPS = (("coord", "Координаторы (основные сессии domain-coordinator)"),
          ("role", "Другие роли Пантеона (основные и субагенты)"),
          ("owner", "Ваши сессии без роли (основные)"),
          ("sub", "Прочие субагенты (Explore, general-purpose, …)"),
          ("auto", "Автоматика (claude -p, SDK)"))


def p1_section(p1):
    calls, waits = p1["calls"], p1["waits"]

    def row(label, keys):
        cells = [calls[k] for k in keys if k in calls]
        n = sum(len(c["sessions"]) for c in cells)
        total = sum(c["calls"] for c in cells)
        agent = sum(c["agent"] for c in cells)
        share = f"{100 * agent / total:.1f} %" if total else "—"
        return (f"| {label} | {n} | {total} | {agent} | {share} | {sum(c['skill'] for c in cells)} | "
                f"{sum(c['qmd'] for c in cells)} |")
    out = ["## Метрики P1", "",
           "Вызовы инструментов за период по группам сессий. Поручения — вызовы Agent (Task); доля — от всех вызовов "
           "группы. Сессия — основной транскрипт или субагент с хотя бы одним вызовом за период.", "",
           "| Группа | Сессий | Вызовов инструментов | Поручений (Agent) | Доля поручений | Skill | qmd |",
           "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, label in GROUPS:
        out.append(row(label, [key]))
    out.append(row("**Роли всего** (координаторы и другие роли)", ["coord", "role"]))
    out.append(row("**Всего**", [k for k, _ in GROUPS]))
    out += ["", "### Ожидание сообщений в очереди", "",
            "Сообщение пришло работающей сессии во время её хода и ждало, пока она его возьмёт. Это приближение "
            "«возраста неотвеченных сообщений», не он сам (см. правила).", "",
            "| Сессии | От кого | Сообщений | Медиана ожидания | Дольше 10 мин | Не взято до конца | Самое долгое |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    labels = dict(GROUPS)
    for key, _ in GROUPS:
        for kind, who in (("owner", "вы"), ("peer", "другие сессии и Пантеон")):
            items = waits.get((key, kind))
            if not items:
                continue
            secs = [x for x, _ in items]
            out.append(f"| {labels[key]} | {who} | {len(items)} | {fmt_wait(median(secs))} | "
                       f"{sum(x > WAIT_ALERT for x in secs)} | {sum(not ok for _, ok in items)} | {fmt_wait(max(secs))} |")
    if not waits:
        out.append("| — | — | 0 | — | — | — | — |")
    return out + [""]


def report(names, rows, start, stop, weeks, note=None, more=None, narrow=False, p1=False):
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
    if narrow and more:
        out += narrow_section(names, rows, more["narrow"], start, weeks)
    if p1 and more:
        out += p1_section(more["p1"])
    doc = (__doc__ or "").split("Правила подсчёта", 1)[1]
    doc, _, rest = doc.partition("\nУзкий режим (--narrow)")
    narrow_doc, _, p1_doc = rest.partition("\nМетрики P1 (--p1)")
    doc = doc.rstrip()
    if narrow:
        doc += "\n\nУзкий режим (--narrow)" + narrow_doc.rstrip()
    if p1:
        doc += "\n\nМетрики P1 (--p1)" + p1_doc.rstrip()
    out += ["## Правила подсчёта", "", "```text", "Правила подсчёта" + doc, "```", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Замер «как сейчас» по git и транскриптам Claude Code")
    ap.add_argument("--end", default=date.today().isoformat(), help="первый день после периода, ГГГГ-ММ-ДД")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--out", help="куда записать отчёт; без него — в вывод")
    ap.add_argument("--note", help="строка под заголовком: почему выбран этот период")
    ap.add_argument("--narrow", action="store_true", help="раздел «узко: задача кода в направлении»")
    ap.add_argument("--p1", action="store_true", help="раздел метрик P1: поручения, Skill, qmd, ожидание сообщений")
    args = ap.parse_args()
    end_day = date.fromisoformat(args.end)
    names, rows, start, stop, more = build(end_day, args.weeks)
    text = report(names, rows, start, stop, args.weeks, args.note, more, args.narrow, args.p1)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"записано: {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
