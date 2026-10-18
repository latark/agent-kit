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

Тест красный на коде 0.11.45: строка не попадает в подлинник owner-log/zeus.md. Остальные проверки — ограждения для
будущей правки: чужой (peer) ввод и ввод с другим текстом подлинником стать не должны.

Запуск: python3 -I plugins/pantheon/tests/test_owner_log_gap.py  (0 — прошли; проверяется и на /usr/bin/python3)
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
        "PANTHEON_CONFIRM_WAIT": "1", "PANTHEON_QUEUED_WAIT": "6", "PANTHEON_REWAKE_DELAY": "0",
        "TZ": "Europe/Moscow"}


def run(ev):
    return subprocess.run([PY, "-I", HOOK, "owner-log"], input=json.dumps(ev), env=dict(BASE),
                          capture_output=True, text=True, timeout=60)


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


def scenario(name, text, kind="human", record_text=None):
    """Владелец пишет во время хода p-<name>-turn; ход кончается сам, ввод становится ходом p-<name>-next."""
    tr = os.path.join(home, "tr", name + ".jsonl")
    t = time.time()
    append(tr, user("ход идёт", "p-%s-turn" % name, t - 10))
    append(tr, {"type": "assistant", "isSidechain": False, "timestamp": iso(t - 5),
                "message": {"role": "assistant", "content": [{"type": "text", "text": "работаю"}]}})
    ev = {"session_id": "s-" + name, "transcript_path": tr, "hook_event_name": "UserPromptSubmit",
          "agent_type": "hq", "prompt": text, "prompt_id": "p-%s-turn" % name}  # promptId — у идущего хода
    holder = {}
    th = threading.Thread(target=lambda: holder.update(r=run(ev)))
    th.start()
    time.sleep(0.3)
    append(tr, queue_op("enqueue", time.time(), text))
    time.sleep(1.5)  # ход доходит до конца, не забрав ввод вложением
    for d in turn_end(time.time()):
        append(tr, d)
    append(tr, queue_op("dequeue", time.time()))
    append(tr, user(record_text or text, "p-%s-next" % name, time.time(), kind=kind, source="queued"))
    th.join(40)
    return holder.get("r")


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

print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
