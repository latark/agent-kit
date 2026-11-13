#!/usr/bin/env python3
"""Хуки репозитория, которые читают или пишут файлы, — на замену скриптам .claude/hooks (metis-0933, класс 2).

    python3 -I repo_hooks.py reexport <путь route.ts>
    python3 -I repo_hooks.py env-sync <путь правленого файла> [<example> <local> <production>]
    python3 -I repo_hooks.py fsd <путь правленого файла>
    python3 -I repo_hooks.py cuda-safety <путь правленого файла>

Запускает только in_repo.py пакета (--file-arg): он открыл корень репозитория по звеньям без ссылок и передал его
открытый дескриптор (fd) — номер в PANTHEON_REPO_FD, папка процесса — тот же корень. Хук пакета идёт вне песочницы
окна, а окно пишет папки репозитория и его родителя: исходный скрипт по ссылке, которую подложило окно (app/app →
чужая папка, .env.production → чужой файл), создавал и перезаписывал файлы вне репозитория и выводил строки чужого
файла (ревью argus C1, C2 и D2 PR #360). Здесь путь репозитория заново не разрешается: CLAUDE_PROJECT_DIR — только
строка, от которой считается относительный путь файла, а каждый файл открывается от fd корня по звеньям: openat с
O_NOFOLLOW, без «.» и «..»; звено-ссылка, не папка, не обычный файл или файл с другими жёсткими ссылками — отказ
строкой в stdout, файл не тронут. Запись — только так же. Без fd корня (запуск не через in_repo.py) — строка отказа
в stdout, ничего не читается.

reexport — check-reexport.sh проекта app: для src/app/api/<путь>/route.ts создаёт или обновляет app/api/<путь>/
route.ts строкой `export { GET,POST } from '@/app/api/<путь>/route'`. env-sync — check-env-sync.sh: сверяет структуру
.env.example, .env.local и .env.production (ключи, порядок, комментарии; значения справа от «=» не сравнивает) и
выводит расхождение; строки не вида `KEY=` (комментарии, мусор, строка без «=» — в ней может быть ключ) выводит маской.
fsd — check-fsd.sh проекта app: импорты слоя FSD правленого файла (shared, entities, features, widgets).
cuda-safety — check-cuda-safety.sh gpu-worker: вызовы, которые инициализируют CUDA до fork, в правленом .py.
Все не блокируют: выход 0 всегда. Python 3.9+."""
import difflib
import os
import re
import stat
import sys

REPO_FD_ENV = "PANTHEON_REPO_FD"
LIMIT = 1 << 20
METHODS = re.compile(r"export (?:async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)")
ENV_KEY = re.compile(r"[ \t\r\f\v]*#?[ \t\r\f\v]*(?:export[ \t\r\f\v]+)?[A-Za-z_][A-Za-z0-9_]*=")
ENV_LINE = re.compile(r"^([ \t\r\f\v]*)#?[ \t\r\f\v]*((?:export[ \t\r\f\v]+)?[A-Za-z_][A-Za-z0-9_]*=).*$")
TRIAD = (".env.example", ".env.local", ".env.production")


class Refused(OSError):
    """Звено пути — ссылка, не папка или не обычный файл: в репозитории его не трогаем."""


def repo_root():
    """(fd корня от in_repo.py, строка пути репозитория) или None: fd не передан или не папка."""
    v, repo = os.environ.get(REPO_FD_ENV, ""), os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not v.isdigit() or not repo.startswith("/"):
        return None
    try:
        if not stat.S_ISDIR(os.fstat(int(v)).st_mode):
            return None
    except OSError:
        return None
    return int(v), repo


def rel_in(repo, p):
    """Путь p относительно repo или None, если p вне repo."""
    p = os.path.normpath(os.path.join(repo, p))
    return p[len(repo):].lstrip("/") if p.startswith(repo.rstrip("/") + "/") else None


def _parent(root, rel, make):
    """fd папки-родителя rel и имя последнего звена; звенья — openat с O_NOFOLLOW от fd корня root, make — mkdir
    недостающих. Путь корня заново не открывается: его звенья окно могло подменить после проверки in_repo.py."""
    parts = rel.split("/")
    if not rel or any(x in ("", ".", "..") for x in parts):
        raise Refused(f"{rel!r}: не путь внутри репозитория")
    fd = os.dup(root)
    try:
        for part in parts[:-1]:
            try:
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not make:
                    raise
                os.mkdir(part, 0o755, dir_fd=fd)  # на месте ссылки — EEXIST: mkdir ссылку не проходит
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as e:
                raise Refused(f"{part}: ссылка или не папка ({e.strerror})")
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd, parts[-1]


