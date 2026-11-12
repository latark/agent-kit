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
from _py311 import PY311, mkroot  # noqa: E402 — pantheon.py только на Python 3.11+

ROOT = os.path.realpath(mkroot("who-canvas-"))  # окно роли: metis-0941
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
dirs = [{"name": "athena-proja", "short": "ProjA"}, {"name": "hermes-siteb", "short": "site-b"},
        {"name": "themis-repos", "short": "законы"}, {"name": "calliope-media", "short": "посты"}]
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
check("7. описание роли без каталога изменилось (имена и статусы те же) → пересборка",
      W.sync(canvas, sig, dict(rl2, charon=""), dirs, dict(st, **{"metis-0760": "done"})) == "written" and "Другое описание" in open(canvas, encoding="utf-8").read())
before = open(canvas, encoding="utf-8").read()
check("7. force пересобирает при тех же входах; текст тот же → 'same', файл не переписан",
      W.sync(canvas, sig, dict(rl2, charon=""), dirs, dict(st, **{"metis-0760": "done"}), force=True) == "same" and open(canvas, encoding="utf-8").read() == before)
write(canvas, "[]")
try:
    W.sync(canvas, sig, dict(rl2, new=""), dirs, st)
    raised0 = False
except ValueError:
    raised0 = True
check("7. файл — JSON, но не холст → ValueError, файл не затёрт", raised0 and open(canvas, encoding="utf-8").read() == "[]")
write(canvas, "{не json")
try:
    W.sync(canvas, sig, dict(rl2, new=""), dirs, st)
    raised = False
except ValueError:
    raised = True
check("7. холст не читается → ValueError, файл не затёрт", raised and open(canvas, encoding="utf-8").read() == "{не json")

# --- 9. состав ролей для .md (metis-0828) ---
# --- 8. CLI pantheon.py на временных папках --------------------------------------------------------------
tmp = os.path.join(ROOT, "home")
home = os.path.join(tmp, "ai", "pantheon")
state = os.path.join(tmp, "state")
plug = os.path.join(tmp, "plug-roles")
for r in ("hq", "argus", "charon"):
    write(os.path.join(tmp, ".claude", "agents", r + ".md"), f"---\nname: {r}\ndescription: Роль {r}.\n---\n")
os.makedirs(plug, exist_ok=True)
write(os.path.join(home, "directions.toml"), '[[direction]]\nname = "athena-proja"\nshort = "Брокер"\n')
write(os.path.join(home, "Кто есть кто.md"), "памятка\n")
write(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0760.md"),
      "---\ntype: task\nid: metis-0760\ntitle: t\nstatus: review\nproject: P\ndirection: metis-pantheon\n"
      "created: 2026-11-01\nupdated: 2026-11-01T10:00:00\nschema_version: 1\n---\n\n# t\n")
write(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0001.md"),
      "---\ntype: task\nid: metis-0001\ntitle: t\nstatus: todo\nproject: P\ndirection: metis-pantheon\n"
      "created: 2026-11-01\nupdated: 2026-11-01T10:00:00\nschema_version: 1\n---\n\n# t\n")  # на неё холст не ссылается
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_PLUGIN_ROLES": plug}
cv_path = os.path.join(home, W.CANVAS_NAME)
probe = f"""
import sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
import inspect
print("statuses:", sorted(p.who_canvas_inputs()[2].items()))
print("1:", p.who_canvas_cmd([]))
import os as _o
_m = _o.stat({cv_path!r}).st_mtime_ns if _o.path.exists({cv_path!r}) else 0
print("2:", p.who_canvas_cmd([]))
print("same-mtime:", _m == (_o.stat({cv_path!r}).st_mtime_ns if _o.path.exists({cv_path!r}) else 0))
"""
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
cv = os.path.join(home, W.CANVAS_NAME)
got = json.load(open(cv, encoding="utf-8")) if os.path.exists(cv) else {"nodes": []}
check("8. pantheon who-canvas собирает холст из ~/.claude/agents, реестра и задач; второй раз файл не трогает",
      "1: 0" in r.stdout and "2: 0" in r.stdout
      and "statuses: [('metis-0760', 'review')]" in r.stdout
      and {"zeus", "argus", "charon", "athena"} <= set(byid(got)) and "[[metis-0760]]" in byid(got)["charon"]["text"],
      r.stdout + r.stderr)
