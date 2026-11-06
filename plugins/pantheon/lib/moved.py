"""Перенос папок системы (metis-0899): одна таблица «старый путь → новый» на две команды.

`pantheon migrate-paths <перенос>… [--dry-run]` — разовый шаг после того, как папку перенесли:
  1. папки истории ~/.claude/projects/<ключ> — под новый ключ: сама папка и её настоящие подпапки (ключ соседней
     папки вроде `agent-kit-old` — нет: в ключе «/» и «-» одинаковы, подпапку сверяет диск); папки старых worktree,
     `<ключ>--claude-worktrees-…`, — нет: решение плана 0899;
  2. записи projects в ~/.claude.json (доверие, mcpServers, allowedTools) — под новый путь;
  3. старые пути → новые во всех текстовых файлах ~/ai и ~/.claude, в том числе в архивах и закрытых задачах (Зевс
     06.11 06:06). Код agent-kit (рабочая копия на старом и новом месте) — нет: его пути меняет PR через шлюз.
  Шаги 2 и 3 пишут через временный файл рядом и os.replace: оборванный запуск оставляет файл прежним или новым целиком,
  а не обрезанным; права файла прежние. Не трогает историю git (.git), транскрипты сессий (~/.claude/projects/**,
  кроме memory/, и history.jsonl), кэши и код установленных плагинов (~/.claude/plugins), копии веток
  (.claude/worktrees) и личное в ~/ai/knowledge (me, Self, Areas, People — его меняет Мнемозина). Без --dry-run —
  только для переноса, который уже сделан: старой папки нет, новая есть; иначе отказ и ничего не меняет. Запускать
  при остановленных сессиях: Claude Code сам переписывает ~/.claude.json. Плановый проход её не вызывает (её нет в
  TICK_SUBCOMMANDS): запуск — разовый, вручную после переноса папки и «да» владельца на план.

workshop_root(home) — папка мастерской по факту на диске (вариант А, координатор 06.11 18:06): новая ~/ai/workshop,
если она есть, иначе старая (workshop в ~/projects). Её берут песочница окна workshop, `pantheon start workshop`, текст
роли и ctx.py — до переноса мастерская остаётся в старой папке.

`pantheon check --moved` — те же файлы (и личное, если читается, — только числом, без имён файлов): старый путь
сделанного переноса — предупреждение, чтобы агент не вернул его из памяти. Код 1 — старые пути есть, 0 — нет.
"""
import json
import os
import re

# Таблица переносов: имя → (старый, новый) — части пути от HOME. Части, а не «~/…» целиком: так таблица не попадает
# ни под замену, ни под check --moved.
MOVES = {
    "agent-kit": (("projects", "agent-kit"), ("ai", "agent-kit")),
    "workshop": (("projects", "workshop"), ("ai", "workshop")),
    "finances": (("projects", "other", "finances"), ("ai", "life", "finances")),
}
SKIP_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".turbo"}
# ~/.claude: история и кэши сессий, код установленных плагинов — не живые файлы
CLAUDE_SKIP = {"projects", "plugins", "file-history", "shell-snapshots", "debug", "todos", "paste-cache", "session-env",
               "statsig", "telemetry", "backups", "cache", "logs", "ide", "downloads", "image-cache", "jobs",
               "history.jsonl"}
PERSONAL = ("me", "Self", "Areas", "People")   # ~/ai/knowledge/<x> — меняет Мнемозина
MAX_BYTES = 8 << 20


def keyify(p):
    """Путь → ключ папки истории Claude Code (~/.claude/projects/<ключ>): всё, кроме букв и цифр, — «-»."""
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def paths(name, home):
    old, new = MOVES[name]
    return os.path.join(home, *old), os.path.join(home, *new)


def done(name, home):
    """Перенос сделан: старой папки нет, новая есть."""
    old, new = paths(name, home)
    return not os.path.lexists(old) and os.path.isdir(new)


def workshop_root(home):
    """Папка мастерской по факту: новая (~/ai/workshop), если она есть и не ссылка, иначе старая (workshop в ~/projects)."""
    old, new = paths("workshop", home)
    return new if os.path.isdir(new) and not os.path.islink(new) else old


