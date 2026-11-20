"""`pantheon supabase migrate <файл> [--dry-run]` — миграция Supabase только из слитого PR (metis-1051, ревизия
автономности 09.11 F1, решение владельца [metis-1049-supabase] «А»).

Запись в базу проекта через MCP окну закрыта (список guard mcp_gate, plugins-by-role.toml). Миграция идёт этой
командой, и только та, что уже в ветке по умолчанию origin (main, а в репозитории без main — например develop,
metis-1295):
  1. файл — supabase/migrations/<версия>_<имя>.sql внутри git-репозитория текущей папки (не папки файла); ни одно
     звено от корня репозитория до файла — не ссылка, без «..»; первая .git над текущей папкой — настоящая папка (не
     файл «gitdir:», не ссылка, без commondir); иначе отказ. В окне направления (PANTHEON_WINDOW в domains.json из
     STATE) репозиторий — только своего направления и не вложенный в другой репозиторий до папки направления.
     Адрес origin в окне — не из .git/config окна, а из STATE/repo-origins/<окно>.json: его пишет сборка окна
     (record_origins из sandbox_build) — репозитории папок направления и их подпапок первого уровня с
     <папка>/.git/config литералом в denyWrite и origin из [merge_repos] направления. В список и в git идёт не
     записанный окном адрес, а канонический, собранный из owner/name (github_url): https://github.com/<o>/<n>.git
     или git@github.com:<o>/<n>.git; имя пользователя, owner и name — только [A-Za-z0-9._-], без «..» («?@», «#@»,
     «\\@», «%40», пробел, второй «@» — не GitHub; круг 5 argus #521). Репозитория нет в списке, списка нет или
     адрес не такой (путь, file://, другой хост) — отказ. Вне окна (команду зовёт владелец) — remote.origin.url
     репозитория: сетевой адрес или абсолютный путь;
  2. git окна в сверке не участвует (класс обходов metis-1295, решение владельца 21.11 metis-1295-class): ни его
     .git/config (remote.<адрес>.url, url.*.insteadOf, http.proxy, http.sslVerify, http.sslCAInfo,
     http.curloptResolve, uploadpack, sshCommand…), ни хуки, ни refs, ни объекты, ни refs/replace. На каждый вызов
     migrate делает свой bare-репозиторий под STATE (STATE/supabase-migrate/git/bare-*: STATE окну не пишется;
     git init --bare --template= — конфиг пустой, его пишет сам git init) и удаляет его после сверки. Каждый git —
     с --git-dir на этот bare, GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1, GIT_NO_REPLACE_OBJECTS=1 и
     --no-replace-objects, без GIT_* вызывающего (GIT_DIR, GIT_CONFIG_* и т. п.), со своим PATH и GIT_SAFE
     (core.hooksPath=/dev/null, core.fsmonitor=false, core.sshCommand=ssh, protocol.ext.allow=never,
     submodule.recurse=false). Чёрного списка ключей конфига окна нет: конфиг окна git migrate не читает, список
     запретов был бы неполон (круг 4 argus #521 нашёл http.*);
  3. ветку по умолчанию называет сервер: `git ls-remote --symref <адрес> HEAD` в своём bare, строка
     «ref: refs/heads/<ветка>\\tHEAD» ровно одна, имя проходит git check-ref-format — иначе отказ. Затем
     `git fetch --depth=1 <адрес> +refs/heads/<ветка>:refs/pantheon/verified-<ветка>` в тот же bare; ref равен
     коммиту, который назвал ls-remote, — иначе отказ «не равен» (ветка сдвинулась между ними). В этой ветке должен
     быть файл по тому же пути, и его blob равен файлу на диске. Нет в ней (новый, не слитый PR, только локальный
     коммит) или отличается — отказ «не из ветки по умолчанию». Объекты (коммит, деревья, blob) читаются cat-file из
     своего bare, и каждый сверяется со своим хешем в Python, хеш файла с диска — тоже в Python (без git). Не совпал —
     отказ «хранилище объектов подменено». Применяется текст blob из ветки, а не файл с диска: подмена файла между
     сверкой и применением ничего не даст. Текст из ветки — строгий UTF-8 без единого «\\» (мета-команды
     psql: \\! запускает shell вне песочницы), без управляющих знаков кроме \\n и \\t, без client_encoding,
     standard_conforming_strings, backslash_quote и без своего BEGIN, COMMIT, ROLLBACK, END, ABORT, START TRANSACTION
     верхнего уровня — иначе отказ (check_sql); psql идёт с PGCLIENTENCODING=UTF8;
  4. база — строка подключения postgresql://… из переменной SUPABASE_DB_URL (её команда не печатает и не пишет в
     журнал); нет или не разобрана — отказ. psql и pg_dump получают её разобранной в PGHOST, PGPORT, PGUSER,
     PGPASSWORD, PGDATABASE (и PGSSLMODE) окружения подпроцесса, а не в argv: argv виден всем процессам Mac;
  5. сверка схемы до и после: `pg_dump --schema-only` до применения; в таблице supabase_migrations.schema_migrations
     (если она есть) версии ещё нет — иначе отказ «уже применена»; применение `psql --single-transaction
     -v ON_ERROR_STOP=1` (сбой — откат всей миграции) вместе с записью версии в schema_migrations; `pg_dump` после.
     Изменение схемы печатается счётом строк, полный дифф и оба снимка — в папке журнала
     ~/.local/state/pantheon/logs/supabase-migrate/<время>-<версия>/ (там же migration.sql и source.txt с веткой и
     хешем её коммита).
     Схема не изменилась — строка «схема не изменилась» (миграция данных так и выглядит).
--dry-run — только шаги 1–3: что будет применено, без базы.

Код 0 — применено (или --dry-run прошёл); 1 — отказ или сбой, причина последней строкой stderr; 2 — не тот вызов.
Модуль-лист без P: STATE передаёт pantheon.py. Инструменты — git (из GIT_PATH), psql и pg_dump из PATH.
Учётных данных git берёт только то, что не из конфига: ssh — ключи ~/.ssh и агент; https к закрытому репозиторию
без помощника учётных данных (он в глобальном конфиге, а тот пуст) не пройдёт — отказ с причиной git.
Сеть: в песочнице окна ls-remote и fetch по ssh падают «Could not resolve hostname» (ssh идёт мимо прокси песочницы,
DNS ей закрыт), а psql к базе — тоже прямое TCP; по https через прокси git проходит. Поэтому окну направления
`pantheon supabase migrate *` выпущен мимо песочницы (SUPABASE_MIGRATE_OUT в pantheon.py, metis-1295, вариант А
владельца 20.11), а форму строки без цепочек держит guard (supabase-migrate-cmd).
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, unquote, urlsplit

USAGE = "pantheon supabase migrate <supabase/migrations/<версия>_<имя>.sql> [--dry-run]"
MIGRATION = re.compile(r"supabase/migrations/(\d{1,20})_([A-Za-z0-9_.-]+)\.sql")
DB_ENV = "SUPABASE_DB_URL"
VERIFIED = "refs/pantheon/verified-"  # + ветка: ref в своём bare (не в .git окна), пишет его только fetch команды
BARES = ("supabase-migrate", "git")  # STATE/supabase-migrate/git/bare-* — свой bare на вызов, удаляется после сверки
URL_SCHEMES = ("postgres", "postgresql")
URL_PARAMS = {"sslmode": "PGSSLMODE"}  # других параметров в адресе нет — отказ, а не молчаливый пропуск


class Refused(Exception):
    """Отказ с причиной для владельца и роли."""


GIT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# как GIT_SAFE в worktree.py: хуки (.git/hooks — reference-transaction на fetch) и fsmonitor из папки окна мимо
# песочницы не исполняются; ssh — свой, протокол ext:: закрыт (metis-1295, возврат argus #521)
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=ssh",
            "-c", "protocol.ext.allow=never", "-c", "submodule.recurse=false"]
# Чёрного списка ключей конфига окна (UNSAFE_CONFIG до metis-1295-class) нет: git этой команды .git окна не читает
# вовсе (решение владельца 21.11), а список запретов неполон по природе — круг 4 argus #521 нашёл http.* и
# remote.<адрес>.url. Глобальный конфиг — пустой (GIT_GLOBAL), системный не читается, локальный — конфиг своего bare.
GIT_GLOBAL = os.devnull


def _env():
    """Окружение git команды: GIT_* вызывающего сняты (GIT_DIR, GIT_CONFIG_COUNT/KEY/VALUE, GIT_OBJECT_DIRECTORY и
    подобные подменили бы адрес или объекты), глобальный конфиг пуст, системный не читается, замен объектов нет."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=GIT_PATH, GIT_CONFIG_GLOBAL=GIT_GLOBAL, GIT_CONFIG_NOSYSTEM="1", GIT_NO_REPLACE_OBJECTS="1")
    return env


