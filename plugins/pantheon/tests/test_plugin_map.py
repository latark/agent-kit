#!/usr/bin/env python3
"""Карта «окно или роль × плагин и MCP» (metis-0238): plugins-by-role.toml применяется при сборке окон и ролей.

Запуск: python3 -I plugins/pantheon/tests/test_plugin_map.py  (код выхода 0 — все прошли)
- разбор карты: опечатка в «оставить» и плохие типы — ValueError, настоящая карта разбирается;
- окно: карта применяется к каждому окну (направление, свой ключ mnemo-brain, workshop, hestia, hq, job-*) через
  `domains build` на временных HOME и PANTHEON_*; у кого плагина нет в «оставить» — enabledPlugins: false и
  permissions.deny mcp__…, кому он нужен — не выключен; окна не из карты и вне каталога плагины — не тронуты;
- роли: `roles build --out` на настоящих шаблонах: disallowedTools получает mcp__… каждого сервера вне «оставить»,
  прежние запреты остаются, нужный роли сервер не закрыт, роль вне карты (личный слой) — шапка как была;
- битая карта: окна и роли собираются без неё (всё включено) и приходит тревога.
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
RUN_PY = os.path.join(LIB, "run.py")
MAP = os.path.join(PLUGIN, "plugins-by-role.toml")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="plugin-map-test-"))
atexit.register(shutil.rmtree, ROOT, True)
fails, total = [], []


def check(name, cond, extra=""):
    total.append(name)
    print(("ok   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        fails.append(name)


def load_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("plugin_map_t", os.path.join(LIB, "plugin_map.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def head(text, key):
    m = re.search(rf"^{key}:(.*)$", text.split("\n---\n", 1)[0], re.M)
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else None


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def env_for(tmp, extra=None):
    home = os.path.join(tmp, "pantheon")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": os.path.join(tmp, "state"),
           "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp"), "PANTHEON_NO_NOTIFY": "1"}
    os.makedirs(env["PANTHEON_CLAUDE_TMP"], exist_ok=True)
    env.update(extra or {})
    return env


def pantheon(env, *args):
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=env, capture_output=True, text=True, timeout=180)


M = load_mod()
MNEMO = '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/projects/kb"]\n'  # ключ [window.mnemo-brain] карты сверяется с реестром
real = M.load(MAP)
mn = real["window"]["mnemo-brain"]
LSP = "pyright-lsp@claude-plugins-official"
NOTION = "notion@anthropic-plugin-directory"

# --- разбор ---
check("настоящая карта разбирается; окна и роли в ней есть",
      {"direction", "mnemo-brain", "workshop", "hq", "hestia", "job-clio", "job-prometheus", "job-iris"}
      <= set(real["window"]) and {"dev-sonnet", "hestia", "momus", "talos"} <= set(real["role"]))


def bad(text):
    p = os.path.join(ROOT, "bad.toml")
    write(p, text)
    try:
        M.load(p)
    except ValueError as e:
        return str(e)
    return None


CAT = '[catalog]\nplugins = ["a@b"]\nmcp = ["qmd"]\n'
check("«оставить» вне каталога (опечатка) — ValueError", bad(CAT + '[window.x]\nplugins = []\nmcp = ["qmdd"]\n'))
check("у окна нет ключа mcp — ValueError", bad(CAT + '[window.x]\nplugins = []\n'))
check("у роли ключ plugins — ValueError", bad(CAT + '[role.x]\nplugins = []\nmcp = []\n'))
check("нет каталога — ValueError", bad('[window.x]\nplugins = []\nmcp = []\n'))
check("плагин в «оставить» окна вне каталога (опечатка) — ValueError",
      bad(CAT + '[window.x]\nplugins = ["a@bb"]\nmcp = []\n'))
for own in ("guard@agent-kit", "pantheon@agent-kit", "project-tools@agent-kit", "Guard@Agent-Kit"):
    check(f"{own} в [catalog] — ValueError (иначе «оставить» выключило бы его во всех окнах)",
          "agent-kit" in (bad(f'[catalog]\nplugins = ["a@b", "{own}"]\nmcp = []\n') or ""))
check("плагин @builtin и чужой каталог с agent-kit в имени — не ошибка",
      bad('[catalog]\nplugins = ["x@builtin", "y@agent-kit-fork"]\nmcp = []\n') is None)
# Д2: запись с неизвестным именем [window.X]/[role.X] пропускается (в skipped), остальная карта действует
write(os.path.join(ROOT, "names.toml"), CAT + '[window.hq]\nplugins = []\nmcp = []\n[role.r1]\nmcp = []\n')


def names_load(windows, roles, text=None):
    if text:
        write(os.path.join(ROOT, "names2.toml"), text)
    return M.load(os.path.join(ROOT, "names2.toml" if text else "names.toml"), windows, roles)


n = names_load({"hq"}, {"r1"})
check("имена записей известны — ничего не пропущено; windows и roles не заданы — не сверяются",
      n["skipped"] == [] and names_load(None, None)["skipped"] == [] and "hq" in n["window"])
n = names_load({"hq"}, {"r1"}, CAT + '[window.hqq]\nplugins = []\nmcp = []\n[window.hq]\nplugins = []\nmcp = []\n')
check("опечатка в имени окна ([window.hqq]) — запись пропущена и названа, [window.hq] действует, карта не отвергнута",
      n["skipped"] == ["[window.hqq]"] and "hqq" not in n["window"] and "hq" in n["window"], n)
n = names_load({"hq"}, {"r1"}, CAT + '[role.r11]\nmcp = []\n[role.r1]\nmcp = []\n')
check("опечатка в имени роли ([role.r11]) — запись пропущена и названа, [role.r1] действует",
      n["skipped"] == ["[role.r11]"] and "r11" not in n["role"] and "r1" in n["role"], n)
n = names_load({"hq"}, {"r1", "hqq"}, CAT + '[window.r1]\nplugins = []\nmcp = []\n')
n2 = names_load({"hq", "r1"}, {"hq"}, CAT + '[role.r1]\nmcp = []\n')
check("имя из списка ролей не годится для окна и наоборот", n["skipped"] == ["[window.r1]"] and n2["skipped"] == ["[role.r1]"])
try:
    M.load(os.path.join(ROOT, "нет-такого.toml"))
    missing = False
except ValueError:
    missing = True
check("нет файла — ValueError", missing)

# --- функции на выдуманной карте ---
write(os.path.join(ROOT, "small.toml"), '[catalog]\nplugins = ["a@b", "c@d"]\nmcp = ["qmd", "ctx"]\n'
      '[window.direction]\nplugins = ["a@b"]\nmcp = ["qmd"]\n[window.w1]\nplugins = []\nmcp = []\n'
      '[role.r1]\nmcp = ["qmd"]\n')
small = M.load(os.path.join(ROOT, "small.toml"))
d = M.window_apply({}, small, "w1")
check("window_apply: всё из каталога вне «оставить» выключено",
      d == {"enabledPlugins": {"a@b": False, "c@d": False}, "permissions": {"deny": ["mcp__qmd", "mcp__ctx"]}}, d)
d = M.window_apply({"permissions": {"deny": ["mcp__qmd", "Edit"]}}, small, "dir-x", True)
check("окно направления без своей записи берёт «direction»; свои deny остаются, повторов нет",
      d["enabledPlugins"] == {"c@d": False} and d["permissions"]["deny"] == ["mcp__qmd", "Edit", "mcp__ctx"], d)
d = M.window_apply({"permissions": {"deny": ["mcp__ctx", "Edit"]}}, small, "w1")
check("window_apply: заранее записанный mcp__ctx, который карта закрывает, не повторён",
      d["permissions"]["deny"] == ["mcp__ctx", "Edit", "mcp__qmd"], d)
d = M.window_apply(M.window_apply({}, small, "w1"), small, "w1")
check("window_apply дважды — те же правила без повторов",
      d["permissions"]["deny"] == ["mcp__qmd", "mcp__ctx"], d)
check("окна нет в карте и это не окно направления — без изменений (всё включено)",
      M.window_apply({"x": 1}, small, "zzz") == {"x": 1})
nodir = M.load(os.path.join(ROOT, "small.toml"))
del nodir["window"]["direction"]
check("окно направления без «direction» в карте — без изменений", M.window_apply({"x": 1}, nodir, "dir-x", True) == {"x": 1})
t = "---\nname: r1\ndisallowedTools: Edit, mcp__ctx\n---\nтело\n"
check("role_header: допишет только недостающее, прежнее остаётся",
      M.role_header(t, small, "r1") == t and M.role_deny(small, "r1") == ["mcp__ctx"])
t2 = "---\nname: r1\ndisallowedTools: Edit\n---\nтело\n"
check("role_header: mcp__ctx дописан в строку, тело цело",
      M.role_header(t2, small, "r1") == "---\nname: r1\ndisallowedTools: Edit, mcp__ctx\n---\nтело\n")
t3 = "---\nname: r1\n---\nтело\n"
check("role_header: нет строки disallowedTools — добавлена в шапку",
      M.role_header(t3, small, "r1") == "---\nname: r1\ndisallowedTools: mcp__ctx\n---\nтело\n")


def header_err(text):
    try:
        M.role_header(text, small, "r1")
    except ValueError as e:
        return str(e)
    return None


check("role_header: disallowedTools блочным списком YAML (- X ниже) — ValueError, а не дописка в строку",
      header_err("---\nname: r1\ndisallowedTools:\n  - Edit\n---\nтело\n"))
check("role_header: disallowedTools списком [A, B] — ValueError",
      header_err("---\nname: r1\ndisallowedTools: [Edit, Write]\n---\nтело\n"))
check("role_header: disallowedTools с пустым значением — ValueError",
      header_err("---\nname: r1\ndisallowedTools:\n---\nтело\n"))
check("role_header: роль вне карты со списком YAML — как есть, без ошибки",
      M.role_header("---\nname: z\ndisallowedTools:\n  - Edit\n---\n", small, "unknown")
      == "---\nname: z\ndisallowedTools:\n  - Edit\n---\n")
check("unknown_enabled: включённый плагин вне каталога назван; выключенный, @agent-kit и @builtin — нет",
      M.unknown_enabled(small, {"a@b": True, "z@x": True, "off@x": False, "guard@agent-kit": True,
                                "y@builtin": True}) == ["z@x"]
      and M.unknown_enabled(small, None) == [] and M.unknown_enabled(small, {"a@b": True}) == [])
check("роль вне карты — текст как есть (всё включено)", M.role_header(t2, small, "unknown") == t2
      and M.role_deny(small, "unknown") is None)

# --- окна: domains build ---
tmp = os.path.join(ROOT, "w")
env = env_for(tmp)
write(os.path.join(env["PANTHEON_HOME"], "directions.toml"),
      '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n'
      '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/projects/kb"]\n')
for p in ("br", "kb", "workshop"):
    os.makedirs(os.path.join(tmp, "projects", p))
os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
r = pantheon(env, "domains", "build")
check("domains build прошёл", r.returncode == 0, r.stderr[-300:])
sdir = os.path.join(env["PANTHEON_STATE"], "settings")
wins = {n[:-5]: json.load(open(os.path.join(sdir, n))) for n in os.listdir(sdir) if n.endswith(".json")}
check("собраны окна: два направления, workshop, hestia, hq, job-clio, job-prometheus, job-iris",
      {"athena-shop", "mnemo-brain", "workshop", "hestia", "hq", "job-clio", "job-prometheus", "job-iris"} <= set(wins),
      sorted(wins))


def expect(name, key):
    keep = real["window"][key]
    w = wins[name]
    off = {p for p in real["plugins"] if p not in keep["plugins"]}
    got_off = {p for p, v in (w.get("enabledPlugins") or {}).items() if v is False}
    got_deny = {x for x in w["permissions"]["deny"] if x.startswith("mcp__")}
    want_deny = {f"mcp__{m}" for m in real["mcp"] if m not in keep["mcp"]}
    ok = got_off == off and got_deny == want_deny and not any(v is not False for v in (w.get("enabledPlugins") or {}).values())
    return ok, (sorted(got_off ^ off), sorted(got_deny ^ want_deny))


for name, key in (("athena-shop", "direction"), ("mnemo-brain", "mnemo-brain"), ("workshop", "workshop"), ("hq", "hq"),
                  ("hestia", "hestia"), ("job-clio", "job-clio"), ("job-prometheus", "job-prometheus"),
                  ("job-iris", "job-iris")):
    ok, diff = expect(name, key)
    check(f"окно {name}: карта [{key}] применена (плагины и MCP вне «оставить» выключены, остальные нет)", ok, diff)
check("окно направления без своей записи (athena-shop) держит LSP, а mnemo-brain и hq — нет",
      LSP not in wins["athena-shop"].get("enabledPlugins", {}) and wins["mnemo-brain"]["enabledPlugins"][LSP] is False
      and wins["hq"]["enabledPlugins"][LSP] is False)
check("Notion выключен у каждого окна, guard/pantheon/project-tools не тронуты никогда",
      all(w["enabledPlugins"][NOTION] is False and not any(k.split("@")[0] in ("guard", "pantheon", "project-tools")
                                                           for k in w["enabledPlugins"]) for w in wins.values()))
check("qmd у окон hq, athena-shop и job-* оставлен, у hestia закрыт; context7 у hq закрыт, у workshop открыт",
      all("mcp__qmd" not in wins[n]["permissions"]["deny"] for n in ("hq", "athena-shop", "job-clio", "job-iris"))
      and "mcp__qmd" in wins["hestia"]["permissions"]["deny"] and "mcp__context7" in wins["hq"]["permissions"]["deny"]
      and "mcp__context7" not in wins["workshop"]["permissions"]["deny"])
check("прежние deny окон не потеряны (Read личного у hq, Edit у hestia)",
      any(x.startswith("Read(") for x in wins["hq"]["permissions"]["deny"]) and "Edit" in wins["hestia"]["permissions"]["deny"])

# --- роли: настоящие шаблоны, roles build --out ---
tmp2 = os.path.join(ROOT, "r")
env2 = env_for(tmp2)
write(os.path.join(env2["PANTHEON_HOME"], "directions.toml"),
      '[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\ndoes = "Демо"\n'
      'does_not = "Чужое"\nexamples = ["раз", "два", "три"]\nleads = ["hephaestus", "apollo"]\n' + MNEMO)
os.makedirs(os.path.join(tmp2, "projects", "demo"))
out = os.path.join(tmp2, "out")
r = pantheon(env2, "roles", "build", "--out", out)
check("roles build --out на настоящих шаблонах: код 0, без ошибок", r.returncode == 0 and not r.stderr.strip(), r.stderr[-300:])
built = {f[:-3]: open(os.path.join(out, f), encoding="utf-8").read() for f in os.listdir(out) if f.endswith(".md")}
files = {"hephaestus": "hephaestus-demo", "apollo": "apollo-demo"}
for role, entry in real["role"].items():
    text = built.get(files.get(role, role))
    if text is None:
        check(f"роль {role}: собрана", False)
        continue
    dis = head(text, "disallowedTools") or []
    want_deny = {f"mcp__{m}" for m in real["mcp"] if m not in entry["mcp"]}
    have = {x for x in dis if x in {f"mcp__{m}" for m in real["mcp"]}}
    check(f"роль {role}: в disallowedTools все серверы вне «оставить» и ни одного нужного", have == want_deny,
          sorted(have ^ want_deny))
check("прежние запреты ролей остались (dev-sonnet: Agent, SendMessage; hestia: Edit, Write)",
      {"Agent", "SendMessage"} <= set(head(built["dev-sonnet"], "disallowedTools"))
      and {"Edit", "Write"} <= set(head(built["hestia"], "disallowedTools")))
check("momus: Docs не закрыт целиком (нужен роли), qmd закрыт; hestia: qmd и context7 закрыты",
      "mcp__claude_ai_Claude_Docs" not in head(built["momus"], "disallowedTools")
      and "mcp__qmd" in head(built["momus"], "disallowedTools")
      and {"mcp__qmd", "mcp__context7"} <= set(head(built["hestia"], "disallowedTools")))
check("dev-sonnet сохранил свой chrome-devtools (его нет в каталоге, не закрыт)",
      "mcp__chrome-devtools" not in head(built["dev-sonnet"], "disallowedTools") and "chrome-devtools" in built["dev-sonnet"])
r2 = pantheon(env2, "roles", "build", "--out", out)
check("повторная сборка идемпотентна: тот же текст, без повторов в disallowedTools",
      all(open(os.path.join(out, f"{k}.md"), encoding="utf-8").read() == v for k, v in built.items())
      and all(len(set(head(v, "disallowedTools") or [])) == len(head(v, "disallowedTools") or []) for v in built.values()))

# роль вне карты — личный слой: шапка как в шаблоне
src = os.path.join(tmp2, "src")
write(os.path.join(src, "custom.tmpl"), "---\nname: custom\ndescription: личная\n---\nтело\n")
r = pantheon(env2, "roles", "build", "--out", os.path.join(tmp2, "out2"), "--src", src)
custom = open(os.path.join(tmp2, "out2", "custom.md"), encoding="utf-8").read() if r.returncode == 0 else ""
check("личная роль вне карты: disallowedTools не добавлен, всё включено", "name: custom" in custom
      and head(custom, "disallowedTools") is None, r.stderr[-300:])

# --- битая карта: окна и роли — без неё ---
plug = os.path.join(ROOT, "plug")
shutil.copytree(PLUGIN, plug, ignore=shutil.ignore_patterns("tests", "__pycache__", ".git"))
write(os.path.join(plug, "plugins-by-role.toml"), CAT + '[window.hq]\nplugins = []\nmcp = ["опечатка"]\n')
tmp3 = os.path.join(ROOT, "b")
env3 = env_for(tmp3)
write(os.path.join(env3["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
os.makedirs(os.path.join(tmp3, "projects", "br"))
r = subprocess.run([PY311, "-I", os.path.join(plug, "lib", "run.py"), "domains", "build"], env=env3, capture_output=True,
                   text=True, timeout=180)
w = json.load(open(os.path.join(env3["PANTHEON_STATE"], "settings", "hq.json"))) if r.returncode == 0 else {}
check("битая карта: код 0, причина в stderr, окна собраны без enabledPlugins и mcp__ (всё включено)",
      r.returncode == 0 and "plugins-by-role" in r.stderr and "enabledPlugins" not in w
      and not any(x.startswith("mcp__") for x in w.get("permissions", {}).get("deny", [])), r.stderr[-300:])
alerts = os.path.join(env3["PANTHEON_HOME"], "alerts.md")
check("битая карта: тревога в alerts.md, причина названа",
      os.path.exists(alerts) and "карта плагинов" in open(alerts, encoding="utf-8").read())

once_dir = os.path.join(env3["PANTHEON_STATE"], "once")


def once(key):
    return [f for f in os.listdir(once_dir) if f.startswith(key + "-")] if os.path.isdir(once_dir) else []


check("битая карта: метка тревоги plugin-map-bad записана (повтор молчит)", once("plugin-map-bad"))


def build_plug(env_, what="domains"):
    args = ["domains", "build"] if what == "domains" else ["roles", "build", *what]
    return subprocess.run([PY311, "-I", os.path.join(plug, "lib", "run.py"), *args], env=env_, capture_output=True,
                          text=True, timeout=180)


# тревога одна (Д1): вторая и третья сборка с той же битой картой не добавляют строк в alerts.md
bad_lines = lambda: [x for x in open(alerts, encoding="utf-8").read().splitlines() if "карта плагинов" in x]
n_bad = len(bad_lines())
build_plug(env3)
build_plug(env3)
check("битая карта: повторные сборки не повторяют тревогу (строк в alerts.md столько же, сколько после первой)",
      n_bad == 1 and len(bad_lines()) == 1, (n_bad, bad_lines()))

# пробная сборка ролей (как role apply: alert=False) при битой карте — без тревоги и без метки
tmp4 = os.path.join(ROOT, "p")
env4 = env_for(tmp4)
write(os.path.join(env4["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
r = build_plug(env4, ["--out", os.path.join(tmp4, "out")])
al4 = os.path.join(env4["PANTHEON_HOME"], "alerts.md")
check("битая карта, пробная сборка ролей: код 0, причина в stderr, тревоги и метки нет",
      r.returncode == 0 and "plugins-by-role" in r.stderr
      and not (os.path.exists(al4) and "карта плагинов" in open(al4, encoding="utf-8").read())
      and not os.path.isdir(os.path.join(env4["PANTHEON_STATE"], "once")), r.stderr[-300:])

# опечатка в имени окна или роли настоящей карты (Д2): запись пропущена, тревога одна на запись, остальная карта действует
real_map = open(MAP, encoding="utf-8").read()
for typo, what in (("[window.mnemo-brain]", "[window.mnemo-brainn]"), ("[role.argus]", "[role.argu]")):
    write(os.path.join(plug, "plugins-by-role.toml"), real_map.replace(typo, what, 1))
    tmp7 = os.path.join(ROOT, "t" + str(len(what)))
    env7 = env_for(tmp7)
    write(os.path.join(env7["PANTHEON_HOME"], "directions.toml"),
          '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
    os.makedirs(os.path.join(tmp7, "projects", "br"))
    r = build_plug(env7)
    build_plug(env7)
    build_plug(env7)
    hq7 = json.load(open(os.path.join(env7["PANTHEON_STATE"], "settings", "hq.json"))) if r.returncode == 0 else {}
    ag7 = os.path.join(tmp7, ".claude", "agents", "dev-sonnet.md")
    ds7 = open(ag7, encoding="utf-8").read() if os.path.exists(ag7) else ""
    al7 = os.path.join(env7["PANTHEON_HOME"], "alerts.md")
    lines7 = [x for x in open(al7, encoding="utf-8").read().splitlines() if what in x] if os.path.exists(al7) else []
    check(f"опечатка {what}: код 0, тревога с именем записи одна после трёх сборок, нет plugin-map-bad",
          r.returncode == 0 and len(lines7) == 1 and "карта не применена" not in "".join(lines7), (r.stderr[-300:], lines7))
    check(f"опечатка {what}: остальная карта действует (окно hq без LSP и с mcp__context7 в deny, dev-sonnet закрыт для jetbrains)",
          hq7.get("enabledPlugins", {}).get(LSP) is False and "mcp__context7" in hq7["permissions"]["deny"]
          and "mcp__jetbrains" in (head(ds7, "disallowedTools") or []), (sorted(hq7.get("enabledPlugins", {})), ds7[:200]))
    write(os.path.join(plug, "plugins-by-role.toml"), real_map)  # запись исправлена: метка снята
    build_plug(env7)
    once7 = os.path.join(env7["PANTHEON_STATE"], "once")
    check(f"запись {what} исправлена: метка тревоги снята",
          not [f for f in os.listdir(once7) if f.startswith("plugin-map-name")] if os.path.isdir(once7) else True)
shutil.copy(MAP, os.path.join(plug, "plugins-by-role.toml"))

# две опечатки одного рода: по одной строке тревоги на запись после трёх сборок (метка своя у каждой записи)
write(os.path.join(plug, "plugins-by-role.toml"), real_map + '\n[window.zz1]\nplugins = []\nmcp = []\n'
      '[window.zz2]\nplugins = []\nmcp = []\n')
tmp9 = os.path.join(ROOT, "two")
env9 = env_for(tmp9)
write(os.path.join(env9["PANTHEON_HOME"], "directions.toml"),
      '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
os.makedirs(os.path.join(tmp9, "projects", "br"))
for _ in range(3):
    build_plug(env9)
al9 = open(os.path.join(env9["PANTHEON_HOME"], "alerts.md"), encoding="utf-8").read().splitlines()
check("две опечатки [window.zz1] и [window.zz2], три сборки: по одной строке тревоги на запись",
      len([x for x in al9 if "[window.zz1]" in x]) == 1 and len([x for x in al9 if "[window.zz2]" in x]) == 1, al9)

# роль только из личного слоя (~/.claude/agents) и из --src: запись [role.X] карты применяется, а не пропускается
write(os.path.join(plug, "plugins-by-role.toml"), real_map + '\n[role.mine]\nmcp = []\n[role.fromsrc]\nmcp = ["qmd"]\n')
tmp10 = os.path.join(ROOT, "mine")
env10 = env_for(tmp10)
write(os.path.join(env10["PANTHEON_HOME"], "directions.toml"),
      '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
os.makedirs(os.path.join(tmp10, "projects", "br"))
write(os.path.join(tmp10, ".claude", "agents", "mine.tmpl"), "---\nname: mine\ndescription: личная\n---\nтело\n")
r = build_plug(env10)
mine = os.path.join(tmp10, ".claude", "agents", "mine.md")
mine_t = open(mine, encoding="utf-8").read() if os.path.exists(mine) else ""
al10 = os.path.join(env10["PANTHEON_HOME"], "alerts.md")
check("роль только из личного слоя ~/.claude/agents с [role.mine]: запись применена (mcp__qmd закрыт), тревоги нет",
      r.returncode == 0 and "mcp__qmd" in (head(mine_t, "disallowedTools") or [])
      and not (os.path.exists(al10) and "[role.mine]" in open(al10, encoding="utf-8").read()), (r.stderr[-300:], mine_t[:200]))
src10 = os.path.join(tmp10, "mysrc")
write(os.path.join(src10, "fromsrc.tmpl"), "---\nname: fromsrc\ndescription: из src\n---\nтело\n")
r = build_plug(env10, ["--out", os.path.join(tmp10, "out"), "--src", src10])
fs = os.path.join(tmp10, "out", "fromsrc.md")
fs_t = open(fs, encoding="utf-8").read() if os.path.exists(fs) else ""
check("roles build --src: роль только из src с [role.fromsrc] — запись применена (mcp__context7 закрыт), не пропущена",
      r.returncode == 0 and "mcp__context7" in (head(fs_t, "disallowedTools") or []) and "[role.fromsrc]" not in r.stderr,
      (r.stderr[-300:], fs_t[:200]))
shutil.copy(MAP, os.path.join(plug, "plugins-by-role.toml"))

# guard@agent-kit в каталоге (проба argus-207): карта не применяется, guard и pantheon включены во всех окнах
write(os.path.join(plug, "plugins-by-role.toml"),
      open(MAP, encoding="utf-8").read().replace('plugins = [\n  "typescript-lsp', 'plugins = [\n  "guard@agent-kit", '
                                                 '"pantheon@agent-kit",\n  "typescript-lsp', 1))
tmp5 = os.path.join(ROOT, "g")
env5 = env_for(tmp5)
write(os.path.join(env5["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
os.makedirs(os.path.join(tmp5, "projects", "br"))
r = build_plug(env5)
sd5 = os.path.join(env5["PANTHEON_STATE"], "settings")
w5 = {n: json.load(open(os.path.join(sd5, n))) for n in os.listdir(sd5) if n.endswith(".json")} if r.returncode == 0 else {}
check("guard@agent-kit в каталоге: карта отвергнута, окна собраны со всем включённым (enabledPlugins и mcp__ нет)",
      len(w5) >= 5 and "agent-kit" in r.stderr
      and all("enabledPlugins" not in w and not any(x.startswith("mcp__") for x in w["permissions"]["deny"])
              for w in w5.values()), (r.stderr[-300:], sorted(w5)))

# починка карты: тревога plugin-map-bad снимается; включённый у владельца плагин вне каталога — тревога
shutil.copy(MAP, os.path.join(plug, "plugins-by-role.toml"))
write(os.path.join(tmp3, ".claude", "settings.json"), json.dumps({"enabledPlugins": {
    "zz-new@some-market": True, "off@some-market": False, "guard@agent-kit": True, "x@builtin": True, NOTION: True}}))
r = build_plug(env3)
hq3 = json.load(open(os.path.join(env3["PANTHEON_STATE"], "settings", "hq.json")))
check("карта починена: окна снова с картой, метка plugin-map-bad снята (следующая поломка снова встревожит)",
      r.returncode == 0 and hq3.get("enabledPlugins", {}).get(NOTION) is False and not once("plugin-map-bad"),
      (r.stderr[-300:], once("plugin-map-bad")))
lines = [x for x in open(alerts, encoding="utf-8").read().splitlines() if "[catalog] карты" in x]
check("включённый у владельца плагин вне каталога — одна тревога с его именем; выключенный, @agent-kit, @builtin — нет",
      len(lines) == 1 and "zz-new@some-market" in lines[0]
      and not any(x in lines[0] for x in ("off@some-market", "guard@agent-kit", "x@builtin", NOTION)), lines)
build_plug(env3)
check("повторная сборка с тем же списком — тревога не повторена",
      len([x for x in open(alerts, encoding="utf-8").read().splitlines() if "[catalog] карты" in x]) == 1)
write(os.path.join(tmp3, ".claude", "settings.json"), "{битый")
build_plug(env3)
check("настройки не прочесть — метка plugin-map-unknown не снята (сверять не с чем)", once("plugin-map-unknown"))
write(os.path.join(tmp3, ".claude", "settings.json"), json.dumps({"enabledPlugins": {NOTION: True}}))
build_plug(env3)
check("плагин убран из настроек — метка plugin-map-unknown снята", not once("plugin-map-unknown"))

# disallowedTools списком YAML в личной роли из карты: шапка как в шаблоне, ошибка роли
src6 = os.path.join(ROOT, "src6")
write(os.path.join(src6, "talos.tmpl"), "---\nname: talos\ndescription: личная\ndisallowedTools:\n  - Edit\n---\nтело\n")
r = pantheon(env2, "roles", "build", "--out", os.path.join(tmp2, "out6"), "--src", src6)
t6 = os.path.join(tmp2, "out6", "talos.md")
t6 = open(t6, encoding="utf-8").read() if os.path.exists(t6) else ""
check("роль из карты с disallowedTools списком YAML: ошибка роли в stderr, шапка не тронута (список цел, mcp__ нет)",
      "talos.tmpl" in r.stderr and "списком YAML" in r.stderr and "disallowedTools:\n  - Edit\n---" in t6
      and "mcp__" not in t6, (r.stderr[-300:], t6[:200]))

# Д5: settings.json владельца отслеживается `domains build --if-changed`: новый плагин в enabledPlugins -> сборка и тревога
tmp8 = os.path.join(ROOT, "s")
env8 = env_for(tmp8)
write(os.path.join(env8["PANTHEON_HOME"], "directions.toml"),
      '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n' + MNEMO)
os.makedirs(os.path.join(tmp8, "projects", "br"))
settings8 = os.path.join(tmp8, ".claude", "settings.json")
write(settings8, json.dumps({"enabledPlugins": {NOTION: True}}))
pantheon(env8, "domains", "build")
dj = os.path.join(env8["PANTHEON_STATE"], "domains.json")
time.sleep(1.2)
pantheon(env8, "domains", "build", "--if-changed")  # сборка ролей дописывает файлы после отметки: одна доводка, дальше тихо
built0 = json.load(open(dj)).get("built_ts")
t0 = built0 - 100  # настройки старше сборки: пересборки нет (built_ts — целые секунды, mtime файлов дробные: ждём)
os.utime(settings8, (t0, t0))
time.sleep(1.2)
pantheon(env8, "domains", "build", "--if-changed")
check("--if-changed: настройки старше сборки — пересборки нет", json.load(open(dj)).get("built_ts") == built0)
write(settings8, json.dumps({"enabledPlugins": {NOTION: True, "zz-new@some-market": True}}))
t1 = built0 + 50
os.utime(settings8, (t1, t1))
r = pantheon(env8, "domains", "build", "--if-changed")
al8 = os.path.join(env8["PANTHEON_HOME"], "alerts.md")
check("--if-changed: settings.json новее сборки — пересборка и тревога plugin-map-unknown с именем плагина",
      r.returncode == 0 and json.load(open(dj)).get("built_ts") != built0 and os.path.exists(al8)
      and "zz-new@some-market" in open(al8, encoding="utf-8").read(), (r.stderr[-300:], built0))

print(f"\n{len(total) - len(fails)} из {len(total)} прошли")
sys.exit(1 if fails else 0)
