#!/usr/bin/env python3
"""Модель угроз окна направления (metis-0933, классы 1–4; класс 5 — граница guard, не здесь).

- класс 1 — ключи пакета: каждый опасный пункт window.json по одному (allow, excludedCommands, allowWrite, домены,
  сокеты, env вне белого списка и переопределение, hooks, defaultMode, плагин вне карты) не меняет окно и назван
  отброшенным;
- класс 2 — исполняемое вне песочницы: окна metis-pantheon и proteus-morph собраны из настоящих пакетов (domains build,
  start --dry-run); каждый исполняемый файл хуков пакета, серверов собранного mcp.json и excludedCommands окна по
  настоящему пути — вне allowWrite окна или под denyWrite; python3 — только с -I; кэш npx — вне allowWrite; npx —
  только через env_from.py: поддельные node_modules/<пакет>, .npmrc (script-shell, logs-dir) и NODE_OPTIONS в папке
  запуска не исполняются (cwd «/», npm_config_* сброшены); in_repo.py не запускает хук, если репозиторий, звено пути,
  .claude или .claude/hooks — ссылка; .env через ссылку env_from.py не читает; хуки пакета proteus-morph на образцах
  tests/fixtures/morph-hooks не пишут и не читают чужое по ссылке в середине пути цели (app/app, app/api, src/shared,
  app/lnk.py): repo_hooks.py вместо check-reexport.sh и check-env-sync.sh, --plain у pre-commit;
- класс 3 — чтение вне песочницы: AGENTS.md — ссылка на личный файл, CLAUDE.md и .claude/settings.json — FIFO,
  AGENTS.md на 100 МБ: запуск и pantheon check не виснут, чужое не попадает в AGENTS.md окна; window_dirs и _read_in
  не идут по ссылке — папка из domains.json, звено в середине пути, ссылка на месте .claude;
- класс 4 — плагины и версии: пакет npx — с точной версией x.y.z, включённые плагины окна — из карты
  plugins-by-role.toml.
Во временном HOME, настоящие ~/.claude и ~/ai не трогает. Python 3.14 (metis-0571)."""
import atexit
import copy
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(PLUGIN, "lib", "run.py")
PACKS = os.path.join(PLUGIN, "packs")
# корень — как у test_tick (9fc5026f): под run-tests TMPDIR окна закрывает запись в …/.claude/agents временного HOME
# (domains build собирает роли туда) — тогда корень с приставкой tmp прямо в /tmp/claude-<uid>
_base = "/tmp/claude-%d" % os.getuid()
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="tmp-winthreat-", dir=_base if os.path.isdir(_base) else None))
atexit.register(shutil.rmtree, ROOT, True)
results = []
PINNED = re.compile(r"(@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+")


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else "\n     " + str(info)[-1500:]))


def put(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text if isinstance(text, str) else json.dumps(text))


def env_for(tmp):
    bindir = os.path.join(tmp, "bin")
    put(os.path.join(bindir, "claude"), "#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    e = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": os.path.join(tmp, "pantheon"),
         "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_NO_NOTIFY": "1",
         "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp")}
    os.makedirs(e["PANTHEON_CLAUDE_TMP"], exist_ok=True)
    return e


def run(env, *a, timeout=120):
    return subprocess.run([sys.executable, "-I", RUN_PY, *a], env=env, capture_output=True, text=True, timeout=timeout)


def lib(tmp):
    os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "pantheon"), PANTHEON_STATE=os.path.join(tmp, "state"),
                      PANTHEON_NO_NOTIFY="1")
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    import pantheon as P
    return P