def _git(gitdir, *args, text=True):
    """git с --git-dir=gitdir (свой bare команды) и -C gitdir: поиск репозитория не идёт по папке окна."""
    return subprocess.run(["git", "--no-replace-objects", *GIT_SAFE, "--git-dir=" + gitdir, "-C", gitdir, *args],
                          capture_output=True, text=text, timeout=120, env=_env())


def _new_bare(state):
    """Свой пустой bare-репозиторий под STATE (окну не пишется): init --bare --template= — без хуков и шаблонов,
    конфиг пишет сам git init. Refused — STATE нет или init не прошёл."""
    if not state:
        raise Refused("нет STATE — своему репозиторию сверки негде быть")
    root = os.path.join(state, *BARES)
    os.makedirs(root, mode=0o700, exist_ok=True)
    bare = tempfile.mkdtemp(prefix="bare-", dir=root)
    r = _git(bare, "init", "--quiet", "--bare", "--template=")
    if r.returncode != 0:
        shutil.rmtree(bare, ignore_errors=True)
        raise Refused(f"свой репозиторий сверки не создан ({(r.stderr or '').strip()[-200:]})")
    return bare


HASHES = {40: hashlib.sha1, 64: hashlib.sha256}  # длина sha → алгоритм (object-format sha1 и sha256)


