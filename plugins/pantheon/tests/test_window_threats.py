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
  .claude или .claude/hooks — ссылка; .env через ссылку env_from.py не читает;
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
    ("плагин вне карты окна", {"plugins": ["context7@claude-plugins-official"]}),
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
    put(os.path.join(foreign, ".env.local"), "TOKEN=FOREIGN\n")
    put(os.path.join(proj, "real", ".env.local"), "TOKEN=OWN\n")
    probe = "import os; print(os.environ.get('TOKEN'))"
    for name, f, want in (("через ссылку папки — не прочитан, выход 1", os.path.join(proj, "app", ".env.local"), None),
                          ("обычный — имя передано", os.path.join(proj, "real", ".env.local"), "OWN")):
        r = subprocess.run([sys.executable, "-I", ENV_FROM, f, "TOKEN", "--", sys.executable, "-I", "-c", probe],
                           env=env, capture_output=True, text=True, timeout=30)
        got = r.stdout.strip() if r.returncode == 0 else None
        check(f"класс 2: env_from.py — .env {name}", got == want and (want or r.returncode == 1), (r.returncode, got,
                                                                                                    r.stderr))


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
    class3_links(P, tmp)
    tmp3 = os.path.join(ROOT, "h3")
    os.makedirs(tmp3)
    class3(tmp3, env_for(tmp3))
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
