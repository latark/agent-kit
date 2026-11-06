#!/usr/bin/env python3
"""Окно направления по схеме А и его пакет (metis-0933, решение владельца 06.11 17:42 «А — окно направления»).

Запуск: python3 -I plugins/pantheon/tests/test_window_pack.py  (код выхода 0 — все прошли)
- `pantheon start <направление> --dry-run` на временном HOME: argv окна — --add-dir на остальные папки направления и
  на вложенные проекты (app/ с CLAUDE.md, AGENTS.md или .claude), без node_modules и скрытых; один
  --append-system-prompt-file с AGENTS.md всех этих папок (флаг не повторяется: второй затирает первый); AGENTS.md
  папки запуска, которую её CLAUDE.md импортирует, — не дублируется; --plugin-dir и --mcp-config пакета, если есть;
  всё до --settings; без пакета — без --plugin-dir;
- граница ядра (класс 5): argv запуска окна целиком собирает P.window_launch, флагов запуска (LAUNCH_FLAGS) в lib/ и
  scripts/ вне pantheon.py нет; PANTHEON_PACKS окружения пакеты не подменяет (тест подменяет константу P.PACKS);
- `pantheon domains build`: окно направления — CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1, deny EnterWorktree и
  ExitWorktree, window.json пакета (ask, deny, plugins, env, sandbox); allow (metis-0137) и неизвестный ключ —
  не влиты, окно собрано; мастерская — без этого;
- `pantheon check`: хук и сервер .mcp.json вложенного проекта без строки в пакете — «предупреждение · окно …»; после
  записи в seen и сервера в mcp.json пакета — тишина; настройки папки запуска не предупреждают; код выхода тот же;
- обёртка packs/_bin/in_repo.py: цель вне репозитория — не запускает, внутри — cwd и CLAUDE_PROJECT_DIR репозитория,
  путь файла аргументом (--file-arg), код выхода как есть, --ok — 0; --cmd-prefix — только Bash с этим началом;
- пакеты репозитория (packs/): JSON читается, window.json вливается без отброшенного, хуки — через in_repo.py; по
  решению владельца 06.11 18:30 нет git push, python, pip, docker, brew в allow, bypassPermissions и токенов,
  supabase — только с protect-db.sh.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(PLUGIN, "lib", "run.py")
IN_REPO = os.path.join(PLUGIN, "packs", "_bin", "in_repo.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="winpack-"))
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
    home, state, packs = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state"), os.path.join(tmp, "packs")
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
    bindir = os.path.join(tmp, "bin")
    put(os.path.join(bindir, "claude"), "#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp"),
           "PANTHEON_PACKS": decoy}  # класс 5: окружение не меняет, откуда пакеты, — приманка не должна попасть в argv
    put(os.path.join(decoy, "proteus-ms", ".claude-plugin/plugin.json"), {"name": "decoy"})
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])
    # пакеты теста — подменой константы P.PACKS в процессе (как AI_HOME через HOME), а не переменной окружения
    shim = os.path.join(tmp, "run_packs.py")
    put(shim, f"import sys\nsys.path.insert(0, {os.path.join(PLUGIN, 'lib')!r})\nimport pantheon\n"
              f"pantheon.PACKS = {packs!r}\nsys.exit(pantheon.main(sys.argv[1:]))\n")
    run = lambda *a: subprocess.run([sys.executable, "-I", shim, *a], env=env, capture_output=True, text=True,  # noqa: E731
                                    timeout=120)
    r = run("domains", "build")
    check("сборка прошла", r.returncode == 0, r.stderr)
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
    check("--plugin-dir пакета, --mcp-config — его mcp.json, собранный ядром в settings/run",
          after(argv, "--plugin-dir") == [pack]
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
    launch_only_in_core()
    shipped_packs(tmp)
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


def shipped_packs(tmp):
    """Пакеты репозитория (plugins/pantheon/packs): JSON читается, window.json вливается без отброшенного, хуки — через
    in_repo.py пакета, опасного по решению владельца нет."""
    os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "pantheon"))
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    import pantheon as P
    root = os.path.join(PLUGIN, "packs")
    names = sorted(n for n in os.listdir(root) if not n.startswith(("_", ".")))
    check("пакеты репозитория: есть proteus-morph и metis-pantheon", {"proteus-morph", "metis-pantheon"} <= set(names),
          names)
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
    mcp = js_of(root, "proteus-morph/mcp.json").get("mcpServers", {})
    hooks = js_of(root, "proteus-morph/hooks/hooks.json")["hooks"]["PreToolUse"]
    check("пакет proteus-morph: supabase — только вместе с protect-db.sh на его инструментах",
          any("protect-db.sh" in h["command"] and "supabase" in g["matcher"] for g in hooks for h in g["hooks"]), hooks)
    check("пакет proteus-morph: серверы со скриптом app/ — из папки app", all(
        "MorphStream/app" in " ".join(s.get("args", [])) for s in mcp.values() if s.get("command") == "bash"), mcp)


def js_of(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
