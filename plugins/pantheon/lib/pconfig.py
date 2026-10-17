"""Настройки pantheon человека: STATE/config.toml (pantheon-setup и `pantheon executors` пишут, infra-check читает).

Файл плоский и маленький, поэтому пишем его сами (tomllib только читает):

    python = "<путь к python3.14 от uv>"

    [executors]
    set = ["claude", "codex"]      # claude — всегда, codex — только дополнение (решение 175)

    [codex]
    enabled = true                 # false — проверка окружения не прошла, задачи идут на dev-*
    disabled_until = ""            # «ГГГГ-ММ-ДДTЧЧ:ММ» — лимит Codex с временем
    reason = ""                    # почему выключен: «нет на PATH», «нет входа», «hello-проба», «нужен вход», «лимит»
    home = "<CODEX_HOME роли codex-dev>"
    version = ""                   # `codex --version` последней проверки
    checked = ""                   # когда проверяли

Пути — от STATE (env PANTHEON_STATE), как в pantheon.py: тесты подменяют его временной папкой.
"""
import contextlib
import os
import sys

try:
    import fcntl
except ImportError:  # pragma: no cover — только macOS (решение 0155), но модуль импортируется и в тестах
    fcntl = None

HOME = os.path.expanduser("~")
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
CONFIG = os.path.join(STATE, "config.toml")
ORDER = ["executors", "codex"]  # порядок таблиц в файле; ключи верхнего уровня — первыми


def path():
    """Путь к файлу — каждый раз из окружения: тесты меняют PANTHEON_STATE между вызовами."""
    st = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
    return os.path.join(st, "config.toml")


def load(p=None):
    """→ dict. Нет файла — {}. Битый файл — ValueError: молча терять набор исполнителей нельзя."""
    p = p or path()
    if sys.version_info < (3, 11):
        raise RuntimeError("pconfig: нужен Python 3.11+ (tomllib)")
    import tomllib
    try:
        with open(p, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{p}: не читается ({e})") from e


def _val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def dumps(data):
    top = [f"{k} = {_val(v)}" for k, v in data.items() if not isinstance(v, dict)]
    out = top + ([""] if top else [])
    tables = [k for k in ORDER if isinstance(data.get(k), dict)] + \
             [k for k, v in data.items() if isinstance(v, dict) and k not in ORDER]
    for t in tables:
        out.append(f"[{t}]")
        out += [f"{k} = {_val(v)}" for k, v in data[t].items() if v is not None]
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


@contextlib.contextmanager
def _locked(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "a") as lk:
        if fcntl:
            fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lk, fcntl.LOCK_UN)


def update(changes, section=None, p=None):
    """Слить changes в файл под замком и записать атомарно (0600). section=None — ключи верхнего уровня.
    Значение None удаляет ключ. → новый dict целиком."""
    p = p or path()
    with _locked(p):
        data = load(p)
        dst = data if section is None else data.setdefault(section, {})
        for k, v in changes.items():
            if v is None:
                dst.pop(k, None)
            else:
                dst[k] = v
        tmp = f"{p}.tmp.{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(dumps(data))
        os.replace(tmp, p)
        return data
