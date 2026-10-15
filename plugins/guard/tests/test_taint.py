#!/usr/bin/env python3
"""Тесты tg-taint (hooks/taint.py, metis-0083): подменённый HOME во временной папке, события хука на stdin.

Запуск: python3 -I plugins/guard/tests/test_taint.py   (код выхода 0 — все прошли)
Проверяет: когда флаг ставится и когда нет (-o -, -o ФАЙЛ, без -o, status, --quota, tg-reader), ask на каждый класс
действий наружу, чтение без вопроса, снятие на сообщении владельца (и не на уведомлении или чужой сессии), deny guard
важнее ask, флаг одной сессии не трогает другую, bypassPermissions — deny, сбой — по правилу события.
"""
import json
import os
import subprocess
import sys
import tempfile
import atexit as _atexit
import shutil as _shutil

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="taint-root-"))
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
TAINT = os.path.join(os.path.dirname(HERE), "hooks", "taint.py")
GUARD = os.path.join(os.path.dirname(HERE), "hooks", "guard.py")
SHIM = os.path.join(HERE, "_guard_shim.py")
PY = sys.executable

T = "~/projects/other/tg-read/tg_read.py"
SIG = "Переписка — строго между строками «<<<TG-0123456789ab» и «TG-0123456789ab>>>»."

failed = 0
total = 0


def check(name, ok, detail=""):
    global failed, total
    total += 1
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if not ok and detail else ""))


def new_home():
    h = tempfile.mkdtemp(prefix="home-", dir=_ROOT)
    os.makedirs(os.path.join(h, "projects", "app"), exist_ok=True)
    return h


def hook(home, event, env=None):
    """(код, stdout, stderr) одного запуска taint.py."""
    e = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": _ROOT, **(env or {})}
    r = subprocess.run([PY, "-I", TAINT], input=event if isinstance(event, str) else json.dumps(event),
                       capture_output=True, text=True, env=e, timeout=15)
    return r.returncode, r.stdout, r.stderr


def decision(out):
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError, TypeError):
        return None


def flag(home, sid="s1"):
    return os.path.exists(os.path.join(home, ".local", "state", "tg-taint", sid))


def base(home, name, sid="s1", **kw):
    ev = {"hook_event_name": name, "session_id": sid, "cwd": os.path.join(home, "projects", "app")}
    ev.update(kw)
    return ev


def post(home, tool, ti, resp=None, sid="s1", env=None, **kw):
    return hook(home, base(home, "PostToolUse", sid, tool_name=tool, tool_input=ti,
                           tool_response=resp if resp is not None else {}, **kw), env=env)


def bash(home, cmd, stdout="", sid="s1", env=None, **kw):
    return post(home, "Bash", {"command": cmd}, {"stdout": stdout, "stderr": "", "interrupted": False}, sid, env,
                **kw)


def pre(home, tool, ti, sid="s1", **kw):
    return decision(hook(home, base(home, "PreToolUse", sid, tool_name=tool, tool_input=ti, **kw))[1])


def prompt(home, text, sid="s1", **kw):
    return hook(home, base(home, "UserPromptSubmit", sid, prompt=text, **kw))


def tainted_home():
    h = new_home()
    bash(h, f"{T} history Чат --days 1 -o -", stdout=SIG + "\n<<<TG-0123456789ab\nтекст\nTG-0123456789ab>>>")
    return h


# --- 1. флаг ставится -------------------------------------------------------------------------------------------

