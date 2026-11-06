#!/usr/bin/env python3
"""Хуки репозитория, которые читают или пишут файлы, — на замену скриптам .claude/hooks (metis-0933, класс 2).

    python3 -I repo_hooks.py reexport <путь route.ts>
    python3 -I repo_hooks.py env-sync <путь правленого файла> [<example> <local> <production>]

Запускает in_repo.py пакета: cwd и CLAUDE_PROJECT_DIR — репозиторий (его путь in_repo.py уже проверил: без ссылок),
путь файла — последним аргументом (--file-arg). Хук пакета идёт вне песочницы окна, а окно пишет папки репозитория:
исходный скрипт по ссылке, которую подложило окно (app/app → чужая папка, .env.production → чужой файл), создавал и
перезаписывал файлы вне репозитория и выводил строки чужого файла (ревью argus C1 и C2 PR #360). Здесь каждый файл
открывается от папки репозитория по звеньям: openat с O_NOFOLLOW, без «.» и «..»; звено-ссылка, не папка, не обычный
файл или файл с другими жёсткими ссылками — отказ строкой в stdout, файл не тронут. Запись — только так же.

reexport — check-reexport.sh MorphStream/app: для src/app/api/<путь>/route.ts создаёт или обновляет app/api/<путь>/
route.ts строкой `export { GET,POST } from '@/app/api/<путь>/route'`. env-sync — check-env-sync.sh: сверяет структуру
.env.example, .env.local и .env.production (ключи, порядок, комментарии; значения справа от «=» не сравнивает) и
выводит расхождение. Оба не блокируют: выход 0 всегда. Python 3.9+."""
import difflib
import os
import re
import stat
import sys

LIMIT = 1 << 20
METHODS = re.compile(r"export (?:async )?function (GET|POST|PUT|PATCH|DELETE|OPTIONS)")
ENV_LINE = re.compile(r"^([ \t\r\f\v]*)#?[ \t\r\f\v]*((?:export[ \t\r\f\v]+)?[A-Za-z_][A-Za-z0-9_]*=).*$")
TRIAD = (".env.example", ".env.local", ".env.production")


class Refused(OSError):
    """Звено пути — ссылка, не папка или не обычный файл: в репозитории его не трогаем."""


def repo_root():
    return os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def rel_in(repo, p):
    """Путь p относительно repo или None, если p вне repo."""
    p = os.path.normpath(os.path.join(repo, p))
    return p[len(repo):].lstrip("/") if p.startswith(repo.rstrip("/") + "/") else None


def _parent(repo, rel, make):
    """fd папки-родителя rel и имя последнего звена; звенья — openat с O_NOFOLLOW от repo, make — mkdir недостающих."""
    parts = rel.split("/")
    if not rel or any(x in ("", ".", "..") for x in parts):
        raise Refused(f"{rel!r}: не путь внутри репозитория")
    fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
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


def read_in(repo, rel):
    """Текст файла rel репозитория; FileNotFoundError — нет файла или папки, Refused — ссылка и прочее."""
    dfd, name = _parent(repo, rel, False)
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


def write_in(repo, rel, text):
    """Записать text в файл rel репозитория, создав недостающие папки; ссылка на любом звене — Refused."""
    dfd, name = _parent(repo, rel, True)
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


def reexport(repo, file_path):
    if not re.search(r"src/app/api/.*/route\.ts$", file_path):
        return 0
    rel_path = re.sub(r"^src/app/api/", "", re.sub(r"^.*/src/app/api/", "", file_path))
    app_file = "app/api/" + rel_path
    import_path = "@/app/api/" + re.sub(r"/route.ts", "", rel_path, count=1) + "/route"
    src_rel = rel_in(repo, file_path)
    try:
        src = read_in(repo, src_rel) if src_rel else ""
    except OSError:
        src = ""
    exports = sorted(set(METHODS.findall(src)))
    line = f"export {{ {','.join(exports)} }} from '{import_path}'\n"
    try:
        try:
            current = read_in(repo, app_file)
        except FileNotFoundError:
            current = None
        if current is not None:
            missing = [m for m in exports if m not in current]
            if missing:
                print(f"⚠️ Re-export устарел: {app_file}")
                print(f"   Отсутствуют: {' '.join(missing)}")
                write_in(repo, app_file, line)
                print(f"✓ Обновлён re-export: {app_file}")
            return 0
        if not exports:
            print(f"⚠️ Нет HTTP методов в {file_path}")
            return 0
        write_in(repo, app_file, line)
        print(f"✓ Создан re-export: {app_file}")
    except OSError as e:
        print(f"⚠️ re-export: {app_file} не тронут — {e}")
    return 0


def normalize(text):
    return [ENV_LINE.sub(r"\1\2", x) for x in text.split("\n")]


def delta(a, b):
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out += [f"< {x}" for x in a[i1:i2]] + (["---"] if tag == "replace" else []) + [f"> {x}" for x in b[j1:j2]]
    return "\n".join(out)


def env_sync(repo, file_path, names):
    if os.path.basename(file_path) not in names:
        return 0
    texts = []
    for n in names:
        try:
            texts.append(normalize(read_in(repo, n)))
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


def main(argv):
    if len(argv) < 2 or argv[0] not in ("reexport", "env-sync") or (argv[0] == "env-sync" and len(argv) not in (2, 5)):
        print("repo_hooks.py: нужно reexport <файл> | env-sync <файл> [<example> <local> <production>]",
              file=sys.stderr)
        return 0
    repo = repo_root()
    if argv[0] == "reexport":
        return reexport(repo, argv[1])
    return env_sync(repo, argv[1], tuple(argv[2:5]) if len(argv) == 5 else TRIAD)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