def _is_sub(d, rest, skip=()):
    """Есть ли под папкой d настоящая папка с ключом истории rest («-a-b»: d/a/b, d/a-b …). Ссылки не проходит;
    имена skip на первом уровне не смотрит."""
    if not rest:
        return True
    try:
        names = os.listdir(d)
    except OSError:
        return False
    for x in names:
        if x in skip:
            continue
        k = keyify("/" + x)
        p = os.path.join(d, x)
        if (rest == k or rest.startswith(k + "-")) and os.path.isdir(p) and not os.path.islink(p) \
                and _is_sub(p, rest[len(k):]):
            return True
    return False


def sub_keys(name, home):
    """Хвосты ключей истории ~/.claude/projects, которые — настоящие подпапки переносимой папки (старой или новой —
    какая есть на диске): «-plugins-guard» для …-agent-kit-plugins-guard. Ключ соседней папки (…-agent-kit-old,
    …-agent-kit-v2, …-workshop-notes) сюда не попадает: такой подпапки нет, а если есть и живая соседняя папка с тем же
    ключом — ключ неоднозначен и тоже не попадает. Ключи worktree (`--claude-worktrees-…`) прямо под папкой — нет."""
    projects = os.path.join(home, ".claude", "projects")
    old, new = paths(name, home)
    base = new if os.path.isdir(new) else old
    out = set()
    if not os.path.isdir(projects) or os.path.islink(projects):
        return out
    sib = {os.path.dirname(x): os.path.basename(x) for x in (old, new)}   # родитель → имя самой папки
    for key in os.listdir(projects):
        for pre in (keyify(old), keyify(new)):
            rest = key[len(pre):]
            if not key.startswith(pre + "-") or rest.startswith("--") or not _is_sub(base, rest):
                continue
            if any(key.startswith(keyify(par) + "-") and _is_sub(par, key[len(keyify(par)):], skip={own})
                   for par, own in sib.items()):
                continue   # соседняя живая папка с тем же ключом: чья история — не понять, не трогаю
            out.add(rest)
    return out


def rules(names, home, subs=None):
    """[(regex, замена)] по таблице: пути от ~, $HOME, /Users/<имя> и самого HOME; ключи истории -Users-<имя>-…
    Конец пути — не буква, не «-» и не «.буква» (точка в конце фразы — конец пути). Ключ истории — целиком: сама папка
    или её подпапка из subs ({перенос: хвосты}, по умолчанию sub_keys), а не любой ключ с тем же началом. Ключ worktree
    (`<ключ>--claude-worktrees-…`) не меняется: такие папки истории не переносятся."""
    homes = sorted({home, os.path.realpath(home)}, key=len, reverse=True)
    pre = "|".join([re.escape(h) for h in homes] + [r"~", r"\$HOME", r"\$\{HOME\}", r"/Users/[A-Za-z0-9._-]+"])
    kpre = "|".join([re.escape(keyify(h)) for h in homes] + [r"-Users-[A-Za-z0-9_-]+?"])
    out = []
    for n in names:
        old, new = MOVES[n]
        out.append((re.compile(rf"(?P<pre>{pre})/{re.escape('/'.join(old))}(?![\w-]|\.\w)"),
                    r"\g<pre>/" + "/".join(new)))
        tails = sorted(subs[n] if subs is not None and n in subs else sub_keys(n, home), key=len, reverse=True)
        sub = "(?P<sub>" + "|".join(re.escape(t) for t in tails) + ")?" if tails else "(?P<sub>)"
        out.append((re.compile(rf"(?P<pre>{kpre}){re.escape(keyify('/' + '/'.join(old)))}{sub}(?![A-Za-z0-9_.-])"),
                    r"\g<pre>" + keyify("/" + "/".join(new)) + r"\g<sub>"))
    return out