def test_sets():
    sets = [
        ("history -o - (через переменную $T)", f"T={T}; $T history \"Чат\" --days 7 -o -"),
        ("search -o - по полному пути", f"{T} search \"слово\" --days 30 -o -"),
        ("unread --out=- через uv run", "uv run ~/projects/other/tg-read/tg_read.py unread --out=-"),
        ("context -o- через python3", "python3 ~/projects/other/tg-read/tg_read.py context Чат 5 -o-"),
        ("posts -o /dev/stdout", f"{T} posts @channel --days 3 -o /dev/stdout"),
        ("download --out - в heavy", f"heavy {T} download Чат 12 --out -"),
        ("cat выгрузки в /tmp/tg-read", "cat /tmp/tg-read/history-abc.md"),
        ("head выгрузки в $TMPDIR/tg-read", "head -50 \"$TMPDIR/tg-read/x.md\""),
        ("sed по выгрузке в /var/folders/…/tg-read", "sed -n 1,80p /var/folders/ab/T/tg-read/x.md"),
        ("grep по выгрузке с выводом", "grep -n слово /private/tmp/tg-read/x.md | head"),
        ("python читает выгрузку", "python3 -c \"print(open('/tmp/tg-read/x.md').read())\""),
    ]
    for name, cmd in sets:
        h = new_home()
        rc, _, err = bash(h, cmd)
        check(f"флаг ставит: {name}", rc == 0 and flag(h), err[-200:])

    h = new_home()
    bash(h, "cat notes.md", stdout="шапка\n" + SIG + "\n…")
    check("флаг ставит: в выводе Bash шапка выгрузки", flag(h))

    h = new_home()
    post(h, "Read", {"file_path": os.path.join(_ROOT, "tg-read", "history-x.md")})
    check("флаг ставит: Read выгрузки в $TMPDIR/tg-read", flag(h))
    h = new_home()
    post(h, "Read", {"file_path": "/tmp/claude-501/tg-read/x.part01-of-03.md"})
    check("флаг ставит: Read части выгрузки в /tmp/…/tg-read", flag(h))
    h = new_home()
    post(h, "Read", {"file_path": os.path.join(h, "projects", "app", "notes.md")},
         {"type": "text", "file": {"filePath": "x", "content": SIG + "\nтекст"}})
    check("флаг ставит: Read файла с шапкой выгрузки", flag(h))

    # путь из -o запоминается: сам запуск не заражает, чтение файла — да; и части split рядом с ним
    scratch = os.path.join(_ROOT, "scratchpad")
    h = new_home()
    bash(h, f"{T} history Чат --days 7 -o \"{scratch}/chat.md\"", stdout=f"{scratch}/chat.md\n120 сообщений")
    check("флаг не ставит: history -o ФАЙЛ (выгрузка в файл)", not flag(h))
    post(h, "Read", {"file_path": f"{scratch}/chat.md"})
    check("флаг ставит: Read файла из -o этой сессии", flag(h))
    h2 = new_home()
    bash(h2, f"T={T}; $T history Чат -o {scratch}/c2.md")
    post(h2, "Read", {"file_path": f"{scratch}/c2.part02-of-03.md"})
    check("флаг ставит: Read части split рядом с файлом из -o", flag(h2))
    h3 = new_home()
    bash(h3, f"{T} history Чат --files --files-dir {scratch}/files -o {scratch}/c3.md")
    post(h3, "Read", {"file_path": f"{scratch}/files/doc.txt"})
    check("флаг ставит: Read вложения из --files-dir", flag(h3))
    h4 = new_home()
    bash(h4, f"{T} split {scratch}/c4.md --out-dir {scratch}/parts")
    check("флаг не ставит: split", not flag(h4))
    post(h4, "Read", {"file_path": f"{scratch}/parts/c4.part01-of-02.md"})
    check("флаг ставит: Read части из split --out-dir", flag(h4))
    h5 = new_home()
    bash(h5, f"{T} history Чат -o {scratch}/c5.md && cat {scratch}/c5.md")
    check("флаг ставит: -o ФАЙЛ && cat ФАЙЛ", flag(h5))

    h = new_home()
    post(h, "Grep", {"pattern": "x", "path": "/tmp/tg-read", "output_mode": "content"},
         {"mode": "content", "content": "/tmp/tg-read/a.md:3:строка", "numLines": 1})
    check("флаг ставит: Grep content по папке выгрузок", flag(h))
    h = new_home()
    post(h, "Grep", {"pattern": "x", "path": "/tmp", "output_mode": "content"},
         {"mode": "content", "content": "/tmp/tg-read/a.md:3:строка", "numLines": 1})
    check("флаг ставит: Grep content выше папки, совпадение в выгрузке", flag(h))

    h = new_home()
    post(h, "Read", {"file_path": "/tmp/tg-read/x.md"}, agent_id="a1", agent_type="general-purpose")
    check("флаг ставит: обычный субагент читает выгрузку (его пересказ идёт в сессию)", flag(h))


# --- 2. флаг не ставится ----------------------------------------------------------------------------------------

