#!/usr/bin/env python3
"""Холст «Кто есть кто.canvas» строится кодом из ролей, реестра и статуса задач (metis-0825, lib/whocanvas.py): новая роль
появляется, удалённая уходит, 🚧 снимается, когда роль появилась, ссылка на закрытую задачу не висит, расположение
карточек и размеры групп владельца сохраняются, пересборка — только при смене входов, битый холст не затирается.

Запуск: python3.14 -I plugins/pantheon/tests/test_who_canvas.py  (код выхода 0 — все прошли)
"""
import atexit
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — pantheon.py только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="who-canvas-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("whocanvas", os.path.join(PLUGIN, "lib", "whocanvas.py"))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def byid(c):
    return {n["id"]: n for n in c["nodes"]}


def overlaps(c):
    """Пары карточек (не групп), которые налезают друг на друга."""
    cards = [n for n in c["nodes"] if n["type"] != "group"]
    bad = []
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            if not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"]):
                bad.append((a["id"], b["id"]))
    return bad


ALL = ["workshop", "charon", "hestia", "hq", "hephaestus", "hephaestus-site", "apollo", "palamedes", "argus", "talos",
       "dev-haiku", "dev-opus", "dev-sonnet", "codex-dev", "prometheus", "iris", "chiron", "momus", "tg-reader", "clio",
       "domain-coordinator"]
roles = {r: "" for r in ALL}
dirs = [{"name": "athena-brokerassistant", "short": "BrokerAssistant"}, {"name": "hermes-alex", "short": "alexbroker"},
        {"name": "themis-sources", "short": "законы"}, {"name": "calliope-content", "short": "посты"}]
st = {"metis-0760": "review", "metis-0765": "todo", "metis-0245": "done"}

# --- 1. холст с нуля ----------------------------------------------------------------------------------------------
c0 = W.build(None, roles, dirs, st)
n0 = byid(c0)
check("1. с нуля: группы, карточки ролей и координаторов есть, 🚧 нет",
      {"top", "coords", "team", "help", "sched", "zeus", "charon", "argus", "athena", "hermes", "themis", "calliope",
       "tick", "clio", "tg", "devs"} <= set(n0) and not any("🚧" in n.get("text", "") for n in c0["nodes"] if n["id"] != "legend"),
      sorted(n0))
check("1. с нуля: карточки не налезают друг на друга и лежат в своих группах",
      not overlaps(c0) and all(n0["argus"]["x"] >= n0["team"]["x"] and n0["argus"]["y"] >= n0["team"]["y"]
                               and n0["argus"]["y"] + n0["argus"]["height"] <= n0["team"]["y"] + n0["team"]["height"]
                               for _ in [0]), overlaps(c0))
check("1. с нуля: связи только между существующими узлами, группы первыми",
      c0["edges"] and all(e["fromNode"] in n0 and e["toNode"] in n0 for e in c0["edges"])
      and [n["type"] for n in c0["nodes"]][:5] == ["group"] * 5)
check("1. Codex в тексте «Разработчиков», пока есть роль codex-dev; без неё — нет",
      "Codex" in n0["devs"]["text"]
      and "Codex" not in byid(W.build(None, {r: "" for r in ALL if r != "codex-dev"}, dirs, st))["devs"]["text"])
js = W.render(c0)
check("1. render — как Obsidian: табы, без перевода строки в конце, читается обратно",
      js.startswith('{\n\t"nodes": [') and not js.endswith("\n") and json.loads(js) == c0)

# --- 2. роль удалена / появилась ----------------------------------------------------------------------------------
r_no_argus = {r: "" for r in ALL if r != "argus"}
c1 = W.build(c0, r_no_argus, dirs, st)
check("2. роль удалена → карточка уходит вместе со связью", "argus" not in byid(c1)
      and not any("argus" in (e["fromNode"], e["toNode"]) for e in c1["edges"]) and "talos" in byid(c1))
c2 = W.build(c1, roles, dirs, st)
check("2. роль вернулась → карточка снова есть", "argus" in byid(c2))

