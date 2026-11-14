#!/usr/bin/env python3
"""Дежурный, часть 6: уборка worktree, подкоманды тика, проверка инфраструктуры, кто есть кто (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_worktree_outside_and_prune_0118():
    """Копии вне .claude/worktrees: тревога после WORKTREE_DAYS, никогда не удаляются; запись без папки чистится."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    outside = os.path.join(e.tmp, "ak-outside")
    young = os.path.join(e.tmp, "ak-young")
    gone = os.path.join(e.tmp, "ak-gone")
    for n, w in (("o-old", outside), ("o-young", young), ("o-gone", gone)):
        g("worktree", "add", "-q", "-b", n, w)
    shutil.rmtree(gone)
    old = T0 - 4 * 86400
    os.utime(outside, (old, old))
    os.utime(young, (T0, T0))
    e.run("watch", t=T0)
    check(os.path.isdir(outside), "копия вне штатной папки убрана")
    a = e.alerts()
    check("вне штатной папки" in a and "ak-outside" in a, "нет тревоги о копии вне штатной папки")
    check("ak-young" not in a, "тревога о молодой копии вне папки")
    lst = g("worktree", "list", "--porcelain").stdout
    check("ak-gone" not in lst and "ak-outside" in lst and "ak-young" in lst, "запись без папки не вычищена")
    check(g("rev-parse", "--verify", "-q", "o-old").returncode == 0, "ветка копии вне папки удалена")


def test_worktree_prune_unreadable_0118():
    """Недоступная папка (EACCES) — не пропавшая: живая копия не теряет запись, prune откладывается и при другой
    пропавшей записи; когда доступ вернулся, prune чистит только пропавшую."""
    e, folder, g = _wt_repo("g-dir")
    wts = os.path.join(folder, ".claude", "worktrees")
    live_wt = os.path.join(wts, "w-live")
    g("worktree", "add", "-q", "-b", "w-live", live_wt)
    e.agents([{"id": "live0001", "sessionId": "live0001-x", "name": "w", "state": "working", "pid": os.getpid(),
               "kind": "background", "cwd": live_wt, "startedAt": (T0 - 100) * 1000}])
    ids = lambda: sorted(os.listdir(os.path.join(folder, ".git", "worktrees")))
    os.chmod(wts, 0o000)
    try:
        e.run("watch", t=T0)
        check("w-live" in ids(), "запись живой копии с недоступной папкой снята prune")
        check("недоступна" in e.alerts() and "prune отложен" in e.alerts(), "нет тревоги о недоступной записи")
    finally:
        os.chmod(wts, 0o755)
    check(os.path.exists(os.path.join(live_wt, ".git")), "копия повреждена")
    # недоступная копия без сессии + реально пропавшая запись: prune не делается
    e2, folder2, g2 = _wt_repo("g-dir")
    wts2 = os.path.join(folder2, ".claude", "worktrees")
    g2("worktree", "add", "-q", "-b", "w-noacc", os.path.join(wts2, "w-noacc"))
    gone = os.path.join(e2.tmp, "ak-gone2")
    g2("worktree", "add", "-q", "-b", "o-gone", gone)
    shutil.rmtree(gone)
    ids2 = lambda: sorted(os.listdir(os.path.join(folder2, ".git", "worktrees")))
    os.chmod(wts2, 0o000)
    try:
        e2.run("watch", t=T0)
        check(ids2() == ["ak-gone2", "w-noacc"], f"prune сработал при недоступной записи: {ids2()}")
    finally:
        os.chmod(wts2, 0o755)
    e2.run("watch", t=T0)
    check(ids2() == ["w-noacc"], f"после возврата доступа prune не убрал пропавшую: {ids2()}")
    # chmod 000 на саму копию (родитель читается): git видит <копия>/.git как «нет файла» — prune снёс бы обе записи
    e3, folder3, g3 = _wt_repo("g-dir")
    self_wt = os.path.join(folder3, ".claude", "worktrees", "w-self")
    g3("worktree", "add", "-q", "-b", "w-self", self_wt)
    gone3 = os.path.join(e3.tmp, "ak-gone3")
    g3("worktree", "add", "-q", "-b", "o-gone3", gone3)
    shutil.rmtree(gone3)
    ids3 = lambda: sorted(os.listdir(os.path.join(folder3, ".git", "worktrees")))
    os.chmod(self_wt, 0o000)
    try:
        e3.run("watch", t=T0)
        check(ids3() == ["ak-gone3", "w-self"], f"prune снял запись копии с chmod 000: {ids3()}")
        check("недоступна" in e3.alerts(), "нет тревоги о недоступной копии")
    finally:
        os.chmod(self_wt, 0o755)
    check(g3("status", "--porcelain", cwd=self_wt).returncode == 0, "копия сломана")
    e3.run("watch", t=T0)
    check(ids3() == ["w-self"], f"после возврата доступа prune не убрал пропавшую: {ids3()}")


