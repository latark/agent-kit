"""Ночной полный набор тестов на main (metis-1050, решение владельца 09.11): на PR — только затронутые тесты (CI или
узкая запись `--affected`, и у ядра, и у пачки), а полный набор раз в ночь гоняет плановый проход на свежем
origin/main. Слияния он не держит: красный — задача metis-pantheon на каждый упавший файл и тревога (её видно утром).

Тик основного Mac зовёт tick(t). Проверка — не чаще раза в CHECK_EVERY (10 мин) и только в часы NIGHT_HOURS по
местному времени; за ночь (дата начала окна) — один прогон на репозиторий. load выше порога (outside.load_state,
metis-0901) — пропуск, повтор на следующем тике той же ночи. Репозиторий — agent-kit из [merge_repos]
(merge.allowed_repos). Тот же sha main, что у прошлого ночного прогона, — не гоняется: код не менялся.

Код тестов исполняется только из своей копии на свежем origin/main (STATE/nightly/<имя>, класс metis-0902): её готовит
release_tick.prepare, чистоту сверяет release_tick.copy_clean. Рабочие копии владельца и ролей проход не трогает.

Работник — в своей группе процессов (тик не ждёт: набор идёт десятки минут): `heavy <python> -I run-tests.py -j 3
--log-dir <папка> <папки плагинов>` с таймаутом RUN_TIMEOUT, вывод — в STATE/nightly/<имя>-<дата>.log. Итог — в
STATE/nightly-tick.json (result), тик пишет его строкой `nightly-tick:` в logs/tick.log. Упавшие файлы — строки
раннера `FAIL <метка>`; файлы карантина (run-tests.py QUARANTINE) — строки `карантин <метка>`: они не дают задачи (у
каждого она уже есть), но называются в строке журнала и в тревоге — падения в карантине видны. На каждый упавший
файл не из карантина — задача «Ночной полный набор: <метка> красный на main», если открытой с тем же заголовком нет.
Красный набор или сбой (клон, код раннера без строки итога, таймаут) — тревога alert_once без critical, одна на
состояние; зелёный её снимает. PANTHEON_DRYRUN=1 (тесты тика) — ничего не делает.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

CHECK_EVERY = 10 * 60
NIGHT_HOURS = range(1, 7)  # 01:00–06:59 местного времени
RUN_TIMEOUT = 3 * 3600
DIED_GRACE = 120  # с: «running» без живого процесса дольше этого — работник погиб
RUNNER = os.path.join("plugins", "pantheon", "scripts", "run-tests.py")
PLUGIN_DIRS = ("plugins/guard", "plugins/pantheon", "plugins/project-tools")
REPO_NAMES = ("agent-kit",)
DIRECTION = "metis-pantheon"
ALERT_KEY = "nightly-tick"
WHO = "pantheon-tick"
FAIL_RE = re.compile(r"^FAIL ([\w.-]+/test_[\w.-]+\.py) ·", re.M)
QUAR_RE = re.compile(r"^карантин ([\w.-]+/test_[\w.-]+\.py) ·", re.M)
TOTAL_RE = re.compile(r"^итого: .*$", re.M)
TITLE = "Ночной полный набор: {label} красный на main"
CLOSED = ("done", "dropped", "cancelled")


def set_core(mod):
    global P
    P = mod


def state_file():
    return P.path("nightly-tick.json")


def repos():
    return sorted(r for r in P.merge_mod().allowed_repos() if r.rsplit("/", 1)[-1] in REPO_NAMES)


def night_of(t):
    """Дата ночи для метки t (строка YYYY-MM-DD) или None — сейчас не ночные часы."""
    d = datetime.fromtimestamp(t)
    return d.strftime("%Y-%m-%d") if d.hour in NIGHT_HOURS else None


def python():
    """Python для набора: 3.14, как в FULL_TESTS шлюза; нет его — тот, что у тика (раннер идёт на 3.11+)."""
    return shutil.which("python3.14") or sys.executable


def parse(out):
    """Вывод раннера → (упавшие метки, метки карантина, строка итога или None)."""
    total = TOTAL_RE.findall(out or "")
    return (sorted(set(FAIL_RE.findall(out or ""))), sorted(set(QUAR_RE.findall(out or ""))),
            total[-1].strip() if total else None)


# --- работник ----------------------------------------------------------------------------------------------------

def _patch_state(path, fn):
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    fn(st)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, path)


def work(job):
    """Работник: полный набор под heavy в копии → итог в состоянии. Зовётся из отдельного процесса (main ниже)."""
    st_path = job["state"]
    _patch_state(st_path, lambda st: st.setdefault("running", {}).update(pid=os.getpid()))
    argv = [*job["heavy"], job["python"], "-I", os.path.join(job["copy"], RUNNER), "-j", "3", "--log-dir",
            job["log"] + ".d", *PLUGIN_DIRS]
    code, out = None, ""
    try:
        with open(job["log"], "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(argv, cwd=job["copy"], env=dict(os.environ), stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=job.get("timeout", RUN_TIMEOUT))
            except subprocess.TimeoutExpired:
                _stop(proc)
        with open(job["log"], encoding="utf-8", errors="replace") as fh:
            out = fh.read()
    except OSError as e:
        out = f"не запустился: {type(e).__name__}: {e}"
    fails, quar, total = parse(out)
    res = {"sha": job["sha"], "repo": job["repo"], "night": job["night"], "code": code, "fails": fails,
           "quarantine": quar, "total": total, "log": job["log"], "t": time.time()}
    _patch_state(st_path, lambda st: (st.pop("running", None), st.update(result=res)))
    return 0


def _stop(proc):
    """Таймаут: TERM группе (раннер гасит свои файлы сам), 10 с, затем KILL."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def spawn(job):
    """Работник в своей группе процессов; тик его не ждёт. Тесты подменяют на прямой вызов work()."""
    log = os.path.join(os.path.dirname(job["state"]), "logs", "nightly-tick-worker.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), json.dumps(job)], stdin=subprocess.DEVNULL,
                         stdout=fh, stderr=fh, start_new_session=True, cwd=job["copy"],
                         env=P.release_tick_mod()._env())