new_role = write(os.path.join(ROOT, "agents", "newbie.md"),
                 "---\nname: newbie\ndescription: Новичок Пантеона. Делает что-то полезное.\n---\ntext\n")
r_new = dict(roles, newbie=new_role)
c3 = W.build(c0, r_new, dirs, st)
nb = byid(c3).get("role-newbie")
check("2. новая роль без записи в каталоге → своя карточка в «Оракулах» с именем и описанием",
      nb is not None and "`newbie`" in nb["text"] and "Новичок Пантеона." in nb["text"] and "Делает" not in nb["text"], nb)
g = byid(c3)["help"]
check("2. карточка новой роли — в свободном месте группы, ничего не закрывает",
      g["x"] <= nb["x"] and nb["x"] + nb["width"] <= g["x"] + g["width"] and g["y"] <= nb["y"]
      and nb["y"] + nb["height"] <= g["y"] + g["height"] and not overlaps(c3), (nb, g, overlaps(c3)))
c4 = W.build(c3, roles, dirs, st)
check("2. роль newbie удалена → карточка уходит", "role-newbie" not in byid(c4))

# --- 3. 🚧 ---------------------------------------------------------------------------------------------------------
cat = W.CATALOG + [W._e("ghost", "help", "ghost", "**Призрак** · пробная\nЕщё не готов", planned="metis-9999")]
st2 = dict(st, **{"metis-9999": "doing"})
cg = W.build(c0, roles, dirs, st2, cat)
gh = byid(cg)["ghost"]
check("3. роли ещё нет, задача открыта → жёлтая карточка 🚧 со ссылкой на задачу",
      gh["text"].startswith("🚧 **Призрак**") and "[[metis-9999]]" in gh["text"] and gh["color"] == W.BUILD, gh)
pos = (gh["x"], gh["y"], gh["width"], gh["height"])
cg2 = W.build(cg, dict(roles, ghost=""), dirs, st2, cat)
gh2 = byid(cg2)["ghost"]
check("3. роль появилась → 🚧, жёлтый цвет и ссылка снимаются, место прежнее",
      "🚧" not in gh2["text"] and "metis-9999" not in gh2["text"] and "color" not in gh2
      and (gh2["x"], gh2["y"], gh2["width"], gh2["height"]) == pos, gh2)
cg3 = W.build(cg, roles, dirs, dict(st2, **{"metis-9999": "done"}), cat)
check("3. роли нет, задача закрыта → 🚧 остаётся, ссылки на закрытую задачу нет",
      "🚧" in byid(cg3)["ghost"]["text"] and "metis-9999" not in byid(cg3)["ghost"]["text"])
check("3. роли нет и задачи в каталоге нет → карточки нет", "ghost" not in byid(W.build(c0, roles, dirs, st2)))

# --- 4. ссылки на задачи ------------------------------------------------------------------------------------------
t = byid(c0)["charon"]["text"]
check("4. Харон: роль есть → без 🚧; открытые задачи (review, todo) — ссылки есть",
      "🚧" not in t and "[[metis-0760]]" in t and "[[metis-0765]]" in t, t)
t2 = byid(W.build(c0, roles, dirs, dict(st, **{"metis-0760": "done", "metis-0765": "dropped"})))["charon"]["text"]
check("4. задачи закрыты (done, dropped) → ссылок нет, текст карточки цел",
      "metis-07" not in t2 and "Харон" in t2 and "после вашего «да»." in t2, t2)
check("4. задачи нет на доске → ссылки нет", "metis-0765" not in byid(W.build(c0, roles, dirs, {}))["charon"]["text"])
check("4. Гестия: metis-0245 закрыта → ссылки нет", "metis-0245" not in byid(c0)["hestia"]["text"])

