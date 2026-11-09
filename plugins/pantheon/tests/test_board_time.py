#!/usr/bin/env python3
"""Время прохода доски (metis-0709). Под нагрузкой Mac (load 40–367) задание launchd с пределом 60 с убивалось по
таймауту (rc=124), а строки «доска-время» в 32 из 42 случаев не было: SIGTERM приходил, пока pantheon.py ещё
импортировался (обработчика нет), бюджет не проверялся внутри долгой части, строка шла в буфер stdout без flush.

Что проверяется:
  - строка «доска-время» с частями и итого, одна на проход;
  - занятая блокировка notify (зависшее уведомление, gh соседа) не держит проход дольше бюджета: код 0, без уведомлений;
  - SIGTERM (таймаут задания) в ожидании замка, в импорте и в медленной части «карточки» не теряет строку, «прервано в …»;
  - бюджет вышел внутри долгой части или импорта (жёсткий SIGALRM, бюджет + BOARD_HARD_GRACE): проход кончает сам
    до предела 60 с, код BUDGET_CUT (77);
  - run_job на коде 77: отпечаток входов skip_fp не пишется (тик не пропустит недоделанную доску), сбоем и
    тревогой это не считается;
  - бюджет считается с начала процесса (медленный импорт 2 с + быстрый проход: «итого» >= 2 с);
  - `pantheon board archive` ранний обработчик бюджета не получает: замок занят — код 1, не 77, без «доска-время»;
  - нечисловой PANTHEON_BOARD_BUDGET не роняет запуск.

Запуск: python3 -I plugins/pantheon/tests/test_board_time.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="btime-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


tmp = os.path.realpath(tempfile.mkdtemp(prefix="btime-test-"))
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions/metis-pantheon/tasks"))
os.makedirs(os.path.join(home, "inbox/tasks"))
os.makedirs(view)
os.makedirs(os.path.join(state, "locks"))
with open(os.path.join(home, "schedule.toml"), "w") as fh:
    fh.write('primary_host = "mac-a"\n')
ENV = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_FAKE_IDLE": "0", "PANTHEON_METRICS": "0"}
argv = [PY311, "-I", RUN_PY, "board"]


def line_of(out):
    ls = [x for x in out.splitlines() if x.startswith("доска-время:")]
    return ls[0] if len(ls) == 1 else None


# 1. обычный проход: одна строка с частями
p = subprocess.run(argv, env=ENV, capture_output=True, text=True, timeout=60)
ln = line_of(p.stdout)
check("проход: код 0 и одна строка «доска-время»", p.returncode == 0 and ln is not None,
      (p.returncode, p.stdout[-300:], p.stderr[-300:]))
check("в строке есть все части и итого",
      ln and all(w in ln for w in ("реестр ", "статусы ", "блокировка-notify ", "карточки ", "сводка ", "итого ")), ln)

# 2. блокировку notify держит чужой процесс: проход ждёт не дольше BOARD_NOTIFY_WAIT, кода 124 нет
src = open(CLI, encoding="utf-8").read()
wait = float(re.search(r"BOARD_NOTIFY_WAIT = ([0-9.]+)", src).group(1))
fh = open(os.path.join(state, "locks", "notify.lock"), "a")
fcntl.flock(fh, fcntl.LOCK_EX)
t0 = time.time()
p = subprocess.run(argv, env=dict(ENV, PANTHEON_BOARD_BUDGET="3"), capture_output=True, text=True, timeout=60)
dt = time.time() - t0
ln = line_of(p.stdout)
check("блокировка notify занята: код 0 за бюджет (3 с), а не за предел задания",
      p.returncode == 0 and dt < 3 + 15, (p.returncode, round(dt, 1), p.stderr[-300:]))
check("блокировка notify занята: строка времени называет пропуск уведомлений, карточки собраны",
      ln and "уведомления" in ln and "карточки " in ln and os.path.exists(os.path.join(state, "board.json")),
      (ln, os.listdir(state)))
check("бюджет вышел: сводка board-auto пропущена", ln and "сводка board-auto" in ln, ln)
check("ожидание замка ограничено бюджетом, а не BOARD_NOTIFY_WAIT", dt < wait, (dt, wait))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

# 3. SIGTERM в ожидании замка: строка времени всё равно есть, с пометкой «прервано в ...»
fh = open(os.path.join(state, "locks", "notify.lock"), "a")
fcntl.flock(fh, fcntl.LOCK_EX)
q = subprocess.Popen(argv, env=dict(ENV, PANTHEON_BOARD_BUDGET="60"), stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)
time.sleep(4)
q.send_signal(signal.SIGTERM)
out, err = q.communicate(timeout=30)
ln = line_of(out)
check("SIGTERM: строка времени с «прервано в «блокировка-notify»»", ln and "прервано в «блокировка-notify»" in ln,
      (ln, out[-200:], err[-200:]))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

# 4. искусственно медленные части и медленный импорт (металл под нагрузкой Mac, 07–08.11): проход кончает сам до
# предела задания 60 с, строка времени есть всегда (metis-0709). Драйвер запускает run.py как задание launchd.
DRV = os.path.join(tmp, "driver.py")
with open(DRV, "w", encoding="utf-8") as fh:
    fh.write("""import os, runpy, sys, time