write(cv, "{нет")
write(os.path.join(tmp, ".claude", "agents", "iris.md"), "---\nname: iris\ndescription: Ирида.\n---\n")  # вход изменился
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
alerts = os.path.join(home, "alerts.md")
check("8. битый холст: команда код 1, файл не затёрт, тревога записана",
      r.returncode == 0 and open(cv, encoding="utf-8").read() == "{нет" and "1: 1" in r.stdout and "2: 1" in r.stdout
      and os.path.exists(alerts) and "Кто есть кто.canvas" in open(alerts, encoding="utf-8").read(), r.stdout + r.stderr)
os.remove(cv)
os.remove(os.path.join(home, "Кто есть кто.md"))
shutil.rmtree(state, True)
r = subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
check("8. нет ни холста, ни памятки → ничего не создаём", not os.path.exists(cv) and "1: 0" in r.stdout,
      r.stdout + r.stderr)

cr = W.collect_roles(dict(roles, newbie=new_role), st2, cat)
crn = {x["name"]: x for x in cr}
check("9. collect_roles: все роли в списке, новая — kind auto с описанием, лиды и dev сведены в запись каталога",
      crn["newbie"]["kind"] == "auto" and crn["newbie"]["description"] == "Новичок Пантеона."
      and crn["heph"]["roles"] == ["hephaestus", "hephaestus-site"] and "codex-dev" not in crn
      and crn["devs"]["roles"] == ["dev-haiku", "dev-opus", "dev-sonnet"], crn.get("newbie"))
check("9. collect_roles: planned без роли — kind planned, present False, задача открыта; роль есть — present True, task None",
      crn["ghost"]["kind"] == "planned" and not crn["ghost"]["present"] and crn["ghost"]["task"] == "metis-9999"
      and crn["tick"]["present"] and crn["charon"]["task"] == "metis-0765")
cr2 = {x["name"]: x for x in W.collect_roles(dict(roles, ghost=""), st2, cat)}
check("9. collect_roles: роль появилась → ghost present, без задачи; закрытая задача Харона не возвращается",
      cr2["ghost"]["present"] and cr2["ghost"]["task"] is None
      and {x["name"]: x for x in W.collect_roles(roles, {"metis-0760": "done", "metis-0765": "done"})}["charon"]["task"] is None)
check("9. collect_roles: роли нет и planned нет → записи нет",
      "argus" not in {x["name"] for x in W.collect_roles({r: "" for r in ALL if r != "argus"}, st2, cat)}
      and "argus" in crn)
# --- 10. замечания argus (PR #314) ---
cur = copy.deepcopy(c0)
cur["nodes"].insert(0, {"id": "mygroup", "type": "group", "x": 3000, "y": 0, "width": 400, "height": 300, "label": "моя группа"})
cur["nodes"].append({"id": "inmine", "type": "text", "text": "в моей группе", "x": 3050, "y": 80, "width": 100, "height": 50})
cur["edges"].append({"id": "e-mine", "fromNode": "you", "fromSide": "right", "toNode": "mygroup", "toSide": "left"})
b = byid(W.build(cur, roles, dirs, st))
bc = W.build(cur, roles, dirs, st)
check("10. группа владельца (неизвестный id) остаётся с карточками и связью, группы идут первыми",
      "mygroup" in b and b["mygroup"]["label"] == "моя группа" and "inmine" in b
      and any(e["id"] == "e-mine" for e in bc["edges"])
      and [n["type"] for n in bc["nodes"]].index("text") > max(i for i, n in enumerate(bc["nodes"]) if n["type"] == "group"))
