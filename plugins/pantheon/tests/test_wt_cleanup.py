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
    """Состарить копию целиком: уборка смотрит не только mtime папки, но и свежие правки внутри (metis-0835, D1)."""
    age_all(wt, seconds)


def age_all(wt, seconds, keep=()):
    """Состарить всё в копии (файлы и папки, без перехода по ссылкам), кроме имён keep, затем саму копию."""
    when = T0 - seconds
    for d, dirs, files in os.walk(wt, topdown=False):
        for n in files + dirs:
            if n not in keep:
                os.utime(os.path.join(d, n), (when, when), follow_symlinks=False)
    os.utime(wt, (when, when))


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
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(meta, open(p, "w"))
    open(p[:-len(".meta.json")] + ".jsonl", "w").write("{}\n")
    for f in (p, p[:-len(".meta.json")] + ".jsonl"):
        os.utime(f, (mtime, mtime))


def test_agent_lock():
    """Lock «claude agent agent-<id> (pid P)» без живой сессии в cwd и старше порога — снимается, копия убрана; lock с
    другой причиной — копия цела и тревога; lock субагента, который ещё пишет журнал, — копия цела."""
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
        age(wt, 4 * 3600)
    age(hold, 10 * DAY)
    age(young, 60)
    e.run("watch", t=T0)
    check(not os.path.exists(dead), "lock субагента: копия без живого субагента старше порога не убрана")
    check(os.path.exists(hold), "lock: копия с lock «держу руками» убрана")
    check("w-hold" in e.alerts() and "lock не субагента" in e.alerts(), f"lock: нет тревоги о чужом lock: {e.alerts()[-300:]}")
    check(os.path.exists(live), "lock субагента: копия живого субагента (журнал свежий) убрана")
    check(os.path.exists(young), "lock субагента: копия моложе порога убрана")
    check("agent-a0bb22cc33dd44ee" not in e.alerts(), "живой субагент попал в тревоги")
    # meta субагента лежит глубже (subagents/<x>/) — тоже найден: живой субагент держит копию
    nested = copy(folder, g, "agent-a0ee55ff66007711")
    g("worktree", "lock", "--reason", "claude agent agent-a0ee55ff66007711 (pid 99999 x)", nested)
    sub_meta(e, "x/agent-a0ee55ff66007711", nested, T0 - 60)
    # lock называет субагента, а meta нет: копия держится, пока в ней есть правка моложе LIVE_SUBAGENT_MAX (3 ч)
    fresh = copy(folder, g, "agent-a0ff66007711aa22")
    quiet = copy(folder, g, "agent-a0aa77118822bb33")
    for wt in (fresh, quiet):
        g("worktree", "lock", "--reason", f"claude agent {os.path.basename(wt)} (pid 99999 x)", wt)
        open(os.path.join(wt, "notes.txt"), "w").write("x\n")
        os.utime(os.path.join(wt, "notes.txt"), (T0 - 4 * DAY, T0 - 4 * DAY))
    open(os.path.join(fresh, "draft.txt"), "w").write("свежее\n")
    os.utime(os.path.join(fresh, "draft.txt"), (T0 - 600, T0 - 600))
    os.remove(os.path.join(quiet, "notes.txt"))
    for wt in (nested, fresh, quiet):
        age_all(wt, 4 * DAY, keep=("draft.txt",))
    e.run("watch", t=T0)
    check(os.path.exists(nested), "lock субагента: meta во вложенной папке не найден — живая копия убрана")
    check(os.path.exists(fresh), "lock субагента без meta: копия со свежей правкой убрана")
    check(not os.path.exists(quiet), "lock субагента без meta: затихшая копия (всё старше 3 ч) не убрана")


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
    links = copy(folder, g, "w-links")  # неотслеживаемое — только ссылка внутрь копии: архив был бы пуст
    os.symlink("base.txt", os.path.join(links, "alias.txt"))
    for w in (dirty, empty, links):
        age(w, 4 * DAY)
    e.run("watch", t=T0)
    check(os.path.islink(os.path.join(links, "alias.txt")), "только ссылки: копия убрана, а сохранено ничего")
    check("w-links" in e.alerts(), f"только ссылки: нет тревоги: {e.alerts()[-300:]}")
    check(not os.path.exists(e.st("wt-archive", "untracked", "w-links.tar.gz")), "только ссылки: пустой архив остался")
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
    # ссылки внутрь копии (наружу — копию держит outward_links) и канал: в архив идут только обычные файлы
    os.symlink("base.txt", os.path.join(wt, "link.txt"))
    os.symlink("../base.txt", os.path.join(wt, "notes", "inner-link.txt"))
    os.mkfifo(os.path.join(wt, "notes", "pipe"))
    age(wt, 4 * DAY)
    e.run("watch", t=T0)
    tar = e.st("wt-archive", "untracked", "w-untr.tar.gz")
    names = tarfile.open(tar).getnames() if os.path.isfile(tar) else []
    check("notes/draft.txt" in names, f"неотслеживаемое: нет notes/draft.txt в архиве: {names}")
    check(not any("node_modules" in n for n in names), f"неотслеживаемое: node_modules в архиве: {names}")
    check(not any(n.endswith(("link.txt", "pipe")) for n in names), f"неотслеживаемое: ссылка или канал в архиве: {names}")
    blob = b"".join(tarfile.open(tar).extractfile(m).read() for m in tarfile.open(tar).getmembers() if m.isfile()) \
        if os.path.isfile(tar) else b""
    members = tarfile.open(tar).getmembers() if os.path.isfile(tar) else []
    check(members and all(m.isfile() for m in members), f"неотслеживаемое: не только обычные файлы: {[(m.name, m.type) for m in members]}")
    check(blob == "черновик\n".encode(), f"неотслеживаемое: содержимое архива {blob!r}")
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


