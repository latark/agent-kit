#!/usr/bin/env python3
"""Уборка копий .claude/worktrees (metis-0835, metis-0616): дежурный (`pantheon watch`, lib/watch.py wt_one) и команда
`pantheon wt done|plan`.

Запуск: python3.14 -I plugins/pantheon/tests/test_wt_cleanup.py  (код выхода 0 — все прошли)
Обвязка (Env, поддельный claude, временные папки) — из test_watch.py: репозитории git только во временных папках,
настоящие .claude/worktrees не трогаются. Один тест — один пункт «Готово, когда» карточки metis-0835, плюс (а) команда
`pantheon wt done` и (б) пустая копия без суток.
"""
import json
import os
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_watch as W  # noqa: E402  — Env, T0, check; своя корневая временная папка и её уборка — там же

T0, check = W.T0, W.check
DAY = 86400


def repo(origin=None):
    """Направление g-dir с репозиторием git (ветка main, один коммит) → (Env, папка, g)."""
    e, folder, g = W._wt_repo("g-dir")
    open(os.path.join(folder, "base.txt"), "w").write("base\n")
    g("add", "base.txt")
    g("commit", "-q", "-m", "base")
    if origin:
        g("remote", "add", "origin", origin)
    return e, folder, g


def copy(folder, g, name, *, detached=False):
    wt = os.path.join(folder, ".claude", "worktrees", name)
    if detached:
        g("worktree", "add", "-q", "--detach", wt)
    else:
        g("worktree", "add", "-q", "-b", name, wt)
    return os.path.realpath(wt)


def commit(g, wt, fname, text):
    open(os.path.join(wt, fname), "w").write(text)
    g("add", fname, cwd=wt)
    g("commit", "-q", "-m", fname, cwd=wt)


def age(wt, seconds):
    os.utime(wt, (T0 - seconds, T0 - seconds))


def branch_sha(g, name):
    r = g("rev-parse", "--verify", "-q", f"refs/heads/{name}")
    return r.stdout.strip() if r.returncode == 0 else None


def journal(e):
    d = e.st("wt-archive")
    out = ""
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.startswith("removed-"):
            out += open(os.path.join(d, n), encoding="utf-8").read()
    return out


def test_squash_merged_pr_cache():
    """Копия после squash-слияния: HEAD не предок main (в main — один общий коммит вместо двух), PR её ветки слит по
    кэшу gh → убрана через сутки, ветка осталась. Та же копия без строки в кэше — неслитая, ждёт WORKTREE_DAYS."""
    e, folder, g = repo(origin="https://github.com/o/r.git")
    sq = copy(folder, g, "feat-sq")
    other = copy(folder, g, "feat-other")
    for wt in (sq, other):
        commit(g, wt, "a.txt", "a\n")
        commit(g, wt, "b.txt", "b\n")
    open(os.path.join(folder, "a.txt"), "w").write("a\n")
    open(os.path.join(folder, "b.txt"), "w").write("b\n")
    g("add", "a.txt", "b.txt")
    g("commit", "-q", "-m", "squash: a и b")
    check(g("merge-base", "--is-ancestor", "feat-sq", "main").returncode != 0, "squash: HEAD копии — предок main")
    check(any(ln.startswith("+") for ln in g("cherry", "main", "feat-sq").stdout.splitlines()),
          "squash: git cherry сам признал слитой — тест не про кэш PR")
    json.dump({"fetched": T0, "merged": {"O/R": [{"number": 7, "headRefName": "feat-sq"}]}},
              open(e.st("autoclose-prs.json"), "w"))
    for wt in (sq, other):
        age(wt, 2 * DAY)
    r = e.run("watch", t=T0)
    check(r.returncode == 0, f"squash: watch упал: {r.stderr[-300:]}")
    check(not os.path.exists(sq), "squash: копия со слитым PR (кэш) не убрана через сутки")
    check(branch_sha(g, "feat-sq") is not None, "squash: ветка слитой копии удалена")
    check(os.path.exists(other), "squash: копия без слитого PR (2 дн.) убрана раньше WORKTREE_DAYS")
    check("feat-sq" in journal(e) and "PR слит" in journal(e), f"squash: нет строки в журнале: {journal(e)!r}")
    check("уборка копий: убрано 1" in e.alerts(), f"squash: нет сводки: {e.alerts()[-300:]}")


