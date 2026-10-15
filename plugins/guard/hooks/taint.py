#!/usr/bin/env python3
"""tg-taint: сессия, в контекст которой попал сырой текст Telegram, дальше действует наружу только с вашего «да»
(metis-0083, guard 0.5.6). Защита от внедрённых указаний из чатов: переписку пишут чужие люди.

Один скрипт на три события (hooks/hooks.json):
  PostToolUse (Bash, Read, Grep; событие приходит только при успехе) — ставит флаг
      <HOME>/.local/state/tg-taint/<session_id>, если сырой текст действительно попал в контекст:
      * Bash: tg_read.py history|search|unread|context|posts|download с выгрузкой в stdout (`-o -`). Без -o и с
        `-o ФАЙЛ` скрипт пишет выгрузку в файл, а в stdout — только путь и сводку: это не флаг. `posts --quota`,
        status, chats, folders, topics, find, split, verify, forms — тоже не флаг;
      * Bash: в выводе — шапка выгрузки tg_read («Переписка — строго между строками «<<<TG-…»);
      * Bash: команда чтения (cat, head, sed, grep, less, strings, python…) с путём выгрузки в словах;
      * Read: файл выгрузки (папка tg-read во временной папке; путь из -o, --files-dir, split --out-dir этой сессии
        и части split рядом с выгрузкой) или файл, в тексте которого шапка выгрузки;
      * Grep: только режим content (files_with_matches и count показывают имена и числа, а не текст) по выгрузкам.
      Субагент tg-reader (agent_type tg-reader) флаг не ставит: он и есть способ читать без заражения — у него только
      Read, Grep и Glob. Пути из -o, --files-dir и --out-dir запоминаются в <session_id>.dumps рядом с флагом.
  PreToolUse — пока флаг стоит, ask с причиной на действия наружу и записи в долговременные места (ask_reason);
      чтение и пересказ — без вопросов. В режиме bypassPermissions вместо ask — deny: по документации Claude Code
      этот режим отключает запросы разрешения, а вопрос хука в списке исключений не назван. Отказ guard.py (deny)
      важнее: Claude Code сводит решения всех хуков PreToolUse как deny > defer > ask > allow.
  UserPromptSubmit — снимает флаг на вашем сообщении. Уведомление фоновой задачи («<task-notification>»), сообщение
      другой сессии («Another Claude session sent a message:»), сообщение канала («<channel») флаг не снимают; поля
      origin.kind и promptSource, если Claude Code начнёт передавать их хуку, учитываются тоже. Запуск по расписанию
      (/loop, задача по времени) отличить нельзя — он снимает флаг (допущение: его текст писали вы).

Сбой: PreToolUse — выход 2 (действие остановлено, как у guard), в hooks.json — onFailure: block. PostToolUse — если
в событии упоминается tg-read, флаг ставится (лучше лишний вопрос, чем пропуск), выход 0. UserPromptSubmit — выход 0
и флаг остаётся: код 2 заблокировал бы ваше сообщение. Каждый сбой — строка в
~/.local/state/pantheon/logs/guard-failures.log. Выключить: GUARD_OFF=tg-taint.

Модель угроз — как у guard (README, SEC-27): ловит обычный путь агента, а не намеренный обход. Не видит, что делает
программа изнутри (python script.py), запись Bash'ем мимо простых шаблонов, сеть мимо списка команд.
Шаблоны — строки для re.search (модуль re кэширует их сам).
"""

import hashlib
import json
import os
import re
import shlex
import signal
import sys
import time

HOME = os.path.expanduser("~")
OFF = {r.strip() for r in os.environ.get("GUARD_OFF", "").split(",") if r.strip()}
STATE = os.path.join(HOME, ".local", "state", "tg-taint")
AI_HOME = os.path.join(HOME, "ai")
CLAUDE = os.path.join(HOME, ".claude")
FAIL_LOG = os.path.join(HOME, ".local", "state", "pantheon", "logs", "guard-failures.log")
DEADLINE = 8          # с, раньше таймаута хука 10 с
KEEP_DAYS = 7         # флаги и списки путей старше — удаляются при записи нового
READER_AGENTS = {"tg-reader"}