def _object(gitdir, kind, sha):
    """Объект kind по sha из gitdir, сверенный со своим хешем: cat-file хеш не сверяет, а свой объект под именем
    слитого (loose-файл) или подменённое дерево выдали бы чужой текст. Пояс к своему bare. Refused — иначе."""
    r = _git(gitdir, "cat-file", kind, sha, text=False)
    algo = HASHES.get(len(sha))
    if r.returncode != 0 or not algo or algo(b"%s %d\0" % (kind.encode(), len(r.stdout)) + r.stdout).hexdigest() != sha:
        raise Refused(f"объект {kind} {sha[:12]} в {gitdir} не прочитан или не совпал со своим хешем — хранилище "
                      "объектов подменено, сверять не с чем (git fsck)")
    return r.stdout


def _tree_entry(tree, name, n):
    """(mode, sha) записи name в сыром дереве (записи «mode имя\\0sha»), None — записи нет."""
    i = 0
    while i < len(tree):
        sp = tree.find(b" ", i)
        nul = tree.find(b"\0", sp + 1) if sp >= 0 else -1
        if nul < 0 or nul + 1 + n > len(tree):
            raise Refused("дерево git не разобрано — сверять не с чем")
        if tree[sp + 1:nul] == name:
            return tree[i:sp], tree[nul + 1:nul + 1 + n].hex()
        i = nul + 1 + n
    return None


def _blob_at(gitdir, commit, rel):
    """(sha, текст) обычного файла rel в коммите commit из gitdir; (None, None) — файла нет. Каждый объект цепочки —
    коммит, деревья, blob — сверен со своим хешем (_object), начиная с sha коммита со слов сервера."""
    head = _object(gitdir, "commit", commit).split(b"\n", 1)[0]
    if not head.startswith(b"tree "):
        raise Refused(f"коммит {commit[:12]} не разобран — сверять не с чем")
    sha, n = head[5:].decode("ascii", "replace"), len(commit) // 2
    parts = rel.split(os.sep)
    for i, part in enumerate(parts):
        entry = _tree_entry(_object(gitdir, "tree", sha), os.fsencode(part), n)
        if entry is None:
            return None, None
        mode, sha = entry
        if mode not in ((b"100644", b"100755") if i == len(parts) - 1 else (b"40000",)):
            return None, None
    return sha, _object(gitdir, "blob", sha)


def _file_hash(path, n):
    """Хеш blob файла с диска, как git hash-object --no-filters, но без git: открыт без перехода по ссылке."""
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as fh:
            data = fh.read()
    except OSError as e:  # подменён на ссылку или не прочитан после locate
        raise Refused(f"{path}: файл не прочитан ({type(e).__name__}) — сверять не с чем") from None
    return HASHES[n](b"blob %d\0" % len(data) + data).hexdigest()


def _repo_root(start):
    """Корень репозитория над папкой start: первая встреченная вверх .git — настоящая папка (не ссылка, не файл
    «gitdir:», без commondir), как _repo в worktree.py. Refused — иначе: gitdir из .git-файла окно кладёт куда
    угодно со своим config (core.sshCommand, uploadpack), а git здесь идёт мимо песочницы."""
    d = os.path.realpath(start)
    while True:
        dotgit = os.path.join(d, ".git")
        if os.path.lexists(dotgit):
            if os.path.islink(dotgit) or not os.path.isdir(dotgit) or os.path.lexists(os.path.join(dotgit, "commondir")):
                raise Refused(f"{dotgit}: не настоящая папка .git (файл gitdir:, ссылка или worktree) — миграция "
                              "только из основной копии репозитория")
            return d
        up = os.path.dirname(d)
        if up == d:
            raise Refused(f"{start}: не в git-репозитории")
        d = up


DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
FORBIDDEN_SQL = re.compile(r"client_encoding|standard_conforming_strings|backslash_quote", re.IGNORECASE)
TXN_WORDS = ("BEGIN", "COMMIT", "ROLLBACK", "END", "ABORT", "START TRANSACTION")


def _outside_literals(sql):
    """Текст SQL без комментариев, строк в кавычках и $$-тел (на их месте пробел). Refused — литерал не закрыт."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c, two = sql[i], sql[i:i + 2]
        if two == "--":
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":
            depth, i = 1, i + 2
            while depth and i < n:
                depth += (sql[i:i + 2] == "/*") - (sql[i:i + 2] == "*/")
                i += 2 if sql[i:i + 2] in ("/*", "*/") else 1
            if depth:
                raise Refused("комментарий /* не закрыт")
        elif c in "'\"":
            esc = c == "'" and i > 0 and sql[i - 1] in "Ee" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_"))
            i += 1
            while i < n and not (sql[i] == c and sql[i + 1:i + 2] != c):
                i += 2 if (sql[i] == c or (esc and sql[i] == "\\")) else 1
            if i >= n:
                raise Refused(f"строка {c} не закрыта")
            i += 1
        elif c == "$" and (m := DOLLAR.match(sql, i)) and not (i and (sql[i - 1].isalnum() or sql[i - 1] in "_$")):
            j = sql.find(m.group(0), m.end())
            if j < 0:
                raise Refused(f"тело {m.group(0)} не закрыто")
            i = j + len(m.group(0))
        else:
            out.append(c)
            i += 1
            continue
        out.append(" ")
    return "".join(out)


def check_sql(rel, body):
    """Отказ миграции, которую psql исполнит не как одну транзакцию SQL. Лексер psql не повторяем — строже его:
    1) текст — строгий UTF-8 (psql идёт с PGCLIENTENCODING=UTF8); 2) ни одного «\\» в байтах, где бы он ни стоял
    (мета-команды psql: \\! — shell вне песочницы, \\copy, \\i, \\o); 3) управляющих знаков нет, кроме \\n и \\t (\\r
    psql считает концом комментария «--»); 4) нет client_encoding, standard_conforming_strings, backslash_quote
    (меняют разбор строк); 5) нет BEGIN, COMMIT, ROLLBACK, END, ABORT, START TRANSACTION верхнего уровня (ломают
    --single-transaction). Пункты 1–4 — по сырому тексту; разбор литералов нужен только пункту 5: его ошибка — ложный
    отказ или пропуск COMMIT, но не исполнение мимо SQL."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(f"{rel}: текст миграции не UTF-8 — не применяю") from None
    if b"\\" in body:
        raise Refused(f"{rel}: обратный слеш запрещён: мета-команды psql; E-строки пишите через chr()/U&")
    bad = sorted({f"U+{ord(c):04X}" for c in text if (ord(c) < 32 and c not in "\n\t") or 127 <= ord(c) < 160})
    if bad:
        raise Refused(f"{rel}: управляющие знаки {', '.join(bad[:5])} — разрешены только \\n и \\t, не применяю")
    if m := FORBIDDEN_SQL.search(text):
        raise Refused(f"{rel}: {m.group(0).lower()} в миграции запрещён — он меняет разбор строк, не применяю")
    try:
        code = _outside_literals(text)
    except Refused as e:
        raise Refused(f"{rel}: текст миграции не разобран ({e}) — не применяю") from None
    for stmt in code.split(";"):
        words = " ".join(stmt.split()).upper()
        if any(words == w or words.startswith(w + " ") for w in TXN_WORDS):
            raise Refused(f"{rel}: в миграции свой {words.split()[0]} верхнего уровня — ломает --single-transaction, "
                          "убери управление транзакцией")


