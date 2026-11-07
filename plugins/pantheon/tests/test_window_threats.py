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
  plugins-by-role.toml;
- круг F (решение Зевса 06.11 23:46) — класс «проверили путь в папке окна, потом исполняем»: хуки и серверы пакета
  исполняются только из снимка (pack_snapshot_make), снятого до старта окна, с проверкой sha256; фоновая подмена и
  переименование промежуточной папки (app, app/.claude — пробы E1 Б1, два mv) не меняют исполняемого, а app ↔ ссылка
  через renamex_np (проба E2 r7) не меняет ни одной папки --add-dir (nested_projects по fd). Мутанты краснеют;
- класс 6 (круг G, решение владельца 07.11 02:27) — мимо песочницы пишет исключённая команда: коммит, собранный
  окном низкоуровневыми git, приходит в .claude/hooks через `git pull . <ветка>`; снимок берёт скрипт репозитория,
  только если его sha256 — эталон направления (~/.claude/pantheon/packs/<направление>/approved.json, поправка Зевса
  02:30), иначе хук пропущен (in_repo.py, выход 0) и Зевсу одна тревога на хеш с диффом; нет файла — скрипты
  направления не исполняются; `pantheon packs hashes` печатает эталоны и ничего не пишет. Долги F1 Д1–Д3 — мутанты
  M5, M3, M6 краснеют.
