#!/usr/bin/env python3
"""Демон хуков guard (metis-0330, этап 2, ступень 2): держит правила guard загруженными, чтобы вызов хука стоил
15–25 мс клиента на C вместо 70–100 мс холодного Python.

Принцип F1 (README guard): демон только ускоряет. Решает тот же код guard.run, что и медленный путь, — в процессе с
контекстом вызова (guard.set_context: argv, окружение, папка). Любая ошибка демона — ответ «F <причина>» или обрыв, и
клиент идёт медленным путём `hooks/python.sh hooks/guard.py <режим>` с тем же stdin. «Пропустить при сбое демона» и
«отказать во всём при сбое демона» запрещены.

Запуск:
  python.sh daemon.py                    — служба launchd pantheon.svc.hookd: сокет даёт launchd (ключ Sockets,
                                           launch_activate_socket «Listeners»), первое соединение запускает демон
  python.sh daemon.py --socket <путь>    — сокет создаёт сам, когда правила загружены (0600; тесты и замер
                                           bench.py --hookd); при выходе убирает
  python.sh daemon.py --fd <n> [--fd …]  — слушающие сокеты уже открыты под этими номерами: их передаёт исполняемый
                                           файл службы pantheon-hookd (hooks/hookd-svc.c), он берёт их у launchd
  python.sh daemon.py --tcc-probe <файл> — не демон: пробует прочесть Desktop, Documents, Downloads и iCloud Drive и
                                           пишет итог в файл JSON (hookd-install.sh, запрос разрешения TCC; ниже)
  [--idle <с>]                           — простой до выхода (по умолчанию 1800 с; launchd поднимет снова)
  [--uid <n>]                            — ожидаемый uid пира, по умолчанию свой (только для проб отказа «peer»)

Устройство. Один поток. На соединение — fork: ребёнок отвечает на запрос, внук решает под своим сроком (guard.run сам
ставит DEADLINE 8 с; ребёнок убивает внука через DECIDE_LIMIT). Без fork нельзя: set_context делает
os.environ.clear() и меняет глобальные имена модулей guard — в общем процессе вызовы мешали бы друг другу.

Протокол, одно соединение на вызов (версия G2):
  демон  → «A\\n»                                   принят; клиент ждёт его 300 мс, иначе медленный путь
         → «F <причина>\\n»                         вместо «A»: stale, peer
  клиент → «G2 <len_hdr> <len_stdin>\\n» + шапка JSON {"argv", "cwd", "env", "hooks", "version", "umask"} + сырой stdin
  демон  → «X <код> <len_out> <len_err>\\n» + stdout + stderr      решение, целиком одним сообщением
         → «F <причина>\\n»                                        клиенту идти медленным путём
Причины F: stale — файлы правил изменились (выход демона), peer — чужой uid (LOCAL_PEERCRED), proto — чужая версия
или мусор, big — запрос больше MAX_REQ, encoding — шапка или событие не UTF-8 (медленный путь разберёт его сам),
locale — локаль вызова не UTF-8 (медленный путь читает событие в своей кодировке), tree — клиент из другого дерева
плагина, version — другая версия плагина, event — событие не PreToolUse (демон судит только его; остальное — медленный
путь), cwd — папку вызова не открыть, perm — внуку отказано в доступе к файлу (EPERM, EACCES; ниже), spawn — правило
запускает программу (git, gh; ниже), killed — внук не уложился или убит, error — любой другой сбой. Команд управления нет.

Отказ доступа — «F perm», а не решение (решение владельца 04.11, Д-A2). Правила guard на ошибке чтения пути идут
дальше: realpath без strict молча оставляет симлинк нераскрытым, os.path.exists и isfile отвечают «нет», open в
`except OSError` пропускается. У службы launchd права TCC другие, чем у окна (Desktop, Documents, Downloads, iCloud):
внук получил бы EPERM там, где медленный путь читает файл, и пропустил бы то, что медленный путь запрещает. Поэтому во
внуке os.stat, lstat, open, listdir, scandir, readlink, getcwd и встроенный open обёрнуты (trap_perm): первый же EPERM
или EACCES — выход внука кодом PERM_EXIT, ответ «F perm» и медленный путь с правами окна. Папку вызова внук тоже
пробует прочесть (scandir) до решения: git и gh во внуке в закрытой папке ответили бы иначе. Ловушка — на уровне os,
а не в отдельных местах guard_rules: новый код правил под неё попадает сам.

Подпроцесс — «F spawn», а не решение (решение лида 05.11, argus #311 Б1). trap_perm ловит отказ доступа, только когда
внук сам зовёт os или open. Программа, которую правило запускает (git и gh шлюза слияния и push в принятый PR), получает
EPERM от TCC у себя: код не 0, правило читает это как «нет данных» и пропускает то, что медленный путь запретил бы. gh под
launchd вдобавок не видит связки ключей окна. Поэтому во внуке все входы запуска программ обёрнуты (trap_spawn):
subprocess.Popen, _posixsubprocess.fork_exec, os.fork, forkpty, posix_spawn(p), system, popen, exec* и spawn*. Первый
же вызов — выход внука кодом SPAWN_EXIT до запуска программы, ответ «F spawn» и медленный путь. Угадывать такие события
по тексту команды нельзя: правило зовёт git там, где текст этого не выдаёт. Правила без подпроцессов (Read, Write,
Edit, разбор команды Bash) демон решает сам.

Устаревшие правила: при каждом соединении демон сверяет файлы hooks/*.py и .claude-plugin/plugin.json по mtime,
размеру и inode (и их список) с тем, что загрузил. Разошлось — «F stale» и выход: launchd поднимет свежий демон по
следующему соединению, а этот вызов идёт медленным путём. Версия плагина из plugin.json едет и в протоколе.

Счёт решений (F9, metis-0811). Откаты клиент пишет в hookd-fallback.log, а решения демона — нигде: без них долю
откатов не посчитать. Ребёнок, отправив «X …», пишет один байт в канал родителя (неблокирующий: занят — байт теряется,
вызов не ждёт). Родитель копит счёт и не чаще раза в FLUSH_EVERY с, а также перед выходом, дописывает строку
«время<TAB>ok<TAB>число» в ~/.local/state/pantheon/logs/hookd-calls.log. Долю за сутки считает scripts/hookd-stats.py.

Проба TCC (--tcc-probe, решение владельца 04.11). hookd-install.sh запускает её разовым заданием launchd через тот же
pantheon-hookd, что и службу: окна macOS «разрешить доступ» появляются при установке, а не из фона в случайный миг, и
разрешение достаётся тому же ответственному процессу, что у демона. В файле — итог по каждой папке (ok, denied,
missing, error <errno>) и путь ответственного процесса (responsibility_get_pid_responsible_for_pid): им macOS
называет того, кого спрашивает. Правила guard проба не грузит.
"""
import errno
import json
import os
import select
import signal
import socket
import struct
import sys
import time

