"""Карта тестов не устаревает на main (metis-0842 п.2, metis-0692 п.1; решение владельца 08.11, вариант В): плановый
проход сам пересобирает affected-map.json частями (`affected-map.py --update`) и пушит отдельный коммит «карта: …» в
main — так же, как release_tick пушит выпуск.

Тик основного Mac зовёт tick(t). Проверка — не чаще раза в CHECK_EVERY (10 мин); load выше порога (outside.load_state,
metis-0901) — пропуск без проверки, повтор на следующем тике. Репозиторий — agent-kit из [merge_repos]. Код
affected-map.py исполняется только из своей копии на свежем origin/main (STATE/map/<имя>, класс metis-0902), готовится
тем же release_tick.prepare; рабочие копии владельца и ролей проход не трогает.

Условия запуска (все):
1. Выпуск не ждёт: после последнего коммита «выпуск: …» на первой родительской линии нет слияний. Слияние и выпуск
   идут первыми, карта — после них: два пуша в main не соревнуются, а карта строится по дереву с новой версией.
2. После последнего слияния карты ещё не было: идём по первой родительской линии от head, коммиты «выпуск: …» и «карта: …»
   не считаются; первое слияние раньше первой «карты» — нужна, первая «карта» раньше слияния — уже была. Это обрывает
   цикл: коммит карты меняет plugins/pantheon, release.py поднимает версию (plugin.json сдвигает sums), и без этого
   правила каждый выпуск звал бы новую карту, а каждая карта — новый выпуск.
3. `affected-map.py --check` на этой копии: код 1 — устарела; 0 — свежая, ничего; другой код — сбой, тревога.
Тогда в фоне (своя группа процессов; тик не ждёт — сборка идёт десятки минут) идёт работник: `heavy python3 -I
affected-map.py --update <папки плагинов>` с таймаутом UPDATE_TIMEOUT, затем проверка, что изменилась одна карта,
коммит «карта: affected-map на <sha7>» от pantheon-tick и обычный `git push origin HEAD:main`. main ушёл вперёд
(push отклонён) — не сбой: следующая проверка начнёт заново. Итог работника — STATE/map-tick.json (result), тик
пишет его строкой `map-tick:` в logs/tick.log; сбой — тревога alert_once без critical, удача её снимает.
Push в main этим процессом идёт вне окон ролей: хук push защиты (guard) на него не действует; ветка main должна
принимать push от входа gh владельца так же, как для release.py --push.
PANTHEON_DRYRUN=1 (тесты тика) — ничего не делает.
"""
import json
import os
import re
import subprocess
import sys
import time

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

CHECK_EVERY = 10 * 60
RELEASE_PREFIX = "выпуск: "
MAP_PREFIX = "карта: "
MAP_SCRIPT = os.path.join("plugins", "pantheon", "scripts", "affected-map.py")
MAP_REL = "plugins/pantheon/scripts/affected-map.json"
PLUGIN_DIRS = ("plugins/guard", "plugins/pantheon", "plugins/project-tools")
REPO_NAMES = ("agent-kit",)
LOG_DEPTH = 200
CHECK_TIMEOUT = 300
UPDATE_TIMEOUT = 3 * 3600
PUSH_TIMEOUT = 120
DIED_GRACE = 120     # с: «running» без живого процесса дольше этого — работник погиб
ALERT_KEY = "map-tick"
WHO = "pantheon-tick"


def set_core(mod):
    global P
    P = mod


def state_file():
    return P.path("map-tick.json")


def repos():
    return sorted(r for r in P.merge_mod().allowed_repos() if r.rsplit("/", 1)[-1] in REPO_NAMES)


def load_state():
    """(load, порог) — то же, что у ожидания полного набора (outside.load_state, metis-0901)."""
    return P.outside_mod().load_state()


def heavy_prefix():
    return [P.outside_mod().heavy_bin()]