def default_branch(gitdir, url):
    """(ветка по умолчанию, sha её коммита) со слов сервера url (`ls-remote --symref <url> HEAD` в своём bare gitdir;
    адрес — из pinned_remote), а не локальный refs/remotes/origin/HEAD окна: его двигает `git remote set-head`.
    Refused — нет ответа, ответ неоднозначен или имя не ветка."""
    r = _git(gitdir, "ls-remote", "--symref", url, "HEAD")
    if r.returncode != 0:
        raise Refused(f"не узнал ветку по умолчанию origin ({(r.stderr or '').strip()[-200:]}) — без неё сверить нельзя")
    heads = [ln.split("\t")[0].removeprefix("ref: ") for ln in r.stdout.splitlines()
             if ln.startswith("ref: ") and ln.split("\t")[1:] == ["HEAD"]]
    name = heads[0].removeprefix("refs/heads/") if len(heads) == 1 and heads[0].startswith("refs/heads/") else ""
    if not name or _git(gitdir, "check-ref-format", "refs/heads/" + name).returncode != 0:
        raise Refused(f"сервер origin не назвал ветку по умолчанию однозначно (ls-remote --symref: {heads[:3]}) — "
                      "сверить не с чем")
    tips = [ln.split("\t")[0] for ln in r.stdout.splitlines()
            if not ln.startswith("ref: ") and ln.split("\t")[1:] == ["HEAD"]]
    tip = tips[0] if len(tips) == 1 else ""
    if len(tip) not in HASHES or tip.strip("0123456789abcdef"):
        raise Refused(f"сервер origin не назвал коммит ветки {name} однозначно ({tips[:3]}) — сверить не с чем")
    return name, tip


def remote_ok(url):
    """Адрес origin — сетевой: https://, ssh:// или scp-вид «хост:путь». Локальный путь, file://, «транспорт::»,
    знак «-» в начале — нет: такой origin окно кладёт рядом со своим main."""
    if not isinstance(url, str) or not url or url.startswith("-") or "::" in url or any(c in url for c in "\0\r\n"):
        return False
    if "://" in url:
        return url.split("://", 1)[0].lower() in ("https", "ssh")
    return bool(re.fullmatch(r"[A-Za-z0-9._@-]+:[^/].*", url))


# Адрес GitHub: хост ровно github.com, имя пользователя (если есть) и owner/name — только [A-Za-z0-9._-]. Знаки
# «?», «#», «\», «%», пробел и второй «@» в имени пользователя не проходят: с ними git видит другой хост, чем этот
# разбор (https://evil?@github.com/… — git идёт на evil, возврат argus #521, круг 5).
_PART = r"[A-Za-z0-9._-]+"
GITHUB = re.compile(rf"(?:https://(?:{_PART}@)?github\.com/|ssh://(?:{_PART}@)?github\.com(?::\d+)?/"
                    rf"|(?:{_PART}@)?github\.com:/?)({_PART})/({_PART}?)(?:\.git)?/?")


def github_repo(url):
    """«владелец/имя» репозитория GitHub в нижнем регистре по адресу origin, "" — адрес не GitHub (или «.»/«..»
    в owner или name)."""
    m = GITHUB.fullmatch(url) if remote_ok(url) else None
    if not m or any(".." in g or g == "." for g in m.groups()):
        return ""
    return f"{m.group(1)}/{m.group(2)}".lower()


def github_url(url):
    """Канонический адрес репозитория GitHub, собранный из owner/name (github_repo), а не сырой адрес origin:
    https://github.com/<owner>/<name>.git для https, git@github.com:<owner>/<name>.git для ssh и scp-вида.
    "" — адрес не GitHub. Только он идёт в git окна (record_origins, pinned_remote; metis-1295, круг 5 argus #521)."""
    repo = github_repo(url)
    if not repo:
        return ""
    return f"https://github.com/{repo}.git" if url.startswith("https://") else f"git@github.com:{repo}.git"


ORIGINS = "repo-origins"  # STATE/repo-origins/<окно>.json — закреплённые репозитории окна и их origin


def record_origins(state, name, folders, deny_write, repos):
    """Сборка окна направления (sandbox_build) → STATE/repo-origins/<name>.json: {"repos": {папка: адрес origin}}.
    Берутся папки направления и их подпапки первого уровня, у которых .git — настоящая папка, а <папка>/.git/config
    литералом в denyWrite окна (окно не переименует и не создаст такую .git), и адрес origin — репозиторий GitHub из
    [merge_repos] направления (repos): репозиторий, который окно создало до сборки, со своим origin сюда не попадёт.
    STATE окну не пишется; migrate в окне берёт origin только отсюда (metis-1295, возврат argus #521) → словарь."""
    pinned, want, out = set(deny_write), {r.lower() for r in repos or () if isinstance(r, str)}, {}
    for top in folders:
        try:
            names = sorted(n for n in os.listdir(top) if not n.startswith("."))
        except OSError:
            continue
        for d in [top] + [os.path.join(top, n) for n in names]:
            dotgit = os.path.join(d, ".git")
            if (d in out or os.path.islink(d) or os.path.join(dotgit, "config") not in pinned or os.path.islink(dotgit)
                    or not os.path.isdir(dotgit) or os.path.lexists(os.path.join(dotgit, "commondir"))):
                continue
            r = _git(dotgit, "config", "--file", os.path.join(dotgit, "config"), "--get", "remote.origin.url")
            url = r.stdout.strip() if r.returncode == 0 else ""
            if github_repo(url) and github_repo(url) in want:
                out[d] = github_url(url)  # канонический, сырой адрес окна в список не идёт
    path = os.path.join(state, ORIGINS, name + ".json")
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"_comment": "pantheon domains build (sandbox_build): репозитории окна для supabase migrate. Руками "
                   "не править.", "repos": out}, fh, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    return out