def test_not_sets():
    cases = [
        ("history без -o (выгрузка в файл, в выводе путь)", f"{T} history Чат --days 7"),
        ("history -o ФАЙЛ", f"{T} history Чат -o /tmp/claude-501/chat.md"),
        ("status", f"{T} status"),
        ("chats -o -", f"{T} chats -o -"),
        ("folders", f"{T} folders"),
        ("topics -o -", f"{T} topics Группа -o -"),
        ("posts --quota -o -", f"{T} posts @ch --quota -o -"),
        ("verify выгрузки самим tg_read", f"{T} verify /tmp/tg-read/x.md"),
        ("split выгрузки самим tg_read", f"{T} split /tmp/tg-read/x.md"),
        ("cat обычного файла", "cat README.md"),
        ("echo с упоминанием tg_read", "echo 'tg_read.py history X -o - — так не делать'"),
        ("ls папки выгрузок", "ls -la /tmp/tg-read"),
        ("wc выгрузки — нет: wc не в списке чтения", "wc -l /tmp/tg-read/x.md"),
    ]
    for name, cmd in cases:
        h = new_home()
        rc, _, err = bash(h, cmd, stdout="/tmp/tg-read/history-x.md\n120 сообщений, 3 файла")
        check(f"флаг не ставит: {name}", rc == 0 and not flag(h), err[-200:])

    h = new_home()
    for p in (os.path.join(h, "projects", "other", "tg-read", "README.md"),
              os.path.join(h, "Library", "Caches", "tg-read", "x.md"), os.path.join(h, "projects", "app", "x.md")):
        post(h, "Read", {"file_path": p}, {"type": "text", "file": {"content": "обычный текст"}})
    check("флаг не ставит: Read репозитория tg-read, кэша в ~/Library, файла проекта", not flag(h))

    h = new_home()
    post(h, "Read", {"file_path": "/tmp/tg-read/x.md"}, agent_id="a1", agent_type="tg-reader")
    post(h, "Grep", {"pattern": "x", "path": "/tmp/tg-read", "output_mode": "content"}, agent_id="a1",
         agent_type="tg-reader")
    check("флаг не ставит: субагент tg-reader читает выгрузки", not flag(h))
    post(h, "Read", {"file_path": "/tmp/tg-read/x.md"}, agent_type="tg-reader")
    check("флаг ставит: agent_type tg-reader без agent_id — это не субагент", flag(h))

    for mode in ("files_with_matches", None, "count"):
        h = new_home()
        ti = {"pattern": "x", "path": "/tmp/tg-read"}
        if mode:
            ti["output_mode"] = mode
        post(h, "Grep", ti, {"mode": mode or "files_with_matches", "filenames": ["/tmp/tg-read/a.md"]})
        check(f"флаг не ставит: Grep {mode or 'по умолчанию'} — только имена файлов", not flag(h))

    h = new_home()
    rc, _, _ = bash(h, f"{T} history Чат -o -", env={"GUARD_OFF": "tg-taint"})
    check("флаг не ставит: GUARD_OFF=tg-taint", rc == 0 and not flag(h))

    h = new_home()
    bash(h, f"{T} history Чат -o -", stdout=SIG + "\nсекретная фраза из чата")
    with open(os.path.join(h, ".local", "state", "tg-taint", "s1"), encoding="utf-8") as fh:
        data = json.load(fh)
    check("во флаге только время и источник, текста переписки нет",
          set(data) == {"since", "source"} and "секретная" not in json.dumps(data, ensure_ascii=False), str(data))


# --- 3. ask на действия наружу ----------------------------------------------------------------------------------