Во временном HOME, настоящие ~/.claude и ~/ai не трогает. Python 3.14 (metis-0571)."""
import atexit
import contextlib
import copy
import fnmatch
import hashlib
import inspect
import io
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
P = None  # модуль ядра (lib), main
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
            # in_repo.py исполняет `.claude/hooks/<имя>` только из своего снимка (manifest.json рядом с _bin)
            cut, snap = rest.index("--"), os.path.dirname(os.path.dirname(os.path.normpath(script)))
            man = json.load(open(os.path.join(snap, "manifest.json"))) if os.path.isfile(
                os.path.join(snap, "manifest.json")) else None
            sub = list(rest[cut + 1:])
            for i, t in enumerate(sub):
                if t.startswith(".claude/hooks/"):
                    rel = ((man or {}).get("repos", {}).get(rest[0]) or {}).get(t[len(".claude/hooks/"):])
                    if rel is None and t[len(".claude/hooks/"):] in ((man or {}).get("unapproved", {}).get(rest[0])
                                                                     or {}):
                        return out, errs  # не одобрен (класс 6): in_repo.py — отказ, ничего не исполняет
                    if rel is None:
                        errs.append((why, f"{t}: in_repo.py не из снимка или скрипта нет в снимке"))
                    sub[i] = os.path.join(snap, rel) if rel else os.path.join(rest[0], t)
            sub_out, sub_errs = execs(sub, rest[0], why)
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


def pack_execs(home, state, name, plugin):
    """Все исполняемые файлы пакета name: хуки (hooks.json плагина plugin — --plugin-dir окна), серверы
    (settings/run/<name>.mcp.json)."""
    out, errs = [], []
    hooks_file = os.path.join(plugin, "hooks", "hooks.json")
    hooks = json.load(open(hooks_file)).get("hooks", {}) if os.path.isfile(hooks_file) else {}
    for ev, groups in hooks.items():
        for g in groups:
            for h in g["hooks"]:
                if h.get("type") != "command":
                    continue
                c = h["command"].replace("${CLAUDE_PLUGIN_ROOT}", plugin).replace("$HOME", home)
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
    for f in ("other/mailkeeper/.claude/hooks/guard_bash.py", "other/mailkeeper/.claude/hooks/guard_read.py",
              "MorphStream/app/.claude/hooks/protect-db.sh", "MorphStream/app/.claude/hooks/pre-commit-check.sh",
              "MorphStream/gpu-worker/.claude/hooks/pre-commit-check.sh"):
        put(os.path.join(tmp, "projects", f), "exit 0\n")
    put(os.path.join(env["PANTHEON_HOME"], "directions.toml"),
        '[[direction]]\nname = "metis-pantheon"\nfolders = ["~/projects/agent-kit", "~/.claude", '
        '"~/projects/other/mailkeeper"]\n[[direction]]\nname = "proteus-morph"\nfolders = ["~/projects/MorphStream"]\n')
    r = run(env, "domains", "build")
    check("класс 2: сборка окон с настоящими пакетами прошла", r.returncode == 0, r.stderr)
    for name in ("metis-pantheon", "proteus-morph"):
        r = run(env, "start", name, "x", "--from", "zeus", "--dry-run")
        check(f"класс 2: start {name} --dry-run прошёл", r.returncode == 0, (r.stdout[-500:], r.stderr))
        win = json.load(open(os.path.join(state, "settings", f"{name}.json")))
        line = next((x for x in r.stdout.splitlines() if "--plugin-dir" in x), "")
        toks = shlex.split(line) if line else []
        plugin = toks[toks.index("--plugin-dir") + 1] if "--plugin-dir" in toks else ""
        check(f"класс 2/F: {name} — --plugin-dir из снимка settings/run/packs, не packs/ (решение Зевса 06.11 23:46)",
              os.path.dirname(os.path.dirname(plugin)) == os.path.join(state, "settings", "run", "packs")
              and os.path.isfile(os.path.join(os.path.dirname(plugin), "manifest.json")), (plugin, r.stdout[-800:]))
        # класс 6: скрипты репозиториев здесь — «exit 0», не эталоны пакета: в снимок не взяты, запуск о них сказал
        man = json.load(open(os.path.join(os.path.dirname(plugin), "manifest.json"))) if plugin else {}
        want = {(os.path.join(home, x), n) for x, n in {
            "metis-pantheon": [("projects/other/mailkeeper", "guard_bash.py"), ("projects/other/mailkeeper",
                                                                                 "guard_read.py")],
            "proteus-morph": [("projects/MorphStream/app", "protect-db.sh"), ("projects/MorphStream/app",
                                                                               "pre-commit-check.sh"),
                              ("projects/MorphStream/gpu-worker", "pre-commit-check.sh")]}[name]}
        got = {(rp, n) for rp, ns in man.get("unapproved", {}).items() for n in ns}
        check(f"класс 6: {name} — скрипты не по эталону пакета в снимок не взяты (unapproved), запуск окна назвал "
              "их строкой «не одобрен»", got == want and not any(man.get("repos", {}).values())
              and r.stderr.count("не одобрен (хеш") == len(want), (got, want, man.get("repos"), r.stderr[-600:]))
        hashes, warn = P.pack_hashes(name)
        listed = {(rp.replace("$HOME", os.path.realpath(home)), n) for rp, v in (hashes or {}).get("repos", {}).items()
                  for n in v["scripts"]}
        check(f"класс 6: packs hashes {name} — sha256 каждого скрипта хуков пакета и только их; HEAD нет — сказано",
              listed == set(P.pack_hook_scripts(os.path.join(PACKS, name))) == want and all(
                  h == hashlib.sha256(b"exit 0\n").hexdigest() for v in hashes["repos"].values()
                  for h in v["scripts"].values()) and any("HEAD" in w for w in warn), (listed, want, warn))
        approved_home = os.path.join(home, ".claude", "pantheon")
        r = run(env, "packs", "hashes", name)
        check(f"класс 6: pantheon packs hashes {name} — JSON в stdout, код 1 (HEAD не прочитан), "
              "~/.claude/pantheon/packs не создан", r.returncode == 1 and json.loads(r.stdout) == hashes
              and not os.path.exists(os.path.join(approved_home, "packs")), (r.returncode, r.stdout[-300:], r.stderr))
        mcp_file = os.path.join(state, "settings", "run", f"{name}.mcp.json")
        scripts = [a for v in (json.load(open(mcp_file)).get("mcpServers", {}) if os.path.isfile(mcp_file) else {}
                               ).values() for a in v.get("args", []) if a.endswith(".py")]
        check(f"класс 2/F: {name} — скрипты серверов mcp.json (${{PANTHEON_PACK_BIN}}) — из _bin того же снимка",
              all(a.startswith(os.path.join(os.path.dirname(plugin), "_bin") + "/") for a in scripts)
              and (scripts or name == "metis-pantheon"), scripts)
        repos = {"metis-pantheon": ["projects/other/mailkeeper"],
                 "proteus-morph": ["projects/MorphStream/app", "projects/MorphStream/gpu-worker"]}[name]
        lit = [os.path.join(home, x, ".claude", "hooks") for x in repos]
        dw = win["sandbox"]["filesystem"].get("denyWrite", [])
        check(f"класс 2/F: {name} — .claude/hooks репозиториев снимка литералом в denyWrite (предки — не "
              "переименовать)", all(x in dw for x in lit), (lit, dw))
        out, errs, servers = pack_execs(home, state, name, plugin)
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


def approve_now(pairs):
    """Эталоны {репозиторий: {имя: sha256}} нынешних файлов pairs — как если бы владелец их одобрил (класс 6)."""
    out = {}
    for repo, name in pairs:
        f = os.path.join(repo, ".claude", "hooks", name)
        if os.path.isfile(f) and not os.path.islink(f):
            out.setdefault(repo, {})[name] = hashlib.sha256(open(f, "rb").read()).hexdigest()
    return out


def snap_of(tmp, label, bin_dir, pairs=(), plugin_dir=None, home=None, approved=None, make=None):
    """Снимок ядра (pack_snapshot_make — как window_launch до старта окна) из bin_dir, плагина plugin_dir и скриптов
    pairs [(репозиторий, имя)] → путь к нему. home — $HOME хуков пакета: скрипты из hooks.json (pack_hook_scripts).
    approved — эталоны (класс 6); не задан — одобрены нынешние файлы (approve_now). make — подмена pack_snapshot_make
    (мутант)."""
    old = P.HOME
    P.HOME = home or old
    try:
        pairs = list(pairs) + (P.pack_hook_scripts(plugin_dir) if plugin_dir else [])
        return (make or P.pack_snapshot_make)(os.path.join(tmp, "snaps"), label, bin_dir, plugin_dir, pairs,
                                              approve_now(pairs) if approved is None else approved)
    finally:
        P.HOME = old


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
    """Хук чужой папки не исполняется, если репозиторий, звено пути, его .claude или .claude/hooks подменены ссылкой
    (окно пишет папку-родителя): репозиторий или звено — in_repo.py выход 2; .claude или .claude/hooks — снимок скрипт
    по ссылке не берёт, in_repo.py выход 1. Обычная папка — исполнен (самопроверка); in_repo.py не из снимка скрипт
    репозитория не исполняет (выход 2)."""
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
    cases = (("репозиторий — ссылка", "$HOME/projects/hk/app", 2),
             ("ссылка в середине пути", "$HOME/projects/midp/foreign-hooks", 2),
             (".claude — ссылка", "$HOME/projects/hk/dot", 1), (".claude/hooks — ссылка", "$HOME/projects/hk/hooks", 1))
    pairs = [(repo.replace("$HOME", tmp), "x.sh") for _, repo, _ in cases] + [(os.path.join(proj, "real"), "x.sh")]
    snap = snap_of(tmp, "links", os.path.join(PACKS, "_bin"), pairs, home=tmp)

    def hook(repo, wrapper=os.path.join(snap, "_bin", "in_repo.py")):
        if os.path.exists(mark):
            os.unlink(mark)
        r = subprocess.run([sys.executable, "-I", wrapper, repo, "--always", "--", "bash", ".claude/hooks/x.sh"],
                           input="{}", env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, os.path.exists(mark), r.stderr

    man = json.load(open(os.path.join(snap, "manifest.json")))
    for name, repo, want in cases:
        rc, ran, err = hook(repo.replace("$HOME", tmp))
        check(f"класс 2: хук — {name}: в снимок не взят, не исполнен, выход {want}",
              rc == want and not ran and repo.replace("$HOME", tmp) not in man["repos"], (rc, ran, err, man["repos"]))
    rc, ran, err = hook(os.path.join(proj, "real"))
    check("класс 2: самопроверка — хук обычной папки из снимка исполнен", rc == 0 and ran, (rc, ran, err))
    rc, ran, err = hook(os.path.join(proj, "real"), IN_REPO)
    check("класс 2/F: in_repo.py не из снимка (packs/_bin) — скрипт репозитория не исполнен, выход 2",
          rc == 2 and not ran and "не из снимка" in err, (rc, ran, err))
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
        res = run_pack_hooks(home, app, gpu, os.path.join(snap_of(tmp, "ph", os.path.join(PACKS, "_bin"), (), root,
                                                                  home), "plugin"))
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
    res = run_pack_hooks(home, app, gpu, os.path.join(snap_of(tmp, "ph-old", os.path.join(PACKS, "_bin"),
                                                              [(app, "check-reexport.sh")], root, home), "plugin"), old)
    check("класс 2: самопроверка — прежний check-reexport.sh по ссылке app/app пишет в чужую папку (проба C1/C2)",
          tree(foreign) != before, res)
    check("класс 2: самопроверка — прежний pre-commit без --plain читает чужое по ссылке src/shared и app/lnk.py",
          any(MARK in o for _, _, _, o in res) and any("❌ app/lnk.py" in o for _, _, _, o in res), res)
    # без ссылок замена делает то же, что check-reexport.sh: новый re-export создан, устаревший обновлён
    home = os.path.join(tmp, "packhooks-plain")
    app, gpu, foreign = morph(home, None)
    res = run_pack_hooks(home, app, gpu, os.path.join(snap_of(tmp, "ph-plain", os.path.join(PACKS, "_bin"), (), root,
                                                              home), "plugin"))
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



# мутант in_repo.py: скрипт `.claude/hooks/<имя>` — из репозитория по пути (как до круга F), а не из снимка
SCRIPT_FROM_REPO = (
    '        if not isinstance(rel, str):\n'
    '            raise FileNotFoundError(f"{arg}: нет в снимке окна (снимок берётся при запуске окна)")\n'
    '        return open_snap(man, rel)\n',
    '        return os.open(os.path.join(repo, arg), os.O_RDONLY)\n')
NO_HASH = ("if hashlib.sha256(_read_fd(fd, MANIFEST_LIMIT)).hexdigest() != want:", "if False:")
SWAP_NP = r"""
import ctypes, os, sys
d, a, b, stop = sys.argv[1:5]
os.chdir(d)
rx = ctypes.CDLL(None).renamex_np
n = 0
while not os.path.exists(stop):
    if rx(a.encode(), b.encode(), 2) == 0:  # RENAME_SWAP: a и b меняются местами одним вызовом
        n += 1
