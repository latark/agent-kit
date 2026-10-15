"""qmd — общий поиск по markdown для всех сессий Mac (шаг 1.5: QMD-01…04, SCHED-05).

Один HTTP-сервер MCP на 127.0.0.1:8181 — служба планировщика `qmd` (launchd, schedule.toml [[service]]);
индекс освежают задачи тика qmd-update (лёгкая, раз в час) и qmd-embed (тяжёлая, раз в час, max_delay 3 ч).

Коллекции описаны в ~/ai/pantheon/qmd.toml (правит только штаб: файла нет в карте guard → только hq). Конфиг
самого qmd (~/.config/qmd/index.yml) pantheon пересобирает из qmd.toml перед каждым запуском qmd и никогда не
пишет в него ключ `update:` — в глобальном конфиге qmd исполняет его через bash без всякого доверия, а qmd update
идёт из тика вне песочницы. Поэтому чужая правка index.yml живёт только до следующего запуска.

Поиск — только по смыслу в своей коллекции (QMD-04): инструмент MCP query с searches [{type: "vec"}],
collections и rerank: false. Полный режим (query без searches, переупорядочивание) держит в памяти три модели и в
50–100 раз медленнее; его закрывает хук ctx.py qmd-query.
"""
import contextlib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

PORT = 8181
HOST = "127.0.0.1"  # только петля (QMD-01): адрес без пароля
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
DEFAULT_MASK = "**/*.md"
# Имя индекса передаём явно (`--index index` перед подкомандой): без него qmd ищет .qmd/index.yml вверх от текущей
# папки до корня, и такой проектный конфиг главнее нашего — `qmd init` в ~ увёл бы тик и сервер в чужой конфиг
# (ревью argus 15.10). С --index проектный конфиг не читается.
INDEX = ["--index", "index"]
PLAIN_DIR = re.compile(r"[\w. -]+")
MD_GLOB = re.compile(r"[^{}()|@+!]*\.md")


def set_core(core):
    global P
    P = core


def config_path():
    return os.path.join(P.PANTHEON, "qmd.toml")


def qmd_config_dir():
    """Папка конфига qmd. Задаём явно (QMD_CONFIG_DIR) — чтобы XDG_CONFIG_HOME окружения не увёл qmd в другой файл."""
    return os.environ.get("PANTHEON_QMD_CONFIG_DIR") or os.path.join(P.HOME, ".config", "qmd")