def test_worktree_prune_alert_key_and_empty_gitdir_0118():
    """Тревога prune — со своим ключом (не склеивается с «забытой копией»); пустой gitdir — препятствие для prune."""
    # chmod 000 на копии старше WORKTREE_DAYS: второй проход не добавляет строк в alerts.md
    e, folder, g = _wt_repo("g-dir")
    wt = os.path.join(folder, ".claude", "worktrees", "w-old")
    g("worktree", "add", "-q", "-b", "w-old", wt)
    old = T0 - 10 * 86400
    os.utime(wt, (old, old))
    os.chmod(wt, 0o000)
    try:
        e.run("watch", t=T0)
        n1 = len(e.alerts().splitlines())
        check("prune отложен" in e.alerts(), "нет тревоги prune")
        e.run("watch", t=T0)
        n2 = len(e.alerts().splitlines())
        check(n2 == n1, f"второй проход добавил строки в alerts.md: {n1} -> {n2}")
    finally:
        os.chmod(wt, 0o755)
    # пустой gitdir + пропавшая запись: обе записи остаются, тревога есть
    e2, folder2, g2 = _wt_repo("g-dir")
    g2("worktree", "add", "-q", "-b", "w-empty", os.path.join(folder2, ".claude", "worktrees", "w-empty"))
    gone = os.path.join(e2.tmp, "ak-gone4")
    g2("worktree", "add", "-q", "-b", "o-gone4", gone)
    shutil.rmtree(gone)
    wd = os.path.join(folder2, ".git", "worktrees")
    open(os.path.join(wd, "w-empty", "gitdir"), "w").close()
    e2.run("watch", t=T0)
    check(sorted(os.listdir(wd)) == ["ak-gone4", "w-empty"], f"prune сработал при пустом gitdir: {sorted(os.listdir(wd))}")
    check("битая" in e2.alerts() and "prune отложен" in e2.alerts(), "нет тревоги о пустом gitdir")


def test_worktree_keeps_unmerged_and_untracked_0184():
    """metis-0184: уборка дежурным не удаляет копию с неслитым коммитом или неотслеживаемым файлом; контроль — слитая
    и чистая копия убирается (тест умеет удалять)."""
    e, folder, g = _wt_repo("g-dir")
    wts = os.path.join(folder, ".claude", "worktrees")
    path = {n: os.path.join(wts, n) for n in ("w-unpushed", "w-untracked", "w-clean")}
    for n, wt in path.items():
        g("worktree", "add", "-q", "-b", n, wt)
    open(os.path.join(path["w-unpushed"], "work.txt"), "w").write("работа\n")
    g("add", "work.txt", cwd=path["w-unpushed"])
    g("commit", "-q", "-m", "неотправленное", cwd=path["w-unpushed"])
    open(os.path.join(path["w-untracked"], "draft.txt"), "w").write("черновик\n")
    old = T0 - 3 * 86400
    for wt in path.values():
        _age_tree(wt, old)
    r = e.run("watch", t=T0)
    check(r.returncode == 0, f"watch упал: {r.stderr[-300:]}")
    check(not os.path.exists(path["w-clean"]), "контроль: слитая и чистая копия не убрана")
    check(g("rev-parse", "--verify", "-q", "w-clean").returncode != 0, "контроль: ветка убранной копии осталась")
    check(os.path.isfile(os.path.join(path["w-unpushed"], "work.txt")), "копия с неслитым коммитом удалена")
    check(g("rev-parse", "--verify", "-q", "w-unpushed").returncode == 0, "ветка с неслитым коммитом удалена")
    check(os.path.isfile(os.path.join(path["w-untracked"], "draft.txt")), "копия с неотслеживаемым файлом удалена")