if n % 2:
    rx(a.encode(), b.encode(), 2)
print(n)
"""


def swap_np(d, a, b, stop):
    """Фоновый обмен d/a ↔ d/b (renamex_np, RENAME_SWAP) — как отвязанный ребёнок прошлой сессии окна."""
    if os.path.exists(stop):
        os.unlink(stop)
    return subprocess.Popen([sys.executable, "-I", "-c", SWAP_NP, d, a, b, stop], stdout=subprocess.PIPE, text=True)


def swap_stop(procs, stop):
    put(stop, "")
    return [int(p.communicate(timeout=30)[0].strip() or 0) for p in procs]


def class_f_dirs(tmp):
    """Проба E2 r7: окно меняет app ↔ ссылку на чужую папку (renamex_np) в любой миг — nested_projects и window_dirs
    не возвращают ни одной чужой папки для --add-dir; мутант «realpath после проверки» (как до круга F) — возвращает."""
    if sys.platform != "darwin":
        print("     пропущено: нужен macOS (renamex_np) — круг F, проба E2 r7")
        return
    ms, foreign = os.path.join(tmp, "projects", "MF"), os.path.join(tmp, "fF")
    put(os.path.join(ms, "app", "CLAUDE.md"), "own\n")
    put(os.path.join(foreign, "CLAUDE.md"), "foreign\n")
    os.symlink(foreign, os.path.join(ms, "lnk"))
    src = inspect.getsource(P.nested_projects)
    old = "out.append(os.path.join(top, n))"
    assert old in src
    ns = dict(P.__dict__)
    exec(src.replace(old, "out.append(os.path.realpath(os.path.join(top, n)))"), ns)
    mutant = ns["nested_projects"]
    stop, n, far = os.path.join(tmp, "f-dirs.stop"), 3000, os.path.realpath(foreign)

    def bad(out):  # папка --add-dir — только строка внутри ms (её имя окна), не чужая папка, куда вела ссылка
        return [d for d in out if not d.startswith(ms + "/") or d == far or os.path.dirname(d) != ms]

    sw = swap_np(ms, "app", "lnk", stop)
    try:
        got = [P.nested_projects(ms) for _ in range(n)] + [P.window_dirs([ms])[1] for _ in range(n // 6)]
        mut = [mutant(ms) for _ in range(n)]
    finally:
        swaps = swap_stop([sw], stop)
    hit = [o for o in got if bad(o)]
    check(f"круг F: проба E2 r7 — app ↔ ссылка (renamex_np) фоном, {len(got)} вызовов nested_projects и window_dirs: "
          "ни одной чужой папки для --add-dir", not hit, hit[:3])
    check("круг F: самопроверка — обмен шёл, своя папка находилась", swaps[0] > n and any(got), (swaps, sum(map(bool, got))))
    check("круг F: самопроверка — мутант «realpath после проверки» отдаёт чужую папку",
          any(bad(o) for o in mut), sum(bool(bad(o)) for o in mut))


def class_f_hooks(tmp):
    """Проба E1 Б1 и её фоновый вариант: окно кладёт свой .claude_new/hooks и переименовывает app/.claude (два mv),
    а затем без остановки меняет местами app/.claude ↔ чужую .claude и app ↔ чужой репозиторий. Хук идёт из снимка:
    чужой скрипт не исполнен ни разу, файлы снимка не изменились (sha256 манифеста) и не пишутся; снимок с
    испорченным файлом не исполняется; правка скрипта окном попадает только в следующий снимок (следующий запуск).
    Мутанты «скрипт из репозитория по пути» и «без сверки хеша» исполняют чужое."""
    home = os.path.join(tmp, "fhome")
    app = os.path.join(home, "projects", "MorphStream", "app")
    log = os.path.join(tmp, "f-hooks.log")
    own_sh = 'echo OWN >> "$F_LOG"\n'
    put(os.path.join(app, ".claude", "hooks", "protect-db.sh"), own_sh)
    env = {"PATH": os.environ["PATH"], "HOME": home, "F_LOG": log}
    pairs = [(app, "protect-db.sh")]
    good = snap_of(tmp, "f", os.path.join(PACKS, "_bin"), pairs)
    m_repo = snap_of(tmp, "f-repo", mutant_bin(tmp, "f-repo", {"in_repo.py": [SCRIPT_FROM_REPO]}), pairs)
    m_hash = snap_of(tmp, "f-hash", mutant_bin(tmp, "f-hash", {"in_repo.py": [NO_HASH]}), pairs)
    man = json.load(open(os.path.join(good, "manifest.json")))
    digest = lambda s: {r: hashlib.sha256(open(os.path.join(s, r), "rb").read()).hexdigest()  # noqa: E731
                        for r in json.load(open(os.path.join(s, "manifest.json")))["files"]}
    before = digest(good)

    def hook(snap):
        if os.path.exists(log):
            os.unlink(log)
        r = subprocess.run([sys.executable, "-I", os.path.join(snap, "_bin", "in_repo.py"), app, "--always", "--",
                            "bash", ".claude/hooks/protect-db.sh"], input="{}", env=env, cwd=home,
                           capture_output=True, text=True, timeout=30)
        words = open(log).read().split() if os.path.exists(log) else []
        return words.count("FOREIGN"), words.count("OWN"), r.returncode, r.stderr

    # E1 Б1 статично: два mv после снятия снимка
    put(os.path.join(app, ".claude_new", "hooks", "protect-db.sh"), 'echo FOREIGN >> "$F_LOG"\n')
    os.rename(os.path.join(app, ".claude"), os.path.join(app, ".claude_old"))
    os.rename(os.path.join(app, ".claude_new"), os.path.join(app, ".claude"))
    got = hook(good)
    check("круг F: проба E1 Б1 (mv .claude .claude_old; mv .claude_new .claude) — исполнен свой скрипт из снимка",
          got[:3] == (0, 1, 0), got)
    got = hook(m_repo)
    check("круг F: самопроверка — мутант «скрипт из репозитория по пути» после двух mv исполняет чужой", got[0] == 1, got)
    # фоном: app/.claude ↔ чужая .claude и app ↔ чужой репозиторий
    if sys.platform == "darwin":
        put(os.path.join(home, "projects", "MorphStream", "evil", ".claude", "hooks", "protect-db.sh"),
            'echo FOREIGN >> "$F_LOG"\n')
        stop, n = os.path.join(tmp, "f-hooks.stop"), 150
        res = {"снимок": [0, 0, 0], "мутант": [0, 0, 0]}
        sws = [swap_np(app, ".claude", ".claude_old", stop)]
        sws.append(swap_np(os.path.dirname(app), "app", "evil", stop))
        try:
            for _ in range(n):
                for label, s in (("снимок", good), ("мутант", m_repo)):
                    f, o, rc, _ = hook(s)
                    res[label] = [res[label][0] + f, res[label][1] + o, res[label][2] + (rc == 2)]
        finally:
            swaps = swap_stop(sws, stop)
        check(f"круг F: фоновая подмена app/.claude и app, {n} запусков хука из снимка — 0 чужих исполнений",
              res["снимок"][0] == 0 and res["снимок"][1] > 0, (res, swaps))
        check("круг F: самопроверка — подмена шла, мутант «скрипт по пути» под ней исполняет чужой",
              min(swaps) > n and res["мутант"][0] > 0, (res, swaps))
    else:
        print("     пропущено: нужен macOS (renamex_np) — круг F, фоновая подмена")
    after = digest(good)
    modes = {r: os.stat(os.path.join(good, r)).st_mode & 0o222 for r in man["files"]}
    check("круг F: файлы снимка не изменились (sha256 = манифест) и без права записи",
          after == before == man["files"] and not any(modes.values()), (after == before, modes))
    # испорченный файл снимка (окно его не пишет — это модель сбоя): без исполнения, выход 2; мутант без хеша — исполнит
    for label, s in (("снимок", good), ("мутант", m_hash)):
        f = os.path.join(s, json.load(open(os.path.join(s, "manifest.json")))["repos"][app]["protect-db.sh"])
        os.chmod(f, 0o644)
        put(f, 'echo FOREIGN >> "$F_LOG"\n')
        got = hook(s)
        if label == "снимок":
            check("круг F: файл снимка не совпал с манифестом — не исполнен, выход 2", got[0] == 0 and got[2] == 2, got)
        else:
            check("круг F: самопроверка — мутант «без сверки хеша» исполняет испорченный файл снимка", got[0] == 1, got)
    # снимок обновляется только следующим запуском: правка скрипта окном — новый снимок, старый цел
    os.rename(os.path.join(app, ".claude_old"), os.path.join(app, ".claude_x"))
    put(os.path.join(app, ".claude", "hooks", "protect-db.sh"), 'echo NEW >> "$F_LOG"\n')
    own = {app: {"protect-db.sh": hashlib.sha256(own_sh.encode()).hexdigest()}}
    with contextlib.redirect_stderr(io.StringIO()):
        unok = snap_of(tmp, "f", os.path.join(PACKS, "_bin"), pairs, approved=own)
    got = hook(unok)
    check("круг G: правка скрипта окном без нового эталона — в снимок не взята, хук пропущен (выход 0), не исполнен",
          got[:3] == (0, 0, 0) and "не одобрен" in got[3], got)
    fresh = snap_of(tmp, "f", os.path.join(PACKS, "_bin"), pairs)
    again = snap_of(tmp, "f", os.path.join(PACKS, "_bin"), pairs)
    check("круг F: правка скрипта с новым эталоном — новый снимок у следующего запуска (старый на месте: его держит "
          "идущая сессия), тот же снимок при тех же файлах", fresh == again != good and os.path.isdir(good)
          and hook(fresh)[:3] == (0, 0, 0) and open(log).read().split() == ["NEW"], (fresh, good))


# --- класс 6: мимо песочницы пишет не окно, а исключённая из неё команда (ревью argus F1 Б1, F2 Б1 PR #360) ---
NO_APPROVAL = ("if (approved.get(repo) or {}).get(script) != digest:", "if False:")
NO_FILE_RUNS = ("if (approved.get(repo) or {}).get(script) != digest:",
                "if approved and (approved.get(repo) or {}).get(script) != digest:")
ALERT_EVERY = ('alert_once(key, "1", text, who="pantheon")', 'alert(text, who="pantheon")')
UNAPPROVED_AS_MISSING = ("if not isinstance(rel, str) and isinstance(digest, str):", "if False:")
WRITES_APPROVED = ("print(json.dumps(got, ensure_ascii=False, indent=2, sort_keys=True))",
                   "os.makedirs(os.path.dirname(pack_approved_path(rest[1])), exist_ok=True); "
                   "open(pack_approved_path(rest[1]), 'w').write(json.dumps(got))")


def git(repo, *a, env=None, inp=None):
    """git в repo без настроек пользователя (GIT_CONFIG_GLOBAL — /dev/null) → stdout; сбой — исключение."""
    e = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="t",
             GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", **(env or {}))
    return subprocess.run(["git", "-C", repo, *a], env=e, input=inp, capture_output=True, text=True, timeout=60,
                          check=True).stdout.strip()


def mutant_fn(fn, old, new):
    """Функция ядра fn с заменой old → new в её исходнике (мутант для самопроверки); замена обязана сработать."""
    src = inspect.getsource(fn)
    assert src.count(old) == 1, (fn.__name__, old)
    ns = dict(P.__dict__)
    exec(src.replace(old, new), ns)
    return ns[fn.__name__]


@contextlib.contextmanager
def patched(**kw):
    """Атрибуты модуля ядра P на время блока (HOME, PACKS, PACK_APPROVED_HOME, функции-мутанты)."""
    old = {k: getattr(P, k) for k in kw}
    for k, v in kw.items():
        setattr(P, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(P, k, v)


def tree_state(top):
    """{путь: байты} всех файлов под top (нет папки — {}): было ли что-то записано."""
    out = {}
    for dp, _, fns in os.walk(top):
        for n in fns:
            with open(os.path.join(dp, n), "rb") as fh:
                out[os.path.join(dp, n)] = fh.read()
    return out


def class_g_pull(tmp):
    """Класс 6 (решение владельца 07.11 02:27 «А — хуки с вашим одобрением», поправка Зевса 02:30): окно в песочнице
    собирает коммит низкоуровневыми git (пишутся только .git/objects и refs — рабочая копия не тронута), а `git pull .
    <ветка>` из excludedCommands окна идёт мимо песочницы и переписывает .claude/hooks/protect-db.sh. Литеральный
    denyWrite такую запись не держит. Эталоны — в данных пользователя ~/.claude/pantheon/packs/<направление>/
    approved.json (PACK_APPROVED_HOME), их печатает `pantheon packs hashes` и ничего не пишет. Следующий запуск окна
    (pack_snapshot) скрипт с чужим хешем в снимок не берёт — хук пропущен (in_repo.py, выход 0), чужое не исполнено,
    Зевсу одна тревога на хеш со старым и новым sha256 и диффом от коммита одобрения. Нет approved.json — скрипты
    направления не исполняются, та же тревога. Мутанты «без сверки», «без файла исполняем», «тревога на каждый
    запуск», «не одобрен — как нет скрипта» (in_repo.py) и «пишет approved.json» краснеют."""
    home = os.path.join(tmp, "ghome")
    app = os.path.join(home, "projects", "MorphStream", "app")
    log, hooks_rel = os.path.join(tmp, "g-pull.log"), ".claude/hooks/protect-db.sh"
    own, evil = 'echo OWN >> "$G_LOG"\n', 'echo EVIL >> "$G_LOG"\n'
    put(os.path.join(app, hooks_rel), own)
    git(app, "init", "-q", "-b", "main")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "свои хуки")
    head = git(app, "rev-parse", "HEAD")
    # пакет направления gwin: хук protect-db.sh через in_repo.py, как у proteus-morph
    packs, win = os.path.join(tmp, "gpacks"), "gwin"
    shutil.copytree(os.path.join(PACKS, "_bin"), os.path.join(packs, "_bin"))
    put(os.path.join(packs, win, ".claude-plugin", "plugin.json"), {"name": "gwin"})
    put(os.path.join(packs, win, "hooks", "hooks.json"), {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": 'python3 -I "${CLAUDE_PLUGIN_ROOT}/../_bin/in_repo.py" '
                                       '"$HOME/projects/MorphStream/app" --always -- bash .claude/hooks/protect-db.sh'}]}]}})
    ahome = os.path.join(home, ".claude", "pantheon", "packs")
    afile = os.path.join(ahome, win, "approved.json")
    alerts = os.path.join(P.PANTHEON, "alerts.md")
    env = {"PATH": os.environ["PATH"], "HOME": home, "G_LOG": log}
    mods = dict(HOME=home, PACKS=packs, PACK_APPROVED_HOME=ahome)

    def hook(snap):
        if os.path.exists(log):
            os.unlink(log)
        r = subprocess.run([sys.executable, "-I", os.path.join(snap, "_bin", "in_repo.py"), app, "--always", "--",
                            "bash", hooks_rel], input="{}", env=env, cwd=home, capture_output=True, text=True,
                           timeout=30)
        words = open(log).read().split() if os.path.exists(log) else []
        return words.count("EVIL"), words.count("OWN"), r.returncode, r.stderr

    def launch(label, **mut):
        """Запуск окна: pack_snapshot (как window_launch) → (снимок, stderr, строки тревог класса 6)."""
        err = io.StringIO()
        with patched(**mods, **mut), contextlib.redirect_stderr(err):
            s = P.pack_snapshot(win, label)
        lines = [x for x in (open(alerts, encoding="utf-8").read().splitlines() if os.path.exists(alerts) else [])
                 if f"[metis-0933] {win}:" in x]
        return s, err.getvalue(), lines

    # первичное одобрение: владелец кладёт вывод `pantheon packs hashes` в approved.json (owner-edit)
    with patched(**mods):
        before = tree_state(ahome)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = P.pack_hashes_cmd(["hashes", win])
        printed = json.loads(out.getvalue())
        wrote = tree_state(ahome) != before
    want = {"repos": {"$HOME/projects/MorphStream/app": {
        "commit": head, "scripts": {"protect-db.sh": hashlib.sha256(own.encode()).hexdigest()}}}}
    check("класс 6: packs hashes — нынешние sha256 и HEAD в формате approved.json, код 0, ничего не записано",
          rc == 0 and printed == want and not wrote, (rc, printed, wrote))
    with patched(**mods, pack_hashes_cmd=mutant_fn(P.pack_hashes_cmd, *WRITES_APPROVED)):
        with contextlib.redirect_stderr(io.StringIO()):
            P.pack_hashes_cmd(["hashes", win])
        mutant_wrote = tree_state(ahome) != before
    check("класс 6: самопроверка — мутант «hashes пишет approved.json» замечен", mutant_wrote, tree_state(ahome))
    shutil.rmtree(ahome, ignore_errors=True)
    # без approved.json: скрипты направления не исполняются, одна тревога
    s0, err0, al0 = launch("g0")
    man = json.load(open(os.path.join(s0, "manifest.json")))
    got = hook(s0)
    check("класс 6: approved.json нет — скрипт не в снимке, хук пропущен (выход 0), не исполнен, тревога одна",
          not man["repos"] and got[:3] == (0, 0, 0) and "не одобрен" in got[3] and len(al0) == 1
          and "approved.json нет" in al0[0] and "одобрить?" in al0[0], (man, got, al0, err0))
    m0, _, _ = launch("g0m", pack_snapshot_make=mutant_fn(P.pack_snapshot_make, *NO_FILE_RUNS))
    check("класс 6: самопроверка — мутант «без файла исполняем» исполняет скрипт без эталона", hook(m0)[1] == 1,
          hook(m0))
    put(afile, json.dumps(printed))
    ok_snap, _, al1 = launch("g")
    check("класс 6: самопроверка — скрипт по эталону взят в снимок и исполнен, новой тревоги нет",
          hook(ok_snap)[:3] == (0, 1, 0) and len(al1) == 1, (hook(ok_snap), al1))
    # окно в песочнице: коммит без рабочей копии (hash-object, update-index во временный индекс, commit-tree, update-ref)
    blob = git(app, "hash-object", "-w", "--stdin", inp=evil)
    idx = {"GIT_INDEX_FILE": os.path.join(tmp, "g-evil.index")}
    git(app, "read-tree", "HEAD", env=idx)
    git(app, "update-index", "--add", "--cacheinfo", f"100755,{blob},{hooks_rel}", env=idx)
    commit = git(app, "commit-tree", git(app, "write-tree", env=idx), "-p", "HEAD", "-m", "x")
    git(app, "update-ref", "refs/heads/evil", commit)
    check("класс 6: самопроверка — коммит собран без записи в рабочую копию",
          open(os.path.join(app, hooks_rel)).read() == own, open(os.path.join(app, hooks_rel)).read())
    git(app, "-c", "pull.rebase=false", "pull", "-q", ".", "evil")  # мимо песочницы (excludedCommands окна)
    check("класс 6: самопроверка — git pull . evil переписал .claude/hooks рабочей копии",
          open(os.path.join(app, hooks_rel)).read() == evil, open(os.path.join(app, hooks_rel)).read())
    digest, was = hashlib.sha256(evil.encode()).hexdigest(), hashlib.sha256(own.encode()).hexdigest()
    after, err, al2 = launch("g")
    after2, _, al3 = launch("g")
    man = json.load(open(os.path.join(after, "manifest.json")))
    got = hook(after)
    new = [x for x in al3 if x not in al1]
    check("класс 6: после git pull . evil подменённый скрипт не в снимке (unapproved), хук пропущен (выход 0), чужое "
          "не исполнено", after != ok_snap and not man["repos"] and man["unapproved"] == {app: {"protect-db.sh": digest}}
          and got[:3] == (0, 0, 0) and "не одобрен" in got[3] and "не одобрен" in err, (man, got, err))
    check("класс 6: тревога одна на два запуска окна — «[metis-0933] gwin: хук … изменён, одобрить?», старый и новый "
          "sha256, дифф от коммита одобрения", after2 == after and al2 == al3 and len(new) == 1
          and "protect-db.sh изменён, одобрить?" in new[0] and was in new[0] and digest in new[0]
          and f"{head[:12]}:{hooks_rel}" in new[0] and "-echo OWN" in new[0] and "+echo EVIL" in new[0], (al1, al3))
    m, _, _ = launch("g-mut", pack_snapshot_make=mutant_fn(P.pack_snapshot_make, *NO_APPROVAL))
    check("класс 6: самопроверка — мутант «без сверки с эталоном» берёт подменённый скрипт и исполняет чужое",
          hook(m)[0] == 1, hook(m))
    os.unlink(alerts)
    launch("g-mut3", pack_unapproved_alert=mutant_fn(P.pack_unapproved_alert, *ALERT_EVERY))
    _, _, al4 = launch("g-mut3", pack_unapproved_alert=mutant_fn(P.pack_unapproved_alert, *ALERT_EVERY))
    check("класс 6: самопроверка — мутант «тревога на каждый запуск» пишет вторую строку", len(al4) == 2, al4)
    with patched(**mods), contextlib.redirect_stderr(io.StringIO()):
        m2 = P.pack_snapshot_make(os.path.join(tmp, "snaps"), "g-mut2", mutant_bin(
            tmp, "g-missing", {"in_repo.py": [UNAPPROVED_AS_MISSING]}), None, [(app, "protect-db.sh")], {})
    got = hook(m2)
    check("класс 6: самопроверка — мутант «не одобрен — как нет скрипта» отдаёт выход 1 без строки об одобрении",
          got[2] == 1 and "не одобрен" not in got[3], got)
    # коммит одобрения без объекта — тревога без диффа; новый эталон (одобрение владельца) — исполняется
    put(afile, {"repos": {"$HOME/projects/MorphStream/app": {"commit": "0" * 40, "scripts": {"protect-db.sh": was}}}})
    os.unlink(alerts)
    shutil.rmtree(P.path("once"), ignore_errors=True)  # этот хеш уже был в тревоге: отметки «один раз» — заново
    _, _, al5 = launch("g-noobj")
    check("класс 6: коммита одобрения нет в репозитории — тревога без диффа («объекта … нет»)",
          len(al5) == 1 and "объекта 000000000000" in al5[0] and "+echo EVIL" not in al5[0], al5)
    put(afile, {"repos": {"$HOME/projects/MorphStream/app": {"commit": commit, "scripts": {"protect-db.sh": digest}}}})
    later, _, _ = launch("g")
    check("класс 6: новый эталон в approved.json (одобрение владельца) — тот же скрипт взят и исполнен",
          hook(later)[:3] == (1, 0, 0), hook(later))
    put(os.path.join(tmp, "gpack.json"), {"repos": {"$HOME/x": {"commit": "nothex", "scripts": {
        "a.sh": "0" * 64, "b.sh": "nothex", "c.sh": 1}}, "~/y": [], "$HOME/z": {"commit": "a" * 40, "scripts": []}}})
    with patched(HOME=home):
        got = P.pack_approved(os.path.join(tmp, "gpack.json"))
        none = P.pack_approved(os.path.join(tmp, "nope.json"))
    rh = os.path.realpath(home)
    check("класс 6: pack_approved — $HOME раскрыт, кривые хеш, коммит и не словарь отброшены; нет файла — (None, {})",
          got == ({os.path.join(rh, "x"): {"a.sh": "0" * 64}, os.path.join(rh, "z"): {}},
                  {os.path.join(rh, "z"): "a" * 40}) and none == (None, {}), (got, none))


def class_g_debts(tmp):
    """Долги F1 Д1–Д3 — мутанты M5, M3, M6 ревью argus F1 выживали:
    - Д1 (M5): nested_projects открывает подпапку с O_NOFOLLOW — подпапка-ссылка на чужой проект не идёт в --add-dir;
    - Д2 (M3): in_repo.py сверяет имя папки снимка с sha256 манифеста — снимок с переписанным манифестом (файлы и хеши
      в нём согласованы) не исполняется;
    - Д3 (M6): pack_snapshot_make берёт готовый снимок, только если он цел (_snapshot_intact) — испорченный файл и
      снимок-ссылка собираются заново."""
    ms, foreign = os.path.join(tmp, "projects", "MG"), os.path.join(tmp, "fG")
    put(os.path.join(ms, "app", "CLAUDE.md"), "own\n")
    put(os.path.join(foreign, "CLAUDE.md"), "foreign\n")
    os.symlink(foreign, os.path.join(ms, "lnk"))
    top = os.path.realpath(ms)
    check("долг Д1: nested_projects — подпапка-ссылка на чужой проект не взята", P.nested_projects(ms) ==
          [os.path.join(top, "app")], P.nested_projects(ms))
    m5 = mutant_fn(P.nested_projects, "nfd = os.open(n, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)",
                   "nfd = os.open(n, os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)")
    check("долг Д1: самопроверка — мутант M5 (без O_NOFOLLOW) берёт ссылку", os.path.join(top, "lnk") in m5(ms), m5(ms))
    # Д2: снимок скопирован, его манифест переписан — repos ведёт на чужой файл, хеш в files верный
    home = os.path.join(tmp, "gdebt")
    app = os.path.join(home, "projects", "app")
    log = os.path.join(tmp, "g-debt.log")
    put(os.path.join(app, ".claude", "hooks", "x.sh"), 'echo OWN >> "$G_LOG"\n')
    env = {"PATH": os.environ["PATH"], "HOME": home, "G_LOG": log}
    # мутант строится после основной проверки: внешний мутант той же строки валит её, а не сборку самопроверки
    m3 = lambda: mutant_bin(tmp, "m3", {"in_repo.py": [  # noqa: E731
        ('if not os.path.basename(SNAP).endswith("-" + hashlib.sha256(raw).hexdigest()[:16]):', "if False:")]})
    for label, bdir in (("снимок", lambda: os.path.join(PACKS, "_bin")), ("мутант M3", m3)):
        bdir = bdir()
        s = snap_of(tmp, "gd-" + label[0], bdir, [(app, "x.sh")])
        man = json.load(open(os.path.join(s, "manifest.json")))
        evil = b'echo EVIL >> "$G_LOG"\n'
        os.chmod(s, 0o755)
        put(os.path.join(s, "repo", "evil.sh"), evil.decode())
        man["files"]["repo/evil.sh"] = hashlib.sha256(evil).hexdigest()
        man["repos"][app]["x.sh"] = "repo/evil.sh"
        os.chmod(os.path.join(s, "manifest.json"), 0o644)
        put(os.path.join(s, "manifest.json"), json.dumps(man))
        if os.path.exists(log):
            os.unlink(log)
        r = subprocess.run([sys.executable, "-I", os.path.join(s, "_bin", "in_repo.py"), app, "--always", "--", "bash",
                            ".claude/hooks/x.sh"], input="{}", env=env, cwd=home, capture_output=True, text=True,
                           timeout=30)
        ran = open(log).read().split() if os.path.exists(log) else []
        if label == "снимок":
            check("долг Д2: манифест снимка переписан (имя папки — не его sha256) — обёртка не из снимка, выход 2",
                  r.returncode == 2 and "EVIL" not in ran and "не из снимка" in r.stderr, (r.returncode, ran, r.stderr))
        else:
            check("долг Д2: самопроверка — мутант M3 (без сверки имени папки) исполняет чужое", "EVIL" in ran,
                  (r.returncode, ran, r.stderr))
    # Д3: снимок испорчен (файл) или заменён ссылкой на копию — следующий запуск собирает его заново
    m6 = lambda: mutant_fn(P.pack_snapshot_make, "if not _snapshot_intact(snap, manifest, files):",  # noqa: E731
                           "if not os.path.isdir(snap):")
    for label, make in (("снимок", lambda: None), ("мутант M6", m6)):
        make = make()
        s = snap_of(tmp, "gi-" + label[0], os.path.join(PACKS, "_bin"), [(app, "x.sh")], make=make)
        man = json.load(open(os.path.join(s, "manifest.json")))
        f = os.path.join(s, man["repos"][app]["x.sh"])
        os.chmod(f, 0o644)
        put(f, "echo BROKEN\n")
        s2 = snap_of(tmp, "gi-" + label[0], os.path.join(PACKS, "_bin"), [(app, "x.sh")], make=make)
        fixed = s2 == s and open(f).read() == 'echo OWN >> "$G_LOG"\n'
        copy_dir = s + ".copy"
        shutil.copytree(s, copy_dir)
        shutil.rmtree(s)
        os.symlink(copy_dir, s)
        s3 = snap_of(tmp, "gi-" + label[0], os.path.join(PACKS, "_bin"), [(app, "x.sh")], make=make)
        relinked = not os.path.islink(s3) and os.path.isdir(s3)
        if label == "снимок":
            check("долг Д3: испорченный файл снимка и снимок-ссылка — собраны заново", fixed and relinked,
                  (fixed, relinked))
        else:
            check("долг Д3: самопроверка — мутант M6 (готов, если папка есть) оставляет испорченное",
                  not fixed or not relinked, (fixed, relinked))


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
    snap = lambda label, b: os.path.join(snap_of(tmp, label, b, [(app, "x.sh")]), "_bin")  # noqa: E731
    bin_dir = snap("race", os.path.join(PACKS, "_bin"))
    m_in = snap("race-in", mutant_bin(tmp, "in-path", {"in_repo.py": [
        ('cmd[i] = f"/dev/fd/{sfd}"', "cmd[i] = a"), ("os.fchdir(root)", "pass"),
        ("env=env, input=raw", "env=env, cwd=repo, input=raw"), SCRIPT_FROM_REPO]}))
    m_rh = snap("race-rh", mutant_bin(tmp, "rh-path", {"repo_hooks.py": [(
        "fd = os.dup(root)", 'fd = os.open(os.path.realpath(os.environ["CLAUDE_PROJECT_DIR"]), os.O_RDONLY)')]}))
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
    snap = lambda label, b: os.path.join(snap_of(tmp, label, b, [(app, "pc.sh")]), "_bin")  # noqa: E731
    for label, b in (("fd", snap("plain", os.path.join(PACKS, "_bin"))), ("мутант", snap("plain-m", m))):
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
    global P
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
    class_f_dirs(os.path.join(ROOT, "h2"))
    class_f_hooks(os.path.join(ROOT, "h2"))
    class_g_pull(os.path.join(ROOT, "h2"))
    class_g_debts(os.path.join(ROOT, "h2"))
    class3_links(P, tmp)
    tmp3 = os.path.join(ROOT, "h3")
    os.makedirs(tmp3)
    class3(tmp3, env_for(tmp3))
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
