#!/usr/bin/env python3
"""`pantheon supabase migrate` — миграция Supabase только из origin/main (metis-1051).

Запуск: python3 -I plugins/pantheon/tests/test_supabase_migrate.py  (код выхода 0 — все прошли)
Репозиторий с origin (голый репозиторий рядом) на временной папке; psql и pg_dump — заглушки в PATH: pg_dump печатает
файл схемы, psql с -f дописывает текст миграции в схему (так «применение» меняет следующий снимок), запросы
отвечают по переменным заглушки. Проверяется:
- файл в origin/main и равен ему — применён текст из main, схема снята до и после, дифф и журнал в STATE, версия
  записана в schema_migrations, код 0; --dry-run — база не тронута;
- отказ (код 1, psql не вызывался): файла нет в origin/main (новый; закоммичен, но не слит), файл отличается от
  main, путь не supabase/migrations/…, ссылка, нет SUPABASE_DB_URL, версия уже применена;
- psql упал — код 1, причина «откатилась»; вызов без файла — код 2; вызов через `pantheon supabase` (run.py);
- main — только свой ref refs/pantheon/verified-main из fetch: ветка или метка origin/main — отказ «неоднозначно»,
  подвинутый вручную свой ref fetch перезаписывает;
- репозиторий без main (metis-1295): ветку по умолчанию develop называет сервер (ls-remote --symref) — сверка с
  refs/pantheon/verified-develop, несливый файл — отказ «не из ветки по умолчанию», локальный origin/HEAD на другую
  ветку (git remote set-head) не влияет, метка origin/develop — «неоднозначно», сервер ветку не назвал — отказ;
- git мимо песочницы (metis-1295, возврат argus #521): .git-файл «gitdir:» на свой gd с core.sshCommand — отказ, команда
  не выполнилась; .git/config с uploadpack, sshCommand, gitProxy, credential.helper, filter, include, url, protocol —
  отказ без PWNED; хук reference-transaction не исполняется; звено-ссылка в середине пути на чужой клон — отказ;
  репозиторий — от текущей папки, файл другого репозитория и «..» — отказ; окно направления — только свой репозиторий
  (domains.json), битая карта — отказ; мутанты каждой из этих проверок;
- origin окна — только из списка сборки (STATE/repo-origins/<окно>.json, record_origins; возврат двух argus #521):
  новый репозиторий окна со своим origin в папке направления, которая сама не репозиторий, и bare-репозиторий,
  переименованный в .git, — отказ «нет в списке»; подменённый remote.origin.url закреплённого репозитория не влияет
  (ls-remote и fetch по закреплённому адресу); закреплённый локальный адрес и нет списка — отказ; record_origins
  берёт только папку с .git/config в denyWrite и origin из merge_repos; мутант на каждую ветку;
- строка подключения не в argv psql и pg_dump, а в PG* окружения (пароль с %-кодом, sslmode, PG* родителя сняты);
  адрес не postgresql://, без пользователя, с чужим параметром или плохим портом — отказ;
- текст миграции (check_sql): «\\» где угодно, не UTF-8, управляющие знаки кроме \\n и \\t (\\r), client_encoding,
  standard_conforming_strings, backslash_quote, свой BEGIN/COMMIT/ROLLBACK/START — отказ; psql с PGCLIENTENCODING=UTF8;
- мутанты внутри теста: без проверки «есть в main», без сверки blob, без проверки «уже применена», без отказа на
  неоднозначное имя, короткое имя вместо своего ref, fetch не в свой ref, адрес в argv, psql без PG*, PG* родителя
  не сняты, чужой параметр адреса молча — тест их ловит.
"""
import atexit
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import zlib
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402 — путь теста выше

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
MOD = os.path.join(LIB, "supabase_migrate.py")
ROOT = os.path.realpath(mkroot("supabase-migrate-test-", "/var/tmp" if sys.platform.startswith("linux") else None))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


