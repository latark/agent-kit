#!/usr/bin/env python3
"""Дежурный, часть 5: пересмотры, правила Аргуса, безопасность worktree, уборка песочницы (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_tool04_limit_after_max_delay():
    """Задача на Claude после max_delay всё равно ждёт лимита; обычная — идёт."""
    e = Env()
    e.schedule(
        'primary_host = "mac-a"\n[[job]]\nname = "clio-weekly"\ncommand = "claude -p --agent clio \\"проход\\""\n'
        'every = 10080\nclass = "heavy"\nclaude = true\nmax_delay = 60\n'
        '[[job]]\nname = "heavy-plain"\ncommand = "pantheon view"\nevery = 10080\nclass = "heavy"\nmax_delay = 60\n'
        'priority = -1\n')
    env = {"PANTHEON_DRYRUN": "1", "PANTHEON_FAKE_WAKE": str(T0 - 7200), "PANTHEON_FAKE_AC": "1",
           "PANTHEON_FAKE_IDLE": "1200", "PANTHEON_FAKE_LIMIT": "95"}
    e.run("tick", t=T0, extra=env)
    e.run("tick", t=T0 + 3700, extra=env)
    st = json.load(open(e.st("jobs", "clio-weekly.json")))
    check("лимит" in (st.get("waiting") or "") and not st.get("last_start"), f"TOOL-04: {st}")


def test_argus_wake_rules():
    """Ревью argus 15.10: снятие паузы не будит при техперезапуске и общей паузе; wake не будит под паузой; не на
    главном Mac самозапуска нет; быстрый «закончила ход» без STATUS.md — сбой; Зевс без вашего слова метку не снимает;
    чужой текст задания — под своей пометкой; saved — только себя."""
    e = Env()
    e.direction("q-dir")
    e.agents([bg("q-dir", "working", "abcdef01-1", pid=61)])
    e.run("pause", "q-dir", "--reason", "limit", t=T0)
    e.agents([bg("q-dir", "stopped", "abcdef01-1")])
    e.run("pause", "--all", "--reason", "manual", t=T0)
    n0 = len([c for c in e.calls() if c[:1] == ["respawn"]])
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "10"})
    check(len([c for c in e.calls() if c[:1] == ["respawn"]]) == n0, "снятие паузы подняло сессию под общей паузой")
    check(os.path.exists(e.st("pauses", "q-dir.json")), "своя пауза снята, хотя будить нельзя")
    r = e.run("wake", "q-dir", t=T0 + 70)
    check(r.returncode == 0 and "пропуск: q-dir — пауза по нагрузке" in r.stdout and "поднимаю" not in r.stdout, f"wake под паузой: {r.stdout} {r.stderr}")
    e.run("pause", "--off", "--all", t=T0 + 80)
    r = e.run("wake", "q-dir", "сделай", "X", t=T0 + 90)
    pushed = open(e.st("push", "abcdef01-1.txt")).read()
    check(pushed.startswith("[Пантеон: задание от владелец] сделай X"), f"текст задания без пометки: {pushed}")
    # не главный Mac
    e2 = Env()
    e2.direction("w-dir")
    e2.task("ww-0001", "w-dir")
    e2.run("watch", t=T0)
    e2.board("ww-0001", T0 + 10)
    out = e2.run("watch", "--dry-run", t=T0 + 60, extra={"PANTHEON_HOST": "mac-b"}).stdout
    check("не главный Mac" in out, f"самозапуск не на главном Mac: {out}")
    # быстрый done без STATUS.md — сбой
    e2.run("watch", t=T0 + 60)
    e2.agents([bg("w-dir", "done", "abcdef02-1", started=T0 + 61)])
    e2.run("watch", t=T0 + 400)
    check(json.load(open(e2.st("autostart.json")))["w-dir"].get("fails") == 1, "быстрый done засчитан успехом")
    # Зевс без вашего слова метку не снимает
    e2.run("stop", "w-dir", t=T0 + 500)
    r = e2.run("resume", "w-dir", t=T0 + 510, extra={"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"})
    check(r.returncode == 1 and os.path.exists(e2.st("stopped", "w-dir")), "Зевс снял метку без вашего слова")
    with open(e2.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 + 505))}\nверни w-dir\n\n")
    r = e2.run("resume", "w-dir", t=T0 + 510, extra={"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"})
    check(r.returncode == 0 and not os.path.exists(e2.st("stopped", "w-dir")), f"Зевс по вашему слову: {r.stderr}")
    # saved — только себя
    e2.agents([bg("w-dir", "working", "abcdef02-1", pid=62)])
    e2.run("restart", "--prepare", t=T0 + 600)
    r = e2.run("saved", "--by", "w-dir", t=T0 + 610, extra={"PANTHEON_SESSION": "other-dir"})
    check(r.returncode == 2, "сессия отметила чужую")


def test_owner_log_shrink_and_u2028():
    e = Env()
    d = e.st("owner-log")
    new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
    p = os.path.join(d, "x.md")
    open(p, "w").write(f"## {new}\nне делай X\n\n## {new}\nдругое\n\n")
    rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 86400)), "kind": "note", "id": "x-0001",
           "text": "раз\u2028два"}
    open(os.path.join(d, "board.jsonl"), "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    e.board("x-0002", T0 - 40 * 86400)
    e.run("watch", t=T0)
    lines = open(os.path.join(d, "board.jsonl"), encoding="utf-8").read().split("\n")
    check(json.loads(lines[0]).get("text") == "раз\u2028два" and len([x for x in lines if x]) == 1,
          f"U+2028 порвал запись: {lines}")
    open(p, "w").write(f"## {new}\nдругое\n\n")
    os.chmod(p, 0o600)
    e.run("watch", t=T0 + 86400)
    check("укорочен" in e.alerts(), "удаление записи не замечено")
    os.remove(p)
    e.run("watch", t=T0 + 2 * 86400)
    check("x.md пропал" in e.alerts(), "пропажа журнала не замечена")


def test_security_0100():
    """Проверка безопасности 0.10.0: git в копии роли не исполняет конфигурацию; pause --off не выходит из pauses/;
    из сессии Claude метку и ручную паузу без вашей строки не снять; saved — только имя сессии."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": e.home})  # без GIT_*/PANTHEON_* внешней среды
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    for n in ("w-ok", "w-bad"):
        g("worktree", "add", "-q", "-b", n, os.path.join(folder, ".claude", "worktrees", n))
    pwn = os.path.join(e.tmp, "pwned")
    bad = os.path.join(folder, ".claude", "worktrees", "w-bad")
    # роль подменяет указатель .git своей копии на собственный каталог git с исполняемым fsmonitor
    evil = os.path.join(bad, "evil.git")
    subprocess.run(["cp", "-R", os.path.join(folder, ".git", "worktrees", "w-bad"), evil])
    open(os.path.join(evil, "commondir"), "w").write(os.path.join(folder, ".git") + "\n")
    open(os.path.join(evil, "config.worktree"), "w").write(f"[core]\n\tfsmonitor = touch {pwn}\n")
    open(os.path.join(bad, ".git"), "w").write(f"gitdir: {evil}\n")
    g("config", "extensions.worktreeConfig", "true")
    old = T0 - 3 * 86400
    for n in ("w-ok", "w-bad"):
        _age_tree(os.path.join(folder, ".claude", "worktrees", n), old)
    e.run("watch", t=T0)
    check(not os.path.exists(pwn), "git исполнил fsmonitor из копии роли")
    check(not os.path.exists(os.path.join(folder, ".claude", "worktrees", "w-ok")), "чистая слитая копия не убрана")
    check(os.path.exists(bad), "копия с исполняемой конфигурацией убрана")
    # подраздел с U+2028 в имени не прячет фильтр от разбора
    w3 = os.path.join(folder, ".claude", "worktrees", "w-ok")
    g("worktree", "add", "-q", "-b", "w3", w3)
    g("config", "filter.x\u2028y.clean", f"touch {pwn}")
    open(os.path.join(w3, ".gitattributes"), "w").write("* filter=x\u2028y\n")
    _age_tree(w3, old)
    e.run("watch", t=T0 + 86400)
    check(not os.path.exists(pwn) and os.path.exists(w3), "фильтр с U+2028 в имени исполнился или копия убрана")
    # pause --off не выходит из pauses/
    open(e.st("maintenance.json"), "w").write("{}")
    r = e.run("pause", "--off", "../maintenance", t=T0)
    check(r.returncode == 2 and os.path.exists(e.st("maintenance.json")), "pause --off удалил файл вне pauses/")
    os.remove(e.st("maintenance.json"))
    # из сессии Claude без роли — нужна ваша строка
    e.run("pause", "g-dir", "--reason", "manual", t=T0)
    e.run("stop", "g-dir", t=T0)
    cl = {"CLAUDECODE": "1"}
    r = e.run("resume", "g-dir", t=T0 + 10, extra=cl)
    check(r.returncode == 1 and os.path.exists(e.st("stopped", "g-dir")), "сессия Claude сняла метку без вашего слова")
    r = e.run("pause", "--off", "g-dir", t=T0 + 10, extra=cl)
    check(r.returncode == 1 and os.path.exists(e.st("pauses", "g-dir.json")), "сессия Claude сняла ручную паузу")
    r = e.run("pause", "--off", "g-dir", t=T0 + 10)
    check(r.returncode == 0 and not os.path.exists(e.st("pauses", "g-dir.json")), "терминал не снял паузу")
    r = e.run("saved", "--by", "../x", t=T0 + 10)
    check(r.returncode != 0 and not os.path.exists(e.st("maintenance", "../x.json")), "saved с путём в имени")


