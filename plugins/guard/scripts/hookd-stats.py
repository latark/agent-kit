#!/usr/bin/env python3
"""Доля откатов демона хуков на медленный путь и расхождения канарейки за сутки (F9, metis-0811).

  python.sh hookd-stats.py [--hours <ч>] [--json]

Журналы — в ~/.local/state/pantheon/logs:
- hookd-fallback.log — пишут клиент и оболочка hookd.sh: «время<TAB>причина» на каждый откат, «время<TAB>canary-diff…»
  на каждое расхождение канарейки, slow-exec, slow-signal, slow-fork, usage — двойной отказ (код 2, без решения guard);
- hookd-calls.log — пишет демон: «время<TAB>ok<TAB>число» — сколько решений он отдал (раз в минуту и перед выходом).
Вызов с флагом PANTHEON_HOOKD=1 кончается либо решением демона, либо одной строкой отката, поэтому
всего = решений + откатов, доля = откатов / всего. Двойной отказ идёт отдельной строкой: он следует за откатом
(уже посчитан) или стоит сам (usage).

Вывод — 3–5 строк для владельца или плановому проходу (--json — то же словарём). Код 0 — в порядке; 3 — тревога:
за срок есть canary-diff (демон решил не так, как медленный путь), причина последней строкой; 1 — журнал не прочесть;
64 — плохие аргументы. Плановый проход зовёт его из проверенного дерева guard и на коде 3 поднимает тревогу:
  /bin/sh <дерево guard>/hooks/python.sh <дерево guard>/scripts/hookd-stats.py --json
"""
import json
import os
import sys
import time

FALLBACK_LOG = "hookd-fallback.log"
CALLS_LOG = "hookd-calls.log"
DOUBLE = frozenset(("slow-exec", "slow-signal", "slow-fork", "usage"))


def logs_dir(home=None):
    return os.path.join(home or os.environ.get("HOME") or "", ".local", "state", "pantheon", "logs")


def _lines(path, since):
    """Строки журнала со временем не раньше since («ГГГГ-ММ-ДДTЧЧ:ММ:СС», то же, что в начале строки)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if len(ln) > 20 and ln[19] == "\t" and ln[:19] >= since:
                    yield ln.rstrip("\n").split("\t")
    except FileNotFoundError:
        return


def stats(home=None, hours=24.0, now=None):
    """Счёт за последние hours часов: {"since", "calls", "daemon", "fallbacks", "share", "reasons", "double",
    "canary_diff", "canary"}. OSError — журнал есть, но не читается."""
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((now if now is not None else time.time()) - hours * 3600))
    d = logs_dir(home)
    reasons, double, canary = {}, {}, []
    for parts in _lines(os.path.join(d, FALLBACK_LOG), since):
        why = parts[1]
        if why == "canary-diff":
            canary.append("\t".join(parts[:5]))
        elif why in DOUBLE:
            double[why] = double.get(why, 0) + 1
        elif why:
            reasons[why] = reasons.get(why, 0) + 1
    ok = 0
    for parts in _lines(os.path.join(d, CALLS_LOG), since):
        if len(parts) >= 3 and parts[1] == "ok" and parts[2].isdigit():
            ok += int(parts[2])
    fb = sum(reasons.values())
    total = ok + fb
    return {"since": since, "calls": total, "daemon": ok, "fallbacks": fb,
            "share": round(fb / total, 4) if total else None,
            "reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))), "double": double,
            "canary_diff": len(canary), "canary": canary[-3:]}


def text(s, hours):
    span = f"{hours:g} ч"
    if not s["calls"] and not s["double"] and not s["canary_diff"]:
        return [f"демон хуков за {span}: вызовов нет (флаг PANTHEON_HOOKD=1 нигде не включён или журналов нет)"]
    pct = f"{s['share'] * 100:.1f}".replace(".", ",") if s["share"] is not None else "—"
    out = [f"демон хуков за {span}: вызовов {s['calls']}, решил демон {s['daemon']}, "
           f"откатов на медленный путь {s['fallbacks']} ({pct} %)"]
    if s["reasons"]:
        out.append("причины откатов: " + ", ".join(f"{k} {v}" for k, v in s["reasons"].items()))
    if s["double"]:
        out.append("двойной отказ (код 2, ни демона, ни медленного пути): "
                   + ", ".join(f"{k} {v}" for k, v in sorted(s["double"].items())))
    out.append(f"canary-diff: {s['canary_diff']}")
    if s["canary_diff"]:
        out += ["  " + x for x in s["canary"]]
        out.append(f"тревога: canary-diff {s['canary_diff']} за {span} — демон решил не так, как медленный путь "
                   f"(журнал {os.path.join(logs_dir(), FALLBACK_LOG)}); флаг PANTHEON_HOOKD=1 снять до разбора")
    return out


def main(argv):
    hours, as_json = 24.0, False
    it = iter(argv)
    try:
        for a in it:
            if a == "--hours":
                hours = float(next(it))
                if not 0 < hours <= 24 * 366:
                    raise ValueError(f"--hours {hours}")
            elif a == "--json":
                as_json = True
            else:
                raise ValueError(a)
    except (StopIteration, ValueError) as e:
        print(f"hookd-stats: плохие аргументы ({e}); нужно: [--hours <ч>] [--json]", file=sys.stderr)
        return 64
    try:
        s = stats(hours=hours)
    except OSError as e:
        print(f"hookd-stats: журнал не прочесть: {e}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(s, ensure_ascii=False))
    else:
        print("\n".join(text(s, hours)))
    return 3 if s["canary_diff"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
