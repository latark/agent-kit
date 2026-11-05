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
плагина, version — другая версия плагина, cwd — папку вызова не открыть, killed — внук не уложился или убит, error
— любой другой сбой. Команд управления нет.

Устаревшие правила: при каждом соединении демон сверяет файлы hooks/*.py и .claude-plugin/plugin.json по mtime,
размеру и inode (и их список) с тем, что загрузил. Разошлось — «F stale» и выход: launchd поднимет свежий демон по
следующему соединению, а этот вызов идёт медленным путём. Версия плагина из plugin.json едет и в протоколе.
"""
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
DECIDE_LIMIT = 8.3  # с: guard сам кончает за DEADLINE 8 с, клиент ждёт решения 8,5 с
RECV_LIMIT = 5.0  # с на приём запроса от клиента
IDLE_DEFAULT = 1800  # с простоя до выхода
REASON_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz-")


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

    def loop(self):
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # дети не становятся зомби
        log(f"готов: {self.hooks} версия {self.version or '?'}")
        while True:
            ready, _, _ = select.select(self.listeners, [], [], self.idle)
            if not ready:
                log("простой — выход")
                self.cleanup()
                os._exit(0)
            for lst in ready:
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
                    log("правила изменились (stale) — выход")
                    self.cleanup()
                    os._exit(0)
                try:
                    pid = os.fork()
                except OSError as e:
                    log(f"fork: {e}")
                    conn.close()
                    continue
                if pid == 0:
                    for x in self.listeners:
                        x.close()
                    self.serve(conn)
                conn.close()

    def serve(self, conn):
        """Ребёнок на соединение. Не возвращается."""
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
            raw.decode("utf-8")  # как разберёт медленный путь кодировку не UTF-8 — решает он сам
        except UnicodeDecodeError:
            raise Refuse("encoding") from None
        except ValueError:
            raise Refuse("proto") from None
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
                os.umask(hdr["umask"])  # файлы журналов и меток — с правами, как у медленного пути
                self.guard.set_context(hdr["argv"], hdr["env"])
                time.tzset()  # время в журналах — по TZ вызова
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


def main(argv):
    sock, idle, uid = None, IDLE_DEFAULT, None
    it = iter(argv)
    try:
        for a in it:
            if a == "--socket":
                sock = next(it)
            elif a == "--idle":
                idle = float(next(it))
            elif a == "--uid":
                uid = int(next(it))
            else:
                raise ValueError(a)
    except (StopIteration, ValueError) as e:
        sys.stderr.write(f"hookd: плохие аргументы ({e}); нужно: daemon.py [--socket <путь>] [--idle <с>]\n")
        os._exit(64)
    # launchd: сокет взять сразу — иначе служба считается сломанной; соединения ждут в очереди, пока грузятся правила.
    # --socket: сокет появляется только у готового демона — тесты и замер ждут его файл
    listeners = None
    if not sock:
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