# --- итог --------------------------------------------------------------------------------------------------------

def _open_titles():
    return {head.get("title"): tid for tid, (_, head, _) in P.tasks_mod().load_tasks(P.PANTHEON).items()
            if head.get("status") not in CLOSED}


def file_tasks(res):
    """Задача на каждый упавший файл не из карантина, если открытой с тем же заголовком нет → [id]."""
    if not res.get("fails"):
        return []
    try:
        have = _open_titles()
    except Exception:  # noqa: BLE001 — список задач не прочитать: лучше дубль, чем потерять красный файл
        have = {}
    out = []
    for label in res["fails"]:
        title = TITLE.format(label=label)
        if title in have:
            out.append(have[title])
            continue
        try:
            tid, _ = P.tasks_mod().task_new(
                P.PANTHEON, P.now(), DIRECTION, title, owner=DIRECTION, actor="плановый проход", priority=1,
                text=(f"Ночной полный набор ({res.get('night')}) на {res.get('repo')} main {str(res.get('sha'))[:12]} "
                      f"упал в файле {label}. Итог раннера: {res.get('total') or 'нет строки итога'}. Полный вывод — "
                      f"{res.get('log')}. Слияний это не держит (metis-1050); падает только под нагрузкой и зелёный "
                      "отдельно — в карантин run-tests.py (QUARANTINE) с этой задачей, иначе чинить."))
            out.append(tid)
        except Exception:  # noqa: BLE001 — карточку не завести: тревога всё равно назовёт файл
            continue
    return out


def summarize(res):
    """Итог работника → (строка журнала, текст тревоги или None)."""
    head = f"{res.get('repo')} {str(res.get('sha'))[:7]} ({res.get('night')})"
    quar = f"; карантин упал: {', '.join(res['quarantine'])}" if res.get("quarantine") else ""
    if res.get("code") is None:
        why = f"{head}: полный набор не завершился (таймаут или не запустился){quar}"
        return why, why
    if res.get("total") is None:
        why = f"{head}: раннер вышел с кодом {res.get('code')} без строки итога{quar}"
        return why, why
    if res.get("fails"):
        tids = file_tasks(res)
        why = (f"{head}: красный — {', '.join(res['fails'])}" + (f" (задачи {', '.join(tids)})" if tids else "")
               + quar + f"; {res['total']}")
        return why, why
    if res.get("code") not in (0, 4):
        why = f"{head}: код раннера {res.get('code')}{quar}; {res['total']}"
        return why, why
    return f"{head}: зелёный{quar}; {res['total']}", None