def _replace_file(p, data):
    """Запись целиком: временный файл рядом, fsync, права прежнего файла, os.replace. Сбой — прежний файл цел."""
    import tempfile
    mode = os.stat(p).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix="." + os.path.basename(p) + ".", suffix=".moved")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply(text, rs):
    total = 0
    for rx, rep in rs:
        text, n = rx.subn(rep, text)
        total += n
    return text, total


def roots(home):
    """Где искать: ~/ai и ~/.claude."""
    return [os.path.join(home, "ai"), os.path.join(home, ".claude")]


def personal_dirs(home):
    return {os.path.join(home, "ai", "knowledge", x) for x in PERSONAL}


def is_personal(p, home):
    return any(p.startswith(d + os.sep) for d in personal_dirs(home))


def files(home, personal=False):
    """Живые файлы для замены и проверки (без ~/.claude.json — его разбирают отдельно). Ссылки не проходит. Код
    agent-kit (рабочая копия на старом и новом месте) — нет: его пути и тестовые данные ядра guard меняет PR через
    шлюз, а не перепись мимо него (argus-2 Б1 к PR #371)."""
    claude = os.path.join(home, ".claude")
    projects = os.path.join(claude, "projects")
    skip = set(paths("agent-kit", home)) | (set() if personal else personal_dirs(home))
    for root in roots(home):
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        for d, dirs, names in os.walk(root):
            if d == claude:
                dirs[:] = [x for x in dirs if x not in CLAUDE_SKIP]
                names = [x for x in names if x not in CLAUDE_SKIP]
            dirs[:] = sorted(x for x in dirs if x not in SKIP_NAMES and os.path.join(d, x) not in skip
                             and not (x == "worktrees" and os.path.basename(d) == ".claude"))
            for x in sorted(names):
                p = os.path.join(d, x)
                if not os.path.islink(p) and os.path.isfile(p):
                    yield p
    # автопамять проектов — живая, транскрипты рядом с ней — история
    if os.path.isdir(projects) and not os.path.islink(projects):
        for key in sorted(os.listdir(projects)):
            mem = os.path.join(projects, key, "memory")
            if os.path.islink(mem) or not os.path.isdir(mem):
                continue
            for d, dirs, names in os.walk(mem):
                for x in sorted(names):
                    p = os.path.join(d, x)
                    if not os.path.islink(p) and os.path.isfile(p):
                        yield p