# --- источник заражения -----------------------------------------------------------------------------------------
RAW_SUBS = {"history", "search", "unread", "context", "posts", "download"}
STDOUT_OUT = {"-", "/dev/stdout", "/dev/fd/1", "/dev/stderr", "/dev/fd/2", "/dev/tty"}
TG_SCRIPT_RX = r"(?<![\w-])tg_read\.py$"
TG_TEXT_RX = r"(?<![\w-])tg_read\.py\b"
TG_VAR_RX = r"(?<![\w$])([A-Za-z_]\w*)=[\"']?[^\s;&|\"']*tg_read\.py\b"
DUMP_SIGNATURE_RX = r"Переписка — строго между строками «<<<TG-[0-9a-f]{12}»"
READERS = {"cat", "head", "tail", "less", "more", "sed", "awk", "gawk", "grep", "egrep", "fgrep", "rg", "ag", "bat",
           "strings", "xxd", "od", "hexdump", "pdftotext", "textutil", "jq", "nl", "cut", "sort", "uniq", "tr",
           "diff", "python", "python3", "node", "perl", "ruby", "glow", "mdcat", "view", "vim", "nvim", "column"}
TEMP_ROOTS_FIXED = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
TEMP_TG_RX = r"(?:\$\{?TMPDIR\}?|/tmp|/private/tmp|/var/folders/[^\s'\";|&]*)/+tg-read(?:/|\b)"

# --- что спрашивать ---------------------------------------------------------------------------------------------
ASK_TOOLS = {"WebFetch": "запрос в интернет (WebFetch)", "WebSearch": "поиск в интернете (WebSearch)",
             "SendMessage": "сообщение другой сессии (SendMessage)",
             "CronCreate": "задача по расписанию (CronCreate) — она запустится позже с этим текстом"}
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
MCP_ALWAYS = ("claude-in-chrome", "computer-use")
MCP_WRITE_WORDS = {"create", "update", "send", "post", "write", "delete", "edit", "insert", "upload", "publish",
                   "push", "comment", "reply", "share", "append", "remove", "move", "archive", "merge", "submit",
                   "navigate", "fill", "click", "type", "set", "add", "put", "patch", "invite", "forward", "react"}
NET_CMDS = {"curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "netcat", "socat", "telnet", "ftp", "gh", "mail",
            "sendmail", "mutt", "aria2c", "xh", "http", "https", "lftp", "rclone", "websocat", "grpcurl"}
SCRIPT_CMD_RX = r"^(?:python[\d.]*|node|deno|bun|ruby|perl|php|uv|uvx)$"
SCRIPT_NET_RX = (r"(?i)urllib|requests|http\.client|httpx|aiohttp|socket|smtplib|ftplib|websocket|fetch\s*\(|"
                 r"axios|XMLHttpRequest|net/http|Net::HTTP|LWP|https?://")
WRAPPERS = {"sudo", "env", "command", "builtin", "nohup", "time", "nice", "timeout", "gtimeout", "xargs", "exec",
            "caffeinate", "heavy", "then", "do", "else", "if", "while", "until", "!", "{", "stdbuf"}
BASH_WRITE_RX = (r">|\btee\b|\b(?:cp|mv|install|ln|rsync|ditto|dd|touch|truncate|rm|unlink|patch)\b|"
                 r"\b(?:sed|gsed|perl)\s+(?:-\w+\s+)*-\w*i")
DURABLE_TEXT_RX = (
    r"(?i)agent-memory(?:/|\b)|\.claude/projects/[^\s/]+/memory(?:/|\b)|(?<![\w-])(?:CLAUDE(?:\.local)?|AGENTS)\.md\b|"
    r"\.claude/(?:tools|skills|agents|commands|hooks|rules|output-styles)(?:/|\b)|\.claude/settings[\w.-]*\.json|"
    r"(?<![\w-])sync\.sh\b|/ai/knowledge(?:/|\b)|\.local/state/tg-taint")
NOT_OWNER_RX = (r"\s*(?:<task-notification>|<channel[\s>]|<cross-session|<teammate-message|"
                r"Another Claude session sent a message:)")


class TaintFailure(Exception):
    pass


