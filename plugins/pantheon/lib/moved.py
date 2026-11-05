"""Перенос папок системы (metis-0899): одна таблица «старый путь → новый» на две команды.

`pantheon migrate-paths <перенос>… [--dry-run]` — разовый шаг после того, как папку перенесли:
  1. папки истории ~/.claude/projects/<ключ> — под новый ключ (папки старых worktree, `<ключ>--claude-worktrees-…`, —
     нет: решение плана 0899);
  2. записи projects в ~/.claude.json (доверие, mcpServers, allowedTools) — под новый путь;
  3. старые пути → новые во всех текстовых файлах ~/ai, ~/.claude и кода agent-kit, в том числе в архивах и закрытых
     задачах (Зевс 06.11 06:06).
  Не трогает историю git (.git), транскрипты сессий (~/.claude/projects/**, кроме memory/, и history.jsonl), кэши и
  код установленных плагинов (~/.claude/plugins), копии веток (.claude/worktrees) и личное в ~/ai/knowledge (me, Self,
  Areas, People — его меняет Мнемозина). Без --dry-run — только для переноса, который уже сделан: старой папки нет,
  новая есть; иначе отказ и ничего не меняет. Запускать при остановленных сессиях: Claude Code сам переписывает
  ~/.claude.json. Сама команда ничего не запускает — её разовой заявкой вызывает плановый проход.

`pantheon check --moved` — те же файлы (и личное, если читается): старый путь сделанного переноса — предупреждение,
чтобы агент не вернул его из памяти. Код 1 — старые пути есть, 0 — нет.
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


def rules(names, home):
    """[(regex, замена)] по таблице: пути от ~, $HOME, /Users/<имя> и самого HOME; ключи истории -Users-<имя>-…
    Конец пути — не буква, не «-» и не «.буква» (точка в конце фразы — конец пути). Ключ worktree
    (`<ключ>--claude-worktrees-…`) не меняется: такие папки истории не переносятся."""
    homes = sorted({home, os.path.realpath(home)}, key=len, reverse=True)
    pre = "|".join([re.escape(h) for h in homes] + [r"~", r"\$HOME", r"\$\{HOME\}", r"/Users/[A-Za-z0-9._-]+"])
    kpre = "|".join([re.escape(keyify(h)) for h in homes] + [r"-Users-[A-Za-z0-9_-]+?"])
    out = []
    for n in names:
        old, new = MOVES[n]
        out.append((re.compile(rf"(?P<pre>{pre})/{re.escape('/'.join(old))}(?![\w-]|\.\w)"),
                    r"\g<pre>/" + "/".join(new)))
        out.append((re.compile(rf"(?P<pre>{kpre}){re.escape(keyify('/' + '/'.join(old)))}(?![A-Za-z0-9_.]|--)"),
                    r"\g<pre>" + keyify("/" + "/".join(new))))
    return out


def apply(text, rs):
    total = 0
    for rx, rep in rs:
        text, n = rx.subn(rep, text)
        total += n
    return text, total


def roots(home):
    """Где искать: ~/ai, ~/.claude и код agent-kit, пока он ещё не в ~/ai."""
    out = [os.path.join(home, "ai"), os.path.join(home, ".claude")]
    old = paths("agent-kit", home)[0]
    if os.path.isdir(old) and not os.path.islink(old):
        out.append(old)
    return out


def files(home, personal=False):
    """Живые файлы для замены и проверки (без ~/.claude.json — его разбирают отдельно). Ссылки не проходит."""
    claude = os.path.join(home, ".claude")
    projects = os.path.join(claude, "projects")
    skip_personal = set() if personal else {os.path.join(home, "ai", "knowledge", x) for x in PERSONAL}
    for root in roots(home):
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        for d, dirs, names in os.walk(root):
            if d == claude:
                dirs[:] = [x for x in dirs if x not in CLAUDE_SKIP]
                names = [x for x in names if x not in CLAUDE_SKIP]
            dirs[:] = sorted(x for x in dirs if x not in SKIP_NAMES and os.path.join(d, x) not in skip_personal
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
            for key in sorted(os.listdir(projects)):
                if key != ok and not (key.startswith(ok + "-") and not key.startswith(ok + "--")):
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
                        with open(cj_path, "w", encoding="utf-8") as fh:
                            fh.write(json.dumps(new, ensure_ascii=False, indent=2) + "\n")
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
                with open(p, "wb") as fh:   # на месте: права и сам файл (inode) прежние
                    fh.write(new.encode("utf-8"))
            except OSError as e:
                out(f"сбой    {short(p)}: {e.strerror or e}")
                rc = 1
    out(f"личное ~/ai/knowledge/{{{','.join(PERSONAL)}}} не тронуто — его меняет Мнемозина")
    out(f"итог: файлов {n_files}, замен {n_rep}, папок истории {renamed}, замен в ~/.claude.json {cj_n}"
        + (" — --dry-run, ничего не изменено" if dry_run else ""))
    return rc


def check(home, names=None):
    """Старые пути сделанных переносов в живых файлах. → ([(файл, число)], [имена несделанных переносов])."""
    names = list(names or MOVES)
    moved = [n for n in names if done(n, home)]
    found = []
    if not moved:
        return found, [n for n in names if n not in moved]
    rs = rules(moved, home)
    cj = os.path.join(home, ".claude.json")
    for p in list(files(home, personal=True)) + ([cj] if os.path.isfile(cj) and not os.path.islink(cj) else []):
        text = read_text(p)
        if text is None:
            continue
        k = sum(len(rx.findall(text)) for rx, _ in rs)
        if k:
            found.append((p, k))
    return found, [n for n in names if n not in moved]