def read_text(p):
    """Текст файла или None: двоичный, не UTF-8, больше MAX_BYTES или не читается."""
    try:
        if os.path.getsize(p) > MAX_BYTES:
            return None
        with open(p, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _walk_json(v, rs, conflicts):
    """Замена в ключах и строках JSON. → (новое значение, число замен)."""
    if isinstance(v, str):
        return apply(v, rs)
    if isinstance(v, list):
        out, n = [], 0
        for x in v:
            y, k = _walk_json(x, rs, conflicts)
            out.append(y)
            n += k
        return out, n
    if isinstance(v, dict):
        out, n = {}, 0
        for key, x in v.items():
            nk, k1 = apply(key, rs)
            y, k2 = _walk_json(x, rs, conflicts)
            if nk != key and (nk in v or nk in out):
                conflicts.append(nk)   # новый ключ уже есть: его запись остаётся, старая — тоже, под старым ключом
                nk, k1 = key, 0
            out[nk] = y
            n += k1 + k2
        return out, n
    return v, 0


def migrate(names, dry_run, home, out=print):
    """pantheon migrate-paths. → код выхода: 0 — сделано (или план при --dry-run), 1 — отказ, конфликт или сбой."""
    short = lambda p: "~" + p[len(home):] if p == home or p.startswith(home + "/") else p
    head = "--dry-run: ничего не меняю, только план" if dry_run else "перенос путей"
    out(f"{head}: " + ", ".join(f"{short(paths(n, home)[0])} → {short(paths(n, home)[1])}" for n in names))
    not_done = [n for n in names if not done(n, home)]
    for n in not_done:
        old, new = paths(n, home)
        why = "старая папка ещё на месте" if os.path.lexists(old) else "новой папки нет"
        out(("внимание " if dry_run else "отказ   ") + f"{n}: {why} — сначала перенести папку {short(old)} → {short(new)}")
    if not_done and not dry_run:
        out("ничего не изменено: перенос папок не сделан")
        return 1
    rs = rules(names, home)
    rc = 0
    # 1. папки истории
    projects = os.path.join(home, ".claude", "projects")
    renamed = 0
    if os.path.isdir(projects) and not os.path.islink(projects):
        for n in names:
            ok, nk = (keyify(p) for p in paths(n, home))
            subs = sub_keys(n, home)   # только целый компонент пути: …-agent-kit-old — соседняя папка, не подпапка
            for key in sorted(os.listdir(projects)):
                if key != ok and not (key.startswith(ok + "-") and key[len(ok):] in subs):
                    continue
                target = nk + key[len(ok):]
                src, dst = os.path.join(projects, key), os.path.join(projects, target)
                if os.path.lexists(dst):
                    out(f"конфликт история {key} → {target}: новая папка уже есть — не переношу")
                    rc = 1
                    continue
                out(f"история {key} → {target}")
                renamed += 1
                if not dry_run:
                    try:
                        os.rename(src, dst)
                    except OSError as e:
                        out(f"сбой    история {key}: {e.strerror or e}")
                        rc = 1
    # 2. ~/.claude.json
    cj_path, cj_n = os.path.join(home, ".claude.json"), 0
    raw = read_text(cj_path) if os.path.isfile(cj_path) and not os.path.islink(cj_path) else None
    if raw is not None:
        try:
            data = json.loads(raw)
        except ValueError:
            out("сбой    ~/.claude.json: не JSON — не трогаю")
            data, rc = None, 1
        if data is not None:
            conflicts = []
            new, cj_n = _walk_json(data, rs, conflicts)
            for c in conflicts:
                out(f"конфликт ~/.claude.json: запись {c} уже есть — старая оставлена под прежним ключом")
                rc = 1
            if cj_n:
                out(f"~/.claude.json: {cj_n}")
                if not dry_run:
                    try:
                        _replace_file(cj_path, (json.dumps(new, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                    except OSError as e:
                        out(f"сбой    ~/.claude.json: {e.strerror or e}")
                        rc = 1
    # 3. текстовые файлы
    n_files = n_rep = 0
    for p in files(home):
        text = read_text(p)
        if text is None:
            continue
        new, k = apply(text, rs)
        if not k:
            continue
        n_files += 1
        n_rep += k
        out(f"{short(p)}: {k}")
        if not dry_run:
            try:
                _replace_file(p, new.encode("utf-8"))   # целиком или никак; права прежние
            except OSError as e:
                out(f"сбой    {short(p)}: {e.strerror or e}")
                rc = 1
    out(f"личное ~/ai/knowledge/{{{','.join(PERSONAL)}}} не тронуто — его меняет Мнемозина")
    out(f"итог: файлов {n_files}, замен {n_rep}, папок истории {renamed}, замен в ~/.claude.json {cj_n}"
        + (" — --dry-run, ничего не изменено" if dry_run else ""))
    return rc


def check(home, names=None):
    """Старые пути сделанных переносов в живых файлах. → ([(файл, число)] без личного, [имена несделанных переносов],
    число личных файлов со старыми путями). Личное (~/ai/knowledge/{me,Self,Areas,People}) — только числом: имя
    личного файла не должно попасть в тревогу и вывод, которые читают роли (argus-2 Б2 к PR #371)."""
    names = list(names or MOVES)
    moved = [n for n in names if done(n, home)]
    found, n_personal = [], 0
    if not moved:
        return found, [n for n in names if n not in moved], 0
    rs = rules(moved, home)
    cj = os.path.join(home, ".claude.json")
    for p in list(files(home, personal=True)) + ([cj] if os.path.isfile(cj) and not os.path.islink(cj) else []):
        text = read_text(p)
        if text is None:
            continue
        k = sum(len(rx.findall(text)) for rx, _ in rs)
        if k and is_personal(p, home):
            n_personal += 1
        elif k:
            found.append((p, k))
    return found, [n for n in names if n not in moved], n_personal