def test_worktree_outward_links_0101():
    """Дежурный не удаляет слитую чистую копию со ссылкой наружу (старый Claude Code сносил цель ссылки); ссылка
    внутрь копии удалению не мешает."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    out_wt = os.path.join(folder, ".claude", "worktrees", "w-out")
    in_wt = os.path.join(folder, ".claude", "worktrees", "w-in")
    for n, w in (("w-out", out_wt), ("w-in", in_wt)):
        g("worktree", "add", "-q", "-b", n, w)
    target = os.path.join(e.tmp, "outside-data")
    os.makedirs(target)
    open(os.path.join(target, "keep.txt"), "w").write("x")
    os.symlink(target, os.path.join(out_wt, "link-out"))
    os.makedirs(os.path.join(in_wt, "sub"))
    os.symlink(os.path.join(in_wt, "sub"), os.path.join(in_wt, "link-in"))
    os.symlink("nowhere", os.path.join(in_wt, "link-broken"))
    for w in (out_wt, in_wt):  # копия чистая для git status: ссылки и папка игнорируются
        ex = subprocess.run(["git", "-C", w, "rev-parse", "--git-path", "info/exclude"], capture_output=True,
                            text=True).stdout.strip()
        ex = ex if os.path.isabs(ex) else os.path.join(w, ex)
        os.makedirs(os.path.dirname(ex), exist_ok=True)
        open(ex, "a").write("link-*\nsub\n")
        check(g("status", "--porcelain", cwd=w).stdout.strip() == "", "копия не чистая для git")
    old = T0 - 3 * 86400
    for w in (out_wt, in_wt):
        _age_tree(w, old)
    e.run("watch", t=T0)
    check(os.path.exists(out_wt) and os.path.exists(os.path.join(target, "keep.txt")),
          "копия со ссылкой наружу убрана или цель тронута")
    check("не убрана" in e.alerts() and "link-out" in e.alerts() and "w-out" in e.alerts(), "нет тревоги о ссылках")
    check(not os.path.exists(in_wt), "копия со ссылкой внутрь не убрана")


def test_outward_links_walk_limit_0101():
    """Обход длиннее WALK_LIMIT — None (копия небезопасна); в пределах лимита — число ссылок наружу."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w = importlib.import_module("watch")
    d = tempfile.mkdtemp(prefix="walk-", dir=os.environ.get("TMPDIR"))
    saved = w.WALK_LIMIT
    try:
        for i in range(10):
            open(os.path.join(d, f"f{i}"), "w").close()
        w.WALK_LIMIT = 5
        check(w.outward_links(d) is None, "обход длиннее лимита не признан небезопасным")
        w.WALK_LIMIT = 50
        check(w.outward_links(d) == (0, None), "обход в пределах лимита без ссылок не (0, None)")
        os.symlink(tempfile.gettempdir(), os.path.join(d, "out"))
        res = w.outward_links(d)
        check(res and res[0] == 1 and res[1][0] == "out", "ссылка наружу не найдена")
    finally:
        w.WALK_LIMIT = saved
        shutil.rmtree(d, ignore_errors=True)