cur = copy.deepcopy(c0)
cur["nodes"].append({"id": "note", "type": "text", "text": "см. [[directions/themis-repos/STATUS|themis-repos]]",
                     "x": 1, "y": 1, "width": 10, "height": 10})
check("10. заметка владельца со ссылкой на STATUS остаётся, даже когда направления нет в реестре",
      "note" in byid(W.build(cur, roles, dirs[:1], st)) and "themis" not in byid(W.build(cur, roles, dirs[:1], st)))
canvas2 = os.path.join(ROOT, "pan2", W.CANVAS_NAME)
sig2 = os.path.join(ROOT, "state2", "who-canvas.json")
W.sync(canvas2, sig2, rl, dirs, st)
os.remove(canvas2)
check("10. холст удалён, отпечаток прежний → создаётся заново", W.sync(canvas2, sig2, rl, dirs, st) == "written"
      and os.path.exists(canvas2))
probe2 = f"""
import sys
sys.path.insert(0, {os.path.join(PLUGIN, "lib")!r})
import pantheon as p
sc = {os.path.join(PLUGIN, "scripts", "who-canvas.sh")!r}
import os
print("script:", p.parse_command(sc) == [os.path.realpath(sc)])
print("cmd:", p.parse_command("pantheon who-canvas"))
"""
r = subprocess.run([PY311, "-I", "-c", probe2], env=env, capture_output=True, text=True, timeout=60)
check("10. расписание: скрипт плагина проходит parse_command, `pantheon who-canvas` — нет (команды нет в TICK_SUBCOMMANDS)",
      "script: True" in r.stdout and "cmd: None" in r.stdout, r.stdout + r.stderr)
for sub in ("who-canvas.sh",):
    pass
write(os.path.join(home, W.CANVAS_NAME), "{нет")
r = subprocess.run([os.path.join(PLUGIN, "scripts", "who-canvas.sh"), "--bad"], env=dict(env), capture_output=True, text=True,
                   timeout=60)
check("10. скрипт передаёт аргументы команде: неверный аргумент → код 2 и справка", r.returncode == 2 and "использование" in r.stderr,
      (r.returncode, r.stdout, r.stderr))

# Д5: карточка направления с богом вне GODS_RU уходит вместе с направлением (id записан в прошлом отпечатке)
canvas5 = os.path.join(ROOT, "pan5", W.CANVAS_NAME)
sig5 = os.path.join(ROOT, "state5", "who-canvas.json")
dx = dirs + [{"name": "zzgod-new", "short": "x"}]
W.sync(canvas5, sig5, rl, dx, st)
had = "zzgod" in byid(json.load(open(canvas5, encoding="utf-8")))
W.sync(canvas5, sig5, rl, dirs, st)
now = byid(json.load(open(canvas5, encoding="utf-8")))
check("10. направление с неизвестным богом убрано → его карточка уходит (id из прошлого отпечатка), заметка владельца цела",
      had and "zzgod" not in now)
# --- 11. ручная правка текста, цвета и подписи группы не затирается ---
canvas3 = os.path.join(ROOT, "pan3", W.CANVAS_NAME)
sig3 = os.path.join(ROOT, "state3", "who-canvas.json")
W.sync(canvas3, sig3, rl, dirs, st)
data = json.load(open(canvas3, encoding="utf-8"))
dn = byid(data)
dn["zeus"]["text"] = "МОЙ ТЕКСТ"
dn["athena"]["color"] = "1"
dn["top"]["label"] = "МОЯ ПОДПИСЬ"
dn["argus"]["text"] = "ещё моё"
write(canvas3, json.dumps(data, ensure_ascii=False, indent="\t"))
man = []
rl3 = dict(rl, iris="")
check("11. вход изменился: правленные руками текст, цвет и подпись группы остаются, остальное пересобрано",
      W.sync(canvas3, sig3, rl3, dirs, st, manual_out=man) == "written", man)
