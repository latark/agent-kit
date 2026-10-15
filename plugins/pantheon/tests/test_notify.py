#!/usr/bin/env python3
"""Умные уведомления (metis-0023) на временных папках и фиктивном времени: присутствие по простою, тихие часы и
утренний дайджест, повтор и «долго ждёт», склейка по id, журнал уведомлений (исходы answer/expired/closed),
бюджет в день, пороги из [notify] в schedule.toml, сбои класса «скоро», критичное, переход digest_day.

Всё — через CLI `pantheon board`/`tick`/`alert` с PANTHEON_NOW, PANTHEON_FAKE_IDLE, PANTHEON_NOTIFY_LOG и TZ=Europe/Moscow.
Запуск: python3 -I plugins/pantheon/tests/test_notify.py  (код выхода 0 — все прошли)
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
MSK = timezone(timedelta(hours=3))  # Москва без перехода на летнее время с 2014 года
results = []


def at(day, hh, mm=0):
    """Метка времени: 2026-10-<day> ЧЧ:ММ по Москве."""
    return datetime(2026, 10, day, hh, mm, tzinfo=MSK).timestamp()


def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


def make(schedule=""):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="notify-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w", encoding="utf-8").write('primary_host = "mac-a"\n' + schedule)
    log = os.path.join(tmp, "notify.log")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NOTIFY_LOG": log,
           "TZ": "Europe/Moscow"}
    return {"tmp": tmp, "home": home, "state": state, "view": view, "env": env, "log": log}


def run(w, *args, t, idle=0, env=None):
    e = dict(w["env"], PANTHEON_NOW=str(t), PANTHEON_FAKE_IDLE=str(idle), **(env or {}))
    return subprocess.run([sys.executable, "-I", CLI, *args], env=e, capture_output=True, text=True, timeout=60)


def board(w, t, idle=0):
    r = run(w, "board", t=t, idle=idle)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
    return r


def question(w, title, t, due=None, recommend=None):
    args = ["task", "new", "--direction", "metis-pantheon", "--title", title, "--status", "waiting", "--waiting-on",
            "human", "--next", "ответ", "--question", f"{title}?", "--option", "А — первый вариант, дешевле",
            "--option", "Б — второй вариант, дороже", "--project", "Пантеон"]
    if due:
        args += ["--due", due]
    if recommend:
        args += ["--recommend", recommend]
    r = run(w, *args, t=t)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[0]


def sent(w, clear=True):
    """Уведомления из PANTHEON_NOTIFY_LOG: [(заголовок, текст, ссылка, группа)]; clear — обнулить журнал."""
    try:
        with open(w["log"], encoding="utf-8") as fh:
            lines = [l for l in fh.read().split("\n") if l]
    except OSError:
        lines = []
    if clear:
        open(w["log"], "w").close()
    return [tuple(l.split("|", 3)) for l in lines]


def pings(xs):
    """Без утреннего дайджеста (он уходит при первом движении дня — «здесь»)."""
    return [x for x in xs if x[3] != "digest"]


def journal(w):
    p = os.path.join(w["state"], "notify-log.jsonl")
    try:
        with open(p, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def card(w, tid):
    d = os.path.join(w["view"], "Доска")
    for f in os.listdir(d):
        if f.startswith(tid + " "):
            return os.path.join(d, f)
    return None


def summary(w):
    with open(os.path.join(w["view"], "Доска", "Сводка.md"), encoding="utf-8") as fh:
        return fh.read()


def src(w, tid):
    return os.path.join(w["home"], "directions", "metis-pantheon", "tasks", tid + ".md")


def edit(p, old, new):
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    assert old in text, (p, old)
    text = text.replace(old, new, 1)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def presence_case():
    """(а) простой 1 и 5 мин — без macOS, 15 мин — есть."""
    w = make()
    q = question(w, "Присутствие", at(20, 12))
    board(w, at(20, 12, 1), idle=60)
    a = sent(w)
    board(w, at(20, 12, 2), idle=300)
    b = sent(w)
    board(w, at(20, 12, 3), idle=900)
    c = sent(w)
    check("(а) простой 1 мин («здесь») и 5 мин («рядом») — без macOS по решению", not pings(a) and not pings(b))
    check("(а) простой 15 мин («нет») — одно уведомление «❓ Вопрос к вам» с карточкой и группой id",
          len(c) == 1 and "Вопрос к вам: Присутствие" in c[0][1] and "file=" in c[0][2] and c[0][3] == q)


def quiet_case():
    """(б) тихие часы: без срока — в очередь; срок до утра — сразу; утренний дайджест при первом движении."""
    w = make()
    q1 = question(w, "Ночной без срока", at(20, 23, 20))
    board(w, at(20, 23, 30), idle=1200)
    a = sent(w)
    # срок через 7 ч 20 мин — дальше urgent_hours, но раньше конца тихих часов: срочно
    q2 = question(w, "Срок до утра", at(20, 23, 40), due="2026-10-21T07:00", recommend="А — потому что дешевле")
    board(w, at(20, 23, 45), idle=0)
    c = sent(w)
    check("(б) ночью решение со сроком 07:00 (раньше конца тихих часов) — уведомление сразу, мимо присутствия",
          len(c) == 1 and "Срочно" in c[0][1] and "Срок до утра" in c[0][1] and c[0][3] == q2)
    board(w, at(21, 3), idle=1200)
    b = sent(w)
    check("(б) 23:30 и 03:00 при простое — решение без срока не будит", not a and not b)
    board(w, at(21, 6, 0), idle=1200)
    d = sent(w)
    check("(б) срочное: напоминание за 60 мин до срока", len(d) == 1 and "Срок до утра" in d[0][1])
    board(w, at(21, 6, 31), idle=1200)
    board(w, at(21, 6, 40), idle=1200)
    e = sent(w)
    check("(б) срочное: напоминание за 30 мин — одно, без повторов", len(e) == 1 and "Срок до утра" in e[0][1])
    board(w, at(21, 8, 30), idle=1800)
    f = sent(w)
    check("(б) 08:30 при простое 30 мин — дайджеста нет и ночное не всплывает пингом", not f)
    board(w, at(21, 8, 31), idle=0)
    g = sent(w)
    board(w, at(21, 8, 32), idle=0)
    h = sent(w)
    check("(б) первое движение после 08:00 — один дайджест «Доброе утро. Нужен ответ: N… Отложено: Q — в сводке»",
          len(g) == 1 and re.search(r"Доброе утро\. Нужен ответ: 2, просрочено: 1, входящих заявок: 0\. Отложено: \d+ — в сводке",
                                    g[0][1]) and g[0][3] == "digest" and "%D0%A1%D0%B2%D0%BE%D0%B4%D0%BA%D0%B0" in g[0][2])
    check("(б) повторный проход — второго дайджеста нет", not h)
    s = summary(w)
    check("(б) сводка: раздел «🔕 Без уведомления» с ночным решением", "🔕 Без уведомления" in s and "Ночной без срока" in s)
    j = journal(w)
    check("(д) истёкший срок — исход expired без answered",
          any(r["id"] == q2 and r.get("outcome") == "expired" and "answered" not in r for r in j))
    check("(б) ночное решение не закрыто и не помечено ответом", not any(r["id"] == q1 and r.get("outcome") for r in j))


def repeat_case():
    """(в) повтор не раньше 60 мин; после 120 мин — «долго ждёт» на карточке и больше ни одного пинга."""
    w = make()
    q = question(w, "Повтор", at(20, 12), recommend="А — потому что дешевле")
    board(w, at(20, 12, 1), idle=1200)
    a = sent(w)
    board(w, at(20, 12, 30), idle=1200)
    b = sent(w)
    board(w, at(20, 13, 2), idle=1200)
    c = sent(w)
    check("(в) первый пинг с советом; через 30 мин — тишина; через 61 мин — повтор с той же группой",
          len(a) == 1 and "совет: А — потому что дешевле" in a[0][1] and not b and len(c) == 1 and c[0][3] == q)
    board(w, at(20, 14, 1), idle=1200)
    for m in (20, 50):
        board(w, at(20, 15, m), idle=1200)
    board(w, at(20, 18), idle=1200)
    d = sent(w)
    with open(card(w, q), encoding="utf-8") as fh:
        ct = fh.read()
    check("(в) после 120 мин — ни одного пинга", not d)
    check("(в) «долго ждёт» во «Внимание» карточки и в сводке",
          re.search(r"\nВнимание: \[[^\]]*долго ждёт", ct) and "долго ждёт" in summary(w))
    base = open(os.path.join(w["view"], "Доска", "Доска.base"), encoding="utf-8").read()
    check("(в) Доска.base: «долго ждёт» поднимает карточку (urgency 1)", 'contains("долго ждёт"), 1' in base)


def group_case():
    """(г) склейка: два решения в проходе — одно уведомление; по одному решению — группа id; ответ — без повторов."""
    w = make()
    question(w, "Склейка один", at(20, 12))
    question(w, "Склейка два", at(20, 12))
    board(w, at(20, 12, 1), idle=1200)
    a = sent(w)
    check("(г) два решения в одном проходе — одно уведомление «Нужен ответ: 2 …», группа decisions, ссылка на сводку",
          len(a) == 1 and a[0][1].startswith("Нужен ответ: 2 — ") and a[0][3] == "decisions"
          and "%D0%A1%D0%B2%D0%BE%D0%B4%D0%BA%D0%B0" in a[0][2])
    q = question(w, "Склейка три", at(20, 12, 2))
    board(w, at(20, 12, 3), idle=1200)
    board(w, at(20, 12, 4), idle=1200)
    b = sent(w)
    check("(г) одно решение, два прохода — одно уведомление с группой = id", len(b) == 1 and b[0][3] == q)
    edit(card(w, q), "- [ ] А — первый вариант, дешевле", "- [x] А — первый вариант, дешевле")
    board(w, at(20, 12, 10), idle=1200)
    for h in (14, 16):
        board(w, at(20, h), idle=1200)
    c = sent(w)
    j = journal(w)
    rec = [r for r in j if r["id"] == q and r.get("outcome")]
    check("(г) ответ галочкой — повторов нет", not any("Склейка три" in x[1] for x in c))
    check("(г) журнал: исход answer со временем ответа владельца",
          len(rec) == 1 and rec[0]["outcome"] == "answer" and rec[0].get("answered", "").startswith("2026-10-20T12:10"))
    check("(г) журнал: строка показа — id, уровень, время показа; текста ответа нет",
          any(r["id"] == q and (r.get("shown") or "").startswith("2026-10-20T12:03") and r["level"] == "normal" for r in j)
          and not any("А — первый" in json.dumps(r, ensure_ascii=False) for r in j))


def journal_case():
    """(д) поддельное answer в файле и закрытие агентом — closed без answered; прямая запись «да» — ValueError."""
    w = make()
    q = question(w, "Подделка", at(20, 12))
    board(w, at(20, 12, 1), idle=1200)
    p = src(w, q)
    edit(p, "status: waiting", 'status: done\nanswer: "да"')
    board(w, at(20, 12, 5), idle=1200)
    rec = [r for r in journal(w) if r["id"] == q and r.get("outcome")]
    check("(д) answer: да в файле задачи и закрытие агентом — исход closed без answered",
          len(rec) == 1 and rec[0]["outcome"] == "closed" and "answered" not in rec[0])
    # ответ в окне вопросов Зевса (журнал owner-log/zeus.md, пометку ставит хук) — тоже ответ: повторов нет
    sent(w)
    z = question(w, "Окно Зевса", at(20, 12, 10))
    board(w, at(20, 12, 11), idle=1200)
    first = sent(w)
    os.makedirs(os.path.join(w["state"], "owner-log"), exist_ok=True)
    with open(os.path.join(w["state"], "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"## 2026-10-20 12:20:00 · окно вопросов\nвопрос: [{q}] чужой вопрос\nответ: да\n\n"
                 f"## 2026-10-20 12:30:00\nпро {z} просто упомянул\n\n")
    board(w, at(20, 13, 15), idle=1200)
    mid = sent(w)
    with open(os.path.join(w["state"], "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"## 2026-10-20 13:20:00 · окно вопросов\nвопрос: [{z}] Окно Зевса?\nответ: А\n\n")
    board(w, at(20, 13, 25), idle=1200)
    board(w, at(20, 14, 30), idle=1200)
    after = sent(w)
    zr = [r for r in journal(w) if r["id"] == z and r.get("outcome")]
    check("(д) упоминание id без окна вопросов — не ответ: повтор идёт; ответ окном вопросов Зевса — исход answer",
          len(first) == 1 and len(mid) == 1 and not after and len(zr) == 1 and zr[0]["outcome"] == "answer"
          and zr[0]["answered"] == "2026-10-20T13:20:00")
    spec = importlib.util.spec_from_file_location("notify_t", os.path.join(LIB, "notify.py"))
    N = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(N)
    jp = os.path.join(w["tmp"], "j.jsonl")
    bad = [dict(outcome="да"), dict(outcome="answer"), dict(outcome="answer", answered="да"),
           dict(outcome="closed", answered="2026-10-20T12:00:00"), dict(outcome="approved")]
    errs = 0
    for kw in bad:
        try:
            N.journal(jp, at(20, 12), "x-0001", "normal", **kw)
        except ValueError:
            errs += 1
    check("(д) запись «да», answer без ответа, answered при другом исходе — ValueError, в журнал не попали",
          errs == len(bad) and not os.path.exists(jp))
    ok = N.journal(jp, at(20, 12), "x-0001", "normal", outcome="answer", answered="2026-10-20T12:00:00")
    check("(д) answer со временем ответа — записывается", ok.get("answered") and os.path.exists(jp))


def budget_case():
    """(е) бюджет 5 в день: шестое прерывающее — в очередь и в сводку; критичное — сразу, но в счёт."""
    w = make()
    titles = [f"Бюджет {i}" for i in range(1, 7)]
    got = []
    for i, title in enumerate(titles):
        question(w, title, at(20, 12, 2 * i))
        board(w, at(20, 12, 2 * i + 1), idle=1200)
        got.append(sent(w))
    check("(е) пять решений — пять уведомлений", all(len(x) == 1 for x in got[:5]))
    check("(е) шестое прерывающее за день — без уведомления", not got[5])
    s = summary(w)
    check("(е) шестое — в сводке «🔕 Без уведомления»", "🔕 Без уведомления" in s
          and "Бюджет 6" in s.split("🔕 Без уведомления")[1])
    r = run(w, "alert", "ключ в логе", "--critical", "--from", "zeus", t=at(20, 12, 20))
    c = sent(w)
    j = journal(w)
    check("(е) критичное сверх бюджета — сразу, в журнале уровнем critical",
          r.returncode == 0 and len(c) == 1 and "критично" in c[0][0] and any(r_["level"] == "critical" for r_ in j))
    st = json.load(open(os.path.join(w["state"], "notify.json"), encoding="utf-8"))
    check("(е) критичное в счёт бюджета", st.get("used") == 6)
    board(w, at(21, 12, 0), idle=0)
    board(w, at(21, 12, 1), idle=1200)
    d = sent(w)
    st = json.load(open(os.path.join(w["state"], "notify.json"), encoding="utf-8"))
    check("(е) новый день — бюджет с нуля: одно утреннее, решения «долго ждут» — без пингов",
          st.get("used") == 1 and len(d) == 1 and "Доброе утро" in d[0][1])


def config_case():
    """(ж) пороги из [notify] в schedule.toml: away_min = 1 — простой 90 с уже «нет»; плохое значение — по умолчанию."""
    w = make("\n[notify]\naway_min = 1\npresent_min = 0.5\n")
    question(w, "Порог", at(20, 12))
    board(w, at(20, 12, 1), idle=90)
    a = sent(w)
    check("(ж) away_min = 1: простой 90 с — уведомление", len(a) == 1 and "Порог" in a[0][1])
    w2 = make('\n[notify]\naway_min = "много"\nrepeat_min = -5\ndaily_budget = true\n')
    question(w2, "Порог", at(20, 12))
    board(w2, at(20, 12, 1), idle=90)
    b = sent(w2)
    board(w2, at(20, 12, 2), idle=900)
    c = sent(w2)
    check("(ж) плохие значения — пороги по умолчанию (90 с — «здесь», 15 мин — «нет»)", not pings(b) and len(c) == 1)
    w3 = make('\n[notify]\nquiet_start = "13:00"\nquiet_end = "14:00"\n')
    question(w3, "Тихо днём", at(20, 13))
    board(w3, at(20, 13, 10), idle=1200)
    d = sent(w3)
    check("(ж) свои тихие часы 13:00–14:00 — в 13:10 тишина", not d)


def faults_case():
    """Сбой класса «скоро» (тревога с note из тика): днём и в отсутствие — macOS; ночью — в очередь, без пинга."""
    sched = '\n[[job]]\nname = "bad"\ncommand = "rm -rf /tmp/x"\nevery = 1\n'
    w = make(sched)
    run(w, "tick", t=at(20, 12), idle=1200)
    a = sent(w)
    check("сбой днём при простое — одно уведомление", len(a) == 1 and "bad" in a[0][1])
    w2 = make(sched)
    run(w2, "tick", t=at(20, 23, 30), idle=1200)
    b = sent(w2)
    st = json.load(open(os.path.join(w2["state"], "notify.json"), encoding="utf-8"))
    check("сбой ночью — без уведомления, в очереди дайджеста", not b and any(x["kind"] == "fault" for x in st["queue"]))
    w3 = make(sched)
    run(w3, "tick", t=at(20, 12), idle=0)
    c = sent(w3)
    check("сбой, когда вы у Mac, — без уведомления (только доска и сводка)", not c)


def conflict_case():
    """Конфликт карточки («Перенос не применён») — без пинга, в сводку."""
    w = make()
    r = run(w, "task", "new", "--direction", "metis-pantheon", "--title", "Конфликт", "--project", "Пантеон",
            "--next", "шаг", t=at(20, 12))
    tid = r.stdout.split()[0]
    board(w, at(20, 12, 1), idle=1200)
    sent(w)
    edit(card(w, tid), "Статус: Очередь", "Статус: В работе")
    with open(src(w, tid), "a", encoding="utf-8") as fh:  # агент поправил задачу, пока вы переносили карточку
        fh.write("\n- 2026-10-20 12:01 — агент: правка\n")
    board(w, at(20, 12, 2), idle=1200)
    a = sent(w)
    s = summary(w)
    check("конфликт карточки — без уведомления, строкой в «🔕 Без уведомления»",
          not a and "Перенос не применён: Конфликт" in s)


def legacy_and_due_case():
    """Переход: digest_day прежнего board.json — второго утреннего нет. Срок с временем: на карточке дата, в выноске время."""
    w = make()
    q = question(w, "Срок со временем", at(20, 7), due="2026-10-25T18:30")
    board(w, at(20, 7, 1), idle=0)  # ночь: дайджеста нет, состояние создано
    os.remove(os.path.join(w["state"], "notify.json"))
    bj = os.path.join(w["state"], "board.json")
    with open(bj, encoding="utf-8") as fh:
        st = json.load(fh)
    st["digest_day"] = "2026-10-20"
    with open(bj, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    sent(w)
    board(w, at(20, 9), idle=0)
    a = sent(w)
    check("переход: утреннее уже было по board.json (до 0.11.15) — второго нет", not any("Доброе утро" in x[1] for x in a))
    with open(card(w, q), encoding="utf-8") as fh:
        ct = fh.read()
    check("срок с временем: «Срок» — дата, в выноске — дата и время",
          "\nСрок: 2026-10-25\n" in ct and "📅 25.10 18:30" in ct)
    r = run(w, "check", t=at(20, 9))
    check("check: due с временем — по схеме", r.returncode == 0 and "с ошибками: 0" in r.stdout)
    board(w, at(21, 9), idle=0)
    b = sent(w)
    check("переход: на следующий день утреннее есть", any("Доброе утро" in x[1] for x in b))


def review_case():
    """Ревью argus 15.10: ночью срочно только срок до конца тихих часов; ваш перенос в «Нужен ответ» — без пингов и не
    ответ; критичное не ждёт прохода доски; ready — по времени срока; срок-дата — напоминания вечером, не ночью."""
    import fcntl
    import time as _time
    # 1. ночью срок после утра (08:30) — не срочно: очередь; утром при «нет» — срочный пинг
    w = make()
    q = question(w, "Срок после утра", at(20, 4, 50), due="2026-10-20T08:30")
    board(w, at(20, 5), idle=1200)
    a = sent(w)
    st = json.load(open(os.path.join(w["state"], "notify.json"), encoding="utf-8"))
    board(w, at(20, 8, 5), idle=1200)
    b = sent(w)
    check("ревью 1: 05:00, срок 08:30 — без пинга, в очереди; 08:05 при «нет» — срочный пинг",
          not a and any(x["id"] == q for x in st["queue"]) and len(b) == 1 and "Срочно" in b[0][1] and b[0][3] == q)
    # 2. вы сами перенесли карточку в «Нужен ответ» — пингов нет; это не ответ
    w = make()
    r = run(w, "task", "new", "--direction", "metis-pantheon", "--title", "Сам спрошу", "--project", "Пантеон",
            "--next", "шаг", t=at(20, 12))
    tid = r.stdout.split()[0]
    board(w, at(20, 12, 1), idle=0)
    edit(card(w, tid), "Статус: Очередь", "Статус: Нужен ответ")
    board(w, at(20, 12, 2), idle=1200)
    board(w, at(20, 12, 22), idle=1200)
    board(w, at(20, 13, 22), idle=1200)
    c = pings(sent(w))
    with open(src(w, tid), encoding="utf-8") as fh:
        moved = "status: waiting" in fh.read()
    check("ревью 2: ваш перенос в «Нужен ответ» — ни одного пинга через 20 и 80 мин при простое 20 мин",
          moved and not c)
    check("ревью 2: перенос не закрывает цикл исходом answer",
          not any(x["id"] == tid and x.get("outcome") for x in journal(w)))
    run(w, "task", "set", tid, "status=todo", t=at(20, 13, 30))
    board(w, at(20, 13, 31), idle=1200)
    rec = [x for x in journal(w) if x["id"] == tid and x.get("outcome")]
    check("ревью 2: карточка ушла — исход closed, без answered",
          len(rec) == 1 and rec[0]["outcome"] == "closed" and "answered" not in rec[0])
    # 3. критичное не ждёт блокировки прохода доски
    w = make()
    os.makedirs(os.path.join(w["state"], "locks"), exist_ok=True)
    fd = os.open(os.path.join(w["state"], "locks", "notify.lock"), os.O_WRONLY | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    t0 = _time.time()
    r = subprocess.run([sys.executable, "-I", CLI, "alert", "прод упал", "--critical", "--from", "zeus"],
                       env=dict(w["env"], PANTHEON_NOW=str(at(20, 12))), capture_output=True, text=True, timeout=60)
    took = _time.time() - t0
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    d = sent(w)
    check("ревью 3: блокировка notify занята — критичное всё равно ушло, команда не висит (< 8 с)",
          r.returncode == 0 and len(d) == 1 and "прод упал" in d[0][1] and took < 8)
    # 4. ready — по времени срока: дата-время того же дня раньше даты без времени
    w = make()
    for title, due in (("Срок днём", "2026-10-21"), ("Срок утром", "2026-10-21T09:00")):
        run(w, "task", "new", "--direction", "metis-pantheon", "--title", title, "--project", "Пантеон", "--due", due,
            t=at(20, 12))
    r = run(w, "task", "ready", t=at(20, 12))
    order = [l.split("\t")[-1] for l in r.stdout.splitlines() if "\t" in l]
    check("ревью 4: task ready — «Срок утром» (09:00) раньше «Срок днём» (дата, конец дня)",
          order == ["Срок утром", "Срок днём"])
    # 5. срок-дата: опорное время — начало тихих часов (23:00): срочно вечером, напоминания 22:00 и 22:30, ночью тихо
    w = make()
    q = question(w, "Срок сегодня", at(20, 20), due="2026-10-20")
    board(w, at(20, 20, 30), idle=0)
    e = pings(sent(w))
    board(w, at(20, 22, 0), idle=0)
    f = pings(sent(w))
    board(w, at(20, 22, 30), idle=0)
    g = pings(sent(w))
    q2 = question(w, "Срок сегодня поздно", at(20, 22, 40), due="2026-10-20")  # первый к 23:10 уже «долго ждёт»
    board(w, at(20, 23, 10), idle=1200)
    h = sent(w)
    st = json.load(open(os.path.join(w["state"], "notify.json"), encoding="utf-8"))
    check("ревью 5: срок-дата, 20:30 при «здесь» — срочный пинг", len(e) == 1 and "Срочно" in e[0][1])
    check("ревью 5: срок-дата — напоминания в 22:00 и 22:30", len(f) == 1 and len(g) == 1)
    check("ревью 5: срок-дата, 23:10 — тишина и очередь", not h and any(x["id"] == q2 for x in st["queue"]))
    check("ревью 5: истечение срока-даты — по концу дня, не в 23:00",
          not any(x["id"] == q and x.get("outcome") for x in journal(w)))
    # тихие часы после полуночи (00:30–08:00): опора срока-даты — конец дня, вечером срочный пинг есть
    w = make('\n[notify]\nquiet_start = "00:30"\nquiet_end = "08:00"\n')
    question(w, "Срок сегодня, тихо после полуночи", at(20, 20), due="2026-10-20")
    board(w, at(20, 20, 30), idle=0)
    k = pings(sent(w))
    check("повторное ревью: тихие часы 00:30–08:00 — срок-дата вечером срочная", len(k) == 1 and "Срочно" in k[0][1])


def main():
    for case in (presence_case, quiet_case, repeat_case, group_case, journal_case, budget_case, config_case,
                 faults_case, conflict_case, legacy_and_due_case, review_case):
        case()
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
