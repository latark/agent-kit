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
write(os.path.join(home, "directions.toml"), '[[direction]]\nname = "athena-brokerassistant"\nshort = "Брокер"\n')
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
cur["nodes"].append({"id": "note", "type": "text", "text": "см. [[directions/themis-sources/STATUS|themis-sources]]",
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
print("script:", p.parse_command(sc) == [sc])
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

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