def test_watch_and_wake_second_instance_exits_0184():
    """metis-0184: пока другой проход держит блокировку, второй watch и второй wake выходят без работы."""
    import fcntl
    e, folder, g = _wt_repo("g-dir")
    wt = os.path.join(folder, ".claude", "worktrees", "w-held")
    g("worktree", "add", "-q", "-b", "w-held", wt)
    old = T0 - 3 * 86400
    _age_tree(wt, old)
    e.task("g-0001", "g-dir", status="todo")
    e.agents([{"id": "dead0001", "sessionId": "dead0001-x", "name": "g-dir", "state": "failed", "kind": "background",
               "cwd": folder, "startedAt": (T0 - 7200) * 1000}])
    os.makedirs(e.st("locks"), exist_ok=True)
    os.makedirs(e.st("hq-rw", "locks"), exist_ok=True)
    with open(e.st("locks", "watch.lock"), "a") as fw, open(e.st("hq-rw", "locks", "wake.lock"), "a") as fk:
        fcntl.flock(fw, fcntl.LOCK_EX)
        fcntl.flock(fk, fcntl.LOCK_EX)
        rw = e.run("watch", t=T0)
        rk = e.run("wake", t=T0)
    check(rw.returncode == 0 and "уже идёт другой проход" in rw.stdout, f"второй watch не вышел: {rw.stdout!r}")
    check(os.path.isdir(wt), "второй watch убрал копию")
    check(rk.returncode == 0 and "уже идёт в другом процессе" in rk.stdout, f"второй wake не вышел: {rk.stdout!r}")
    check(not e.calls(), f"второй watch/wake вызвал claude: {e.calls()}")
    check(not os.path.exists(e.st("start.log")) or "g-dir" not in open(e.st("start.log")).read(),
          "второй wake поднял сессию")
    # контроль: без чужой блокировки тот же watch работает и убирает копию
    e.run("watch", t=T0)
    check(not os.path.exists(wt), "контроль: свободный watch не убрал слитую копию")


def test_tick_subcommands():
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    for cmd in ("pantheon watch", "pantheon agents", "pantheon revisits", "pantheon usage 7"):
        check(p.parse_command(cmd) is not None, f"тик не пускает {cmd}")
    check(p.parse_command("pantheon restart --go") is None, "тик пускает restart")