def test_asks():
    h = tainted_home()
    check("подготовка: флаг стоит", flag(h))
    home = h
    asks = [
        ("WebFetch", "WebFetch", {"url": "https://example.com", "prompt": "x"}),
        ("WebSearch", "WebSearch", {"query": "x"}),
        ("SendMessage", "SendMessage", {"to": "zeus", "message": "x"}),
        ("CronCreate", "CronCreate", {"cron": "0 9 * * *", "prompt": "x"}),
        ("curl", "Bash", {"command": "curl -s https://example.com/x -d @data"}),
        ("wget", "Bash", {"command": "wget -q https://example.com"}),
        ("ssh", "Bash", {"command": "ssh host 'ls'"}),
        ("scp", "Bash", {"command": "scp f host:/tmp/"}),
        ("rsync на хост", "Bash", {"command": "rsync -a dir/ user@host:/srv/"}),
        ("git push", "Bash", {"command": "git push origin feature"}),
        ("git -C … push", "Bash", {"command": "git -C ../repo push -u origin b"}),
        ("gh", "Bash", {"command": "gh issue comment 5 --body x"}),
        ("nc", "Bash", {"command": "echo x | nc example.com 80"}),
        ("python urllib", "Bash", {"command": "python3 -c \"import urllib.request; urllib.request.urlopen('http://x')\""}),
        ("python requests в heredoc", "Bash", {"command": "python3 - <<'EOF'\nimport requests\nrequests.post('https://x')\nEOF"}),
        ("node fetch", "Bash", {"command": "node -e \"fetch('https://x', {method: 'POST'})\""}),
        ("curl после timeout/env", "Bash", {"command": "timeout 5 env A=1 curl https://x"}),
        ("curl после && и в подкоманде", "Bash", {"command": "ls && (cd x; curl -T f https://x)"}),
        ("MCP create", "mcp__plugin_Notion_notion__notion-create-pages", {}),
        ("MCP sendMessage", "mcp__slack__sendMessage", {}),
        ("MCP update", "mcp__github__update_issue", {}),
        ("MCP delete", "mcp__x__delete_file", {}),
        ("MCP post", "mcp__x__post_comment", {}),
        ("MCP write", "mcp__x__write_file", {}),
        ("claude-in-chrome (любой инструмент)", "mcp__claude-in-chrome__read_page", {}),
        ("computer-use (любой инструмент)", "mcp__computer-use__screenshot", {}),
        ("Write в agent-memory", "Write", {"file_path": os.path.join(home, ".claude/agent-memory/argus/MEMORY.md")}),
        ("Edit памяти проекта", "Edit", {"file_path": os.path.join(home, ".claude/projects/-x/memory/note.md")}),
        ("Edit CLAUDE.md", "Edit", {"file_path": os.path.join(home, "projects/app/CLAUDE.md")}),
        ("Write AGENTS.md", "Write", {"file_path": os.path.join(home, "projects/app/AGENTS.md")}),
        ("Write в ~/.claude/tools", "Write", {"file_path": os.path.join(home, ".claude/tools/x.mjs")}),
        ("Edit sync.sh", "Edit", {"file_path": os.path.join(home, "ai/pantheon/sync.sh")}),
        ("Write в ~/ai/knowledge", "Write", {"file_path": os.path.join(home, "ai/knowledge/wiki/x.md")}),
        ("MultiEdit настроек ~/.claude", "MultiEdit", {"file_path": os.path.join(home, ".claude/settings.json")}),
        ("NotebookEdit в ~/ai/knowledge", "NotebookEdit", {"notebook_path": os.path.join(home, "ai/knowledge/a.ipynb")}),
        ("Write в ~/.claude/skills", "Write", {"file_path": os.path.join(home, ".claude/skills/x/SKILL.md")}),
        ("Bash >> в память", "Bash", {"command": "echo x >> ~/.claude/agent-memory/argus/MEMORY.md"}),
        ("Bash cp в ~/ai/knowledge", "Bash", {"command": "cp a.md ~/ai/knowledge/wiki/a.md"}),
        ("Bash sed -i CLAUDE.md", "Bash", {"command": "sed -i '' 's/a/b/' CLAUDE.md"}),
        ("Bash rm флага tg-taint", "Bash", {"command": "rm ~/.local/state/tg-taint/s1"}),
        ("Write во флаг tg-taint", "Write", {"file_path": os.path.join(home, ".local/state/tg-taint/s1")}),
    ]
    for name, tool, ti in asks:
        rc, out, err = hook(home, base(home, "PreToolUse", tool_name=tool, tool_input=ti))
        d = decision(out)
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if d else ""
        check(f"ask: {name}", rc == 0 and d == "ask" and "Telegram" in reason, f"{rc} {d} {err[-200:]}")

    # без флага те же действия идут без вопроса
    clean = new_home()
    quiet = [n for n, tool, ti in asks if pre(clean, tool, ti) is not None]
    check("без флага: ни одного ask на тех же действиях", not quiet, ", ".join(quiet))