def test_worktree_node_modules_0616():
    """Сквозной (metis-0616): дежурный убирает слитую чистую копию с 6000 файлами в node_modules и .next (больше
    WALK_LIMIT); копию со ссылкой наружу внутри node_modules не убирает и тревожит; копию с 6000 файлами вне
    зависимостей оставляет с тревогой «обход длиннее лимита»."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    target = os.path.join(e.tmp, "outside-data")
    os.makedirs(target)
    open(os.path.join(target, "keep.txt"), "w").write("x")
    old = T0 - 3 * 86400
    wts = {}
    for n in ("w-clean", "w-link", "w-wide", "w-dirty"):
        wts[n] = os.path.join(folder, ".claude", "worktrees", n)
        g("worktree", "add", "-q", "-b", n, wts[n])
    for n in ("w-clean", "w-link", "w-dirty"):
        w = wts[n]
        _mk_wt_files(os.path.join(w, ".venv", "lib"), 1000)
        _mk_wt_files(os.path.join(w, "node_modules", ".pnpm", "x", "node_modules", "y"), 3000)
        _mk_wt_files(os.path.join(w, ".next", "cache"), 3000)
        os.symlink(os.path.join(w, "node_modules", ".pnpm", "x"), os.path.join(w, "node_modules", "inner"))
    os.symlink(target, os.path.join(wts["w-link"], "node_modules", ".pnpm", "x", "node_modules", "out"))
    _mk_wt_files(os.path.join(wts["w-wide"], "src"), 6000)
    for n, w in wts.items():  # git status чист: зависимости и сборка в исключениях копии
        ex = subprocess.run(["git", "-C", w, "rev-parse", "--git-path", "info/exclude"], capture_output=True,
                            text=True).stdout.strip()
        ex = ex if os.path.isabs(ex) else os.path.join(w, ex)
        os.makedirs(os.path.dirname(ex), exist_ok=True)
        open(ex, "a").write("node_modules\n.next\n.venv\nsrc\n")
        if n == "w-dirty":
            open(os.path.join(w, "work.txt"), "w").write("не закоммичено")
            check(g("status", "--porcelain", cwd=w).stdout.strip() != "", "w-dirty чистая")
            _age_tree(w, old)
            continue
        check(g("status", "--porcelain", cwd=w).stdout.strip() == "", f"{n}: копия не чистая для git")
        _age_tree(w, old)
    e.run("watch", t=T0)
    check(not os.path.exists(wts["w-clean"]), "слитая чистая копия с 6000 файлами в node_modules не убрана за проход")
    check(os.path.exists(wts["w-link"]) and os.path.exists(os.path.join(target, "keep.txt")),
          "копия со ссылкой наружу в node_modules убрана или цель тронута")
    check(os.path.exists(os.path.join(wts["w-dirty"], "work.txt")), "копия с незакоммиченной работой и большим node_modules убрана")
    check("w-link" in e.alerts() and "ссылки наружу" in e.alerts(), "нет тревоги о ссылке наружу в node_modules")
    check(os.path.exists(wts["w-wide"]) and "w-wide" in e.alerts() and "обход длиннее лимита" in e.alerts(),
          "копия с 6000 файлами вне зависимостей убрана или нет тревоги о лимите")


def test_outward_links_skips_node_modules_0616():
    """Копия с 6000 файлами в node_modules/.next не «небезопасна» по WALK_LIMIT; ссылка наружу на любой глубине
    node_modules (в том числе .pnpm/x/node_modules/y) находится; зависимости больше DEPS_LIMIT — None («не знаю»);
    6000 файлов вне зависимостей — по-прежнему None."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w = importlib.import_module("watch")
    base = os.path.realpath(tempfile.mkdtemp(prefix="walk-", dir=os.environ.get("TMPDIR")))
    outside = os.path.join(base, "outside")
    os.makedirs(outside)
    try:
        def make(name):
            d = os.path.join(base, name)
            _mk_wt_files(os.path.join(d, "node_modules", ".pnpm", "x", "node_modules", "y"), 3000)
            _mk_wt_files(os.path.join(d, ".next", "cache"), 3000)
            os.symlink(os.path.join(d, "node_modules", ".pnpm", "x"), os.path.join(d, "node_modules", "inner"))
            return d
        clean = make("clean")
        check(w.outward_links(clean) == (0, None), f"копия без ссылок: {w.outward_links(clean)}")
        for i, rel in enumerate((("node_modules", "out"), ("node_modules", ".pnpm", "x", "node_modules", "out"),
                                 ("node_modules", ".pnpm", "x", "node_modules", "y", "deep"),
                                 (".next", "cache", "out"))):
            d = make(f"bad{i}")
            os.symlink(outside, os.path.join(d, *rel))
            res = w.outward_links(d)
            check(res and res[0] == 1 and res[1][1] == outside, f"ссылка наружу {rel} не найдена: {res}")
        saved = w.DEPS_LIMIT
        try:
            w.DEPS_LIMIT = 100
            check(w.outward_links(clean) is None, "зависимости больше DEPS_LIMIT не дали None")
        finally:
            w.DEPS_LIMIT = saved
        venv = os.path.join(base, "venv-wt")
        _mk_wt_files(os.path.join(venv, ".venv", "lib"), 6000)
        check(w.outward_links(venv) == (0, None), f".venv с 6000 файлами: {w.outward_links(venv)}")
        plain = os.path.join(base, "plain")
        _mk_wt_files(plain, 6000)
        check(w.outward_links(plain) is None, "6000 файлов вне node_modules не дали None")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_sandbox_clean_0620():
    """Уборка кэшей песочниц: старое без процессов уходит, свежее, занятое процессом и чужие папки остаются;
    ссылка снимается сама, цель не тронута."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w = importlib.import_module("watch")
    base = os.path.realpath(tempfile.mkdtemp(prefix="sbx-", dir=os.environ.get("TMPDIR")))
    keep_out = os.path.join(base, "outside")
    os.makedirs(keep_out)
    open(os.path.join(keep_out, "k"), "w").write("x")
    root = os.path.join(base, "cache")
    now = time.time()
    old = now - 20 * 86400

    def entry(role, part, name, mtime, sub=True):
        p = os.path.join(root, role, part, name)
        os.makedirs(os.path.join(p, "deep") if sub else os.path.dirname(p), exist_ok=True)
        f = p if not sub else os.path.join(p, "deep", "f")
        open(f, "w").write("x") if sub else open(p, "w").write("x")
        for q in ([p, os.path.join(p, "deep"), f] if sub else [p]):
            os.utime(q, (mtime, mtime))
        return p
    try:
        gone = entry("argus", "tmp", "old1", old)
        gone2 = entry("argus", "npm", "old2", old)
        gone3 = entry("argus", "logs", "x.log", old, sub=False)
        fresh = entry("argus", "tmp", "fresh", now)
        mixed = entry("argus", "tmp", "mixed", old)
        os.utime(os.path.join(mixed, "deep", "f"), (now, now))  # внутри свежее — запись остаётся
        held = entry("argus", "tmp", "held", old)
        other = entry("argus", "work", "old", old)  # не из списка частей
        link = os.path.join(root, "argus", "tmp", "lnk")
        os.symlink(keep_out, link)
        os.makedirs(os.path.join(root, "evil-role", "tmp"))
        os.makedirs(os.path.join(keep_out, "tmp", "old"))
        os.utime(os.path.join(keep_out, "tmp", "old"), (old, old))
        os.utime(os.path.join(keep_out, "tmp"), (old, old))
        os.symlink(keep_out, os.path.join(root, "linkrole"))
        os.makedirs(os.path.join(root, "partlink"))
        os.symlink(os.path.join(keep_out, "tmp"), os.path.join(root, "partlink", "tmp"))
        removed, failed = w.sandbox_clean(root, now, {os.path.join(held, "deep", "f")}, days=7)
        check(not os.path.exists(gone) and not os.path.exists(gone2) and not os.path.exists(gone3),
              "старое не убрано")
        check(all(os.path.exists(x) for x in (fresh, mixed, held, other)), "свежее, занятое или чужое убрано")
        check(os.path.exists(os.path.join(keep_out, "k")), "цель ссылки тронута")
        check(removed >= 3 and failed == 0, f"счётчики: {removed} {failed}")
        # ссылка tmp/lnk сама свежая по lstat — остаётся; состаренную снимаем, цель цела
        os.utime(link, (old, old), follow_symlinks=False)
        w.sandbox_clean(root, now, set(), days=7)
        check(not os.path.lexists(link) and os.path.exists(os.path.join(keep_out, "k")), "ссылка не снята или цель тронута")
        check(not os.path.exists(held), "без процесса запись должна уйти")
        # окно-ссылка не обходится вовсе
        w.sandbox_clean(root, now + 99 * 86400, set(), days=7)
        check(os.path.exists(os.path.join(keep_out, "k")) and os.path.isdir(os.path.join(keep_out, "tmp", "old")),
              "обход через окно- или часть-ссылку тронул цель")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_sandbox_clean_swap_0620():
    """Окно подменяет папку части ссылкой наружу между проверкой и удалением: цель снаружи цела."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w = importlib.import_module("watch")
    base = os.path.realpath(tempfile.mkdtemp(prefix="sbx-", dir=os.environ.get("TMPDIR")))
    try:
        root = os.path.join(base, "cache")
        part = os.path.join(root, "argus", "tmp")
        os.makedirs(os.path.join(part, "old1"))
        os.makedirs(os.path.join(base, "outside", "old1"))
        open(os.path.join(base, "outside", "old1", "keep"), "w").write("x")
        old = time.time() - 30 * 86400
        for q in (os.path.join(part, "old1"), part):
            os.utime(q, (old, old))
        real_newer, swapped = w._tree_newer, []

        def newer(path, lim):
            r = real_newer(path, lim)
            if not swapped:  # между проверкой возраста и удалением
                swapped.append(1)
                os.rename(part, part + "-moved")
                os.symlink(os.path.join(base, "outside"), part)
            return r
        w._tree_newer = newer
        try:
            w.sandbox_clean(root, time.time(), set(), days=7)
        finally:
            w._tree_newer = real_newer
        check(swapped and os.path.exists(os.path.join(base, "outside", "old1", "keep")),
              "после подмены части ссылкой тронута цель снаружи")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_sandbox_cap_alert_0620():
    """Дежурный: кэш выше потолка после уборки — строка в alerts.md; в пределах — нет; старое убирает проходом."""
    e = Env()
    root = os.path.join(e.home, "Library", "Caches", "pantheon-sandbox", "argus")
    old_dir = os.path.join(root, "tmp", "old")
    os.makedirs(old_dir)
    open(os.path.join(old_dir, "big"), "wb").write(b"0" * 3 * 1024 * 1024)
    fresh = os.path.join(root, "tmp", "fresh")
    os.makedirs(fresh)
    open(os.path.join(fresh, "big"), "wb").write(b"0" * 3 * 1024 * 1024)
    old = T0 - 20 * 86400
    for q in (old_dir, os.path.join(old_dir, "big")):
        os.utime(q, (old, old))
    e.run("watch", t=T0, extra={"PANTHEON_SANDBOX_CAP_MB": "1"})
    check("кэши песочниц" in e.alerts() and "потолке 1 МБ" in e.alerts(), f"нет тревоги о потолке: {e.alerts()[-400:]}")
    check(not os.path.exists(old_dir) and os.path.exists(fresh), "старое не убрано или свежее убрано")
    e2 = Env()
    r2 = os.path.join(e2.home, "Library", "Caches", "pantheon-sandbox", "argus", "tmp", "fresh")
    os.makedirs(r2)
    open(os.path.join(r2, "big"), "wb").write(b"0" * 1024 * 1024)
    e2.run("watch", t=T0, extra={"PANTHEON_SANDBOX_CAP_MB": "100"})
    check("потолке" not in e2.alerts(), "тревога при объёме в пределах потолка")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