def log_failure(where, e):
    """Строка в журнал сбоев guard: время, «taint», событие, тип ошибки. Текста событий нет."""
    try:
        os.makedirs(os.path.dirname(FAIL_LOG), exist_ok=True)
        with open(FAIL_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\ttaint\t{where}\t{type(e).__name__}\n")
    except Exception:
        pass


# --- файлы состояния --------------------------------------------------------------------------------------------

def session_key(event):
    """Имя файла флага по session_id: как есть, если это простое имя, иначе хеш."""
    sid = event.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}", sid) and ".." not in sid:
        return sid
    return "h-" + hashlib.sha256(sid.encode("utf-8", "replace")).hexdigest()[:32]


def flag_path(sid):
    return os.path.join(STATE, sid)


def dumps_path(sid):
    return os.path.join(STATE, sid + ".dumps")


def read_flag(sid):
    """Флаг сессии или None. Нечитаемый флаг — тоже флаг: лучше лишний вопрос."""
    p = flag_path(sid)
    if not os.path.lexists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _cleanup():
    try:
        cut = time.time() - KEEP_DAYS * 86400
        for e in os.scandir(STATE):
            if e.is_file(follow_symlinks=False) and e.stat(follow_symlinks=False).st_mtime < cut:
                os.unlink(e.path)
    except OSError:
        pass


def set_flag(sid, source):
    _write_json(flag_path(sid), {"since": time.strftime("%Y-%m-%d %H:%M"), "source": source})
    _cleanup()


def clear_flag(sid):
    try:
        os.unlink(flag_path(sid))
    except FileNotFoundError:
        pass


def load_dumps(sid):
    try:
        with open(dumps_path(sid), encoding="utf-8") as fh:
            data = json.load(fh)
        return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add_dumps(sid, paths):
    old = load_dumps(sid)
    new = old + [p for p in dict.fromkeys(paths) if p not in old]
    if new != old:
        _write_json(dumps_path(sid), new[-200:])


# --- разбор команды ---------------------------------------------------------------------------------------------

def _tokens(line):
    """Слова и разделители строки команды; кавычки сняты. Незакрытая кавычка — грубое деление по пробелам."""
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return re.findall(r"[;&|()]+|[^\s;&|()]+", line)


def segments(cmd):
    """Простые команды: списки слов между разделителями (; && || | & ( ) и перевод строки)."""
    segs = []
    for line in cmd.split("\n"):
        cur = []
        for t in _tokens(line):
            if t and set(t) <= set(";&|()"):
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            segs.append(cur)
    return segs


def head(seg):
    """Имя команды и её позиция: без присваиваний VAR=… и обёрток (sudo, env, timeout 5, nohup, heavy)."""
    i = 0
    while i < len(seg):
        w = seg[i]
        if re.fullmatch(r"[A-Za-z_]\w*=.*", w, re.S):
            i += 1
        elif w in WRAPPERS:
            i += 1
            if w in ("timeout", "gtimeout", "nice") and i < len(seg) and re.fullmatch(r"-?[\d.]+[smhd]?", seg[i]):
                i += 1
        elif w.startswith("-") and i > 0 and seg[i - 1] in WRAPPERS:
            i += 1
        else:
            return os.path.basename(w), i
    return "", len(seg)


def _tg_vars(cmd):
    return set(re.findall(TG_VAR_RX, cmd))


def _is_tg_word(w, tg_vars):
    return bool(re.search(TG_SCRIPT_RX, w)) or any(w in (f"${v}", f"${{{v}}}") for v in tg_vars)


def tg_runs(cmd):
    """Запуски tg_read.py в команде: [(подкоманда, {--out|--files-dir|--out-dir: значение}, есть ли --quota)]."""
    if not re.search(TG_TEXT_RX, cmd):
        return []
    tg_vars = _tg_vars(cmd)
    runs = []
    for seg in segments(cmd):
        for i, w in enumerate(seg):
            if not _is_tg_word(w, tg_vars) or re.fullmatch(r"[A-Za-z_]\w*=.*", w, re.S):
                continue
            rest = seg[i + 1:]
            sub = next((t for t in rest if not t.startswith("-")), "")
            opts, k = {}, 0
            while k < len(rest):
                t = rest[k]
                for name, short in (("--out", "-o"), ("--files-dir", None), ("--out-dir", None)):
                    if t == name or (short and t == short):
                        if k + 1 < len(rest):
                            opts[name] = rest[k + 1]
                    elif t.startswith(name + "="):
                        opts[name] = t[len(name) + 1:]
                    elif short and t.startswith(short) and len(t) > 2 and not t.startswith("--"):
                        opts[name] = t[2:]
                k += 1
            runs.append((sub, opts, "--quota" in rest))
            break
    return runs