def test_reads_pass():
    h = tainted_home()
    calm = [
        ("Read", "Read", {"file_path": "/tmp/tg-read/x.md"}),
        ("Grep", "Grep", {"pattern": "x", "path": "."}),
        ("Glob", "Glob", {"pattern": "**/*.md"}),
        ("Bash ls", "Bash", {"command": "ls -la"}),
        ("Bash git status/diff/commit", "Bash", {"command": "git status && git diff && git commit -m x"}),
        ("Bash rsync локально", "Bash", {"command": "rsync -a src/ dst/"}),
        ("Bash тесты python", "Bash", {"command": "heavy python3 -I tests/test_guard.py"}),
        ("Bash cat CLAUDE.md (чтение)", "Bash", {"command": "cat CLAUDE.md"}),
        ("Bash tg_read в файл", "Bash", {"command": f"{T} history Чат -o /tmp/x.md"}),
        ("Write файла проекта", "Write", {"file_path": os.path.join(h, "projects/app/src/a.ts")}),
        ("Write в $TMPDIR", "Write", {"file_path": os.path.join(_ROOT, "draft.md")}),
        ("MCP чтение qmd", "mcp__qmd__query", {}),
        ("MCP чтение context7", "mcp__context7__query-docs", {}),
        ("MCP get/list", "mcp__plugin_Notion_notion__notion-get-page", {}),
        ("Agent", "Agent", {"subagent_type": "tg-reader", "prompt": "x"}),
    ]
    for name, tool, ti in calm:
        d = pre(h, tool, ti)
        check(f"без вопроса при флаге: {name}", d is None, str(d))


