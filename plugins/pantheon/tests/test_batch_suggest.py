#!/usr/bin/env python3
"""Раскладка открытых задач по пачкам без модели (metis-0595): `pantheon task batch-suggest` и плановая сводка
`pantheon batch-suggest run`. Временные папки, настоящих задач и ~/ai/pantheon тест не трогает.

Запуск: python3 -I plugins/pantheon/tests/test_batch_suggest.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="batchsug-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402
import batchsuggest as B  # noqa: E402

T0 = 1_793_000_000
DAY = 86400
DIR = "metis-pantheon"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


DIRS = '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n\n[[direction]]\nname = "demo"\nproject = "Демо"\n'

# тексты: у каждой темы свой словарь, чтобы похожесть не смешивала темы
GATE_TXT = "Шлюз слияния ядра: перенос записи принять на PR после squash, gate() читает решение владельца по head"
OUTBOX = "Рассылка уведомлений outbox: очередь сообщений, повтор отправки при сбое сети, outbox_sender пишет журнал доставки"
HESTIA = "Гестия после выпуска перезапускает окна ролей: очередь перезапуска, проверка занятости окна, пауза между окнами"
PHOTO = "Отпуск на море: билеты, отель у пляжа, экскурсии по старому городу, фотографии заката"


def put(home, tid, title, text, direction=DIR, status="todo", touches=None, typ="task", parent=None, mode="single"):
    lines = ["---", f"type: {typ}", f"id: {tid}", f'title: "{title}"', f"status: {status}",
             f"project: {'Пантеон' if direction == DIR else 'Демо'}", f"direction: {direction}", f"owner: {direction}",
             "created: 2026-11-01", "updated: 2026-11-01T10:00:00", "schema_version: 1"]
    if touches:
        lines.append(f"touches: [{', '.join(touches)}]")
    if parent:
        lines.append(f"parent: {parent}")
    if mode and typ == "task":
        lines += [f"mode: {mode}", "mode_why: тест"]
    lines += ["---", "", f"# {title}", "", text, "", "## Журнал", "", "- 2026-11-01 10:00 — агент: создана", ""]
    open(os.path.join(home, "directions", direction, "tasks", tid + ".md"), "w", encoding="utf-8").write("\n".join(lines))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="batchsug-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "directions/demo/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    for d in (state, os.path.join(view, "Доска"), os.path.join(tmp, ".claude", "pantheon")):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmp, "PANTHEON_METRICS": "0"}
    return tmp, home, state, view, env


def fill(home):
    # существующая пачка с двумя задачами
    put(home, "metis-9001", "Пачка: шлюз слияния", "Шлюз слияния и перенос записей.", typ="story", status="doing", mode=None)
    put(home, "metis-9002", "Шлюз слияния: вернуть на другом head", GATE_TXT, touches=["plugins/pantheon/lib/merge.py"],
        parent="metis-9001")
    put(home, "metis-9003", "Шлюз слияния: отпечаток переноса", GATE_TXT + " отпечаток от вершины main",
        touches=["plugins/pantheon/lib/merge.py"], parent="metis-9001")
    # без пачки: в существующую (общий файл + текст)
    put(home, "metis-9010", "merge.py: gate() теряет принять после squash",
        "gate() в merge.py теряет запись принять после squash слияния, шлюз не переносит решение на PR сверху.",
        touches=["plugins/pantheon/lib/merge.py"])
    # то же, но режим не решён: attach откажет
    put(home, "metis-9011", "merge.py: ещё одно замечание про gate()",
        "gate() в merge.py: шлюз слияния, перенос записи принять на PR после squash по head владельца.",
        touches=["plugins/pantheon/lib/merge.py"], mode="undecided")
    # только текст: копия состава пачки без общих файлов — предложение не «уверенно»
    put(home, "metis-9012", "Шлюз слияния ядра: перенос записи", GATE_TXT + " отпечаток от вершины main")
    # новая пачка: три задачи с общим файлом и символом
    for i, (t, x) in enumerate((("outbox: повтор отправки", "Повтор отправки: пауза растёт вдвое, потолок десять минут."),
                                ("outbox: журнал доставки", "Журнал доставки: ротация по размеру, сжатие старых файлов."),
                                ("outbox: очередь сообщений", "Очередь сообщений: порядок по важности, лимит длины."))):
        put(home, f"metis-902{i}", t, "outbox_sender: " + x, touches=["plugins/pantheon/lib/outbox_sender.py"])
    # дубли
    put(home, "metis-9030", "Гестия: перезапуск окон после выпуска", HESTIA)
    put(home, "metis-9031", "Гестия: перезапуск окон после выпуска 0.11", HESTIA + " версия")
    # ссылка друг на друга, темы разные
    put(home, "metis-9040", "Очистить кэш превью", "Кэш превью растёт без ротации; связано с metis-9041, чистить вместе.")
    put(home, "metis-9041", "Ротация логов браузера", "Логи браузера не ротируются, размер растёт; см. также кэш превью.")
    # одиночка
    put(home, "metis-9050", "Планы на отпуск", PHOTO)
    # не берутся: закрытая, чужое направление с теми же файлами
    put(home, "metis-9060", "Закрытая про outbox", OUTBOX, status="done", touches=["plugins/pantheon/lib/outbox_sender.py"])
    put(home, "demo-9070", "Чужое про outbox", OUTBOX, direction="demo", touches=["plugins/pantheon/lib/outbox_sender.py"])


def pan(env, *a, now=T0):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=dict(env, PANTHEON_NOW=str(now)), capture_output=True, text=True,
                          timeout=120)


def task_text(home, tid, d=DIR):
    return open(os.path.join(home, "directions", d, "tasks", tid + ".md"), encoding="utf-8").read()


def pure(home):
    tasks = T.load_tasks(home, T.WORK_TYPES)
    res = B.suggest(tasks, DIR)
    groups = [sorted(t["id"] for t in g["tasks"]) for g in res["groups"]]
    check("группа: три задачи с общим файлом outbox_sender.py вместе", ["metis-9020", "metis-9021", "metis-9022"] in groups, groups)
    check("группа: закрытая и чужого направления в неё не попали",
          not any(x in ("metis-9060", "demo-9070") for g in groups for x in g), groups)
    check("группа: ссылка друг на друга собирает пару 9040+9041", ["metis-9040", "metis-9041"] in groups, groups)
    g_out = next((g for g in res["groups"] if g["tasks"][0]["id"] == "metis-9020"), {"reasons": [], "name": ""})
    check("группа: причина называет общий файл, название начинается с «Пачка: »",
          any("outbox_sender.py" in r for r in g_out["reasons"]) and g_out["name"].startswith("Пачка: "), g_out)
    dup = [(d["a"], d["b"]) for d in res["duplicates"]]
    check("дубли: 9030 и 9031 — «объединить?»", ("metis-9030", "metis-9031") in dup, dup)
    check("дубли: задачи разных тем (9050, 9040, 902x) дублями не названы",
          not any(set(p) & {"metis-9050", "metis-9040", "metis-9041", "metis-9020", "metis-9021", "metis-9022"} for p in dup), dup)
    joins = {j["task"]: j for j in res["joins"]}
    check("в пачку: 9010 → 9001 уверенно (общий merge.py)",
          joins.get("metis-9010", {}).get("story") == "metis-9001" and joins["metis-9010"]["confidence"] == "high",
          joins.get("metis-9010"))
    check("в пачку: только по тексту, без общего файла (9012) — не «уверенно»",
          joins.get("metis-9012", {}).get("confidence") != "high", joins.get("metis-9012"))
    check("в пачку: «уверенно» только с признаком не из текста (файл, имя, ссылка, PR)",
          all(j["confidence"] != "high" or any(x.startswith(("файлы", "имена", "ссылка", "PR")) for x in j["reasons"])
              for j in res["joins"]))
    check("одиночка 9050 не в группах и не в пачке",
          all("metis-9050" not in g for g in groups) and "metis-9050" not in joins
          and "metis-9050" in [s["id"] for s in res["singles"]], res["singles"])
    check("задачи, уже лежащие в пачке (9002, 9003), и сама пачка не предлагаются заново",
          all(x not in joins for x in ("metis-9002", "metis-9003", "metis-9001"))
          and all("metis-9002" not in g for g in groups))
    demo = B.suggest(tasks, "demo")
    check("чужое направление считается отдельно: demo не видит metis-pantheon", demo["groups"] == [] and demo["open_loose"] == 1)
    check("стемминг: окончания русских слов отсекаются", B.stem("перезапуска") == B.stem("перезапуск")
          and B.stem("окнами") == B.stem("окна"), (B.stem("окнами"), B.stem("окна")))
    # мутант: без общего файла у пары признак «files» пропадает (файл — реальный признак, а не шум)
    h = dict(tasks["metis-9020"][1])
    h.pop("touches")
    f1 = B.features("metis-9020", h, tasks["metis-9020"][2].replace("outbox_sender", "sender"))
    f2 = B.features("metis-9021", tasks["metis-9021"][1], tasks["metis-9021"][2])
    f3 = B.features("metis-9022", tasks["metis-9022"][1], tasks["metis-9022"][2])
    pair_with = B.Scorer({"metis-9021": f2, "metis-9022": f3}).pair("metis-9021", "metis-9022")
    pair_without = B.Scorer({"metis-9020": f1, "metis-9021": f2}).pair("metis-9020", "metis-9021")
    check("пара с общим файлом оценивается выше пары без него; files пусто без touches",
          pair_with[1]["files"] == ["outbox_sender.py"] and pair_without[1]["files"] == []
          and pair_with[0] > pair_without[0], (pair_with, pair_without))


def common_file():
    feats = {}
    for i in range(9):
        h = {"title": f"Задача номер {i} про тему{i}", "touches": ["lib/everywhere.py"], "direction": DIR}
        feats[f"metis-95{i:02d}"] = B.features(f"metis-95{i:02d}", h, f"Текст{i}.")
    sc = B.Scorer(feats)
    check("файл, который есть у многих задач, не признак пачки", sc.pair("metis-9500", "metis-9501")[1]["files"] == [])


def cli(home, env):
    r = pan(env, "task", "batch-suggest", "--direction", DIR)
    check("task batch-suggest: код 0, три раздела в тексте",
          r.returncode == 0 and "Объединить?" in r.stdout and "Положить в существующую пачку" in r.stdout
          and "Новые пачки" in r.stdout, r.stdout[-300:] + r.stderr[-200:])
    check("task batch-suggest: без --apply ничего не записано",
          "parent:" not in task_text(home, "metis-9010") and "parent:" not in task_text(home, "metis-9020"))
    j = pan(env, "task", "batch-suggest", "--direction", DIR, "--json")
    try:
        data = json.loads(j.stdout)
    except ValueError:
        data = {}
    r0 = (data.get("results") or [{}])[0]
    check("--json: разбирается, есть joins/groups/duplicates, applied пуст",
          j.returncode == 0 and r0.get("direction") == DIR and r0.get("groups") and r0.get("duplicates")
          and r0.get("joins") and data.get("applied") == [], j.stdout[:200])
    allj = pan(env, "task", "batch-suggest", "--json")
    dd = [x["direction"] for x in json.loads(allj.stdout)["results"]] if allj.returncode == 0 else []
    check("без --direction: считаются все направления", dd == ["demo", DIR], dd)
    bad = pan(env, "task", "batch-suggest", "--bogus")
    check("неизвестный флаг → код 2 и имя флага последней строкой",
          bad.returncode == 2 and "--bogus" in bad.stderr.strip().splitlines()[-1], bad.stderr)
    bad2 = pan(env, "task", "batch-suggest", "--direction")
    check("--direction без значения → код 2", bad2.returncode == 2, bad2.stderr)
    a = pan(env, "task", "batch-suggest", "--direction", DIR, "--apply")
    check("--apply: уверенная 9010 прикреплена к 9001",
          a.returncode == 0 and "parent: metis-9001" in task_text(home, "metis-9010"), a.stdout[-300:] + a.stderr[-200:])
    check("--apply: группа новой пачки не тронута (parent не пишет)",
          all("parent:" not in task_text(home, f"metis-902{i}") for i in range(3)))
    check("--apply: только по тексту (9012) не прикреплена", "parent:" not in task_text(home, "metis-9012"))
    check("--apply: журнал пачки получил строку о прикреплении", "metis-9010" in task_text(home, "metis-9001"))
    a2 = pan(env, "task", "batch-suggest", "--direction", DIR, "--apply", "--json")
    d2 = json.loads(a2.stdout) if a2.returncode == 0 else {}
    check("--apply повторно: 9010 уже в пачке — не предлагается, ошибок нет",
          a2.returncode == 0 and not any(x.startswith("metis-9010") for x in d2.get("applied", []) + d2.get("skipped", [])),
          a2.stdout[:200] + a2.stderr[-200:])


def apply_skips(home):
    tasks = T.load_tasks(home, T.WORK_TYPES)
    res = {"joins": [{"task": "metis-9011", "story": "metis-9001", "confidence": "high"},
                     {"task": "metis-9012", "story": "metis-9001", "confidence": "normal"}]}
    calls = []

    def attach(t, s):
        calls.append((t, s))
        if t == "metis-9011":
            raise ValueError("нет mode")
    done, skipped = B.apply(res, tasks, attach)
    check("apply: normal не вызывает attach; отказ attach — в пропущенных, не падение",
          calls == [("metis-9011", "metis-9001")] and done == [] and len(skipped) == 1 and "нет mode" in skipped[0],
          (calls, skipped))


def tick(home, state, view, env):
    r = pan(env, "batch-suggest", "run")
    board = os.path.join(view, "Доска", "Пачки-предложения.md")
    check("run: код 0, файл на доске и копия в STATE, одна строка тревоги о новом",
          r.returncode == 0 and os.path.exists(board) and os.path.exists(os.path.join(state, "batch-suggest.md"))
          and r.stdout.count("[alert]") == 1 and "Доска/Пачки-предложения.md" in r.stdout, r.stdout[-300:] + r.stderr[-200:])
    txt = open(board, encoding="utf-8").read() if os.path.exists(board) else ""
    check("run: файл называет новые пачки и дубли", "Новые пачки" in txt and "Объединить?" in txt)
    r2 = pan(env, "batch-suggest", "run", now=T0 + 2 * DAY)
    check("частота: через 2 суток пропуск, тревоги нет", r2.returncode == 0 and "следующий не раньше" in r2.stdout
          and "[alert]" not in r2.stdout, r2.stdout)
    r3 = pan(env, "batch-suggest", "run", now=T0 + 3 * DAY + 3600)
    check("частота: через 3 суток и час проход идёт; нового нет — без тревоги",
          r3.returncode == 0 and "новых 0" in r3.stdout and "[alert]" not in r3.stdout, r3.stdout)
    put(home, "metis-9080", "Заметки про рассылку: повтор outbox", OUTBOX + " ещё",
        touches=["plugins/pantheon/lib/outbox_sender.py"])
    r4 = pan(env, "batch-suggest", "run", now=T0 + 3 * DAY + 7200)
    check("внутри окна без --force — пропуск", "следующий не раньше" in r4.stdout and "[alert]" not in r4.stdout, r4.stdout)
    r5 = pan(env, "batch-suggest", "run", "--force", now=T0 + 3 * DAY + 7200)
    check("--force внутри окна: проход идёт, новая задача в составе группы — тревога о новом",
          r5.returncode == 0 and r5.stdout.count("[alert]") == 1, r5.stdout)
    bad = pan(env, "batch-suggest", "run", "--zzz")
    check("run с лишним флагом → код 2", bad.returncode == 2 and "использование" in bad.stderr, bad.stderr)
    code = (f"import sys; sys.path.insert(0, {LIB!r}); import pantheon as P; "
            "print(P.parse_command('pantheon batch-suggest run') is not None, "
            "P.parse_command('pantheon batch-suggest run --force') is None, P.parse_command('pantheon batch-suggest') is None)")
    pc = subprocess.run([PY311, "-I", "-c", code], env=dict(env), capture_output=True, text=True, timeout=60)
    check("тик пускает только `pantheon batch-suggest run`", pc.stdout.strip() == "True True True", pc.stdout + pc.stderr[-200:])


def main():
    tmp, home, state, view, env = make()
    fill(home)
    pure(home)
    apply_skips(home)
    common_file()
    cli(home, env)
    tmp2, home2, state2, view2, env2 = make()
    fill(home2)
    tick(home2, state2, view2, env2)
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