def _config_origin(gitdir, repo):
    """Вне окна (команду зовёт владелец) — remote.origin.url из <repo>/.git/config: только этот ключ, файлом
    (`config --file`, без include) через свой bare gitdir; остальной конфиг репозитория git не читает. Адрес —
    сетевой (remote_ok) или абсолютный путь. Refused — иначе."""
    r = _git(gitdir, "config", "--file", os.path.join(repo, ".git", "config"), "--get", "remote.origin.url")
    url = r.stdout.strip() if r.returncode == 0 else ""
    if not (remote_ok(url) or (url.startswith("/") and not any(c in url for c in "\0\r\n"))):
        raise Refused(f"{repo}: remote.origin.url не задан или не адрес ({url[:80]!r}) — сверять не с чем")
    return url


def pinned_remote(state, repo, gitdir=None):
    """Адрес, с которым сверяется ветка по умолчанию. Вне окна — remote.origin.url репозитория (_config_origin через
    свой bare gitdir). В окне — только закреплённый при сборке окна (record_origins): .git/config окна не источник
    доверия — свой git init или bare-репозиторий, переименованный в .git, задал бы origin окна. Из записи — только
    канонический адрес github_url, сырая строка в git не идёт. Refused — списка нет, репозитория в нём нет или адрес
    не GitHub (локальный, другой хост)."""
    win = os.environ.get("PANTHEON_WINDOW") or ""
    if not win or not state:
        if not gitdir:
            raise Refused("нет своего репозитория сверки — origin не прочитать")
        return _config_origin(gitdir, repo)
    path = os.path.join(state, ORIGINS, win + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            pins = json.load(fh).get("repos")
    except (OSError, ValueError, AttributeError) as e:
        raise Refused(f"список закреплённых репозиториев окна {win} не прочитан ({type(e).__name__}) — origin не "
                      "сверить (пересобрать окна: pantheon domains build)") from None
    url = pins.get(repo) if isinstance(pins, dict) else None
    if not isinstance(url, str):
        raise Refused(f"{repo} нет в списке закреплённых репозиториев окна {win} ({path}): новый или не из "
                      "[merge_repos] направления — его origin задало бы окно; миграция только из репозитория, "
                      "закреплённого при сборке окна (pantheon domains build)")
    canon = github_url(url)  # в git — только адрес, собранный из owner/name, а не записанная строка
    if not canon:
        raise Refused(f"закреплённый origin {repo} — локальный путь, file:// или не адрес github.com/<владелец>/<имя> "
                      f"({url[:80]!r}) — сверять не с чем")
    return canon


def own_repo(state, repo):
    """В окне направления (PANTHEON_WINDOW есть в domains.json) — репозиторий только своего направления: самая глубокая
    папка направлений над ним, как _own в worktree.py (модуль-лист без P — копия). Карта не прочитана — отказ."""
    win = os.environ.get("PANTHEON_WINDOW") or ""
    if not win or not state:
        return
    try:
        with open(os.path.join(state, "domains.json"), encoding="utf-8") as fh:
            doms = json.load(fh).get("domains") or {}
    except (OSError, ValueError, AttributeError) as e:
        raise Refused(f"карта направлений domains.json не прочитана ({type(e).__name__}) — чей репозиторий, не знаю")
    if not isinstance(doms, dict) or not isinstance(doms.get(win), list):
        return
    hits = [(os.path.realpath(os.path.expanduser(f)), n) for n, fs in doms.items() if isinstance(fs, list)
            for f in fs if isinstance(f, str) and f]
    hits = [(f, n) for f, n in hits if repo == f or repo.startswith(f.rstrip("/") + "/")]
    top, owner = max(hits, key=lambda x: len(x[0])) if hits else ("", None)
    if owner != win:
        raise Refused(f"{repo} — " + (f"репозиторий направления {owner}" if owner else "вне папок направлений")
                      + f", а окно — {win}: миграция только из своего репозитория")
    d = repo
    while d != top:  # вложенный в другой репозиторий (до папки направления) — его origin задало окно
        d = os.path.dirname(d)
        if os.path.lexists(os.path.join(d, ".git")):
            raise Refused(f"{repo} — вложенный репозиторий внутри {d}: миграция только из корня репозитория "
                          "направления")


def locate(path, state=None):
    """Репозиторий текущей папки (не папки файла: ссылкой в пути подставился бы чужой репозиторий с чужим origin) и
    путь файла в нём. Ни одно звено от корня репозитория до файла — не ссылка, без «..». Refused — иначе."""
    cwd = os.getcwd()  # физический путь, ссылок в нём нет
    repo = _repo_root(cwd)
    own_repo(state, repo)
    full = os.path.join(cwd, path)
    if ".." in path.split(os.sep) or not full.startswith(repo.rstrip("/") + "/"):
        raise Refused(f"{path}: вне репозитория текущей папки {repo} (или с «..») — cd в свой репозиторий")
    rel = os.path.relpath(os.path.normpath(full), repo)
    cur = repo
    for part in rel.split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise Refused(f"{path}: звено {rel[:len(cur) - len(repo) - 1]} — ссылка; миграция только по настоящему пути")
    if not os.path.isfile(cur):
        raise Refused(f"{path}: нет такого файла")
    return repo, rel


def _fetch_verified(bare, url):
    """ls-remote и fetch ветки по умолчанию url в свой bare → (ветка, sha коммита, сверенный с ls-remote)."""
    branch, tip = default_branch(bare, url)
    base, verified = "origin/" + branch, VERIFIED + branch
    # без подмодулей и меток; --depth=1 — нужен только коммит ветки, объекты свои, а не из .git окна
    f = _git(bare, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--depth=1", url,
             f"+refs/heads/{branch}:{verified}")
    if f.returncode != 0:
        raise Refused(f"не удалось получить {base} ({(f.stderr or '').strip()[-200:]}) — без свежей ветки по "
                      "умолчанию сверить нельзя")
    head = _git(bare, "rev-parse", "--verify", "--quiet", verified + "^{commit}")
    if head.returncode != 0:
        raise Refused(f"после fetch нет {verified} ({base})")
    sha = head.stdout.strip()
    if sha != tip:  # ветка сдвинулась между ls-remote и fetch: сверка шла бы не с тем коммитом, что назвал сервер
        raise Refused(f"{verified} ({sha[:12]}) не равен {base} со слов сервера ({tip[:12]}) — ветка сдвинулась "
                      "между ls-remote и fetch, повтори команду")
    return branch, sha


def check_file(path, state=None):
    """Сверка файла с веткой по умолчанию origin → (репозиторий, путь в нём, sha коммита ветки, текст миграции из
    ветки в байтах, версия, имя, «origin/<ветка>»). Refused — файл не из этой ветки или не миграция Supabase.
    git идёт только в свой bare под STATE (_new_bare), .git окна — ни конфиг, ни refs, ни объекты — не читается."""
    repo, rel = locate(path, state)
    m = MIGRATION.fullmatch(rel)
    if not m:
        raise Refused(f"{rel}: не миграция Supabase — нужен файл supabase/migrations/<версия>_<имя>.sql")
    bare = _new_bare(state)
    try:
        url = pinned_remote(state, repo, bare)
        branch, sha = _fetch_verified(bare, url)
        blob, body = _blob_at(bare, sha, rel)
    finally:
        shutil.rmtree(bare, ignore_errors=True)
    base = "origin/" + branch
    if blob is None:
        raise Refused(f"{rel}: файла нет в {base} (не из ветки по умолчанию) — миграция не из слитого PR, применять "
                      "нельзя (сначала слияние)")
    if _file_hash(os.path.join(repo, rel), len(blob)) != blob:
        raise Refused(f"{rel}: файл на диске отличается от {base} — применяется только слитый текст (git checkout "
                      f"{base} -- {rel} или новый PR)")
    check_sql(rel, body)
    return repo, rel, sha, body, m.group(1), m.group(2), base


def pg_env(url):
    """SUPABASE_DB_URL → окружение подпроцесса с PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE (и PGSSLMODE). Адрес не
    идёт в argv psql и pg_dump: argv виден любому процессу Mac (ps). Свои PG* родителя сняты. Refused — не тот адрес."""
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError as e:
        raise Refused(f"{DB_ENV}: адрес не разобран ({type(e).__name__})") from None
    if u.scheme not in URL_SCHEMES or not u.hostname or not u.username or u.fragment:
        raise Refused(f"{DB_ENV}: нужен адрес postgresql://пользователь:пароль@хост[:порт]/база")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST=u.hostname, PGUSER=unquote(u.username), PGDATABASE=unquote(u.path.lstrip("/")) or "postgres",
               PGCLIENTENCODING="UTF8")
    if port:
        env["PGPORT"] = str(port)
    if u.password is not None:
        env["PGPASSWORD"] = unquote(u.password)
    for k, v in parse_qsl(u.query, keep_blank_values=True):
        if k not in URL_PARAMS:
            raise Refused(f"{DB_ENV}: параметр адреса {k!r} не поддержан — только {', '.join(URL_PARAMS)}")
        env[URL_PARAMS[k]] = v
    return env