def load():
    """qmd.toml → {port, embed_model, collections: [{name, path, mask, ignore, context}]}; ошибки — ValueError."""
    with open(config_path(), "rb") as fh:
        raw = tomllib.load(fh)
    port = raw.get("port", PORT)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError(f"port: нужно целое 1024–65535, а не {port!r}")
    model = raw.get("embed_model")
    if model is not None and (not isinstance(model, str) or not model.strip() or "\n" in model):
        raise ValueError("embed_model: строка без переводов строк")
    out, seen = [], set()
    for c in raw.get("collection") or []:
        if not isinstance(c, dict):
            raise ValueError("collection: нужна таблица [[collection]]")
        name = str(c.get("name", ""))
        if not NAME.fullmatch(name) or name in seen:
            raise ValueError(f"collection {name!r}: имя только a-z, 0-9, дефис, без повторов")
        seen.add(name)
        p = os.path.realpath(os.path.expanduser(str(c.get("path", ""))))
        if not p.startswith(os.path.realpath(P.HOME) + os.sep):
            raise ValueError(f"collection {name}: путь должен быть внутри домашней папки ({c.get('path')!r})")
        # скрытые папки дома (~/.claude — память ролей и транскрипты, ~/.ssh, ~/.config) и ~/Library (почта, iCloud,
        # заметки приложений) — не для общего индекса, который видят все роли
        under = p[len(os.path.realpath(P.HOME)) + 1:].split(os.sep)
        if any(x.startswith(".") for x in under) or under[0].casefold() == "library":
            raise ValueError(f"collection {name}: путь через скрытую папку или ~/Library ({c.get('path')!r})")
        mask = c.get("mask", DEFAULT_MASK)
        ignore = c.get("ignore", [])
        context = c.get("context", "")
        if not isinstance(mask, str) or not mask.strip():
            raise ValueError(f"collection {name}: mask — непустая строка")
        if not isinstance(ignore, list) or not all(isinstance(x, str) and x.strip() for x in ignore):
            raise ValueError(f"collection {name}: ignore — список непустых строк")
        if not isinstance(context, str):
            raise ValueError(f"collection {name}: context — строка")
        for v in [mask, context, *ignore]:
            if any(ord(ch) < 32 for ch in v):
                raise ValueError(f"collection {name}: управляющие символы в mask, ignore или context")
        # глоб уходит в qmd как есть: « me/**» с пробелом fast-glob не исключит me/, а проверка ниже сочла бы иначе
        if any(g != g.strip() or not g for g in [*mask.split(","), *ignore]):
            raise ValueError(f"collection {name}: пробелы по краям или пустой глоб в mask/ignore")
        # индекс — только markdown: маска вида **/*.json(l) открыла бы журналы, выгрузки и ключи в рабочих папках
        if not all(MD_GLOB.fullmatch(g.rsplit("/", 1)[-1]) for g in mask.split(",")):
            raise ValueError(f"collection {name}: mask — только файлы .md (последняя часть глоба вида *.md)")
        # APFS не различает регистр — пути сравниваем через casefold; rel — срезом, а не relpath (с ним ~/AI/… дал бы
        # «../../ai/…», а «..» сошёл бы за скрытую папку)
        pc = p.casefold()
        for priv in private_paths():
            vc = priv.casefold()
            if pc == vc or pc.startswith(vc + os.sep):
                raise ValueError(f"collection {name}: лежит внутри личного {priv.replace(os.path.realpath(P.HOME), '~')} "
                                 "([private] policy.toml) — этот сервер видят все роли")
            if vc.startswith(pc + os.sep) and not _excluded(priv[len(p) + 1:], mask, ignore):
                raise ValueError(f"collection {name}: накрывает личное {priv.replace(os.path.realpath(P.HOME), '~')} "
                                 "([private] policy.toml) — этот сервер видят все роли; исключи папку в ignore "
                                 "(\"<папка>/**\") или сузь mask")
        out.append({"name": name, "path": p, "mask": mask, "ignore": ignore, "context": context.strip()})
    return {"port": port, "embed_model": model, "collections": out}


def private_paths():
    """Личные пути из [private] policy.toml (SEC-11) и ~/ai/knowledge/me — всегда, даже без policy.toml."""
    out = {os.path.realpath(os.path.join(P.AI_HOME, "knowledge", "me"))}
    with contextlib.suppress(OSError, ValueError):
        with open(os.path.join(P.HOME, ".claude", "pantheon", "policy.toml"), "rb") as fh:
            for x in (tomllib.load(fh).get("private") or {}).get("paths") or []:
                if isinstance(x, str):
                    out.add(os.path.realpath(os.path.expanduser(x)))
    return out


def _excluded(rel, mask, ignore):
    """Личная папка rel (относительно коллекции) точно не попадёт в индекс: она скрытая, её исключает ignore «rel/**»,
    или каждый глоб маски начинается с другой папки без подстановок."""
    if rel == ".":
        return False
    if any(part.startswith(".") for part in rel.split(os.sep)):
        return True  # скрытое qmd не индексирует никогда (store.js: части пути на «.» отброшены)
    # fast-glob исключает папку только записью «rel» или «rel/**» (а «rel/» — нет) и с учётом регистра — сверяем строго
    if any(x in (rel + "/**", rel) for x in ignore):
        return True
    top = rel.split(os.sep, 1)[0].casefold()
    for g in mask.split(","):
        first = g.split("/", 1)
        # APFS не различает регистр: маска «ME/**» найдёт me/ — первую папку сравниваем без регистра
        # обычная папка — только буквы, цифры, «._ -»; иначе подстановка (в том числе @(…), +(…) fast-glob)
        if len(first) < 2 or not PLAIN_DIR.fullmatch(first[0]) or first[0].casefold() == top:
            return False
    return True