PROTO = "G2"
MAX_REQ = 8 * 1024 * 1024  # байт шапки и события; больше — «F big», медленный путь
# с: клиент ждёт демона не дольше 7,5 с от своего старта (TOTAL_MS в hookd-client.c) — медленному пути до таймаута хука
# 10 с остаётся 2,5 с. Демон убивает внука раньше, и клиент получает «F killed», а не ждёт до своего срока. guard во
# внуке своего DEADLINE 8 с не достигает: долгое решение уходит на медленный путь, где DEADLINE считается заново
DECIDE_LIMIT = 7.0
RECV_LIMIT = 5.0  # с на приём запроса от клиента
IDLE_DEFAULT = 1800  # с простоя до выхода
REASON_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz-")
PERM_EXIT = 98  # код внука: отказ доступа к файлу (trap_perm) — «F perm». guard сам выходит 0 или 2, сбой Python — 1
PERM_ERRNO = frozenset((errno.EPERM, errno.EACCES))
# функции os, которыми guard читает пути; os.path (realpath, exists, isfile, isdir) берёт их из os в момент вызова
PERM_OS = ("stat", "lstat", "open", "listdir", "scandir", "readlink", "getcwd")
SPAWN_EXIT = 97  # код внука: правило запускает программу (trap_spawn) — «F spawn»
# входы os и posix, которыми запускают программу или копию процесса; exec*, spawn* и popen из os.py зовут их же, но
# обёрнуты сами — на случай, если их тело когда-нибудь возьмёт posix напрямую
SPAWN_OS = ("fork", "forkpty", "posix_spawn", "posix_spawnp", "system", "popen", "execv", "execve", "execl", "execle",
            "execlp", "execlpe", "execvp", "execvpe", "spawnv", "spawnve", "spawnl", "spawnle", "spawnlp", "spawnlpe",
            "spawnvp", "spawnvpe")