def _regular(fd, rel):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > LIMIT:
        raise Refused(f"{rel}: не обычный файл, с другими жёсткими ссылками или больше {LIMIT} байт")


def read_in(root, rel):
    """Текст файла rel репозитория; FileNotFoundError — нет файла или папки, Refused — ссылка и прочее."""
    dfd, name = _parent(root, rel, False)
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        except FileNotFoundError:
            raise
        except OSError as e:
            raise Refused(f"{rel}: ссылка или не файл ({e.strerror})")
    finally:
        os.close(dfd)
    try:
        _regular(fd, rel)
        return os.read(fd, LIMIT + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def write_in(root, rel, text):
    """Записать text в файл rel репозитория, создав недостающие папки; ссылка на любом звене — Refused."""
    dfd, name = _parent(root, rel, True)
    try:
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dir_fd=dfd)
        except OSError as e:
            raise Refused(f"{rel}: ссылка или не файл ({e.strerror})")
    finally:
        os.close(dfd)
    try:
        _regular(fd, rel)
        os.ftruncate(fd, 0)
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def reexport(root, repo, file_path):
    if not re.search(r"src/app/api/.*/route\.ts$", file_path):
        return 0
    rel_path = re.sub(r"^src/app/api/", "", re.sub(r"^.*/src/app/api/", "", file_path))
    app_file = "app/api/" + rel_path
    import_path = "@/app/api/" + re.sub(r"/route.ts", "", rel_path, count=1) + "/route"
    src_rel = rel_in(repo, file_path)
    try:
        src = read_in(root, src_rel) if src_rel else ""
    except OSError:
        src = ""
    exports = sorted(set(METHODS.findall(src)))
    line = f"export {{ {','.join(exports)} }} from '{import_path}'\n"
    try:
        try:
            current = read_in(root, app_file)
        except FileNotFoundError:
            current = None
        if current is not None:
            missing = [m for m in exports if m not in current]
            if missing:
                print(f"⚠️ Re-export устарел: {app_file}")
                print(f"   Отсутствуют: {' '.join(missing)}")
                write_in(root, app_file, line)
                print(f"✓ Обновлён re-export: {app_file}")
            return 0
        if not exports:
            print(f"⚠️ Нет HTTP методов в {file_path}")
            return 0
        write_in(root, app_file, line)
        print(f"✓ Создан re-export: {app_file}")
    except OSError as e:
        print(f"⚠️ re-export: {app_file} не тронут — {e}")
    return 0


def normalize(text):
    return [ENV_LINE.sub(r"\1\2", x) for x in text.split("\n")]


def masked(line):
    """Строка вывода env-sync: вида `KEY=` (после normalize) и пустая — как есть, иначе маска: в строке без «=»
    или в комментарии может быть ключ (ревью argus D2, Д2)."""
    return line if not line.strip() or ENV_KEY.fullmatch(line) else f"‹строка не KEY=, {len(line)} зн. скрыта›"


def delta(a, b):
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out += [f"< {masked(x)}" for x in a[i1:i2]] + (["---"] if tag == "replace" else []) + [
                f"> {masked(x)}" for x in b[j1:j2]]
    return "\n".join(out)


def env_sync(root, file_path, names):
    if os.path.basename(file_path) not in names:
        return 0
    texts = []
    for n in names:
        try:
            texts.append(normalize(read_in(root, n)))
        except FileNotFoundError:
            print(f"ℹ️ .env-sync: файл {n} отсутствует — проверку пропускаю")
            return 0
        except OSError as e:
            print(f"⚠️ .env-sync: {n} не прочитан — {e}; проверку пропускаю")
            return 0
    report = []
    for n, t in zip(names[1:], texts[1:]):
        if t != texts[0]:
            report.append(f"\n--- {names[0]} (<) ↔ {n} (>) ---\n{delta(texts[0], t)}\n")
    if report:
        print("⚠️ .env-sync: структура .env-файлов рассинхронизирована.")
        print("   Ключи, их порядок и комментарии должны совпадать во всех трёх файлах — отличаться могут только значения.")
        print("".join(report))
        print("Приведи файлы к идентичной структуре (см. память проекта: .env files sync).")
    return 0


