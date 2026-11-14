"""`pantheon supabase migrate <файл> [--dry-run]` — миграция Supabase только из слитого PR (metis-1051, ревизия
автономности 09.11 F1, решение владельца [metis-1049-supabase] «А»).

Запись в базу проекта через MCP окну закрыта (список guard mcp_gate, plugins-by-role.toml). Миграция идёт этой
командой, и только та, что уже в origin/main:
  1. файл — supabase/migrations/<версия>_<имя>.sql внутри git-репозитория (не ссылка); иначе отказ;
  2. `git fetch origin +refs/heads/main:refs/pantheon/verified-main` — main origin в свой ref, сверка только с ним
     (короткое имя origin/main не берётся). Есть ветка или метка refs/heads/origin/main, refs/tags/origin/main — отказ
     «неоднозначно». В этом main должен быть файл по тому же пути, и его blob равен файлу на диске. Нет в main
     (новый, не слитый PR, только локальный коммит) или отличается — отказ «не из main». Применяется текст blob из
     main, а не файл с диска: подмена файла между сверкой и применением ничего не даст. git идёт без GIT_* окружения
     (GIT_CONFIG_*, GIT_DIR и т. п. подменили бы origin). Текст из main — строгий UTF-8 без единого «\\» (мета-команды
     psql: \\! запускает shell вне песочницы), без управляющих знаков кроме \\n и \\t, без client_encoding,
     standard_conforming_strings, backslash_quote и без своего BEGIN, COMMIT, ROLLBACK, END, ABORT, START TRANSACTION
     верхнего уровня — иначе отказ (check_sql); psql идёт с PGCLIENTENCODING=UTF8;
  3. база — строка подключения postgresql://… из переменной SUPABASE_DB_URL (её команда не печатает и не пишет в
     журнал); нет или не разобрана — отказ. psql и pg_dump получают её разобранной в PGHOST, PGPORT, PGUSER,
     PGPASSWORD, PGDATABASE (и PGSSLMODE) окружения подпроцесса, а не в argv: argv виден всем процессам Mac;
  4. сверка схемы до и после: `pg_dump --schema-only` до применения; в таблице supabase_migrations.schema_migrations
     (если она есть) версии ещё нет — иначе отказ «уже применена»; применение `psql --single-transaction
     -v ON_ERROR_STOP=1` (сбой — откат всей миграции) вместе с записью версии в schema_migrations; `pg_dump` после.
     Изменение схемы печатается счётом строк, полный дифф и оба снимка — в папке журнала
     ~/.local/state/pantheon/logs/supabase-migrate/<время>-<версия>/ (там же migration.sql с хешем коммита main).
     Схема не изменилась — строка «схема не изменилась» (миграция данных так и выглядит).
--dry-run — только шаги 1–2: что будет применено, без базы.

Код 0 — применено (или --dry-run прошёл); 1 — отказ или сбой, причина последней строкой stderr; 2 — не тот вызов.
Модуль-лист без P: STATE передаёт pantheon.py. Инструменты — git, psql и pg_dump из PATH.
"""
import difflib
import os
import re
import subprocess
import sys
import time
from urllib.parse import parse_qsl, unquote, urlsplit

USAGE = "pantheon supabase migrate <supabase/migrations/<версия>_<имя>.sql> [--dry-run]"
MIGRATION = re.compile(r"supabase/migrations/(\d{1,20})_([A-Za-z0-9_.-]+)\.sql")
DB_ENV = "SUPABASE_DB_URL"
BASE = "origin/main"
VERIFIED = "refs/pantheon/verified-main"  # свой ref: main origin пишет сюда только эта команда
SHADOW = ("refs/heads/origin/main", "refs/tags/origin/main")
URL_SCHEMES = ("postgres", "postgresql")
URL_PARAMS = {"sslmode": "PGSSLMODE"}  # других параметров в адресе нет — отказ, а не молчаливый пропуск


class Refused(Exception):
    """Отказ с причиной для владельца и роли."""


def _git(repo, *args, text=True):
    # GIT_* окружения сняты: GIT_CONFIG_COUNT/KEY/VALUE (url.<чужой>.insteadOf), GIT_DIR, GIT_OBJECT_DIRECTORY и
    # подобные подменили бы origin или объекты, с которыми идёт сверка
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=text, timeout=120, env=env)


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


def check_file(path, fetch=True):
    """Сверка файла с origin/main → (репозиторий, путь в нём, sha коммита main, текст миграции из main в байтах,
    версия, имя). Refused — файл не из main или не миграция Supabase."""
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refused(f"{path}: нет такого файла (или это ссылка)")
    real = os.path.realpath(path)
    top = _git(os.path.dirname(real), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise Refused(f"{path}: не в git-репозитории")
    repo = os.path.realpath(top.stdout.strip())
    rel = os.path.relpath(real, repo)
    m = MIGRATION.fullmatch(rel)
    if not m:
        raise Refused(f"{rel}: не миграция Supabase — нужен файл supabase/migrations/<версия>_<имя>.sql")
    for ref in SHADOW:  # ветка или метка «origin/main» затеняет удалённую ветку в коротком имени — отказ
        if _git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0:
            raise Refused(f"в {repo} есть {ref} — имя {BASE} неоднозначно, удали его (git update-ref -d {ref})")
    if fetch:
        f = _git(repo, "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/main:{VERIFIED}")
        if f.returncode != 0:
            raise Refused(f"не удалось обновить {BASE} ({(f.stderr or '').strip()[-200:]}) — без свежего main "
                          "сверить нельзя")
    head = _git(repo, "rev-parse", "--verify", "--quiet", VERIFIED + "^{commit}")
    if head.returncode != 0:
        raise Refused(f"в {repo} нет {VERIFIED} ({BASE})")
    blob = _git(repo, "rev-parse", "--verify", "--quiet", f"{head.stdout.strip()}:{rel}")
    if blob.returncode != 0:
        raise Refused(f"{rel}: файла нет в {BASE} — миграция не из слитого PR, применять нельзя (сначала слияние)")
    mine = _git(repo, "hash-object", "--", rel)
    if mine.returncode != 0 or mine.stdout.strip() != blob.stdout.strip():
        raise Refused(f"{rel}: файл на диске отличается от {BASE} — применяется только слитый текст (git checkout "
                      f"{BASE} -- {rel} или новый PR)")
    body = _git(repo, "cat-file", "blob", blob.stdout.strip(), text=False)
    if body.returncode != 0:
        raise Refused(f"{rel}: не прочитан blob {BASE}")
    check_sql(rel, body.stdout)
    return repo, rel, head.stdout.strip(), body.stdout, m.group(1), m.group(2)


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
    repo, rel, sha, body, version, name = check_file(path)
    run = os.path.join(state, "logs", "supabase-migrate", f"{time.strftime('%Y%m%d-%H%M%S')}-{version}")
    os.makedirs(run, mode=0o700, exist_ok=True)
    sql = os.path.join(run, "migration.sql")
    with open(sql, "wb") as fh:
        fh.write(body)
    with open(os.path.join(run, "source.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"{repo}\n{rel}\n{BASE} {sha}\n")
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
    out(f"применено: {rel} из {BASE} {sha[:12]} ({name})")
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
            _, rel, sha, body, _, _ = check_file(files[0])
            print(f"проверено: {rel} = {BASE} {sha[:12]} ({len(body)} байт); база не тронута (--dry-run)")
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
