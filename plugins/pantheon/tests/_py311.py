"""Интерпретатор для вызова CLI pantheon из тестов — тот же, что гоняет тест (Python 3.11+, metis-0571).

Подключение (тесты идут с -I, поэтому каталог добавляется явно):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _py311 import PY311
Тесты идут только на Python 3.11+ (AGENTS.md «Как проверять», CI — 3.14). Старше — код 1 и одна строка: pantheon.py
без tomllib не идёт, а молчаливый пропуск прятал бы непроверенное."""
import os
import shutil
import sys
import tempfile

if sys.version_info < (3, 11):
    print("FAIL тесты pantheon идут на Python 3.11+, здесь %d.%d (%s)" % (sys.version_info[:2] + (sys.executable,)))
    sys.exit(1)

# Признак теста для всех тестов pantheon и их подпроцессов, унаследовавших окружение: notify пишет в
# STATE/notify-test.log, а не на экран владельца (metis-0307). Тест со своим окружением с нуля защищает сам
# notify: временный PANTHEON_STATE или HOME тоже уводят уведомление в файл.
os.environ["PANTHEON_TEST"] = "1"


def python_without_claude(exe):
    """Путь интерпретатора для подпроцессов теста, в папке которого нет настоящего `claude` (metis-1308) → путь.

    run_env (lib/pantheon.py) ставит папку sys.executable в PATH окон и дочерних `pantheon start` раньше PATH теста —
    раньше папки подменного claude. Тест, запущенный python3.14 из ~/.local/bin (uv кладёт туда ссылку рядом с
    настоящим claude), отдавал дочернему start настоящий claude: самозапуск звал `claude --bg` мимо подмены, и окно в
    журнале подмены не появлялось. Тогда берётся realpath интерпретатора — тот же Python из своей папки. И там есть
    claude — код 1 и причина: подмена не изолирована, проверять нечего."""
    if not os.path.lexists(os.path.join(os.path.dirname(exe), "claude")):
        return exe
    real = os.path.realpath(exe)
    if os.path.lexists(os.path.join(os.path.dirname(real), "claude")):
        print(f"FAIL рядом с интерпретатором теста {real} лежит claude — подменный claude тестов не изолирован "
              "(metis-1308): запустите тесты другим python3.14")
        sys.exit(1)
    return real


PY311 = python_without_claude(sys.executable)


# Запасные корни тестов в окне роли: свой TMPDIR песочницы Claude Code. «%d» — uid.
SPARE = ("/tmp/claude-%d", "/private/tmp/claude-%d")


def fs_ok(base):
    """Можно ли под base собрать то, что строят тесты: репозиторий (`.git/hooks`, `.git/config`) и поддельный HOME с
    ролями (`.claude/agents`) → bool. Проба — на деле, во временной папке, которую она за собой убирает."""
    try:
        probe = tempfile.mkdtemp(prefix="fsprobe-", dir=base)
    except OSError:
        return False
    try:
        os.makedirs(os.path.join(probe, ".git", "hooks"))
        with open(os.path.join(probe, ".git", "config"), "w"):
            pass
        os.makedirs(os.path.join(probe, ".claude", "agents"))
        return True
    except OSError:
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def own_dir(path):
    """Запасная папка в общей /tmp годится, только если она своя: папка, а не ссылка, владелец — этот uid, и писать
    в неё не могут группа и остальные. Иначе другой пользователь Mac мог создать её заранее и подменять файлы теста
    (Д ревью PR #279, metis-0670)."""
    import stat
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022


def mkroot(prefix, first=None, spare=None):
    """Корневая временная папка теста, где создаются репозитории и `.claude/agents` (metis-0715, metis-0941).

    Под `heavy` в окне роли TMPDIR — tmp кэша окна (PANTHEON_TMP: там разрешены сокеты), а песочница запрещает под
    кэшем запись в `.git/hooks`, `.git/config` и `.claude/agents` (защита от подмены хуков и ролей): `git init` и
    `roles build` падают с EPERM. Свой TMPDIR песочницы (`/tmp/claude-<uid>`) этих запретов не имеет, но сокетов там
    нет — поэтому тест с сокетами mkroot не берёт. Порядок: first (своя первая папка теста: Linux — /var/tmp, чтобы
    корень не лежал в /tmp), TMPDIR, запасные spare (по умолчанию SPARE) — только свои (own_dir); берётся первая, где
    fs_ok. Ни одной — mkdtemp в TMPDIR как был: тест упадёт на своём месте, а не здесь."""
    uid = os.getuid()
    given = [b for b in (first, os.environ.get("TMPDIR")) if b]
    spares = [s % uid if "%d" in s else s for s in (SPARE if spare is None else spare)]
    for base in given + [s for s in spares if s not in given]:
        if not os.path.isdir(base) or (base not in given and not own_dir(base)):
            continue
        if fs_ok(base):
            return tempfile.mkdtemp(prefix=prefix, dir=base)
    return tempfile.mkdtemp(prefix=prefix)