def _q(s):
    # Строка JSON — допустимая строка YAML в двойных кавычках; управляющих символов в ней нет (load их не пускает).
    return json.dumps(s, ensure_ascii=False)


def render(cfg):
    """index.yml для qmd. Только path, pattern, ignore, context — ключа update нет и быть не может."""
    lines = ["# Собирает `pantheon qmd config` из ~/ai/pantheon/qmd.toml перед каждым запуском qmd — правки здесь",
             "# пропадут. Ключа update (команда bash при qmd update) здесь нет намеренно.", "collections:"]
    if not cfg["collections"]:
        lines[-1] = "collections: {}"
    for c in cfg["collections"]:
        lines += [f"  {_q(c['name'])}:", f"    path: {_q(c['path'])}", f"    pattern: {_q(c['mask'])}"]
        if c["ignore"]:
            lines.append("    ignore:")
            lines += [f"      - {_q(x)}" for x in c["ignore"]]
        if c["context"]:
            lines += ["    context:", f"      \"/\": {_q(c['context'])}"]
    if cfg.get("embed_model"):
        # модель в index.yml главнее переменной QMD_EMBED_MODEL (проверено 14.10) — менять только здесь
        lines += ["models:", f"  embed: {_q(cfg['embed_model'])}"]
    return "\n".join(lines) + "\n"


def write_config(cfg=None):
    """Пересобрать index.yml. Отдаёт (путь, изменился ли)."""
    cfg = cfg or load()
    d = qmd_config_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "index.yml")
    text = render(cfg)
    try:
        if os.path.islink(p):
            os.remove(p)  # ссылка увела бы запись в чужой файл
        elif open(p, encoding="utf-8").read() == text:
            return p, False
    except OSError:
        pass
    tmp = f"{p}.{os.getpid()}"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, p)
    return p, True


def _ver(p):
    m = re.search(r"/v(\d+)\.(\d+)\.(\d+)/", p)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def qmd_bin():
    """Путь к qmd: PANTHEON_QMD_BIN (тесты), PATH тика, самая новая версия node в nvm, Homebrew."""
    if os.environ.get("PANTHEON_QMD_BIN"):
        return os.environ["PANTHEON_QMD_BIN"]
    found = shutil.which("qmd", path=P.run_env()["PATH"])
    if found:
        return found
    nvm = sorted(glob.glob(os.path.join(P.HOME, ".nvm", "versions", "node", "v*", "bin", "qmd")), key=_ver)
    if nvm:
        return nvm[-1]
    for c in ("/opt/homebrew/bin/qmd", "/usr/local/bin/qmd"):
        if os.path.exists(c):
            return c
    return None


def qmd_env(binary):
    env = P.run_env()
    # node лежит рядом с qmd (nvm); переменные доверия qmd снимаем — пусть решает только наш конфиг
    env["PATH"] = os.path.dirname(os.path.realpath(binary)) + ":" + os.path.dirname(binary) + ":" + env["PATH"]
    env["QMD_CONFIG_DIR"] = qmd_config_dir()
    # QMD_ALLOWED_ORIGINS=* выключил бы защиту от DNS rebinding, XDG_CACHE_HOME увёл бы базу и модели
    for k in ("QMD_TRUST_UPDATE_HOOKS", "QMD_TRUST_LOCAL_CONFIG", "QMD_HOST", "QMD_ALLOWED_HOSTS", "QMD_ALLOWED_ORIGINS",
              "XDG_CACHE_HOME", "INDEX_PATH"):
        env.pop(k, None)
    return env


def workdir():
    # своя пустая папка: qmd ищет проектный .qmd/ от текущей папки, а он главнее глобального конфига
    d = P.path("qmd")
    os.makedirs(d, exist_ok=True)
    return d