CALLS_LOG = "hookd-calls.log"  # счёт решений демона в ~/.local/state/pantheon/logs (F9)
FLUSH_EVERY = 60  # с между строками счёта
# папки под TCC «Файлы и папки», к которым проба просит доступ: имя в итоге → путь от HOME
TCC_DIRS = (("Desktop", "Desktop"), ("Documents", "Documents"), ("Downloads", "Downloads"),
            ("iCloud Drive", os.path.join("Library", "Mobile Documents")))


def trap_perm(on_perm):
    """Внук: EPERM или EACCES из функций PERM_OS и встроенного open — сразу on_perm() (выход PERM_EXIT), до того как
    правило проглотит ошибку в `except OSError`. Обёртки встают и в os.supports_* вместо исходных функций: shutil и
    pathlib сверяют по ним, можно ли передать dir_fd или fd."""
    import builtins
    import io

    def wrap(fn):
        def inner(*a, **kw):
            try:
                return fn(*a, **kw)
            except OSError as e:
                if e.errno in PERM_ERRNO:
                    on_perm()
                raise
        return inner

    for name in PERM_OS:
        fn = getattr(os, name)
        w = wrap(fn)
        setattr(os, name, w)
        for s in (os.supports_dir_fd, os.supports_fd, os.supports_follow_symlinks, os.supports_effective_ids):
            if fn in s:
                s.add(w)
    builtins.open = io.open = wrap(builtins.open)


def trap_spawn(on_spawn):
    """Внук: любой запуск программы или fork — сразу on_spawn() (выход SPAWN_EXIT), до того как программа запустится.
    subprocess.run, check_output, call и asyncio идут через Popen.__init__; Popen внутри зовёт _fork_exec или
    os.posix_spawn — обёрнуты и они, на случай вызова мимо __init__."""
    import posix
    import subprocess

    def stop(*_a, **_kw):
        on_spawn()
        raise OSError(errno.EPERM, "hookd: запуск программы во внуке демона")  # on_spawn не вернётся; на всякий случай

    for mod in {os, posix}:
        for name in SPAWN_OS:
            fn = getattr(mod, name, None)
            if fn is None:
                continue
            setattr(mod, name, stop)
            for s in (os.supports_dir_fd, os.supports_fd, os.supports_follow_symlinks, os.supports_effective_ids):
                if fn in s:
                    s.add(stop)
    subprocess.Popen.__init__ = stop
    if hasattr(subprocess, "_fork_exec"):
        subprocess._fork_exec = stop
    try:
        import _posixsubprocess
        _posixsubprocess.fork_exec = stop
    except ImportError:
        pass


def log(msg):
    """Строка в stderr демона (у службы launchd — ~/.local/state/pantheon/logs/svc-hookd.log)."""
    try:
        sys.stderr.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\thookd\t{os.getpid()}\t{msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


def plugin_version(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
        return v if isinstance(v, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def fingerprint(hooks, root):
    """Отпечаток кода правил: (имя, mtime_ns, размер, inode) каждого hooks/*.py и plugin.json. Новый или пропавший
    файл меняет список."""
    out = []
    try:
        names = sorted(f for f in os.listdir(hooks) if f.endswith(".py"))
    except OSError:
        names = []
    for p in [os.path.join(hooks, f) for f in names] + [os.path.join(root, ".claude-plugin", "plugin.json")]:
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size, st.st_ino))
        except OSError:
            out.append((p, None, None, None))
    return out


def peer_uid(conn):
    """uid процесса на том конце Unix-сокета: macOS — LOCAL_PEERCRED (struct xucred), Linux — SO_PEERCRED."""
    if sys.platform == "darwin":
        raw = conn.getsockopt(0, 0x001, 76)  # SOL_LOCAL, LOCAL_PEERCRED → {cr_version, cr_uid, …}
        _, uid = struct.unpack_from("II", raw)
        return uid
    raw = conn.getsockopt(socket.SOL_SOCKET, getattr(socket, "SO_PEERCRED", 17), 12)  # {pid, uid, gid}
    return struct.unpack("iII", raw)[1]


def launchd_sockets(name="Listeners"):
    """Слушающие сокеты службы launchd (ключ Sockets plist). Вне launchd — OSError (ESRCH)."""
    if sys.platform != "darwin":
        raise OSError("сокет от launchd — только на macOS; вне службы нужен --socket <путь>")
    import ctypes
    lib = ctypes.CDLL(None)
    fn = lib.launch_activate_socket
    fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_int)), ctypes.POINTER(ctypes.c_size_t)]
    fn.restype = ctypes.c_int
    fds, cnt = ctypes.POINTER(ctypes.c_int)(), ctypes.c_size_t(0)
    err = fn(name.encode(), ctypes.byref(fds), ctypes.byref(cnt))
    if err:
        raise OSError(err, f"launch_activate_socket({name}): {os.strerror(err)}")
    try:
        return [socket.socket(fileno=fds[i]) for i in range(cnt.value)]
    finally:
        lib.free.argtypes = [ctypes.c_void_p]
        lib.free(ctypes.cast(fds, ctypes.c_void_p))


def recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise EOFError("клиент закрыл соединение")
        buf += chunk
    return bytes(buf)


def recv_line(conn, limit=128):
    buf = bytearray()
    while not buf.endswith(b"\n"):
        c = conn.recv(1)
        if not c or len(buf) > limit:
            raise EOFError("нет строки запроса")
        buf += c
    return buf[:-1].decode("ascii", "replace")


class Refuse(Exception):
    """Ответ «F <причина>»: клиенту идти медленным путём."""


class Daemon:
    def __init__(self, idle=IDLE_DEFAULT, uid=None):
        self.listeners = []
        self.own_path = self.own_ino = None  # сокет, созданный самим демоном (--socket): убрать при выходе
        self.idle = idle
        self.uid = os.getuid() if uid is None else uid
        self.count_r = self.count_w = None  # канал «решение отправлено» от детей (F9)
        self.ok = 0  # решений с прошлой строки счёта
        self.flushed = time.monotonic()
        self.hooks = os.path.dirname(os.path.realpath(__file__))
        self.root = os.path.dirname(self.hooks)
        self.version = plugin_version(self.root)
        self.fp = fingerprint(self.hooks, self.root)
        sys.path.insert(0, self.hooks)
        import guard  # вход: set_context, run
        import guard_rules  # правила: грузятся один раз, внук берёт их готовыми
        self.guard = guard
        try:  # то, что guard грузит по первому обращению: детям не платить за импорт; сбой — внук загрузит сам
            import hashlib  # noqa: F401
            import ipaddress  # noqa: F401
            import subprocess  # noqa: F401
            guard_rules._mg()
        except Exception as e:
            log(f"предзагрузка: {type(e).__name__}")
        # отпечаток снят до импорта: файл, изменённый во время загрузки, даст «stale» на первом же запросе

    def attach(self, listeners, own_path=None):
        self.listeners = listeners
        if own_path:
            self.own_path, self.own_ino = own_path, os.stat(own_path).st_ino

    def stale(self):
        return fingerprint(self.hooks, self.root) != self.fp

    def cleanup(self):
        if self.own_path:
            try:
                if os.stat(self.own_path).st_ino == self.own_ino:
                    os.unlink(self.own_path)
            except OSError:
                pass

    def flush(self):
        """Строка счёта решений в hookd-calls.log (если было что считать). Сбой записи — строка в журнал демона."""
        n, self.ok, self.flushed = self.ok, 0, time.monotonic()
        if not n:
            return
        try:
            home = os.environ.get("HOME") or ""
            if not home:
                raise OSError("HOME пуст")
            d = os.path.join(home, ".local", "state", "pantheon", "logs")
            os.makedirs(d, exist_ok=True)
            fd = os.open(os.path.join(d, CALLS_LOG), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o644)
            try:
                os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\tok\t{n}\n".encode())
            finally:
                os.close(fd)
        except OSError as e:
            log(f"счёт решений ({n}) не записан в {CALLS_LOG}: {e}")

    def drain(self):
        try:
            self.ok += len(os.read(self.count_r, 65536))
        except OSError:  # BlockingIOError — ложное пробуждение
            pass

    def exit(self, why):
        log(why)
        self.flush()
        self.cleanup()
        os._exit(0)

    def loop(self):
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # дети не становятся зомби
        self.count_r, self.count_w = os.pipe()
        os.set_blocking(self.count_r, False)
        os.set_blocking(self.count_w, False)
        log(f"готов: {self.hooks} версия {self.version or '?'}")
        while True:
            ready, _, _ = select.select(self.listeners + [self.count_r], [], [], self.idle)
            if not ready:
                self.exit("простой — выход")
            for lst in ready:
                if lst == self.count_r:
                    self.drain()
                    continue
                try:
                    conn, _ = lst.accept()
                except (BlockingIOError, InterruptedError, ConnectionAbortedError):
                    continue
                conn.setblocking(True)
                if self.stale():
                    try:
                        conn.sendall(b"F stale\n")
                    except OSError:
                        pass
                    conn.close()
                    self.drain()
                    self.exit("правила изменились (stale) — выход")
                try:
                    pid = os.fork()
                except OSError as e:
                    log(f"fork: {e}")
                    conn.close()
                    continue
                if pid == 0:
                    for x in self.listeners:
                        x.close()
                    os.close(self.count_r)
                    self.serve(conn)
                conn.close()
            if self.ok and time.monotonic() - self.flushed >= FLUSH_EVERY:
                self.flush()

    def serve(self, conn):
        """Ребёнок на соединение. Не возвращается."""
        # SIG_IGN у родителя (loop) наследуется. На macOS waitpid ребёнка при SIG_IGN ждёт выхода внука и даёт ECHILD
        # — «F error» на каждый вызов. На Linux так же. Подпроцессов внук не запускает (trap_spawn — «F spawn»)
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        try:
            if peer_uid(conn) != self.uid:
                raise Refuse("peer")
            conn.sendall(b"A\n")
            conn.settimeout(RECV_LIMIT)
            hdr, raw = self.request(conn)
            conn.settimeout(None)
            code, out, err = self.decide(hdr, raw)
            conn.sendall(f"X {code} {len(out)} {len(err)}\n".encode() + out + err)
            try:  # счёт решений (F9): канал неблокирующий — занят, байт теряется, вызов не ждёт
                os.write(self.count_w, b".")
            except (OSError, TypeError):
                pass
        except Refuse as e:
            self.refuse(conn, str(e))
        except Exception as e:
            log(f"сбой запроса: {type(e).__name__}: {str(e)[:200]}")
            self.refuse(conn, "error")
        os._exit(0)

    @staticmethod
    def refuse(conn, why):
        try:
            conn.sendall(f"F {why}\n".encode())
        except OSError:
            pass

    def request(self, conn):
        """(шапка, событие) из соединения; иначе Refuse."""
        parts = recv_line(conn).split(" ")
        if len(parts) != 3 or parts[0] != PROTO or not all(p.isdigit() for p in parts[1:]):
            raise Refuse("proto")
        n_hdr, n_in = int(parts[1]), int(parts[2])
        if n_hdr + n_in > MAX_REQ:
            raise Refuse("big")
        try:
            hdr = json.loads(recv_exact(conn, n_hdr).decode("utf-8"))
            raw = recv_exact(conn, n_in)
            text = raw.decode("utf-8")  # как разберёт медленный путь кодировку не UTF-8 — решает он сам
        except UnicodeDecodeError:
            raise Refuse("encoding") from None
        except ValueError:
            raise Refuse("proto") from None
        try:  # демон судит только PreToolUse (hooks.json зовёт hookd.sh только на нём); прочее и мусор — медленный путь
            ev = json.loads(text)
        except ValueError:
            ev = None
        if not (isinstance(ev, dict) and ev.get("hook_event_name") == "PreToolUse"):
            raise Refuse("event")
        if not (isinstance(hdr, dict) and isinstance(hdr.get("argv"), list)
                and all(isinstance(x, str) for x in hdr["argv"]) and isinstance(hdr.get("cwd"), str)
                and isinstance(hdr.get("env"), dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in hdr["env"].items())
                and isinstance(hdr.get("hooks"), str) and isinstance(hdr.get("version"), str)
                and isinstance(hdr.get("umask"), int) and 0 <= hdr["umask"] <= 0o777):
            raise Refuse("proto")
        if not utf8_locale(hdr["env"]):
            raise Refuse("locale")
        if os.path.realpath(hdr["hooks"]) != self.hooks:
            raise Refuse("tree")
        if hdr["version"] != self.version:
            raise Refuse("version")
        return hdr, raw

    def decide(self, hdr, raw):
        """(код, stdout, stderr) решения guard в отдельном внуке."""
        try:
            os.chdir(hdr["cwd"])
        except OSError:
            raise Refuse("cwd") from None
        o_r, o_w = os.pipe()
        e_r, e_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(o_r)
                os.close(e_r)
                if self.count_w is not None:  # счёт решений пишет ребёнок, а не внук
                    os.close(self.count_w)
                null = os.open(os.devnull, os.O_RDONLY)
                os.dup2(null, 0)
                os.dup2(o_w, 1)
                os.dup2(e_w, 2)
                for fd in (null, o_w, e_w):
                    os.close(fd)
                # как у нового процесса Python: stdin пуст (событие уже прочитано), stdout в канал — блоками
                sys.stdin = open(0, encoding="utf-8", errors="strict", closefd=False)
                sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
                sys.stderr = open(2, "w", encoding="utf-8", errors="backslashreplace", closefd=False)
                trap_perm(lambda: os._exit(PERM_EXIT))
                trap_spawn(lambda: os._exit(SPAWN_EXIT))
                with os.scandir(".") as it:  # папка вызова не читается (TCC, права) — «F perm»
                    next(it, None)
                os.umask(hdr["umask"])  # файлы журналов и меток — с правами, как у медленного пути
                self.guard.set_context(hdr["argv"], hdr["env"])
                time.tzset()  # TZ вызова: time.tzname, time.timezone; на Linux и время strftime
                self.guard.run(hdr["argv"], raw)
            finally:
                os._exit(99)  # guard.run не возвращается: сюда — только сбой самого демона
        os.close(o_w)
        os.close(e_w)
        bufs = {o_r: bytearray(), e_r: bytearray()}
        open_fds = [o_r, e_r]
        end = time.monotonic() + DECIDE_LIMIT
        while open_fds:
            left = end - time.monotonic()
            ready = select.select(open_fds, [], [], left)[0] if left > 0 else []
            if not ready:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise Refuse("killed")
            for fd in ready:
                chunk = os.read(fd, 65536)
                if chunk:
                    bufs[fd] += chunk
                else:
                    open_fds.remove(fd)
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
        if code < 0:
            raise Refuse("killed")
        if code == PERM_EXIT:
            raise Refuse("perm")
        if code == SPAWN_EXIT:
            raise Refuse("spawn")
        if code == 99:
            raise Refuse("error")
        return code, bytes(bufs[o_r]), bytes(bufs[e_r])