def _abs(p, cwd):
    """Абсолютный путь слова команды или None (переменные, кроме TMPDIR, не раскрываем)."""
    if not p:
        return None
    tmp = os.environ.get("TMPDIR", "")
    p = p.replace("${TMPDIR}", tmp).replace("$TMPDIR", tmp)
    if "$" in p or "`" in p:
        return None
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


# --- где лежат выгрузки -----------------------------------------------------------------------------------------

def _under(path, root):
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root + "/")


def _temp_roots(event):
    roots = list(TEMP_ROOTS_FIXED)
    for p in (os.environ.get("TMPDIR"), event.get("scratchpad_dir")):
        if isinstance(p, str) and p:
            roots.append(p)
    out = []
    for r in roots:
        out += [os.path.normpath(r), os.path.realpath(r)]
    return out


def in_dump(path, event, sid):
    """Путь — выгрузка tg_read или её часть: папка tg-read во временной папке, путь из -o/--files-dir/--out-dir."""
    if not isinstance(path, str) or not path:
        return False
    p0 = os.path.normpath(os.path.expanduser(path))
    cands = {p0, os.path.realpath(p0)}
    homes = (HOME, os.path.realpath(HOME))
    roots = _temp_roots(event)
    dumps = load_dumps(sid) if sid else []
    for p in cands:
        parts = p.split("/")
        if "tg-read" in parts and not any(_under(p, h) for h in homes):
            prefix = "/".join(parts[:parts.index("tg-read")]) or "/"
            if any(_under(prefix, r) for r in roots):
                return True
        for d in dumps:
            if _under(p, d):
                return True
            stem = os.path.splitext(d)[0]
            if os.path.dirname(p) == os.path.dirname(d) and p.startswith(stem + ".part"):
                return True
    return False


def _resp_text(resp, limit=400000):
    """Текст ответа инструмента — только для поиска шапки выгрузки в памяти; никуда не пишется."""
    if isinstance(resp, str):
        return resp[:limit]
    if isinstance(resp, dict):
        parts = [resp[k][:limit] for k in ("stdout", "content", "output", "text") if isinstance(resp.get(k), str)]
        f = resp.get("file")
        if isinstance(f, dict) and isinstance(f.get("content"), str):
            parts.append(f["content"][:limit])
        return "\n".join(parts)
    if isinstance(resp, list):
        return "\n".join(_resp_text(x, limit) for x in resp[:50])
    return ""


def _resp_files(resp):
    if isinstance(resp, dict) and isinstance(resp.get("filenames"), list):
        return [f for f in resp["filenames"][:2000] if isinstance(f, str)]
    return []


def _bash_source(event, sid, cmd):
    cwd = event.get("cwd") or ""
    runs = tg_runs(cmd)
    hit, record = None, []
    for sub, opts, quota in runs:
        for name in ("--out", "--files-dir", "--out-dir"):
            v = opts.get(name)
            if v and v not in STDOUT_OUT:
                a = _abs(v, cwd)
                if a:
                    record.append(a)
        if sub in RAW_SUBS and not (sub == "posts" and quota) and opts.get("--out") in STDOUT_OUT:
            hit = hit or f"tg_read {sub} -o -"
    if record and sid:
        add_dumps(sid, record)
    if hit:
        return hit
    if re.search(DUMP_SIGNATURE_RX, _resp_text(event.get("tool_response"))):
        return "Bash: вывод выгрузки tg_read"
    dumps = load_dumps(sid) if sid else []
    if not (re.search(TEMP_TG_RX, cmd) or any(d in cmd for d in dumps)):
        return None
    tg_vars = _tg_vars(cmd)
    for seg in segments(cmd):
        if any(_is_tg_word(w, tg_vars) for w in seg):
            continue  # сам tg_read.py (verify, split) читает выгрузку для себя, в контекст она не идёт
        name, i = head(seg)
        if name in READERS and any(re.search(TEMP_TG_RX, w) or in_dump(_abs(w, cwd), event, sid)
                                   for w in seg[i + 1:]):
            return f"Bash: {name} по выгрузке tg_read"
    return None