d3 = byid(json.load(open(canvas3, encoding="utf-8")))
check("11. текст zeus, цвет athena, подпись top — как у владельца; id названы в manual_out; iris добавлен",
      d3["zeus"]["text"] == "МОЙ ТЕКСТ" and d3["athena"]["color"] == "1" and d3["top"]["label"] == "МОЯ ПОДПИСЬ"
      and sorted(man) == ["argus", "athena", "top", "zeus"] and "iris" in d3, (man, d3["top"]["label"]))
# повторно, без новых правок: manual всё ещё названы, цвет athena держится
man2 = []
W.sync(canvas3, sig3, dict(rl3, momus=""), dirs, st, manual_out=man2)
d3b = byid(json.load(open(canvas3, encoding="utf-8")))
check("11. правка живёт и через следующую пересборку", d3b["zeus"]["text"] == "МОЙ ТЕКСТ" and "momus" in d3b
      and sorted(man2) == ["argus", "athena", "top", "zeus"])
# удалённая карточка собирается заново и снова под автосборкой
data = json.load(open(canvas3, encoding="utf-8"))
data["nodes"] = [n for n in data["nodes"] if n["id"] != "zeus"]
write(canvas3, json.dumps(data, ensure_ascii=False, indent="\t"))
man3 = []
W.sync(canvas3, sig3, dict(rl3, momus="", talos2=""), dirs, st, manual_out=man3)
d3c = byid(json.load(open(canvas3, encoding="utf-8")))
check("11. удалённая карточка собирается заново кодом и больше не в manual",
      d3c["zeus"]["text"].startswith("## Зевс") and "zeus" not in man3, (d3c["zeus"]["text"], man3))
# первая сборка: записи хеша нет — код пишет поверх чужого текста
canvas4 = os.path.join(ROOT, "pan4", W.CANVAS_NAME)
data = json.load(open(canvas3, encoding="utf-8"))
byid(data)["zeus"]["text"] = "старый холст"
write(canvas4, json.dumps(data, ensure_ascii=False, indent="\t"))
man4 = []
W.sync(canvas4, os.path.join(ROOT, "state4", "who-canvas.json"), rl, dirs, st, manual_out=man4)
check("11. нет записи хеша (первая сборка) → текст пишет код, manual пуст",
      byid(json.load(open(canvas4, encoding="utf-8")))["zeus"]["text"].startswith("## Зевс") and man4 == [])
# команда: тревога один раз
cvp = os.path.join(home, W.CANVAS_NAME)
shutil.rmtree(state, True)
if os.path.exists(cvp):
    os.remove(cvp)
write(os.path.join(home, "Кто есть кто.md"), "памятка\n")
subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
cd = json.load(open(cvp, encoding="utf-8"))
byid(cd)["argus"]["text"] = "РУКАМИ"
write(cvp, json.dumps(cd, ensure_ascii=False, indent="\t"))
write(os.path.join(tmp, ".claude", "agents", "momus.md"), "---\nname: momus\ndescription: Мом.\n---\n")
for _ in range(2):
    subprocess.run([PY311, "-I", "-c", probe], env=env, capture_output=True, text=True, timeout=120)
    write(os.path.join(tmp, ".claude", "agents", "momus.md"), "---\nname: momus\ndescription: Мом %d.\n---\n" % _)
al = open(os.path.join(home, "alerts.md"), encoding="utf-8").read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
check("11. pantheon who-canvas: тревога «карточка argus правлена руками» — один раз, текст держится",
      al.count("карточка argus правлена руками, код её не обновляет") == 1
      and "удалите карточку" in al and byid(json.load(open(cvp, encoding="utf-8")))["argus"]["text"] == "РУКАМИ", al[-400:])