def test_infra_check_managed_mode():
    """infra-check зовёт guard как живой хук: с --managed, когда управляемые настройки активны (metis-0114)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_t", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-")
    managed = os.path.join(d, "managed-settings.json")
    journal = os.path.join(d, "argv.log")
    fake = os.path.join(d, "guard.py")
    with open(fake, "w", encoding="utf-8") as fh:
        fh.write(
            "import json, sys\n"
            f"MANAGED = {managed!r}\n"
            f"JOURNAL = {journal!r}\n"
            "open(JOURNAL, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "mode = 'managed' if '--managed' in sys.argv else 'plugin'\n"
            "def active():\n"
            "    try:\n"
            "        data = json.load(open(MANAGED))\n"
            "    except (OSError, ValueError):\n"
            "        return False\n"
            "    for g in (data.get('hooks') or {}).get('PreToolUse') or []:\n"
            "        for h in g.get('hooks') or []:\n"
            "            c = h.get('command') or ''\n"
            "            if 'guard.py' in c and '--managed' in c:\n"
            "                return True\n"
            "    return False\n"
            "sys.stdin.read()\n"
            "if mode == 'plugin' and active():\n"
            "    sys.exit(0)\n"
            "print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny'}}))\n")
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    want = "готово  guard отказывает на git push --force (роль dev-haiku)"
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = managed, d, (lambda: fake), (lambda: [])
        p.alert_once = p.clear_once = lambda *a, **k: None  # тревоги — не в настоящий alerts.md
        with open(managed, "w", encoding="utf-8") as fh:
            json.dump({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": f'python3 "{fake}" --managed'}]}]}}, fh)
        _, lines = w.infra_check()
        check(want in lines, f"управляемые настройки активны: проба guard не отказала ({lines[:1]})")
        check("--managed" in open(journal).read(), "управляемые настройки активны: проба без --managed")
        os.remove(managed)
        os.remove(journal)
        _, lines = w.infra_check()
        check(want in lines, f"управляемых настроек нет: проба guard не отказала ({lines[:1]})")
        check("--managed" not in open(journal).read(), "управляемых настроек нет: проба с --managed")
        # строка «Python установки» (metis-alpha): не записан — ок с пометкой; записан и работает — ок; сломан — НЕТ
        st = os.path.join(d, "state")
        old_state = os.environ.get("PANTHEON_STATE")
        os.environ["PANTHEON_STATE"] = st
        try:
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            check(line and "не записан (установка без pantheon-setup)" in line[0] and line[0].startswith("готово"),
                  f"Python не записан: ок с пометкой ({line})")
            os.makedirs(st)
            open(os.path.join(st, "config.toml"), "w").write(f'python = "{sys.executable}"\n')
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            ver = "%d.%d.%d" % sys.version_info[:3]
            check(line and line[0].startswith("готово") and ver in line[0], f"Python записан и работает ({line})")
            open(os.path.join(st, "config.toml"), "w").write('python = "/nonexistent/python3.14"\n')
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            check(not ok and line and line[0].startswith("НЕТ") and "не запускается" in line[0],
                  f"Python записан, но сломан: не ок ({line})")
        finally:
            if old_state is None:
                os.environ.pop("PANTHEON_STATE", None)
            else:
                os.environ["PANTHEON_STATE"] = old_state
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_hq_section():
    """infra-check: нет раздела [hq] в policy.toml — строка НЕТ и тревога «Пританею ничего не закрыто»; пустой [hq] —
    без тревоги, тревога снята; битый — строка НЕТ с причиной (metis-0182)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_hq", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-hq-")
    os.makedirs(os.path.join(d, ".claude", "pantheon"))
    pol = os.path.join(d, ".claude", "pantheon", "policy.toml")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        text = "в policy.toml нет раздела [hq]: Пританею ничего не закрыто"
        for name, body in (("нет policy.toml", None), ("нет раздела", '[private]\nroles = ["hq"]\n')):
            calls.clear()
            if body is not None:
                open(pol, "w").write(body)
            ok, lines = w.infra_check()
            check(not ok and any(x.startswith("НЕТ") and "[hq]" in x for x in lines)
                  and any(c[0] == "alert" and c[1] == "hq-policy-missing" and c[2].startswith(text) for c in calls),
                  f"infra-check, {name}: нет строки НЕТ или тревоги про [hq] ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write("[hq]\n")
        _, lines = w.infra_check()
        check(any(x.startswith("готово") and "[hq]" in x for x in lines)
              and not any(c[0] == "alert" and c[1] == "hq-policy-missing" for c in calls)
              and ("clear", "hq-policy-missing") in calls,
              f"infra-check, пустой [hq]: тревога или строка НЕТ ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write('[hq]\nclosed_dirs = "~/x"\n')
        _, lines = w.infra_check()
        check(any(x.startswith("НЕТ") and "[hq].closed_dirs" in x for x in lines),
              f"infra-check, битый [hq]: нет строки НЕТ с причиной ({lines})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_corpus_section():
    """infra-check: нет раздела [corpus] в policy.toml — строка НЕТ и тревога «corpus-role ничего не закрывает»;
    раздел со списком — без тревоги, тревога снята; пустой раздел при объявленном корпусе — как его нет (metis-0194);
    policy.toml не TOML — без второй строки (metis-0182)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_corpus", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-corpus-")
    os.makedirs(os.path.join(d, ".claude", "pantheon"))
    pol = os.path.join(d, ".claude", "pantheon", "policy.toml")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        text = "в policy.toml нет раздела [corpus] или он пуст: правило corpus-role ничего не закрывает"
        decl = '[hq]\nclosed_dirs = ["~/ai/corpus"]\n'
        for name, body in (("корпус в closed_dirs, нет раздела", decl),
                           ("папка x-corpus в closed_dirs, нет раздела", '[hq]\nclosed_dirs = ["~/projects/x-corpus"]\n'),
                           ("корпус в closed_collections, нет раздела", '[hq]\nclosed_collections = ["corpus"]\n'),
                           ("корпус в closed_dirs, пустой [corpus]", decl + "[corpus]\n"),
                           ("корпус в closed_dirs, [corpus] с пустыми списками", decl + "[corpus]\ncommands = []\n")):
            calls.clear()
            open(pol, "w").write(body)
            ok, lines = w.infra_check()
            check(not ok and any(x.startswith("НЕТ") and "[corpus]" in x for x in lines)
                  and any(c[0] == "alert" and c[1] == "corpus-policy-missing" and c[2].startswith(text) for c in calls),
                  f"infra-check, {name}: нет строки НЕТ или тревоги про [corpus] ({lines}, {calls})")
        # metis-0253: чистая policy без [corpus] и без корпуса — тревоги нет, строки про [corpus] нет, старая снята
        for name, body in (("нет policy.toml", None), ("нет раздела и корпуса", '[hq]\nclosed_dirs = ["~/ai/me"]\n'),
                           ("пустой [corpus] без корпуса", "[hq]\n[corpus]\n")):
            calls.clear()
            if body is None:
                os.remove(pol)
            else:
                open(pol, "w").write(body)
            _, lines = w.infra_check()
            check(not any("[corpus]" in x for x in lines)
                  and not any(c[0] == "alert" and c[1] == "corpus-policy-missing" for c in calls)
                  and ("clear", "corpus-policy-missing") in calls,
                  f"infra-check, {name}: лишняя тревога или строка про [corpus] ({lines}, {calls})")
        for name, body in (("[corpus] со списком", '[hq]\n[corpus]\ncommands = ["corpus-x"]\n'),
                           ("корпус в closed_dirs, [corpus] со списком", decl + '[corpus]\nscripts = ["add.py"]\n')):
            calls.clear()
            open(pol, "w").write(body)
            _, lines = w.infra_check()
            check(any(x.startswith("готово") and "[corpus]" in x for x in lines)
                  and not any(c[0] == "alert" and c[1] == "corpus-policy-missing" for c in calls)
                  and ("clear", "corpus-policy-missing") in calls,
                  f"infra-check, {name}: тревога или строка НЕТ ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write("[hq\n")
        _, lines = w.infra_check()
        check(not any("[corpus]" in x for x in lines)
              and not any(c[1] == "corpus-policy-missing" for c in calls),
              f"infra-check, policy.toml не TOML: лишняя строка или тревога про [corpus] ({lines}, {calls})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_hooks_tomllib():
    """infra-check: запускатель хуков hooks/python.sh без Python 3.11+ — строка НЕТ и тревога; нашёл — строка
    «готово» и тревога снята (metis-0571; раньше — python3 хуков без tomllib, metis-0182). Без Python запускатель вне
    хука молчит с кодом 0 — это тоже НЕТ."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_tomllib", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-toml-")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        line = "запускатель хуков находит Python 3.11+"
        for body, good, name in (("exit 0", False, "нет 3.11+ (молчит, код 0)"), ("exit 1", False, "сбой"),
                                 ('echo "$*" > /dev/null; echo ok', True, "нашёл 3.11+")):
            fake = os.path.join(d, f"launcher-{len(calls)}-{good}.sh")
            with open(fake, "w") as fh:
                fh.write(f"#!/bin/sh\n{body}\n")
            w.HOOK_LAUNCHER = fake
            calls.clear()
            _, lines = w.infra_check()
            alerted = any(c[0] == "alert" and c[1] == "hooks-python-no-tomllib" and "python@3.14" in c[2]
                          for c in calls)
            if not good:
                check(any(x.startswith("НЕТ") and line in x for x in lines) and alerted,
                      f"infra-check, {name}: нет строки НЕТ или тревоги ({lines}, {calls})")
            else:
                check(any(x.startswith("готово") and line in x for x in lines) and not alerted
                      and ("clear", "hooks-python-no-tomllib") in calls,
                      f"infra-check, {name}: строка НЕТ, тревога или тревога не снята ({lines}, {calls})")
        w.HOOK_LAUNCHER = os.path.join(d, "нет-такого")
        calls.clear()
        _, lines = w.infra_check()
        check(any(x.startswith("НЕТ") and line in x for x in lines),
              f"infra-check, запускатель не найден: нет строки НЕТ ({lines})")
        # настоящий запускатель плагина: тест идёт на 3.11+, значит и он находит 3.11+
        w.HOOK_LAUNCHER = None
        calls.clear()
        _, lines = w.infra_check()
        check(any(x.startswith("готово") and line in x for x in lines),
              f"infra-check, настоящий hooks/python.sh: нет строки «готово» ({lines})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_who_is_who_memo():
    """Памятка «Кто есть кто.md» сверяется с ролями и реестром: +роль, −лишнее, совпало — тревога снята (metis-0120)."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    d = tempfile.mkdtemp(prefix="who-")
    pan, st, ag = (os.path.join(d, x) for x in ("pantheon", "state", "agents"))
    for x in (pan, st, ag):
        os.makedirs(x)
    for r in ("argus", "momus", "hq", "workshop", "domain-coordinator", "hephaestus-pantheon", "apollo-site"):
        open(os.path.join(ag, r + ".md"), "w").write("---\nname: x\n---\n")
    os.makedirs(os.path.join(ag, "_parts"))
    open(os.path.join(ag, "argus.tmpl"), "w").write("шаблон")
    open(os.path.join(pan, "directions.toml"), "w").write(
        '[[direction]]\nname = "metis-pantheon"\n[[direction]]\nname = "hermes-site"\n')
    memo = os.path.join(pan, "Кто есть кто.md")
    full = ("`zeus` `daedalus-<задача>` `metis-pantheon` `hermes-site` `argus` `momus` `hephaestus-<проект>` "
            "`apollo-<проект>` `claude agents` `pantheon tick` `~/.claude/agents/<роль>.md`\n")
    saved = {k: getattr(p, k) for k in ("PANTHEON", "STATE", "AGENTS", "PLUGIN_ROLES", "ROLES_DEFERRED")}
    alerts = os.path.join(pan, "alerts.md")
    plug = os.path.join(d, "plugin-roles")  # общие шаблоны плагина (metis-0252): сначала пусто
    os.makedirs(plug)

    def read():
        return open(alerts, encoding="utf-8").read() if os.path.exists(alerts) else ""

    def put(text):
        open(memo, "w", encoding="utf-8").write(text)
    try:
        p.PANTHEON, p.STATE, p.AGENTS, p.PLUGIN_ROLES = pan, st, ag, plug
        os.environ["PANTHEON_NO_NOTIFY"] = "1"
        # 1. всё совпадает (чужой код в кавычках не мешает): тихо
        put(full)
        check(p.who_is_who_check() == ([], []), f"совпало, а сверка нашла {p.who_is_who_check()}")
        check(p.who_is_who_alert() == "" and not read(), "совпало, а тревога есть")
        # 2. роли нет в памятке: +momus, на том же состоянии строка одна
        put(full.replace("`momus` ", ""))
        line = p.who_is_who_alert()
        check(line == "памятку обновить: +momus" and "+momus" in read(), f"нет тревоги +momus: {line!r}")
        p.who_is_who_alert()
        check(read().count("+momus") == 1, "тревога +momus повторилась на том же состоянии")
        # 3. направление пропало, лишнее есть: +hermes-site / −janus-probe
        put(full.replace("`hermes-site` ", "") + "`janus-probe` `hephaestus-old`\n")
        line = p.who_is_who_alert()
        check(line == "памятку обновить: +hermes-site / −hephaestus-old / −janus-probe", f"нет −janus-probe: {line!r}")
        # 4. снова совпало: тревога снята — новый сбой пишется заново
        put(full)
        check(p.who_is_who_alert() == "", "совпало, а тревога осталась")
        put(full.replace("`momus` ", ""))
        p.who_is_who_alert()
        check(read().count("+momus") == 2, "после снятия тревога +momus не вернулась")
        # 5. нет памятки: проверять нечего
        os.remove(memo)
        check(p.who_is_who_check() is None and p.who_is_who_alert() == "", "нет памятки, а сверка что-то нашла")
        # 6. metis-0252: новая роль есть только шаблоном в плагине (не собрана), в памятке её нет: +имя
        put(full)
        open(os.path.join(plug, "newgod.tmpl"), "w").write("шаблон")
        p.ROLES_DEFERRED = {"hearth": "проба"}  # отложенная роль (сейчас таких нет, механизм остаётся): не роль
        open(os.path.join(plug, "hearth.tmpl"), "w").write("отложена")
        check(p.who_is_who_check() == (["newgod"], []), f"шаблон плагина не виден сверке: {p.who_is_who_check()}")
        put(full + "`newgod`\n")
        check(p.who_is_who_check() == ([], []), f"роль в памятке, а сверка нашла {p.who_is_who_check()}")
        # 7. .canvas и system.md: везде есть — тихо; нет в .canvas или system.md — «+имя (файл)» в той же строке
        cv, sy = (os.path.join(pan, x) for x in ("Кто есть кто.canvas", "system.md"))
        all_roles = "argus momus hq workshop domain-coordinator hephaestus-<проект> apollo-<проект> newgod"
        canvas_ok = '{"nodes":[{"text":"**Аргус** **Мом** **Зевс** **Дедал** координатор **Гефест** **Аполлон**%s"}]}'
        open(cv, "w", encoding="utf-8").write(canvas_ok % " newgod")
        open(sy, "w", encoding="utf-8").write(all_roles)
        check(p.who_is_who_check() == ([], []), f"везде есть, а сверка нашла {p.who_is_who_check()}")
        open(cv, "w", encoding="utf-8").write(canvas_ok % "")
        check(p.who_is_who_check() == (["newgod (canvas)"], []), f"нет в .canvas: {p.who_is_who_check()}")
        open(sy, "w", encoding="utf-8").write(all_roles.replace(" newgod", ""))
        line = p.who_is_who_alert()
        check(line == "памятку обновить: +newgod (canvas); system.md обновить: +newgod", f"нет в system.md: {line!r}")
        # целым словом (metis-0252): «мом» в «Момент истины» — не Мом
        open(cv, "w", encoding="utf-8").write(canvas_ok.replace("**Мом**", "Момент истины") % " newgod")
        check([x for x in p.who_is_who_check()[0] if "canvas" in x] == ["momus (canvas)"], f"подстрока в холсте сошла за роль: {p.who_is_who_check()}")
        # падежные формы (metis-0252, повтор): «Разработчики», «координатора» засчитываются
        open(cv, "w", encoding="utf-8").write(canvas_ok.replace(" координатор ", " координатора Разработчики ") % " newgod")
        check([x for x in p.who_is_who_check()[0] if "canvas" in x] == [], f"падежные формы не засчитаны: {p.who_is_who_check()}")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)
        os.environ.pop("PANTHEON_NO_NOTIFY", None)
        shutil.rmtree(d, ignore_errors=True)


def test_agents_timeout_1175():
    """metis-1175: claude agents не ответил за срок — проход не падает трассой, строка в вывод, счёт подряд; тревога
    только с третьего раза и со временем первого сбоя; проверки без списка сессий идут; заявка Зевса на запуск остаётся
    в очереди; ответ сбрасывает счёт."""
    from datetime import datetime
    e = Env()
    first = datetime.fromtimestamp(T0 + 60).strftime("%Y-%m-%d %H:%M")
    slow = {"FAKE_AGENTS_SLEEP": "5", "PANTHEON_AGENTS_TIMEOUT": "0.3"}
    req = e.st("hq-rw", "start-req", "g-dir.req")
    os.makedirs(os.path.dirname(req), exist_ok=True)
    open(req, "w").write("заявка\n")
    for i in (1, 2, 3):
        r = e.run("watch", t=T0 + 60 * i, extra=slow)
        check("Traceback" not in r.stderr, f"таймаут {i}: трасса {r.stderr[-300:]!r}")
        check(f"подряд {i}" in r.stdout, f"таймаут {i}: нет строки счёта ({r.stdout[-300:]!r})")
        check(r.returncode == (76 if i == 3 else 75), f"таймаут {i}: код {r.returncode}")
        has = "claude agents --json не ответил 3 раз подряд" in e.alerts()
        check(has == (i == 3), f"таймаут {i}: тревога {'нет' if i == 3 else 'раньше третьего'} ({e.alerts()[-200:]!r})")
        check(os.path.exists(req), f"таймаут {i}: заявка Зевса на запуск потеряна")
        check(f"с {first}" in r.stdout, f"таймаут {i}: не время первого сбоя {first} ({r.stdout[-300:]!r})")
        if i == 1:  # версия Claude Code — проверка без списка сессий, пишет cc-version
            check(os.path.exists(e.st("cc-version")), "при неответе claude agents не шли проверки без списка сессий")
    check(f"3 раз подряд с {first}" in e.alerts(), f"в тревоге не время первого сбоя ({e.alerts()[-200:]!r})")
    e.run("watch", t=T0 + 240)
    check(not os.path.exists(e.st("watch-agents-fails")), "ответ не сбросил счёт неответов")
    r = e.run("watch", t=T0 + 300, extra=slow)
    check("подряд 1" in r.stdout and r.returncode == 75, f"после ответа счёт не с 1 ({r.stdout[-200:]!r} {r.returncode})")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