# --- класс 1: ключи пакета ---
DANGEROUS = [
    ("allow", {"allow": ["Bash(rm *)"]}),
    ("permissions.allow", {"permissions": {"allow": ["Bash(*)"]}}),
    ("excludedCommands", {"sandbox": {"excludedCommands": ["mk *"]}}),
    ("allowWrite", {"sandbox": {"allowWrite": ["~"]}}),
    ("filesystem.allowWrite", {"sandbox": {"filesystem": {"allowWrite": ["~"]}}}),
    ("allowedDomains", {"sandbox": {"allowedDomains": ["evil.example"]}}),
    ("network.allowedDomains", {"sandbox": {"network": {"allowedDomains": ["evil.example"]}}}),
    ("allowUnixSockets", {"sandbox": {"allowUnixSockets": ["/var/run/docker.sock"]}}),
    ("sandbox.enabled", {"sandbox": {"enabled": False}}),
    ("hooks", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}),
    ("defaultMode", {"defaultMode": "bypassPermissions"}),
    ("mcpServers", {"mcpServers": {"x": {"command": "x"}}}),
    ("apiKeyHelper", {"apiKeyHelper": "x"}),
    ("плагин вне карты окна", {"plugins": ["ralph-loop@claude-plugins-official"]}),  # убран, владелец 06.11 21:55
    ("кривой id плагина", {"plugins": ["a b"]}),
    ("env DO_NOT_TRACK не 0/1", {"env": {"DO_NOT_TRACK": "1; rm -rf ~"}}),
] + [(f"env {k}", {"env": {k: "1"}}) for k in (
    "HOME", "PATH", "TMPDIR", "GUARD_OFF", "ANTHROPIC_BASE_URL", "XDG_CACHE_HOME", "npm_config_cache", "BASH_FUNC_x%%",
    "DYLD_INSERT_LIBRARIES", "HTTPS_PROXY", "NODE_OPTIONS", "PYTHONPATH", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD")]


def class1(P, base, ok):
    for name, extra in DANGEROUS:
        d = copy.deepcopy(base)
        bad = P.window_extra_apply(d, extra, ok)
        check(f"класс 1: {name} — отброшено, окно не изменилось", bad and d == base, (bad, extra))
    d = copy.deepcopy(base)
    d.setdefault("env", {})["DO_NOT_TRACK"] = "1"
    before = copy.deepcopy(d)
    bad = P.window_extra_apply(d, {"env": {"DO_NOT_TRACK": "0"}}, ok)
    check("класс 1: env из белого списка не переопределяет заданное окном", bad and d == before, (bad, d.get("env")))
    d = copy.deepcopy(base)
    bad = P.window_extra_apply(d, {"deny": ["Bash(x *)"], "ask": ["Bash(y *)"], "env": {"DO_NOT_TRACK": "1"},
                                   "sandbox": {"denyRead": ["~/x"], "deniedDomains": ["d.example"]},
                                   "plugins": sorted(ok)[:1]}, ok)
    check("класс 1: сужающее (deny, ask, env белого списка, denyRead, deniedDomains, плагин карты) — влито",
          not bad and "Bash(x *)" in d["permissions"]["deny"] and "Bash(y *)" in d["permissions"]["ask"]
          and d["env"].get("DO_NOT_TRACK") == "1" and "~/x" in d["sandbox"]["filesystem"]["denyRead"]
          and "d.example" in d["sandbox"]["network"]["deniedDomains"]
          and all(d["enabledPlugins"].get(p) is True for p in sorted(ok)[:1]), (bad, d))


# --- класс 2: исполняемое вне песочницы ---
def under(p, top):
    return p == top or p.startswith(top.rstrip("/") + "/")


def writable(p, win, home):
    """Пишет ли окно win (собранные настройки) по настоящему пути p: под allowWrite и не под denyWrite."""
    fs = win["sandbox"]["filesystem"]
    exp = lambda x: home + x[1:] if x.startswith("~") else x  # noqa: E731
    rp = os.path.realpath(p)
    allow = [os.path.realpath(exp(a)) for a in fs.get("allowWrite", []) if exp(a).startswith("/")]
    chain = [rp] + [rp[:i] for i in range(len(rp)) if rp[i] == "/" and i]
    deny = [exp(x) for x in fs.get("denyWrite", [])]
    return any(under(rp, a) for a in allow) and not any(fnmatch.fnmatchcase(c, x) for c in chain for x in deny)


def execs(tokens, cwd, why, wrapped=False):
    """Исполняемые файлы команды tokens (уже без $HOME): [(путь, откуда)] и ошибки разбора [(откуда, что)].
    wrapped — команда идёт через env_from.py (cwd вне папок окна, без npm_config_* окружения)."""
    out, errs = [], []
    if not tokens:
        return out, errs
    exe = tokens[0] if tokens[0].startswith("/") else shutil.which(tokens[0]) or ""
    if not exe:
        return out, [(why, f"{tokens[0]} не найден в PATH")]
    out.append((exe, why))
    base = os.path.basename(tokens[0])
    if base.startswith("python"):
        at = 2 if tokens[1:2] == ["-I"] else 1
        if at == 1:
            errs.append((why, "python3 без -I"))
        if len(tokens) <= at:
            return out, errs + [(why, "python3 без скрипта")]
        script = os.path.join(cwd, tokens[at])
        out.append((script, why))
        rest = tokens[at + 1:]
        if os.path.basename(script) == "in_repo.py":
            cut = rest.index("--")
            sub_out, sub_errs = execs(rest[cut + 1:], rest[0], why)
            out, errs = out + sub_out, errs + sub_errs
        elif os.path.basename(script) == "env_from.py":  # до «--» — .env-файл и имена: данные, не код
            cut = rest.index("--")
            sub_out, sub_errs = execs(rest[cut + 1:], cwd, why, wrapped=True)
            out, errs = out + sub_out, errs + sub_errs
    elif base in ("bash", "sh", "zsh"):
        out.append((os.path.join(cwd, tokens[1]), why))
    elif base == "npx":
        pkg = next((t for t in tokens[1:] if not t.startswith("-")), "")
        if not PINNED.fullmatch(pkg):
            errs.append((why, f"npx {pkg} — без точной версии"))
        if not wrapped:  # Claude Code запускает сервер в папке запуска: npx взял бы её node_modules и .npmrc
            errs.append((why, f"npx {pkg} — без env_from.py: cwd — папка запуска окна"))
    elif base not in ("mcp-grafana",):
        errs.append((why, f"{base}: неизвестно, что исполняет"))
    return out, errs


def pack_execs(home, state, name, pack_root):
    """Все исполняемые файлы пакета name: хуки (hooks.json), серверы (settings/run/<name>.mcp.json)."""
    out, errs = [], []
    hooks_file = os.path.join(pack_root, name, "hooks", "hooks.json")
    hooks = json.load(open(hooks_file)).get("hooks", {}) if os.path.isfile(hooks_file) else {}
    for ev, groups in hooks.items():
        for g in groups:
            for h in g["hooks"]:
                if h.get("type") != "command":
                    continue
                c = h["command"].replace("${CLAUDE_PLUGIN_ROOT}", os.path.join(pack_root, name)).replace("$HOME", home)
                o, e = execs(shlex.split(c), home, f"hook {ev}: {h['command'][:90]}")
                out, errs = out + o, errs + e
    mcp_file = os.path.join(state, "settings", "run", f"{name}.mcp.json")
    mcp = json.load(open(mcp_file)).get("mcpServers", {}) if os.path.isfile(mcp_file) else {}
    for s, v in mcp.items():
        if v.get("type") in ("http", "sse"):
            continue
        sub = lambda x: x.replace("${HOME}", home)  # noqa: E731
        o, e = execs([sub(v["command"])] + [sub(a) for a in v.get("args", [])], home, f"mcp {s}")
        out, errs = out + o, errs + e
        if "npx" in [v["command"]] + v.get("args", []):  # кэш задаёт env_from.py: $HOME/.npm
            out.append((os.path.join(home, ".npm"), f"mcp {s}: кэш npx"))
        if "env_from.py" in " ".join(v.get("args", [])):
            out.append(("/", f"mcp {s}: cwd сервера (env_from.SAFE_CWD)"))
    return out, errs, sorted(mcp)


def class2(tmp, env, P):
    home, state = tmp, env["PANTHEON_STATE"]
    for d in ("projects/agent-kit/.git", "projects/other/mailkeeper/.claude/hooks", ".claude/plugins/cache",
              "projects/MorphStream/app/.claude/hooks", "projects/MorphStream/gpu-worker/.claude/hooks"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    for d in ("app", "gpu-worker"):
        put(os.path.join(tmp, "projects/MorphStream", d, "AGENTS.md"), f"{d}\n")
    put(os.path.join(env["PANTHEON_HOME"], "directions.toml"),
        '[[direction]]\nname = "metis-pantheon"\nfolders = ["~/projects/agent-kit", "~/.claude", '
        '"~/projects/other/mailkeeper"]\n[[direction]]\nname = "proteus-morph"\nfolders = ["~/projects/MorphStream"]\n')
    r = run(env, "domains", "build")
    check("класс 2: сборка окон с настоящими пакетами прошла", r.returncode == 0, r.stderr)
    for name in ("metis-pantheon", "proteus-morph"):
        r = run(env, "start", name, "x", "--from", "zeus", "--dry-run")
        check(f"класс 2: start {name} --dry-run прошёл", r.returncode == 0, (r.stdout[-500:], r.stderr))
        win = json.load(open(os.path.join(state, "settings", f"{name}.json")))
        out, errs, servers = pack_execs(home, state, name, PACKS)
        # в работе пакет лежит в кэше плагинов: ~/.claude/plugins/cache/<маркетплейс>/pantheon/<версия>/packs
        prod = os.path.join(home, ".claude/plugins/cache/agent-kit/pantheon/0.0.1/packs")
        out += [(p.replace(PACKS, prod), why + " (из кэша плагинов)") for p, why in out if p.startswith(PACKS)]
        mine = set(P.window_excluded(name))
        check(f"класс 2: {name} — excludedCommands окна от пакета — только константа ядра WINDOW_EXCLUDED",
              mine <= set(win["sandbox"].get("excludedCommands", [])), sorted(mine))
        for c in win["sandbox"].get("excludedCommands", []):
            first = c.split(" ", 1)[0]
            if c in mine and not first.startswith("/"):
                errs.append(("excludedCommands", f"{c}: не абсолютный путь"))
            # общие команды ядра (git, gh, pantheon) — по PATH окна: пакет PATH не меняет (env — белый список)
            exe = first if first.startswith("/") else shutil.which(first, path=os.environ["PATH"])
            if exe:
                out.append((exe, f"excludedCommands {c}"))
        check(f"класс 2: {name} — команды разобраны, python3 с -I, npx с версией", not errs, errs)
        check(f"класс 2: {name} — исполняемое найдено (хуки, серверы, excludedCommands)",
              len(out) >= (8 if name == "proteus-morph" else 4) and (servers or name == "metis-pantheon"), out)
        hit = [(p, why) for p, why in out if writable(p, win, home)]
        check(f"класс 2: {name} — всё исполняемое вне allowWrite окна или под denyWrite", not hit, hit)
    win = json.load(open(os.path.join(state, "settings", "proteus-morph.json")))
    for p in ("projects/MorphStream/x.sh", "projects/MorphStream/app/scripts/start-grafana-mcp.sh",
              "projects/MorphStream/app/.env.local"):
        check(f"класс 2: самопроверка — {p} окно пишет (такой путь в хуке был бы найден)",
              writable(os.path.join(home, p), win, home), win["sandbox"]["filesystem"].get("denyWrite"))
    _, errs = execs(["python3", os.path.join(PACKS, "_bin", "in_repo.py"), home, "--", "bash", "x.sh"], home, "t")
    _, errs2 = execs(["npx", "-y", "shadcn@latest", "mcp"], home, "t")
    _, errs3 = execs(["npx", "-y", "shadcn@4.8.2", "mcp"], home, "t")
    check("класс 2/4: самопроверка — python3 без -I, npx @latest и npx без env_from.py замечены",
          errs and errs2 and errs3, (errs, errs2, errs3))
    return win


ENV_FROM = os.path.join(PACKS, "_bin", "env_from.py")
IN_REPO = os.path.join(PACKS, "_bin", "in_repo.py")


def class2_npx(tmp):
    """npx сервера пакета не берёт код из папки запуска (ревью argus B1 Б1, B2 Б1 PR #360): в папке, которую пишет
    окно, — поддельный node_modules/<пакет> и .npmrc со script-shell и logs-dir. Через env_from.py подделка не
    исполняется и .npmrc не читается; тот же npx прямо из папки (как без обёртки) — исполняет: проба настоящая."""
    npx = shutil.which("npx")
    if not npx:
        print("     пропущено: нет npx — класс 2, подмена пакета npx")
        return
    launch = os.path.join(tmp, "projects", "npxlaunch")
    pkg = os.path.join(launch, "node_modules", "fakepkg-mcp")
    mark, shell_mark = os.path.join(tmp, "FAKE-RAN"), os.path.join(tmp, "SHELL-RAN")
    put(os.path.join(pkg, "package.json"), {"name": "fakepkg-mcp", "version": "1.0.0", "bin": {"fakepkg-mcp": "cli.js"}})
    put(os.path.join(pkg, "cli.js"), f"#!/usr/bin/env node\nrequire('fs').writeFileSync({json.dumps(mark)}, 'x')\n")
    os.chmod(os.path.join(pkg, "cli.js"), 0o755)
    os.makedirs(os.path.join(launch, "node_modules", ".bin"))
    os.symlink("../fakepkg-mcp/cli.js", os.path.join(launch, "node_modules", ".bin", "fakepkg-mcp"))
    put(os.path.join(launch, "evil.sh"), f"#!/bin/sh\ntouch {shlex.quote(shell_mark)}\nexec /bin/sh \"$@\"\n")
    os.chmod(os.path.join(launch, "evil.sh"), 0o755)
    put(os.path.join(launch, ".npmrc"), f"script-shell={launch}/evil.sh\nlogs-dir={launch}/npmlogs\n")
    home = os.path.join(tmp, "npxhome")
    os.makedirs(home)
    env = {"PATH": os.environ["PATH"], "HOME": home, "npm_config_cache": os.path.join(launch, "cache"),
           "NODE_OPTIONS": "--require=" + os.path.join(launch, "x.js")}
    put(os.path.join(launch, "x.js"), f"require('fs').writeFileSync({json.dumps(mark + '-NODE')}, 'x')\n")
    cmd = ["npx", "-y", "--offline", "fakepkg-mcp@1.0.0"]
    r = subprocess.run([sys.executable, "-I", ENV_FROM, "--", *cmd], cwd=launch, env=env, capture_output=True,
                       text=True, timeout=120)
    left = [p for p in (mark, shell_mark, mark + "-NODE", os.path.join(launch, "npmlogs"), os.path.join(launch, "cache"))
            if os.path.exists(p)]
    check("класс 2: npx через env_from.py — node_modules, .npmrc и NODE_OPTIONS папки запуска не исполнены и не прочитаны",
          not left and r.returncode != 0, (left, r.returncode, r.stderr[-600:]))
    env.pop("NODE_OPTIONS")
    r = subprocess.run(cmd, cwd=launch, env=env, capture_output=True, text=True, timeout=120)
    check("класс 2: самопроверка — тот же npx прямо из папки запуска исполняет подделку (без обёртки так и было)",
          os.path.exists(mark) or os.path.exists(shell_mark), (r.returncode, r.stderr[-600:]))
    probe = "import os, json; print(json.dumps({'cwd': os.getcwd(), 'env': dict(os.environ)}))"
    env["NODE_OPTIONS"] = "x"
    r = subprocess.run([sys.executable, "-I", ENV_FROM, "--", sys.executable, "-I", "-c", probe], cwd=launch, env=env,
                       capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}")
    npm = {k: v for k, v in (got.get("env") or {}).items() if k.lower().startswith("npm_config_")}
    check("класс 2: env_from.py — cwd «/» (вне allowWrite), npm_config_* окружения сброшены, кэш $HOME/.npm, "
          "без NODE_OPTIONS", r.returncode == 0 and got.get("cwd") == "/" and "NODE_OPTIONS" not in got.get("env", {})
          and npm == {"npm_config_cache": os.path.join(home, ".npm")}, (r.returncode, got.get("cwd"), npm, r.stderr))


def class2_links(tmp):
    """in_repo.py не запускает хук, если репозиторий, его .claude или .claude/hooks подменены ссылкой (окно пишет
    папку-родителя): выход 2, хук чужой папки не исполнен. Обычная папка — исполнен (самопроверка)."""
    foreign = os.path.join(tmp, "foreign-hooks")
    mark = os.path.join(tmp, "HOOK-RAN")
    put(os.path.join(foreign, ".claude", "hooks", "x.sh"), f"#!/bin/sh\ntouch {shlex.quote(mark)}\n")
    proj = os.path.join(tmp, "projects", "hk")
    os.makedirs(os.path.join(proj, "real", ".claude", "hooks"))
    shutil.copy(os.path.join(foreign, ".claude", "hooks", "x.sh"), os.path.join(proj, "real", ".claude", "hooks"))
    os.symlink(foreign, os.path.join(proj, "app"))
    os.makedirs(os.path.join(proj, "dot"))
    os.symlink(os.path.join(foreign, ".claude"), os.path.join(proj, "dot", ".claude"))
    os.makedirs(os.path.join(proj, "hooks", ".claude"))
    os.symlink(os.path.join(foreign, ".claude", "hooks"), os.path.join(proj, "hooks", ".claude", "hooks"))
    os.symlink(tmp, os.path.join(tmp, "projects", "midp"))  # $HOME/projects/midp/foreign-hooks — ссылка звеном midp
    env = {"PATH": os.environ["PATH"], "HOME": tmp}

    def hook(repo):
        if os.path.exists(mark):
            os.unlink(mark)
        r = subprocess.run([sys.executable, "-I", IN_REPO, repo, "--always", "--", "bash", ".claude/hooks/x.sh"],
                           input="{}", env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, os.path.exists(mark), r.stderr

    for name, repo in (("репозиторий — ссылка", "$HOME/projects/hk/app"), ("ссылка в середине пути", "$HOME/projects/midp/foreign-hooks"),
                       (".claude — ссылка", "$HOME/projects/hk/dot"), (".claude/hooks — ссылка", "$HOME/projects/hk/hooks")):
        rc, ran, err = hook(repo.replace("$HOME", tmp))
        check(f"класс 2: in_repo.py — {name}: хук не исполнен, выход 2", rc == 2 and not ran, (rc, ran, err))
    rc, ran, err = hook(os.path.join(proj, "real"))
    check("класс 2: самопроверка — in_repo.py в обычной папке исполняет хук", rc == 0 and ran, (rc, ran, err))
    # имя не .env*: песочница планового прохода закрывает запись файлов .env* (outside 2a8c58, EPERM) — env_from.py
    # имя файла не важно, проверяется путь
    put(os.path.join(foreign, "dotenv.local"), "TOKEN=FOREIGN\n")
    put(os.path.join(proj, "real", "dotenv.local"), "TOKEN=OWN\n")
    probe = "import os; print(os.environ.get('TOKEN'))"
    for name, f, want in (("через ссылку папки — не прочитан, выход 1", os.path.join(proj, "app", "dotenv.local"), None),
                          ("обычный — имя передано", os.path.join(proj, "real", "dotenv.local"), "OWN")):
        r = subprocess.run([sys.executable, "-I", ENV_FROM, f, "TOKEN", "--", sys.executable, "-I", "-c", probe],
                           env=env, capture_output=True, text=True, timeout=30)
        got = r.stdout.strip() if r.returncode == 0 else None
        check(f"класс 2: env_from.py — .env {name}", got == want and (want or r.returncode == 1), (r.returncode, got,
                                                                                                    r.stderr))


FIXT = os.path.join(PLUGIN, "tests", "fixtures", "morph-hooks")
REPO_HOOKS = os.path.join(PACKS, "_bin", "repo_hooks.py")
MARK = "FOREIGN-SECRET-7731"


def tree(p):
    """Снимок папки без перехода по ссылкам: путь → содержимое файла, цель ссылки или «папка»."""
    out = {}
    for dp, dns, fns in os.walk(p):
        for n in dns + fns:
            f = os.path.join(dp, n)
            out[os.path.relpath(f, p)] = ("link", os.readlink(f)) if os.path.islink(f) else (
                ("dir",) if os.path.isdir(f) else ("file", open(f, "rb").read()))
    return out


def morph(home, link_at):
    """Временный MorphStream с образцами хуков (tests/fixtures/morph-hooks) и чужая папка с MARK. link_at — где окно
    подложило ссылку: «app» (app/app → чужая папка, проба C1/C2), «app/api» (звено глубже) или None (без ссылок)."""
    ms = os.path.join(home, "projects", "MorphStream")
    app, gpu, foreign = os.path.join(ms, "app"), os.path.join(ms, "gpu-worker"), os.path.join(home, "foreign")
    for d, sub in ((app, "app"), (gpu, "gpu-worker")):
        shutil.copytree(os.path.join(FIXT, sub), os.path.join(d, ".claude", "hooks"))
    put(os.path.join(app, "src/app/api/x/route.ts"), "export async function GET() {}\nexport function POST() {}\n")
    put(os.path.join(app, "src/app/api/new/route.ts"), "export function GET() {}\n")
    put(os.path.join(foreign, "api/x/route.ts"), f"{MARK} ДАННЫЕ ДРУГОГО ПРОЕКТА\n")
    put(os.path.join(foreign, "x/route.ts"), f"{MARK} ДАННЫЕ ДРУГОГО ПРОЕКТА\n")
    for d in ("api/new", "new"):  # re-export «new» по ссылке есть: прежний pre-commit доходит до grep src/shared/
        put(os.path.join(foreign, d, "route.ts"), "export { GET } from '@/app/api/new/route'\n")
    put(os.path.join(foreign, "lib/s.ts"), f"import a from '@/features/{MARK}'\n")
    put(os.path.join(foreign, "cuda.py"), "import onnxruntime\nonnxruntime.get_available_providers()\n")
    os.makedirs(os.path.join(gpu, "app"))
    if link_at:
        if link_at == "app/api":
            os.makedirs(os.path.join(app, "app"))
        os.symlink(foreign, os.path.join(app, link_at))
        os.symlink(os.path.join(foreign, "lib"), os.path.join(app, "src/shared"))
        os.symlink(os.path.join(foreign, "cuda.py"), os.path.join(gpu, "app", "lnk.py"))
    else:
        put(os.path.join(app, "app/api/x/route.ts"), "export { GET } from '@/app/api/x/route'\n")
        os.makedirs(os.path.join(app, "src/shared"))
    return app, gpu, foreign


def run_pack_hooks(home, app, gpu, plugin_root, hooks=None):
    """Каждый хук-команда пакета на правку route.ts (есть и новый), git commit в app и в gpu-worker: [(команда, вход,
    код, вывод)]. hooks — подмена hooks.json (мутант), по умолчанию — из plugin_root."""
    hooks = hooks or json.load(open(os.path.join(plugin_root, "hooks", "hooks.json")))["hooks"]
    inputs = [{"tool_name": "Edit", "tool_input": {"file_path": os.path.join(app, "src/app/api/x/route.ts")}, "cwd": app},
              {"tool_name": "Write", "tool_input": {"file_path": os.path.join(app, "src/app/api/new/route.ts")},
               "cwd": app},
              {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": app},
              {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": gpu}]
    env = {"PATH": os.environ["PATH"], "HOME": home, "CLAUDE_PLUGIN_ROOT": plugin_root}
    out = []
    for groups in hooks.values():
        for g in groups:
            for h in g["hooks"]:
                if h.get("type") != "command":
                    continue
                for inp in inputs:
                    if g.get("matcher") and not re.fullmatch(g["matcher"], inp["tool_name"]):
                        continue
                    r = subprocess.run(["/bin/sh", "-c", h["command"]], input=json.dumps(inp), env=env, cwd=home,
                                       capture_output=True, text=True, timeout=60)
                    out.append((h["command"][-70:], inp["tool_name"], r.returncode, r.stdout + r.stderr))
    return out


def class2_pack_hooks(tmp):
    """Хуки пакета proteus-morph идут вне песочницы и не пишут и не читают вне репозитория по ссылке, которую подложило
    окно (ревью argus C1 и C2 PR #360): app/app или app/api → чужая папка, src/shared → чужая папка, app/lnk.py
    gpu-worker → чужой файл. Чужая папка не меняется, её содержимое не попадает в вывод, git commit с такой ссылкой
    не проверяется (выход 2). Самопроверки: прежние строки (bash check-reexport.sh, pre-commit без --plain) по тем
    же ссылкам пишут и читают чужое; без ссылок замена делает то же, что check-reexport.sh."""
    root = os.path.join(PACKS, "proteus-morph")
    for link_at in ("app", "app/api"):
        home = os.path.join(tmp, "packhooks-" + link_at.replace("/", "-"))
        app, gpu, foreign = morph(home, link_at)
        before = tree(foreign)
        res = run_pack_hooks(home, app, gpu, root)
        check(f"класс 2: хуки пакета (ссылка {link_at}) — запущены на правках и git commit", len(res) >= 8, res)
        check(f"класс 2: хуки пакета (ссылка {link_at} → чужая папка) — чужая папка не изменена, файлы не созданы",
              tree(foreign) == before, sorted(set(tree(foreign).items()) ^ set(before.items()))[:5])
        leak = [(c, t, rc, o) for c, t, rc, o in res if MARK in o or "❌" in o]
        check(f"класс 2: хуки пакета (ссылка {link_at}) — содержимое чужих файлов не попало в вывод", not leak, leak)
        commit = [(c, rc) for c, t, rc, o in res if t == "Bash" and "pre-commit-check.sh" in c and rc != 0]
        check(f"класс 2: хуки пакета (ссылка {link_at}) — git commit со ссылкой в src/ или app/ — выход 2 обоих "
              "pre-commit", len(commit) == 2 and all(rc == 2 for _, rc in commit), res)
    # самопроверки: те же ссылки, прежние строки пакета (до metis-0933 круга D) — чужое пишется и читается
    home = os.path.join(tmp, "packhooks-old")
    app, gpu, foreign = morph(home, "app")
    before = tree(foreign)
    old = json.load(open(os.path.join(root, "hooks", "hooks.json")))["hooks"]
    old = copy.deepcopy(old)
    for g in old["PreToolUse"] + old["PostToolUse"]:
        for h in g["hooks"]:
            c = h.get("command", "")
            c = re.sub(r'python3 -I "\$\{CLAUDE_PLUGIN_ROOT\}/../_bin/repo_hooks.py" reexport',
                       "bash .claude/hooks/check-reexport.sh", c)
            h["command"] = re.sub(r" --plain=\S+", "", c)
    res = run_pack_hooks(home, app, gpu, root, old)
    check("класс 2: самопроверка — прежний check-reexport.sh по ссылке app/app пишет в чужую папку (проба C1/C2)",
          tree(foreign) != before, res)
    check("класс 2: самопроверка — прежний pre-commit без --plain читает чужое по ссылке src/shared и app/lnk.py",
          any(MARK in o for _, _, _, o in res) and any("❌ app/lnk.py" in o for _, _, _, o in res), res)
    # без ссылок замена делает то же, что check-reexport.sh: новый re-export создан, устаревший обновлён
    home = os.path.join(tmp, "packhooks-plain")
    app, gpu, foreign = morph(home, None)
    res = run_pack_hooks(home, app, gpu, root)
    got = {f: open(os.path.join(app, "app/api", f, "route.ts")).read() if os.path.isfile(
        os.path.join(app, "app/api", f, "route.ts")) else None for f in ("x", "new")}
    check("класс 2: без ссылок repo_hooks.py reexport создаёт и обновляет re-export, как check-reexport.sh",
          got == {"x": "export { GET,POST } from '@/app/api/x/route'\n", "new": "export { GET } from '@/app/api/new/route'\n"}
          and not [rc for c, t, rc, o in res if rc == 2], (got, res))
    # env-sync: имена не .env* (песочница прохода, п. 5) — те же три роли файлов аргументами
    names = ["sync.example", "sync.local", "sync.production"]
    for n in names[:2]:
        put(os.path.join(app, n), "# ключи\nA=1\nB=2\n")
    env = {"PATH": os.environ["PATH"], "HOME": home, "CLAUDE_PROJECT_DIR": app}

    def sync(*ns, bin_dir=None):  # как хук пакета: через in_repo.py (fd корня), путь файла — явно перед именами
        b = bin_dir or os.path.dirname(REPO_HOOKS)
        inp = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(app, "sync.local")}})
        r = subprocess.run([sys.executable, "-I", os.path.join(b, "in_repo.py"), app, "--", sys.executable, "-I",
                            os.path.join(b, "repo_hooks.py"), "env-sync", os.path.join(app, "sync.local"), *ns],
                           input=inp, env=env, cwd=home, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    put(os.path.join(foreign, "prod"), f"# ключи\nA=1\n{MARK} строка чужого файла\n")
    os.symlink(os.path.join(foreign, "prod"), os.path.join(app, "sync.production"))
    os.symlink(foreign, os.path.join(app, "cfg"))
    for name, ns in (("файл — ссылка на чужой файл", names), ("ссылка в середине пути", names[:2] + ["cfg/prod"])):
        rc, o = sync(*ns)
        check(f"класс 2: repo_hooks.py env-sync — {name}: чужое не прочитано, проверка пропущена",
              rc == 0 and MARK not in o and "не прочитан" in o, (rc, o))
    # запись по ссылке-файлу: окно подменило файл между чтением и записью (гонка) — write_in и сам не идёт по ссылке
    import importlib.util
    spec = importlib.util.spec_from_file_location("repo_hooks", REPO_HOOKS)
    rh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rh)
    put(os.path.join(foreign, "victim"), f"{MARK}\n")
    os.symlink(os.path.join(foreign, "victim"), os.path.join(app, "app/api/x/lnk.ts"))
    before = tree(foreign)
    rfd = os.open(app, os.O_RDONLY | os.O_DIRECTORY)
    try:
        rh.write_in(rfd, "app/api/x/lnk.ts", "export {}\n")
        refused = False
    except OSError:
        refused = True
    finally:
        os.close(rfd)
    check("класс 2: repo_hooks.write_in — последнее звено ссылка на чужой файл: отказ, файл не тронут",
          refused and tree(foreign) == before, refused)
    # жёсткая ссылка на чужой файл (st_nlink 2): окно не может её отличить от своего файла по пути (metis-0950, m4)
    hard_key = "FOREIGN_HARD_7731"  # строка вида KEY= — env-sync её покажет, если прочтёт (маска её не скрывает)
    put(os.path.join(foreign, "prod-hard"), f"# ключи\nA=1\n{hard_key}=1\n")
    os.link(os.path.join(foreign, "prod-hard"), os.path.join(app, "hard.production"))
    rc, o = sync(*names[:2], "hard.production")
    check("класс 2: repo_hooks.py env-sync — жёсткая ссылка на чужой файл (st_nlink 2): чужое не прочитано",
          rc == 0 and hard_key not in o and "не прочитан" in o, (rc, o))
    m4 = mutant_bin(tmp, "m4", {"repo_hooks.py": [("st.st_nlink != 1 or ", "")]})
    rc, o = sync(*names[:2], "hard.production", bin_dir=m4)
    check("класс 2: самопроверка — мутант m4 (без st_nlink != 1) читает чужое по жёсткой ссылке", hard_key in o, (rc, o))
    # вывод env-sync — только строки KEY= (ревью argus D2, Д2): строка без «=» или комментарий — маской
    put(os.path.join(app, "own.production"), "# ключи\nA=1\nEXTRA-OWN-LINE sk-SECRET\n# секрет-в-комментарии\nB=2\n")
    rc, o = sync(*names[:2], "own.production")
    check("класс 2: env-sync — расхождение выведено, строки не KEY= — маской (EXTRA-OWN-LINE и комментарий скрыты)",
          rc == 0 and "рассинхронизирована" in o and "EXTRA-OWN-LINE" not in o and "секрет-в-комментарии" not in o
          and "строка не KEY=" in o, (rc, o))
    m = mutant_bin(tmp, "mask", {"repo_hooks.py": [('return line if not line.strip() or ENV_KEY.fullmatch(line) else',
                                                    'return line if True else')]})
    rc, o = sync(*names[:2], "own.production", bin_dir=m)
    check("класс 2: самопроверка — без маски env-sync выводит строку не KEY= целиком", "EXTRA-OWN-LINE" in o, (rc, o))


def mutant_bin(tmp, name, subs):
    """Копия packs/_bin с заменами {файл: [(было, стало)]} — мутант для самопроверки; замена обязана сработать."""
    d = os.path.join(tmp, "mutant-" + name)
    shutil.copytree(os.path.join(PACKS, "_bin"), d)
    for f, pairs in subs.items():
        text = open(os.path.join(d, f), encoding="utf-8").read()
        for a, b in pairs:
            assert a in text, (name, f, a)
            text = text.replace(a, b)
        with open(os.path.join(d, f), "w", encoding="utf-8") as fh:
            fh.write(text)
    return d



# --- класс 2: гонка «проверка пути строкой → действие по строке» (ревью argus D2, metis-0933 круг E) ---
SWAP_AT_RUN = r"""
import importlib.util, os, subprocess, sys
path, app, foreign = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("in_repo", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
real_run = subprocess.run
def swapped(*a, **k):  # худший миг: проверки in_repo.py позади, ребёнок ещё не начал — окно подменяет app ссылкой
    os.rename(app, app + ".real")
    os.symlink(foreign, app)
    try:
        return real_run(*a, **k)
    finally:
        os.unlink(app)
        os.rename(app + ".real", app)
subprocess.run = swapped
sys.exit(m.main(sys.argv[4:]))
"""
SWAPPER = r"""
import os, sys, time
app, foreign, stop = sys.argv[1:4]
n = 0
while not os.path.exists(stop):
    os.rename(app, app + ".real")
    os.symlink(foreign, app)
    time.sleep(0.0003)
    os.unlink(app)
    os.rename(app + ".real", app)
    time.sleep(0.0003)
    n += 1
print(n)
"""
RACE_MARK = "FOREIGN_RACE_5517"  # годится в ключ KEY= — маска env-sync его не скрывает


def race_repo(home):
    """Свой репозиторий app и чужая папка: хук .claude/hooks/x.sh (пишет OWN или FOREIGN в $RACE_LOG), route.ts,
    sync.* для env-sync, src/shared/s.ts и gpu.py для fsd и cuda-safety; в чужих файлах — RACE_MARK."""
    app, foreign = os.path.join(home, "projects", "M", "app"), os.path.join(home, "foreign")
    for d, who in ((app, "OWN"), (foreign, "FOREIGN")):
        mark = RACE_MARK if who == "FOREIGN" else "own"
        put(os.path.join(d, ".claude/hooks/x.sh"), f'echo {who} >> "$RACE_LOG"\n')
        put(os.path.join(d, "src/app/api/x/route.ts"), "export function GET() {}\n")
        for n in ("sync.example", "sync.local", "sync.production"):
            put(os.path.join(d, n), f"# ключи\nA=1\n{mark}_{n.replace('.', '_')}=1\n")
        put(os.path.join(d, "src/shared/s.ts"), f"import a from '@/features/{mark}'\n")
        put(os.path.join(d, "gpu.py"), "import onnxruntime\nonnxruntime.get_available_providers()\n"
            if who == "FOREIGN" else "x = 1\n")
    return app, foreign


def race_cmds(app, bin_dir):
    """Хуки пакета под гонкой: (имя, флаги in_repo, команда, вход)."""
    rh = [sys.executable, "-I", os.path.join(bin_dir, "repo_hooks.py")]
    edit = lambda rel: json.dumps({"tool_name": "Edit", "tool_input": {"file_path": os.path.join(app, rel)}})  # noqa
    return [("исполнение .claude/hooks/x.sh", ["--always"], ["bash", ".claude/hooks/x.sh"], "{}"),
            ("reexport", ["--file-arg"], rh + ["reexport"], edit("src/app/api/x/route.ts")),
            ("env-sync", [], rh + ["env-sync", os.path.join(app, "sync.local"), "sync.example", "sync.local",
                                   "sync.production"], edit("sync.local")),
            ("fsd", ["--file-arg"], rh + ["fsd"], edit("src/shared/s.ts")),
            ("cuda-safety", ["--file-arg"], rh + ["cuda-safety"], edit("gpu.py"))]


def race_effects(foreign, before, log, outs):
    """(сколько раз исполнен чужой хук, чужая папка изменена, сколько выводов с чужим текстом)."""
    ran = open(log).read().split().count("FOREIGN") if os.path.exists(log) else 0
    read = sum(RACE_MARK in o or "CUDA-safety" in o for o in outs)  # у своего gpu.py предупреждения нет
    return ran, tree(foreign) != before, read


def class2_race(tmp):
    """Окно подменяет папку репозитория ссылкой (app ↔ ссылка на чужую папку) в любой миг: in_repo.py и repo_hooks.py
    действуют по fd корня, открытого без ссылок, а не по строке пути — чужой скрипт не исполнен, в чужую папку ничего
    не записано и из неё ничего не прочитано. Подмена в худший миг (после проверок, до запуска ребёнка) —
    детерминированно, на каждом хуке; мутанты «по строке вместо fd» в in_repo.py и repo_hooks.py ловятся. Затем
    фоновая подмена и N запусков исполнения, reexport и env-sync."""
    home = os.path.join(tmp, "race")
    app, foreign = race_repo(home)
    log = os.path.join(tmp, "race.log")
    env = {"PATH": os.environ["PATH"], "HOME": home, "RACE_LOG": log}
    bin_dir = os.path.join(PACKS, "_bin")
    m_in = mutant_bin(tmp, "in-path", {"in_repo.py": [('cmd[i] = f"/dev/fd/{sfd}"', "cmd[i] = a"),
                                                      ("os.fchdir(root)", "pass"),
                                                      ("env=env, input=raw", "env=env, cwd=repo, input=raw")]})
    m_rh = mutant_bin(tmp, "rh-path", {"repo_hooks.py": [(
        "fd = os.dup(root)", 'fd = os.open(os.path.realpath(os.environ["CLAUDE_PROJECT_DIR"]), os.O_RDONLY)')]})
    clean = tree(foreign)
    for label, b in (("fd", bin_dir), ("in_repo", m_in), ("repo_hooks", m_rh)):
        got = {}
        for name, flags, cmd, inp in race_cmds(app, b):
            if os.path.exists(log):
                os.unlink(log)
            r = subprocess.run([sys.executable, "-I", "-c", SWAP_AT_RUN, os.path.join(b, "in_repo.py"), app, foreign,
                                app, *flags, "--", *cmd], input=inp, env=env, cwd=home, capture_output=True,
                               text=True, timeout=60)
            own = open(log).read().split().count("OWN") if os.path.exists(log) else 0
            got[name] = race_effects(foreign, clean, log, [r.stdout + r.stderr]) + (own, r.returncode)
            if tree(foreign) != clean:  # мутант записал в чужую папку — вернуть её, следующий хук сравнивает с чистой
                shutil.rmtree(foreign)
                race_repo(os.path.join(tmp, "race-reset"))
                shutil.move(os.path.join(tmp, "race-reset", "foreign"), foreign)
                shutil.rmtree(os.path.join(tmp, "race-reset"))
        if label == "fd":
            bad = {k: v for k, v in got.items() if v[:3] != (0, False, 0)}
            check("класс 2: гонка — подмена app ссылкой в худший миг: 0 чужих исполнений, 0 записей, 0 чтений чужого "
                  "(исполнение, reexport, env-sync, fsd, cuda-safety); свой хук исполнен",
                  not bad and got["исполнение .claude/hooks/x.sh"][3] == 1, got)
        elif label == "in_repo":
            check("класс 2: самопроверка — мутант «in_repo по строке» (cwd=путь, скрипт по пути) исполняет чужой хук",
                  got["исполнение .claude/hooks/x.sh"][0] == 1, got)
        else:
            check("класс 2: самопроверка — мутант «repo_hooks по строке» (realpath CLAUDE_PROJECT_DIR) пишет в чужую "
                  "папку и читает чужое (reexport, env-sync, fsd, cuda-safety)",
                  got["reexport"][1] and all(got[k][2] for k in ("env-sync", "fsd", "cuda-safety")), got)
    # фоновая подмена: N запусков каждого хука, пока окно без остановки меняет app ↔ ссылка
    n = 200
    stop = os.path.join(tmp, "race.stop")
    if os.path.exists(log):
        os.unlink(log)
    sw = subprocess.Popen([sys.executable, "-I", "-c", SWAPPER, app, foreign, stop], stdout=subprocess.PIPE, text=True)
    outs, codes = [], {}
    try:
        for name, flags, cmd, inp in race_cmds(app, bin_dir)[:3]:
            for _ in range(n):
                r = subprocess.run([sys.executable, "-I", os.path.join(bin_dir, "in_repo.py"), app, *flags, "--",
                                    *cmd], input=inp, env=env, cwd=home, capture_output=True, text=True, timeout=60)
                outs.append(r.stdout + r.stderr)
                codes.setdefault(name, []).append(r.returncode)
    finally:
        put(stop, "")
        swaps = sw.communicate(timeout=30)[0].strip()
    ran, wrote, read = race_effects(foreign, clean, log, outs)
    own = open(log).read().split().count("OWN") if os.path.exists(log) else 0
    refused = sum(c == 2 for c in codes["исполнение .claude/hooks/x.sh"])
    check(f"класс 2: гонка — фоновая подмена app ↔ ссылка, по {n} запусков исполнения, reexport и env-sync: 0 чужих "
          "исполнений, 0 записей и 0 чтений в чужой папке", (ran, wrote, read) == (0, False, 0),
          (ran, wrote, read, [o for o in outs if RACE_MARK in o][:2]))
    check("класс 2: самопроверка гонки — подмена шла, хук то исполнялся из своей папки, то получал отказ (выход 2)",
          int(swaps or 0) > n and own > 0 and refused > 0, (swaps, own, refused))


def class2_plain_after(tmp):
    """--plain: окно подложило ссылку во время прогона хука (ревью argus D2, Д1) — после прогона links_under заново,
    вывод хука выброшен, выход 2. Хук сам кладёт ссылку и читает по ней — так гонка детерминирована."""
    home = os.path.join(tmp, "plain-after")
    app, foreign = race_repo(home)
    put(os.path.join(app, ".claude/hooks/pc.sh"), f"ln -s {shlex.quote(foreign)} src/lnk\ncat src/lnk/src/shared/s.ts\n")
    env = {"PATH": os.environ["PATH"], "HOME": home}
    m = mutant_bin(tmp, "plain-after", {"in_repo.py": [(
        "    if plain:\n        bad = [x for rel in plain for x in links_under(root, rel)]\n",
        "    if plain:\n        bad = []\n")]})
    for label, b in (("fd", os.path.join(PACKS, "_bin")), ("мутант", m)):
        if os.path.lexists(os.path.join(app, "src/lnk")):
            os.unlink(os.path.join(app, "src/lnk"))
        r = subprocess.run([sys.executable, "-I", os.path.join(b, "in_repo.py"), app, "--always", "--plain=src", "--",
                            "bash", ".claude/hooks/pc.sh"], input="{}", env=env, cwd=home, capture_output=True,
                           text=True, timeout=30)
        if label == "fd":
            check("класс 2: --plain — ссылка появилась во время хука: вывод выброшен, выход 2",
                  r.returncode == 2 and RACE_MARK not in r.stdout + r.stderr and "во время хука" in r.stderr,
                  (r.returncode, r.stdout, r.stderr))
        else:
            check("класс 2: самопроверка — без проверки после прогона чужое попадает в вывод",
                  RACE_MARK in r.stdout, (r.returncode, r.stdout, r.stderr))

# --- класс 3: чтение вне песочницы ---
def class3(tmp, env):
    ms = os.path.join(tmp, "projects/ms3")
    put(os.path.join(tmp, "secret.txt"), "SECRET-PERSONAL-123\n")
    os.makedirs(os.path.join(ms, "app/.claude"))
    os.symlink(os.path.join(tmp, "secret.txt"), os.path.join(ms, "app/AGENTS.md"))
    os.makedirs(os.path.join(ms, "big"))
    with open(os.path.join(ms, "big/AGENTS.md"), "wb") as fh:
        fh.truncate(100 << 20)
    put(os.path.join(ms, "ok/AGENTS.md"), "OK-RULES\n")
    os.mkfifo(os.path.join(ms, "CLAUDE.md"))
    put(os.path.join(ms, "AGENTS.md"), "LAUNCH\n")
    os.makedirs(os.path.join(ms, "fifo/.claude"))
    os.mkfifo(os.path.join(ms, "fifo/.claude/settings.json"))
    os.mkfifo(os.path.join(ms, "fifo/AGENTS.md"))
    put(os.path.join(env["PANTHEON_HOME"], "directions.toml"),
        '[[direction]]\nname = "proteus-three"\nfolders = ["~/projects/ms3"]\n')
    r = run(env, "domains", "build", timeout=60)
    check("класс 3: сборка с FIFO и ссылками в папках окна прошла", r.returncode == 0, r.stderr)
    try:
        r = run(env, "start", "proteus-three", "x", "--from", "zeus", "--dry-run", timeout=60)
        hung = False
    except subprocess.TimeoutExpired:
        hung = True
    check("класс 3: start --dry-run с CLAUDE.md и AGENTS.md — FIFO не виснет", not hung and r.returncode == 0,
          "завис" if hung else r.stderr)
    f = os.path.join(env["PANTHEON_STATE"], "settings", "run", "proteus-three.agents.md")
    text = open(f, encoding="utf-8").read() if os.path.isfile(f) else ""
    check("класс 3: AGENTS.md окна — обычные файлы есть, ссылки на личный файл нет", "OK-RULES" in text
          and "LAUNCH" in text and "SECRET-PERSONAL" not in text, text[:500])
    check("класс 3: AGENTS.md на 100 МБ не вклеен", os.path.getsize(f) < (1 << 20) if os.path.isfile(f) else False,
          os.path.getsize(f) if os.path.isfile(f) else None)
    try:
        r = run(env, "check", timeout=90)
        hung = False
    except subprocess.TimeoutExpired:
        hung = True
    check("класс 3: pantheon check с .claude/settings.json — FIFO не виснет", not hung, "завис")


def class3_links(P, tmp):
    """window_dirs и _read_in не идут по ссылке (ревью argus B1 Д1, B2 Д1 PR #360): папка из domains.json — ссылка
    (окно пишет папку-родителя и подменило подпапку), ссылка в середине пути папки, ссылка на месте .claude. Чужое
    (AGENTS.md, .claude/settings.json) не попадает ни в --add-dir, ни в AGENTS.md окна, ни в repo_items."""
    foreign = os.path.join(tmp, "foreign3")
    put(os.path.join(foreign, "AGENTS.md"), "FOREIGN-SECRET\n")
    put(os.path.join(foreign, ".claude", "settings.json"), {"env": {"FOREIGN_KEY": "1"}})
    proj = os.path.join(tmp, "projects", "lk")
    put(os.path.join(proj, "AGENTS.md"), "LK-OK\n")
    put(os.path.join(proj, "ok", "AGENTS.md"), "OK-SUB\n")
    os.symlink(foreign, os.path.join(proj, "app"))  # папка реестра — ссылка
    os.symlink(tmp, os.path.join(tmp, "projects", "via"))  # ~/projects/via/foreign3 — ссылка звеном via
    os.makedirs(os.path.join(proj, "dot"))
    os.symlink(os.path.join(foreign, ".claude"), os.path.join(proj, "dot", ".claude"))  # на месте .claude
    for p, why in ((os.path.join(proj, "app", "AGENTS.md"), "папка-ссылка"),
                   (os.path.join(tmp, "projects", "via", "foreign3", "AGENTS.md"), "ссылка в середине"),
                   (os.path.join(proj, "dot", ".claude", "settings.json"), ".claude-ссылка")):
        check(f"класс 3: самопроверка — {why}: файл по ссылке читается обычным open", os.path.isfile(p), p)
    real_foreign = os.path.realpath(foreign)
    cases = (("папка из domains.json — ссылка", ["~/projects/lk", "~/projects/lk/app"]),
             ("ссылка в середине пути папки", ["~/projects/lk", "~/projects/via/foreign3"]),
             ("папка запуска — ссылка", ["~/projects/lk/app", "~/projects/lk"]))
    for name, folders in cases:
        launch, dirs = P.window_dirs(folders)
        text = "".join(t for _, t in P.window_agents_md(launch, dirs))
        items = [x for d in dirs for x in P.repo_items(d)]
        check(f"класс 3: {name} — чужая папка не в --add-dir, её AGENTS.md и настройки не прочитаны",
              real_foreign not in dirs and launch != real_foreign and "FOREIGN" not in text
              and not any("FOREIGN" in x for x in items) and ("OK-SUB" in text), (launch, dirs, text[:300], items))
    launch, _ = P.window_dirs(cases[2][1])
    check("класс 3: папка запуска через ссылку — window_dirs отдаёт пустую (её файлы не читаются)", launch == "", launch)
    for name, folder, rel in (("папка — ссылка", os.path.join(proj, "app"), "AGENTS.md"),
                              ("ссылка в середине пути", os.path.join(tmp, "projects", "via", "foreign3"), "AGENTS.md"),
                              ("ссылка на месте .claude", os.path.join(proj, "dot"), ".claude/settings.json")):
        check(f"класс 3: _read_in — {name}: None", P._read_in(folder, rel) is None, P._read_in(folder, rel))
    check("класс 3: _read_in .claude-ссылки — repo_items пуст", P.repo_items(os.path.join(proj, "dot")) == [],
          P.repo_items(os.path.join(proj, "dot")))
    put(os.path.join(proj, "real", ".claude", "settings.json"), {"env": {"OWN": "1"}})
    check("класс 3: самопроверка — _read_in обычной папки читает", P._read_in(proj, "AGENTS.md") == "LK-OK\n"
          and P.repo_items(os.path.join(proj, "real")), P.repo_items(os.path.join(proj, "real")))


# --- класс 4: плагины и версии ---
def class4(P, tmp, env):
    pmap = P.plugin_map_load(alert=False)
    for name in ("metis-pantheon", "proteus-morph"):
        win = json.load(open(os.path.join(env["PANTHEON_STATE"], "settings", f"{name}.json")))
        on = {p for p, v in (win.get("enabledPlugins") or {}).items() if v is True}
        keep = P.window_plugins_allowed(pmap, name)
        check(f"класс 4: {name} — включённые плагины окна ⊆ «оставить» карты", on <= keep, sorted(on - keep))
        w = json.load(open(os.path.join(PACKS, name, "window.json")))
        check(f"класс 4: {name} — plugins пакета ⊆ карты окна", set(w.get("plugins") or []) <= keep,
              sorted(set(w.get("plugins") or []) - keep))
    for name in sorted(os.listdir(PACKS)):
        f = os.path.join(PACKS, name, "mcp.json")
        if not os.path.isfile(f):
            continue
        for s, v in json.load(open(f)).get("mcpServers", {}).items():
            words = [v.get("command", "")] + v.get("args", [])
            if "npx" in words:
                pkg = next((t for t in words[words.index("npx") + 1:] if not t.startswith("-")), "")
                check(f"класс 4: {name}/{s} — npx {pkg} с точной версией", PINNED.fullmatch(pkg), words)


def main():
    tmp = os.path.join(ROOT, "h")
    os.makedirs(tmp)
    env = env_for(tmp)
    P = lib(tmp)
    base = {"permissions": {"allow": ["Read"], "deny": ["Bash(rm -rf *)"]}, "env": {"X": "1"},
            "sandbox": {"filesystem": {"allowWrite": ["~/p"], "denyRead": []}, "network": {}, "excludedCommands": []},
            "enabledPlugins": {}}
    ok = P.window_plugins_allowed(P.plugin_map_load(alert=False), "proteus-morph")
    check("класс 1: карта даёт proteus-morph плагины (иначе проверка плагина ничего не значит)", ok, ok)
    class1(P, base, ok)
    class2(tmp, env, P)
    class4(P, tmp, env)
    class2_npx(tmp)
    class2_links(tmp)
    class2_pack_hooks(os.path.join(ROOT, "h2"))
    class2_race(os.path.join(ROOT, "h2"))
    class2_plain_after(os.path.join(ROOT, "h2"))
    class3_links(P, tmp)
    tmp3 = os.path.join(ROOT, "h3")
    os.makedirs(tmp3)
    class3(tmp3, env_for(tmp3))
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
