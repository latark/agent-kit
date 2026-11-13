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
- мутанты внутри теста: без проверки «есть в main», без сверки blob, без проверки «уже применена» — тест их ловит.
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
write(os.path.join(BIN, "pg_dump"), '#!/bin/sh\necho "pg_dump $*" | sed "s/postgres:[^ ]*/URL/" >> "$FAKE_LOG"\n'
      'cat "$FAKE_SCHEMA"\n', 0o755)
write(os.path.join(BIN, "psql"), r'''#!/bin/sh
echo "psql $*" | sed "s/postgres:[^ ]*/URL/" >> "$FAKE_LOG"
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
URL = "postgres://u:secret@db.example/postgres"
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
    keep = dict(os.environ)
    os.environ.update({**GIT_ENV, "PATH": BIN + os.pathsep + keep.get("PATH", ""), "FAKE_LOG": LOG,
                       "FAKE_SCHEMA": SCHEMA, "SUPABASE_DB_URL": URL})
    for k in ("FAKE_TABLE", "FAKE_COUNT", "FAKE_APPLY_FAIL"):
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
M3 = mutant('if known and _query(url, f"select count(*)', 'if False and _query(url, f"select count(*)')
check("мутант (без проверки «уже применена») применяет повторно — тест это видит",
      call(["migrate", p(MIG)], {"FAKE_COUNT": "1"}, mod=M3)[0] == 0 and call(["migrate", p(MIG)], {"FAKE_COUNT": "1"})[0] == 1)
M4 = mutant("m = MIGRATION.fullmatch(rel)", r'm = re.fullmatch(r"(.*)()", rel)')
check("мутант (без проверки пути миграции) пропускает README.md из main — тест это видит",
      call(["migrate", p("README.md"), "--dry-run"], mod=M4)[0] == 0 and call(["migrate", p("README.md"), "--dry-run"])[0] == 1)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
