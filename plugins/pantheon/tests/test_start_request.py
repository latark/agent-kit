#!/usr/bin/env python3
"""metis-0771: `pantheon start <направление>` без других слов в окне Пританея (PANTHEON_ROLE=hq) — заявка в
STATE/hq-rw/start-req, а не запуск; плановый проход (take_start_requests) превращает её в разовый запуск. Имя — только
из реестра (domains.json), не направление с coordinator = false; подложенный файл заявки — тревога без запуска.
Строки 15–18 модели угроз (drafts/0771-threat-model.md).

Запуск: python3 -I plugins/pantheon/tests/test_start_request.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="startreq-"))
tempfile.tempdir = _ROOT
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
os.environ.update({"HOME": os.path.join(_ROOT, "home"), "PANTHEON_HOME": os.path.join(_ROOT, "home", "ai", "pantheon"),
                   "PANTHEON_STATE": os.path.join(_ROOT, "state"), "PANTHEON_NO_NOTIFY": "1", "TMPDIR": _ROOT})
os.makedirs(os.environ["PANTHEON_HOME"])
os.makedirs(os.environ["PANTHEON_STATE"])
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = P.start(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


try:
    _spec = importlib.util.spec_from_file_location("pantheon_startreq_test", os.path.join(LIB, "pantheon.py"))
    P = importlib.util.module_from_spec(_spec)
    sys.modules["pantheon_startreq_test"] = P
    _spec.loader.exec_module(P)
    doms = {"hermes-alex": ["~/projects/alexbroker"], "solo-led": ["~/projects/solo"]}
    P.write_json(P.path("domains.json"), {"domains": doms})
    with open(os.path.join(P.PANTHEON, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "hermes-alex"\nfolders = ["~/projects/alexbroker"]\n'
                 '[[direction]]\nname = "solo-led"\nfolders = ["~/projects/solo"]\ncoordinator = false\n')
    qdir = P.path(P.HQ_RW, "start-req")
    req = os.path.join(qdir, "hermes-alex.req")
    os.environ["PANTHEON_ROLE"] = "hq"

    rc, out, err = call(["hermes-alex"])
    check("принята: имя из реестра → 0, «заявка принята, окно поднимется на следующем проходе»",
          rc == 0 and "заявка принята, окно hermes-alex поднимется на следующем проходе" in out, (rc, out, err))
    data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
    check("принята: файл заявки — строка JSON {target, time, by: zeus}",
          len(data) == 1 and set(data[0]) == {"target", "time", "by"} and data[0]["target"] == "hermes-alex"
          and data[0]["by"] == "zeus", data)

    for argv, why in ((["evil-dir"], "15 чужое имя"), (["../x"], "15 имя с путём"), (["solo-led"], "18 coordinator = false")):
        rc, out, err = call(argv)
        check(f"{why} → отказ, код 2, файла нет", rc == 2 and "заявка не принята" in err
              and not os.path.exists(os.path.join(qdir, argv[0] + ".req")), (rc, out, err))

    os.unlink(req)
    rc, out, err = call(["hermes-alex", "сделай всё сам"])
    check("16 с аргументами → не заявка: прежний путь, отказ без вашего слова (код 2), файла нет",
          rc == 2 and not os.path.exists(req) and "заявка принята" not in out, (rc, out, err))
    rc, out, err = call(["hermes-alex", "--at", "23:59"])
    check("16 с флагом --at → не заявка (отказ без слова), файла нет", rc != 0 and not os.path.exists(req), (rc, out, err))
    os.environ.pop("PANTHEON_ROLE")
    rc, out, err = call(["evil-dir", "--dry-run"])
    check("вне окна hq заявки нет: прежний запуск", "заявка" not in out + err, (rc, out, err))
    os.environ["PANTHEON_ROLE"] = "hq"

    # проход: корректная заявка → разовый запуск; подложенные — тревога, без запуска; файлы сняты
    call(["hermes-alex"])
    with open(os.path.join(qdir, "solo-led.req"), "w") as fh:  # имя, у которого нет координатора
        fh.write(json.dumps({"target": "solo-led", "time": "x", "by": "zeus"}) + "\n")
    with open(os.path.join(qdir, "ghost.req"), "w") as fh:  # имени нет в реестре
        fh.write(json.dumps({"target": "ghost", "time": "x", "by": "zeus"}) + "\n")
    os.makedirs(os.path.join(_ROOT, "elsewhere"))
    with open(os.path.join(_ROOT, "elsewhere", "x"), "w") as fh:
        fh.write(json.dumps({"target": "hermes-alex", "time": "x", "by": "zeus"}) + "\n")
    t = P.now()
    got = dict(P.take_start_requests(doms, t))
    items = P.night_mod().oneshot_items()
    check("проход: заявка → разовый запуск by=zeus-request с поручением про STATUS.md и inbox",
          isinstance(got.get("hermes-alex"), str) and got["hermes-alex"].startswith("at-")
          and any(x["target"] == "hermes-alex" and x["by"] == "zeus-request" and "inbox/" in x["text"] for x in items),
          (got, items))
    check("17/18 проход: заявки на solo-led и ghost отклонены, разовых запусков у них нет",
          "координатора" in got.get("solo-led", "") + P.hq_led_why("solo-led") and "реестре" in got.get("ghost", "")
          and not any(x["target"] in ("solo-led", "ghost") for x in items), got)
    check("проход: файлы заявок сняты", not [f for f in os.listdir(qdir) if f.endswith(".req")], os.listdir(qdir))

    with open(req, "w") as fh:  # лишний ключ — поручение в обход
        fh.write(json.dumps({"target": "hermes-alex", "time": "x", "by": "zeus", "text": "сделай чужое"}) + "\n")
    with open(os.path.join(qdir, "x.req"), "w") as fh:  # имя в строке не как у файла
        fh.write(json.dumps({"target": "hermes-alex", "time": "x", "by": "zeus"}) + "\n")
    n0 = len(P.night_mod().oneshot_items())
    got = dict(P.take_start_requests(doms, t + 120))
    check("17 подложенная заявка: лишний ключ — отказ", "не по образцу" in got.get("hermes-alex", ""), got)
    check("17 подложенная заявка: имя не из реестра или не как у файла — отказ", "x" in got and not got["x"].startswith("at-"), got)
    os.symlink(os.path.join(_ROOT, "elsewhere", "x"), req)
    got = dict(P.take_start_requests(doms, t + 240))
    check("17 заявка-ссылка — отказ (O_NOFOLLOW), ссылка снята",
          "не открыть" in got.get("hermes-alex", "") and not os.path.lexists(req), got)
    check("17 подложенные заявки разовых запусков не добавили", len(P.night_mod().oneshot_items()) == n0)
finally:
    os.environ.pop("PANTHEON_ROLE", None)
    shutil.rmtree(_ROOT, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