# --- 12. долги #314 (metis-0838) ----------------------------------------------------------------------------------
# Д8: отпечаток отстал от холста (холст записан, отпечаток нет) — карточка кода не «ручная»
canvas6 = os.path.join(ROOT, "pan6", W.CANVAS_NAME)
sig6 = os.path.join(ROOT, "state6", "who-canvas.json")
W.sync(canvas6, sig6, rl, dirs, st)
saved = json.load(open(sig6, encoding="utf-8"))
saved["hashes"]["zeus"] = "0" * 16  # прошлая запись — от другого текста; на холсте текст кода нынешний
saved["hashes"]["top"] = "1" * 16
write(sig6, json.dumps(saved))
man6, rep6 = [], {}
W.sync(canvas6, sig6, dict(rl, iris=""), dirs, st, manual_out=man6, report_out=rep6)
check("12. Д8: хеш в отпечатке отстал, а текст и цвет узла — как пишет код → узел не ручной, тревоги нет",
      "zeus" not in man6 and "top" not in man6 and "zeus" in rep6["auto"] and "top" in rep6["auto"]
      and json.load(open(sig6, encoding="utf-8"))["hashes"]["zeus"] != "0" * 16, (man6, rep6.get("auto")))
# Д8: процесс убит между отпечатком и холстом → холст со старым текстом не «ручной», пересборка не потеряна
canvas7 = os.path.join(ROOT, "pan7", W.CANVAS_NAME)
sig7 = os.path.join(ROOT, "state7", "who-canvas.json")
rl7 = dict(rl, charon="")
W.sync(canvas7, sig7, rl7, dirs, st)
st7 = dict(st, **{"metis-0760": "done"})  # текст Харона меняется
real_replace = W.os.replace


def boom(src, dst):
    if dst == canvas7:
        raise OSError("убит")
    return real_replace(src, dst)


W.os.replace = boom
try:
    W.sync(canvas7, sig7, rl7, dirs, st7)
    crashed = False
except OSError:
    crashed = True
finally:
    W.os.replace = real_replace
mid = json.load(open(sig7, encoding="utf-8"))
man7 = []
got7 = W.sync(canvas7, sig7, rl7, dirs, st7, manual_out=man7)
check("12. Д8: сбой записи холста после отпечатка → прежний sig, в записи старый и новый хеш; следующий проход "
      "пересобирает, Харон не ручной",
      crashed and isinstance(mid["hashes"].get("charon"), list) and got7 == "written" and "charon" not in man7
      and "metis-0760" not in byid(json.load(open(canvas7, encoding="utf-8")))["charon"]["text"]
      and isinstance(json.load(open(sig7, encoding="utf-8"))["hashes"]["charon"], str), (crashed, mid["hashes"].get("charon"), got7, man7))
# Д8: замок — второй запуск ждёт первого
import fcntl  # noqa: E402
import threading  # noqa: E402
lk = open(sig7 + ".lock", "a")
fcntl.flock(lk, fcntl.LOCK_EX)
done = []
th = threading.Thread(target=lambda: done.append(W.sync(canvas7, sig7, rl7, dirs, st, force=True)))
th.start()
th.join(0.5)
waited = not done
fcntl.flock(lk, fcntl.LOCK_UN)
lk.close()
th.join(10)
check("12. Д8: sync берёт замок — пока он занят, сборка ждёт; отпущен — доходит", waited and done == ["written"], (waited, done))

# Д9 и clear_once("who-canvas"): команда целиком
probe_f = probe.replace("p.who_canvas_cmd([])", "p.who_canvas_cmd(['--force'])") + f"""
print("mark-canvas:", _o.path.exists(p.once_path("who-canvas")))
print("mark-argus:", _o.path.exists(p.once_path("who-canvas-manual-argus")))
"""


def run_f():
    return subprocess.run([PY311, "-I", "-c", probe_f], env=env, capture_output=True, text=True, timeout=120)


def edit_argus(text):
    d = json.load(open(cvp, encoding="utf-8"))
    byid(d)["argus"]["text"] = text
    write(cvp, json.dumps(d, ensure_ascii=False, indent="\t"))


def alerts_argus():
    a = open(os.path.join(home, "alerts.md"), encoding="utf-8").read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    return a.count("карточка argus правлена руками")


edit_argus("ДРУГОЕ РУКАМИ")
r = run_f()
check("12. Д9: новая ручная правка той же карточки → новая тревога (значение — хеш текста)",
      alerts_argus() == 2 and "mark-argus: True" in r.stdout, (alerts_argus(), r.stdout + r.stderr))