FSD_LAYER = re.compile(r".*/src/(shared|entities|features|widgets|pages|app)/")
FSD_RULES = {
    "shared": (r"from ['\"]@/(entities|features|widgets|pages|app)/",
               "⚠️ FSD: shared не может импортировать из верхних слоёв"),
    "entities": (r"from ['\"]@/(features|widgets|pages|app)/",
                 "⚠️ FSD: entities не может импортировать из features/widgets/pages/app"),
    "features": (r"from ['\"]@/(widgets|pages)/", "⚠️ FSD: features не может импортировать из widgets/pages"),
    "widgets": (r"from ['\"]@/pages/", "⚠️ FSD: widgets не может импортировать из pages"),
}


def _text_of(root, repo, file_path):
    """Текст правленого файла репозитория по fd корня или None (вне репозитория, нет файла, ссылка — как
    `grep … 2>/dev/null` и `[ -f ] || exit 0` исходных скриптов: молча)."""
    rel = rel_in(repo, file_path)
    try:
        return read_in(root, rel) if rel else None
    except OSError:
        return None


def fsd(root, repo, file_path):
    m = FSD_LAYER.match(file_path)
    text = _text_of(root, repo, file_path) if m else None
    if text is None:
        return 0
    lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
    grep = lambda rx: [f"{n}:{x}" for n, x in enumerate(lines, 1) if re.search(rx, x)]  # noqa: E731
    layer = m.group(1)
    if layer in FSD_RULES:
        rx, msg = FSD_RULES[layer]
        hits = grep(rx)
        if hits:
            print(msg)
            print("\n".join(hits[:5]))
    feature = re.match(r".*/src/features/([^/]*)/", file_path) if layer == "features" else None
    if feature and feature.group(1):
        hits = [h for h in grep(r"from ['\"]@/features/") if f"@/features/{feature.group(1)}" not in h]
        if hits:
            print("⚠️ FSD: features не может импортировать другие features")
            print("\n".join(hits[:5]))
    return 0


def strip_noncode(text):
    """Как awk strip_noncode check-cuda-safety.sh: без # комментариев и строк внутри тройных кавычек."""
    out, indoc = [], False
    for line in text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"):
        line = line.split("#", 1)[0]
        n = line.count('"""') % 2
        if indoc:
            indoc = not n
            continue
        if n:
            indoc = True
            continue
        out.append(line)
    return out


def cuda_safety(root, repo, file_path):
    text = _text_of(root, repo, file_path) if file_path.endswith(".py") else None
    if text is None:
        return 0
    code, base, warned = strip_noncode(text), os.path.basename(file_path), False
    if any(re.search(r"get_available_providers\s*\(", x) for x in code):
        print(f"⚠️ CUDA-safety: вызов get_available_providers() в {base}")
        print("   Он вызывает cudaGetDeviceCount() → инициализирует CUDA. Если файл исполняется в")
        print("   parent-процессе ДО mp.fork() — GPU subprocess упадёт в CPU mode (0.3 FPS вместо 24+).")
        print("   Safe-альтернатива: onnxruntime.get_all_providers().")
        warned = True
    if any(re.search(r"CodecContext.*\.open\s*\(", x) or re.search(r"h264_nvenc.*\.open\s*\(", x) for x in code):
        print(f"⚠️ CUDA-safety: CodecContext.open() с GPU-кодеком в {base}")
        print("   open() на NVENC-кодеке инициализирует CUDA. Используй deferred-init pattern")
        print("   (изолированный subprocess probe), как в patches/aiortc_h264_nvenc.py.")
        warned = True
    if warned:
        print("")
        print("→ Прогони агент cuda-safety-reviewer — убедись, что паттерн не в parent pre-fork пути.")
        print('  Детали: CLAUDE.md → "CUDA + fork() SAFETY".')
    return 0


def main(argv):
    hooks = ("reexport", "env-sync", "fsd", "cuda-safety")
    if len(argv) < 2 or argv[0] not in hooks or len(argv) not in ((2, 5) if argv[0] == "env-sync" else (2,)):
        print("repo_hooks.py: нужно reexport | fsd | cuda-safety <файл> | env-sync <файл> [<example> <local> "
              "<production>]", file=sys.stderr)
        return 0
    got = repo_root()
    if got is None:
        print(f"⚠️ repo_hooks.py {argv[0]}: нет fd корня репозитория ({REPO_FD_ENV}) — запуск только через in_repo.py;"
              " хук пропущен")
        return 0
    root, repo = got
    if argv[0] == "reexport":
        return reexport(root, repo, argv[1])
    if argv[0] == "fsd":
        return fsd(root, repo, argv[1])
    if argv[0] == "cuda-safety":
        return cuda_safety(root, repo, argv[1])
    return env_sync(root, argv[1], tuple(argv[2:5]) if len(argv) == 5 else TRIAD)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