def _prepare():
    binary = qmd_bin()
    if not binary:
        print("qmd не найден — поставить: npm install -g @tobilu/qmd (node 22+)", file=sys.stderr)
        return None, None
    try:
        cfg = load()
    except (OSError, ValueError) as e:
        print(f"~/ai/pantheon/qmd.toml: {e}", file=sys.stderr)
        return None, None
    missing = [c["name"] for c in cfg["collections"] if not os.path.isdir(c["path"])]
    if missing:
        # папки нет на этом Mac (у сестры другой набор проектов) — коллекцию пропускаем, а не валим всё
        cfg["collections"] = [c for c in cfg["collections"] if c["name"] not in missing]
        print(f"нет папок на этом Mac, коллекции пропущены: {', '.join(missing)}")
    write_config(cfg)
    return binary, cfg


def run(args, timeout=None):
    binary, _ = _prepare()
    if not binary:
        return 1
    r = subprocess.run([binary, *INDEX, *args], env=qmd_env(binary), cwd=workdir(), stdin=subprocess.DEVNULL,
                       timeout=timeout)
    return r.returncode


def serve():
    """Служба launchd: сервер MCP qmd на переднем плане (без --daemon — за перезапуск отвечает launchd)."""
    binary, cfg = _prepare()
    if not binary:
        return 1
    os.chdir(workdir())
    argv = [binary, *INDEX, "mcp", "--http", "--port", str(cfg["port"]), "--host", HOST]
    os.execve(binary, argv, qmd_env(binary))


def url(cfg=None):
    try:
        port = (cfg or load())["port"]
    except (OSError, ValueError):
        port = PORT
    return f"http://{HOST}:{port}/mcp"


def mcp_registered():
    r = subprocess.run(["claude", "mcp", "get", "qmd"], capture_output=True, text=True, env=P.run_env(), cwd=P.HOME,
                       timeout=60)
    return r.returncode == 0, r.stdout


def install():
    """Подключить qmd на этом Mac: проверка qmd, index.yml, сервер MCP уровня пользователя для Claude."""
    binary, cfg = _prepare()
    if not binary:
        return 1
    ok, out = mcp_registered()
    want = url(cfg)
    if ok and want in out:
        print(f"MCP qmd уже подключён: {want}")
    else:
        if ok:
            subprocess.run(["claude", "mcp", "remove", "--scope", "user", "qmd"], capture_output=True,
                           env=P.run_env(), cwd=P.HOME, timeout=60)
        r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "--transport", "http", "qmd", want],
                           capture_output=True, text=True, env=P.run_env(), cwd=P.HOME, timeout=60)
        if r.returncode != 0:
            print(f"claude mcp add не прошёл: {(r.stderr or r.stdout).strip()}", file=sys.stderr)
            return r.returncode
        print(f"MCP qmd подключён для всех сессий Claude: {want}")
    print("Сервер поднимет тик (служба qmd в schedule.toml); первый индекс: pantheon qmd update, затем pantheon qmd embed")
    return 0


def status():
    binary, cfg = _prepare()
    if not binary:
        return 1
    print(f"qmd: {binary}\nконфиг: {os.path.join(qmd_config_dir(), 'index.yml')} (из ~/ai/pantheon/qmd.toml)\n"
          f"сервер MCP: {url(cfg)}")
    subprocess.run([binary, *INDEX, "status"], env=qmd_env(binary), cwd=workdir(), stdin=subprocess.DEVNULL, timeout=60)
    return 0


def main(rest):
    sub = rest[0] if rest else ""
    if sub == "config":
        binary, _ = _prepare()
        if binary is None and not os.path.exists(config_path()):
            return 1
        print(os.path.join(qmd_config_dir(), "index.yml"))
        return 0
    if sub == "update":
        return run(["update"], timeout=900)
    if sub == "embed":
        return run(["embed"], timeout=3500)
    if sub == "serve":
        return serve()
    if sub == "install":
        return install()
    if sub == "status":
        return status()
    print("pantheon qmd config | update | embed | serve | install | status", file=sys.stderr)
    return 2