d = json.load(open(cvp, encoding="utf-8"))
d["nodes"] = [n for n in d["nodes"] if n["id"] != "argus"]
write(cvp, json.dumps(d, ensure_ascii=False, indent="\t"))
r = run_f()
check("12. Д9: карточка удалена и собрана кодом → метка ручной правки снята", "mark-argus: False" in r.stdout,
      r.stdout + r.stderr)
edit_argus("РУКАМИ")
run_f()
check("12. Д9: после возврата под код та же правка, что раньше, снова даёт тревогу", alerts_argus() == 3, alerts_argus())
write(cvp, "{нет")
r = run_f()
had_mark = "mark-canvas: True" in r.stdout
os.remove(cvp)
r = run_f()
check("12. clear_once: холст не читался (тревога, метка) → удачная сборка снимает метку «who-canvas»",
      had_mark and "1: 0" in r.stdout and "mark-canvas: False" in r.stdout, r.stdout + r.stderr)

# --- 13. таблица ролей в «Кто есть кто.md» и реестр в system.md (metis-0828) ----------------------------------------
B, E = W.BEGIN_FULL.format(name="roles"), W.END.format(name="roles")
mt = W.memo_table(dict(roles, newbie=new_role), dirs, st2, cat)
rows = {ln.split(" | ")[0][2:]: ln for ln in mt.splitlines()[2:]}
check("13. таблица: строка на каждую запись каталога, авто-роль, координатор; лиды — `<имя>-<проект>`, dev — все",
      "**Аргус**, ревьюер" in rows and "**Newbie**" in rows and "Новичок Пантеона." in rows["**Newbie**"]
      and "`athena-proja` · [[directions/athena-proja/STATUS\\|STATUS]]" in rows["**Афина**"]
      and "`hephaestus-<проект>`" in rows["**Гефест**, лид кода"] and "`zeus`" in rows["**Зевс**, Пританей"]
      and all(f"`{r}`" in rows["**Разработчики**"] for r in ("dev-haiku", "dev-opus", "dev-sonnet", "codex-dev")),
      mt)
check("13. таблица: роли нет, задача открыта → «🚧 роли ещё нет» со ссылкой; роль появилась → «есть»",
      "🚧 роли ещё нет · [[metis-9999]]" in rows["**Призрак**, пробная"]
      and "| есть |" in {ln.split(" | ")[0][2:]: ln for ln in W.memo_table(dict(roles, ghost=""), dirs, st2, cat)
                         .splitlines()[2:]}["**Призрак**, пробная"])
check("13. таблица: роль удалена → строки нет; направление убрано → строки координатора нет",
      "**Аргус**, ревьюер" not in W.memo_table(r_no_argus, dirs, st) and "**Фемида**" not in W.memo_table(roles, dirs[:2], st)
      and "**Фемида**" in mt)
check("13. таблица: порядок групп — Пританей, Полисы, Артель, Оракулы, Оры",
      [ln.split(" | ")[3] for ln in mt.splitlines()[2:]] == sorted(
          [ln.split(" | ")[3] for ln in mt.splitlines()[2:]],
          key=["Пританей", "Полисы", "Артель", "Оракулы", "Оры"].index))
doc = "# Памятка\n\nручное до\n\n" + B + "\nстарая таблица\n" + E + "\n\nручное после\n"
new_doc = W.splice(doc, "roles", "| новая |", W.MEMO_HEADING)
check("13. splice: между маркерами — новое, текст до и после маркеров цел",
      new_doc == "# Памятка\n\nручное до\n\n" + B + "\n| новая |\n" + E + "\n\nручное после\n", new_doc)
app = W.splice("# Памятка\nручное\n", "roles", "| т |", W.MEMO_HEADING)
check("13. splice: маркеров нет → блок в конце под заголовком, ручной текст цел; повтор ничего не меняет",
      app == "# Памятка\nручное\n\n" + W.MEMO_HEADING + "\n\n" + B + "\n| т |\n" + E + "\n"
      and W.splice(app, "roles", "| т |", W.MEMO_HEADING) == app, app)