def taint_source(event, sid):
    """PostToolUse: что заразило сессию (коротко, без текста) или None. Пути из -o запоминает."""
    tool = event.get("tool_name")
    ti = event.get("tool_input") or {}
    resp = event.get("tool_response")
    if tool == "Bash":
        cmd = ti.get("command")
        return _bash_source(event, sid, cmd) if isinstance(cmd, str) else None
    if tool == "Read":
        if in_dump(ti.get("file_path"), event, sid):
            return "Read выгрузки tg_read"
        if re.search(DUMP_SIGNATURE_RX, _resp_text(resp)):
            return "Read файла с выгрузкой tg_read"
        return None
    if tool == "Grep":
        if (ti.get("output_mode") or "files_with_matches") != "content":
            return None
        if in_dump(ti.get("path"), event, sid) or any(in_dump(f, event, sid) for f in _resp_files(resp)):
            return "Grep (content) по выгрузке tg_read"
        text = _resp_text(resp)
        if re.search(TEMP_TG_RX, text) or re.search(DUMP_SIGNATURE_RX, text):
            return "Grep (content) по выгрузке tg_read"
    return None


# --- что спрашивать ---------------------------------------------------------------------------------------------

def _words(name):
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return {w for w in re.split(r"[^A-Za-z0-9]+", name.lower()) if w}


def _mcp_reason(tool):
    parts = tool.split("__", 2)
    if len(parts) < 3:
        return None
    server, name = parts[1].lower(), parts[2]
    if any(m in server for m in MCP_ALWAYS):
        return f"действие в браузере или на компьютере ({tool})"
    if _words(name) & MCP_WRITE_WORDS:
        return f"запись или действие через MCP ({tool})"
    return None


def durable_path(path):
    """Долговременное место: память ролей и проектов, CLAUDE.md/AGENTS.md, ~/.claude/tools и настройки, sync.sh,
    ~/ai/knowledge, сам флаг tg-taint."""
    if not isinstance(path, str) or not path:
        return False
    p0 = os.path.normpath(os.path.expanduser(path))
    if os.path.basename(p0).casefold() in ("claude.md", "claude.local.md", "agents.md", "sync.sh"):
        return True
    for q in {p0, os.path.realpath(p0)}:
        for d in ("agent-memory", "tools", "skills", "agents", "commands", "hooks", "rules", "output-styles"):
            if _under(q, os.path.join(CLAUDE, d)):
                return True
        if _under(q, os.path.join(AI_HOME, "knowledge")) or _under(q, STATE):
            return True
        rel = q[len(CLAUDE) + 1:] if _under(q, CLAUDE) else ""
        if re.fullmatch(r"projects/[^/]+/memory(?:/.*)?|settings[\w.-]*\.json", rel):
            return True
        if re.search(r"/\.claude/(?:settings[\w.-]*\.json$|skills/|agents/|commands/|hooks/|rules/)", q):
            return True
    return False


def _bash_reason(cmd):
    segs = segments(cmd)
    for seg in segs:
        name, i = head(seg)
        args = seg[i + 1:]
        if name in NET_CMDS:
            return f"сеть из Bash ({name})"
        if name == "git" and any(a in ("push", "send-email", "request-pull") for a in args):
            return "git push"
        if name == "rsync" and any(re.match(r"rsync://|[^/\s=-][^/\s]*:", a) for a in args):
            return "rsync на другой хост"
        if re.match(SCRIPT_CMD_RX, name) and re.search(SCRIPT_NET_RX, " ".join(args)):
            return f"сеть из скрипта ({name})"
    if re.search(r"<<-?\s*['\"]?\w+", cmd) and re.search(SCRIPT_NET_RX, cmd) and \
            any(re.match(SCRIPT_CMD_RX, head(s)[0]) for s in segs):
        return "сеть из скрипта (heredoc)"
    if re.search(DURABLE_TEXT_RX, cmd) and re.search(BASH_WRITE_RX, cmd):
        return "запись Bash'ем в память, CLAUDE.md/AGENTS.md, настройки, ~/ai/knowledge или флаг tg-taint"
    return None