def sub_meta(e, agent, wt, mtime, finished=False):
    d = os.path.join(e.home, ".claude", "projects", "-proj", "11111111-2222-4333-8444-555555555555", "subagents")
    os.makedirs(d, exist_ok=True)
    meta = {"agentType": "dev", "worktreePath": wt}
    if finished:
        meta["finished"] = True
    p = os.path.join(d, agent + ".meta.json")
    json.dump(meta, open(p, "w"))
    open(p[:-len(".meta.json")] + ".jsonl", "w").write("{}\n")
    for f in (p, p[:-len(".meta.json")] + ".jsonl"):
        os.utime(f, (mtime, mtime))


def test_agent_lock():
    """Замок «claude agent agent-<id> (pid P)» без живой сессии в cwd и старше порога — снимается, копия убрана; замок с
    другой причиной — копия цела и тревога; замок субагента, который ещё пишет журнал, — копия цела."""
    e, folder, g = repo()
    dead = copy(folder, g, "agent-a0aa11bb22cc33dd")
    hold = copy(folder, g, "w-hold")
    live = copy(folder, g, "agent-a0bb22cc33dd44ee")
    young = copy(folder, g, "agent-a0cc33dd44ee55ff")
    g("worktree", "lock", "--reason", "claude agent agent-a0aa11bb22cc33dd (pid 99999 start Thu Nov  5 17:57:45 2026)", dead)
    g("worktree", "lock", "--reason", "держу руками", hold)
    g("worktree", "lock", "--reason", "claude agent agent-a0bb22cc33dd44ee (pid 99999 start x)", live)
    g("worktree", "lock", "--reason", "claude agent agent-a0cc33dd44ee55ff (pid 99999 start x)", young)
    sub_meta(e, "agent-a0aa11bb22cc33dd", dead, T0 - 5 * 3600, finished=True)
    sub_meta(e, "agent-a0bb22cc33dd44ee", live, T0 - 60)
    for wt in (dead, live):
        age(wt, 2 * 3600)
    age(hold, 10 * DAY)
    age(young, 60)
    e.run("watch", t=T0)
    check(not os.path.exists(dead), "замок субагента: копия без живого субагента старше порога не убрана")
    check(os.path.exists(hold), "замок: копия с замком «держу руками» убрана")
    check("w-hold" in e.alerts() and "замок не субагента" in e.alerts(), f"замок: нет тревоги о чужом замке: {e.alerts()[-300:]}")
    check(os.path.exists(live), "замок субагента: копия живого субагента (журнал свежий) убрана")
    check(os.path.exists(young), "замок субагента: копия моложе порога убрана")
    check("agent-a0bb22cc33dd44ee" not in e.alerts(), "живой субагент попал в тревоги")


