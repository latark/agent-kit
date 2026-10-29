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
      'does_not = "Чужое"\nexamples = ["раз", "два", "три"]\nleads = ["hephaestus", "apollo"]\n')
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
write(os.path.join(env3["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
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


# пробная сборка ролей (как role apply: alert=False) при битой карте — без тревоги и без метки
tmp4 = os.path.join(ROOT, "p")
env4 = env_for(tmp4)
write(os.path.join(env4["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
r = build_plug(env4, ["--out", os.path.join(tmp4, "out")])
al4 = os.path.join(env4["PANTHEON_HOME"], "alerts.md")
check("битая карта, пробная сборка ролей: код 0, причина в stderr, тревоги и метки нет",
      r.returncode == 0 and "plugins-by-role" in r.stderr
      and not (os.path.exists(al4) and "карта плагинов" in open(al4, encoding="utf-8").read())
      and not os.path.isdir(os.path.join(env4["PANTHEON_STATE"], "once")), r.stderr[-300:])

# guard@agent-kit в каталоге (проба argus-207): карта не применяется, guard и pantheon включены во всех окнах
write(os.path.join(plug, "plugins-by-role.toml"),
      open(MAP, encoding="utf-8").read().replace('plugins = [\n  "typescript-lsp', 'plugins = [\n  "guard@agent-kit", '
                                                 '"pantheon@agent-kit",\n  "typescript-lsp', 1))
tmp5 = os.path.join(ROOT, "g")
env5 = env_for(tmp5)
write(os.path.join(env5["PANTHEON_HOME"], "directions.toml"), '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
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

print(f"\n{len(total) - len(fails)} из {len(total)} прошли")
sys.exit(1 if fails else 0)
