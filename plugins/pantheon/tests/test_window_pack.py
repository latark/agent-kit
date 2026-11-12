#!/usr/bin/env python3
"""Окно направления по схеме А и его пакет (metis-0933, решение владельца 06.11 17:42 «А — окно направления»).

Запуск: python3 -I plugins/pantheon/tests/test_window_pack.py  (код выхода 0 — все прошли)
- `pantheon start <направление> --dry-run` на временном HOME: argv окна — --add-dir на остальные папки направления и
  на вложенные проекты (app/ с CLAUDE.md, AGENTS.md или .claude), без node_modules и скрытых; один
  --append-system-prompt-file с AGENTS.md всех этих папок (флаг не повторяется: второй затирает первый); AGENTS.md
  папки запуска, которую её CLAUDE.md импортирует, — не дублируется; --plugin-dir и --mcp-config пакета, если есть;
  всё до --settings; без пакета — без --plugin-dir;
- пакеты — данные пользователя (решение владельца 12.11): читаются из ~/.claude/pantheon/packs/<направление>/ (HOME
  теста); папки пакетов нет совсем — окно запускается и собирается без пакета; в плагине пакетов направлений нет,
  только общий packs/_bin;
- перенос из прежней версии плагина (`pantheon packs migrate`, шаг domains build): берётся самая новая версия с
  пакетами, существующий пакет и личная карта не затираются, ссылка источника не копируется, после отметки
  удалённый пакет не возвращается; коды выхода 0, 1 и 2; правка window.json пакета — пересборка по --if-changed;
- [auto_rules] policy.toml: правила autoMode.allow направления по именам, неизвестное имя — тревога;
- граница ядра (класс 5): argv запуска окна целиком собирает P.window_launch, флагов запуска (LAUNCH_FLAGS) в lib/ и
  scripts/ вне pantheon.py нет; PANTHEON_PACKS окружения пакеты не подменяет;
- `pantheon domains build`: окно направления — CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1, deny EnterWorktree и
  ExitWorktree, window.json пакета (ask, deny, plugins, env, sandbox); allow (metis-0137) и неизвестный ключ —
  не влиты, окно собрано; мастерская — без этого;
- `pantheon check`: хук и сервер .mcp.json вложенного проекта без строки в пакете — «предупреждение · окно …»; после
  записи в seen и сервера в mcp.json пакета — тишина; настройки папки запуска не предупреждают; код выхода тот же;
- обёртка packs/_bin/in_repo.py: цель вне репозитория — не запускает, внутри — cwd и CLAUDE_PROJECT_DIR репозитория,
  путь файла аргументом (--file-arg), код выхода как есть, --ok — 0; --cmd-prefix — только Bash с этим началом;
- образцы пакетов (tests/fixtures/packs): JSON читается, window.json вливается без отброшенного, хуки — через
  in_repo.py; по решению владельца 06.11 18:30 нет git push, python, pip, docker, brew в allow, bypassPermissions и
  токенов, supabase — только с protect-db.sh.
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import importlib.util
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

RUN_PY = os.path.join(PLUGIN, "lib", "run.py")
IN_REPO = os.path.join(PLUGIN, "packs", "_bin", "in_repo.py")
FIXTURES = os.path.join(HERE, "fixtures", "packs")
ROOT = os.path.realpath(mkroot("winpack-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else "\n     " + str(info)[-1500:]))


def put(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text if isinstance(text, str) else json.dumps(text))


def after(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    packs = os.path.join(tmp, ".claude", "pantheon", "packs")  # данные пользователя, от HOME (решение владельца 12.11)
    decoy = os.path.join(tmp, "decoy-packs")
    ms, side = os.path.join(tmp, "projects/ms"), os.path.join(tmp, "projects/side")
    put(os.path.join(ms, "CLAUDE.md"), "@AGENTS.md\n")
    put(os.path.join(ms, "AGENTS.md"), "LAUNCH-RULES\n")
    put(os.path.join(ms, ".claude/settings.json"), {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                                                                   "command": "launch-hook"}]}]}})
    put(os.path.join(ms, "app/AGENTS.md"), "APP-RULES\n")
    put(os.path.join(ms, "app/.claude/settings.json"), {"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": "bash .claude/hooks/x.sh"}]}]},
        "enabledPlugins": {"p@m": True}})
    put(os.path.join(ms, "app/.mcp.json"), {"mcpServers": {"srv": {"command": "x"}}})
    put(os.path.join(ms, "worker/.claude/skills/s/SKILL.md"), "---\nname: s\ndescription: d\n---\n")
    put(os.path.join(ms, "node_modules/CLAUDE.md"), "no\n")
    put(os.path.join(ms, ".hidden/CLAUDE.md"), "no\n")
    put(os.path.join(ms, "plain/readme.txt"), "no\n")
    put(os.path.join(side, "AGENTS.md"), "SIDE-RULES\n")
    os.makedirs(os.path.join(tmp, "projects/solo"))
    for d in ("projects/workshop", ".claude/pantheon"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    put(os.path.join(home, "directions.toml"),
        '[[direction]]\nname = "proteus-ms"\nfolders = ["~/projects/ms", "~/projects/side"]\n'
        '[[direction]]\nname = "athena-solo"\nfolders = ["~/projects/solo"]\n')
    pack = os.path.join(packs, "proteus-ms")
    put(os.path.join(pack, ".claude-plugin/plugin.json"), {"name": "pack-proteus-ms"})
    put(os.path.join(pack, "mcp.json"), {"mcpServers": {}})
    put(os.path.join(pack, "window.json"), {
        "allow": ["Bash(uv sync *)", "Bash(gh pr merge *)"], "ask": ["Bash(codesign *)"],
        "deny": ["Bash(docker rm *)"], "plugins": ["pyright-lsp@claude-plugins-official", "p@m", "bad id",
                                                   "notion@anthropic-plugin-directory"],
        "env": {"HF_HUB_DISABLE_TELEMETRY": "1", "PACK_ENV": "1", "GUARD_OFF": "1"},
        "sandbox": {"denyRead": ["~/Library/Mail"], "deniedDomains": ["mail.example"], "excludedCommands": ["mk *"]},
        "strange": 1, "seen": {}})
    # какие правила autoMode.allow направления включены — данные пользователя: [auto_rules] его policy.toml
    put(os.path.join(tmp, ".claude", "pantheon", "policy.toml"),
        '[auto_rules]\nproteus-ms = ["uv-sync"]\nathena-solo = ["no-such-rule"]\n')
    bindir = os.path.join(tmp, "bin")
    put(os.path.join(bindir, "claude"), "#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp"),
           "PANTHEON_PACKS": decoy}  # класс 5: окружение не меняет, откуда пакеты, — приманка не должна попасть в argv
    put(os.path.join(decoy, "proteus-ms", ".claude-plugin/plugin.json"), {"name": "decoy"})
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])
    run = lambda *a: subprocess.run([sys.executable, "-I", RUN_PY, *a], env=env, capture_output=True,  # noqa: E731
                                    text=True, timeout=120)
    r = run("domains", "build")
    check("сборка прошла", r.returncode == 0, r.stderr)
    # прежних пакетов рядом с плагином теста нет: отметка переноса — чтобы не искать их на каждой сборке; пакет цел
    check("сборка: прежних пакетов нет — отметка .migrated.json в папке пакетов, свой пакет не тронут",
          os.path.isfile(os.path.join(packs, ".migrated.json"))
          and json.load(open(os.path.join(pack, "window.json"))).get("strange") == 1, os.listdir(packs))
    real = lambda p: os.path.realpath(os.path.join(tmp, p))  # noqa: E731

    # --- запуск окна (pantheon start --dry-run печатает argv) ---
    r = run("start", "proteus-ms", "x", "--from", "zeus", "--dry-run")
    line = next((x for x in r.stdout.splitlines() if " --settings " in x), "")
    import shlex
    argv = shlex.split(line.rsplit(" (папка ", 1)[0]) if line else []
    check("start --dry-run напечатал запуск окна", argv and argv[0].endswith("claude"), (r.stdout, r.stderr))
    dirs = after(argv, "--add-dir")
    check("--add-dir: вторая папка и вложенные проекты app/ и worker/, по порядку",
          dirs == [real("projects/ms/app"), real("projects/ms/worker"), real("projects/side")], dirs)
    check("--add-dir: без папки запуска, node_modules, скрытых и подпапок без меток проекта",
          not {real("projects/ms"), real("projects/ms/node_modules"), real("projects/ms/.hidden"),
               real("projects/ms/plain")} & set(dirs), dirs)
    files = after(argv, "--append-system-prompt-file")
    text = open(files[0], encoding="utf-8").read() if len(files) == 1 and os.path.isfile(files[0]) else ""
    check("AGENTS.md — один --append-system-prompt-file со всеми папками --add-dir",
          len(files) == 1 and "APP-RULES" in text and "SIDE-RULES" in text, (files, text))
    check("AGENTS.md папки запуска с @AGENTS.md в CLAUDE.md не дублируется", "LAUNCH-RULES" not in text, text)
    check("файл AGENTS.md окна — в settings/run, не в репозитории",
          files and files[0] == os.path.join(state, "settings", "run", "proteus-ms.agents.md"), files)
    snaps = os.path.join(state, "settings", "run", "packs")
    plug = after(argv, "--plugin-dir")
    snap = os.path.dirname(plug[0]) if len(plug) == 1 else ""
    check("--plugin-dir — плагин пакета из снимка settings/run/packs/<окно>-<хеш> (круг F), не packs/; "
          "--mcp-config — его mcp.json, собранный ядром в settings/run",
          plug == [os.path.join(snap, "plugin")] and os.path.dirname(snap) == snaps
          and re.fullmatch(r"proteus-ms-[0-9a-f]{16}", os.path.basename(snap))
          and open(os.path.join(snap, "plugin", ".claude-plugin", "plugin.json")).read()
          == open(os.path.join(pack, ".claude-plugin", "plugin.json")).read()
          and after(argv, "--mcp-config") == [os.path.join(state, "settings", "run", "proteus-ms.mcp.json")], argv)
    s = argv.index("--settings") if "--settings" in argv else -1
    check("флаги схемы А — до --settings, текст поручения последним",
          s > max(i for i, a in enumerate(argv) if a in ("--add-dir", "--plugin-dir", "--mcp-config"))
          and "поручение от zeus] x" in argv[-1] and s == len(argv) - 3, argv)
    r2 = run("start", "athena-solo", "x", "--from", "zeus", "--dry-run")
    check("направление без пакета и без других папок — без --add-dir, --plugin-dir, AGENTS.md",
          " --settings " in r2.stdout and not any(f in r2.stdout for f in ("--add-dir", "--plugin-dir",
                                                                           "--append-system-prompt-file")),
          (r2.stdout, r2.stderr))
    put(os.path.join(ms, "CLAUDE.md"), "свой текст\n")
    r3 = run("start", "proteus-ms", "x", "--from", "zeus", "--dry-run")
    text = open(os.path.join(state, "settings", "run", "proteus-ms.agents.md"), encoding="utf-8").read()
    check("CLAUDE.md папки запуска без @AGENTS.md — её AGENTS.md в общем файле", "LAUNCH-RULES" in text,
          (r3.stdout, text))
    put(os.path.join(ms, "CLAUDE.md"), "@AGENTS.md\n")

    # --- окно (domains build) ---
    win = json.load(open(os.path.join(state, "settings", "proteus-ms.json")))
    perms = win.get("permissions") or {}
    check("env CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1",
          (win.get("env") or {}).get("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD") == "1", win.get("env"))
    check("deny EnterWorktree и ExitWorktree (П9b)",
          {"EnterWorktree", "ExitWorktree"} <= set(perms.get("deny") or []), perms.get("deny"))
    check("window.json: ask и deny пакета влиты",
          perms.get("ask") == ["Bash(codesign *)"]
          and "Bash(docker rm *)" in perms.get("deny", []), perms)
    check("window.json: allow пакета не влит совсем — permissions.allow окна пуст (metis-0137), окно собрано",
          not perms.get("allow"), perms.get("allow"))
    ep = win.get("enabledPlugins") or {}
    check("window.json: сужающее влито — плагин карты окна, env из белого списка, denyRead, deniedDomains",
          ep.get("pyright-lsp@claude-plugins-official") is True and win["env"].get("HF_HUB_DISABLE_TELEMETRY") == "1"
          and "~/Library/Mail" in win["sandbox"]["filesystem"]["denyRead"]
          and "mail.example" in win["sandbox"]["network"].get("deniedDomains", []), (ep, win["env"], win["sandbox"]))
    # класс 1 модели угроз metis-0933: прежде здесь требовалось, чтобы «mk *» влилось, — тест закреплял дыру
    check("window.json: excludedCommands, env вне белого списка, плагин вне карты окна и кривой id — не влиты",
          "mk *" not in win["sandbox"]["excludedCommands"] and "PACK_ENV" not in win["env"]
          and "GUARD_OFF" not in win["env"] and ep.get("p@m") is None and "bad id" not in ep
          and ep.get("notion@anthropic-plugin-directory") is not True, (ep, win["env"], win["sandbox"]))
    alerts = open(os.path.join(home, "alerts.md"), encoding="utf-8").read() \
        if os.path.isfile(os.path.join(home, "alerts.md")) else ""
    check("отброшенное из window.json названо тревогой", "packs/proteus-ms/window.json" in alerts
          and "gh pr merge" in alerts and "strange" in alerts and "sandbox.excludedCommands" in alerts
          and "env.GUARD_OFF" in alerts,
          alerts[-800:])
    solo = json.load(open(os.path.join(state, "settings", "athena-solo.json")))
    check("окно без пакета: deny EnterWorktree тоже есть, allow пакета — нет",
          "EnterWorktree" in solo["permissions"]["deny"] and "Bash(uv sync *)" not in solo["permissions"].get("allow", []),
          solo["permissions"])
    ws = json.load(open(os.path.join(state, "settings", "workshop.json")))
    check("мастерская — без переменной add-dir и без deny EnterWorktree",
          "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD" not in (ws.get("env") or {})
          and "EnterWorktree" not in (ws.get("permissions") or {}).get("deny", []), ws.get("permissions"))
    rules = lambda w: [x.split(":", 1)[0] for x in (w.get("autoMode") or {}).get("allow", [])]  # noqa: E731
    check("[auto_rules] policy.toml: направлению — названное правило autoMode.allow, и только оно из правил направлений",
          "Pantheon Uv Sync" in rules(win) and "Pantheon Git Remote" not in rules(win)
          and "Pantheon Mailkeeper Read" not in rules(win), rules(win))
    check("[auto_rules] policy.toml: неизвестное имя правила — не взято, окно собрано, тревога с этим именем",
          not {"Pantheon Uv Sync", "Pantheon Git Remote", "Pantheon Mailkeeper Read"} & set(rules(solo))
          and "[auto_rules]" in alerts and "no-such-rule" in alerts, (rules(solo), alerts[-600:]))

    # --- правка пакета в данных пользователя → пересборка окна по --if-changed (плановый проход) ---
    run("domains", "build", "--if-changed")  # прочее новое (запуски выше) — в эту сборку, следующую будит только пакет
    w = json.load(open(os.path.join(pack, "window.json")))
    put(os.path.join(pack, "window.json"), dict(w, deny=w["deny"] + ["Bash(docker rmi *)"]))
    later = os.path.getmtime(os.path.join(state, "settings", "proteus-ms.json")) + 5
    os.utime(os.path.join(pack, "window.json"), (later, later))
    r = run("domains", "build", "--if-changed")
    win = json.load(open(os.path.join(state, "settings", "proteus-ms.json")))
    check("domains build --if-changed: правка window.json пакета в ~/.claude/pantheon/packs пересобирает окно",
          r.returncode == 0 and "Bash(docker rmi *)" in win["permissions"]["deny"], (r.stderr, win["permissions"]))
    put(os.path.join(pack, "window.json"), w)

    # --- pantheon check: что из вложенных проектов не учтено в пакете ---
    r = run("check")
    warn = [x for x in r.stdout.splitlines() if x.startswith("предупреждение · окно proteus-ms")]
    check("check: хук, ключ settings и сервер .mcp.json вложенного проекта без пакета — предупреждения",
          any("app/.claude/settings.json hooks.PostToolUse bash .claude/hooks/x.sh" in x for x in warn)
          and any("enabledPlugins.p@m" in x for x in warn) and any("app/.mcp.json srv" in x for x in warn), r.stdout)
    check("check: настройки папки запуска не предупреждают", not any("launch-hook" in x for x in warn), warn)
    w = json.load(open(os.path.join(pack, "window.json")))
    w["seen"] = {"~/projects/ms/app/.claude/settings.json hooks.PostToolUse bash .claude/hooks/x.sh": "перенесено",
                 "~/projects/ms/app/.claude/settings.json enabledPlugins.p@m": "перенесено"}
    put(os.path.join(pack, "window.json"), w)
    put(os.path.join(pack, "mcp.json"), {"mcpServers": {"srv": {"command": "x"}}})
    r2 = run("check")
    check("check: учтено в seen и в mcp.json пакета — тишина, код выхода тот же",
          "предупреждение · окно proteus-ms" not in r2.stdout and r2.returncode == r.returncode, (r2.stdout, r.returncode))

    # --- обёртка in_repo.py ---
    repo = os.path.join(tmp, "projects/ms/app")
    probe = os.path.join(tmp, "probe.sh")
    put(probe, 'pwd > "$OUT"; echo "$CLAUDE_PROJECT_DIR|$CLAUDE_FILE_PATH|$1" >> "$OUT"; cat >> "$OUT"; exit 3\n')
    out = os.path.join(tmp, "probe.out")
    wenv = dict(os.environ, OUT=out)

    def wrap(target, *flags, cwd=tmp, ti=None):
        if os.path.exists(out):
            os.remove(out)
        inp = json.dumps({"cwd": cwd, "tool_input": ti if ti is not None else {"file_path": target}})
        r = subprocess.run([sys.executable, "-I", IN_REPO, repo, *flags, "--", "sh", probe], input=inp, env=wenv,
                           capture_output=True, text=True, timeout=30)
        return r.returncode, (open(out).read() if os.path.exists(out) else None)

    code, got = wrap(os.path.join(side, "f.py"))
    check("in_repo: цель вне репозитория — команда не запущена, выход 0", code == 0 and got is None, (code, got))
    code, got = wrap("projects/ms/app/src/a.ts", "--file-arg")
    f = os.path.realpath(os.path.join(repo, "src/a.ts"))
    check("in_repo: цель внутри — cwd, CLAUDE_PROJECT_DIR, CLAUDE_FILE_PATH и аргумент; stdin тот же; код как есть",
          code == 3 and got and got.splitlines()[0] == os.path.realpath(repo)
          and got.splitlines()[1] == f"{os.path.realpath(repo)}|{f}|{f}" and '"file_path"' in got, (code, got))
    code, got = wrap(os.path.join(side, "f.py"), "--always", "--ok")
    check("in_repo: --always запускает и вне репозитория, --ok — выход 0", code == 0 and got is not None, (code, got))
    pre = "--cmd-prefix=git commit"
    code, got = wrap("", pre, cwd=repo, ti={"command": "git commit -m x"})
    check("in_repo: --cmd-prefix — команда с этим началом в репозитории запускает хук", code == 3 and got, (code, got))
    code, got = wrap("", pre, cwd=repo, ti={"command": "git commitx; ls"})
    code2, got2 = wrap("", pre, cwd=repo, ti={"command": "ls"})
    check("in_repo: --cmd-prefix — другая команда (и похожее начало) — хук не запущен, выход 0",
          (code, got, code2, got2) == (0, None, 0, None), (code, got, code2, got2))
    code, got = wrap("", pre, cwd=side, ti={"command": "git commit -m x"})
    check("in_repo: --cmd-prefix — git commit вне репозитория — хук не запущен", (code, got) == (0, None), (code, got))
    r = subprocess.run([sys.executable, "-I", RUN_PY, "start", "proteus-ms", "x", "--from", "zeus", "--dry-run"],
                       env=env, capture_output=True, text=True, timeout=120)
    check("PANTHEON_PACKS окружения не подменяет пакеты: обычный запуск pantheon не берёт пакет-приманку",
          " --settings " in r.stdout and decoy not in r.stdout, (r.stdout, r.stderr))
    r = run("start", "zeus", "--dry-run")
    line = next((x for x in r.stdout.splitlines() if " --settings " in x), "")
    check("штаб: start zeus --dry-run — тот же запуск через window_launch, без --bg и флагов схемы А",
          shlex.split(line.rsplit(" (папка ", 1)[0])[1:] == ["--agent", "hq", "--name", "zeus", "--settings",
                                                              os.path.join(state, "settings", "hq.json")],
          (r.stdout, r.stderr))

    # --- папки пакетов нет совсем (новый пользователь): окно запускается и собирается без пакета ---
    off = os.path.join(tmp, "packs-off")
    os.rename(packs, off)
    r = run("start", "proteus-ms", "x", "--from", "zeus", "--dry-run")
    check("папки ~/.claude/pantheon/packs нет — start окна без --plugin-dir, без падения",
          r.returncode == 0 and " --settings " in r.stdout and "--plugin-dir" not in r.stdout, (r.stdout, r.stderr))
    r = run("domains", "build")
    win = json.load(open(os.path.join(state, "settings", "proteus-ms.json")))
    check("папки пакетов нет — сборка окон проходит, window.json пакета не влит",
          r.returncode == 0 and "Bash(codesign *)" not in (win["permissions"].get("ask") or []),
          (r.stderr, win["permissions"]))
    shutil.rmtree(packs, True)
    os.rename(off, packs)

    launch_only_in_core()
    no_packs_in_plugin()
    fixture_packs(tmp)
    migration(tmp, env)
    return all(results)


# Флаги, которыми запуск окна подключает своё к сессии (настройки, плагин, MCP, папки, системный текст, режим прав).
# Класс 5 «граница ядра» (ревью #372 Д2): собирает их только pantheon.py (window_launch и job-окна), модуль вне ядра
# дописал бы --plugin-dir или --mcp-config без Touch ID — и хуки пошли бы вне песочницы.
LAUNCH_FLAGS = ("--settings", "--plugin-dir", "--mcp-config", "--add-dir", "--append-system-prompt", "--system-prompt",
                "--setting-sources", "--permission-mode", "--dangerously-skip-permissions", "--allowedTools",
                "--allowed-tools", "--disallowedTools")  # --strict-mcp-config сужает (читатель read.py) — можно


def launch_only_in_core():
    """Ни один флаг запуска окна (LAUNCH_FLAGS) не собирается в lib/ и scripts/ вне pantheon.py: строковые константы
    AST, в том числе куски f-строк; sessions.py запуск окна берёт целиком у P.window_launch."""
    import ast
    hits, calls = [], 0
    for sub in ("lib", "scripts"):
        for fn in sorted(os.listdir(os.path.join(PLUGIN, sub))):
            if not fn.endswith(".py") or (sub, fn) == ("lib", "pantheon.py"):
                continue
            p = os.path.join(PLUGIN, sub, fn)
            with open(p, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), p)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and any(node.value.lstrip().startswith(f) for f in LAUNCH_FLAGS):
                    hits.append(f"{sub}/{fn}:{node.lineno} {node.value[:40]!r}")
                if fn == "sessions.py" and isinstance(node, ast.Attribute) and node.attr == "window_launch":
                    calls += 1
    check("флаги запуска окна (--settings, --plugin-dir, --mcp-config, …) не собираются вне pantheon.py", not hits, hits)
    check("sessions.py: все три запуска окна (свежий, start, штаб) — через P.window_launch", calls == 3, calls)


# Решение владельца 06.11 18:30 «А — опасное заменить, мёртвое убрать»: в пакеты не идут
FORBIDDEN_ALLOW = ("git push", "Bash(python", "Bash(pip", "Bash(docker", "brew install", "gh pr merge")
FORBIDDEN_TEXT = ("bypassPermissions", "defaultMode", "Bearer", "hf_", "/Users/", '"enabled": false')


def no_packs_in_plugin():
    """Пакеты направлений — данные пользователя: в плагине только общий код пакетов packs/_bin, папок направлений нет."""
    got = sorted(n for n in os.listdir(os.path.join(PLUGIN, "packs")) if n != "_bin" and not n.startswith("."))
    check("в плагине нет пакетов направлений: plugins/pantheon/packs — только _bin", not got, got)


def fixture_packs(tmp):
    """Образцы пакетов (tests/fixtures/packs): JSON читается, window.json вливается без отброшенного, хуки — через
    in_repo.py пакета, опасного по решению владельца нет. Тот же разбор пакет пользователя проходит при сборке окна."""
    os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "pantheon"))
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    import pantheon as P
    root = FIXTURES
    names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    check("образцы пакетов: god-proj и god-mail", names == ["god-mail", "god-proj"], names)
    for n in names:
        texts = {}
        for dp, _, fs in os.walk(os.path.join(root, n)):
            for f in fs:
                texts[os.path.relpath(os.path.join(dp, f), root)] = open(os.path.join(dp, f), encoding="utf-8").read()
        js = {k: json.loads(v) for k, v in texts.items() if k.endswith(".json")}
        man = js.get(f"{n}/.claude-plugin/plugin.json") or {}
        w = js.get(f"{n}/window.json") or {}
        if w:  # seen — опись для check, в ней имена убранного; в окно она не идёт
            texts[f"{n}/window.json"] = json.dumps({k: v for k, v in w.items() if k != "seen"}, ensure_ascii=False)
        data = {}
        bad = P.window_extra_apply(data, w, P.window_plugins_allowed(P.plugin_map_load(alert=False), n))
        cmds = [h.get("command", "") for evs in (js.get(f"{n}/hooks/hooks.json") or {}).get("hooks", {}).values()
                for g in evs for h in g["hooks"] if h.get("type") == "command"]
        check(f"пакет {n}: plugin.json pack-{n}, window.json вливается целиком", man.get("name") == f"pack-{n}"
              and not bad and w.get("seen"), (man, bad))
        allow = data.get("permissions", {}).get("allow", [])
        check(f"пакет {n}: в allow нет опасного (git push, python, pip, docker, brew, merge)",
              not [r for r in allow if any(x in r for x in FORBIDDEN_ALLOW)], allow)
        check(f"пакет {n}: нет bypassPermissions, defaultMode, токенов и путей /Users/",
              not [(k, x) for k, v in texts.items() for x in FORBIDDEN_TEXT if x in v],
              [(k, x) for k, v in texts.items() for x in FORBIDDEN_TEXT if x in v])
        # metis-0933 круг E: скрипт .claude/hooks напрямую по пути окно подменило бы ссылкой — только через in_repo.py
        check(f"пакет {n}: хуки — только через in_repo.py пакета (скрипт .claude/hooks по fd), python3 — только с -I",
              cmds and all(c.startswith('python3 -I "${CLAUDE_PLUGIN_ROOT}/../_bin/in_repo.py" ') for c in cmds), cmds)
    mcp = js_of(root, "god-proj/mcp.json").get("mcpServers", {})
    hooks = js_of(root, "god-proj/hooks/hooks.json")["hooks"]["PreToolUse"]
    check("пакет god-proj: supabase — только вместе с protect-db.sh на его инструментах",
          any("protect-db.sh" in h["command"] and "supabase" in g["matcher"] for g in hooks for h in g["hooks"]), hooks)
    local = [s for s in mcp.values() if "command" in s]
    check("пакет god-proj: серверы MCP — через env_from.py пакета (python3 -I), npx — с точной версией",
          local and all(s["command"] == "python3" and s["args"][:2] == ["-I", "${PANTHEON_PACK_BIN}/env_from.py"]
                        for s in local)
          and all(re.search(r"@\d+\.\d+\.\d+$", s["args"][s["args"].index("-y") + 1])
                  for s in local if "npx" in s["args"]), mcp)


def js_of(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return json.load(fh)


def migration(tmp, env):
    """Перенос пакетов из прежней версии плагина (lib/packs_local.py и `pantheon packs migrate`)."""
    spec = importlib.util.spec_from_file_location("packs_local", os.path.join(PLUGIN, "lib", "packs_local.py"))
    pl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pl)
    base = os.path.join(ROOT, "mig")
    cache = os.path.join(base, "cache", "pantheon")
    secret = os.path.join(base, "secret.json")
    put(secret, '{"token": "SECRET"}')
    for ver, desc in (("0.11.9", "OLD"), ("0.11.10", "NEW")):
        put(os.path.join(cache, ver, "packs", "dir-a", ".claude-plugin", "plugin.json"), {"name": "pack-dir-a"})
        put(os.path.join(cache, ver, "packs", "dir-a", "window.json"), {"description": desc})
    put(os.path.join(cache, "0.11.10", "packs", "dir-a", "hooks", "hooks.json"), {"hooks": {}})
    os.symlink(secret, os.path.join(cache, "0.11.10", "packs", "dir-a", "mcp.json"))
    put(os.path.join(cache, "0.11.10", "packs", "dir-b", "window.json"), {"description": "FROM-CACHE"})
    put(os.path.join(cache, "0.11.10", "packs", "_bin", "window.json"), {})
    put(os.path.join(cache, "0.11.10", "plugins-by-role.toml"),
        '[window.dir-a]\nplugins = ["p@m"]\n[window.hq]\nplugins = []\n[window.stranger]\nplugins = ["q@m"]\n'
        '[window.dir-b]\nmcp = [5]\n')
    os.makedirs(os.path.join(cache, "0.11.11"))  # нынешняя версия — без пакетов
    user = os.path.join(base, "user", "packs")
    map_local = os.path.join(base, "user", "plugins-by-role.toml")
    put(os.path.join(user, "dir-b", "window.json"), {"description": "MINE"})
    desc = lambda d: json.load(open(os.path.join(user, d, "window.json"))).get("description")  # noqa: E731

    res = pl.migrate(user, os.path.join(cache, "0.11.11"), map_local, {"dir-a", "dir-b", "hq"}, {"hq"}, "t", None, True)
    check("перенос: источник — самая новая версия с пакетами (0.11.10 новее 0.11.9 по числам), пакет скопирован",
          res["from"] == os.path.join(cache, "0.11.10") and res["copied"] == ["dir-a"] and desc("dir-a") == "NEW"
          and os.path.isfile(os.path.join(user, "dir-a", "hooks", "hooks.json")), res)
    check("перенос: пакет, который уже есть у пользователя, не затёрт и не дополнен; _bin — не направление",
          res["kept"] == ["dir-b"] and desc("dir-b") == "MINE" and not os.path.exists(os.path.join(user, "_bin")), res)
    check("перенос: файл-ссылка источника не копируется (O_NOFOLLOW)",
          not os.path.lexists(os.path.join(user, "dir-a", "mcp.json")), os.listdir(os.path.join(user, "dir-a")))
    with open(map_local, "rb") as fh:
        got = tomllib.load(fh)
    check("перенос: личная карта — только [window.<направление реестра>] вне карты плагина, без кривых записей",
          res["map"] == ["dir-a"] and got == {"window": {"dir-a": {"plugins": ["p@m"]}}}, (res, got))
    check("перенос: отметка .migrated.json", os.path.isfile(os.path.join(user, ".migrated.json")), os.listdir(user))
    shutil.rmtree(os.path.join(user, "dir-a"))
    res = pl.migrate(user, os.path.join(cache, "0.11.11"), map_local, {"dir-a"}, set(), "t", None, True)
    check("после отметки шаг сборки ничего не переносит: удалённый пакет не возвращается",
          res["copied"] == [] and not os.path.exists(os.path.join(user, "dir-a")), res)
    put(map_local, "# моя карта\n")
    res = pl.migrate(user, os.path.join(cache, "0.11.11"), map_local, {"dir-a"}, set(), "t", None, False)
    check("ручной перенос (без отметки) возвращает пакет, но личную карту, которая уже есть, не затирает",
          res["copied"] == ["dir-a"] and desc("dir-a") == "NEW" and res["map"] == []
          and open(map_local, encoding="utf-8").read() == "# моя карта\n", res)
    lone = os.path.join(base, "lone")
    res = pl.migrate(os.path.join(lone, "packs"), os.path.join(lone, "plugin", "1.0"), os.path.join(lone, "map.toml"),
                     mark=False)
    check("прежних пакетов нет, ручной путь — источника нет, отметки нет",
          res["from"] is None and not os.path.exists(os.path.join(lone, "packs")), res)
    res = pl.migrate(os.path.join(lone, "packs"), os.path.join(lone, "plugin", "1.0"), os.path.join(lone, "map.toml"),
                     mark=True)
    check("прежних пакетов нет, шаг сборки — отметка, чтобы не искать их на каждой сборке",
          res["from"] is None and os.path.isfile(os.path.join(lone, "packs", ".migrated.json")), res)

    # --- команда `pantheon packs migrate` (HOME — свой) ---
    mh = os.path.join(base, "home")
    put(os.path.join(mh, "pantheon", "directions.toml"), '[[direction]]\nname = "dir-a"\nfolders = ["~/projects/a"]\n')
    menv = dict(env, HOME=mh, PANTHEON_HOME=os.path.join(mh, "pantheon"), PANTHEON_STATE=os.path.join(mh, "state"))
    run = lambda *a: subprocess.run([sys.executable, "-I", RUN_PY, "packs", "migrate", *a], env=menv,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    dst = os.path.join(mh, ".claude", "pantheon", "packs", "dir-a", "window.json")
    r = run("--from", os.path.join(cache, "0.11.9"))
    check("packs migrate --from: пакет в ~/.claude/pantheon/packs, код 0",
          r.returncode == 0 and "перенесён пакет dir-a" in r.stdout
          and json.load(open(dst)).get("description") == "OLD", (r.returncode, r.stdout, r.stderr))
    r = run("--from", os.path.join(cache, "0.11.10", "packs"))
    check("packs migrate --from папки пакетов: пакет уже есть — не тронут, код 0",
          r.returncode == 0 and "уже есть" in r.stdout and json.load(open(dst)).get("description") == "OLD",
          (r.returncode, r.stdout, r.stderr))
    r = run("--from", os.path.join(base, "nothing"))
    check("packs migrate: источника нет — код 1, причина последней строкой",
          r.returncode == 1 and "прежних пакетов нет" in (r.stderr.strip().splitlines() or [""])[-1], (r.returncode, r.stderr))
    r = run("--frm", "x")
    check("packs migrate: не те аргументы — код 2", r.returncode == 2, (r.returncode, r.stderr))


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