def test_detached_unmerged():
    """Неслитая detached копия старше WORKTREE_DAYS: сначала ветка archive/wt-<имя> на её HEAD, потом копия убрана."""
    e, folder, g = repo()
    wt = copy(folder, g, "w-det", detached=True)
    commit(g, wt, "work.txt", "работа\n")
    head = g("rev-parse", "HEAD", cwd=wt).stdout.strip()
    br = copy(folder, g, "w-unmerged")
    commit(g, br, "work.txt", "работа 2\n")
    for w in (wt, br):
        age(w, 4 * DAY)
    e.run("watch", t=T0)
    check(branch_sha(g, "archive/wt-w-det") == head, f"detached: нет ветки archive/wt-w-det на {head[:8]}")
    check(not os.path.exists(wt), "detached: неслитая копия старше срока не убрана")
    check(not os.path.exists(br) and branch_sha(g, "w-unmerged") is not None,
          "неслитая с веткой: копия не убрана или ветка удалена")
    # detached, чей HEAD уже на ветке origin, — слитая: через сутки и без archive/wt-<имя> (коммиты на origin)
    pushed = copy(folder, g, "w-pushed", detached=True)
    commit(g, pushed, "pushed.txt", "на origin\n")
    g("update-ref", "refs/remotes/origin/feat-p", g("rev-parse", "HEAD", cwd=pushed).stdout.strip())
    age(pushed, 2 * DAY)
    e.run("watch", t=T0)
    check(not os.path.exists(pushed), "detached на origin: копия не убрана через сутки")
    check(branch_sha(g, "archive/wt-w-pushed") is None, "detached на origin: лишняя ветка archive/wt-w-pushed")


def test_dirty_patch_and_empty_patch():
    """Грязная старше WORKTREE_DAYS: правка в wt-archive/patches/<имя>.patch, копия убрана. Грязная, у которой
    сохранить нечего (неотслеживаемое — только node_modules, патч пуст) — копия цела и тревога."""
    e, folder, g = repo()
    dirty = copy(folder, g, "w-dirty")
    open(os.path.join(dirty, "base.txt"), "w").write("base\nправка не закоммичена\n")
    empty = copy(folder, g, "w-nothing")
    os.makedirs(os.path.join(empty, "node_modules", "x"))
    open(os.path.join(empty, "node_modules", "x", "index.js"), "w").write("1\n")
    check(g("status", "--porcelain", cwd=empty).stdout.strip() != "", "пустой патч: копия чистая для git")
    for w in (dirty, empty):
        age(w, 4 * DAY)
    e.run("watch", t=T0)
    patch = e.st("wt-archive", "patches", "w-dirty.patch")
    check(os.path.isfile(patch) and "правка не закоммичена" in open(patch, encoding="utf-8").read(),
          "грязная: нет патча с правкой в wt-archive/patches")
    check(not os.path.exists(dirty), "грязная: копия не убрана после патча")
    check(os.path.exists(os.path.join(empty, "node_modules", "x", "index.js")), "пустой патч: копия убрана")
    check("w-nothing" in e.alerts() and "сохранить нечего" in e.alerts(), f"пустой патч: нет тревоги: {e.alerts()[-300:]}")
    check(not os.path.exists(e.st("wt-archive", "patches", "w-nothing.patch")), "пустой патч: файл патча записан")


def test_untracked_tar_and_failure():
    """Неотслеживаемый файл грязной копии — в wt-archive/untracked/<имя>.tar.gz до удаления (node_modules — нет);
    архив не собрался (на месте папки untracked — файл) — копия цела, недописанный патч снят, тревога."""
    e, folder, g = repo()
    wt = copy(folder, g, "w-untr")
    os.makedirs(os.path.join(wt, "notes"))
    open(os.path.join(wt, "notes", "draft.txt"), "w").write("черновик\n")
    os.makedirs(os.path.join(wt, "node_modules"))
    open(os.path.join(wt, "node_modules", "big.js"), "w").write("x\n")
    age(wt, 4 * DAY)
    e.run("watch", t=T0)
    tar = e.st("wt-archive", "untracked", "w-untr.tar.gz")
    names = tarfile.open(tar).getnames() if os.path.isfile(tar) else []
    check("notes/draft.txt" in names, f"неотслеживаемое: нет notes/draft.txt в архиве: {names}")
    check(not any("node_modules" in n for n in names), f"неотслеживаемое: node_modules в архиве: {names}")
    check(not os.path.exists(wt), "неотслеживаемое: копия не убрана после архива")
    # сбой архива
    e2, folder2, g2 = repo()
    wt2 = copy(folder2, g2, "w-fail")
    open(os.path.join(wt2, "draft.txt"), "w").write("черновик\n")
    open(os.path.join(wt2, "base.txt"), "w").write("правка\n")
    os.makedirs(e2.st("wt-archive"), exist_ok=True)
    open(e2.st("wt-archive", "untracked"), "w").write("не папка")
    age(wt2, 4 * DAY)
    e2.run("watch", t=T0)
    check(os.path.isfile(os.path.join(wt2, "draft.txt")), "сбой архива: копия убрана")
    check("w-fail" in e2.alerts() and "архив не собрался" in e2.alerts(), f"сбой архива: нет тревоги: {e2.alerts()[-300:]}")
    check(not os.path.exists(e2.st("wt-archive", "patches", "w-fail.patch")), "сбой архива: недописанный патч остался")