def _dump(env, out):
    r = subprocess.run(["pg_dump", "--schema-only", "--no-owner", "--no-privileges"],
                       capture_output=True, text=True, errors="replace", timeout=600, env=env)
    if r.returncode != 0:
        raise Refused(f"pg_dump не снял схему (код {r.returncode}): {(r.stderr or '').strip()[-300:]}")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(r.stdout)
    return r.stdout


def _query(env, sql):
    r = subprocess.run(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, errors="replace", timeout=120, env=env)
    if r.returncode != 0:
        raise Refused(f"psql: запрос не выполнен (код {r.returncode}): {(r.stderr or '').strip()[-300:]}")
    return r.stdout.strip()


def apply(state, path, out=print):
    """Применить миграцию path (шаги 1–4 шапки) → путь папки журнала. Refused — отказ или сбой."""
    url = os.environ.get(DB_ENV) or ""
    if not url:
        raise Refused(f"нет строки подключения {DB_ENV} — база не названа, миграция не применена")
    db = pg_env(url)
    repo, rel, sha, body, version, name, base = check_file(path, state=state)
    run = os.path.join(state, "logs", "supabase-migrate", f"{time.strftime('%Y%m%d-%H%M%S')}-{version}")
    os.makedirs(run, mode=0o700, exist_ok=True)
    sql = os.path.join(run, "migration.sql")
    with open(sql, "wb") as fh:
        fh.write(body)
    with open(os.path.join(run, "source.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"{repo}\n{rel}\n{base} {sha}\n")
    before = _dump(db, os.path.join(run, "before.sql"))
    known = _query(db, "select to_regclass('supabase_migrations.schema_migrations') is not null") == "t"
    if known and _query(db, f"select count(*) from supabase_migrations.schema_migrations where version = '{version}'") != "0":
        raise Refused(f"{rel}: версия {version} уже есть в supabase_migrations.schema_migrations — уже применена")
    cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", sql]
    if known:
        cmd += ["-c", f"insert into supabase_migrations.schema_migrations (version) values ('{version}')"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800, env=db)
    with open(os.path.join(run, "psql.log"), "w", encoding="utf-8") as fh:
        fh.write(r.stdout + r.stderr)
    after = _dump(db, os.path.join(run, "after.sql"))
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "before.sql", "after.sql", lineterm=""))
    with open(os.path.join(run, "schema.diff"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(diff) + ("\n" if diff else ""))
    if r.returncode != 0:
        same = "схема та же, что до" if not diff else "СХЕМА ИЗМЕНИЛАСЬ, хотя psql упал — смотри schema.diff"
        raise Refused(f"{rel}: psql упал (код {r.returncode}), транзакция откатилась; {same}; журнал — {run}")
    plus = sum(1 for x in diff if x.startswith("+") and not x.startswith("+++"))
    minus = sum(1 for x in diff if x.startswith("-") and not x.startswith("---"))
    out(f"применено: {rel} из {base} {sha[:12]} ({name})")
    out(f"схема: +{plus} −{minus} строк, дифф — {os.path.join(run, 'schema.diff')}" if diff else "схема не изменилась")
    return run


def main(argv, state):
    if len(argv) < 2 or argv[0] != "migrate" or any(a.startswith("-") and a != "--dry-run" for a in argv[1:]):
        print(f"pantheon supabase: {USAGE}", file=sys.stderr)
        return 2
    files = [a for a in argv[1:] if a != "--dry-run"]
    if len(files) != 1:
        print(f"pantheon supabase: одна миграция за вызов — {USAGE}", file=sys.stderr)
        return 2
    try:
        if "--dry-run" in argv:
            _, rel, sha, body, _, _, base = check_file(files[0], state=state)
            print(f"проверено: {rel} = {base} {sha[:12]} ({len(body)} байт); база не тронута (--dry-run)")
        else:
            apply(state, files[0])
    except Refused as e:
        print(f"pantheon supabase: {e}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as e:  # нет git, psql или pg_dump; таймаут
        print(f"pantheon supabase: сбой ({type(e).__name__}: {e}) — миграция не применена или не проверена",
              file=sys.stderr)
        return 1
    return 0
