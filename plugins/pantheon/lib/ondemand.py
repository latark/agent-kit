"""Служба по требованию (metis-0151): launchd держит сокет, процесс поднимается первым соединением и уходит в простое.

Зачем: сервер qmd держал около 350 МБ круглые сутки ради нескольких вызовов в день (служба с KeepAlive). Теперь
порт 127.0.0.1:<socket> слушает сам launchd (ключ Sockets в plist службы, без KeepAlive). Первое соединение
запускает службу, то есть этот прокси. Прокси забирает сокет у launchd (launch_activate_socket), поднимает настоящий
сервер на свободном внутреннем порту петли и пересылает байты в обе стороны. Если `idle` секунд не прошло ни одного
байта и не было новых соединений, прокси гасит сервер, закрывает соединения и выходит. Сокет остаётся у launchd:
следующее соединение (или пришедшее в момент выхода — оно ждёт в очереди сокета) запустит службу заново.

Простой считается по байтам, а не по открытым соединениям: клиенты MCP держат часами молчащие потоки
subscriptions/listen, и счёт по соединениям не отпустил бы сервер никогда. qmd 2.8 по HTTP работает без сессий
(протокол MCP 2026-07-28: нет Mcp-Session-Id), поэтому перезапуск сервера не даёт клиентам 404 «session not found».

Только стандартная библиотека.
Запасной путь для тестов: PANTHEON_LISTEN_FDS="3[,4…]" — готовые слушающие сокеты вместо launchd.
"""
import ctypes
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time

LOOPBACK = "127.0.0.1"
LAUNCHD_NAME = "Listeners"  # имя записи в словаре Sockets plist службы
READY_TIMEOUT = 60  # сколько ждать, пока сервер начнёт принимать соединения
STOP_TIMEOUT = 10  # сколько ждать выхода сервера после SIGTERM, потом SIGKILL


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M')} по требованию: {msg}", file=sys.stderr, flush=True)


def launchd_fds(name=LAUNCHD_NAME):
    """Дескрипторы сокета `name` из plist службы. Не под launchd или нет такого сокета — OSError."""
    try:
        libc = ctypes.CDLL(None)
        fn = libc.launch_activate_socket
    except (OSError, AttributeError) as e:
        raise OSError(f"launch_activate_socket недоступен: {e}") from None
    # int launch_activate_socket(const char *name, int **fds, size_t *cnt) — launch.h, macOS 10.10+
    fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_int)), ctypes.POINTER(ctypes.c_size_t)]
    fn.restype = ctypes.c_int
    fds = ctypes.POINTER(ctypes.c_int)()
    cnt = ctypes.c_size_t(0)
    err = fn(name.encode(), ctypes.byref(fds), ctypes.byref(cnt))
    if err:
        raise OSError(err, f"launch_activate_socket({name}): {os.strerror(err)}")
    try:
        return [fds[i] for i in range(cnt.value)]
    finally:
        libc.free.argtypes = [ctypes.c_void_p]
        libc.free.restype = None
        libc.free(ctypes.cast(fds, ctypes.c_void_p))


def listen_sockets():
    """Слушающие сокеты: из PANTHEON_LISTEN_FDS (тесты) или от launchd."""
    raw = os.environ.get("PANTHEON_LISTEN_FDS")
    fds = [int(x) for x in raw.split(",") if x.strip()] if raw else launchd_fds()
    if not fds:
        raise OSError("нет слушающих сокетов")
    return [socket.socket(fileno=fd) for fd in fds]


def free_port():
    with socket.socket() as s:
        s.bind((LOOPBACK, 0))
        return s.getsockname()[1]


def connect_loopback(port):
    return socket.create_connection((LOOPBACK, port), timeout=10)


class Proxy:
    """start(port) → Popen сервера, слушающего LOOPBACK:port; idle — секунды тишины до выхода.
    connect и new_port — замены для теста в песочнице, где слушать порт нельзя (соединения через socketpair)."""

    def __init__(self, listeners, start, idle, ready_timeout=READY_TIMEOUT, connect=connect_loopback,
                 new_port=free_port):
        self.listeners = listeners
        self.start = start
        self.connect = connect
        self.new_port = new_port
        self.idle = float(idle)
        self.ready_timeout = ready_timeout
        self.proc = None
        self.port = None
        self.lock = threading.Lock()  # last, conns
        self.start_lock = threading.Lock()  # один запуск сервера на всех ждущих
        self.last = time.monotonic()
        self.conns = set()
        self.stop = threading.Event()

    def touch(self):
        with self.lock:
            self.last = time.monotonic()

    def backend(self):
        """Порт идущего сервера; не шёл — поднять и дождаться приёма соединений. None — не поднялся."""
        with self.start_lock:
            if self.proc is not None and self.proc.poll() is None:
                return self.port
            if self.proc is not None:
                log(f"сервер вышел сам (код {self.proc.returncode}) — поднимаю заново")
            self.port = self.new_port()
            t0 = time.monotonic()
            self.proc = self.start(self.port)
            while time.monotonic() - t0 < self.ready_timeout and not self.stop.is_set():
                if self.proc.poll() is not None:
                    log(f"сервер не поднялся: вышел с кодом {self.proc.returncode}")
                    return None
                try:
                    self.connect(self.port).close()
                    log(f"сервер поднят за {time.monotonic() - t0:.1f} с, pid {self.proc.pid}")
                    self.touch()  # время запуска не съедает простой
                    return self.port
                except OSError:
                    time.sleep(0.05)
            log(f"сервер не принял соединение за {self.ready_timeout} с — гашу")
            self.stop_backend()
            return None

    def stop_backend(self):
        p, self.proc = self.proc, None
        if p is None or p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

    def _pipe(self, src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                self.touch()
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def handle(self, conn):
        up = None
        try:
            port = self.backend()
            if port is None:
                return
            up = self.connect(port)
            up.settimeout(None)
            with self.lock:
                self.conns.add(up)
            t = threading.Thread(target=self._pipe, args=(conn, up), daemon=True)
            t.start()
            self._pipe(up, conn)
            t.join()
        except OSError as e:
            log(f"соединение с сервером: {e}")
        finally:
            with self.lock:
                self.conns.discard(conn)
                self.conns.discard(up)
            for s in (conn, up):
                if s is not None:
                    s.close()
            self.touch()

    def run(self):
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
            signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        sel = selectors.DefaultSelector()
        for s in self.listeners:
            s.setblocking(False)
            sel.register(s, selectors.EVENT_READ)
        tick = max(0.05, min(1.0, self.idle / 4))
        why = "SIGTERM"
        while not self.stop.is_set():
            for key, _ in sel.select(timeout=tick):
                try:
                    conn, _ = key.fileobj.accept()
                except (BlockingIOError, InterruptedError):
                    continue
                conn.setblocking(True)
                with self.lock:
                    self.conns.add(conn)
                self.touch()
                threading.Thread(target=self.handle, args=(conn,), daemon=True).start()
            with self.lock:
                quiet = time.monotonic() - self.last
            if quiet >= self.idle and not self.start_lock.locked():
                why = f"простой {int(quiet)} с"
                break
        # сервер гасим до закрытия соединений: иначе молчащий поток клиента успел бы отправить запрос в полумёртвый
        self.stop_backend()
        with self.lock:
            conns, self.conns = list(self.conns), set()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()
        for s in self.listeners:
            sel.unregister(s)
            s.close()  # закрываем свою копию; сокет launchd остаётся слушать
        log(f"выход: {why}")
        return 0