def test_live_session_never_touched():
    """Живая сессия в копии (cwd сессии с процессом или процесс с текущей папкой в ней) — копия цела в любом случае:
    пустая, грязная старше срока, с замком субагента, по заявке `pantheon wt done`."""
    e, folder, g = repo()
    names = ("w-empty", "w-dirty", "agent-a0dd44ee55ff6600", "w-req", "w-proc")
    wts = {n: copy(folder, g, n) for n in names}
    open(os.path.join(wts["w-dirty"], "base.txt"), "w").write("правка\n")
    g("worktree", "lock", "--reason", "claude agent agent-a0dd44ee55ff6600 (pid 99999 x)", wts["agent-a0dd44ee55ff6600"])
    e.agents([{"id": f"live{i:04d}", "sessionId": f"live{i:04d}-x", "name": f"s{i}", "state": "working",
               "pid": os.getpid(), "kind": "background", "cwd": os.path.join(wts[n], "sub") if i == 1 else wts[n],
               "startedAt": (T0 - 100) * 1000} for i, n in enumerate(names[:4])])
    os.makedirs(e.st("wt-req"), exist_ok=True)
    json.dump({"path": wts["w-req"], "time": T0}, open(e.st("wt-req", "0123456789abcdef.json"), "w"))
    proc = subprocess.Popen(["sleep", "60"], cwd=wts["w-proc"])
    try:
        for w in wts.values():
            age(w, 10 * DAY)
        e.run("watch", t=T0)
        r = e.run("wt", "done", wts["w-empty"], t=T0)
    finally:
        proc.kill()
        proc.wait()
    for n, w in wts.items():
        check(os.path.isdir(w), f"живая сессия: копия {n} тронута")
    check(r.returncode == 0 and "занята" in r.stdout, f"wt done живой копии: {r.returncode} {r.stdout!r} {r.stderr!r}")
    check(os.path.exists(e.st("wt-req", "0123456789abcdef.json")), "живая сессия: заявка на занятую копию снята")
    check(not os.path.exists(e.st("wt-archive", "patches", "w-dirty.patch")), "живая сессия: патч записан")


def test_empty_copy_without_day():
    """(б) Пустая чистая копия (HEAD = main, своих коммитов нет) без сессии убирается через WORKTREE_EMPTY_MIN, а не
    через сутки; моложе — остаётся; копия, где Claude Code знает сессию без процесса (её поднимут), ждёт сутки."""
    e, folder, g = repo()
    old = copy(folder, g, "w-empty-old")
    young = copy(folder, g, "w-empty-young")
    known = copy(folder, g, "w-empty-known")
    e.agents([{"id": "stop0001", "sessionId": "stop0001-x", "name": "x", "state": "stopped", "kind": "background",
               "cwd": known, "startedAt": (T0 - 9000) * 1000}])
    age(old, 3600)
    age(known, 3600)
    age(young, 10 * 60)
    e.run("watch", t=T0)
    check(not os.path.exists(old), "пустая копия часового возраста не убрана (ждёт сутки?)")
    check(branch_sha(g, "w-empty-old") is None, "пустая копия: слитая ветка не снята branch -d")
    check(os.path.exists(young), "пустая копия моложе WORKTREE_EMPTY_MIN убрана")
    check(os.path.exists(known), "пустая копия с остановленной сессией Claude Code убрана раньше суток")


