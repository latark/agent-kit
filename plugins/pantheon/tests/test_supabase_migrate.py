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
import os
import shutil
import subprocess
import sys
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


def write(p, text, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(p, mode)


GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": ROOT}


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd, capture_output=True, text=True,
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


def call(argv, env=None, mod=None):
    """main модуля в этом процессе → (код, stdout, stderr, вызовы psql/pg_dump)."""
    write(SCHEMA, "create schema public;\n")
    write(LOG, "")
    write(ENVLOG, "")
    keep = dict(os.environ)
    os.environ.update({**GIT_ENV, "PATH": BIN + os.pathsep + keep.get("PATH", ""), "FAKE_LOG": LOG,
                       "FAKE_ENVLOG": ENVLOG, "FAKE_SCHEMA": SCHEMA, "SUPABASE_DB_URL": URL})
    for k in ("FAKE_TABLE", "FAKE_COUNT", "FAKE_APPLY_FAIL", "PGHOST", "PGPASSWORD", "PGSSLMODE"):
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

# --- через pantheon (run.py) ---
env = {**os.environ, **GIT_ENV, "PATH": BIN + os.pathsep + os.environ.get("PATH", ""), "PANTHEON_STATE": STATE,
       "PANTHEON_HOME": os.path.join(ROOT, "pantheon"), "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_CLAUDE_TMP": os.path.join(ROOT, "ctmp")}
os.makedirs(env["PANTHEON_CLAUDE_TMP"], exist_ok=True)
r = subprocess.run([PY311, "-I", os.path.join(LIB, "run.py"), "supabase", "migrate", p(LOCAL), "--dry-run"], env=env,
                   capture_output=True, text=True, timeout=120)
check("pantheon supabase migrate: отказ файлу не из main — код 1, причина последней строкой",
      r.returncode == 1 and "нет в origin/main" in r.stderr.strip().splitlines()[-1], (r.returncode, r.stderr[-300:]))
r = subprocess.run([PY311, "-I", os.path.join(LIB, "run.py"), "supabase", "migrate", p(MIG), "--dry-run"], env=env,
                   capture_output=True, text=True, timeout=120)
check("pantheon supabase migrate --dry-run файла из main — код 0", r.returncode == 0 and "проверено" in r.stdout,
      (r.returncode, r.stderr[-300:]))


# --- мутанты ---
def mutant(old, new):
    src = SRC.replace(old, new, 1)
    assert src != SRC, old
    return load(src)


M1 = mutant('blob = _git(repo, "rev-parse", "--verify", "--quiet", f"{head.stdout.strip()}:{rel}")',
            'blob = _git(repo, "rev-parse", "--verify", "--quiet", f"HEAD:{rel}")')
check("мутант (сверка с HEAD вместо origin/main) пропускает локальный коммит — тест это видит",
      call(["migrate", p(LOCAL), "--dry-run"], mod=M1)[0] == 0 and call(["migrate", p(LOCAL), "--dry-run"])[0] == 1)
M2 = mutant("if mine.returncode != 0 or mine.stdout.strip() != blob.stdout.strip():", "if mine.returncode != 0:")
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

M5 = mutant('    for ref in SHADOW:', '    for ref in ():')
git(REPO, "update-ref", "refs/tags/origin/main", "HEAD")
check("мутант (без отказа на ветку или метку origin/main) пропускает неоднозначное имя — тест это видит",
      call(["migrate", p(MIG), "--dry-run"], mod=M5)[0] == 0 and call(["migrate", p(MIG), "--dry-run"])[0] == 1)
SRC6 = SRC.replace('    for ref in SHADOW:', '    for ref in ():', 1).replace(
    'VERIFIED + "^{commit}"', 'BASE + "^{commit}"', 1)
assert SRC6.count('BASE + "^{commit}"') == 1 and "for ref in ():" in SRC6
check("мутант (короткое имя origin/main вместо своего ref, без отказа) берёт метку с локальным коммитом, а без "
      "мутанта — отказ «неоднозначно»", call(["migrate", p(LOCAL), "--dry-run"], mod=load(SRC6))[0] == 0
      and "неоднозначно" in call(["migrate", p(LOCAL), "--dry-run"])[2])
git(REPO, "update-ref", "-d", "refs/tags/origin/main")
M7 = mutant('"fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/main:{VERIFIED}"',
            '"fetch", "--quiet", "--no-tags", "origin", "main"')
git(REPO, "update-ref", "refs/pantheon/verified-main", "HEAD")
check("мутант (fetch не в свой ref) оставляет подвинутый ref — тест это видит",
      call(["migrate", p(LOCAL), "--dry-run"], mod=M7)[0] == 0 and call(["migrate", p(LOCAL), "--dry-run"])[0] == 1)
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

M12 = mutant("    check_sql(rel, body.stdout)\n", "")
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

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