bad_doc = os.path.join(ROOT, "docs", "bad.md")
write(bad_doc, "до\n" + B + "\nбез конца\n")
try:
    W.sync_doc(bad_doc, "roles", "| т |", W.MEMO_HEADING)
    raised_b = False
except ValueError:
    raised_b = True
bad2 = "x\n" + E + "\n" + B + "\n"
try:
    W.splice(bad2, "roles", "т", "h")
    raised_c = False
except ValueError:
    raised_c = True
check("13. маркер без пары или конец раньше начала → ValueError, файл не тронут",
      raised_b and raised_c and open(bad_doc, encoding="utf-8").read() == "до\n" + B + "\nбез конца\n")
check("13. sync_doc: файла нет → 'skip', файл не создан",
      W.sync_doc(os.path.join(ROOT, "docs", "none.md"), "roles", "т", "h") == "skip"
      and not os.path.exists(os.path.join(ROOT, "docs", "none.md")))
stt = W.system_table({"hq": "", "argus": "/x/roles/argus.tmpl", "hephaestus-site": "/a/agents/hephaestus-site.md",
                      "domain-coordinator": "", "newbie": new_role}, st)
srow = {ln.split(" | ")[0][2:]: ln for ln in stt.splitlines()[2:]}
check("13. system_table: строка на каждую роль по имени файла, кто она и источник",
      set(srow) == {"`hq`", "`argus`", "`hephaestus-site`", "`domain-coordinator`", "`newbie`"}
      and "**Зевс**, Пританей" in srow["`hq`"] and "шаблон плагина `roles/argus.tmpl`" in srow["`argus`"]
      and "`~/.claude/agents/hephaestus-site.md`" in srow["`hephaestus-site`"] and "**Гефест**" in srow["`hephaestus-site`"]
      and "Новичок Пантеона." in srow["`newbie`"] and "координатор направления" in srow["`domain-coordinator`"], stt)
# команда целиком: памятка и system.md получают блок, сверка памятки (who_is_who_check) — без расхождений
memo_p = os.path.join(home, "Кто есть кто.md")
sys_p = os.path.join(home, "system.md")
write(memo_p, "# Памятка\n\nручной текст владельца\n")
write(sys_p, "# Реестр\n\n| ручная таблица |\n\n" + B + "\nстарое\n" + E + "\n\nхвост\n")
probe_d = probe_f + """
print("check:", p.who_is_who_check())
"""
r = subprocess.run([PY311, "-I", "-c", probe_d], env=env, capture_output=True, text=True, timeout=120)
mtext, stext = open(memo_p, encoding="utf-8").read(), open(sys_p, encoding="utf-8").read()
check("13. pantheon who-canvas: блок ролей в памятке и в system.md, ручной текст цел, сверка памятки чистая",
      "ручной текст владельца" in mtext and W.MEMO_HEADING in mtext and "`charon`" in mtext and "`athena-proja`" in mtext
      and stext.startswith("# Реестр\n\n| ручная таблица |\n\n") and stext.endswith("\n\nхвост\n") and "старое" not in stext
      and "`argus`" in stext and "check: ([], [])" in r.stdout and "1: 0" in r.stdout, r.stdout + r.stderr + mtext[-600:])
m_before = os.stat(memo_p).st_mtime_ns
os.utime(memo_p, ns=(1, 1))
r = subprocess.run([PY311, "-I", "-c", probe_d], env=env, capture_output=True, text=True, timeout=120)
check("13. повторный проход без перемен файл памятки не переписывает", os.stat(memo_p).st_mtime_ns == 1 and m_before != 1,
      r.stdout + r.stderr)
write(sys_p, "x\n" + B + "\n")
r = subprocess.run([PY311, "-I", "-c", probe_d], env=env, capture_output=True, text=True, timeout=120)
al = open(os.path.join(home, "alerts.md"), encoding="utf-8").read()
check("13. маркер без пары в system.md → код 1, тревога, файл не тронут",
      "1: 1" in r.stdout and "таблица ролей не собрана" in al and open(sys_p, encoding="utf-8").read() == "x\n" + B + "\n",
      r.stdout + r.stderr)