def history_need(rows):
    """rows — [(sha, тема)] первой родительской линии от head → (нужна ли карта, почему). Условия 1 и 2."""
    subjects = [s for _, s in rows]
    rel = next((i for i, s in enumerate(subjects) if s.startswith(RELEASE_PREFIX)), None)
    if rel is None:
        return False, f"коммита «{RELEASE_PREFIX}…» нет в {LOG_DEPTH} последних"
    if any(not s.startswith(MAP_PREFIX) for s in subjects[:rel]):
        return False, "слияние ждёт выпуска"
    for s in subjects:
        if s.startswith(MAP_PREFIX):
            return False, "после последнего слияния карта уже обновлялась"
        if not s.startswith(RELEASE_PREFIX):
            return True, "после последней карты были слияния"
    return True, f"карты в {LOG_DEPTH} последних нет"


def first_parent_rows(RT, copy, sha):
    code, out = RT.git(copy, "log", "--first-parent", f"-n{LOG_DEPTH}", "--format=%H %s", sha)
    if code != 0:
        return None, f"git log: {out[-200:]}"
    return [tuple(ln.split(" ", 1)) if " " in ln else (ln, "") for ln in out.splitlines()], None


def map_stale(RT, copy):
    """Условие 3 → (True/False, текст) или (None, причина сбоя)."""
    try:
        r = subprocess.run([sys.executable, "-I", os.path.join(copy, MAP_SCRIPT), "--check", *PLUGIN_DIRS], cwd=copy,
                           capture_output=True, text=True, timeout=CHECK_TIMEOUT, env=RT._env(),
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"affected-map --check не запустился: {type(e).__name__}"
    lines = [ln for ln in (r.stdout + "\n" + r.stderr).splitlines() if ln.strip()]
    last = (lines[-1].strip() if lines else "")[:200]
    if r.returncode in (0, 1):
        return r.returncode == 1, last
    return None, f"affected-map --check код {r.returncode}: {last}"


# --- работник (отдельный процесс) --------------------------------------------------------------------------------

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


def _run(argv, cwd, env, timeout, keep=1):
    """→ (код, последняя строка вывода); не запустился или таймаут — (None, причина). Группа процессов гасится целиком."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, start_new_session=True)
    except OSError as e:
        return None, f"не запустился: {type(e).__name__}"
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return None, f"дольше {int(timeout)} с — остановлено"
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    return proc.returncode, " | ".join(ln.strip() for ln in lines[-keep:])[:400]


def _git(copy, env, *args, keep=1):
    return _run(["git", "-C", copy, *args], copy, env, PUSH_TIMEOUT, keep)


def _only_map_changed(copy, env):
    try:
        r = subprocess.run(["git", "-C", copy, "-c", "core.quotepath=off", "status", "--porcelain",
                            "--untracked-files=all"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return False, "git status не выполнился"
    rows = [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]
    if not rows:
        return False, "карта не изменилась"
    if rows != [MAP_REL]:
        return False, "--update тронул не только карту: " + ", ".join(rows[:5])
    return True, None


def publish(job, env):
    """Проверка, коммит и push → (итог, ok, сбой?) — итог строкой."""
    copy, sha = job["copy"], job["sha"]
    ok, why = _only_map_changed(copy, env)
    if not ok:
        return why, False
    for args in (("add", "--", MAP_REL),
                 ("-c", "user.name=pantheon-tick", "-c", "user.email=pantheon-tick@localhost", "commit", "-q", "-m",
                  f"{MAP_PREFIX}affected-map на {sha[:7]}")):
        code, last = _git(copy, env, *args)
        if code != 0:
            return f"git {args[0] if args[0] != '-c' else 'commit'}: {last}", False
    code, last = _git(copy, env, "push", "origin", "HEAD:main", keep=8)
    if code != 0:
        if re.search(r"rejected|non-fast-forward|fetch first", last):
            return f"main ушёл вперёд, push отклонён — повтор со следующей проверкой ({last})", None
        return f"git push код {code}: {last}", False
    return f"коммит карты на {sha[:7]} отправлен в main", True


def work(job):
    """Работник: update под heavy → publish → итог в состоянии. Зовётся из отдельного процесса (main ниже)."""
    st_path = job["state"]
    _patch_state(st_path, lambda st: st.setdefault("running", {}).update(pid=os.getpid()))
    env = {k: v for k, v in job["env"].items()}
    code, last = _run([*job["heavy"], sys.executable, "-I", os.path.join(job["copy"], MAP_SCRIPT), "--update",
                       *PLUGIN_DIRS], job["copy"], env, job.get("timeout", UPDATE_TIMEOUT))
    if code != 0:
        text, ok = f"affected-map --update на {job['sha'][:7]}: код {code}: {last}", False
    else:
        text, ok = publish(job, env)
    res = {"sha": job["sha"], "text": text, "ok": ok, "t": time.time()}
    _patch_state(st_path, lambda st: (st.pop("running", None), st.update(result=res)))
    return 0 if ok is not False else 1


def spawn(job):
    """Работник в своей группе процессов; тик его не ждёт. Тесты подменяют на прямой вызов work()."""
    log = os.path.join(os.path.dirname(job["state"]), "logs", "map-tick-worker.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), json.dumps(job)], stdin=subprocess.DEVNULL,
                         stdout=fh, stderr=fh, start_new_session=True, cwd=job["copy"])


# --- тик ---------------------------------------------------------------------------------------------------------

def log(t, text):
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "tick.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{P.stamp(t)} map-tick: {' '.join(text.split())}\n")


def collect(t, st):
    """Итог прошлого работника → (строка, сбой или None) либо None, если собирать нечего; идущий работник — ("busy")."""
    run = st.get("running")
    if isinstance(run, dict):
        started = run.get("t") if isinstance(run.get("t"), (int, float)) else 0
        pid = run.get("pid")
        if pid is not None and P.pid_alive(pid):
            return "busy", None
        if pid is None and t - started < DIED_GRACE:
            return "busy", None
        st.pop("running", None)
        return "работник карты погиб без итога", "работник карты погиб без итога"
    res = st.pop("result", None)
    if isinstance(res, dict):
        return res.get("text", "?"), (None if res.get("ok") is not False else res.get("text", "сбой"))
    return None


def check(repo, t, st):
    """Проверка репозитория → (итог, сбой или None, запуск работника был)."""
    RT = P.release_tick_mod()
    copy = P.path("map", repo.rsplit("/", 1)[-1])
    sha, err = RT.prepare(repo, copy)
    if err:
        return f"{repo}: {err}", err, False
    rows, err = first_parent_rows(RT, copy, sha)
    if err:
        return f"{repo}: {err}", err, False
    need, why = history_need(rows)
    if not need:
        return f"{repo}: не нужна — {why}", None, False
    ok, why = RT.copy_clean(copy, sha)
    if not ok:
        return f"{repo}: не запускаю — {why}", why, False
    stale, why = map_stale(RT, copy)
    if stale is None:
        return f"{repo}: {why}", why, False
    if not stale:
        return f"{repo}: карта свежая — {why}", None, False
    job = {"repo": repo, "copy": copy, "sha": sha, "state": state_file(), "heavy": heavy_prefix(), "env": RT._env()}
    st["running"] = {"t": t, "sha": sha}
    P.write_json(state_file(), st)
    spawn(job)
    return f"{repo}: карта устарела на {sha[:7]} ({why}) — обновление запущено", None, True


def tick(t):
    """Проход тика: не чаще CHECK_EVERY, не под нагрузкой, по одному репозиторию. → итог или None (пропуск)."""
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
    last = st.get("checked")
    if isinstance(last, (int, float)) and 0 <= t - last < CHECK_EVERY:
        return None
    todo = repos()
    if not todo:
        return None
    load, limit = load_state()
    if load > limit:
        return None
    st["checked"] = t
    P.write_json(state_file(), st)
    texts, fails, ran = [], [], False
    for repo in todo:
        text, fail, did = check(repo, t, st)
        texts.append(text)
        ran = ran or did
        if fail:
            fails.append(f"{repo}: {fail}")
    text = "; ".join(texts)
    if ran or text != st.get("last"):
        log(t, text)
    cur = P.read_json(state_file(), {})  # работник мог уже записать итог (running/result) — их не затираем
    cur["last"] = text
    P.write_json(state_file(), cur)
    _alert("; ".join(fails) if fails else None)
    return text


def _alert(fail):
    if fail:
        P.alert_once(ALERT_KEY, fail[:300], "карта тестов: " + fail[:300], WHO)
    else:
        P.clear_once(ALERT_KEY)


if __name__ == "__main__":
    sys.exit(work(json.loads(sys.argv[1])))