def test_tar_regular_only():
    """_tar_regular (lib/watch.py) кладёт в архив только обычный файл, прочитанный без перехода по ссылке: ссылка и
    канал (git их в список неотслеживаемого не всегда даёт, но файл могут подменить между списком и чтением) — пропуск,
    размер — по прочитанному, больше остатка предела — _TooBig."""
    import io
    import tempfile
    sys.path.insert(0, os.path.join(W.ROOT, "lib"))
    import watch  # noqa: E402 — модуль без ядра: _tar_regular не трогает P
    d = tempfile.mkdtemp()
    reg, fifo, link = (os.path.join(d, n) for n in ("reg.txt", "pipe", "link.txt"))
    open(reg, "w").write("12345")
    os.mkfifo(fifo)
    os.symlink(reg, link)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        got = [watch._tar_regular(tf, p, os.path.basename(p), 100) for p in (reg, fifo, link)]
        names = [m.name for m in tf.getmembers()]
    check(got == [5, 0, 0] and names == ["reg.txt"], f"_tar_regular: прочитано {got}, в архиве {names}")
    with tarfile.open(fileobj=io.BytesIO(), mode="w") as tf:
        try:
            watch._tar_regular(tf, reg, "reg.txt", 4)
            check(False, "_tar_regular: файл больше остатка предела принят")
        except watch._TooBig:
            pass


def test_live_session_never_touched():
    """Живая сессия в копии (cwd сессии с процессом или процесс с текущей папкой в ней) — копия цела в любом случае:
    пустая, грязная старше срока, с lock субагента, по заявке `pantheon wt done`."""
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
    """(б) Пустая чистая копия (HEAD = main, своих коммитов нет) без сессии убирается через LIVE_SUBAGENT_MAX (3 ч без
    правок), а не через сутки; моложе — остаётся; копия, где Claude Code знает сессию без процесса (её поднимут), ждёт
    сутки."""
    e, folder, g = repo()
    old = copy(folder, g, "w-empty-old")
    young = copy(folder, g, "w-empty-young")
    known = copy(folder, g, "w-empty-known")
    e.agents([{"id": "stop0001", "sessionId": "stop0001-x", "name": "x", "state": "stopped", "kind": "background",
               "cwd": known, "startedAt": (T0 - 9000) * 1000}])
    age(old, 4 * 3600)
    age(known, 4 * 3600)
    age(young, 10 * 60)
    e.run("watch", t=T0)
    check(not os.path.exists(old), "пустая копия 4 ч без правок не убрана (ждёт сутки?)")
    check(branch_sha(g, "w-empty-old") is None, "пустая копия: слитая ветка не снята branch -d")
    check(os.path.exists(young), "пустая копия моложе LIVE_SUBAGENT_MAX убрана")
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
    for w in (plain, dirty):
        age(w, 3600)
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
    for w in (win, foreign):
        age(w, 3600)
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
    # папка заявок окна подменена ссылкой на чужую папку: её файлы проход не читает и не удаляет
    other_dir = os.path.join(e.tmp, "not-requests")
    os.makedirs(other_dir)
    junk = os.path.join(other_dir, "0123456789abcdef.json")
    open(junk, "w").write("{}")
    os.makedirs(os.path.join(cache, "g-link"))
    os.symlink(other_dir, os.path.join(cache, "g-link", "wt-req"))
    e.run("watch", t=T0)
    check(os.path.isfile(junk), "заявки: файл в папке за ссылкой wt-req удалён")