def write_bytes(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


def write(p, text, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(p, mode)


GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": ROOT}


def git(cwd, *args, input=None):
    # хуки окна — только для проверяемой команды: подготовка теста (update-ref) свой хук не исполняет
    r = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd,
                       capture_output=True, text=True, input=input,
                       env={**os.environ, **GIT_ENV}, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


# заглушки psql и pg_dump: журнал вызовов, схема — файл FAKE_SCHEMA
BIN = os.path.join(ROOT, "bin")
LOG = os.path.join(ROOT, "calls.log")
SCHEMA = os.path.join(ROOT, "schema.sql")
ENVLOG = os.path.join(ROOT, "env.log")
PGLINE = ('echo "$0 host=$PGHOST port=$PGPORT user=$PGUSER pw=$PGPASSWORD db=$PGDATABASE ssl=$PGSSLMODE enc=$PGCLIENTENCODING" '
          '>> "$FAKE_ENVLOG"\n')
write(os.path.join(BIN, "pg_dump"), '#!/bin/sh\necho "pg_dump $*" >> "$FAKE_LOG"\n' + PGLINE + 'cat "$FAKE_SCHEMA"\n',
      0o755)
write(os.path.join(BIN, "psql"), r'''#!/bin/sh
echo "psql $*" >> "$FAKE_LOG"
''' + PGLINE + r'''
file=
sql=
while [ $# -gt 0 ]; do
    case $1 in
        -f) file=$2; shift ;;
        -c) sql=$2; shift ;;
    esac
    shift
done
if [ -n "$file" ]; then
    [ "${FAKE_APPLY_FAIL:-}" = 1 ] && { echo "ERROR: syntax" >&2; exit 3; }
    cat "$file" >> "$FAKE_SCHEMA"
    [ -n "$sql" ] && echo "$sql" >> "$FAKE_LOG"
    exit 0
fi
case $sql in
    *to_regclass*) echo "${FAKE_TABLE:-t}" ;;
    *count*) echo "${FAKE_COUNT:-0}" ;;
esac
''', 0o755)

# origin и рабочая копия
ORIGIN = os.path.join(ROOT, "origin.git")
REPO = os.path.join(ROOT, "repo")
REPO2 = os.path.join(ROOT, "repo2")
R3, GD3, R4, R5 = (os.path.join(ROOT, n) for n in ("r3", "gd3", "r4", "r5"))
REPOS = [REPO, REPO2, R3, R4, R5]
git(ROOT, "init", "--bare", ORIGIN)
git(ROOT, "clone", ORIGIN, REPO)
MIG = "supabase/migrations/20260101000000_init.sql"
MAIN_SQL = "create table t (id int);\n"
write(os.path.join(REPO, MIG), MAIN_SQL)
write(os.path.join(REPO, "README.md"), "x\n")
# миграции в main, которые psql исполнил бы не одной транзакцией SQL, и честная со «страшными» словами внутри литералов
BAD_SQL = {  # имя → (байты, слово причины в последней строке)
    "20260110000000_shell.sql": (b"create table a (i int);\n  \\! touch /tmp/pwn\n", "обратный слеш"),
    "20260111000000_inline.sql": (b"select 1 \\o /tmp/out\n;\n", "обратный слеш"),
    # обходы разбора из проверки безопасности 5501bf3f: $ после не-ASCII, \r в комментарии, кодировка, E-строки
    "20260117000000_dollar.sql": ("select ä$$x;\n\\! id\n$$;\n".encode(), "обратный слеш"),
    "20260118000000_cr.sql": (b"-- note\rcommit;\ncreate table d (i int);\n", "управляющие знаки"),
    "20260119000000_ff.sql": (b"select 1;\x0c\n", "управляющие знаки"),
    "20260120000000_sjis.sql": (b"select '\x95';\n", "не UTF-8"),
    "20260121000000_enc.sql": (b"SET Client_Encoding TO 'SJIS';\nselect 1;\n", "client_encoding"),
    "20260122000000_scs.sql": (b"set standard_conforming_strings = off;\n", "standard_conforming_strings"),
    "20260123000000_bq.sql": (b"/* x */ set backslash_quote = on;\n", "backslash_quote"),
    "20260124000000_estr.sql": (b"select E'\\';\n", "обратный слеш"),
    "20260112000000_begin.sql": (b"BEGIN;\ncreate table b (i int);\nCOMMIT;\n", "свой BEGIN"),
    "20260125000000_commit.sql": (b"create table x (i int);\ncommit;\ncreate table y (i int);\n", "свой COMMIT"),
    # $ — знак идентификатора: a$$x$$ не открывает тело $x$, и COMMIT за ним виден (argus 14.11, Д1)
    "20260126000000_ident.sql": (b"select 1 as a$$x$$;\nCOMMIT;\nselect 1 as b$x$;\n", "свой COMMIT"),
    "20260113000000_rollback.sql": (b"create table c (i int);\n  rollback ;\n", "свой ROLLBACK"),
    "20260114000000_start.sql": (b"start  transaction isolation level serializable;\n", "свой START"),
    "20260115000000_open.sql": ("select 'не закрыта;\n".encode(), "не разобран")}
GOOD_SQL = ("-- begin; в комментарии\n/* commit; /* вложенный */ x */\n"
            "create function f() returns int language plpgsql as $fn$\nbegin\n\treturn 1;\nend;\n$fn$;\n"
            "select 'it''s; commit', \"end\", chr(92), 'приём';\nselect $$ begin; $$;\n")
for name, (raw, _) in BAD_SQL.items():
    os.makedirs(os.path.join(REPO, "supabase/migrations"), exist_ok=True)
    with open(os.path.join(REPO, "supabase/migrations", name), "wb") as fh:
        fh.write(raw)
GOOD = "supabase/migrations/20260116000000_good.sql"
write(os.path.join(REPO, GOOD), GOOD_SQL)
git(REPO, "add", "-A")
git(REPO, "commit", "-m", "init")
git(REPO, "push", "origin", "main")
LOCAL = "supabase/migrations/20260102000000_local.sql"  # закоммичена, но не в origin/main
write(os.path.join(REPO, LOCAL), "drop table t;\n")
git(REPO, "add", LOCAL)
git(REPO, "commit", "-m", "local")
NEW = "supabase/migrations/20260103000000_new.sql"  # не закоммичена вовсе
write(os.path.join(REPO, NEW), "drop table t;\n")
STATE = os.path.join(ROOT, "state")
URL = "postgresql://u:secret@db.example:6543/postgres"
SRC = open(MOD, encoding="utf-8").read()


def load(src=SRC):
    spec = importlib.util.spec_from_file_location("supabase_migrate_t", MOD)
    m = importlib.util.module_from_spec(spec)
    exec(compile(src, MOD, "exec"), m.__dict__)
    return m


def call(argv, env=None, mod=None, cwd=None):
    """main модуля в этом процессе → (код, stdout, stderr, вызовы psql/pg_dump). Текущая папка — cwd, без него —
    репозиторий файла из argv (команда берёт репозиторий от текущей папки, metis-1295)."""
    if cwd is None:
        hit = [r for r in REPOS for a in argv[1:] if a.startswith(r + os.sep)]
        cwd = hit[0] if hit else REPO
    here = os.getcwd()
    os.chdir(cwd)
    try:
        return _call(argv, env, mod)
    finally:
        os.chdir(here)


def _call(argv, env, mod):
    write(SCHEMA, "create schema public;\n")
    write(LOG, "")
    write(ENVLOG, "")
    keep = dict(os.environ)
    os.environ.update({**GIT_ENV, "PATH": BIN + os.pathsep + keep.get("PATH", ""), "FAKE_LOG": LOG,
                       "FAKE_ENVLOG": ENVLOG, "FAKE_SCHEMA": SCHEMA, "SUPABASE_DB_URL": URL})
    for k in ("FAKE_TABLE", "FAKE_COUNT", "FAKE_APPLY_FAIL", "PGHOST", "PGPASSWORD", "PGSSLMODE",
              "PANTHEON_WINDOW"):
        os.environ.pop(k, None)
    for k, v in (env or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = (mod or load()).main(argv, STATE)
    finally:
        os.environ.clear()
        os.environ.update(keep)
    return code, out.getvalue(), err.getvalue(), open(LOG, encoding="utf-8").read()


def p(rel):
    return os.path.join(REPO, rel)


# --- применение из main ---
code, out, err, calls = call(["migrate", p(MIG)])
runs = sorted(os.listdir(os.path.join(STATE, "logs", "supabase-migrate"))) if code == 0 else []
run = os.path.join(STATE, "logs", "supabase-migrate", runs[-1]) if runs else ""
check("файл из origin/main: код 0, «применено», схема изменилась (+1 строка)",
      code == 0 and "применено: " + MIG in out and "схема: +1 −0" in out, (code, out, err))
check("схема снята до и после, psql одним --single-transaction с ON_ERROR_STOP",
      calls.count("pg_dump --schema-only") == 2 and "--single-transaction" in calls and "ON_ERROR_STOP=1" in calls, calls)
check("версия записана в schema_migrations в той же транзакции",
      "insert into supabase_migrations.schema_migrations (version) values ('20260101000000')" in calls, calls)
check("журнал: migration.sql — текст из main, before/after/schema.diff, источник с sha main",
      run and open(os.path.join(run, "migration.sql"), encoding="utf-8").read() == MAIN_SQL
      and all(os.path.isfile(os.path.join(run, f)) for f in ("before.sql", "after.sql", "schema.diff", "source.txt"))
      and "+create table t (id int);" in open(os.path.join(run, "schema.diff"), encoding="utf-8").read(), run)
check("строка подключения не попала ни в вывод, ни в журнал",
      "secret" not in out + err and not any("secret" in open(os.path.join(run, f), encoding="utf-8").read()
                                            for f in os.listdir(run)) if run else False)
envs = open(ENVLOG, encoding="utf-8").read().splitlines()
check("строки подключения нет в argv psql и pg_dump (ни пароля, ни хоста)",
      calls.strip() and "secret" not in calls and "db.example" not in calls and "postgres" + "ql://" not in calls, calls)
check("psql и pg_dump получили адрес разобранным в PG* окружения — каждый вызов (2 pg_dump + 3 psql)",
      len(envs) == 5 and all(x.endswith(" host=db.example port=6543 user=u pw=secret db=postgres ssl= enc=UTF8") for x in envs),
      envs)
code, out, err, calls = call(["migrate", p(MIG)], {"SUPABASE_DB_URL": "postgresql://u:p%40ss@db.example/app?sslmode=require",
                                                    "PGHOST": "evil.example", "PGSSLMODE": "disable"})
envs = open(ENVLOG, encoding="utf-8").read().splitlines()
check("пароль с %-кодом раскодирован, sslmode → PGSSLMODE, PG* родителя не протекли, порт не задан — не задан",
      code == 0 and envs and all(x.endswith(" host=db.example port= user=u pw=p@ss db=app ssl=require enc=UTF8") for x in envs),
      (code, err, envs))
for bad, word in (("host=db.example user=u password=secret", "нужен адрес"), ("postgresql://db.example/x", "нужен адрес"),
                  ("postgresql://u:secret@db.example/x?options=-c%20x", "не поддержан"),
                  ("postgresql://u:secret@db.example:99999/x", "не разобран")):
    code, out, err, calls = call(["migrate", p(MIG)], {"SUPABASE_DB_URL": bad})
    check(f"адрес {bad.split('@')[-1][:30]!r} — код 1, «{word}», база не тронута, пароля нет в выводе",
          code == 1 and word in err.strip().splitlines()[-1] and not calls.strip() and "secret" not in out + err,
          (code, err, calls))
code, out, err, calls = call(["migrate", p(MIG)], {"FAKE_TABLE": "f"})
check("таблицы schema_migrations нет — применено без записи версии", code == 0 and "insert into" not in calls, calls)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"], {"SUPABASE_DB_URL": None})
check("--dry-run: код 0, база не тронута (ни psql, ни pg_dump), без SUPABASE_DB_URL",
      code == 0 and "проверено: " + MIG in out and not calls.strip(), (code, out, err, calls))

# --- отказы ---
for rel, what, word in ((LOCAL, "закоммичен, но не в origin/main", "нет в origin/main"),
                        (NEW, "новый, не закоммичен", "нет в origin/main")):
    code, out, err, calls = call(["migrate", p(rel)])
    check(f"файл {what} — код 1, «{word}», база не тронута", code == 1 and word in err.strip().splitlines()[-1]
          and "psql" not in calls and "pg_dump" not in calls, (code, err, calls))
write(p(MIG), MAIN_SQL + "drop table t;\n")
code, out, err, calls = call(["migrate", p(MIG)])
check("файл отличается от origin/main — код 1, «отличается», база не тронута",
      code == 1 and "отличается" in err and not calls.strip(), (code, err, calls))
write(p(MIG), MAIN_SQL)
write(p("sql/20260101000000_x.sql"), "x;\n")
code, out, err, calls = call(["migrate", p("sql/20260101000000_x.sql")])
check("путь не supabase/migrations/… — код 1", code == 1 and "не миграция Supabase" in err, err)
code, out, err, calls = call(["migrate", p("README.md"), "--dry-run"])
check("файл из origin/main, но не миграция (README.md) — код 1", code == 1 and "не миграция Supabase" in err, err)
os.symlink(p(MIG), p("supabase/migrations/20260104000000_link.sql"))
code, out, err, calls = call(["migrate", p("supabase/migrations/20260104000000_link.sql")])
check("ссылка — код 1", code == 1 and "ссылка" in err and not calls.strip(), err)
os.remove(p("supabase/migrations/20260104000000_link.sql"))
code, out, err, calls = call(["migrate", p(MIG)], {"SUPABASE_DB_URL": None})
check("нет SUPABASE_DB_URL — код 1, база не названа", code == 1 and "SUPABASE_DB_URL" in err and not calls.strip(), err)
code, out, err, calls = call(["migrate", p(MIG)], {"FAKE_COUNT": "1"})
check("версия уже в schema_migrations — код 1, «уже применена», миграция не запускалась",
      code == 1 and "уже применена" in err and " -f " not in calls, (err, calls))
code, out, err, calls = call(["migrate", p(MIG)], {"FAKE_APPLY_FAIL": "1"})
check("psql упал — код 1, «откатилась», схема та же", code == 1 and "откатилась" in err and "схема та же" in err, err)
for argv in ([], ["migrate"], ["apply", p(MIG)], ["migrate", p(MIG), p(LOCAL)], ["migrate", p(MIG), "--force"]):
    code, out, err, calls = call(argv)
    check(f"вызов {argv[:1] + ['…'] * (len(argv) > 1)} не тот — код 2", code == 2, (argv, code, err))

# --- текст миграции: без мета-команд psql и своего управления транзакцией ---
for name, (_, word) in BAD_SQL.items():
    code, out, err, calls = call(["migrate", p("supabase/migrations/" + name)])
    check(f"{name} — код 1, «{word}» последней строкой, psql -f не вызывался",
          code == 1 and word in err.strip().splitlines()[-1] and " -f " not in calls, (code, err, calls))
code, out, err, calls = call(["migrate", p(GOOD)])
check("begin/commit внутри комментариев, строк, \"end\" и $$-тел, табуляция, chr(92) — не отказ, применено",
      code == 0 and " -f " in calls, (code, err))

# --- git без GIT_* окружения: url.<чужой>.insteadOf из GIT_CONFIG_* не подменяет origin ---
EVIL = os.path.join(ROOT, "evil.git")
git(ROOT, "init", "--bare", EVIL)
git(REPO, "push", EVIL, "HEAD:refs/heads/main")  # в «чужом» main есть LOCAL
GIT_EVIL = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{EVIL}.insteadOf", "GIT_CONFIG_VALUE_0": ORIGIN}
code, out, err, calls = call(["migrate", p(LOCAL), "--dry-run"], GIT_EVIL)
check("GIT_CONFIG_* подменяет origin на чужой репозиторий — снят, LOCAL — отказ «нет в origin/main»",
      code == 1 and "нет в origin/main" in err, (code, err))

# --- main берётся только из своего ref, а не по короткому имени origin/main ---
for ref in ("refs/tags/origin/main", "refs/heads/origin/main"):
    git(REPO, "update-ref", ref, "HEAD")  # HEAD — локальный коммит с LOCAL
    code, out, err, calls = call(["migrate", p(MIG), "--dry-run"])
    check(f"есть {ref} — код 1, «неоднозначно»", code == 1 and "неоднозначно" in err.strip().splitlines()[-1], err)
    git(REPO, "update-ref", "-d", ref)
git(REPO, "update-ref", "refs/pantheon/verified-main", "HEAD")
code, out, err, calls = call(["migrate", p(LOCAL), "--dry-run"])
check("свой ref подвинут на локальный коммит — fetch его перезаписал из origin, LOCAL — отказ",
      code == 1 and "нет в origin/main" in err, (code, err))
check("refs/pantheon/verified-main после сверки — main origin", git(REPO, "rev-parse", "refs/pantheon/verified-main")
      == git(ORIGIN, "rev-parse", "refs/heads/main"))

# --- репозиторий без main: ветка по умолчанию develop со слов сервера (metis-1295) ---
ORIGIN2 = os.path.join(ROOT, "origin2.git")
git(ROOT, "init", "--bare", "--initial-branch=develop", ORIGIN2)
git(ROOT, "clone", ORIGIN2, REPO2)
write(os.path.join(REPO2, MIG), MAIN_SQL)
git(REPO2, "add", "-A")
git(REPO2, "commit", "-m", "init")
git(REPO2, "push", "origin", "HEAD:refs/heads/develop")  # имя локальной ветки клона пустого репозитория — по версии git
write(os.path.join(REPO2, LOCAL), "drop table t;\n")  # закоммичена, в develop не слита, лежит в ветке feature
git(REPO2, "add", LOCAL)
git(REPO2, "commit", "-m", "local")
git(REPO2, "push", "origin", "HEAD:refs/heads/feature")
git(REPO2, "fetch", "origin")
assert "main" not in git(ORIGIN2, "branch", "--list")


def p2(rel):
    return os.path.join(REPO2, rel)


code, out, err, calls = call(["migrate", p2(MIG), "--dry-run"])
check("без main, по умолчанию develop: файл из develop — код 0, «= origin/develop»",
      code == 0 and f"проверено: {MIG} = origin/develop" in out, (code, out, err))
check("свой ref refs/pantheon/verified-develop — develop origin, verified-main не заведён",
      git(REPO2, "rev-parse", "refs/pantheon/verified-develop") == git(ORIGIN2, "rev-parse", "refs/heads/develop")
      and "verified-main" not in git(REPO2, "for-each-ref", "refs/pantheon"))
code, out, err, calls = call(["migrate", p2(MIG)])
check("без main: применено из origin/develop, source.txt с веткой", code == 0 and "из origin/develop" in out
      and " -f " in calls, (code, out, err))
code, out, err, calls = call(["migrate", p2(LOCAL), "--dry-run"])
check("без main: файл не слит в develop — код 1, «не из ветки по умолчанию» последней строкой",
      code == 1 and "не из ветки по умолчанию" in err.strip().splitlines()[-1] and "origin/develop" in err, (code, err))
git(REPO2, "remote", "set-head", "origin", "feature")  # локальный origin/HEAD → feature, где LOCAL есть
assert git(REPO2, "symbolic-ref", "refs/remotes/origin/HEAD").strip() == "refs/remotes/origin/feature"
code, out, err, calls = call(["migrate", p2(LOCAL), "--dry-run"])
check("локальный origin/HEAD на feature (git remote set-head) не влияет — LOCAL всё равно отказ, сверка с develop",
      code == 1 and "не из ветки по умолчанию" in err and "origin/develop" in err, (code, err))
git(REPO2, "update-ref", "refs/tags/origin/develop", "HEAD")
code, out, err, calls = call(["migrate", p2(MIG), "--dry-run"])
check("без main: есть refs/tags/origin/develop — код 1, «неоднозначно»",
      code == 1 and "неоднозначно" in err.strip().splitlines()[-1], err)
git(REPO2, "update-ref", "-d", "refs/tags/origin/develop")
# HEAD сервера отцеплен от ветки: ls-remote --symref даёт «<sha>\tHEAD» без строки «ref:» — ветку не назвать
git(ORIGIN2, "update-ref", "--no-deref", "HEAD", "develop")
code, out, err, calls = call(["migrate", p2(MIG), "--dry-run"])
check("сервер не назвал ветку по умолчанию — код 1, «однозначно» последней строкой, без догадки",
      code == 1 and "однозначно" in err.strip().splitlines()[-1], (code, err))
git(ORIGIN2, "symbolic-ref", "HEAD", "refs/heads/develop")

# --- git мимо песочницы: .git и его конфиг пишет окно (metis-1295, возврат argus #521) ---
PWNED = os.path.join(ROOT, "PWNED")
# r3/.git — файл «gitdir: ../gd3», в gd3/config core.sshCommand и origin по ssh: без проверки ls-remote исполнил бы его
git(ROOT, "clone", ORIGIN, R3)
shutil.move(os.path.join(R3, ".git"), GD3)
write(os.path.join(R3, ".git"), "gitdir: ../gd3\n")
git(R3, "config", "core.sshCommand", f"touch {PWNED} #")
git(R3, "remote", "set-url", "origin", "ssh://example.invalid/x.git")
code, out, err, calls = call(["migrate", os.path.join(R3, MIG), "--dry-run"])
check("r3/.git — файл gitdir: на свой gd3 с core.sshCommand — код 1, «настоящая папка .git», команда не выполнилась",
      code == 1 and "настоящая папка .git" in err.strip().splitlines()[-1] and not os.path.exists(PWNED), (code, err))
# r4 — настоящая .git, но конфиг задаёт команду или транспорт
git(ROOT, "clone", ORIGIN, R4)
UPLOAD = f"touch {PWNED}; git-upload-pack"
for key, val in (("remote.origin.uploadPack", UPLOAD), ("core.sshCommand", f"touch {PWNED} #"),
                 ("core.gitProxy", "x"), ("credential.helper", f"!touch {PWNED}"), ("filter.x.clean", "x"),
                 ("include.path", os.devnull), ("url.file:///x.insteadOf", ORIGIN), ("protocol.ext.allow", "always")):
    git(R4, "config", key, val)
    code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"])
    check(f".git/config с {key} — код 1, ключ в причине последней строкой, команда не выполнилась",
          code == 1 and key.lower() in err.strip().splitlines()[-1] and not os.path.exists(PWNED), (code, err))
    git(R4, "config", "--unset", key)
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"])
check("r4 без опасных ключей (remote.origin.url, branch.*) — код 0", code == 0, (code, err))
# хук .git/hooks/reference-transaction: fetch пишет свой ref — без core.hooksPath=/dev/null хук исполнился бы
write(os.path.join(R4, ".git", "hooks", "reference-transaction"), f"#!/bin/sh\ntouch {PWNED}\n", 0o755)
git(R4, "update-ref", "-d", "refs/pantheon/verified-main")
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"])
check("хук reference-transaction в .git/hooks на fetch не исполнен, код 0", code == 0 and not os.path.exists(PWNED),
      (code, err))

# хранилище объектов (.git/objects, refs/replace) пишет окно, cat-file хеш не сверяет (metis-1295, второй argus #521)
EVIL_SQL = b"drop table everything;\n"
GOOD_BLOB = git(REPO, "rev-parse", f"refs/pantheon/verified-main:{MIG}").strip()
EVIL_BLOB = git(REPO, "hash-object", "-w", "--stdin", input=EVIL_SQL.decode()).strip()
OK_DRY = f"({len(MAIN_SQL.encode())} байт)"


def plant(sha, kind, body):
    """Свой zlib-объект под именем sha (loose-файл, как пишет окно) → (путь, прежние байты или None)."""
    pth = os.path.join(REPO, ".git", "objects", sha[:2], sha[2:])
    old = open(pth, "rb").read() if os.path.exists(pth) else None
    if old is not None:
        os.remove(pth)  # клон по локальному пути делит объекты с origin ссылками — не писать в общий файл
    write_bytes(pth, zlib.compress(b"%s %d\0" % (kind, len(body)) + body))
    return pth, old


def unplant(pth, old):
    os.remove(pth)
    if old is not None:
        write_bytes(pth, old)


git(REPO, "replace", GOOD_BLOB, EVIL_BLOB)
check("подготовка: git replace подменяет слитый blob для cat-file", git(REPO, "cat-file", "blob", GOOD_BLOB).encode()
      == EVIL_SQL)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"])
check("git replace <слитый blob> <свой> не действует — код 0, прочитан слитый текст", code == 0 and OK_DRY in out,
      (code, out, err))
REPLACE_OUT = (code, out)
git(REPO, "replace", "-d", GOOD_BLOB)
LOOSE = plant(GOOD_BLOB, b"blob", EVIL_SQL)
check("подготовка: свой loose-объект под именем слитого blob читается cat-file",
      git(REPO, "cat-file", "blob", GOOD_BLOB).encode() == EVIL_SQL)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"])
check("подменённый loose-объект слитого blob — код 1, «подменено» последней строкой",
      code == 1 and "подменено" in err.strip().splitlines()[-1], (code, err))
unplant(*LOOSE)
# дерево supabase/migrations под своим именем указывает файл на чужой blob, на диске — тот же чужой текст
DIR_TREE = git(REPO, "rev-parse", "refs/pantheon/verified-main:supabase/migrations").strip()
RAW = subprocess.run(["git", "cat-file", "tree", DIR_TREE], cwd=REPO, capture_output=True, check=True).stdout
assert RAW.count(bytes.fromhex(GOOD_BLOB)) == 1
TREE = plant(DIR_TREE, b"tree", RAW.replace(bytes.fromhex(GOOD_BLOB), bytes.fromhex(EVIL_BLOB)))
write_bytes(p(MIG), EVIL_SQL)
check("подготовка: rev-parse через подменённое дерево даёт чужой blob",
      git(REPO, "rev-parse", f"refs/pantheon/verified-main:{MIG}").strip() == EVIL_BLOB)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"])
check("подменённое дерево (файл на диске = чужой blob) — код 1, «подменено» последней строкой",
      code == 1 and "подменено" in err.strip().splitlines()[-1], (code, err))
unplant(*TREE)
write(p(MIG), MAIN_SQL)

# подмодуль: fetch по умолчанию (on-demand) идёт и в подмодуль, а его config ($GIT_DIR/modules/<имя>/config) пишет
# окно и check_config его не видит — uploadpack оттуда исполнился бы мимо песочницы (metis-1295, первый argus #521, Б1)
GF = ("-c", "protocol.file.allow=always")
SUBO, SUBW, ORIGIN7, W7, R7 = (os.path.join(ROOT, n) for n in ("sub.git", "subw", "origin7.git", "w7", "r7"))
git(ROOT, "init", "--bare", SUBO)
git(ROOT, "init", SUBW)
write(os.path.join(SUBW, "a"), "a\n")
git(SUBW, "add", "a")
git(SUBW, "commit", "-m", "a")
git(SUBW, "push", SUBO, "HEAD:main")
git(ROOT, "init", "--bare", ORIGIN7)
git(ROOT, "init", W7)
write(os.path.join(W7, MIG), MAIN_SQL)
git(W7, *GF, "submodule", "add", SUBO, "sub")
git(W7, "add", "-A")
git(W7, "commit", "-m", "init")
git(W7, "push", ORIGIN7, "HEAD:main")
git(ROOT, "clone", ORIGIN7, R7)
git(R7, *GF, "submodule", "update", "--init")
SUBCFG = os.path.join(R7, ".git", "modules", "sub", "config")
git(R7, "config", "-f", SUBCFG, "protocol.file.allow", "always")
git(R7, "config", "-f", SUBCFG, "remote.origin.uploadpack", UPLOAD)
write(os.path.join(SUBW, "a"), "b\n")  # новый коммит подмодуля в origin7: fetch on-demand пошёл бы за ним
git(SUBW, "commit", "-am", "b")
git(SUBW, "push", SUBO, "HEAD:main")
git(os.path.join(W7, "sub"), *GF, "pull", "origin", "main")
git(W7, "commit", "-am", "bump")
git(W7, "push", ORIGIN7, "HEAD:main")
R7M = os.path.join(ROOT, "r7m")  # копия до fetch — для мутанта: после fetch идти в подмодуль уже не за чем
shutil.copytree(R7, R7M, symlinks=True)
if os.path.exists(PWNED):
    os.remove(PWNED)
code, out, err, calls = call(["migrate", os.path.join(R7, MIG), "--dry-run"], cwd=R7)
check("uploadpack в config подмодуля (.git/modules/sub/config) на fetch не исполнен, код 0",
      code == 0 and not os.path.exists(PWNED), (code, err))
# .git/commondir: git возьмёт config и объекты из папки, которую назвал файл окна
write(os.path.join(R4, ".git", "commondir"), "../../r3\n")
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"])
check("r4/.git/commondir — код 1, «настоящая папка .git» последней строкой",
      code == 1 and "настоящая папка .git" in err.strip().splitlines()[-1], (code, err))
os.remove(os.path.join(R4, ".git", "commondir"))
# PATH: git ищется только в GIT_PATH — свой git первым в PATH не исполнен
FAKEBIN, GITMARK = os.path.join(ROOT, "fakegit"), os.path.join(ROOT, "GITMARK")
REAL_GIT = shutil.which("git")
write(os.path.join(FAKEBIN, "git"), f'#!/bin/sh\ntouch {GITMARK}\nexec {REAL_GIT} "$@"\n', 0o755)
FAKE_PATH = {"PATH": FAKEBIN + os.pathsep + BIN + os.pathsep + os.environ.get("PATH", "")}
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"], FAKE_PATH)
check("свой git первым в PATH не исполнен, код 0", code == 0 and not os.path.exists(GITMARK), (code, err))
# файл подменён на ссылку после locate: хеш с диска — отказ Refused, а не трассировка и не текст по ссылке
LINKED = os.path.join(ROOT, "linked.sql")
os.symlink(p(MIG), LINKED)
try:
    load()._file_hash(LINKED, 40)
    LINK_ERR = ""
except Exception as e:  # проверяется именно класс исключения
    LINK_ERR = type(e).__name__
check("хеш файла-ссылки — Refused «не прочитан»", LINK_ERR == "Refused", LINK_ERR)
# r5/supabase — ссылка на чужой клон (его origin — evil.git, где LOCAL «слит»): репозиторий берётся от текущей папки,
# звено-ссылка в середине пути — отказ; раньше realpath файла уводил в чужой репозиторий с чужим origin, код 0
EVILREPO = os.path.join(ROOT, "evilrepo")
git(ROOT, "clone", EVIL, EVILREPO)
git(ROOT, "clone", ORIGIN, R5)
shutil.rmtree(os.path.join(R5, "supabase"))
os.symlink(os.path.join(EVILREPO, "supabase"), os.path.join(R5, "supabase"))
code, out, err, calls = call(["migrate", os.path.join(R5, LOCAL), "--dry-run"])
check("r5/supabase — ссылка на чужой репозиторий: код 1, «ссылка» последней строкой",
      code == 1 and "ссылка" in err.strip().splitlines()[-1], (code, err))
code, out, err, calls = call(["migrate", "supabase/migrations/20260102000000_local.sql", "--dry-run"], cwd=R5)
check("тот же путь относительным от r5 — код 1, «ссылка»", code == 1 and "ссылка" in err.strip().splitlines()[-1],
      (code, err))
code, out, err, calls = call(["migrate", os.path.join(REPO2, MIG), "--dry-run"], cwd=REPO)
check("файл другого репозитория, текущая папка — repo: код 1, «вне репозитория текущей папки»",
      code == 1 and "вне репозитория текущей папки" in err.strip().splitlines()[-1], (code, err))
code, out, err, calls = call(["migrate", "supabase/../supabase/migrations/20260101000000_init.sql", "--dry-run"],
                             cwd=REPO)
check("путь с «..» — код 1", code == 1 and "«..»" in err.strip().splitlines()[-1], (code, err))
code, out, err, calls = call(["migrate", MIG, "--dry-run"], cwd=os.path.join(REPO, "supabase"))
check("текущая папка внутри репозитория, путь от неё не туда — отказ, не догадка", code == 1, (code, err))
code, out, err, calls = call(["migrate", MIG, "--dry-run"], cwd=REPO)
check("относительный путь от корня репозитория — код 0", code == 0 and "проверено" in out, (code, err))
# окно направления — только свой репозиторий (domains.json в STATE) и origin только из списка сборки окна
# (STATE/repo-origins/<окно>.json, record_origins; metis-1295, возврат двух argus #521). Закреплённый адрес — GitHub
# (локальный — отказ); в тесте его подменяет на голый origin рядом url.insteadOf глобального конфига (HOME=ROOT):
# его окно не пишет, а конфиг репозитория с url.* — отказ check_config
PIN_URL = "https://github.com/t/r4.git"
write(os.path.join(ROOT, ".gitconfig"), f'[url "{ORIGIN}"]\n\tinsteadOf = {PIN_URL}\n')
PINS = os.path.join(STATE, "repo-origins")


def pins(win, repos):
    write(os.path.join(PINS, win + ".json"), json.dumps({"repos": repos}))


DIR_C = os.path.join(ROOT, "dir-c")  # папка направления w-c, сама не репозиторий
APP, BARED = os.path.join(DIR_C, "app"), os.path.join(DIR_C, "x")
NESTED = os.path.join(R4, "nested")
pins("w-a", {REPO: PIN_URL})
pins("w-b", {R4: PIN_URL, NESTED: PIN_URL})
pins("w-c", {})
DOMAINS = os.path.join(STATE, "domains.json")
write(DOMAINS, '{"domains": {"w-a": ["%s"], "w-b": ["%s"], "w-c": ["%s"]}}' % (REPO, R4, DIR_C))
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-a"})
check("окно w-a, репозиторий направления w-b — код 1, «направления w-b»",
      code == 1 and "направления w-b" in err.strip().splitlines()[-1], (code, err))
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-b"})
check("окно w-b, свой репозиторий — код 0", code == 0, (code, err))
code, out, err, calls = call(["migrate", os.path.join(R3, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-a"}, cwd=ROOT)
check("окно w-a, текущая папка вне репозитория — код 1", code == 1, (code, err))
write(DOMAINS, "{")
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-b"})
check("карта направлений битая при окне — код 1, «не прочитана»",
      code == 1 and "не прочитана" in err.strip().splitlines()[-1], (code, err))
write(DOMAINS, '{"domains": {"w-a": ["%s"], "w-b": ["%s"], "w-c": ["%s"]}}' % (REPO, R4, DIR_C))
# вложенный репозиторий в репозитории направления: его .git/config (origin) окно задаёт при клоне (metis-1295, Д1)
git(ROOT, "clone", ORIGIN, NESTED)
code, out, err, calls = call(["migrate", os.path.join(NESTED, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-b"},
                             cwd=NESTED)
check("окно w-b, репозиторий вложен в r4 — код 1, «вложенный» последней строкой",
      code == 1 and "вложенный" in err.strip().splitlines()[-1], (code, err))
# папка направления — не репозиторий: окно делает в ней свой репозиторий со своим origin (evil.git, где LOCAL «слит»)
git(ROOT, "clone", EVIL, APP)
W_C = {"PANTHEON_WINDOW": "w-c"}
code, out, err, calls = call(["migrate", os.path.join(APP, LOCAL), "--dry-run"], W_C, cwd=APP)
check("окно w-c, новый репозиторий в папке направления (не репозиторий) со своим origin — код 1, «нет в списке»",
      code == 1 and "нет в списке" in err.strip().splitlines()[-1], (code, err))
# bare-репозиторий с origin evil, переименованный в .git: литерал <x>/.git/config в denyWrite его бы не пустил,
# а x — не из сборки, его в списке нет
git(ROOT, "clone", "--bare", EVIL, os.path.join(BARED, "g"))
os.rename(os.path.join(BARED, "g"), os.path.join(BARED, ".git"))
git(BARED, "config", "core.bare", "false")
git(BARED, "checkout", "-f", "main")
check("подготовка: bare-клон evil, переименованный в .git, — рабочая копия с LOCAL",
      os.path.isfile(os.path.join(BARED, LOCAL)))
code, out, err, calls = call(["migrate", os.path.join(BARED, LOCAL), "--dry-run"], W_C, cwd=BARED)
check("окно w-c, bare-репозиторий переименован в .git — код 1, «нет в списке»",
      code == 1 and "нет в списке" in err.strip().splitlines()[-1], (code, err))
# закреплённый r4: окно меняет remote.origin.url на evil и кладёт LOCAL — ls-remote и fetch всё равно по закреплённому
git(R4, "remote", "set-url", "origin", EVIL)
write(os.path.join(R4, LOCAL), "drop table t;\n")
W_B = {"PANTHEON_WINDOW": "w-b"}
code, out, err, calls = call(["migrate", os.path.join(R4, LOCAL), "--dry-run"], W_B)
check("окно w-b, remote.origin.url r4 подменён на evil — сверка по закреплённому адресу: код 1, «не из ветки»",
      code == 1 and "не из ветки по умолчанию" in err.strip().splitlines()[-1], (code, err))
code, out, err, calls = call(["migrate", os.path.join(R4, MIG), "--dry-run"], W_B)
check("окно w-b, слитый файл r4 при подменённом remote — код 0", code == 0, (code, err))
pins("w-b", {R4: EVIL, NESTED: PIN_URL})
code, out, err, calls = call(["migrate", os.path.join(R4, LOCAL), "--dry-run"], W_B)
check("закреплённый адрес — локальный путь — код 1, «локальный»",
      code == 1 and "локальный" in err.strip().splitlines()[-1], (code, err))
pins("w-b", {R4: PIN_URL, NESTED: PIN_URL})
git(R4, "remote", "set-url", "origin", ORIGIN)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-z"}, cwd=REPO)
check("списка окна нет — код 1, «не прочитан»", code == 1 and "не прочитан" in err.strip().splitlines()[-1],
      (code, err))
RM = load()
check("remote_ok: сетевые адреса — да, локальные, file://, «::» и «-» — нет",
      all(RM.remote_ok(u) for u in (PIN_URL, "ssh://git@github.com/t/r.git", "git@github.com:t/r.git"))
      and not any(RM.remote_ok(u) for u in (EVIL, "./x", "x", "file:///x", "FILE://x", "ext::sh -c x", "-u.x:y",
                                            "git@h:/abs", "", None)))
check("github_repo: только github.com, регистр не важен",
      RM.github_repo("https://github.com/T/R4.git") == "t/r4" and RM.github_repo("git@github.com:t/r4") == "t/r4"
      and RM.github_repo("https://github.comx/t/r4") == "" and RM.github_repo(EVIL) == "")
# record_origins (сборка окна): закреплён только репозиторий с <папка>/.git/config в denyWrite и origin из merge_repos
TOP = os.path.join(ROOT, "top")
REC = {n: os.path.join(TOP, n) for n in ("a", "b", "c", "d")}
for n, url in (("a", "https://github.com/T/R4.git"), ("b", "https://github.com/t/other.git"), ("c", ORIGIN),
               ("d", PIN_URL)):
    git(ROOT, "clone", ORIGIN, REC[n])
    git(REC[n], "remote", "set-url", "origin", url)
REC_DENY = [REC[n] + "/.git/config" for n in "abc"]  # d — не закреплён: так выглядит .git, созданная окном
REC_STATE = os.path.join(ROOT, "state-rec")
REC_OUT = RM.record_origins(REC_STATE, "w-r", [TOP], REC_DENY, ["t/r4"])
check("record_origins: закреплён только a (github из merge_repos, .git/config в denyWrite), список в STATE",
      REC_OUT == {REC["a"]: "https://github.com/T/R4.git"}
      and json.load(open(os.path.join(REC_STATE, "repo-origins", "w-r.json"), encoding="utf-8"))["repos"] == REC_OUT,
      REC_OUT)

# --- через pantheon (run.py) ---
env = {**os.environ, **GIT_ENV, "PATH": BIN + os.pathsep + os.environ.get("PATH", ""), "PANTHEON_STATE": STATE,
       "PANTHEON_HOME": os.path.join(ROOT, "pantheon"), "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_CLAUDE_TMP": os.path.join(ROOT, "ctmp")}
env.pop("PANTHEON_WINDOW", None)  # окно, из которого идёт тест, — не окно теста: у него нет списка в STATE теста
os.makedirs(env["PANTHEON_CLAUDE_TMP"], exist_ok=True)
r = subprocess.run([PY311, "-I", os.path.join(LIB, "run.py"), "supabase", "migrate", p(LOCAL), "--dry-run"], env=env,
                   capture_output=True, text=True, timeout=120, cwd=REPO)
check("pantheon supabase migrate: отказ файлу не из main — код 1, причина последней строкой",
      r.returncode == 1 and "нет в origin/main" in r.stderr.strip().splitlines()[-1], (r.returncode, r.stderr[-300:]))
r = subprocess.run([PY311, "-I", os.path.join(LIB, "run.py"), "supabase", "migrate", p(MIG), "--dry-run"], env=env,
                   capture_output=True, text=True, timeout=120, cwd=REPO)
check("pantheon supabase migrate --dry-run файла из main — код 0", r.returncode == 0 and "проверено" in r.stdout,
      (r.returncode, r.stderr[-300:]))


# --- мутанты ---
def mutant(old, new):
    src = SRC.replace(old, new, 1)
    assert src != SRC, old
    return load(src)


M1 = mutant("    blob, body = _blob_at(repo, sha, rel)",
            '    blob, body = _blob_at(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(), rel)')
check("мутант (сверка с HEAD вместо origin/main) пропускает локальный коммит — тест это видит",
      call(["migrate", p(LOCAL), "--dry-run"], mod=M1)[0] == 0 and call(["migrate", p(LOCAL), "--dry-run"])[0] == 1)
M2 = mutant("if _file_hash(os.path.join(repo, rel), len(blob)) != blob:", "if False:")
write(p(MIG), MAIN_SQL + "drop table t;\n")
check("мутант (без сверки blob) пропускает изменённый файл — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], mod=M2)[0] == 0 and call(["migrate", p(MIG), "--dry-run"])[0] == 1)
write(p(MIG), MAIN_SQL)
M3 = mutant('if known and _query(db, f"select count(*)', 'if False and _query(db, f"select count(*)')
check("мутант (без проверки «уже применена») применяет повторно — тест это видит",
      call(["migrate", p(MIG)], {"FAKE_COUNT": "1"}, mod=M3)[0] == 0 and call(["migrate", p(MIG)], {"FAKE_COUNT": "1"})[0] == 1)
M4 = mutant("m = MIGRATION.fullmatch(rel)", r'm = re.fullmatch(r"(.*)()", rel)')
check("мутант (без проверки пути миграции) пропускает README.md из main — тест это видит",
      call(["migrate", p("README.md"), "--dry-run"], mod=M4)[0] == 0 and call(["migrate", p("README.md"), "--dry-run"])[0] == 1)

M5 = mutant('    for ref in (s + branch for s in SHADOW):', '    for ref in ():')
git(REPO, "update-ref", "refs/tags/origin/main", "HEAD")
check("мутант (без отказа на ветку или метку origin/main) пропускает неоднозначное имя — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], mod=M5)[0] == 0 and call(["migrate", p(MIG), "--dry-run"])[0] == 1)
SRC6 = SRC.replace('    for ref in (s + branch for s in SHADOW):', '    for ref in ():', 1).replace(
    'verified + "^{commit}"', 'base + "^{commit}"', 1).replace("    if sha != tip:", "    if False:", 1)
assert SRC6.count('base + "^{commit}"') == 1 and "for ref in ():" in SRC6 and "if sha != tip" not in SRC6
check("мутант (короткое имя origin/main вместо своего ref, без отказа) берёт метку с локальным коммитом, а без "
      "мутанта — отказ «неоднозначно»", call(["migrate", p(LOCAL), "--dry-run"], mod=load(SRC6))[0] == 0
      and "неоднозначно" in call(["migrate", p(LOCAL), "--dry-run"])[2])
git(REPO, "update-ref", "-d", "refs/tags/origin/main")
M7 = mutant('"fetch", "--quiet", "--no-tags", "--no-recurse-submodules", remote, f"+refs/heads/{branch}:{verified}"',
            '"fetch", "--quiet", "--no-tags", "--no-recurse-submodules", remote, "main"')
git(REPO, "update-ref", "refs/pantheon/verified-main", "HEAD")
check("мутант (fetch не в свой ref) оставляет подвинутый ref — его ловит сверка с ls-remote «не равен»",
      "не равен" in call(["migrate", p(LOCAL), "--dry-run"], mod=M7)[2]
      and "нет в origin/main" in call(["migrate", p(LOCAL), "--dry-run"])[2])
SRC32 = SRC.replace('"fetch", "--quiet", "--no-tags", "--no-recurse-submodules", remote, f"+refs/heads/{branch}:{verified}"',
                    '"fetch", "--quiet", "--no-tags", "--no-recurse-submodules", remote, "main"', 1).replace("    if sha != tip:", "    if False:", 1)
assert "if sha != tip" not in SRC32 and "{branch}:{verified}" not in SRC32
git(REPO, "update-ref", "refs/pantheon/verified-main", "HEAD")  # настоящий вызов выше вернул ref — снова двигаем
check("мутант (ref не сверен с коммитом из ls-remote) — ref, подвинутый окном на свой коммит, пропускает LOCAL — "
      "тест это видит", call(["migrate", p(LOCAL), "--dry-run"], mod=load(SRC32))[0] == 0)
M8 = mutant('cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", sql]',
            'cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction", "--dbname", url, "-f", sql]')
check("мутант (адрес в argv psql) — тест это видит", "secret" in call(["migrate", p(MIG)], mod=M8)[3])
M9 = mutant("timeout=1800, env=db)", "timeout=1800)")
call(["migrate", p(MIG)], mod=M9)
check("мутант (psql без PG* окружения) — тест это видит",
      any(x.startswith(os.path.join(BIN, "psql")) and " pw= " in x for x in open(ENVLOG, encoding="utf-8")))
M10 = mutant('if not k.startswith("PG")}', "}")
call(["migrate", p(MIG)], {"PGSSLMODE": "disable"}, mod=M10)
check("мутант (PG* родителя не сняты) — PGSSLMODE=disable протёк — тест это видит",
      "ssl=disable" in open(ENVLOG, encoding="utf-8").read())
M11 = mutant("raise Refused(f\"{DB_ENV}: параметр адреса", "continue  # raise Refused(f\"{DB_ENV}: параметр адреса")
check("мутант (неизвестный параметр адреса пропущен молча) — тест это видит",
      call(["migrate", p(MIG)], {"SUPABASE_DB_URL": "postgresql://u:s@db.example/x?options=-c%20x"}, mod=M11)[0] == 0)

M12 = mutant("    check_sql(rel, body)\n", "")
SHELL = p("supabase/migrations/20260110000000_shell.sql")
check("мутант (без проверки текста миграции) отдаёт psql \\! — тест это видит",
      call(["migrate", SHELL], mod=M12)[0] == 0 and call(["migrate", SHELL])[0] == 1)
M13 = mutant('    if b"\\\\" in body:', "    if False:")
check("мутант п. 2 (без отказа на «\\») пропускает \\! — тест это видит",
      call(["migrate", SHELL], mod=M13)[0] == 0)
M17 = mutant('text = body.decode("utf-8")\n', 'text = body.decode("utf-8", "replace")\n')
SJIS = p("supabase/migrations/20260120000000_sjis.sql")
check("мутант п. 1 (decode с replace) пропускает не-UTF-8 — тест это видит",
      call(["migrate", SJIS], mod=M17)[0] == 0 and call(["migrate", SJIS])[0] == 1)
M18 = mutant("    if bad:\n", "    if False:\n")
CR = p("supabase/migrations/20260118000000_cr.sql")
check("мутант п. 3 (без отказа на управляющие знаки) пропускает COMMIT за \\r в комментарии — тест это видит",
      call(["migrate", CR], mod=M18)[0] == 0 and call(["migrate", CR])[0] == 1)
M19 = mutant("    if m := FORBIDDEN_SQL.search(text):", "    if m := None:")
ENC = p("supabase/migrations/20260121000000_enc.sql")
check("мутант п. 4 (без отказа на client_encoding) пропускает смену кодировки — тест это видит",
      call(["migrate", ENC], mod=M19)[0] == 0 and call(["migrate", ENC])[0] == 1)
M20 = mutant(',\n               PGCLIENTENCODING="UTF8")', ")")
call(["migrate", p(MIG)], mod=M20)
check("мутант п. 5 (psql без PGCLIENTENCODING=UTF8) — тест это видит",
      all(x.endswith(" enc=") for x in open(ENVLOG, encoding="utf-8").read().splitlines()))
M14 = mutant("        if any(words == w or words.startswith(w + \" \") for w in TXN_WORDS):", "        if False:")
BEGIN = p("supabase/migrations/20260112000000_begin.sql")
check("мутант (без отказа на BEGIN/COMMIT) пропускает свой BEGIN — тест это видит",
      call(["migrate", BEGIN], mod=M14)[0] == 0 and call(["migrate", BEGIN])[0] == 1)
M15 = mutant('if not k.startswith("GIT_")}', "}")
check("мутант (GIT_* не сняты) берёт main чужого репозитория — тест это видит",
      call(["migrate", p(LOCAL), "--dry-run"], GIT_EVIL, mod=M15)[0] == 0
      and call(["migrate", p(LOCAL), "--dry-run"], GIT_EVIL)[0] == 1)
M16 = mutant("    return \"\".join(out)", "    return sql")
check("мутант (литералы не вырезаны) отказывает честной миграции — тест это видит",
      call(["migrate", p(GOOD)], mod=M16)[0] == 1 and call(["migrate", p(GOOD)])[0] == 0)

M21 = mutant("    branch, tip = default_branch(repo, remote)\n", '    branch, tip = "main", default_branch(repo, remote)[1]\n')
check("мутант (всегда main) отказывает репозиторию без main — тест это видит",
      call(["migrate", p2(MIG), "--dry-run"], mod=M21)[0] == 1 and call(["migrate", p2(MIG), "--dry-run"])[0] == 0)
M22 = mutant("    return name, tip\n", '    b = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")'
             '.stdout.strip().removeprefix("origin/")\n'
             '    return b, _git(repo, "rev-parse", "refs/remotes/origin/" + b).stdout.strip()\n')
check("мутант (ветка из локального origin/HEAD) берёт feature и пропускает несливый LOCAL — тест это видит",
      call(["migrate", p2(LOCAL), "--dry-run"], mod=M22)[0] == 0 and call(["migrate", p2(LOCAL), "--dry-run"])[0] == 1)
M23 = mutant("    if not name or _git(", "    if False and _git(")
git(ORIGIN2, "update-ref", "--no-deref", "HEAD", "develop")
check("мутант (без отказа на неназванную ветку) — причина уже не «однозначно» — тест это видит",
      "однозначно" not in call(["migrate", p2(MIG), "--dry-run"], mod=M23)[2]
      and "однозначно" in call(["migrate", p2(MIG), "--dry-run"])[2])
git(ORIGIN2, "symbolic-ref", "HEAD", "refs/heads/develop")

# мутанты защиты git мимо песочницы (metis-1295, возврат argus #521)
M24 = mutant('"-c", "core.hooksPath=/dev/null", ', "")
git(R4, "update-ref", "-d", "refs/pantheon/verified-main")
call(["migrate", os.path.join(R4, MIG), "--dry-run"], mod=M24)
check("мутант (без core.hooksPath=/dev/null) исполняет хук reference-transaction окна — тест это видит",
      os.path.exists(PWNED))
if os.path.exists(PWNED):
    os.remove(PWNED)
os.remove(os.path.join(R4, ".git", "hooks", "reference-transaction"))
M25 = mutant("    check_config(repo)\n    m = MIGRATION", "    m = MIGRATION")
git(R4, "config", "remote.origin.uploadPack", UPLOAD)
call(["migrate", os.path.join(R4, MIG), "--dry-run"], mod=M25)
check("мутант (без проверки конфига) исполняет remote.origin.uploadpack окна — тест это видит", os.path.exists(PWNED))
if os.path.exists(PWNED):
    os.remove(PWNED)
git(R4, "config", "--unset", "remote.origin.uploadPack")
M26 = mutant("            if os.path.islink(dotgit) or not os.path.isdir(dotgit) or", "            if False and")
check("мутант (.git-файл gitdir: принят) — причина уже не «настоящая папка .git» — тест это видит",
      "настоящая папка .git" not in call(["migrate", os.path.join(R3, MIG), "--dry-run"], mod=M26)[2]
      and "настоящая папка .git" in call(["migrate", os.path.join(R3, MIG), "--dry-run"])[2])
M27 = mutant("        if os.path.islink(cur):", "        if False:")
check("мутант (ссылка в середине пути не проверена) — причина уже не «ссылка» — тест это видит",
      "ссылка" not in call(["migrate", os.path.join(R5, LOCAL), "--dry-run"], mod=M27)[2]
      and "ссылка" in call(["migrate", os.path.join(R5, LOCAL), "--dry-run"])[2])
M28 = mutant("    repo = _repo_root(cwd)\n", "    repo = _repo_root(os.path.dirname(os.path.realpath(os.path.join(cwd, path))))\n"
             "    cwd = repo\n    path = os.path.relpath(os.path.realpath(os.path.join(os.getcwd(), path)), repo)\n")
check("мутант (репозиторий от realpath файла) уводит в чужой клон через ссылку и пропускает несливый LOCAL — тест "
      "это видит", call(["migrate", os.path.join(R5, LOCAL), "--dry-run"], mod=M28)[0] == 0
      and call(["migrate", os.path.join(R5, LOCAL), "--dry-run"])[0] == 1)
M29 = mutant("    own_repo(state, repo)\n", "")
check("мутант (без проверки направления) — причина уже не «направления w-b» — тест это видит",
      "направления w-b" not in call(["migrate", os.path.join(R4, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-a"},
                                    mod=M29)[2]
      and "направления w-b" in call(["migrate", os.path.join(R4, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-a"})[2])

# мутанты origin из списка сборки окна (metis-1295, возврат двух argus #521)
M37 = mutant('    if not isinstance(url, str):\n        raise', '    if not isinstance(url, str):\n        return "origin"\n'
             "        raise")
check("мутант (репозиторий не из списка — origin его config) пускает новый репозиторий окна с origin evil — тест это "
      "видит", call(["migrate", os.path.join(APP, LOCAL), "--dry-run"], W_C, cwd=APP, mod=M37)[0] == 0
      and call(["migrate", os.path.join(BARED, LOCAL), "--dry-run"], W_C, cwd=BARED, mod=M37)[0] == 0)
M38 = mutant("    except (OSError, ValueError, AttributeError) as e:\n        raise Refused(f\"список",
             "    except (OSError, ValueError, AttributeError) as e:\n        return \"origin\"\n        raise Refused(f\"список")
check("мутант (списка нет — origin config) — окно без списка проходит — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-z"}, cwd=REPO, mod=M38)[0] == 0)
M39 = mutant("    return url\n\n\ndef own_repo", '    return "origin"\n\n\ndef own_repo')
git(R4, "remote", "set-url", "origin", EVIL)
check("мутант (ls-remote и fetch по remote из config, не по закреплённому) пропускает LOCAL с origin evil — тест это "
      "видит", call(["migrate", os.path.join(R4, LOCAL), "--dry-run"], W_B, mod=M39)[0] == 0
      and call(["migrate", os.path.join(R4, LOCAL), "--dry-run"], W_B)[0] == 1)
M40 = mutant("    if not remote_ok(url):\n        raise Refused(f\"закреплённый", "    if False:\n        raise Refused(f\"закреплённый")
pins("w-b", {R4: EVIL, NESTED: PIN_URL})
check("мутант (локальный закреплённый адрес принят) пропускает LOCAL из evil — тест это видит",
      call(["migrate", os.path.join(R4, LOCAL), "--dry-run"], W_B, mod=M40)[0] == 0)
pins("w-b", {R4: PIN_URL, NESTED: PIN_URL})
git(R4, "remote", "set-url", "origin", ORIGIN)
os.remove(os.path.join(R4, LOCAL))
M41 = mutant('    if not isinstance(url, str) or not url or url.startswith("-") or "::" in url', "    if False")
check("мутант remote_ok (без отказа на «-», «::», пустое) — тест это видит",
      any(M41.remote_ok(u) for u in ("-u.x:y", "ext::sh -c x")))
M42 = mutant('        return url.split("://", 1)[0].lower() in ("https", "ssh")', "        return True")
check("мутант remote_ok (любая схема, file://) — тест это видит", M42.remote_ok("file:///x"))
M43 = mutant('or os.path.join(dotgit, "config") not in pinned ', "")
check("мутант record_origins (без литерала .git/config в denyWrite) закрепляет d — тест это видит",
      REC["d"] in M43.record_origins(REC_STATE, "w-m", [TOP], REC_DENY, ["t/r4"]))
M44 = mutant("            if github_repo(url) and github_repo(url) in want:", "            if url:")
check("мутант record_origins (origin не из merge_repos) закрепляет b и c — тест это видит",
      {REC["b"], REC["c"]} <= set(M44.record_origins(REC_STATE, "w-m", [TOP], REC_DENY, ["t/r4"])))
M45 = mutant("        for d in [top] + [os.path.join(top, n) for n in names]:", "        for d in [top]:")
check("мутант record_origins (без подпапок первого уровня) не закрепляет a — тест это видит",
      M45.record_origins(REC_STATE, "w-m", [TOP], REC_DENY, ["t/r4"]) == {})

# мутанты хранилища объектов (metis-1295, второй argus #521)
SRC30 = SRC.replace('"git", "--no-replace-objects", ', '"git", ').replace(', GIT_NO_REPLACE_OBJECTS="1"', "")
assert '"--no-replace-objects"' not in SRC30 and 'GIT_NO_REPLACE_OBJECTS="1"' not in SRC30
git(REPO, "replace", GOOD_BLOB, EVIL_BLOB)
check("мутант (замены объектов действуют) — git replace меняет итог — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], mod=load(SRC30))[:2] != REPLACE_OUT)
git(REPO, "replace", "-d", GOOD_BLOB)
M31 = mutant("    if r.returncode != 0 or not algo or algo(", "    if r.returncode != 0 or not algo or False and algo(")
LOOSE = plant(GOOD_BLOB, b"blob", EVIL_SQL)
code, out, err, calls = call(["migrate", p(MIG), "--dry-run"], mod=M31)
check("мутант (объект не сверен с хешем) — подменённый loose-объект проходит, код 0 — тест это видит",
      code == 0 and f"({len(EVIL_SQL)} байт)" in out, (code, out, err))
unplant(*LOOSE)
TREE = plant(DIR_TREE, b"tree", RAW.replace(bytes.fromhex(GOOD_BLOB), bytes.fromhex(EVIL_BLOB)))
write_bytes(p(MIG), EVIL_SQL)
check("мутант (объект не сверен с хешем) — подменённое дерево проходит — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], mod=M31)[0] == 0)
unplant(*TREE)
write(p(MIG), MAIN_SQL)

# мутанты подмодулей, вложенного репозитория, commondir и PATH (metis-1295, первый argus #521)
SRC33 = SRC.replace('"--no-recurse-submodules", ', "", 1).replace(', "-c", "submodule.recurse=false"', "", 1)
assert '"--no-recurse-submodules"' not in SRC33 and '"submodule.recurse=false"' not in SRC33
if os.path.exists(PWNED):
    os.remove(PWNED)
call(["migrate", os.path.join(R7M, MIG), "--dry-run"], cwd=R7M, mod=load(SRC33))
check("мутант (fetch идёт в подмодули) исполняет uploadpack из config подмодуля — тест это видит",
      os.path.exists(PWNED))
if os.path.exists(PWNED):
    os.remove(PWNED)
M34 = mutant("    while d != top:", "    while False:")
check("мутант (вложенный репозиторий не проверен) пускает r4/nested — тест это видит",
      call(["migrate", os.path.join(NESTED, MIG), "--dry-run"], {"PANTHEON_WINDOW": "w-b"}, cwd=NESTED, mod=M34)[0]
      == 0)
M35 = mutant(' or os.path.lexists(os.path.join(dotgit, "commondir")):', ":")
write(os.path.join(R4, ".git", "commondir"), "../../r3\n")
check("мутант (commondir не проверен) — причина уже не «настоящая папка .git» — тест это видит",
      "настоящая папка .git" not in call(["migrate", os.path.join(R4, MIG), "--dry-run"], mod=M35)[2])
os.remove(os.path.join(R4, ".git", "commondir"))
M36 = mutant("    env.update(PATH=GIT_PATH, ", "    env.update(")
call(["migrate", os.path.join(R4, MIG), "--dry-run"], FAKE_PATH, mod=M36)
check("мутант (PATH окружения) исполняет свой git первым в PATH — тест это видит", os.path.exists(GITMARK))

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
