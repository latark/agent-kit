"""Срок gh внутри шлюза `gh pr merge` (metis-1146) — часть ядра защит guard, как merge_gate.py (весь плагин guard —
ядро, CORE_DIR). Вынесено из merge_gate.py (metis-1326): файл длиннее 1500 строк расти не должен.

Каждый gh шлюза ждёт не дольше остатка DEADLINE хука минус GH_MARGIN и не дольше заданного срока (GH_TIMEOUT по
умолчанию); остаток меньше GH_MIN — gh не запускается. Решение шлюза, обёрнутое в _gh_in_time, при хоть одном
неуложившемся gh — отказ «GitHub не ответил вовремя»: без ответа GitHub шлюз закрыт. Вне _gh_in_time (запись
вердиктов, проверка push) и без таймера хука — срок как задан.

Модуль-лист: импортирует только стандартную библиотеку; merge_gate.py берёт отсюда имена через `from gh_deadline
import …`. Состояние — один список _GH_LATE на время _gh_in_time. Тест, подменяющий subprocess у gh, подменяет его
здесь (gh_deadline.subprocess), а не у merge_gate.
"""
import os
import signal
import subprocess

GH_TIMEOUT = 6
GH_MARGIN = 1.5  # metis-1146: запас до срока хука на отказ шлюза после gh
GH_MIN = 0.5  # metis-1146: срок короче — gh не запускаем, вызов не уложился
_GH_LATE = None  # metis-1146: список вызовов gh, не уложившихся в срок хука, — только внутри _gh_in_time


def _hook_left():
    """Сколько секунд до срока хука (таймер ITIMER_REAL guard_rules.set_deadline); 0 — таймера нет."""
    try:
        return signal.getitimer(signal.ITIMER_REAL)[0]
    except (AttributeError, OSError, ValueError):
        return 0


def _gh_budget(timeout):
    """Срок вызова gh внутри шлюза (metis-1146): не дольше остатка DEADLINE хука минус GH_MARGIN; None — не
    уложится. Вне _gh_in_time (запись, push) и без таймера — timeout как есть."""
    left = _hook_left()
    if _GH_LATE is None or not left:
        return timeout
    t = min(timeout, left - GH_MARGIN)
    return t if t >= GH_MIN else None


def _gh_proc(args, timeout=GH_TIMEOUT):
    """subprocess.run gh без GH_REPO/GH_HOST со сроком из _gh_budget; None — не уложился в срок или сбой запуска.
    Не уложившийся вызов шлюза пишется в _GH_LATE: _gh_in_time тогда откажет (metis-1146)."""
    timeout = _gh_budget(timeout)
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    try:
        if timeout is None:
            raise subprocess.TimeoutExpired(["gh"] + args, 0)
        return subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        if _GH_LATE is not None:
            _GH_LATE.append(" ".join(args[:2]))
        return None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _gh_in_time(fn, *a, **kw):
    """fn (решение шлюза) со сроком gh из остатка DEADLINE хука (metis-1146). Хоть один вызов gh не уложился —
    отказ «GitHub не ответил вовремя», даже если fn пропустил бы: без ответа GitHub шлюз закрыт. Отказ самого fn
    (красный CI и т. п.) идёт следом своей причиной, а не как «что ещё не сверено» (metis-1326)."""
    global _GH_LATE
    _GH_LATE = []
    try:
        why = fn(*a, **kw)
        late = list(_GH_LATE)
    finally:
        _GH_LATE = None
    if not late:
        return why
    msg = (f"GitHub не ответил вовремя (gh {', gh '.join(late)}): шлюз не уложился в срок хука guard и без ответа "
           f"GitHub не пускает — повтори слияние через минуту.")
    return f"{msg} Отказ шлюза и по сверенному: {why}" if why else msg