# --- 5. расположение сохраняется ---------------------------------------------------------------------------------
cur = copy.deepcopy(c0)
cn = byid(cur)
cn["athena"].update(x=777, y=1234, width=333, height=200)
cn["zeus"].update(x=-5, y=-6)
cn["coords"].update(width=1500)
cn["argus"]["text"] = "правка руками"
cur["nodes"].append({"id": "mine", "type": "text", "text": "заметка владельца", "x": 5, "y": 5, "width": 100, "height": 50})
c5 = W.build(cur, r_new, dirs, st)
n5 = byid(c5)
check("5. x, y, ширина и высота карточек и размер групп — с текущего холста",
      (n5["athena"]["x"], n5["athena"]["y"], n5["athena"]["width"], n5["athena"]["height"]) == (777, 1234, 333, 200)
      and (n5["zeus"]["x"], n5["zeus"]["y"]) == (-5, -6) and n5["coords"]["width"] == 1500)
check("5. текст пересобран кодом (ручная правка текста не живёт), чужая карточка владельца остаётся как есть",
      n5["argus"]["text"].startswith("**Аргус**") and n5["mine"] == cur["nodes"][-1])
check("5. повторная сборка без перемен не меняет холст (идемпотентность)", W.render(W.build(c5, r_new, dirs, st)) == W.render(c5))

# --- 6. направления -----------------------------------------------------------------------------------------------
c6 = W.build(c0, roles, dirs[:2], st)
check("6. направление убрано из реестра → его координатор уходит, остальные на месте",
      "themis" not in byid(c6) and "calliope" not in byid(c6) and "athena" in byid(c6))
dirs2 = dirs + [{"name": "janus-probe", "short": "пробное"}]
c7 = W.build(c0, roles, dirs2, st)
j = byid(c7)["janus"]
check("6. новое направление → карточка бога с подписью из реестра и ссылкой на STATUS; на месте других не стоит",
      "**Янус**" in j["text"] and "directions/janus-probe/STATUS|janus-probe" in j["text"] and not overlaps(c7), j)
ids = ["athena", "hermes", "themis", "calliope", "janus"]
many = dirs + [{"name": f"{g}-x", "short": ""} for g in ("mnemo", "proteus", "metis", "janus")]
full = W.build(c0, roles, many, st)  # группа координаторов заполнена
below = byid(full)["team"]["y"]
more = many + [{"name": "newgod-new", "short": "новое"}]
c8 = W.build(full, roles, more, st)
n8 = byid(c8)
gcoord = n8["coords"]
ng = n8["newgod"]
check("6. места в группе нет → группа растёт вниз, карточка внутри, ничего не налезает",
      ng["y"] + ng["height"] <= gcoord["y"] + gcoord["height"] and gcoord["height"] > byid(full)["coords"]["height"]
      and not overlaps(c8), (ng, gcoord, overlaps(c8)))
check("6. ниже лежавшая группа и её карточки сдвинуты на столько же, правая колонка не тронута",
      n8["team"]["y"] - below == gcoord["height"] - byid(full)["coords"]["height"]
      and n8["argus"]["y"] - byid(full)["argus"]["y"] == n8["team"]["y"] - below
      and n8["help"]["y"] == byid(full)["help"]["y"] and n8["prom"]["y"] == byid(full)["prom"]["y"])

# --- 7. sync: пересборка только при смене входов, битый холст цел -------------------------------------------------
canvas = os.path.join(ROOT, "pan", W.CANVAS_NAME)
sig = os.path.join(ROOT, "state", "who-canvas.json")
agent = write(os.path.join(ROOT, "ag", "x.md"), "---\nname: x\ndescription: Икс.\n---\n")
rl = {"x": agent, "argus": "", "hq": ""}
check("7. нет холста → создаётся", W.sync(canvas, sig, rl, dirs, st) == "written" and os.path.exists(canvas))
check("7. входы те же → 'unchanged', файл не трогали", W.sync(canvas, sig, rl, dirs, st) == "unchanged")
m1 = os.stat(canvas).st_mtime_ns
rl2 = dict(rl, iris="")
check("7. добавилась роль → пересборка, карточка в файле",
      W.sync(canvas, sig, rl2, dirs, st) == "written" and "iris" in byid(json.load(open(canvas, encoding="utf-8"))))