def ask_reason(event):
    """PreToolUse при стоящем флаге: какое это действие наружу, или None (чтение — None)."""
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    if tool in ASK_TOOLS:
        return ASK_TOOLS[tool]
    if tool.startswith("mcp__"):
        return _mcp_reason(tool)
    if tool in EDIT_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path")
        return f"запись в долговременное место ({os.path.basename(str(path))})" if durable_path(path) else None
    if tool == "Bash":
        cmd = ti.get("command")
        return _bash_reason(cmd) if isinstance(cmd, str) else None
    return None


# --- снятие -----------------------------------------------------------------------------------------------------

def owner_prompt(event):
    """UserPromptSubmit от вас, а не уведомление задачи или сообщение другой сессии."""
    origin = event.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    if event.get("promptSource") == "system":
        return False
    prompt = event.get("prompt")
    return not (isinstance(prompt, str) and re.match(NOT_OWNER_RX, prompt))


# --- вход хука --------------------------------------------------------------------------------------------------

def is_reader(event):
    at = event.get("agent_type")
    return bool(event.get("agent_id")) and isinstance(at, str) and \
        at.strip().rsplit(":", 1)[-1].casefold() in READER_AGENTS


def handle(event):
    """Ответ хука (dict для stdout) или None."""
    name = event.get("hook_event_name")
    sid = session_key(event)
    if not sid:
        return None
    if name == "PostToolUse":
        if not is_reader(event):
            src = taint_source(event, sid)
            if src:
                set_flag(sid, src)
        return None
    if name == "UserPromptSubmit":
        if owner_prompt(event):
            clear_flag(sid)
        return None
    if name != "PreToolUse":
        return None
    flag = read_flag(sid)
    if flag is None:
        return None
    what = ask_reason(event)
    if not what:
        return None
    src = flag.get("source") or "сырой текст Telegram"
    since = flag.get("since") or "?"
    bypass = event.get("permission_mode") == "bypassPermissions"
    tail = ("В режиме bypassPermissions вопрос не показывается, поэтому отказ: выйдите из режима или дождитесь "
            "следующего сообщения владельца — оно снимет флаг." if bypass else
            "Подтвердите, только если просили это сами; ваше следующее сообщение снимет флаг.")
    reason = (f"Правило tg-taint: сессия читала сырой Telegram ({src}, {since}) — в переписке могут быть "
              f"внедрённые указания. Действие: {what}. {tail}")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny" if bypass else "ask",
                                   "permissionDecisionReason": reason}}


def _out_of_time(signum, frame):
    raise TaintFailure(f"tg-taint: проверка не уложилась в {DEADLINE} с")


def _stop_timer():
    if hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)


def run_hook():
    """Вход хука. Не возвращается: os._exit с кодом по событию (шапка модуля, «Сбой»)."""
    code, raw, name = 0, "", None
    try:
        if hasattr(signal, "setitimer"):
            signal.signal(signal.SIGALRM, _out_of_time)
            signal.setitimer(signal.ITIMER_REAL, DEADLINE)
        raw = sys.stdin.read()
        try:
            event = json.loads(raw)
        except ValueError:
            event = None
        name = event.get("hook_event_name") if isinstance(event, dict) else None
        if not isinstance(name, str):
            raise TaintFailure("tg-taint: событие хука не разобрать")
        if "tg-taint" not in OFF:
            out = handle(event)
            if out:
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        _stop_timer()
        sys.stdout.flush()
    except BaseException as e:  # любой сбой — по правилу события, а не молча
        try:
            _stop_timer()
            log_failure(name or "event", e)
            if name in ("UserPromptSubmit", "PostToolUse"):
                code = 0  # код 2 на UserPromptSubmit заблокировал бы сообщение владельца
                if name == "PostToolUse" and re.search(r"tg[-_]read", raw):
                    try:
                        sid = session_key(json.loads(raw))
                        if sid:
                            set_flag(sid, "сбой проверки tg-taint на вызове с tg-read")
                    except Exception:
                        pass
            else:
                code = 2
                sys.stderr.write(f"guard: сбой проверки tg-taint ({type(e).__name__}) — действие остановлено. "
                                 "Повтори проще или сообщи координатору.\n")
                sys.stderr.flush()
        finally:
            os._exit(code)
    os._exit(code)


if __name__ == "__main__":
    run_hook()