def utf8_locale(env):
    """Кодировка stdin и stdout нового Python в этом окружении — UTF-8: локаль UTF-8, C, POSIX или не задана (Python
    сам переходит на UTF-8). Иначе (KOI8-R и т. п.) медленный путь читал бы событие в своей кодировке — «F locale»."""
    v = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG") or ""
    low = v.lower().replace("-", "")
    return v in ("", "C", "POSIX") or low.startswith("c.") or low.endswith(".utf8") or low == "utf8" or ".utf8@" in low


def bind_own(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        srv.bind(path)
    finally:
        os.umask(old)
    srv.listen(64)
    return srv


def responsible_path():
    """Путь исполняемого файла процесса, которому macOS приписывает доступ этого (ответственный процесс TCC)."""
    if sys.platform != "darwin":
        return ""
    try:
        import ctypes
        lib = ctypes.CDLL(None)
        fn = lib.responsibility_get_pid_responsible_for_pid
        fn.argtypes, fn.restype = [ctypes.c_int], ctypes.c_int
        pid = fn(os.getpid())
        proc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = ctypes.create_string_buffer(4096)
        if pid <= 0 or proc.proc_pidpath(pid, buf, 4096) <= 0:
            return ""
        return buf.value.decode("utf-8", "replace")
    except (OSError, AttributeError, ValueError):
        return ""


def tcc_probe(out):
    """Проба доступа к папкам TCC_DIRS (запрос разрешения при установке, --check). Итог — JSON в out; код 0, сбой
    записи — 1 с причиной."""
    home = os.environ.get("HOME") or ""
    dirs = {}
    for name, rel in TCC_DIRS:
        p = os.path.join(home, rel)
        try:
            with os.scandir(p) as it:  # чтение списка — то, что спрашивает macOS; stat папки не спрашивает
                next(it, None)
            dirs[name] = "ok"
        except FileNotFoundError:
            dirs[name] = "missing"
        except OSError as e:
            dirs[name] = "denied" if e.errno in PERM_ERRNO else f"error {e.errno}"
    res = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid(), "home": home,
           "responsible": responsible_path(), "dirs": dirs}
    try:
        with open(out + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
        os.replace(out + ".tmp", out)
    except OSError as e:
        sys.stderr.write(f"hookd: итог пробы не записан в {out}: {e}\n")
        os._exit(1)
    os._exit(0)


def listening(s):
    """Сокет слушает. Linux отвечает SO_ACCEPTCONN; macOS его не знает (ENOPROTOOPT) — там слушающий сокет Unix тот,
    что привязан к пути и ни с кем не соединён (socketpair и соединения — с собеседником, непривязанный — без пути)."""
    try:
        return bool(s.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
    except (OSError, AttributeError):
        pass
    try:
        s.getpeername()
        return False
    except OSError:
        return bool(s.getsockname())


def fd_sockets(fds):
    """Слушающие сокеты Unix под номерами fds (их передал pantheon-hookd). Не сокет, не Unix или не слушает — OSError."""
    out = []
    for n in fds:
        s = socket.socket(fileno=n)
        if s.family != socket.AF_UNIX or s.type != socket.SOCK_STREAM or not listening(s):
            raise OSError(f"--fd {n}: не слушающий сокет Unix")
        s.set_inheritable(False)
        s.setblocking(False)
        out.append(s)
    return out


def main(argv):
    sock, idle, uid, fds, probe = None, IDLE_DEFAULT, None, [], None
    it = iter(argv)
    try:
        for a in it:
            if a == "--socket":
                sock = next(it)
            elif a == "--idle":
                idle = float(next(it))
            elif a == "--uid":
                uid = int(next(it))
            elif a == "--fd":
                fds.append(int(next(it)))
                if fds[-1] < 3:
                    raise ValueError(f"--fd {fds[-1]}")
            elif a == "--tcc-probe":
                probe = next(it)
            else:
                raise ValueError(a)
        if (sock and fds) or (probe and (sock or fds)):
            raise ValueError("--socket, --fd и --tcc-probe — порознь")
    except (StopIteration, ValueError) as e:
        e = e or "у последнего ключа нет значения"
        sys.stderr.write(f"hookd: плохие аргументы ({e}); нужно: daemon.py [--socket <путь> | --fd <n>…] [--idle <с>]"
                         " или daemon.py --tcc-probe <файл>\n")
        os._exit(64)
    if probe:
        tcc_probe(probe)
    # launchd: сокет взять сразу — иначе служба считается сломанной; соединения ждут в очереди, пока грузятся правила.
    # --socket: сокет появляется только у готового демона — тесты и замер ждут его файл
    listeners = None
    if fds:
        listeners = take_sockets(lambda: fd_sockets(fds))
    elif not sock:
        listeners = take_sockets(launchd_sockets)
    try:
        d = Daemon(idle=idle, uid=uid)
    except BaseException as e:  # noqa: B036 — правила не загрузились: выход, клиенты идут медленным путём
        log(f"правила guard не загрузились: {type(e).__name__}: {str(e)[:200]}")
        os._exit(1)
    if sock:
        listeners = take_sockets(lambda: [bind_own(sock)])
    d.attach(listeners, own_path=sock)
    d.loop()


def take_sockets(get):
    try:
        listeners = get()
    except OSError as e:
        sys.stderr.write(f"hookd: сокет не получен: {e}\n")
        os._exit(1)
    if not listeners:
        sys.stderr.write("hookd: launchd не дал ни одного сокета (ключ Sockets → Listeners в plist)\n")
        os._exit(1)
    return listeners


if __name__ == "__main__":
    main(sys.argv[1:])
