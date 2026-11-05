#!/usr/bin/env python3
"""Служба демона хуков guard плановым проходом (metis-0845): установка, перестановка после выпуска guard, сводка F9.

Запуск: python3 -I plugins/pantheon/tests/test_svc_hookd.py  (код выхода 0 — все прошли).
Всё — во временном HOME: дерево guard в кэше подменённого HOME (installed_plugins.json и verified.json), установщик
scripts/hookd-install.sh и сводка scripts/hookd-stats.py в нём — поддельные (пишут журнал вызовов и делают то же, что
настоящие: plist, pantheon-hookd.hooks, метка .sum). launchd не трогается: PANTHEON_DRYRUN — bootstrap и bootout
идут строкой в dryrun.log, состояние служб — svc-dry.json. Настоящие ~/.claude, ~/Library/LaunchAgents и gui-домен
launchctl тест не трогает.
1. services_sync: [[service]] hookd без command не снимается, а ставится установщиком guard (--no-probe, окружение —
   только HOME и PATH); повтор при совпадении — ничего (ни установщика, ни launchctl).
2. Выпуск guard (новая версия в installed_plugins.json и verified.json) — перестановка на новое дерево
   (pantheon-hookd.hooks), затем снова ничего. Служба не загружена, plist не тот, что даёт --print, — перестановка.
3. pantheon-hookd поставлен впервые или пересобран — тревога «проверьте доступ» с --check; тот же — тревоги нет.
4. Сбой установщика — тревога с последней строкой, повтор из того же дерева через час, а не на каждом проходе.
5. Нет проверенного guard — тревога, служба не трогается; выключена, на паузе, убрана из расписания — снята.
6. hookd-stats раз в сутки, только когда служба стоит: код 0 — тихо, 3 — тревога canary-diff и сбой в политике
   уведомлений (утренний итог), ошибка, не JSON — тревога «сводка не прошла», тик не падает; шаг стоит в тике.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # CLI pantheon — только на Python 3.11+

_ROOT = mkroot("svc-hookd-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.environ.get("TEST_PANTHEON_LIB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIBDIR, "run.py")
T0 = 1_792_000_000
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"\n     {detail}"))


def write(p, text, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(p, mode)


def read(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# Поддельный установщик: --print — plist от HOME и метки $HOME/tmpl (так меняется «шаблон»); --no-probe — журнал
# «папка-hooks ключ окружение», затем pin, метка .sum (из $HOME/svc-sum) и plist, как настоящий. $HOME/install-fail —
# сбой с причиной последней строкой. Свои файлы — вне дерева guard: иначе дерево разошлось бы с verified.json.
INSTALL = r'''#!/bin/sh
h=$(cd "${0%/*}/../hooks" && pwd -P)
case "${1:-}" in
    --print)
        printf '<plist>%s %s</plist>\n' "$HOME" "$(cat "$HOME/tmpl" 2>/dev/null)"
        exit 0 ;;
    --no-probe)
        echo "$h $1 state=${PANTHEON_STATE:-нет} lctl=${PANTHEON_HOOKD_LAUNCHCTL:-нет}" >>"$HOME/install.log"
        if [ -f "$HOME/install-fail" ]; then
            echo "что-то в начале" >&2
            echo "hookd-install: клиент не собран (hookd-build.sh)" >&2
            exit 1
        fi
        mkdir -p "$HOME/.cache/pantheon/hookd/bin" "$HOME/Library/LaunchAgents"
        printf '%s\n' "$h" >"$HOME/.cache/pantheon/hookd/bin/pantheon-hookd.hooks"
        cat "$HOME/svc-sum" >"$HOME/.cache/pantheon/hookd/bin/pantheon-hookd.sum"
        /bin/sh "$0" --print >"$HOME/Library/LaunchAgents/pantheon.svc.hookd.plist"
        echo "служба pantheon.svc.hookd поставлена"
        exit 0 ;;
esac
echo "$h неожиданно: $*" >>"$HOME/install.log"
exit 64
'''

# Поддельная сводка: режим — $HOME/stats-mode (0, 3, 1, junk); каждый вызов — строка в $HOME/stats.log
STATS = r'''import json, os, sys
home = os.environ["HOME"]
with open(os.path.join(home, "stats.log"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
mode = open(os.path.join(home, "stats-mode")).read().strip()
if mode == "junk":
    print("не json")
    sys.exit(0)
if mode == "1":
    print("hookd-stats: журнал не прочесть: нет доступа", file=sys.stderr)
    sys.exit(1)
n = 2 if mode == "3" else 0
print(json.dumps({"calls": 10, "daemon": 9, "fallbacks": 1, "share": 0.1, "canary_diff": n}))
sys.exit(int(mode))
'''


def guard_tree(h, ver):
    d = os.path.join(h, ".claude", "plugins", "cache", "agent-kit", "guard", ver)
    write(os.path.join(d, ".claude-plugin", "plugin.json"), json.dumps({"name": "guard", "version": ver}))
    write(os.path.join(d, "scripts", "hookd-install.sh"), INSTALL, 0o755)
    write(os.path.join(d, "scripts", "hookd-stats.py"), STATS)
    write(os.path.join(d, "hooks", "python.sh"), f'#!/bin/sh\nexec "{sys.executable}" -I "$@"\n', 0o755)
    return os.path.realpath(d)


def env_for(h, t=T0, **kw):
    env = {"PATH": os.environ["PATH"], "HOME": h, "PANTHEON_HOME": os.path.join(h, "pantheon"),
           "PANTHEON_STATE": os.path.join(h, "state"), "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a",
           "PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_HOOKD_LAUNCHCTL": "/nonexistent/launchctl"}
    env.update(kw)
    return env


def py(h, code, t=T0, **kw):
    r = subprocess.run([PY311, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pantheon as P\n" + code,
                        LIBDIR], env=env_for(h, t, **kw), capture_output=True, text=True, timeout=120)
    if r.returncode:
        print(r.stdout[-1500:], r.stderr[-1500:])
    return r


def install_guard(h, tree, ver):
    """Выпуск guard: installed_plugins.json → tree, verified.json — его хеш (как после plugins-update)."""
    write(os.path.join(h, ".claude", "plugins", "installed_plugins.json"), json.dumps(
        {"version": 2, "plugins": {"guard@agent-kit": [{"scope": "user", "installPath": tree, "version": ver}]}}))
    r = py(h, "P.verified_write('guard', sys.argv[2], P._tree_hash(sys.argv[2]), sys.argv[3], 'test')"
           .replace("sys.argv[2]", repr(tree)).replace("sys.argv[3]", repr(ver)))
    assert r.returncode == 0


def home(schedule):
    h = os.path.realpath(tempfile.mkdtemp(prefix="h-"))
    write(os.path.join(h, "pantheon", "schedule.toml"), schedule)
    write(os.path.join(h, "svc-sum"), "aaaa\n")
    os.makedirs(os.path.join(h, "state"))
    return h


def sync(h, t=T0, **kw):
    return py(h, "P.services_sync(P.load_schedule())", t, **kw)


def ilog(h):
    return read(os.path.join(h, "install.log")).splitlines()


def dry(h):
    return read(os.path.join(h, "state", "dryrun.log")).splitlines()


def alerts(h):
    return read(os.path.join(h, "pantheon", "alerts.md"))


def pin(h):
    return read(os.path.join(h, ".cache", "pantheon", "hookd", "bin", "pantheon-hookd.hooks")).strip()


def plist(h):
    return os.path.join(h, "Library", "LaunchAgents", "pantheon.svc.hookd.plist")


def svc_dry(h):
    p = os.path.join(h, "state", "svc-dry.json")
    return json.load(open(p)) if os.path.exists(p) else {}


SCHED = '[[service]]\nname = "hookd"\ndescription = "демон хуков guard"\nhosts = "all"\n'


def test_install_and_upgrade():
    h = home(SCHED)
    g1 = guard_tree(h, "1.0.0")
    install_guard(h, g1, "1.0.0")
    r = sync(h)
    log = ilog(h)
    check("services_sync: hookd из schedule.toml не снят, а поставлен установщиком guard 1.0.0 с --no-probe",
          r.returncode == 0 and log == [f"{g1}/hooks --no-probe state=нет lctl=нет"] and os.path.exists(plist(h)),
          (r.returncode, log, r.stderr[-500:]))
    check("установщику — только HOME и PATH (ни PANTHEON_STATE, ни PANTHEON_HOOKD_LAUNCHCTL тика)",
          log and "state=нет lctl=нет" in log[0], log)
    check("plist — от установщика guard (--print), а не шаблон pantheon service-run",
          read(plist(h)) == f"<plist>{h} </plist>\n" and "service-run" not in read(plist(h)), read(plist(h)))
    check("pantheon-hookd.hooks → папка hooks установленного guard", pin(h) == f"{g1}/hooks", pin(h))
    check("dryrun: строка установки с версией и кодом 0, служба загружена (svc-dry)",
          any(x.split()[1:] == ["svc-hookd-install", "1.0.0", "0"] for x in dry(h)) and "hookd" in svc_dry(h), dry(h))
    a = alerts(h)
    check("первая установка — тревога «проверьте доступ» с командой --check",
          "pantheon-hookd поставлен впервые" in a and "hookd-install.sh --check" in a, a[-600:])

    n_dry, n_alerts = len(dry(h)), alerts(h)
    r = sync(h, T0 + 60)
    check("повтор при совпадении — ни установщика, ни launchctl, ни тревоги",
          r.returncode == 0 and len(ilog(h)) == 1 and len(dry(h)) == n_dry and alerts(h) == n_alerts,
          (ilog(h), dry(h)[n_dry:], alerts(h)[len(n_alerts):]))

    # выпуск guard 1.0.1: pin называет прежнюю версию — перестановка на новое дерево
    g2 = guard_tree(h, "1.0.1")
    install_guard(h, g2, "1.0.1")
    r = sync(h, T0 + 120)
    check("после выпуска guard — перестановка из 1.0.1, pin → новая версия",
          r.returncode == 0 and ilog(h)[1:] == [f"{g2}/hooks --no-probe state=нет lctl=нет"] and pin(h) == f"{g2}/hooks",
          (ilog(h), pin(h)))
    check("тот же pantheon-hookd (метка .sum прежняя) — тревоги о доступе нет",
          alerts(h).count("не проверен — в терминале") == 1 and alerts(h).count("поставлен впервые") == 1
          and "пересобран" not in alerts(h), alerts(h)[-400:])
    r = sync(h, T0 + 180)
    check("после перестановки — снова ничего", len(ilog(h)) == 2, ilog(h))

    # служба выгружена (bootout вручную) — поставить снова
    d = svc_dry(h)
    d.pop("hookd", None)
    write(os.path.join(h, "state", "svc-dry.json"), json.dumps(d))
    sync(h, T0 + 240)
    check("служба не загружена — переустановка", len(ilog(h)) == 3 and "hookd" in svc_dry(h), (ilog(h), svc_dry(h)))

    # шаблон plist в новом guard другой (--print не тот) — переустановка
    write(os.path.join(h, "tmpl"), "v2")
    sync(h, T0 + 300)
    check("plist не тот, что даёт --print — переустановка, plist новый",
          len(ilog(h)) == 4 and read(plist(h)) == f"<plist>{h} v2</plist>\n", (ilog(h), read(plist(h))))

    # pin испорчен (другое дерево) — переустановка
    write(os.path.join(h, ".cache", "pantheon", "hookd", "bin", "pantheon-hookd.hooks"), "/elsewhere/hooks\n")
    sync(h, T0 + 360)
    check("pin называет другое дерево — переустановка", len(ilog(h)) == 5 and pin(h) == f"{g2}/hooks", ilog(h))

    # pantheon-hookd пересобран (исходник в выпуске другой) — тревога «проверьте доступ», одна на метку
    write(os.path.join(h, "svc-sum"), "bbbb\n")
    g3 = guard_tree(h, "1.0.2")
    install_guard(h, g3, "1.0.2")
    sync(h, T0 + 420)
    a = alerts(h)
    check("pantheon-hookd пересобран — тревога «пересобран» с командой --check из нового дерева",
          len(ilog(h)) == 6 and "pantheon-hookd пересобран" in a
          and "~/.claude/plugins/cache/agent-kit/guard/1.0.2/scripts/hookd-install.sh --check" in a
          and a.count("не проверен — в терминале") == 2,
          a[-500:])

    # сбой установщика: тревога с последней строкой, повтор — через час
    open(os.path.join(h, "install-fail"), "w").close()
    g4 = guard_tree(h, "1.0.3")
    install_guard(h, g4, "1.0.3")
    r = sync(h, T0 + 480)
    a = alerts(h)
    check("сбой установщика — код прохода 0, тревога: версия, код, последняя строка вывода",
          r.returncode == 0 and len(ilog(h)) == 7 and "установка из guard 1.0.3 не прошла (код 1)" in a
          and "клиент не собран (hookd-build.sh)" in a and "что-то в начале" not in a, a[-500:])
    check("сбой: pin остаётся на прежнем дереве", pin(h) == f"{g3}/hooks", pin(h))
    sync(h, T0 + 540)
    check("сбой: следующий проход в пределах часа не зовёт установщик снова", len(ilog(h)) == 7, ilog(h))
    os.remove(os.path.join(h, "install-fail"))
    sync(h, T0 + 480 + 3601)
    check("через час — повтор, служба переставлена на 1.0.3", len(ilog(h)) == 8 and pin(h) == f"{g4}/hooks", ilog(h))
    return h


def test_remove_and_guards():
    # нет проверенного guard: служба не трогается, тревога
    h = home(SCHED)
    g = guard_tree(h, "1.0.0")
    write(os.path.join(h, ".claude", "plugins", "installed_plugins.json"), json.dumps(
        {"version": 2, "plugins": {"guard@agent-kit": [{"scope": "user", "installPath": g, "version": "1.0.0"}]}}))
    write(plist(h), "<plist>руками</plist>\n")
    r = sync(h)
    check("нет проверенного guard — установщик не зовётся, plist не тронут, тревога «нет проверенного дерева guard»",
          r.returncode == 0 and not ilog(h) and read(plist(h)) == "<plist>руками</plist>\n"
          and "служба hookd: нет проверенного дерева guard" in alerts(h), (ilog(h), alerts(h)[-400:]))

    # проверенный guard без установщика (старый выпуск)
    os.remove(os.path.join(g, "scripts", "hookd-install.sh"))
    install_guard(h, g, "1.0.0")
    r = sync(h)
    check("в guard нет hookd-install.sh — тревога, plist не тронут",
          r.returncode == 0 and "нет scripts/hookd-install.sh" in alerts(h) and os.path.exists(plist(h)), alerts(h)[-300:])

    # выключена, пауза, нет в расписании — снята (bootout и plist удалён)
    for label, sched, pause in (("enabled = false", SCHED + "enabled = false\n", False),
                                ("пауза (pantheon jobs pause hookd)", SCHED, True),
                                ("нет в schedule.toml", "", False)):
        h = home(sched)
        g = guard_tree(h, "1.0.0")
        install_guard(h, g, "1.0.0")
        write(plist(h), "<plist>x</plist>\n")
        write(os.path.join(h, "state", "svc-dry.json"), json.dumps({"hookd": 0}))
        if pause:
            write(os.path.join(h, "state", "jobs", "hookd.json"), json.dumps({"paused": True}))
        r = sync(h)
        check(f"{label} — служба снята: bootout и plist удалён, установщик не зовётся",
              r.returncode == 0 and not os.path.exists(plist(h)) and not ilog(h)
              and any(x.split()[1:] == ["svc-bootout", "hookd"] for x in dry(h)), (dry(h), ilog(h)))

    # не этот Mac (hosts = "primary")
    h = home('primary_host = "mac-b"\n' + SCHED.replace('hosts = "all"', 'hosts = "primary"'))
    g = guard_tree(h, "1.0.0")
    install_guard(h, g, "1.0.0")
    sync(h)
    check("hosts = primary на другом Mac — не ставится", not ilog(h) and not os.path.exists(plist(h)), ilog(h))

    # pantheon jobs: строка службы hookd без «127.0.0.1:None»; service-run hookd — отказ, код 2
    h = home(SCHED)
    g = guard_tree(h, "1.0.0")
    install_guard(h, g, "1.0.0")
    sync(h)
    r = subprocess.run([PY311, "-I", RUN_PY, "jobs"], env=env_for(h), capture_output=True, text=True, timeout=60)
    row = [x for x in r.stdout.splitlines() if x.startswith("hookd")]
    check("pantheon jobs: hookd по требованию ждёт запроса на сокете ~/.cache/pantheon/hookd/hookd.sock",
          r.returncode == 0 and row and "ждёт запроса на ~/.cache/pantheon/hookd/hookd.sock" in row[0], (r.stdout[-600:], r.stderr[-300:]))
    r = subprocess.run([PY311, "-I", RUN_PY, "service-run", "hookd"], env=env_for(h), capture_output=True, text=True,
                       timeout=60)
    check("service-run hookd — код 2 и причина: запускает launchd через pantheon-hookd",
          r.returncode == 2 and "pantheon-hookd" in r.stderr, (r.returncode, r.stderr[-300:]))
    # pantheon status: загружена без процесса — ожидание запроса, не «НЕ ИДЁТ»; не загружена — «НЕ ЗАГРУЖЕНА»
    r = subprocess.run([PY311, "-I", RUN_PY, "status"], env=env_for(h), capture_output=True, text=True, timeout=120)
    check("pantheon status: hookd загружена, процесса нет — ни «НЕ ИДЁТ», ни «НЕ ЗАГРУЖЕНА» (код status — от прочих проверок)",
          svc_dry(h).get("hookd") == 0 and "Claude Code" in r.stdout
          and "служба hookd: НЕ" not in r.stdout, (r.returncode, r.stdout[-600:], r.stderr[-300:]))
    write(os.path.join(h, "state", "svc-dry.json"), json.dumps({}))
    r = subprocess.run([PY311, "-I", RUN_PY, "status"], env=env_for(h), capture_output=True, text=True, timeout=120)
    check("pantheon status: hookd не загружена — «НЕ ЗАГРУЖЕНА (по требованию)» с журналом svc-hookd.log",
          "служба hookd: НЕ ЗАГРУЖЕНА (по требованию)" in r.stdout and "svc-hookd.log" in r.stdout,
          (r.returncode, r.stdout[-600:], r.stderr[-300:]))


def stats(h, t):
    return py(h, f"P.hookd_stats_tick({t})")


def slog(h):
    return read(os.path.join(h, "stats.log")).splitlines()


def test_stats():
    h = home(SCHED)
    g = guard_tree(h, "1.0.0")
    install_guard(h, g, "1.0.0")
    write(os.path.join(h, "stats-mode"), "0")
    stats(h, T0)
    check("службы нет (plist нет) — сводка не зовётся", not slog(h), slog(h))
    sync(h)
    stats(h, T0)
    st = json.load(open(os.path.join(h, "state", "hookd-stats.json")))
    check("служба стоит — hookd-stats --json из проверенного дерева, код 0, тревог нет, итог в hookd-stats.json",
          slog(h) == ["--json"] and st.get("code") == 0 and st.get("stats", {}).get("calls") == 10
          and "canary" not in alerts(h) and "сводка" not in alerts(h), (slog(h), st, alerts(h)[-300:]))
    stats(h, T0 + 3600)
    check("второй раз за сутки — не зовётся", len(slog(h)) == 1, slog(h))

    write(os.path.join(h, "stats-mode"), "3")
    stats(h, T0 + 86400)
    a = alerts(h)
    nf = json.load(open(os.path.join(h, "state", "notify.json"))) if os.path.exists(os.path.join(h, "state", "notify.json")) else {}
    check("код 3 — тревога canary-diff с числом за сутки и журналом разбора",
          len(slog(h)) == 2 and "демон хуков: canary-diff 2 за сутки" in a and "hookd-fallback.log" in a, a[-500:])
    check("код 3 — сбой в политике уведомлений (в тихие часы — утренний итог)",
          "hookd-canary" in json.dumps(nf, ensure_ascii=False), json.dumps(nf, ensure_ascii=False)[:500])
    stats(h, T0 + 86400 + 60)
    check("код 3 — не чаще раза в сутки", len(slog(h)) == 2 and alerts(h).count("canary-diff 2") == 1, slog(h))

    for mode, want, t in (("1", "сводка hookd-stats не прошла (код 1): hookd-stats: журнал не прочесть: нет доступа",
                           T0 + 2 * 86400),
                          ("junk", "сводка hookd-stats не прошла (код 0, вывод не JSON)", T0 + 3 * 86400)):
        write(os.path.join(h, "stats-mode"), mode)
        r = stats(h, t)
        check(f"сводка: {mode} — вызов не падает, тревога «сводка не прошла»",
              r.returncode == 0 and want in alerts(h), (r.returncode, alerts(h)[-400:]))
    # нет python.sh в дереве — тоже тревога, не исключение
    os.remove(os.path.join(g, "scripts", "hookd-stats.py"))
    install_guard(h, g, "1.0.0")
    r = stats(h, T0 + 4 * 86400)
    check("нет hookd-stats.py в дереве guard — тревога, без исключения",
          r.returncode == 0 and "нет hookd-stats.py в проверенном дереве guard" in alerts(h), alerts(h)[-300:])

    # шаг стоит в тике: проход с hookd в расписании зовёт сводку
    h = home(SCHED)
    g = guard_tree(h, "1.0.0")
    install_guard(h, g, "1.0.0")
    write(os.path.join(h, "stats-mode"), "3")
    r = subprocess.run([PY311, "-I", RUN_PY, "tick"], env=env_for(h, PANTHEON_FAKE_WAKE=str(T0 - 7200),
                                                                  PANTHEON_FAKE_AC="1", PANTHEON_FAKE_IDLE="1200"),
                       capture_output=True, text=True, timeout=120)
    check("тик: ставит службу и в том же проходе зовёт сводку; код 3 — тревога canary-diff",
          r.returncode == 0 and len(ilog(h)) == 1 and slog(h) == ["--json"] and "canary-diff 2" in alerts(h),
          (r.returncode, ilog(h), slog(h), r.stderr[-500:], alerts(h)[-400:]))


def main():
    test_install_and_upgrade()
    test_remove_and_guards()
    test_stats()
    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
