#!/usr/bin/env python3
"""Слияние по Touch ID, часть 2: таймауты и запасное уведомление, окно, отмена и замена заявки (общая часть — _merge_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403


def test_timeout_retry():
    b = Box()
    b.request()
    b.set("touchid-rc", 3)
    b.run()
    check("окно без ответа → слияния нет, заявка ждёт с повтором", not b.merges() and b.req()
          and b.req().get("wait_until") == T0 + 600, b.req())
    b.set("touchid-rc", 0)
    b.run(t=T0 + 60)
    check("повтор не раньше 10 минут", len(b.windows()) == 1, b.windows())
    b.run(t=T0 + 601)
    check("через 10 минут — окно снова, палец сливает", len(b.windows()) == 2 and len(b.merges()) == 1)


def test_system_cancel_is_no_answer():
    """Окно закрыла система (экран заблокирован, сон: LAError.systemCancel −4, appCancel −9) — помощник выходит
    с кодом 3, как «ответа нет», а не 1 «вы отказали»: 21.11 заявку #531 так сняли за 0 с. Сам LocalAuthentication
    в тесте не вызвать — проверка по исходнику помощника; путь кода 3 у прохода — test_timeout_retry."""
    src = open(os.path.join(LIBDIR, "touchid.swift"), encoding="utf-8").read()
    body = src[src.index("ctx.evaluatePolicy("):]
    m = re.search(r"case\s+LAError\.systemCancel\.rawValue\s*,\s*LAError\.appCancel\.rawValue\s*:\s*code\s*=\s*(\d+)",
                  body)
    check("systemCancel и appCancel → код 3 (ответа нет, повтор позже)", m is not None and m.group(1) == "3",
          m and m.group(0))
    check("прочие отказы — по-прежнему код 1", re.search(r"default\s*:\s*code\s*=\s*1", body) is not None)


def test_fallback_notification():
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    b.run()
    note = open(b.notify_log).read() if os.path.exists(b.notify_log) else ""
    check("окно не показать → уведомление со щелчком `pantheon merge run --click`, слияния нет",
          "execute:" in note and note.rstrip().endswith("merge run --click|merge") and not b.merges()
          and b.req() and b.req().get("notified"), note)
    b.run(t=T0 + 30)
    check("без щелчка следующий проход окна не показывает и уведомление не повторяет",
          len(b.windows()) == 1 and open(b.notify_log).read() == note, b.windows())
    b.set("touchid-rc", 0)
    b.run(t=T0 + 60, click=True, extra={"PANTHEON_FAKE_IDLE": "900"})
    check("щелчок → окно Touch ID и слияние этого SHA",
          len(b.windows()) == 2 and b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA,
                                                     "--merge"]] and b.req() is None, b.outs[-1])
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    b.run(click=True)
    check("окно не показать и при щелчке → заявка снята с тревогой", b.req() is None and not b.merges()
          and "не показано" in b.alerts(), b.alerts())


def test_merge_fails():
    b = Box()
    b.request()
    b.set("gh-merge-rc", 1)
    b.run()
    check("gh pr merge упал → тревога, заявка снята (одно применение), согласие записано",
          len(b.merges()) == 1 and b.req() is None and "не прошло" in b.alerts() and len(b.approve_lines()) == 1,
          b.alerts())


def test_conflict_before_window():
    """metis-0819: PR с конфликтом с main (CONFLICTING или DIRTY) — окна нет, заявка снята с причиной, причина в
    status; GitHub ещё считает (UNKNOWN, поля нет) — окна нет, заявка ждёт, а посчитал — окно и слияние."""
    for name, kw in (("mergeable CONFLICTING", {"mergeable": "CONFLICTING", "merge_state": "DIRTY"}),
                     ("только mergeStateStatus DIRTY", {"merge_state": "DIRTY"})):
        b = Box()
        b.request()
        b.view(SHA, **kw)
        b.run()
        check(f"{name} → окна нет, слияния нет, заявка снята с тревогой «конфликт с main»",
              not b.windows() and not b.merges() and b.req() is None and "конфликт с main" in b.alerts(), b.alerts())
        r = b.cli(["merge", "status"])
        check(f"{name} → status: заявок нет, ниже — снятая с причиной «конфликт с main»",
              "заявок нет" in r.stdout and f"{REPO}#{PR}\t{SHA[:12]}\tgate: конфликт с main" in r.stdout, r.stdout)
    for name, kw in (("mergeable UNKNOWN", {"mergeable": "UNKNOWN", "merge_state": "UNKNOWN"}),
                     ("mergeStateStatus UNKNOWN", {"merge_state": "UNKNOWN"}),
                     ("полей mergeable нет", {"mergeable": None, "merge_state": None})):
        b = Box()
        b.request()
        b.view(SHA, **kw)
        b.run()
        check(f"{name} → окна нет, заявка ждёт без тревоги",
              not b.windows() and b.req() is not None and not b.alerts()
              and "ждёт: GitHub ещё не посчитал, сливается ли PR с main" in b.outs[-1], (b.outs[-1], b.alerts()))
        b.view(SHA)
        b.run(t=T0 + 60)
        check(f"{name}, затем MERGEABLE → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, mergeable="CONFLICTING", checks=ci("PENDING", "SUCCESS"))
    b.run()
    check("конфликт, CI ещё идёт → снята сразу (ждать CI незачем)", b.req() is None and not b.windows(), b.outs[-1])


def test_unknown_after_finger():
    """Б1, Д1 argus #381: после пальца base мог сдвинуться (прежний PR пачки слит, другое слияние за время окна), и
    GitHub отдаёт mergeable UNKNOWN — это не «условия изменились»: PR сливается. Конфликт после пальца — снята."""
    b = Box()
    b.request()
    script(b.touchid, window_script("open(os.path.join(rec, 'unknown-once'), 'w').write('7')", 0))
    b.run()
    check("одна заявка: UNKNOWN после пальца → слита, без тревоги",
          b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA, "--merge"]]
          and b.req() is None and not b.alerts() and "gate-after" not in b.log(), (b.outs[-1], b.alerts()))
    body = ("v = json.load(open(os.path.join(rec, 'gh-view.json'))); v['mergeable'] = 'CONFLICTING'\n"
            "json.dump(v, open(os.path.join(rec, 'gh-view.json'), 'w'))")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("одна заявка: CONFLICTING после пальца → слияния и согласия нет, снята с тревогой «конфликт с main»",
          not b.merges() and not b.approve_lines() and b.req() is None and "gate-after" in b.log()
          and "после пальца условия изменились — конфликт с main" in b.alerts(), (b.outs[-1], b.alerts()))
    b = batch_box()
    request_batch(b)
    b.set("base-moves", "7 8")
    b.run()
    check("пачка: base сдвинулся после слияния #7 (у #8 UNKNOWN) → слиты оба, без тревоги",
          b.merges() == [merge_argv(7), merge_argv(8)] and b.req(8) is None and not b.alerts(),
          (b.outs[-1], b.alerts()))
    b = Box()
    b.request()
    b.view(SHA, mergeable="UNKNOWN")
    b.run()
    r = b.cli(["merge", "status"])
    check("Д2 argus #381: status показывает, почему заявка ждёт",
          f"{REPO}#{PR}\t{SHA[:12]}" in r.stdout and "ждёт: GitHub ещё не посчитал, сливается ли PR с main" in r.stdout,
          r.stdout)
    b2 = batch_box()
    request_batch(b2)
    b2.view(SHA2, pr=8, title="PR 8", files=["docs.md"], mergeable="UNKNOWN")
    b2.run()
    rows = {ln.split("\t")[0]: ln for ln in b2.cli(["merge", "status"]).stdout.splitlines()}
    check("Д2, пачка: причина ожидания — у того PR, который ждёт (#8), у #7 её нет",
          "ждёт: GitHub ещё не посчитал" in rows.get(f"{REPO}#8", "") and f"{REPO}#7" in rows
          and "ждёт:" not in rows[f"{REPO}#7"],
          rows)
    b.view(SHA)
    b.set("touchid-rc", 3)
    b.run(t=T0 + 60)
    req = b.req()
    check("ждать больше нечего (окно было, без ответа) → отметка причины снята",
          req is not None and "waiting" not in req and "ждёт: GitHub" not in b.cli(["merge", "status"]).stdout, req)


def test_status_shows_done():
    """metis-0819: status — не только «заявок нет»: снятые за сутки с причиной, провал gh pr merge после пальца,
    слитые; старше суток и мусор в журнале — нет."""
    b = Box()
    b.request()
    b.set("gh-merge-rc", 1)
    b.run()
    r = b.cli(["merge", "status"], t=T0 + 3600)
    check("merge-failed после пальца — в status с причиной",
          "заявок нет" in r.stdout and f"{REPO}#{PR}\t{SHA[:12]}\tmerge-failed: палец есть, gh pr merge упал (1)"
          in r.stdout, r.stdout)
    with open(os.path.join(b.state, "logs", "merge.jsonl"), "a") as fh:
        fh.write("не json\n[1]\n" + json.dumps({"time": "вчера", "event": "gate"}) + "\n")
    with open(os.path.join(b.state, "logs", "merge.jsonl"), "ab") as fh:   # Д1 argus A #381: байты не в UTF-8
        fh.write(b"\xff\xfe broken\n")
    r = b.cli(["merge", "status"], t=T0 + 25 * 3600)
    check("через 25 ч — снятых нет, мусор в журнале не роняет status",
          r.returncode == 0 and r.stdout.strip() == "заявок нет", r.stdout + r.stderr)
    b = Box()
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    b.request()
    r = b.cli(["merge", "status"])
    check("отказ — в status «refused: вы отказали», и стоящая заявка видна",
          f"{REPO}#{PR}\t{SHA[:12]}\trefused: вы отказали" in r.stdout and "заявок нет" not in r.stdout, r.stdout)
    b.set("touchid-rc", 0)
    b.run()
    r = b.cli(["merge", "status"])
    check("слит — в status «merged»", f"{REPO}#{PR}\t{SHA[:12]}\tmerged" in r.stdout, r.stdout)


def test_refused_from_claude_window():
    b = Box()
    b.request()
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        r = b.run(extra={var: ""})
        check(f"merge run при {var} (окно Claude Code) → отказ, окна нет", r.returncode == 2 and not b.windows(),
              r.stdout + r.stderr)
        r = b.run(click=True, extra={var: "cli"})
        check(f"merge run --click при {var} → отказ", r.returncode == 2 and not b.windows())
    check("заявка цела", b.req() is not None)


def test_no_helper():
    b = Box()
    b.request()
    # STATE/bin — ссылка на папку с исправным помощником: его не берут (и swiftc не зовут — папка не та)
    sbin = os.path.join(b.state, "bin")
    os.rename(sbin, os.path.join(b.tmp, "bin-real"))
    os.symlink(os.path.join(b.tmp, "bin-real"), sbin)
    b.run()
    check("помощника окна нет (STATE/bin — ссылка) → окна и слияния нет, заявка ждёт, тревога",
          not b.windows() and not b.merges() and b.req() is not None and "помощник" in b.alerts(), b.alerts())


def test_helper_not_from_env():
    """argus-b 1: помощник окна из переменной окружения (launchctl setenv) не берётся — только STATE/bin."""
    b = Box()
    b.request()
    evil = script(os.path.join(b.tmp, "evil-touchid"), EVIL)
    b.set("touchid-rc", 1)   # настоящий (поддельный в STATE/bin) — «Не сливать»
    b.run(extra={"PANTHEON_TOUCHID": evil})
    check("PANTHEON_TOUCHID в окружении прохода не подменяет помощника: окно из STATE/bin, слияния нет",
          len(b.windows()) == 1 and not b.merges() and not os.path.exists(os.path.join(b.rec, "evil"))
          and not b.approve_lines(), (b.outs[-1], b.windows()))


def test_helper_mark_and_swiftc():
    """Помощник с отметкой не того исходника не берётся — пересборка /usr/bin/swiftc с чистым окружением. swiftc в
    тесте подменён в процессе (subprocess.run), настоящий компилятор и окно не запускаются."""
    b = Box()
    with open(os.path.join(b.state, "bin", "pantheon-touchid.sha256"), "w") as fh:
        fh.write("0" * 64 + "\n")
    script(os.path.join(b.bin, "swiftc"), "import sys; sys.exit(1)\n")   # swiftc из PATH прохода — не берётся
    code = ("import sys, json, types; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); calls = []\n"
            "def fake(argv, **kw):\n"
            "    calls.append([argv[0], sorted((kw.get('env') or {}).keys())])\n"
            "    return types.SimpleNamespace(returncode=1, stdout='', stderr='сборка в тесте')\n"
            "m.subprocess.run = fake\n"
            "print(json.dumps([m.helper(), calls]))" % LIBDIR)
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, {"DEVELOPER_DIR": b.tmp, "SDKROOT": b.tmp}),
                       capture_output=True, text=True, timeout=60)
    try:
        got, calls = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got, calls = "?", None
    want = [["/usr/bin/swiftc", ["HOME", "PATH"]]] if os.access("/usr/bin/swiftc", os.X_OK) else []
    check("отметка sha256 не та → помощник не берётся, пересборка /usr/bin/swiftc без DEVELOPER_DIR/SDKROOT",
          got is None and calls == want, r.stdout + r.stderr)


def test_merged_notice_and_window_fields():
    """metis-0921: слито → одно уведомление «слит repo#N (sha7)»; поля окна помощника — в событии window."""
    b = Box()
    b.request()
    b.set("touchid-out", json.dumps({"biometry": "touchID", "la_code": None, "shown_sec": 3.4, "text": "x"}))
    b.run()
    note = open(b.notify_log).read() if os.path.exists(b.notify_log) else ""
    check("слито → ровно одно уведомление «слит repo#N (sha7)», без щелчка-команды",
          note.count(f"слит {REPO}#{PR} ({SHA[:7]})") == 1 and note.count("\n") == 1 and "execute:" not in note, note)
    w = [r for r in jsonl(b) if r["event"] == "window"]
    check("window: device_biometry (тип датчика, metis-0932), la_code, shown_sec из помощника, чужое поле не попало",
          len(w) == 1 and w[0]["device_biometry"] == "touchID" and "biometry" not in w[0] and w[0]["la_code"] is None
          and w[0]["shown_sec"] == 3.4 and "text" not in w[0], w)
    b = Box()
    b.request()
    b.set("touchid-rc", 1)
    b.set("touchid-out", json.dumps({"biometry": "none", "la_code": -2, "shown_sec": 1}))
    b.run()
    w = [r for r in jsonl(b) if r["event"] == "window"]
    check("отказ: la_code -2 в журнале, уведомления о слиянии нет",
          w and w[0]["la_code"] == -2 and w[0]["device_biometry"] == "none" and not os.path.exists(b.notify_log),
          (w, b.outs[-1]))
    for bad in ("-2", True, 1.5):   # Д3 argus #364 (M7): la_code только int или null — строка, bool, float не идут
        b = Box()
        b.request()
        b.set("touchid-rc", 1)
        b.set("touchid-out", json.dumps({"la_code": bad, "shown_sec": 1}))
        b.run()
        w = [r for r in jsonl(b) if r["event"] == "window"]
        check(f"la_code {bad!r} (не int) → в журнал не идёт, shown_sec идёт",
              w and "la_code" not in w[0] and w[0]["shown_sec"] == 1, w)
    b = Box()
    b.request()
    b.set("gh-merge-rc", 1)
    b.run()
    check("gh pr merge упал → уведомления «слит» нет",
          len(b.merges()) == 1 and not os.path.exists(b.notify_log), b.outs[-1])
    b = Box()
    b.request()
    b.set("touchid-out", "не json")
    b.run()
    w = [r for r in jsonl(b) if r["event"] == "window"]
    check("помощник напечатал не JSON → слияние идёт, полей окна нет",
          len(b.merges()) == 1 and w and "device_biometry" not in w[0] and "shown_sec" not in w[0], w)
    # Д3 argus #364 (M6): merge.ask — только код помощника (int), его зовёт handoff; кортеж ask_full — нет
    code = ("import sys; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); "
            "m.ask_full = lambda text: (3, {'la_code': -9}); print(repr(m.ask('x')))" % LIBDIR)
    r = subprocess.run([PY311, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                       env={"HOME": b.home, "PATH": "/usr/bin:/bin", "PANTHEON_STATE": b.state, "TMPDIR": _ROOT})
    check("merge.ask → код помощника 3, а не кортеж", r.stdout.strip() == "3", r.stdout + r.stderr)


def test_cancel_during_window():
    """argus-a 1, argus-b 2: заявку сняли, пока окно открыто, — ни согласия, ни слияния, ни записи обратно."""
    for rc in (0, 3, 2):
        b = Box()
        b.request()
        script(b.touchid, window_script(CANCEL_BODY, rc))
        b.run()
        check(f"отмена во время окна, код {rc}: слияния и строки согласия нет, заявка не ожила, журнал gone",
              not b.merges() and not b.approve_lines() and b.req() is None and b.log()[-1] == "gone"
              and not os.path.exists(b.notify_log), (b.outs[-1], b.log()))
        script(b.touchid, FAKE_TOUCHID)
        b.run(t=T0 + 601)
        check(f"отмена во время окна, код {rc}: через 10 минут окна нет", len(b.windows()) == 1, b.windows())


def test_replaced_during_window():
    """Во время окна роль поставила заявку заново (новое время): проход старую не сливает и новую не удаляет."""
    body = ("p = os.path.join(state, 'merge-queue', 'latark__agent-kit__7.json')\nd = json.load(open(p))\n"
            "d['created'] += 5\njson.dump(d, open(p, 'w'))")
    for rc in (0, 1, 3):
        b = Box()
        b.request()
        script(b.touchid, window_script(body, rc))
        b.run()
        req = b.req()
        check(f"заявку заменили во время окна, код {rc}: слияния нет, новая заявка цела и без отметок",
              not b.merges() and not b.approve_lines() and req is not None and req["created"] == T0 + 5
              and "wait_until" not in req, (b.outs[-1], req))


def test_reject_during_window():
    """argus-a 1, argus-b 2: новый «вернуть» argus, пока окно открыто, — после пальца не сливать."""
    rej = {"v": 1, "kind": "reject", "repo": [REPO], "pr": PR, "sha": SHA,
           "by": {"agent_type": "argus", "agent_id": "a9", "session_id": "s9"},
           "checklist": {"opened": "x", "ran": "y", "unchecked": "z"}}
    body = "open(os.path.join(state, 'merge-gate', 'records.jsonl'), 'a').write(%r)" % (json.dumps(rej) + "\n")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("«вернуть» во время окна: палец есть, но слияния и строки согласия нет, заявка снята с тревогой",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None
          and "после пальца" in b.alerts() and "вернуть" in b.alerts(), (b.outs[-1], b.alerts()))
    body = ("v = json.load(open(os.path.join(rec, 'gh-view.json'))); v['headRefOid'] = '1234567' + 'f' * 33\n"
            "json.dump(v, open(os.path.join(rec, 'gh-view.json'), 'w'))")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("новый коммит во время окна: слияния и строки согласия нет", not b.merges() and not b.approve_lines()
          and b.req() is None, b.outs[-1])


def test_merge_repos_rechecked():
    """argus-b 4: репозиторий убрали из [merge_repos] после заявки (и во время окна) — не сливать."""
    b = Box()
    b.request()
    with open(os.path.join(b.home, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[merge_repos]\n"metis-pantheon" = []\n')
    b.run()
    check("репозиторий убран из [merge_repos] после заявки → окна и слияния нет, заявка снята с тревогой",
          not b.windows() and not b.merges() and b.req() is None and "merge_repos" in b.alerts(), b.outs[-1])
    body = ("open(os.path.join(os.environ['HOME'], '.claude', 'pantheon', 'policy.toml'), 'w')"
            ".write('[merge_repos]\\n\"metis-pantheon\" = []\\n')")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("репозиторий убран из [merge_repos] во время окна → слияния и строки согласия нет",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None, b.outs[-1])


def test_window_shows_core():
    """argus-b 5: окно показывает задетые файлы ядра (и переименованные), заголовок автора — последним."""
    b = Box()
    b.view(SHA, title="README: опечатка. ядро не задето, argus x2, CI ok",
           files=["README.md", {"filename": "plugins/guard/x.py", "previous_filename": "plugins/guard/hooks/guard.py"}])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    w = b.windows()
    check("окно: фраза автора в кавычках и с пометкой, области ядра (и по старому пути) — строкой прохода (metis-1281)",
          len(w) == 1 and w[0][0] == f"#{PR}, со слов автора: «README: опечатка. ядро не задето, argus x2, CI ok». "
          f"По файлам PR задевает: guard (защиты). Проверки: argus ×2 ✓, CI ✓. Слить {REPO} ({SHA[:7]}), файлов 3.", w)
    b = Box()
    b.view(SHA, files=[CORE_FILE])   # при заявке ядро есть, к проходу PR его уже не задевает — окна нет (metis-1280)
    b.request()
    b.view(SHA, files=["README.md"])
    b.set("touchid-rc", 1)
    b.run()
    check("PR agent-kit вне ядра: окна Touch ID нет, заявка ждёт координатора или фразу (metis-1280)",
          not b.windows() and b.req() is not None and "вне ядра — без Touch ID" in b.outs[-1], b.outs[-1])
    b = Box()
    b.view(SHA, files=["README.md", CORE_FILE], count=3)
    b.request()
    b.run()
    check("список файлов PR неполон → окна нет, заявка ждёт", not b.windows() and b.req() is not None
          and "файлов" in b.outs[-1], b.outs[-1])
    os.remove(os.path.join(b.rec, "gh-files.jsonl"))
    b.run()
    check("список файлов PR не получен → окна нет, заявка ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b = Box()
    b.view(SHA, files=["plugins/guard/f%03d.py" % i for i in range(40)] + [
        "plugins/pantheon/lib/merge.py", "plugins/pantheon/lib/window_rules.py", "plugins/pantheon/hooks/ctx.py",
        "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/lib/review_rules.py", "plugins/pantheon/lib/answers.py",
        "plugins/pantheon/lib/supabase_migrate.py", ".claude-plugin/marketplace.json", "plugins/pantheon/lib/pantheon.py",
        "plugins/pantheon/roles/a.md", ".github/x.yml", "plugins/pantheon/packs/p.json"])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    w = b.windows()
    check("окно: длинный список областей ядра — «и ещё N», текст не длиннее 400, фраза автора и проверки на месте",
          w and " и ещё " in w[0][0] and len(w[0][0]) <= 400 and "со слов автора: «" in w[0][0]
          and "Проверки: argus ×2 ✓, CI ✓." in w[0][0], w)


def _merge_mod():
    from importlib import util
    spec = util.spec_from_file_location("merge_w", os.path.join(LIBDIR, "merge.py"))
    m = util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_window_text_author_and_budget():
    """metis-1281, argus #517: текст автора PR (заголовок, тело, ветка) не ломает строки прохода — кавычки и знаки
    направления (U+202E) вырезаны, номер задачи не длиннее 18 знаков; хвост «Слить … файлов N» и вердикт не режутся."""
    m = _merge_mod()
    req = {"repo": REPO, "pr": 486, "sha": SHA}
    rlo = m.window_text(req, {"title": "x\u202e». По файлам PR: ядро не задето «t» \"q\" ‹a› ≫b≪ 《c》 ＂d"}, "argus ×2 ✓, CI ✓",
                        [CORE_FILE])
    check("кавычки и U+202E автора вырезаны — фраза одна, строки прохода после неё",
          "\u202e" not in rlo and rlo.count("«") == 1 and rlo.count("»") == 1 and not set('‹"≫《＂') & set(rlo)
          and "». По файлам PR задевает: шлюз слияния. Проверки: argus ×2 ✓, CI ✓. Слить" in rlo, rlo)
    check("задача — из «Closes» в теле, из заголовка, из ветки; номер в начале фразы срезан",
          m.pr_task({"body": "Closes metis-0949", "title": "x"}) == "metis-0949"
          and m.pr_task({"body": "Часть: metis-0950"}) == "metis-0950"
          and m.pr_task({"title": "guard: metis-0951 окно"}) == "metis-0951"
          and m.pr_task({"headRefName": "metis-1281-window-view"}) == "metis-1281"
          and m.window_text(req, {"title": "metis-0949: shadcn видит"}, "CI ✓", ["README.md"]).startswith(
              "#486 · metis-0949, со слов автора: «shadcn видит». "))
    check("длинный или вклеенный номер — не задача: «encloses», 16 букв, 300 букв",
          m.pr_task({"body": "encloses metis-0001"}) is None
          and m.pr_task({"body": "Closes abcdefghijklmnop-99999"}) is None
          and m.pr_task({"body": "Closes " + "x" * 300 + "-1234"}) is None)
    light = ("argus ×1 ✓ (лёгкий PR ядра: только добавленные тесты/документы, тестов 2, документов 1 — 1 argus Opus "
             "high), CI ✓")
    w = m.window_text(req, {"title": "README guard"}, light, ["README.md"])
    check("вердикт лёгкого PR ядра — целиком, «CI ✓» виден", f"Проверки: {light}. Слить" in w, w)
    every = list(m.CORE_FILES) + ["plugins/pantheon/roles/a.md", ".github/x.yml", "plugins/pantheon/packs/p.json"]
    win = "metis-pantheon-window-name-long-xx"
    w = m.window_text(dict(req, restart=win), {"title": "t" * 200},
                      m.BILLING_OK + SHA[:12] + "; необязательная проверка GitHub tests/full красная: FAILURE", every)
    check("все области, перезапуск, длинный вердикт: хвост целиком, вердикт — коротко, не длиннее 400",
          len(w) <= 400 and w.endswith(f"Слить {REPO} ({SHA[:7]}) и затем перезапустить окно {win}, файлов "
                                       f"{len(set(every))}.") and "CI: лимит, тесты ✓" in w, w)
    long_repo = dict(req, repo="o" * 20 + "/" + "r" * 25, pr=123456, restart="w" * 31)
    w = m.window_text(long_repo, {"title": "t" * 200}, "argus ×2 ✓, CI ✓", every)
    check("длинный repo и окно, все области: вердикт целиком, фраза вытесняется первой (argus #517 Д)",
          len(w) <= 400 and "Проверки: argus ×2 ✓, CI ✓. Слить" in w, w)
    check("пустой заголовок — без «со слов автора» и пустых кавычек",
          m.window_text(req, {}, "CI ✓", ["a"]) == f"#486. По файлам PR: ядро не задето. Проверки: CI ✓. Слить {REPO} "
          f"({SHA[:7]}), файлов 1.")
    reqs = [{"repo": REPO, "pr": 10000 + i, "sha": "%07d" % i + "c" * 33} for i in range(5)]
    views = [{"title": "metis-12%02d: окно Touch ID — номер PR и задачи" % i} for i in range(5)]
    t = m.batch_window_text(reqs, views, ["argus ×2 ✓, CI ✓"] * 5, [[CORE_FILE]] * 5)
    check("MAX_BATCH, обычные задачи: у каждого PR номер, задача, SHA и фраза", len(t) <= 400 and all(
        f"#{10000 + i} metis-12%02d ({'%07d' % i}) «окно Touch" % i in t for i in range(5)), t)
    tfull = "argus ×2 ✓, CI ✓; необязательная проверка GitHub tests/full красная: FAILURE"
    three = [["plugins/guard/hooks/merge_gate.py"], ["plugins/pantheon/lib/window_rules.py"],
             ["plugins/guard/hooks/protect_config.py"], [], []]
    real = [{**r, "pr": 1500 + i} for i, r in enumerate(reqs)]   # четырёхзначные номера: следующие сотни PR
    ok, light = "argus ×2 ✓, CI ✓", ("argus ×1 ✓ (лёгкий PR ядра: только добавленные тесты/документы, тестов 2, "
                                     "документов 1 — 1 argus Opus high), CI ✓")
    for whys in ([ok] * 4 + [tfull], [ok] * 4 + [m.BILLING_OK + SHA[:12]], [ok, tfull, m.BILLING_OK + SHA[:12], light, ok]):
        t = m.batch_window_text(real, views, whys, three)
        check("MAX_BATCH, 3 области, вердикты разные: каждый вердикт — сжатый, но целиком (argus #517 Б1/Б6)",
              len(t) <= 400 and all(f"#{1500 + i} metis-12%02d ({'%07d' % i})" % i in t for i in range(5))
              and all(m.short_why(w) in t for w in whys) and ("tests/full ✗" in t) == (tfull in whys)
              and ("CI: лимит, тесты ✓" in t) == any(m.BILLING_OK in w for w in whys), t)
    narrow = m.BILLING_OK + SHA[:12] + " (узкий прогон: затронутые PR тесты)"
    whys = [narrow, narrow + "; необязательная проверка GitHub tests/full красная: FAILURE", m.BILLING_OK + SHA[:12],
            tfull, light]
    t = m.batch_window_text(real, views, whys, three)
    check("MAX_BATCH, разные вердикты запасного пути: «(узкий)» и «tests/full ✗» целиком (argus #517 Д)",
          len(t) <= 400 and "CI: лимит, тесты ✓ (узкий); tests/full ✗" in t and all(m.short_why(w) in t for w in whys), t)
    t = m.batch_window_text(real, views, [ok] * 5, three)
    check("MAX_BATCH, 3 области, один вердикт: фраза у каждого PR", len(t) <= 400 and t.count("«окно") == 5, t)
    t = m.batch_window_text(real[:3], views[:3], [ok, tfull, light], three[:3])
    check("3 PR, три разных вердикта: фраза у каждого и вердикты целиком",
          len(t) <= 400 and t.count("«окно") == 3 and "(лёгкий), CI ✓" in t and "tests/full ✗" in t, t)
    t = m.batch_window_text(reqs, [{"body": "Closes abcdefghijkl-12%03d" % i} for i in range(5)],
                            ["слово %d " % i * 20 for i in range(5)], [[c] for c in every][:5] + [every])
    check("MAX_BATCH, длинные задачи и разные вердикты: SHA, «Слить по очереди» и вердикт каждого — в окне",
          len(t) <= 400 and "Слить по очереди в latark/agent-kit" in t and all(f"#{10000 + i} слово {i}" in t for i in range(5))
          and all(f"({'%07d' % i})" in t for i in range(5)), t)
    check("области окна покрывают всё ядро и сборку окон",
          set(m.CORE_FILES) | set(m.BUILD_FILES) <= set(m.AREA_FILES) and set(m.CORE_DIR) <= dict(m.AREA_DIRS).keys())


def test_light_no_window():
    """metis-1280 (слово владельца 20.11 «PR вне ядра — без вашего пальца»): заявка на PR agent-kit вне ядра
    ставится с подсказкой «сливает координатор», окна на неё нет; список файлов не получен — окно, как раньше;
    одиночные заявки того же repo — подсказка подать пачкой. Окно «ядро не задето» осталось для других repo."""
    b = Box()
    b.view(SHA, files=["README.md", "plugins/pantheon/lib/env_from.py"])
    r = b.request()
    check("заявка вне ядра: поставлена, подсказка — координатор metis-pantheon и gh pr merge",
          r.returncode == 0 and b.req() is not None and "окна Touch ID на #%d не будет" % PR in r.stdout
          and "metis-pantheon" in r.stdout and "--match-head-commit" in r.stdout, r.stdout + r.stderr)
    b.set("touchid-rc", 0)
    b.run()
    check("заявка вне ядра: окна нет, слияния нет, заявка ждёт", not b.windows() and not b.merges()
          and b.req() is not None, b.outs[-1])
    b.view(SHA, files=["README.md", "plugins/pantheon/lib/env_from.py"], state="MERGED")
    b.run(t=T0 + 60)
    check("слита координатором мимо окна: заявка снята тихо — событие merged-outside, тревоги нет (argus #519 Б1)",
          b.req() is None and "merged-outside" in b.log() and "заявка снята" not in b.alerts(),
          b.outs[-1] + b.alerts())
    b = Box()
    b.view(SHA, files=["README.md"])
    b.request()
    b.run()
    b.run(t=T0 + 25 * 3600)
    check("вне ядра и никто не слил за сутки: заявка остаётся, тревога «не слит 25 ч» (слово владельца 20.11)",
          b.req() is not None and "expired" not in b.log() and "не слит 25 ч" in b.alerts(), b.outs[-1] + b.alerts())
    b.run(t=T0 + 26 * 3600)
    check("через час — без повтора", b.alerts().count("PR вне ядра") == 1, b.alerts())
    b.run(t=T0 + 50 * 3600)
    check("ещё через сутки — тревога повторена", b.alerts().count("PR вне ядра") == 2 and "не слит 50 ч" in b.alerts()
          and b.log().count("nag") == 2, b.alerts())
    for name, checks in (("до первого прохода", None), ("пока CI шёл (проход видел только «ждёт»)",
                                                         ci("PENDING", "SUCCESS"))):
        b = Box()
        b.view(SHA, files=["README.md"], checks=checks)
        b.request()
        if checks:
            b.run()
        b.view(SHA, files=["README.md"], state="MERGED")
        b.run(t=T0 + 60)
        check(f"вне ядра слит координатором {name}: снята тихо по файлам PR (argus #519 Б1)", b.req() is None
              and "merged-outside" in b.log() and "заявка снята" not in b.alerts(), b.outs[-1] + b.alerts())
    b = Box()
    b.view(SHA, files=["README.md", CORE_FILE])
    b.request()
    b.run(extra={"PANTHEON_FAKE_IDLE": "900"})   # вас нет у Mac — заявка ядра ждёт окна
    b.view(SHA, files=["README.md", CORE_FILE], state="MERGED")
    b.run(t=T0 + 60)
    check("PR ядра слит мимо окна — тревога, как раньше (отметки light нет)", b.req() is None
          and "заявка снята — PR не открыт (MERGED)" in b.alerts(), b.outs[-1] + b.alerts())
    check("LIGHT_REPOS — полное owner/repo: чужой <owner>/agent-kit идёт с окном (argus #519 Д1)",
          not _merge_mod().light_paths("other/agent-kit", ["README.md"]))
    b = Box()
    b.view(SHA, files=["README.md", CORE_FILE])
    r = b.request()
    check("заявка с ядром: подсказки «вне ядра» нет", r.returncode == 0 and "Вне ядра" not in r.stdout, r.stdout)
    b = Box()
    b.view(SHA, files=["README.md"], count=3)   # список неполон — ядро не проверить
    r = b.request()
    check("список файлов не получен при заявке: подсказки «вне ядра» нет", "Вне ядра" not in r.stdout,
          r.stdout + r.stderr)
    b = Box()
    b.view(SHA, files=[CORE_FILE])
    b.view(SHA2, pr=8, files=[CORE_FILE])
    b.gate_ok(SHA2, pr=8)
    b.request()
    r = b.request(pr=8)
    check("вторая одиночная заявка того же repo — подсказка подать пачкой одной командой",
          r.returncode == 0 and f"уже ждут отдельные заявки #{PR}" in r.stdout
          and f"pantheon merge request {min(PR, 8)} {max(PR, 8)} -R {REPO}" in r.stdout, r.stdout + r.stderr)
    m = _merge_mod()
    check("light_paths: только agent-kit, только известный список, только без window_core",
          m.light_paths(REPO, ["README.md"]) and not m.light_paths("latark/app", ["README.md"])
          and not m.light_paths(REPO, None) and not m.light_paths(REPO, ["README.md", CORE_FILE])
          and not m.light_paths(REPO, ["plugins/pantheon/lib/pantheon.py"]))
    req = {"repo": "latark/app", "pr": 3, "sha": SHA}
    check("окно другого repo вне ядра — «ядро не задето»",
          ". По файлам PR: ядро не задето. " in m.window_text(req, {"title": "t"}, "CI ✓", ["README.md"]))


def test_core_matches_guard():
    """Ядро в окне — то же, что у шлюза guard: CORE_FILES и CORE_DIR merge.py и merge_gate.py совпадают."""
    code = ("import sys, importlib.util; sys.path.insert(0, %r); import merge_gate as g\n"
            "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m)\nprint(g.CORE_FILES == m.CORE_FILES and g.CORE_DIR == m.CORE_DIR)"
            % (GUARD_HOOKS, os.path.join(LIBDIR, "merge.py")))
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    check("ядро merge.py == ядро merge_gate.py", r.stdout.strip() == "True", r.stdout + r.stderr)



def test_is_core_matches_gate():
    """metis-0551: один признак ядра — merge.is_core и _is_core шлюза совпадают на одних путях (./, //, `..`, регистр),
    а окно Touch ID называет среди ядра и файлы сборки окон BUILD_ROOTS шлюза."""
    paths = ["plugins/guard/x.py", "./plugins/guard/x.py", "plugins//guard/x.py", "plugins/x/../guard/x.py",
             "PLUGINS/Pantheon/lib/merge.py", "plugins/pantheon/lib/a/../merge.py", "/plugins/pantheon/hooks/ctx.py",
             "plugins/pantheon/lib/pantheon.py", "plugins/pantheon/lib/sessions.py", "README.md", "", "/", ".",
             "plugins/guardian/x.py", ".github", "plugins/pantheon/packs/a/hooks.json",
             "a/../.claude-plugin/marketplace.json"]
    code = ("import sys, json, importlib.util; sys.path.insert(0, %r); import merge_gate as g\n"
            "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m)\ncore = {c.casefold() for c in g.CORE_FILES}\nps = json.loads(sys.argv[1])\n"
            "print(json.dumps([[p, g._is_core(p, core), m.is_core(p), m.window_core(p)] for p in ps]))\n"
            "print(json.dumps(sorted(g.BUILD_ROOTS) == sorted(m.BUILD_FILES)))"
            % (GUARD_HOOKS, os.path.join(LIBDIR, "merge.py")))
    r = subprocess.run([sys.executable, "-I", "-c", code, json.dumps(paths)], capture_output=True, text=True,
                       timeout=60)
    lines = r.stdout.splitlines()
    rows = json.loads(lines[0]) if lines else []
    check("is_core: ответ на каждый путь", len(rows) == len(paths), r.stdout + r.stderr)
    bad = [x for x in rows if x[1] != x[2]]
    check("is_core merge.py == _is_core шлюза на всех путях", not bad, bad)
    check("окно: файлы сборки — среди ядра окна, но не is_core",
          all(x[3] and not x[2] for x in rows if x[0].endswith(("lib/pantheon.py", "lib/sessions.py"))), rows)
    check("окно: ядро is_core — и ядро окна", all(x[3] for x in rows if x[2]), rows)
    check("BUILD_FILES merge.py == BUILD_ROOTS шлюза", lines[1:] == ["true"], r.stdout + r.stderr)


def test_ci_fork():
    """metis-0649: PR из форка — у его запусков pull_requests пуст; проход по Touch ID засчитывает запуск
    pull_request с head этого форка и ветки (поля из gh pr view, их просит pr_view). Чужой форк или ветка на том же
    SHA — ждёт; форк не получен — заявка снята с тревогой; обычный PR без номера в pull_requests — ждёт, как раньше."""
    def fork_ci(repo="Ext/agent-kit", branch="feat"):
        return [dict(c, prs=[], head_repo=repo, head_branch=branch) for c in ci("SUCCESS", "SUCCESS")]

    b = Box()
    b.request()
    b.view(SHA, checks=fork_ci(), head=FORK)
    b.run()
    check("форк: зелёные запуски его head → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1,
          b.outs[-1])
    for how, checks in (("чужого форка", fork_ci(repo="evil/agent-kit")), ("чужой ветки", fork_ci(branch="x"))):
        b = Box()
        b.request()
        b.view(SHA, checks=checks, head=FORK)
        b.run()
        check(f"форк: зелёные запуски {how} на том же SHA → окна нет, ждёт", not b.windows() and b.req() is not None,
              b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=fork_ci(), head=dict(FORK, headRepository={"id": "R_x"}))
    b.run()
    check("форк: nameWithOwner не получен → окна нет, заявка снята с тревогой «из форка»",
          not b.windows() and not b.merges() and b.req() is None and "из форка" in b.alerts(), b.alerts())
    b = Box()
    b.request()
    b.view(SHA, checks=fork_ci(), head=dict(FORK, isCrossRepository=False))
    b.run()
    check("не форк: запуски без номера PR → окна нет, ждёт (как раньше)", not b.windows() and b.req() is not None,
          b.outs[-1])
    calls = [json.loads(x)["argv"] for x in open(os.path.join(b.rec, "gh-argv.jsonl"))]
    fields = [a[a.index("--json") + 1].split(",") for a in calls if a[:2] == ["pr", "view"]]
    check("pr_view просит isCrossRepository, headRepository и headRefName",
          fields and all({"isCrossRepository", "headRepository", "headRefName"} <= set(f) for f in fields), fields)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544); исключение — провал случая
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], FAILS,
              lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