def fresh(wt, fname, seconds, text="правка\n"):
    """Файл копии с правкой seconds назад (по часам T0); папка, где он лежит, — тоже (новый файл меняет её mtime)."""
    p = os.path.join(wt, fname)
    open(p, "w").write(text)
    for q in (p, os.path.dirname(p)):
        os.utime(q, (T0 - seconds, T0 - seconds))


def test_fresh_change_keeps_copy():
    """D1 (metis-0835): живую работу, которую не видно по cwd, lsof и meta (сессия сделала cd в копию, субагент без
    worktreePath в meta), выдают свежие правки. Дежурный: копия, которой по сроку пора (4 дн.), но в ней правка
    моложе LIVE_SUBAGENT_MAX (3 ч), — цела, без патча и тревоги; та же правка старше 3 ч — копия убрана. `wt done`:
    правка 2 мин назад — копия цела, заявка оставлена; правка старше WT_DONE_QUIET (10 мин) — убрана сразу."""
    e, folder, g = repo()
    busy = copy(folder, g, "w-busy")
    calm = copy(folder, g, "w-calm")
    for w in (busy, calm):
        age(w, 4 * DAY)
    fresh(busy, "base.txt", 3600)          # грязная, правка час назад
    fresh(calm, "base.txt", 4 * 3600)      # грязная, правка 4 ч назад
    os.utime(busy, (T0 - 4 * DAY, T0 - 4 * DAY))
    os.utime(calm, (T0 - 4 * DAY, T0 - 4 * DAY))
    e.run("watch", t=T0)
    check(os.path.isfile(os.path.join(busy, "base.txt")), "D1 проход: копия со свежей правкой (1 ч) убрана")
    check(not os.path.exists(e.st("wt-archive", "patches", "w-busy.patch")), "D1 проход: патч занятой копии записан")
    check("w-busy" not in e.alerts(), "D1 проход: занятая копия попала в тревоги")
    check(not os.path.exists(calm), "D1 проход: копия с правкой старше 3 ч не убрана")
    # wt done: короткое окно
    now = copy(folder, g, "w-now")
    later = copy(folder, g, "w-later")
    for w in (now, later):
        age(w, 3600)
    fresh(now, "draft.txt", 120)
    fresh(later, "draft.txt", 20 * 60)
    r = e.run("wt", "done", now, t=T0)
    check(r.returncode == 0 and "занята" in r.stdout and "правки моложе 10 мин" in r.stdout and os.path.isdir(now),
          f"D1 wt done: копия с правкой 2 мин назад: {r.returncode} {r.stdout!r} {r.stderr!r}")
    check(len(os.listdir(e.st("wt-req"))) == 1, "D1 wt done: заявка на занятую копию не оставлена")
    r = e.run("wt", "done", later, t=T0)
    check(r.returncode == 0 and not os.path.exists(later), f"D1 wt done: правка 20 мин назад, копия не убрана: {r.stdout!r} {r.stderr!r}")


def ignore_repo():
    """Репозиторий, где .gitignore закоммичен: .env.local, сборка и зависимости игнорируются."""
    e, folder, g = repo()
    open(os.path.join(folder, ".gitignore"), "w").write(".env.local\nconfig/\ndist/\nnode_modules/\n*.bin\nlogs/\n")
    g("add", ".gitignore")
    g("commit", "-q", "-m", "gitignore")
    return e, folder, g


