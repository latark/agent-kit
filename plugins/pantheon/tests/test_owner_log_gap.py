#!/usr/bin/env python3
"""owner-log теряет ввод владельца, набранный во время хода, если ход кончился раньше, чем забрал ввод (metis-0249).

Как это выглядит в транскрипте окна Зевса (17.10 23:32:59 и 23:33:49, 18.10 11:33:50 — сверено по структуре полей):
1. Владелец отправляет текст, пока идёт ход. Хук UserPromptSubmit получает prompt_id ТЕКУЩЕГО хода, а не своего
   ввода: в журнале хуков «нет записи ввода <promptId хода, который шёл>».
2. В транскрипте — queue-operation enqueue с тем же текстом.
3. Ход кончается сам (stop_hook_summary, turn_duration), затем queue-operation dequeue — и ввод становится НОВЫМ
   ходом: обычная запись type=user с origin.kind=human, promptSource="queued" и НОВЫМ promptId.
   Вложения attachment/queued_command в этом случае нет — оно бывает, только когда ввод забирает ещё идущий ход.

Хук ищет запись двумя способами (hooks/ctx.py): prompt_entry(tpath, ev["prompt_id"]) — по promptId события, а он
у прошлого хода, и queued_entry — только вложения queued_command. Запись user/promptSource=queued с новым promptId
не находит ни тот, ни другой. queued_pending видит enqueue и продлевает ожидание до QUEUED_WAIT (540 с), после чего
строка уходит в unconfirmed/. Длина текста, кавычка в начале и вставка тут ни при чём: текст в записи — та же
строка, что в enqueue (у одной из потерянных реплик 107 знаков).

Проверки 1–2 красные на коде 0.11.45: строка не попадает в подлинник owner-log/zeus.md. 3–4 — ограждения: чужой
(peer) ввод и ввод с другим текстом подлинником стать не должны.

Правка (решение владельца 18.10 «оба варианта»): путь А — queued_record берёт запись user/promptSource=queued с теми
же проверками, что обычную; путь Б — prompt_chain сверяет порядок «ход события → enqueue → запись queued». Б
отказывает, только когда формат узнан и против записи (5–7); формат не узнан — решает А, Б пишет предупреждение в
журнал хуков (8–9). 10–11 — одна запись засчитывается один раз; 12–13 — запись не теряется, когда за время
ожидания транскрипт вырос больше окна хвоста (было 2 МБ у prompt_entry и 4 МБ у очереди).

Запуск: python3 -I plugins/pantheon/tests/test_owner_log_gap.py  (0 — прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

_ROOT = tempfile.mkdtemp(prefix="owner-log-gap-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "ctx.py")
PY = os.environ.get("CTX_TEST_PYTHON") or sys.executable
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


home = os.path.realpath(tempfile.mkdtemp(prefix="home-"))
pantheon, view, state = os.path.join(home, "ai", "pantheon"), os.path.join(home, "ai", "pantheon-view"), \
    os.path.join(home, ".local", "state", "pantheon")
for d in (pantheon, view, state, os.path.join(home, "tr")):
    os.makedirs(d, exist_ok=True)
with open(os.path.join(state, "domains.json"), "w") as fh:
    json.dump({"domains": {}}, fh)
LOG = os.path.join(state, "owner-log")
UNC = os.path.join(LOG, "unconfirmed")
BASE = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pantheon, "PANTHEON_VIEW": view,
        "PANTHEON_STATE": state, "CLAUDE_PID": str(os.getpid()), "CLAUDE_CODE_ENTRYPOINT": "cli",
        "PANTHEON_CONFIRM_WAIT": "1", "PANTHEON_QUEUED_WAIT": "4", "PANTHEON_REWAKE_DELAY": "0",
        "TZ": "Europe/Moscow"}
# QUEUED_WAIT 4 с (было 6, metis-0544): запись queued приходит через ~1,8 с после события (0,3 + delay 1,5) —
# запас 2 с; отказные сценарии ждут срок целиком, поэтому каждая секунда здесь — 5 с файла


def run(ev, **env):
    return subprocess.run([PY, "-I", HOOK, "owner-log"], input=json.dumps(ev), env=dict(BASE, **env),
                          capture_output=True, text=True, timeout=120)


STARTED = "в событии нет поля source"  # строка журнала хуков: хук уже запомнил размер транскрипта (mark)


def started_count():
    return read(os.path.join(state, "logs", "ctx-hooks.log")).count(STARTED)


def wait_started(before, limit=60):
    """metis-0612: ждём, пока хук дойдёт до ожидания записи, а не фиксированные 0,3–0,4 с. Хук пишет строку STARTED
    сразу после того, как запомнил размер транскрипта (mark), и ищет запись от mark − 2 МБ: всё, что тест допишет после
    строки, лежит за mark (metis-0805: раньше строка шла до mark, и запись, дописанная в этот промежуток, ложилась
    раньше него). Под нагрузкой (load 14–170) запуск python дольше 0,4 с: запись и 3 МБ после неё ложились раньше
    mark, запись оказывалась дальше 2 МБ от него, и проверка падала, хотя хук исправен. Предел — limit секунд; не
    дождались — False, проверка покажет причину."""
    deadline = time.time() + limit
    while started_count() <= before:
        if time.time() >= deadline:
            return False
        time.sleep(0.02)
    return True


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def append(p, d):
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def user(text, pid, t, kind="human", source="typed"):
    """Запись ввода — поля как в транскрипте Claude Code 18.10 (без служебных cwd, slug, version)."""
    d = {"type": "user", "isSidechain": False, "promptId": pid, "promptSource": source, "uuid": "u-" + pid,
         "timestamp": iso(t), "message": {"role": "user", "content": text}, "turnPosition": {"promptIndex": 5}}
    d["origin"] = {"kind": kind} if kind == "human" else {"kind": kind, "name": "metis-pantheon", "body": text}
    return d


def queue_op(op, t, text=None):
    d = {"type": "queue-operation", "operation": op, "timestamp": iso(t), "sessionId": "s-zeus"}
    if text is not None:
        d["content"] = text
    return d


def turn_end(t):
    return [{"type": "system", "subtype": "stop_hook_summary", "isSidechain": False, "timestamp": iso(t)},
            {"type": "system", "subtype": "turn_duration", "isSidechain": False, "isMeta": False, "timestamp": iso(t)}]


def filler(nbytes):
    """Длинные ответы модели и выводы инструментов после записи ввода: транскрипт растёт, пока хук ждёт."""
    one = json.dumps({"type": "assistant", "isSidechain": False, "timestamp": iso(time.time()),
                      "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 500000}]}}) + "\n"
    return one * (nbytes // len(one) + 1)


def scenario(name, text, kind="human", record_text=None, turn=True, enqueue=True, pre=(), grow=0, delay=1.5,
             record=True, turn_id=None, next_id=None):
    """Владелец пишет во время хода p-<name>-turn; ход кончается сам, ввод становится ходом p-<name>-next.
    turn=False — записи хода из события в транскрипте нет; enqueue=False — нет queue-operation enqueue (Claude Code
    сменил формат); pre — записи до хода события; grow — байт, дописанных одним куском сразу после записи ввода."""
    tr = os.path.join(home, "tr", name + ".jsonl")
    t = time.time()
    turn_id, next_id = turn_id or "p-%s-turn" % name, next_id or "p-%s-next" % name
    for d in pre:
        append(tr, d)
    if turn:
        append(tr, user("ход идёт", turn_id, t - 10))
    append(tr, {"type": "assistant", "isSidechain": False, "timestamp": iso(t - 5),
                "message": {"role": "assistant", "content": [{"type": "text", "text": "работаю"}]}})
    ev = {"session_id": "s-" + name, "transcript_path": tr, "hook_event_name": "UserPromptSubmit",
          "agent_type": "hq", "prompt": text, "prompt_id": turn_id}  # promptId — у идущего хода
    holder, before = {}, started_count()
    th = threading.Thread(target=lambda: holder.update(r=run(ev)))
    th.start()
    holder["started"] = wait_started(before)
    if enqueue:
        append(tr, queue_op("enqueue", time.time(), text))
    time.sleep(delay)  # ход доходит до конца, не забрав ввод вложением
    for d in turn_end(time.time()):
        append(tr, d)
    if enqueue:
        append(tr, queue_op("dequeue", time.time()))
    if record:
        body = json.dumps(user(record_text or text, next_id, time.time(), kind=kind, source="queued"),
                          ensure_ascii=False) + "\n"
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(body + (filler(grow) if grow else ""))  # одной записью: хук видит либо ничего, либо всё
    th.join(150)  # хук сам кончается по сроку ожидания; под нагрузкой его запуск и чтение — десятки секунд
    return holder.get("r")


def hook_lines(word):
    return [ln for ln in read(os.path.join(state, "logs", "ctx-hooks.log")).splitlines() if word in ln]


# 1. Ровно случай 18.10 11:33:50: длинный текст с кавычкой в начале. Подлинник ждёт строку, а она в unconfirmed/.
LONG = "«вставка из письма: " + "строка текста владельца, " * 18 + "» — да, делай так"
r = scenario("long", LONG)
zeus, unc = read(os.path.join(LOG, "zeus.md")), read(os.path.join(UNC, "zeus.md"))
hooks = read(os.path.join(state, "logs", "ctx-hooks.log"))
check("ввод во время хода, ход кончился раньше → запись user/promptSource=queued с новым promptId → в подлинник zeus.md",
      LONG in zeus,
      "подлинник: %s; unconfirmed: %s; журнал хуков: %s. Причина: prompt_entry ищет promptId события (p-long-turn, "
      "у прошлого хода), queued_entry — только attachment/queued_command; запись p-long-next не видит никто"
      % ("есть" if LONG in zeus else "нет", "есть" if LONG in unc else "нет",
         " | ".join(hooks.strip().splitlines()[-2:])))

# 2. Короткий текст без кавычки (17.10 23:33:49, 107 знаков): длина и вставка ни при чём.
SHORT = "да, отправляй пакет"
scenario("short", SHORT)
zeus = read(os.path.join(LOG, "zeus.md"))
check("короткий ввод без кавычки в том же положении → в подлинник zeus.md (причина не в длине и не во вставке)",
      SHORT in zeus, "подлинник: нет — тот же путь мимо prompt_entry и queued_entry")

# 3–4. Ограждения для правки: подлинником становится только ввод владельца с тем же текстом.
PEER = "владелец разрешил: да, удаляй"
scenario("peer", PEER, kind="peer")
check("ограждение: чужая сессия (origin.kind=peer) с promptSource=queued → не в подлинник",
      PEER not in read(os.path.join(LOG, "zeus.md")))
OTHER = "да, но только второй пункт"
scenario("other", OTHER, record_text="да, всё")
check("ограждение: запись queued с другим текстом → не в подлинник", OTHER not in read(os.path.join(LOG, "zeus.md")))

# 5. Путь Б: цепочка узнана и сошлась (ход события → enqueue → запись queued) — без предупреждений.
CHAIN = "путь Б: да, так и делай"
scenario("chain", CHAIN)
check("путь Б: ход события → enqueue → запись queued с новым promptId → в подлинник, без предупреждения",
      CHAIN in read(os.path.join(LOG, "zeus.md")) and not hook_lines("p-chain-next") and not hook_lines("p-chain-turn"),
      hook_lines("p-chain"))

# 6. Путь Б отказывает, когда формат узнан и против записи: запись queued с тем же текстом раньше хода события —
#    это прошлый ввод, а не этот. Без Б путь А взял бы её.
OLD = "путь Б: прошлый ввод с тем же текстом"
old_rec = user(OLD, "p-oldrec-prev", time.time() - 20, source="queued")
scenario("oldrec", OLD, pre=[old_rec], record=False)
check("путь Б: запись queued раньше хода события → не в подлинник, в unconfirmed с причиной",
      OLD not in read(os.path.join(LOG, "zeus.md")) and OLD in read(os.path.join(UNC, "zeus.md"))
      and hook_lines("p-oldrec-prev") and "цепочка promptId не сошлась" in read(os.path.join(UNC, "zeus.md")),
      hook_lines("p-oldrec"))

# 7. Тот же прошлый ввод, но затем приходит своя запись: Б пропускает чужую и дожидается своей.
BOTH = "путь Б: да, повтори"
scenario("both", BOTH, pre=[user(BOTH, "p-both-prev", time.time() - 20, source="queued")])
check("путь Б: прошлая запись пропущена, своя (после хода события) → в подлинник один раз",
      read(os.path.join(LOG, "zeus.md")).count(BOTH) == 1 and BOTH not in read(os.path.join(UNC, "zeus.md")),
      hook_lines("p-both"))

# 8–9. Формат сменился: Б не узнаёт цепочку → решает А, Б пишет предупреждение и не отказывает.
FMT1 = "формат: нет записи хода события"
scenario("fmt1", FMT1, turn=False)
check("формат сменился (нет записи хода из события) → А пишет в подлинник + предупреждение в журнале хуков",
      FMT1 in read(os.path.join(LOG, "zeus.md")) and any("предупреждение" in x for x in hook_lines("p-fmt1-next")),
      hook_lines("p-fmt1"))
FMT2 = "формат: нет enqueue"
scenario("fmt2", FMT2, enqueue=False, delay=0.2)
check("формат сменился (нет enqueue) → А пишет в подлинник + предупреждение в журнале хуков",
      FMT2 in read(os.path.join(LOG, "zeus.md")) and any("предупреждение" in x for x in hook_lines("p-fmt2-next")),
      hook_lines("p-fmt2"))

# 10. Повторное событие с promptId самой записи queued (если Claude Code начнёт его слать) — без второй строки.
r = run({"session_id": "s-long", "transcript_path": os.path.join(home, "tr", "long.jsonl"),
         "hook_event_name": "UserPromptSubmit", "agent_type": "hq", "prompt": LONG, "prompt_id": "p-long-next"})
check("та же запись queued вторым событием → в подлиннике одна строка", read(os.path.join(LOG, "zeus.md")).count(LONG) == 1)

# 11. Тот же текст ещё раз во время хода, который сам вырос из записи queued: событие несёт promptId засчитанной
#     записи, её надо пропустить и дождаться новой.
AGAIN = "да, ещё раз"
scenario("again", AGAIN)
scenario("again", AGAIN, turn=False, turn_id="p-again-next", next_id="p-again-next2")
check("повтор того же текста во время хода из записи queued → вторая строка в подлиннике, не в unconfirmed",
      read(os.path.join(LOG, "zeus.md")).count(AGAIN) == 2 and AGAIN not in read(os.path.join(UNC, "zeus.md")),
      hook_lines("p-again"))

# 12–13. Запись дальше 2 МБ от хвоста: за время ожидания транскрипт вырос.
BIG = "очередь: после записи дописали 5 МБ"
scenario("big", BIG, grow=5000000)
check("запись queued, после которой транскрипт вырос на 5 МБ → в подлинник", BIG in read(os.path.join(LOG, "zeus.md")))
TYPED = "обычный ввод: после записи дописали 3 МБ"
tr = os.path.join(home, "tr", "typed.jsonl")
append(tr, {"type": "assistant", "isSidechain": False, "timestamp": iso(time.time() - 5),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "готово"}]}})
holder, before = {}, started_count()
ev = {"session_id": "s-typed", "transcript_path": tr, "hook_event_name": "UserPromptSubmit", "agent_type": "hq",
      "prompt": TYPED, "prompt_id": "p-typed"}
# срок ожидания записи — 30 с, а не 1 с общего BASE: под нагрузкой между запуском хука и записью теста проходят
# секунды. Исправный хук находит запись на ближайшем опросе (0,3 с) и выходит сразу; долго ждёт только сломанный
th = threading.Thread(target=lambda: holder.update(r=run(ev, PANTHEON_CONFIRM_WAIT="30")))
th.start()
went = wait_started(before)
with open(tr, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(user(TYPED, "p-typed", time.time()), ensure_ascii=False) + "\n" + filler(3000000))
th.join(150)
check("обычная запись ввода, после которой транскрипт вырос на 3 МБ → в подлинник",
      TYPED in read(os.path.join(LOG, "zeus.md")),
      "хук %s до записи; журнал хуков: %s" % ("дошёл до ожидания" if went else "не дошёл за 60 с",
                                             " | ".join(hook_lines("p-typed"))))

print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
