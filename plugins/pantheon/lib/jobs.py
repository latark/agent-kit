"""Пантеон: запуск задач и служб плановым проходом (pantheon run-job, service-run) и пульт задач (pantheon jobs).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import contextlib
import os
import signal
import subprocess
import sys
import time

__all__ = [
    "service_run", "run_job", "next_run", "jobs_show",
]


def service_run(name):
    """Точка входа службы для launchd: перечитать расписание, проверить и заменить себя командой."""
    try:
        sched = P.load_schedule()
    except (OSError, ValueError) as e:
        print(f"schedule.toml не читается: {e}", file=sys.stderr)
        time.sleep(60)
        return 1
    svc = next((s for s in sched.get("service") or [] if s["name"] == name), None)
    if name == P.HOOKD_SVC:
        # демон хуков guard идёт своим plist (pantheon-hookd), его ставит установщик guard (metis-0845), не service-run
        print(f"служба {name}: её запускает launchd через pantheon-hookd, а не service-run", file=sys.stderr)
        return 2
    ok, why = P.service_wanted(svc, sched) if svc else (False, "нет в schedule.toml")
    if not ok:
        print(f"{P.stamp()} служба {name} не идёт: {why}", file=sys.stderr)
        time.sleep(60)  # KeepAlive перезапустит; тик снимет задачу launchd за минуту
        return 0
    argv = P.parse_service_command(svc.get("command"))
    print(f"{P.stamp()} служба {name}: {' '.join(argv)}", file=sys.stderr, flush=True)
    env = P.run_env()
    if P.svc_socket(svc) is not None:
        # служба по требованию: сокет ждёт у launchd (запись Listeners в plist), простой — до выхода
        env["PANTHEON_SVC_SOCKET"] = "Listeners"
        env["PANTHEON_SVC_IDLE"] = str(int(P.svc_idle(svc)))
    os.chdir(P.HOME)
    os.execve(argv[0], argv, env)


def run_job(name):
    sched = P.load_schedule()
    job = next((j for j in sched.get("job") or [] if j["name"] == name), None)
    if not job:
        return 2
    argv = P.parse_command(job.get("command"))
    if argv is None:
        return 2
    heavy = job.get("class") == "heavy"
    with P.lock("job-" + name, block=False) as got:
        if not got:
            return 0
        # задача на Claude — только в песочнице своего окна (P0-3): окна нет — не запускать, а не запускать без неё.
        # Запуск считается сбоем: срок задачи сдвигается, тяжёлые задачи за ней не ждут каждый тик
        bad = P.job_window_problem(argv)
        if bad:
            P.alert_once("job-window-" + name, bad, f"задача {name} не идёт: {bad}. Окна задач собирает `pantheon domains "
                       "build`", "pantheon-tick",
                       note=f"Задача {name} не идёт: нет окна песочницы")
            st = P.job_state(name)
            st.update(last_start=P.now(), last_end=P.now(), last_rc=P.ALERTED, fails=int(st.get("fails") or 0) + 1)
            st.pop("waiting", None)
            P.save_job_state(name, st)
            return P.ALERTED
        P.clear_once("job-window-" + name)
        if P.job_cap_hold(name, argv, P.job_state(name), P.now()):  # и прямой run-job: тик проверял до запуска процесса
            return 0
        with (P.lock("heavy-run", block=False) if heavy else contextlib.nullcontext(True)) as hgot:
            if not hgot:
                return 0
            fp0 = P.tick_fingerprint(job)  # до прогона: что изменилось за время работы, поймает следующий тик
            st = P.job_state(name)
            st.update(last_start=P.now())
            P.save_job_state(name, st)
            os.makedirs(P.path("logs"), exist_ok=True)
            log = P.path("logs", name + ".log")
            started = time.time()
            started_at = P.now()
            timeout = float(job.get("timeout", 600))
            # Своя группа процессов: по таймауту гасится вся задача, а не только первый процесс.
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=P.claude_env() if os.path.basename(argv[0]) == "claude" else P.run_env(), cwd=P.HOME,
                                    start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, sig)
                    try:
                        out, _ = proc.communicate(timeout=5)
                        break
                    except subprocess.TimeoutExpired:
                        out = ""
                rc, out = 124, f"таймаут {int(timeout)} с, группа процессов остановлена\n{out or ''}"
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"--- {P.stamp()} rc={rc} {time.time() - started:.1f} с\n{(out or '')[-4000:]}")
            P.trim_log(log)
            st = P.job_state(name)
            st.update(last_end=P.now(), last_rc=rc)
            st.pop("running", None)
            if rc == 0 and fp0:
                st.update(skip_fp=fp0, skip_at=started_at)
            else:
                st.pop("skip_fp", None)
                st.pop("skip_at", None)
            if rc == P.TEMPFAIL:
                st["waiting"] = "нет сети или GitHub недоступен"
            else:
                st.pop("waiting", None)
                st["fails"] = 0 if rc == 0 else int(st.get("fails") or 0) + 1
            P.save_job_state(name, st)
            if heavy:
                P.write_json(P.path("heavy.json"), {"last_end": P.now()})
            if rc not in (0, P.TEMPFAIL, P.ALERTED) and st["fails"] in (1, 5, 20):
                tail = (out or "").strip().splitlines()[-1:] or [""]
                P.alert(f"задача {name} упала (код {rc}, подряд {st['fails']}): {tail[0][:200]} — журнал {log.replace(P.HOME, '~')}",
                      "pantheon-tick")
                if job.get("notify", True):
                    P.notify_soon("job-" + name, f"Задача {name} упала (код {rc})")
            return rc


def next_run(job, st, t):
    if job.get("enabled") is False or st.get("disabled") or st.get("paused"):
        return "—"
    held = P.lock_held("job-" + job["name"])  # metis-0266: показ замок не пишет (в песочнице окна STATE/locks только читается)
    if held:
        return "идёт"
    if held is None:
        return "не знаю (блокировка не читается)"
    if st.get("waiting"):
        return "ждёт условий"
    if st.get("last_start") is None:
        return "на ближайшем плановом проходе"
    if job.get("every", "tick") == "tick":
        return "каждый плановый проход"
    left = st["last_start"] + P.every_sec(job) - t
    if left <= 60:
        return "на ближайшем плановом проходе"
    return f"через {int(left // 60)} мин" if left < 5400 else P.stamp(st["last_start"] + P.every_sec(job))


def jobs_show():
    lt = None
    with contextlib.suppress(OSError, ValueError):
        lt = float(open(P.path("last-tick")).read())
    tick_line = f"плановый проход: {P.ago(lt)}" if lt else "плановый проход: ещё не шёл (pantheon install)"
    if not os.path.exists(P.PLIST) and P.old_plists(P.OLD_TICK_GLOB):
        tick_line += " — старая метка launchd: выполните `pantheon install`"
    if lt and P.now() - lt > 180:
        tick_line += " — ПЛАНИРОВЩИК СТОИТ"
    if os.path.exists(P.path("paused")):
        tick_line += " · весь планировщик на паузе (pantheon jobs resume --all)"
    sched = P.load_schedule()
    print(f"{tick_line} · этот Mac: {P.host()} · главный: {sched.get('primary_host') or '—'}\n")
    rows = [("задача", "класс", "где", "как часто", "последний запуск", "дальше", "состояние")]
    t = P.now()
    for job in sched.get("job") or []:
        st = P.job_state(job["name"])
        every = "каждый плановый проход" if job.get("every", "tick") == "tick" else f"{job['every']} мин"
        held = False
        if job.get("enabled") is False or st.get("disabled"):
            state = "выключена"
        elif st.get("paused"):
            state = f"пауза{': ' + st['paused_reason'] if st.get('paused_reason') else ''}"
        elif (held := P.lock_held("job-" + job["name"])):
            state = "идёт"
        elif P.parse_command(job.get("command")) is None:
            state = "команда не разрешена — пропускается"
        elif P.job_window_problem(P.parse_command(job.get("command"))):
            state = f"не идёт: {P.job_window_problem(P.parse_command(job.get('command')))} (pantheon domains build)"
        elif st.get("waiting"):
            state = f"ждёт: {st['waiting']}"
        elif st.get("last_rc") not in (None, 0):
            state = f"упала, код {st['last_rc']}"
        else:
            state = "ок"
        if held is None:  # metis-0266: замок не прочитан — «идёт» или нет, не знаем; остальное состояние выше верно
            state += " · идёт ли сейчас — не знаю (блокировка не читается)"
        if st.get("lease_until"):
            state += f" · аренда до {P.stamp(st['lease_until'])[:10]}"
        last = P.ago(st.get("last_start")) if st.get("last_start") else "—"
        rows.append((job["name"], job.get("class", "light"), job.get("hosts", "all"), every, last,
                     next_run(job, st, t), state))
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r[:6], widths)) + "  " + r[6])
    if sched.get("service"):
        print()
        rows = [("служба", "где", "состояние", "что")]
        for svc in sched["service"]:
            ok, why = P.service_wanted(svc, sched)
            pid = P.svc_running(svc["name"])
            if ok and svc["name"] == P.HOOKD_SVC:  # сокет и простой — у демона guard, не в schedule.toml
                where = os.path.join(P.HOOKD_DIR, "hookd.sock").replace(P.HOME, "~")
                state = (f"идёт по запросу, pid {pid}" if pid else f"по требованию: ждёт запроса на {where}"
                         if pid == 0 else "не загружена — плановый проход поставит установщиком guard")
            elif ok and P.svc_on_demand(svc):
                where = f"127.0.0.1:{P.svc_socket(svc)}"
                state = (f"идёт по запросу, pid {pid}; выйдет после простоя {int(P.svc_idle(svc) // 60)} мин" if pid
                         else f"по требованию: ждёт запроса на {where}" if pid == 0
                         else "не загружена — плановый проход поднимет")
            else:
                state = (f"идёт, pid {pid}" if pid else "не идёт — плановый проход поднимет") if ok else why
            if not ok and pid:
                state += f" (ещё идёт, pid {pid}: плановый проход снимет)"
            rows.append((svc["name"], svc.get("hosts", "all"), state, str(svc.get("description", ""))[:70]))
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        for r in rows:
            print("  ".join(c.ljust(w) for c, w in zip(r[:3], widths)) + "  " + r[3])