def test_ignored_files_saved():
    """D2 (metis-0835): игнорируемое (.gitignore) вне зависимостей и сборки — .env.local, целиком игнорируемая папка
    config/ — идёт в архив копии и у чистой копии; dist/ и node_modules/ — нет. Игнорируемого больше предела (по
    байтам или числу файлов) — копия цела, тревога."""
    e, folder, g = ignore_repo()
    wt = copy(folder, g, "w-env")
    open(os.path.join(wt, ".env.local"), "w").write("SECRET=1\n")
    os.makedirs(os.path.join(wt, "config"))
    open(os.path.join(wt, "config", "local.json"), "w").write("{}\n")
    for d in ("dist", "node_modules"):
        os.makedirs(os.path.join(wt, d))
        open(os.path.join(wt, d, "x.js"), "w").write("1\n")
    check(g("status", "--porcelain", cwd=wt).stdout.strip() == "", "D2: копия с игнорируемым не чистая для git")
    big = copy(folder, g, "w-bigign")
    with open(os.path.join(big, "huge.bin"), "wb") as fh:
        fh.truncate(201 * 1024 * 1024)  # разреженный: места не занимает, размер больше UNTRACKED_MAX_MB
    many = copy(folder, g, "w-many")
    os.makedirs(os.path.join(many, "logs"))
    for i in range(2001):  # SAVE_MAX_FILES + 1, меньше WALK_LIMIT
        open(os.path.join(many, "logs", f"{i}.log"), "w").close()
    for w in (wt, big, many):
        age(w, 4 * 3600)
    e.run("watch", t=T0)
    tar = e.st("wt-archive", "untracked", "w-env.tar.gz")
    names = tarfile.open(tar).getnames() if os.path.isfile(tar) else []
    check(".env.local" in names and "config/local.json" in names, f"D2: .env.local или config/ не в архиве: {names}")
    check(not any(n.startswith(("dist", "node_modules")) for n in names), f"D2: сборка или зависимости в архиве: {names}")
    check(not os.path.exists(wt), "D2: чистая копия с .env.local не убрана после архива")
    check("w-env" in journal(e) and "w-env.tar.gz" in journal(e), f"D2: архив не в журнале: {journal(e)!r}")
    check(os.path.isfile(os.path.join(big, "huge.bin")), "D2: копия с игнорируемым больше 200 МБ убрана")
    check("w-bigign" in e.alerts() and "больше предела" in e.alerts(), f"D2: нет тревоги о пределе: {e.alerts()[-400:]}")
    check(not os.path.exists(e.st("wt-archive", "untracked", "w-bigign.tar.gz")), "D2: архив сверх предела записан")
    check(os.path.isdir(os.path.join(many, "logs")), "D2: копия с 2001 игнорируемым файлом убрана")
    check("w-many" in e.alerts() and "файлов больше" in e.alerts(), f"D2: нет тревоги о числе файлов: {e.alerts()[-400:]}")


def test_change_after_save_keeps_copy():
    """D4 (metis-0835): правка, легшая в копию после патча и архива (wt_save), — копия цела: перепроверка прямо перед
    `git worktree remove`; устаревший патч снят. Без правки та же копия убирается. В процессе: wt_save подменён."""
    import types
    sys.path.insert(0, os.path.join(W.ROOT, "lib"))
    import watch  # noqa: E402
    e, folder, g = repo()
    root = os.path.realpath(folder)

    def read_json(p, default=None):
        try:
            return json.load(open(p))
        except (OSError, ValueError):
            return {} if default is None else default

    saved_p, orig = watch.P, watch.wt_save
    watch.set_core(types.SimpleNamespace(HOME=e.home, path=lambda *a: e.st(*a), read_json=read_json))
    try:
        for name, late in (("w-race", True), ("w-norace", False)):
            wt = copy(folder, g, name)
            fresh(wt, "base.txt", 4 * DAY)
            age(wt, 4 * DAY)

            def racing(w, env, clean=False, late=late):
                res = orig(w, env, clean=clean)
                if late:
                    open(os.path.join(w, "late.txt"), "w").write("правка после патча\n")
                return res

            watch.wt_save = racing
            block = dict(watch._copies(root))[wt]
            verdict, text = watch.wt_one(root, wt, block, watch.WtCtx([], [], T0))
            if late:
                check(verdict == "live" and os.path.isfile(os.path.join(wt, "late.txt")),
                      f"D4: правка после патча, копия убрана: {verdict} {text}")
                check("правка во время уборки" in text, f"D4: причина не названа: {text}")
                check(not os.path.exists(e.st("wt-archive", "patches", name + ".patch")), "D4: устаревший патч не снят")
            else:
                check(verdict == "removed" and not os.path.exists(wt), f"D4: копия без поздней правки: {verdict} {text}")
    finally:
        watch.wt_save = orig
        watch.set_core(saved_p)


def test_lock_refused_does_nothing():
    """D5 (metis-0835): lock уборки (P.lock("worktrees")) не взят — проход не трогает ни одной копии. В процессе:
    P подменён, lock отдаёт False."""
    import contextlib
    import types
    sys.path.insert(0, os.path.join(W.ROOT, "lib"))
    import watch  # noqa: E402
    e, folder, g = repo()
    wt = copy(folder, g, "w-old-empty")
    age(wt, 4 * 3600)

    @contextlib.contextmanager
    def refused(name, block=True):
        yield False

    noop = lambda *a, **k: None  # noqa: E731
    saved_p = watch.P
    watch.set_core(types.SimpleNamespace(HOME=e.home, path=lambda *a: e.st(*a), read_json=lambda p, d=None: d or {},
                                         lock=refused, alert_once=noop, clear_once=noop, alert=noop))
    try:
        watch.worktrees([], [], {"g-dir": [folder]}, T0)
    finally:
        watch.set_core(saved_p)
    check(os.path.isdir(wt), "D5: lock уборки не взят, а копия убрана")


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
