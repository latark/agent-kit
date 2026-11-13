#!/usr/bin/env python3
"""metis-0771: `pantheon start <направление>` без других слов в окне Пританея (PANTHEON_ROLE=hq) — заявка в
STATE/hq-rw/start-req, а не запуск; плановый проход (take_start_requests) превращает её в разовый запуск. Имя — только
из реестра (domains.json), не направление с coordinator = false; подложенный файл заявки — тревога без запуска.
Строки 15–18 модели угроз (drafts/0771-threat-model.md).
metis-1066: `pantheon resume <направление>` и `pantheon wake hestia --task <id>` в окне hq — строки resume/task в той же
заявке; проход исполняет их только при вашей записи в owner-log/zeus.md до заявки, иначе тревога без запуска.

Запуск: python3 -I plugins/pantheon/tests/test_start_request.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
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


def call(argv, fn=None):
    """P.start(argv), а с fn — fn(argv[-1]) (cancel_request по id)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = fn(argv[-1]) if fn else P.start(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


try:
    _spec = importlib.util.spec_from_file_location("pantheon_startreq_test", os.path.join(LIB, "pantheon.py"))
    P = importlib.util.module_from_spec(_spec)
    sys.modules["pantheon_startreq_test"] = P
    _spec.loader.exec_module(P)
    doms = {"hermes-siteb": ["~/projects/site-b"], "solo-led": ["~/projects/solo"]}
    P.write_json(P.path("domains.json"), {"domains": doms})
    with open(os.path.join(P.PANTHEON, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "hermes-siteb"\nfolders = ["~/projects/site-b"]\n'
                 '[[direction]]\nname = "solo-led"\nfolders = ["~/projects/solo"]\ncoordinator = false\n')
    qdir = P.path(P.HQ_RW, "start-req")
    req = os.path.join(qdir, "hermes-siteb.req")
    os.environ["PANTHEON_ROLE"] = "hq"

    rc, out, err = call(["hermes-siteb"])
    check("принята: имя из реестра → 0, «заявка принята, окно поднимется на следующем проходе»",
          rc == 0 and "заявка принята, окно hermes-siteb поднимется на следующем проходе" in out, (rc, out, err))
    data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
    check("принята: файл заявки — строка JSON {target, time, by: zeus}",
          len(data) == 1 and set(data[0]) == {"target", "time", "by"} and data[0]["target"] == "hermes-siteb"
          and data[0]["by"] == "zeus", data)

    for argv, why in ((["evil-dir"], "15 чужое имя"), (["../x"], "15 имя с путём"), (["solo-led"], "18 coordinator = false")):
        rc, out, err = call(argv)
        check(f"{why} → отказ, код 2, файла нет", rc == 2 and "заявка не принята" in err
              and not os.path.exists(os.path.join(qdir, argv[0] + ".req")), (rc, out, err))

    os.unlink(req)
    inbox = os.path.join(P.PANTHEON, "directions", "hermes-siteb", "inbox")
    rc, out, err = call(["hermes-siteb", "сделай всё сам"])
    got = sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []
    body = open(os.path.join(inbox, got[0]), encoding="utf-8").read() if got else ""
    data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
    check("16 (metis-1009) с поручением → файл во входящих направления и заявка без текста поручения, код 0",
          rc == 0 and len(got) == 1 and "сделай всё сам" in body and len(data) == 1
          and set(data[0]) == {"target", "time", "by"} and "заявка принята" in out, (rc, out, err, got, data))
    for f in got:
        os.unlink(os.path.join(inbox, f))
    os.unlink(req)
    for argv in (["hermes-siteb", "--restart"], ["hermes-siteb", "--restart", "сделай"], ["hermes-siteb", "--over-cap"],
                 ["hermes-siteb", "--force", "сделай"]):
        rc, out, err = call(argv + ["--dry-run"])
        check(f"16 {' '.join(argv[1:])} → не заявка и не поручение: прежний путь (start_gate)",
              "заявка принята" not in out and "была бы принята" not in out and "легло бы" not in out
              and not os.path.exists(req) and not os.listdir(inbox), (rc, out, err))

    def start_files():
        """Файлы поручений (…-start-….md) где угодно во временном корне теста."""
        return sorted(os.path.join(d, f) for d, _, fs in os.walk(_ROOT) for f in fs if "-start-" in f and f.endswith(".md"))

    for name, why in (("../../../escape", "имя с ../"), ("evil-dir", "имя не из реестра"),
                      ("solo-led", "coordinator = false (hq_led)")):
        rc, out, err = call([name, "сделай"])
        check(f"16 поручение на {why} → отказ, код 2, файла поручения нигде нет",
              rc == 2 and "заявка не принята" in err and not start_files(), (rc, out, err, start_files()))
    shutil.rmtree(inbox)
    away = os.path.join(_ROOT, "away")
    os.makedirs(away)
    os.symlink(away, inbox)
    rc, out, err = call(["hermes-siteb", "сделай"])
    check("16 inbox — символьная ссылка → код 1, по ссылке ничего не записано, заявки нет",
          rc == 1 and not os.listdir(away) and not os.path.exists(req), (rc, out, err, os.listdir(away)))
    os.unlink(inbox)
    os.makedirs(inbox)
    rc, out, err = call(["hermes-siteb", "x" * (getattr(P, "START_ORDER_MAX", 100_000) + 1)])
    check("16 поручение длиннее START_ORDER_MAX → отказ, ни файла, ни заявки",
          rc != 0 and not os.listdir(inbox) and not os.path.exists(req), (rc, out, err))
    rc, out, err = call(["hermes-siteb", "--at", "23:59"])
    check("16 с флагом --at → не заявка (отказ без слова), файла нет", rc != 0 and not os.path.exists(req), (rc, out, err))
    os.environ.pop("PANTHEON_ROLE")
    rc, out, err = call(["evil-dir", "--dry-run"])
    check("вне окна hq заявки нет: прежний запуск", "заявка" not in out + err, (rc, out, err))
    os.environ["PANTHEON_ROLE"] = "hq"

    # проход: корректная заявка → разовый запуск; подложенные — тревога, без запуска; файлы сняты
    call(["hermes-siteb"])
    with open(os.path.join(qdir, "solo-led.req"), "w") as fh:  # имя, у которого нет координатора
        fh.write(json.dumps({"target": "solo-led", "time": "x", "by": "zeus"}) + "\n")
    with open(os.path.join(qdir, "ghost.req"), "w") as fh:  # имени нет в реестре
        fh.write(json.dumps({"target": "ghost", "time": "x", "by": "zeus"}) + "\n")
    os.makedirs(os.path.join(_ROOT, "elsewhere"))
    with open(os.path.join(_ROOT, "elsewhere", "x"), "w") as fh:
        fh.write(json.dumps({"target": "hermes-siteb", "time": "x", "by": "zeus"}) + "\n")
    t = P.now()
    got = dict(P.take_start_requests(doms, t))
    items = P.night_mod().oneshot_items()
    check("проход: заявка → разовый запуск by=zeus-request с поручением про STATUS.md и inbox",
          isinstance(got.get("hermes-siteb"), str) and got["hermes-siteb"].startswith("at-")
          and any(x["target"] == "hermes-siteb" and x["by"] == "zeus-request" and "inbox/" in x["text"] for x in items),
          (got, items))
    check("17/18 проход: заявки на solo-led и ghost отклонены, разовых запусков у них нет",
          "координатора" in got.get("solo-led", "") + P.hq_led_why("solo-led") and "реестре" in got.get("ghost", "")
          and not any(x["target"] in ("solo-led", "ghost") for x in items), got)
    check("проход: файлы заявок сняты", not [f for f in os.listdir(qdir) if f.endswith(".req")], os.listdir(qdir))

    with open(req, "w") as fh:  # лишний ключ — поручение в обход
        fh.write(json.dumps({"target": "hermes-siteb", "time": "x", "by": "zeus", "text": "сделай чужое"}) + "\n")
    with open(os.path.join(qdir, "x.req"), "w") as fh:  # имя в строке не как у файла
        fh.write(json.dumps({"target": "hermes-siteb", "time": "x", "by": "zeus"}) + "\n")
    n0 = len(P.night_mod().oneshot_items())
    got = dict(P.take_start_requests(doms, t + 120))
    check("17 подложенная заявка: лишний ключ — отказ", "не по образцу" in got.get("hermes-siteb", ""), got)
    check("17 подложенная заявка: имя не из реестра или не как у файла — отказ", "x" in got and not got["x"].startswith("at-"), got)
    os.symlink(os.path.join(_ROOT, "elsewhere", "x"), req)
    got = dict(P.take_start_requests(doms, t + 240))
    check("17 заявка-ссылка — отказ (O_NOFOLLOW), ссылка снята",
          "не открыть" in got.get("hermes-siteb", "") and not os.path.lexists(req), got)
    check("17 подложенные заявки разовых запусков не добавили", len(P.night_mod().oneshot_items()) == n0)

    # metis-1009: --at-cancel из окна hq — строка cancel в заявке; проход гасит разовый запуск и окно не поднимает
    oid = P.night_mod().oneshot_add("hermes-siteb", t + 5 * 3600, "позже", "zeus", t=t)
    rc, out, err = call(["--at-cancel", oid], P.cancel_request)  # её зовёт start_at, когда oneshot.json закрыт
    data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
    check("cancel: в окне hq без записи oneshot.json → заявка {target, time, by, cancel}, код 0",
          rc == 0 and len(data) == 1 and data[0].get("cancel") == oid, (rc, out, err, data))
    n0 = len(P.night_mod().oneshot_items())
    got = P.take_start_requests(doms, t + 360)
    items = {x["id"]: x for x in P.night_mod().oneshot_items()}
    check("cancel: проход отменил разовый запуск и не добавил новых (одна отмена — без подъёма окна)",
          items[oid].get("done_at") and len(items) == n0 and got == [("hermes-siteb", f"cancel {oid}: отменён")],
          (got, items[oid]))
    rc, out, err = call(["--at-cancel", oid], P.cancel_request)
    check("cancel: отмена уже погашенного id → код 1, заявки нет", rc == 1 and "погашен" in err
          and not os.path.exists(req), (rc, out, err))
    oid2 = P.night_mod().oneshot_add("solo-led", t + 6 * 3600, "чужое", "zeus", t=t)
    with open(req, "w") as fh:  # отмена разового запуска другого направления под заявкой hermes-siteb
        fh.write(json.dumps({"target": "hermes-siteb", "time": "x", "by": "zeus", "cancel": oid2}) + "\n")
    got = dict(P.take_start_requests(doms, t + 480))
    items = {x["id"]: x for x in P.night_mod().oneshot_items()}
    check("cancel: id чужого направления — отказ «не по образцу», разовый запуск цел",
          "не по образцу" in got.get("hermes-siteb", "") and not items[oid2].get("done_at"), (got, items[oid2]))
    rc, out, err = call(["--at-cancel", "at-20991231-2359-hermes-siteb"], P.cancel_request)
    check("cancel: несуществующий id → код 1, заявки нет", rc == 1 and not os.path.exists(req), (rc, out, err))

    # metis-1066: `pantheon resume <направление>` и `pantheon wake hestia --task <id>` из окна Пританея — заявка;
    # плановый проход сверяет ваше слово в owner-log/zeus.md, снимает метку и поднимает окно
    import time as _time
    W = P.watch_mod()
    alerts = os.path.join(P.PANTHEON, "alerts.md")
    stopped = P.path("stopped", "hermes-siteb")

    def word(ago):
        """Ваша запись в owner-log/zeus.md ago секунд назад (её пишет хук; здесь — тест)."""
        os.makedirs(P.path("owner-log"), exist_ok=True)
        with open(P.path("owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
            fh.write(f"## {_time.strftime('%Y-%m-%d %H:%M:%S', _time.localtime(P.now() - ago))}\n\nверни\n")

    def run(fn, *a):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fn(*a)
        return rc, out.getvalue(), err.getvalue()

    def alerts_text():
        return open(alerts, encoding="utf-8").read() if os.path.exists(alerts) else ""

    def mark():
        os.makedirs(P.path("stopped"), exist_ok=True)
        with open(stopped, "w") as fh:
            fh.write("2026-11-12 16:00 владелец\n")

    def req_line(**kw):
        with open(req, "w") as fh:
            fh.write(json.dumps({"target": "hermes-siteb", "time": P.stamp(P.now()), "by": "zeus", **kw}) + "\n")

    def oneshots_of(name):
        return [x for x in P.night_mod().oneshot_items() if x["target"] == name and x["by"] == "zeus-request"
                and not x.get("done_at")]

    for x in P.night_mod().oneshot_items():
        P.night_mod().oneshot_cancel(x["id"], P.now(), "тест")
    mark()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(P.path("owner-log", "zeus.md"))
    a0 = len(alerts_text())
    rc, out, err = run(W.resume, ["hermes-siteb"], "zeus")
    check("1066 окно hq без вашего слова: resume → код 1, тревога, заявки нет, метка на месте",
          rc == 1 and "отклонён" in alerts_text()[a0:] and not os.path.exists(req) and os.path.exists(stopped),
          (rc, out, err))

    word(60)
    os.chmod(P.path("stopped"), 0o555)  # песочница окна hq: STATE/stopped закрыт (без песочницы метку снимает сам resume)
    try:
        rc, out, err = run(W.resume, ["hermes-siteb"], "zeus")
    finally:
        os.chmod(P.path("stopped"), 0o755)
    data = [json.loads(x) for x in open(req).read().splitlines()] if os.path.exists(req) else []
    check("1066 окно hq со словом, STATE/stopped закрыт: resume → код 0, заявка {target, time, by, resume: true}",
          rc == 0 and "заявка принята" in out and len(data) == 1 and data[0].get("resume") is True
          and set(data[0]) == {"target", "time", "by", "resume"} and os.path.exists(stopped), (rc, out, err, data))
    a0 = len(alerts_text())
    got = dict(P.take_start_requests(doms, P.now()))
    check("1066 проход: заявка вернуть → метка снята, разовый запуск zeus-request, сброс самозапуска",
          not os.path.exists(stopped) and str(got.get("hermes-siteb", "")).startswith("at-")
          and len(oneshots_of("hermes-siteb")) == 1 and "метка «остановлено вами» снята" in alerts_text()[a0:]
          and os.path.exists(P.path(P.HQ_RW, "autostart-reset", "hermes-siteb")), (got, alerts_text()[a0:]))

    for x in P.night_mod().oneshot_items():
        P.night_mod().oneshot_cancel(x["id"], P.now(), "тест")
    for kw, ago, why in (({"resume": True}, 3 * 3600, "слово старше 15 мин до заявки"),
                         ({"resume": True, "time": P.stamp(P.now() - 3600)}, 3600 + 60, "заявка старше REQ_FRESH"),
                         ({"resume": True, "time": P.stamp(P.now() - 25 * 60)}, 26 * 60,
                          "старое время заявки и слово старше 15 мин от прохода"),
                         ({"resume": True, "time": P.stamp(P.now() - 10 * 60)}, 20 * 60,
                          "слово за 15 мин до времени заявки, но старше 15 мин от прохода (время пишет окно)"),
                         ({"resume": True, "time": P.stamp(P.now() - 20 * 60)}, 60, "свежее слово, заявка старше 15 мин"),
                         ({"resume": True, "time": "x"}, 60, "время не по образцу"),
                         ({"resume": 1}, 60, "resume не true"),
                         ({"resume": True, "cancel": "at-20991231-2359-hermes-siteb"}, 60, "resume вместе с cancel")):
        mark()
        word(ago)
        req_line(**kw)
        a0 = len(alerts_text())
        got = dict(P.take_start_requests(doms, P.now()))
        check(f"1066 проход: {why} → отклонена с тревогой, метка на месте, окно не поднято",
              "отклонена" in alerts_text()[a0:] and not str(got.get("hermes-siteb", "at-")).startswith("at-")
              and os.path.exists(stopped) and not oneshots_of("hermes-siteb"), (got, alerts_text()[a0:]))
    word(60)
    with open(req, "w") as fh:  # обычная заявка рядом с «вернуть» без слова — вся заявка отклонена
        fh.write(json.dumps({"target": "hermes-siteb", "time": "x", "by": "zeus"}) + "\n")
    got = dict(P.take_start_requests(doms, P.now()))
    check("1066 проход: обычная заявка без resume слова не требует (как раньше), метку не снимает",
          str(got.get("hermes-siteb", "")).startswith("at-") and os.path.exists(stopped), got)

    check("1066 resume_request: имя, которое ведёт Пританей, — прежний путь (None)", P.resume_request("solo-led") is None)
    if os.geteuid() != 0:
        os.makedirs(P.path("stopped"), exist_ok=True)
        with open(P.path("stopped", "solo-led"), "w") as fh:
            fh.write("x\n")
        os.chmod(P.path("stopped"), 0o555)
        try:
            rc, out, err = run(W.resume, ["solo-led"], "zeus")
        finally:
            os.chmod(P.path("stopped"), 0o755)
        check("1066 окно hq, имя не из реестра, STATE/stopped закрыт → код 1 и причина строкой, без трассировки",
              rc == 1 and "песочница окна закрывает STATE/stopped" in err, (rc, out, err))

    # Гестия: окно hq, которому STATE/settings/run закрыт, — заявка hestia.req
    tdir = os.path.join(P.PANTHEON, "directions", "metis-pantheon", "tasks")
    os.makedirs(tdir, exist_ok=True)
    with open(os.path.join(tdir, "metis-0001.md"), "w", encoding="utf-8") as fh:
        fh.write("---\ntype: task\nid: metis-0001\ntitle: \"Поставить выпуск\"\nstatus: todo\nproject: Пантеон\n"
                 "direction: metis-pantheon\nowner: hestia\ncreated: 2026-11-12\nupdated: 2026-11-12T16:00:00\n"
                 "schema_version: 1\n---\n\n# Поставить выпуск\n")
    os.makedirs(P.path("settings", "run"), exist_ok=True)
    with open(P.path("settings", "hestia.json"), "w") as fh:
        fh.write("{}")
    os.makedirs(os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox", "hestia"), exist_ok=True)
    os.makedirs(P.AGENTS, exist_ok=True)
    with open(os.path.join(P.AGENTS, "hestia.md"), "w") as fh:
        fh.write("---\nname: hestia\n---\n")
    hreq = os.path.join(qdir, "hestia.req")
    if os.geteuid() != 0:
        os.chmod(P.path("settings", "run"), 0o555)
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(P.path("owner-log", "zeus.md"))
            a0 = len(alerts_text())
            rc, out, err = run(P.wake_hestia, ["hestia", "--task", "metis-0001"])
            check("1066 wake hestia в окне hq без вашего слова → код 2, тревога, заявки нет",
                  rc == 2 and "отклонён" in alerts_text()[a0:] and not os.path.exists(hreq), (rc, out, err))
            word(60)
            rc, out, err = run(P.wake_hestia, ["hestia", "--task", "metis-0001"])
            data = [json.loads(x) for x in open(hreq).read().splitlines()] if os.path.exists(hreq) else []
            check("1066 wake hestia в окне hq со словом → код 0, заявка {target: hestia, time, by, task}",
                  rc == 0 and len(data) == 1 and data[0] == {"target": "hestia", "time": data[0]["time"], "by": "zeus",
                                                             "task": "metis-0001"}, (rc, out, err, data))
        finally:
            os.chmod(P.path("settings", "run"), 0o755)
        calls = []
        G = P.take_start_requests.__globals__
        real = G["_hestia_by_request"]
        G["_hestia_by_request"] = lambda tid: calls.append(tid) or "поднята"
        try:
            got = dict(P.take_start_requests(doms, P.now()))
            check("1066 проход: заявка Гестии → pantheon wake hestia --task metis-0001 (один вызов), файл снят",
                  calls == ["metis-0001"] and got.get("hestia") == "поднята" and not os.path.exists(hreq), (calls, got))
            for line, ago, why in (({"task": "metis-0001", "cancel": "x"}, 60, "лишний ключ"),
                                   ({"task": "../etc"}, 60, "id задачи не по образцу"),
                                   ({}, 60, "без task"),
                                   ({"task": "metis-0001"}, 3 * 3600, "без вашего слова")):
                word(ago)
                with open(hreq, "w") as fh:
                    fh.write(json.dumps({"target": "hestia", "time": P.stamp(P.now()), "by": "zeus", **line}) + "\n")
                del calls[:]
                a0 = len(alerts_text())
                got = dict(P.take_start_requests(doms, P.now()))
                check(f"1066 проход: заявка Гестии, {why} → отклонена с тревогой, Гестия не поднята",
                      not calls and "отклонена" in alerts_text()[a0:] and got.get("hestia") != "поднята", (calls, got))
        finally:
            G["_hestia_by_request"] = real

        class FakeSub:  # subprocess модуля sessions: argv и окружение дочернего pantheon без запуска
            TimeoutExpired = subprocess.TimeoutExpired
            seen = []
            rc = 0

            @classmethod
            def run(cls, argv, **kw):
                cls.seen.append((argv, kw.get("env") or {}))
                return subprocess.CompletedProcess(argv, cls.rc, "", "" if cls.rc == 0 else "строка\nотказ — причина\n")

        real_sub = G["subprocess"]
        G["subprocess"] = FakeSub
        try:
            res = G["_hestia_by_request"]("metis-0001")
            FakeSub.rc = 2
            res2 = G["_hestia_by_request"]("metis-0001")
        finally:
            G["subprocess"] = real_sub
        argv, env = FakeSub.seen[0] if FakeSub.seen else ([], {})
        check("1066 _hestia_by_request: pantheon wake hestia --task <id> --from zeus, без роли окна; итог строкой",
              argv[1:] == ["wake", "hestia", "--task", "metis-0001", "--from", "zeus"] and argv[0].endswith("/bin/pantheon")
              and "PANTHEON_ROLE" not in env and res == "поднята" and res2 == "не вышло, код 2: отказ — причина",
              (FakeSub.seen, res, res2))
    os.environ["PANTHEON_ROLE"] = "domain-coordinator"
    rc, out, err = run(P.wake_hestia, ["hestia", "--task", "metis-0001", "--from", "zeus"])
    check("1066 wake hestia --from zeus в окне не hq → код 2", rc == 2 and "--from zeus" in err, (rc, out, err))
    os.environ.pop("PANTHEON_ROLE")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(P.path("owner-log", "zeus.md"))
    real_agents, real_path = P.agents_all, os.environ.get("PATH", "")
    P.agents_all = lambda *a, **k: []
    os.environ["PATH"] = "/usr/bin:/bin"  # настоящий claude тест не зовёт ни при какой ошибке шлюза
    try:
        rc, out, err = run(P.wake_hestia, ["hestia", "--task", "metis-0001", "--from", "zeus"])
    finally:
        P.agents_all = real_agents
        os.environ["PATH"] = real_path
    check("1066 wake hestia --from zeus вне окна без вашего слова → отказ start_gate, код 2",
          rc == 2 and "без вашего слова" in err, (rc, out, err))
    os.environ["PANTHEON_ROLE"] = "hq"
finally:
    os.environ.pop("PANTHEON_ROLE", None)
    shutil.rmtree(_ROOT, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
