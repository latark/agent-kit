"""Интерпретатор для вызова CLI pantheon из тестов — тот же, что гоняет тест (Python 3.11+, metis-0571).

Подключение (тесты идут с -I, поэтому каталог добавляется явно):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _py311 import PY311
Тесты идут только на Python 3.11+ (AGENTS.md «Как проверять», CI — 3.14). Старше — код 1 и одна строка: pantheon.py
без tomllib не идёт, а молчаливый пропуск прятал бы непроверенное."""
import atexit
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


# Настоящие инструменты, которые тесты подменяют заглушкой или ждут «нет на PATH» (metis-1308): настоящий claude
# поднимает окна, настоящий codex идёт входить в OpenAI. Ни один тест их звать не должен.
REAL_TOOLS = ("claude", "codex")


def _has_tool(d, tools=REAL_TOOLS):
    return any(os.path.lexists(os.path.join(d, t)) for t in tools)


def python_without_claude(exe, tools=REAL_TOOLS):
    """Путь интерпретатора для подпроцессов теста, в папке которого нет настоящих `claude` и `codex` (metis-1308) → путь.

    run_env (lib/pantheon.py) ставит папку sys.executable в PATH окон и дочерних `pantheon start` раньше PATH теста —
    раньше папки подменного claude. Тест, запущенный python3.14 из ~/.local/bin (uv кладёт туда ссылку рядом с
    настоящим claude), отдавал дочернему start настоящий claude: самозапуск звал `claude --bg` мимо подмены, и окно в
    журнале подмены не появлялось. Тогда берётся realpath интерпретатора — тот же Python из своей папки. И там есть
    claude или codex — код 1 и причина: подмена не изолирована, проверять нечего."""
    if not _has_tool(os.path.dirname(exe), tools):
        return exe
    real = os.path.realpath(exe)
    if _has_tool(os.path.dirname(real), tools):
        print(f"FAIL рядом с интерпретатором теста {real} лежит claude или codex — подмена тестов не изолирована "
              "(metis-1308): запустите тесты другим python3.14")
        sys.exit(1)
    return real


def isolate_path(path, root, tools=REAL_TOOLS):
    """PATH теста без настоящих tools (metis-1308) → строка PATH. Папка PATH, где лежит claude или codex, заменяется
    зеркалом в root: ссылки на все её файлы, кроме tools. node, pnpm и python3.14 из той же папки остаются на PATH,
    а `shutil.which("codex")` теста «Codex нет» ничего не находит. Пример: codex из npm лежит в bin nvm рядом с node,
    и тест «Codex нет: add_codex» звал настоящий codex — тот шёл входить в OpenAI и вис до TimeoutExpired.
    root — папка или функция, которая её создаёт: её зовут при первом зеркале, нечего зеркалить — папки нет (metis-1309)."""
    out = []
    for d in (path or "").split(":"):
        if not d or not os.path.isdir(d) or not _has_tool(d, tools):
            out.append(d)
            continue
        if callable(root):  # папка зеркал создаётся, только когда зеркалить есть что (metis-1309)
            root = root()
        mirror = os.path.join(root, f"bin{len(out)}")
        os.makedirs(mirror)
        try:
            names = os.listdir(d)
        except OSError:
            names = []
        for n in names:
            if n not in tools:
                os.symlink(os.path.join(d, n), os.path.join(mirror, n))
        out.append(mirror)
    return ":".join(out)


def isolate_env(environ, root, tools=REAL_TOOLS):
    """Окружение процесса теста без настоящих tools (metis-1308): PATH — isolate_path, NVM_DIR — путь, которого нет.
    run_env ставит bin nvm (NVM_DIR, иначе HOME/.nvm) первым в PATH дочерних процессов, если его нет в PATH: после
    зеркала его там нет, и настоящий codex из nvm вернулся бы раньше всего. NVM_DIR под /dev/null: nvm_bin() не читает
    versions/node и ничего не добавляет, node берётся из зеркала, а папка для этого не нужна (metis-1309).
    root — папка или функция, создающая её по первой надобности. Меняет environ на месте."""
    if environ.get("PATH"):
        environ["PATH"] = isolate_path(environ["PATH"], root, tools)
    environ["NVM_DIR"] = os.path.join(os.devnull, "nvm")


MIRROR_PREFIX = "py311-path-"  # по этому началу run-tests.py (sweep_py311_mirrors) находит папки зеркал; дальше — pid
_mirror = {"root": None, "owner": None}


def mirror_root():
    """Папка зеркал PATH → путь; создаётся при первом вызове (metis-1309). Имя `py311-path-<pid>-…`: по pid создателя
    run-tests.py при старте узнаёт, жив ли он, и убирает папки после SIGKILL (таймаут раннера), куда atexit не доходит.
    Папку убирает atexit только процесс-создатель: копия (fork) с sys.exit не сносит её у соседей."""
    if _mirror["root"] is None:
        _mirror["owner"] = os.getpid()
        _mirror["root"] = tempfile.mkdtemp(prefix=f"{MIRROR_PREFIX}{_mirror['owner']}-")
        atexit.register(_drop_mirror)
    return _mirror["root"]


def _drop_mirror():
    if os.getpid() == _mirror["owner"]:
        shutil.rmtree(_mirror["root"], True)


isolate_env(os.environ, mirror_root)
PY311 = python_without_claude(sys.executable)


def unlock_tree(root):
    """metis-1400: вернуть права 0o700 на root и все каталоги под ним (до листинга), чтобы rmtree смог их удалить."""
    try:
        os.chmod(root, 0o700)
    except OSError:
        return
    for d, dirs, _files in os.walk(root):
        for n in dirs:
            p = os.path.join(d, n)
            if not os.path.islink(p):
                try:
                    os.chmod(p, 0o700)
                except OSError:
                    pass


def readonly_dirs(root):
    """metis-1400: каталоги под root (и он сам) без права записи владельца — их rmtree не удалит, в TMPDIR копится мусор."""
    bad = []
    for d, dirs, _files in os.walk(root):
        for p in [d] + [os.path.join(d, n) for n in dirs]:
            if not os.path.islink(p) and not os.stat(p).st_mode & 0o200 and p not in bad:
                bad.append(p)
    return bad


def rmtree_force(root):
    unlock_tree(root)
    shutil.rmtree(root, True)


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


def copy_plugin(src, dst):
    """Копия плагина без bin/ и tests/ (metis-1431): папками верхнего уровня, а не copytree корня, чтобы карта не
    связывала тест с bin/heavy, которого он не зовёт."""
    os.makedirs(dst)
    for n in sorted(os.listdir(src)):
        if n in ("bin", "tests", "__pycache__", ".git"):
            continue
        s = os.path.join(src, n)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, n), ignore=shutil.ignore_patterns("__pycache__", "tests", ".git"))
        else:
            shutil.copy2(s, os.path.join(dst, n))
