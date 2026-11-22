"""Помощники test_claude_sync.py: подложенные объекты клона и коммит окна во временном индексе (metis-1327)."""
import hashlib
import os
import subprocess
import zlib


def plant(objs, sha, kind, body):
    """Свободный объект под чужим SHA (git хеш при чтении не сверяет, свободный перекрывает pack) → (путь, старое)."""
    p = os.path.join(objs, sha[:2], sha[2:])
    old = None
    if os.path.exists(p):
        with open(p, "rb") as fh:
            old = fh.read()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".t", "wb") as fh:
        fh.write(zlib.compress(b"%s %d\0" % (kind, len(body)) + body))
    os.replace(p + ".t", p)
    return p, old


def unplant(po):
    p, old = po
    if old is None:
        os.unlink(p)
        return
    with open(p + ".t", "wb") as fh:
        fh.write(old)
    os.replace(p + ".t", p)


def window_commit(wt, index, files):
    """Коммит окна поверх HEAD копии wt: свои файлы {путь: текст} — во временном индексе index."""
    env = dict(os.environ, GIT_INDEX_FILE=index, GIT_AUTHOR_NAME="окно",
               GIT_AUTHOR_EMAIL="w@localhost", GIT_COMMITTER_NAME="окно", GIT_COMMITTER_EMAIL="w@localhost")

    def run(*a, data=None):
        return subprocess.run(["git", "-C", wt, *a], input=data, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
    run("read-tree", "HEAD")
    for rel, text in files.items():
        run("update-index", "--add", "--cacheinfo", f"100644,{run('hash-object', '-w', '--stdin', data=text)},{rel}")
    return run("commit-tree", run("write-tree"), "-p", "HEAD", "-m", "окно")


def git(d, *args):
    r = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "-c", "init.defaultBranch=main", *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def put(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


def read(d, rel):
    try:
        with open(os.path.join(d, rel)) as fh:
            return fh.read()
    except OSError:
        return None


def digest(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def mv(*pairs):   # переименования (src, dst); dst None — пустая папка src, src None — rmdir dst
    for a, b in pairs:
        os.mkdir(a) if b is None else os.rmdir(b) if a is None else os.rename(a, b)