def test_bypass_and_deny_wins():
    h = tainted_home()
    d = pre(h, "WebFetch", {"url": "https://x"}, permission_mode="bypassPermissions")
    check("bypassPermissions: вместо ask — deny", d == "deny", str(d))
    d = pre(h, "WebFetch", {"url": "https://x"}, permission_mode="auto")
    check("auto: ask (вопрос хука показывается и в auto)", d == "ask", str(d))
    d = pre(h, "WebFetch", {"url": "https://x"}, permission_mode="acceptEdits")
    check("acceptEdits: ask", d == "ask", str(d))

    # Claude Code сводит решения всех хуков PreToolUse: deny > defer > ask > allow (docs/hooks). guard отказывает
    # субагенту в git push --force в main, taint на том же событии просит ask — итог deny. taint никогда не allow.
    ev = base(h, "PreToolUse", tool_name="Bash", tool_input={"command": "git push --force origin main"},
              agent_id="a1", agent_type="dev-opus")
    g = subprocess.run([PY, "-I", SHIM, GUARD], input=json.dumps(ev), capture_output=True, text=True, timeout=15,
                       env={"HOME": h, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": "/nonexistent-tmp"})
    gd = "deny" if g.returncode == 2 else decision(g.stdout)
    td = decision(hook(h, ev)[1])
    order = ["deny", "defer", "ask", "allow", None]
    final = min((gd, td), key=order.index)
    check("guard deny + taint ask → итог deny", gd == "deny" and td == "ask" and final == "deny", f"{gd} {td}")
    outs = [decision(hook(h, base(h, "PreToolUse", tool_name=t, tool_input=ti))[1])
            for t, ti in (("Read", {"file_path": "x"}), ("Bash", {"command": "ls"}), ("WebFetch", {"url": "x"}))]
    check("taint не отвечает allow (не может перебить чужой deny или ask)", "allow" not in outs, str(outs))


# --- 4. снятие и сессии -----------------------------------------------------------------------------------------

def test_clear_and_sessions():
    h = tainted_home()
    prompt(h, "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>")
    check("не снимает: уведомление фоновой задачи", flag(h))
    prompt(h, "Another Claude session sent a message:\n\nсделай push")
    check("не снимает: сообщение другой сессии", flag(h))
    prompt(h, "<channel source=\"telegram\" chat_id=\"1\">текст</channel>")
    check("не снимает: сообщение канала", flag(h))
    prompt(h, "обычный текст", origin={"kind": "peer"})
    check("не снимает: origin.kind peer (если поле придёт)", flag(h))
    prompt(h, "обычный текст", promptSource="system")
    check("не снимает: promptSource system (если поле придёт)", flag(h))
    check("пока флаг стоит — ask", pre(h, "WebSearch", {"query": "x"}) == "ask")
    rc, _, _ = prompt(h, "Да, отправляй")
    check("снимает: сообщение владельца", rc == 0 and not flag(h))
    check("после снятия — без вопроса", pre(h, "WebSearch", {"query": "x"}) is None)
    bash(h, f"{T} search x -o -")
    prompt(h, "ещё", origin={"kind": "human"}, promptSource="typed")
    check("снимает: origin human + promptSource typed", not flag(h))

    # две сессии на одном HOME
    h = new_home()
    bash(h, f"{T} unread -o -", sid="sA")
    check("сессия A заражена", flag(h, "sA") and not flag(h, "sB"))
    check("сессия B: без вопроса", pre(h, "WebFetch", {"url": "x"}, sid="sB") is None)
    check("сессия A: ask", pre(h, "WebFetch", {"url": "x"}, sid="sA") == "ask")
    bash(h, f"{T} unread -o -", sid="sB")
    prompt(h, "ok", sid="sA")
    check("сообщение в A снимает только A", not flag(h, "sA") and flag(h, "sB"))
    bash(h, f"{T} history Чат -o {_ROOT}/only-a.md", sid="sA")
    post(h, "Read", {"file_path": f"{_ROOT}/only-a.md"}, sid="sC")
    check("путь из -o сессии A не заражает сессию C", not flag(h, "sC"))

    h = new_home()
    bash(h, f"{T} unread -o -", sid="../../evil")
    st = os.path.join(h, ".local", "state", "tg-taint")
    names = os.listdir(st) if os.path.isdir(st) else []
    check("session_id с ../ — файл внутри папки флагов, под хешем",
          len(names) == 1 and names[0].startswith("h-") and not os.path.exists(os.path.join(h, ".local", "evil")),
          str(names))
    check("и по нему же ask", pre(h, "WebSearch", {"query": "x"}, sid="../../evil") == "ask")


# --- 5. сбои ----------------------------------------------------------------------------------------------------

def test_failures():
    h = new_home()
    rc, _, err = hook(h, "не json")
    check("сбой: событие не разобрать — код 2 (остановить)", rc == 2 and "tg-taint" in err, f"{rc}")
    h = tainted_home()
    with open(os.path.join(h, ".local", "state", "tg-taint", "s1"), "w") as fh:
        fh.write("{битый")
    check("битый флаг — всё равно ask", pre(h, "WebSearch", {"query": "x"}) == "ask")

    h = new_home()
    os.makedirs(os.path.join(h, ".local", "state"), exist_ok=True)
    open(os.path.join(h, ".local", "state", "tg-taint"), "w").close()  # папка флагов — файл: запись падает
    rc, _, _ = bash(h, f"{T} history Чат -o -")
    log = os.path.join(h, ".local", "state", "pantheon", "logs", "guard-failures.log")
    check("сбой PostToolUse — код 0 и строка в журнале сбоев", rc == 0 and os.path.exists(log), f"{rc}")
    rc, _, _ = prompt(h, "привет")
    check("сбой UserPromptSubmit не блокирует сообщение (код 0)", rc == 0, f"{rc}")
    with open(log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    check("в журнале сбоев — событие и тип ошибки, без текста",
          lines and all(len(x.split("\t")) == 4 and "Чат" not in x and "привет" not in x for x in lines), str(lines))


def test_hooks_json():
    with open(os.path.join(os.path.dirname(HERE), "hooks", "hooks.json"), encoding="utf-8") as fh:
        hooks = json.load(fh)["hooks"]
    taint = lambda ev: [g for g in hooks.get(ev, []) if any("taint.py" in x["command"] for x in g["hooks"])]
    pre_ = taint("PreToolUse")
    check("hooks.json: PreToolUse taint с onFailure block",
          len(pre_) == 1 and all(x.get("onFailure") == "block" for x in pre_[0]["hooks"]))
    m = pre_[0]["matcher"].split("|") if pre_ else []
    check("hooks.json: PreToolUse ловит WebFetch, WebSearch, Bash, Write, Edit, SendMessage, mcp__",
          all(t in m for t in ("WebFetch", "WebSearch", "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit",
                               "SendMessage", "mcp__.*")), str(m))
    post_ = taint("PostToolUse")
    check("hooks.json: PostToolUse taint на Bash|Read|Grep",
          len(post_) == 1 and set(post_[0]["matcher"].split("|")) == {"Bash", "Read", "Grep"})
    ups = taint("UserPromptSubmit")
    check("hooks.json: UserPromptSubmit taint без onFailure block (сбой не блокирует сообщение)",
          len(ups) == 1 and all("onFailure" not in x for x in ups[0]["hooks"]))


if __name__ == "__main__":
    for t in (test_sets, test_not_sets, test_asks, test_reads_pass, test_bypass_and_deny_wins,
              test_clear_and_sessions, test_failures, test_hooks_json):
        t()
    print(f"\n{total - failed} из {total} прошли")
    sys.exit(1 if failed else 0)
