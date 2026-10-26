"""Слой платформы Пантеона для macOS (решение 0155): всё, что зависит от системы, — здесь.

setup.py ходит к системе только через этот модуль: Homebrew, launchd, sandbox-exec, Связка ключей и текст про
уведомления. Другая платформа получит свой модуль с теми же функциями. Только стандартная библиотека.
"""
import os
import shutil
import subprocess

NOTIFY_HELP = (
    "Чтобы уведомления Пантеона показывались: Системные настройки → Уведомления → terminal-notifier → "
    "«Разрешить уведомления» (стиль «Оповещения» или «Баннеры»). Пока terminal-notifier ни разу ничего не показал, "
    "в списке его нет: запустите `terminal-notifier -message проверка` и вернитесь в настройки."
)


def is_macos():
    import platform
    return platform.system() == "Darwin"


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=kw.pop("timeout", 600), **kw)


def brew_path():
    """Путь к brew: PATH, затем стандартные места Apple Silicon и Intel. Нет — None."""
    p = shutil.which("brew")
    if p:
        return p
    for c in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.access(c, os.X_OK):
            return c
    return None


def brew_install(package):
    """→ (ok, сообщение). Без Homebrew — (False, причина)."""
    brew = brew_path()
    if not brew:
        return False, "Homebrew не найден"
    r = _run([brew, "install", package])
    if r.returncode != 0:
        return False, (r.stderr.strip().splitlines() or ["brew install не вышло"])[-1]
    return True, ""


def launchd_bootstrap(plist, uid=None):
    uid = os.getuid() if uid is None else uid
    return _run(["launchctl", "bootstrap", f"gui/{uid}", plist])


def launchd_bootout(label, uid=None):
    uid = os.getuid() if uid is None else uid
    return _run(["launchctl", "bootout", f"gui/{uid}/{label}"])


def sandbox_exec(profile, argv, **kw):
    """Запуск argv под профилем песочницы (файл профиля). → CompletedProcess."""
    return _run(["sandbox-exec", "-f", profile, *argv], **kw)


def keychain_has(service):
    """Есть ли в Связке ключей запись службы. Значение не читается (нет флагов -w и -g)."""
    r = _run(["security", "find-generic-password", "-s", service])
    return r.returncode == 0


def keychain_add(service, account, secret):
    """Новая запись Связки ключей (без -U: существующую не перезаписывает). → (ok, причина). Секрет уходит только
    в argv `security`; в причину отказа идёт последняя строка stderr, а не argv."""
    try:
        r = _run(["security", "add-generic-password", "-s", service, "-a", account, "-w", secret], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, type(e).__name__
    if r.returncode != 0:
        return False, ((r.stderr or "").strip().splitlines() or [f"security: код {r.returncode}"])[-1]
    return True, ""