def test_wt_done_command():
    """(а) `pantheon wt done <путь>`: свежая чистая копия — сразу (без сроков), строка в журнале; грязная свежая —
    сначала патч; не копия .claude/worktrees — код 2; plan — ничего не меняет. В окне роли (PANTHEON_TMP) — заявка в
    кэш окна, копия цела; проход исполняет заявку своего окна, а заявку чужого окна снимает, не трогая копию."""
    e, folder, g = repo()
    plain = copy(folder, g, "w-plain")
    commit(g, plain, "x.txt", "своя работа\n")
    dirty = copy(folder, g, "w-dirty")
    open(os.path.join(dirty, "base.txt"), "w").write("правка\n")
    other = os.path.join(e.tmp, "outside-copy")
    g("worktree", "add", "-q", "-b", "o-1", other)
    r = e.run("wt", "plan", folder, t=T0)
    check(r.returncode == 0 and "w-plain" in r.stdout and os.path.isdir(plain), f"plan: {r.stdout!r} {r.stderr!r}")
    r = e.run("wt", "done", plain, "--dry-run", t=T0)
    check(r.returncode == 0 and "убрал бы" in r.stdout and os.path.isdir(plain), f"done --dry-run: {r.stdout!r}")
    r = e.run("wt", "done", plain, t=T0)
    check(r.returncode == 0 and not os.path.exists(plain), f"wt done: свежая копия не убрана: {r.stdout!r} {r.stderr!r}")
    check(branch_sha(g, "w-plain") is not None, "wt done: ветка неслитой копии удалена")
    check("w-plain" in journal(e), "wt done: нет строки в журнале")
    r = e.run("wt", "done", dirty, t=T0)
    check(r.returncode == 0 and not os.path.exists(dirty) and os.path.isfile(e.st("wt-archive", "patches", "w-dirty.patch")),
          f"wt done: грязная копия без патча или не убрана: {r.stdout!r} {r.stderr!r}")
    r = e.run("wt", "done", other, t=T0)
    check(r.returncode == 2 and os.path.isdir(other), f"wt done вне .claude/worktrees: код {r.returncode}")
    r = e.run("wt", "done", t=T0)
    check(r.returncode == 2, f"wt done без пути: код {r.returncode}")
    # окно роли: заявка в кэш окна
    win = copy(folder, g, "w-win")
    foreign = copy(folder, g, "w-foreign")
    cache = os.path.join(e.home, "Library", "Caches", "pantheon-sandbox")
    for n, w in (("g-dir", win), ("zz-other", foreign)):
        os.makedirs(os.path.join(cache, n, "tmp"), exist_ok=True)
        r = e.run("wt", "done", w, t=T0, extra={"PANTHEON_TMP": os.path.join(cache, n, "tmp")})
        check(r.returncode == 0 and "заявка принята" in r.stdout and os.path.isdir(w),
              f"окно {n}: заявка не принята или копия тронута: {r.stdout!r} {r.stderr!r}")
        check(len(os.listdir(os.path.join(cache, n, "wt-req"))) == 1, f"окно {n}: нет файла заявки")
    e.run("watch", t=T0)
    check(not os.path.exists(win), "заявка окна направления не исполнена проходом")
    check(os.path.isdir(foreign), "заявка чужого окна исполнена")
    check(os.listdir(os.path.join(cache, "zz-other", "wt-req")) == [], "заявка чужого окна не снята")
    check(os.listdir(os.path.join(cache, "g-dir", "wt-req")) == [], "исполненная заявка не снята")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            W.FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
            print("ОШИБКА:", fn.__name__, type(ex).__name__, ex)
    print(f"тестов: {len(tests)}, не прошло: {len(W.FAILS)}")
    sys.exit(1 if W.FAILS else 0)