# --- тик ---------------------------------------------------------------------------------------------------------

def log(t, text):
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "tick.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{P.stamp(t)} nightly-tick: {' '.join(text.split())}\n")


def collect(t, st):
    """Итог прошлого работника → (строка, тревога или None) либо None; идущий работник — ("busy", None)."""
    run = st.get("running")
    if isinstance(run, dict):
        started = run.get("t") if isinstance(run.get("t"), (int, float)) else 0
        pid = run.get("pid")
        if pid is not None and P.pid_alive(pid):
            return "busy", None
        if pid is None and t - started < DIED_GRACE:
            return "busy", None
        st.pop("running", None)
        why = f"{run.get('repo')} {str(run.get('sha'))[:7]}: работник ночного набора погиб без итога"
        return why, why
    res = st.pop("result", None)
    if isinstance(res, dict):
        return summarize(res)
    return None


def check(repo, t, st, night):
    """Проверка репозитория → (итог, сбой или None, запуск был)."""
    RT = P.release_tick_mod()
    name = repo.rsplit("/", 1)[-1]
    copy = P.path("nightly", name)
    sha, err = RT.prepare(repo, copy)
    if err:
        return f"{repo}: {err}", err, False
    done = st.setdefault("done", {})
    if isinstance(done.get(repo), dict) and done[repo].get("sha") == sha:
        done[repo]["night"] = night
        return f"{repo}: main {sha[:7]} уже прогнан ночью — не гоняю", None, False
    ok, why = RT.copy_clean(copy, sha)
    if not ok:
        return f"{repo}: не запускаю — {why}", why, False
    job = {"repo": repo, "copy": copy, "sha": sha, "night": night, "state": state_file(), "python": python(),
           "heavy": [P.outside_mod().heavy_bin()], "log": P.path("nightly", f"{name}-{night}.log")}
    done[repo] = {"sha": sha, "night": night}
    st["running"] = {"t": t, "sha": sha, "repo": repo}
    P.write_json(state_file(), st)
    spawn(job)
    return f"{repo}: полный набор на {sha[:7]} запущен", None, True


def tick(t):
    """Проход тика: ночью, не чаще CHECK_EVERY, не под нагрузкой, раз за ночь. → итог или None (пропуск)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return None
    st = P.read_json(state_file(), {})
    got = collect(t, st)
    if got and got[0] == "busy":
        return None
    if got:
        text, fail = got
        P.write_json(state_file(), st)
        log(t, text)
        _alert(fail)
        return text
    night = night_of(t)
    if night is None:
        return None
    last = st.get("checked")
    if isinstance(last, (int, float)) and 0 <= t - last < CHECK_EVERY:
        return None
    todo = [r for r in repos() if not (isinstance(st.get("done", {}).get(r), dict)
                                       and st["done"][r].get("night") == night)]
    if not todo:
        return None
    load, limit = P.outside_mod().load_state()
    if load > limit:
        return None
    st["checked"] = t
    P.write_json(state_file(), st)
    texts, fails = [], []
    for repo in todo[:1]:  # по одному: второй репозиторий — следующим тиком, после итога первого
        text, fail, _ = check(repo, t, st, night)
        texts.append(text)
        if fail:
            fails.append(f"{repo}: {fail}")
    cur = P.read_json(state_file(), {})  # работник мог уже записать running/result — их не затираем
    cur["done"] = st.get("done", {})
    P.write_json(state_file(), cur)
    text = "; ".join(texts)
    log(t, text)
    if fails:
        _alert("; ".join(fails))
    return text


def _alert(fail):
    if fail:
        P.alert_once(ALERT_KEY, fail[:300], "ночной полный набор: " + fail[:300], WHO)
    else:
        P.clear_once(ALERT_KEY)


if __name__ == "__main__":
    sys.exit(work(json.loads(sys.argv[1])))