mode, delay = sys.argv[1], float(sys.argv[2])
sys.argv = [sys.argv[3], "board"]
if mode == "import":  # импорт pantheon.py тянется долго
    class Slow:
        def find_spec(self, name, path=None, target=None):
            if name == "pantheon":
                time.sleep(delay)
    sys.meta_path.insert(0, Slow())
else:  # медленная часть «карточки»; SIGALRM обязан прервать её, а не ждать
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_t", sys.argv[0].replace("run.py", "pantheon.py"))
sys.path.insert(0, os.path.dirname(sys.argv[0]))
if mode == "cards":
    import pantheon
    T = pantheon.tasks_mod()
    T.board_sync = lambda *a, **k: time.sleep(delay)
    pantheon.tasks_mod = lambda: T
    pantheon.PROC_T0 = time.monotonic()
    sys.exit(pantheon.main(["board"]))
runpy.run_path(sys.argv[0], run_name="__main__")
""")
dargv = lambda mode, delay: [PY311, "-I", DRV, mode, str(delay), RUN_PY]

t0 = time.time()
p = subprocess.run(dargv("cards", 120), env=dict(ENV, PANTHEON_BOARD_BUDGET="3"), capture_output=True, text=True,
                   timeout=60)
dt = time.time() - t0
ln = line_of(p.stdout)
check("медленная «карточки» (120 с) при бюджете 3 с: прервана по бюджету, код 77, строка «прервано в «карточки»»",
      p.returncode == 77 and dt < 20 and ln and "прервано в «карточки»" in ln, (p.returncode, round(dt, 1), ln, p.stderr[-300:]))

t0 = time.time()
p = subprocess.run(dargv("import", 120), env=dict(ENV, PANTHEON_BOARD_BUDGET="3"), capture_output=True, text=True,
                   timeout=60)
dt = time.time() - t0
ln = line_of(p.stdout)
check("медленный импорт (120 с) при бюджете 3 с: кончает по бюджету с кодом 77 и строкой «прервано в «импорт pantheon.py»»",
      p.returncode == 77 and dt < 20 and ln and "прервано в «импорт pantheon.py»" in ln, (p.returncode, round(dt, 1), ln, p.stderr[-300:]))

q = subprocess.Popen(dargv("import", 120), env=dict(ENV, PANTHEON_BOARD_BUDGET="60"), stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)
time.sleep(3)
q.send_signal(signal.SIGTERM)
out, err = q.communicate(timeout=30)
ln = line_of(out)
check("SIGTERM до окончания импорта: строка времени есть, код 143",
      ln and "прервано в «импорт pantheon.py»" in ln and q.returncode == 143, (q.returncode, ln, err[-200:]))

q = subprocess.Popen(dargv("cards", 120), env=dict(ENV, PANTHEON_BOARD_BUDGET="60"), stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)
time.sleep(4)
q.send_signal(signal.SIGTERM)
out, err = q.communicate(timeout=30)
ln = line_of(out)
check("SIGTERM в медленной «карточки»: строка «прервано в «карточки»»", ln and "прервано в «карточки»" in ln, (ln, err[-200:]))

# нечисловой бюджет не роняет запуск
p = subprocess.run(argv, env=dict(ENV, PANTHEON_BOARD_BUDGET="abc"), capture_output=True, text=True, timeout=60)
check("PANTHEON_BOARD_BUDGET=abc: проход идёт с бюджетом по умолчанию", p.returncode == 0 and line_of(p.stdout), (p.returncode, p.stderr[-200:]))

# 5. run_job на коде 77 (бюджет): skip_fp не пишется, сбоя и тревоги нет; на коде 0 skip_fp пишется (контроль)
with open(os.path.join(home, "schedule.toml"), "a") as fh:
    fh.write('[[job]]\nname = "board"\ncommand = "pantheon board"\nevery = "tick"\n')
RJ = os.path.join(tmp, "runjob.py")
with open(RJ, "w", encoding="utf-8") as fh:
    fh.write("""import json, os, sys
