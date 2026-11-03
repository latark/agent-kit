"""Общее для тестов guard: корневая временная папка, где репозиторий создаётся (metis-0715, metis-0729).

Копия mkroot() из plugins/pantheon/tests/_py311.py (PR #279) с одним добавлением — параметр first: тест, которому
нужна своя первая папка (Linux: /var/tmp, чтобы корень не лежал в /tmp), называет её, и она идёт раньше запасных."""
import os
import shutil
import tempfile


def mkroot(prefix, first=None):
    """Под `heavy` в окне роли TMPDIR — кэш песочницы, а песочница запрещает там запись в `.git/hooks` и `.git/config`
    (защита от подмены хуков): `git init` падает с кодом 128. Берём первую папку из списка (first, TMPDIR, свой TMPDIR
    роли `/tmp/claude-<uid>`), где `.git/hooks` создаётся; ни одной — обычный mkdtemp (тест упадёт на своём месте)."""
    uid = os.getuid()
    for base in (first, os.environ.get("TMPDIR"), "/tmp/claude-%d" % uid, "/private/tmp/claude-%d" % uid):
        if not base or not os.path.isdir(base):
            continue
        try:
            probe = tempfile.mkdtemp(prefix="gitprobe-", dir=base)
        except OSError:
            continue
        try:
            os.makedirs(os.path.join(probe, ".git", "hooks"))
            with open(os.path.join(probe, ".git", "config"), "w"):
                pass
            ok = True
        except OSError:
            ok = False
        finally:
            shutil.rmtree(probe, ignore_errors=True)
        if ok:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
    return tempfile.mkdtemp(prefix=prefix)