check("7. статус задачи сменился (закрыта) → пересборка, ссылка ушла",
      W.sync(canvas, sig, dict(rl2, charon=""), dirs, dict(st, **{"metis-0760": "done"})) == "written"
      and "metis-0760" not in open(canvas, encoding="utf-8").read())
write(agent, "---\nname: x\ndescription: Другое описание.\n---\n")
os.utime(agent, (1, 1))
check("7. описание роли без каталога изменилось → пересборка",
      W.sync(canvas, sig, rl2, dirs, st) == "written" and "Другое описание" in open(canvas, encoding="utf-8").read())
before = open(canvas, encoding="utf-8").read()
check("7. force пересобирает при тех же входах; текст тот же → 'same', файл не переписан",
      W.sync(canvas, sig, rl2, dirs, st, force=True) == "same" and open(canvas, encoding="utf-8").read() == before)
write(canvas, "{не json")
try:
    W.sync(canvas, sig, dict(rl2, new=""), dirs, st)
    raised = False
except ValueError:
    raised = True
check("7. холст не читается → ValueError, файл не затёрт", raised and open(canvas, encoding="utf-8").read() == "{не json")

# --- 8. тик и CLI pantheon.py на временных папках --------------------------------------------------------------
tmp = os.path.join(ROOT, "home")
home = os.path.join(tmp, "ai", "pantheon")
state = os.path.join(tmp, "state")
plug = os.path.join(tmp, "plug-roles")
for r in ("hq", "argus", "charon"):
    write(os.path.join(tmp, ".claude", "agents", r + ".md"), f"---\nname: {r}\ndescription: Роль {r}.\n---\n")
os.makedirs(plug, exist_ok=True)
write(os.path.join(home, "directions.toml"), '[[direction]]\nname = "athena-brokerassistant"\nshort = "Брокер"\n')
write(os.path.join(home, "Кто есть кто.md"), "памятка\n")
write(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0760.md"),
      "---\ntype: task\nid: metis-0760\ntitle: t\nstatus: review\nproject: P\ndirection: metis-pantheon\n"
      "created: 2026-11-01\nupdated: 2026-11-01T10:00:00\nschema_version: 1\n---\n\n# t\n")
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_PLUGIN_ROLES": plug}
probe = f"""
import sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
import inspect
print("tick-calls:", "who_canvas_tick()" in inspect.getsource(p.tick))
print("1:", p.who_canvas_tick())
print("2:", p.who_canvas_tick())
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
cv = os.path.join(home, W.CANVAS_NAME)
got = json.load(open(cv, encoding="utf-8")) if os.path.exists(cv) else {"nodes": []}
check("8. тик собирает холст из ~/.claude/agents, реестра и задач; второй раз ничего не делает; tick зовёт сборку",
      "tick-calls: True" in r.stdout and "1: written" in r.stdout and "2: unchanged" in r.stdout
      and {"zeus", "argus", "charon", "athena"} <= set(byid(got)) and "[[metis-0760]]" in byid(got)["charon"]["text"],
      r.stdout + r.stderr)
write(cv, "{нет")
write(os.path.join(tmp, ".claude", "agents", "iris.md"), "---\nname: iris\ndescription: Ирида.\n---\n")  # вход изменился
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
alerts = os.path.join(home, "alerts.md")
check("8. битый холст: тик не падает, файл не затёрт, тревога записана",
      r.returncode == 0 and open(cv, encoding="utf-8").read() == "{нет" and "1: error" in r.stdout and "2: error" in r.stdout
      and os.path.exists(alerts) and "Кто есть кто.canvas" in open(alerts, encoding="utf-8").read(), r.stdout + r.stderr)
os.remove(cv)
os.remove(os.path.join(home, "Кто есть кто.md"))
shutil.rmtree(state, True)
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
check("8. нет ни холста, ни памятки → ничего не создаём", not os.path.exists(cv) and "1: skip" in r.stdout,
      r.stdout + r.stderr)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