sys.path.insert(0, os.path.dirname(sys.argv[1]))
import pantheon as P
rc = int(sys.argv[2])
class Fake:
    pid = 1
    returncode = rc
    def __init__(self, *a, **k): pass
    def communicate(self, timeout=None): return ("доска-время: x\\n", None)
import subprocess
subprocess.Popen = Fake
P.tick_fingerprint = lambda job: "fp-test"
P.run_job_rc = P.main(["run-job", "board"])
st = P.job_state("board")
print(json.dumps({"rc": P.run_job_rc, "skip_fp": st.get("skip_fp"), "fails": st.get("fails"), "last_rc": st.get("last_rc")}))
""")
def run_rj(rc):
    pr = subprocess.run([PY311, "-I", RJ, CLI, str(rc)], env=ENV, capture_output=True, text=True, timeout=60)
    try:
        return json.loads(pr.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"err": (pr.stdout[-200:], pr.stderr[-300:])}
r0 = run_rj(0)
check("контроль: run_job с кодом 0 пишет skip_fp", r0.get("skip_fp") == "fp-test", r0)
r77 = run_rj(77)
check("run_job с кодом 77 (бюджет доски): skip_fp нет, сбоев 0", r77.get("last_rc") == 77 and not r77.get("skip_fp")
      and r77.get("fails") == 0, r77)

# 6. бюджет считается от старта процесса (metis-0709, Б2): импорт 2 с + быстрый проход — «итого» не меньше 2 с.
# Режим import драйвера не трогает PROC_T0, его ставит run.py. Мутанты: PROC_T0 не задаётся; BoardClock без t0.
p = subprocess.run(dargv("import", 2), env=ENV, capture_output=True, text=True, timeout=60)
ln = line_of(p.stdout)
m = re.search(r"итого ([0-9.]+) с", ln or "")
check("импорт 2 с + быстрый проход: код 0, «итого» с начала процесса (>= 2 с)",
      p.returncode == 0 and m and float(m.group(1)) >= 2.0, (p.returncode, ln, p.stderr[-200:]))

# 7. board archive — не проход (metis-0709, Б1): ранний обработчик бюджета на него не ставится; замок board-git занят —
# как на base: код 1 за HQ_LOCK_WAIT, без «доска-время» и без кода 77 (иначе os._exit пропустил бы откат архива, metis-0810)
os.makedirs(os.path.join(state, "hq-rw", "locks"), exist_ok=True)
with open(os.path.join(home, "board.md"), "w", encoding="utf-8") as fh:
    fh.write("# Доска\n")
fh = open(os.path.join(state, "hq-rw", "locks", "board-git.lock"), "a")
fcntl.flock(fh, fcntl.LOCK_EX)
t0 = time.time()
p = subprocess.run([PY311, "-I", RUN_PY, "board", "archive"], env=dict(ENV, PANTHEON_BOARD_BUDGET="1", PANTHEON_HQ_LOCK_WAIT="9"),
                   capture_output=True, text=True, timeout=60)
dt = time.time() - t0
check("board archive при занятом замке (бюджет 1, ожидание 9 с): код 1, «повтори», без «доска-время» и без 77",
      p.returncode == 1 and "повтори" in p.stderr and "доска-время" not in p.stdout + p.stderr and dt >= 8,
      (p.returncode, round(dt, 1), p.stdout[-200:], p.stderr[-300:]))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