# --- 14. долги #383 (metis-0992): маркеры в середине строки, двойные, сбой одного файла, ссылка, замок --------------
mid = "вот " + B + " середина " + E + " дальше\nручное\n"
got_mid = W.splice(mid, "roles", "| т |", W.MEMO_HEADING)
check("14. splice: маркеры в середине строки — обычный текст: ничего не теряется, блок добавлен в конец",
      got_mid.startswith(mid.rstrip("\n")) and " середина " in got_mid and got_mid.endswith(B + "\n| т |\n" + E + "\n")
      and W.splice(got_mid, "roles", "| т |", W.MEMO_HEADING) == got_mid, got_mid)
mid2 = "вот " + E + " конец в строке\n" + B + "\nстарое\n" + E + "\nхвост\n"
check("14. splice: конец в середине строки до настоящего блока не обрезает его и не теряет текст",
      W.splice(mid2, "roles", "| н |", "h") == "вот " + E + " конец в строке\n" + B + "\n| н |\n" + E + "\nхвост\n")
for nm, dbl in (("два начала", B + "\na\n" + B + "\nb\n" + E + "\n"), ("два блока", B + "\na\n" + E + "\n" + B + "\nb\n" + E + "\n"),
                ("два конца", B + "\na\n" + E + "\n" + E + "\n")):
    try:
        W.splice(dbl, "roles", "т", "h")
        rz = False
    except ValueError:
        rz = True
    check(f"14. splice: {nm} → ValueError", rz)
d14 = os.path.join(ROOT, "docs14")
real14 = write(os.path.join(d14, "real.md"), "до\n" + B + "\nстарое\n" + E + "\n")
link14 = os.path.join(d14, "link.md")
os.symlink(real14, link14)
fixed_tmp = write(real14 + ".tmp", "чужой файл")
res14 = W.sync_doc(link14, "roles", "| н |", "h")
check("14. sync_doc: ссылка остаётся ссылкой, запись в её цель; чужой path.tmp цел; временных файлов не осталось",
      res14 == "written" and os.path.islink(link14) and "| н |" in open(real14, encoding="utf-8").read()
      and open(fixed_tmp, encoding="utf-8").read() == "чужой файл"
      and sorted(os.listdir(d14)) == ["link.md", "real.md", "real.md.lock", "real.md.tmp"], sorted(os.listdir(d14)))
d15 = os.path.join(ROOT, "docs15")
write(os.path.join(d15, W.MEMO_NAME), "x\n" + B + "\nнет конца\n")
write(os.path.join(d15, W.SYSTEM_NAME), "# Реестр\n")
got15 = W.sync_docs(d15, roles, dirs, st2, cat)
check("14. sync_docs: маркеры первого файла не парные → у него «ошибка», второй файл всё равно обновлён",
      got15[W.MEMO_NAME].startswith("ошибка") and got15[W.SYSTEM_NAME] == "written"
      and "`argus`" in open(os.path.join(d15, W.SYSTEM_NAME), encoding="utf-8").read(), got15)
canvas16, sig16 = os.path.join(ROOT, "c16", "k.canvas"), os.path.join(ROOT, "c16", "state", "sig.json")
W.sync(canvas16, sig16, rl, dirs, st)
c16 = json.load(open(canvas16, encoding="utf-8"))
gone = next(n["id"] for n in c16["nodes"] if n["type"] != "group")
c16["nodes"] = [n for n in c16["nodes"] if n["id"] != gone]
write(canvas16, json.dumps(c16, ensure_ascii=False))
check("14. удалённая карточка, входы те же → холст собирается заново (без --force)",
      W.sync(canvas16, sig16, rl, dirs, st) == "written" and gone in byid(json.load(open(canvas16, encoding="utf-8")))
      and W.sync(canvas16, sig16, rl, dirs, st) == "unchanged")

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
