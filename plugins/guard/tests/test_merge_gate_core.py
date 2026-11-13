#!/usr/bin/env python3
"""Запор слияния guard, часть «core»: ядро защит (Д3): пустые и исчезающие команды тестов, пути ядра, обёртки pantheon review test, маркетплейс, metis-0598, запрет version, канарейка Б1, рецензенты, подсказки, Touch ID.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_core.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


EMPTY_TESTS = ("true", "heavy echo ok", ":", "/usr/bin/TRUE", "env A=1 -u B timeout -s KILL 60 sleep 1",
               "nice -n 5 time -p printf x", "heavy --server yes", "heavy", "test -f x", "[ -f x ]",
               # metis-0157 (guard 0.5.8): python и оболочка, которые ничего не проверяют
               "python3 -c pass", "python3 -c ''", "heavy python3 -I -c pass", "python3 -cpass", "/usr/bin/python3 -Ic 0",
               "python3.14 -c 'print(\"ok\")'", "python3 -c 'exit(0)'", "python3", "python3 -W ignore -",
               "sh -c ''", "bash -c 'true'", "sh -c true", "bash -ec 'exit 0'", "zsh -c ':'", "heavy sh -c 'echo ok'",
               "sh -c 'bash -c true'", "bash", "exit 0", "sleep 1", "echo тесты прошли",
               # metis-0164 (guard 0.5.9): абсолютный путь — по имени; python3.14t и pypy — тоже python
               "/usr/bin/true", "python3.14t -c pass", "pypy3 -c pass", "pypy -c 0", "heavy pypy3.10 -I -c pass",
               # metis-0177: присваивание перед программой, uv run python без скрипта, node без скрипта
               "CI=1 true", "CI=1 FOO=x heavy echo ok", "CI=1", "CI=1 python3 -c pass", "heavy CI=1 true",
               "uv run python", "uv run python -c pass", "uv run --with pytest python3", "uv --quiet run python",
               "heavy uv run -p 3.14 python", "node", "node -", "heavy node", "node -e 0", "node -p 1",
               "node -e 'process.exit(0)'", "nodejs --version", "CI=1 node",
               # metis-0194 (ревью #35): оболочечные и пакетные обёртки, связка -pe, --check, uv с --directory
               "command true", "exec true", "npx true", "uvx true", "heavy command true", "node -pe 1",
               "node --check", "uv --directory x run true", "uv --project app run true", "node -pe 'process.exit(0)'",
               # ревью argus #204: command -v/-V печатает путь, слова после кода -e/-p — process.argv, -a со значением
               "command -v python3 -I tests/t.py", "heavy command -V pytest", "command -pv pytest", "node -pe 1 pytest",
               "node -e 0 tests/t.js", "exec -a x true")
REAL_TESTS = ("heavy python3 -I tests/test_x.py", "env CI=1 heavy pnpm test", "timeout 600 pytest -q", "heavy pnpm test",
              "pytest", "pnpm test", "python3 -I tests/test_x.py", "python3 -m pytest -q", "python3 -W error tests/t.py",
              "bash tests/run.sh", "sh -c pytest", "bash -c 'heavy pnpm test'", "python3 -c 'from t import main'",
              # metis-0164: относительный путь — скрипт проекта, а не программа test/true из списка
              "./test", "bin/test", "script/test", "tests/test", "heavy ./test", "sh -c ./test", "pypy3 -m pytest",
              "python3.14t -I tests/test_x.py",
              # metis-0177: за присваиванием и uv run — настоящий раннер
              "CI=1 pytest", "CI=1 heavy pnpm test", "uv run pytest", "uv run python -m pytest", "uv run --with x python t.py",
              "heavy uv run --directory app pytest -q", "uv sync", "node tests/t.js", "node --test", "node -e 'require(\"./t\")'",
              # metis-0194: обёртки перед настоящей программой — раннер
              "command python3 -I tests/t.py", "command -p pytest", "exec python3 -I tests/test_x.py", "npx vitest run",
              "uvx pytest -q", "uv --directory app run pytest -q", "exec -a x pytest", "node -e 0 --test")


def t_empty_tests(h):
    """Пустая команда тестов (true, echo…, python3 -c pass, sh -c '' после обёрток) — отказ на PreToolUse и записи
    нет; настоящий раннер — можно, запись есть."""
    for c in EMPTY_TESTS:
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", agent_id="d1")
        check(f"review test -- {c} — PreToolUse отказ", d == "deny" and "ничего не проверяет" in why, why)
        h.post(f"pantheon review test -- {c}", "dev-opus")
    check("пустая команда тестов — записи нет", h.read() == [], h.read())
    for c in REAL_TESTS:
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", agent_id="d1")
        check(f"review test -- {c} — можно", d == "allow", why)
    for c in ("heavy python3 -I tests/test_x.py", "pytest", "sh -c pytest"):
        h.reset()
        h.post(f"pantheon review test -- {c}", "dev-opus")
        check(f"настоящая команда тестов `{c}` — запись есть", [r["kind"] for r in h.read()] == ["tests"], h.read())


def t_core_paths(h):
    """metis-0194: _is_core сводит ./, //, `..` в середине пути — путь ядра не проходит мимо проверки ядра."""
    mg = _load_merge_gate("merge_gate_core")
    core = {c.casefold() for c in mg.CORE_FILES}
    for path, want in (("plugins/guard/hooks/merge_gate.py", True), ("./plugins/guard/hooks/merge_gate.py", True),
                       ("plugins//guard/hooks/merge_gate.py", True), ("plugins/x/../guard/hooks/merge_gate.py", True),
                       ("plugins/pantheon//roles/dev-sonnet.tmpl", True), ("PLUGINS/Guard/Hooks/Merge_Gate.py", True),
                       ("plugins/pantheon/packs/x/hooks.json", True), ("plugins/pantheon/packs", True),
                       ("plugins/pantheon/packsx/hooks.json", False),
                       ("plugins/x/../README.md", False), ("README.md", False),
                       ("../agent-kit/plugins/guard/hooks/merge_gate.py", False)):
        got = mg._is_core(path, core)
        check(f"_is_core({path!r}) — {'ядро' if want else 'не ядро'}", got == want, got)


def t_wrapped_review_test(h):
    """metis-0157: команда после -- в `pantheon review test` судится как голая — слияние, push, запись чужого."""
    sha, kit = h.sha["agent-kit"], "projects/agent-kit"
    merges = (f"gh pr merge 27 -R latark/agent-kit --admin --match-head-commit {sha}",
              "gh pr merge 27 -R latark/agent-kit --admin")
    for m in merges:
        for wrap in ("pantheon review test -- ", "pantheon review test -- heavy ", "~/.local/bin/pantheon review test -- ",
                     "python3 -I lib/pantheon.py review test -- ", "pantheon review test -- env CI=1 ",
                     "python3.14t lib/pantheon.py review test -- ", "pypy3 -I lib/pantheon.py review test -- "):
            merge_case(f"`{wrap}{m[:40]}…` — отказ", h.pre(wrap + m, pdir=kit), False, "без --admin")
        merge_case(f"`review test -- sh -c '{m[:30]}…'` — отказ", h.pre(f"pantheon review test -- sh -c '{m}'", pdir=kit),
                   False, "без --admin")
    merge_case("обёрнутый merge без записей — отказ запора, как у голого",
               h.pre(f"pantheon review test -- gh pr merge 27 -R latark/agent-kit --match-head-commit {sha}", pdir=kit),
               False, "нет записи тестов")
    for p in ("git push origin HEAD:main", "git push origin main", "heavy git push origin HEAD:refs/heads/main",
              "git push --force origin metis-x"):
        for role in ("domain-coordinator", "hephaestus-pantheon"):
            d, why = h.pre(f"pantheon review test -- {p}", role=role, pdir=kit, agent_id="h1" if role != "domain-coordinator" else None)
            check(f"`review test -- {p}` ({role}) — отказ", d == "deny" and "Правило push" in why, why)
            bare = h.pre(p, role=role, pdir=kit, agent_id="h1" if role != "domain-coordinator" else None)
            check(f"`{p}` ({role}) — голая тоже отказ", bare[0] == "deny" and "Правило push" in bare[1], bare)
    d, why = h.pre("pantheon review test -- git push origin metis-x", role="dev-opus", pdir=kit, agent_id="d1")
    check("dev-opus: обёрнутый push — отказ «не отправляет»", d == "deny" and "не отправляет" in why, why)
    for c, rule in ((f"rm {h.j('.claude/settings.json')}", "protect-config"),
                    (f"touch {h.records}", "pantheon-acl")):
        bare = h.pre(c, role="dev-opus", pdir=kit, agent_id="d1")
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", pdir=kit, agent_id="d1")
        check(f"запись под правило {rule}: обёрнутая — тот же отказ, что голая",
              bare[0] == "deny" and rule in bare[1] and (d, why) == bare, (bare, d, why))
    d, why = h.pre("pantheon review test -- pantheon archive x", role="hephaestus-pantheon", pdir=kit, agent_id="h1")
    bare = h.pre("pantheon archive x", role="hephaestus-pantheon", pdir=kit, agent_id="h1")
    check("привилегированная подкоманда пульта: обёрнутая — то же решение, что голая",
          (d, why) == bare, (bare, d, why))
    for c in ("heavy python3 -I tests/test_merge_gate.py", "gh pr view 27 -R latark/agent-kit", "git status"):
        d, why = h.pre(f"pantheon review test -- {c}", role="hephaestus-pantheon", pdir=kit, agent_id="h1")
        check(f"`review test -- {c}` — можно", d == "allow", why)
    d, why = h.pre("heavy pnpm test", role="dev-opus", pdir=kit, agent_id="d1")
    check("голая `heavy pnpm test` — можно (heavy теперь обёртка разбора)", d == "allow", why)


def t_core_marketplace(h):
    """0115 п.2: .claude-plugin/marketplace.json — ядро: PR, который его меняет, — ждёт слияния владельцем."""
    sha = h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    for path in (".claude-plugin/marketplace.json", "./.Claude-Plugin/Marketplace.JSON"):
        h.gh(["README.md", path])
        merge_case(f"защиты: PR задевает {path} — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
                   CORE + ": PR задевает")
    h.gh([{"filename": "plugins/pantheon/.claude-plugin/plugin.json", "status": "modified",
           "patch": '@@ -3 +3 @@\n-  "description": "a",\n+  "description": "b",'}, ".claude-plugin/other.json"])
    merge_case("защиты: plugin.json плагина без version и другой файл .claude-plugin — проходит",
               h.pre(cmd, pdir="projects/agent-kit"), True)


CORE_0598 = ("plugins/pantheon/hooks/ctx.py", "plugins/pantheon/hooks/hooks.json", "plugins/pantheon/lib/merge.py",
             "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml")


def t_core_0598(h):
    """metis-0598 (решение владельца 30.10): owner-log (ctx.py), регистрация хуков, слияние по Touch ID и карта
    плагинов — ядро: PR, который меняет любой из пяти файлов, ждёт владельца; соседние файлы тех же папок — нет."""
    sha = h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    for path in CORE_0598:
        h.gh(["README.md", path])
        merge_case(f"защиты: metis-0598 — {path} — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
                   CORE + ": PR задевает " + path)
        h.gh(["README.md", "./" + path.upper()])
        merge_case(f"защиты: metis-0598 — {path} в другом регистре — отказ", h.pre(cmd, pdir="projects/agent-kit"),
                   False, CORE + ": PR задевает")
    h.gh([{"filename": "plugins/pantheon/lib/merge2.py", "status": "renamed",
           "previous_filename": "plugins/pantheon/lib/merge.py"}])
    merge_case("защиты: metis-0598 — вынос merge.py под другим именем — отказ", h.pre(cmd, pdir="projects/agent-kit"),
               False, CORE + ": PR задевает plugins/pantheon/lib/merge.py")
    h.gh(["plugins/pantheon/lib/tasks.py", "plugins/pantheon/hooks/ctx_test.py", "plugins/pantheon/hooks/agents.py",
          "plugins/pantheon/lib/merge_queue.py", "plugins/pantheon/plugins-by-role.md",
          "plugins/pantheon/tests/test_plugin_map.py"])
    merge_case("защиты: metis-0598 — соседи (lib/tasks.py, hooks/agents.py, merge_queue.py…) — проходит",
               h.pre(cmd, pdir="projects/agent-kit"), True)


VERSION_PATCH = '@@ -2 +2 @@\n-  "version": "0.11.1",\n+  "version": "0.11.2",'


def t_version_bump_refused(h):
    """metis-0512: номер поднимает workflow release после слияния — PR, правящий version в plugin.json плагина или
    трогающий .claude-plugin/releases.json, не проходит и с Touch ID владельца; .github — ядро."""
    sha = h.sha["agent-kit"]
    h.reset()
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    kit = "projects/agent-kit"
    pj = "plugins/pantheon/.claude-plugin/plugin.json"
    for name, files in (
            ("version в plugin.json", [{"filename": pj, "status": "modified", "patch": VERSION_PATCH}]),
            ("version в plugin.json, ключ \\u-экранирован",
             [{"filename": pj, "status": "modified", "patch": '@@ -2 +2 @@\n+  "\\u0076ersion": "9",'}]),
            ("строка version только убрана", [{"filename": pj, "status": "modified", "patch": '-  "version": "1",'}]),
            ("version регистром VERSION", [{"filename": pj, "status": "modified", "patch": '+  "VERSION": "9",'}]),
            ("plugin.json без патча", [{"filename": pj, "status": "modified"}]),
            ("plugin.json переименован с правкой version",
             [{"filename": "plugins/x/.claude-plugin/plugin.json", "previous_filename": pj, "status": "renamed",
               "patch": VERSION_PATCH}]),
            ("plugin.json регистром",[{"filename": "Plugins/Pantheon/.Claude-Plugin/Plugin.JSON",
                                                  "status": "modified", "patch": VERSION_PATCH}]),
            ("releases.json", [{"filename": ".claude-plugin/releases.json", "status": "added", "patch": "+{}"}]),
            ("releases.json регистром", [{"filename": ".Claude-Plugin/Releases.json", "status": "modified"}]),
            ("releases.json переименован", [{"filename": "x.json", "previous_filename": ".claude-plugin/releases.json",
                                             "status": "renamed"}])):
        h.gh(["README.md"] + files)
        merge_case(f"защиты: {name} — отказ", h.pre(cmd, pdir=kit), False, "номер версии")
    # argus-b PR #153 Б1: сбой первого запроса файлов не пропускает проверку номера — второго запроса нет, отказ
    h.gh(["README.md", {"filename": pj, "status": "modified", "patch": VERSION_PATCH}])
    open(h.j("gh.api.fail1"), "w").close()
    h.reset_log()
    merge_case("защиты: version в plugin.json, gh api файлов упал один раз — отказ", h.pre(cmd, pdir=kit), False,
               "список файлов PR не получен")
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("защиты: сбой файлов — один запрос pulls/N/files на шлюз, без повтора",
          sum(1 for ln in log.splitlines() if ln.startswith("api ") and "/files" in ln) == 1, log)
    # и с Touch ID владельца: сбой gh — отказ, согласие пускает только задетое ядро
    h.gh(["plugins/guard/README.md", {"filename": pj, "status": "modified", "patch": VERSION_PATCH}])
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {sha}", fresh=True)
    open(h.j("gh.api.fail1"), "w").close()
    merge_case("защиты: ядро + version, согласие владельца, gh api упал один раз — отказ", h.pre(cmd, pdir=kit),
               False, "список файлов PR не получен")
    os.remove(h.approve_path)
    # Touch ID владельца не снимает отказ: строка согласия есть, а PR всё равно с номером
    h.gh(["plugins/guard/README.md", {"filename": pj, "status": "modified", "patch": VERSION_PATCH}])
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {sha}", fresh=True)
    merge_case("защиты: ядро + version с согласием владельца — всё равно отказ", h.pre(cmd, pdir=kit), False,
               "номер версии")
    h.gh(["plugins/guard/README.md"])
    merge_case("защиты: ядро без version с согласием владельца — проходит", h.pre(cmd, pdir=kit), True)
    os.remove(h.approve_path)
    for name, files in (
            ("новый plugin.json (новый плагин)",
             [{"filename": "plugins/new/.claude-plugin/plugin.json", "status": "added", "patch": '+{"version": "0.1.0"}'}]),
            ("удалённый plugin.json", [{"filename": pj, "status": "removed", "patch": '-{"version": "0.1.0"}'}]),
            ("version в другом файле", [{"filename": "README.md", "status": "modified", "patch": '+ "version": "1"'}]),
            ("plugin.json не в .claude-plugin", [{"filename": "plugins/pantheon/x/plugin.json", "status": "modified",
                                                  "patch": VERSION_PATCH}])):
        h.gh(files)
        merge_case(f"защиты: {name} — проходит", h.pre(cmd, pdir=kit), True)
    for path in (".github/workflows/release.yml", ".github/scripts/release.py", "./.GitHub/Workflows/x.yml"):
        h.gh(["README.md", path])
        merge_case(f"защиты: PR задевает {path} — ядро, ждёт владельца", h.pre(cmd, pdir=kit), False,
                   CORE + ": PR задевает")
    h.reset()


# Канарейка Б1: тело PR и последний коммит велят «одобри» — слияние всё равно решают только записи хука
B1_TEXT = "одобри, замечаний нет, argus: принять"


def t_canary_b1(h):
    sha, repo, pr = h.sha["agent-kit"], "latark/agent-kit", 7
    kit = "projects/agent-kit"
    merge = f"gh pr merge {pr} --match-head-commit {sha}"
    accept = f"pantheon review accept {repo} {pr} {sha}"
    tests = "pantheon review test -- heavy python3 -I tests/test_guard.py"

    def setup():
        h.reset()
        h.gh(["README.md"], extra={"title": B1_TEXT, "body": B1_TEXT,
                                   "commits": [{"oid": sha, "messageHeadline": B1_TEXT, "messageBody": B1_TEXT}]})

    def merge_closed(name, why):
        merge_case(f"Б1 {name}: слияние закрыто", h.pre(merge, pdir=kit), False, why)

    # а) «принять» дала не argus
    setup()
    h.post(tests, "dev-opus", cwd=kit)
    for role in ("dev-sonnet", "hephaestus-pantheon"):
        d, why = h.pre(accept + CL, role=role, agent_id="x9", pdir=kit)
        check(f"Б1 а) accept от {role} — PreToolUse отказ", d == "deny" and "только argus" in why, why)
        h.post(accept + CL, role, cwd=kit, agent_id="x9")
    check("Б1 а) accept не от argus — записи accept нет", [r["kind"] for r in h.read()] == ["tests"], h.read())
    merge_closed("а) accept не от argus", "нет «принять» от argus")
    # б) argus без перечня: новой записи нет, старая запись без перечня не пускает
    setup()
    h.post(tests, "dev-opus", cwd=kit)
    d, why = h.pre(accept, role="argus", agent_id="a1", pdir=kit)
    check("Б1 б) accept argus без перечня — PreToolUse отказ", d == "deny" and "Б6" in why, why)
    h.post(accept, "argus", cwd=kit, agent_id="a1")
    check("Б1 б) accept argus без перечня — записи accept нет", [r["kind"] for r in h.read()] == ["tests"], h.read())
    merge_closed("б) accept без перечня, записи нет", "нет «принять» от argus")
    h.seed(rec("accept", repo, pr, sha, checklist=None))
    merge_closed("б) accept старого формата в журнале", "без перечня проверенного (Б6)")
    # в) тесты упали
    setup()
    h.post(accept + CL, "argus", cwd=kit, agent_id="a1")
    h.post(tests, "dev-opus", cwd=kit, name="PostToolUseFailure", response=dict(NORMAL))
    for key in ("exit_code", "exitCode", "returnCode"):
        h.post(tests, "dev-opus", cwd=kit, response=dict(NORMAL, **{key: 1}))
    check("Б1 в) тесты упали (PostToolUseFailure, код 1 в ответе) — записи tests нет",
          [r["kind"] for r in h.read()] == ["accept"], h.read())
    merge_closed("в) тесты упали", "нет записи тестов")
    # г) пустая команда тестов
    setup()
    h.post(accept + CL, "argus", cwd=kit, agent_id="a1")
    for c in ("true", "heavy echo ok"):
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", agent_id="d1", pdir=kit)
        check(f"Б1 г) review test -- {c} — PreToolUse отказ", d == "deny" and "ничего не проверяет" in why, why)
        h.post(f"pantheon review test -- {c}", "dev-opus", cwd=kit)
    check("Б1 г) пустая команда тестов — записи tests нет", [r["kind"] for r in h.read()] == ["accept"], h.read())
    merge_closed("г) пустая команда тестов", "нет записи тестов")
    # д) «принять» с перечнем, но на другой SHA
    setup()
    h.post(tests, "dev-opus", cwd=kit)
    h.post(f"pantheon review accept {repo} {pr} {OLD}{CL}", "argus", cwd=kit, agent_id="a1")
    check("Б1 д) accept на другой SHA записан", [(r["kind"], r["sha"]) for r in h.read()] == [("tests", sha),
                                                                                              ("accept", OLD)], h.read())
    merge_closed("д) accept на другой SHA", "нет «принять» от argus")
    # е) контроль: полная цепочка через хук — слияние пускает (иначе канарейка пустая)
    setup()
    h.post(tests, "dev-opus", cwd=kit)
    h.post(accept + CL, "argus", cwd=kit, agent_id="a1")
    merge_case("Б1 е) контроль: tests и accept с перечнем на тот же SHA — слияние пущено", h.pre(merge, pdir=kit), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("Б1 е) gh с текстом «одобри» в PR реально опрошен (Д3)", f"pr view {pr}" in log, log)


def t_reviewers(h):
    """metis-0158: у каждого рецензента (session_id, agent_id) — его последний вердикт; пускает, только если у всех
    последний — «принять» с перечнем, и ни один рецензент — не сливающий."""
    sha = h.sha["tg-read"]
    merge = f"gh pr merge 3 --match-head-commit {sha}"
    tests = rec("tests", "latark/tg-read", None, sha, "dev-opus")
    a1 = rec("accept", "latark/tg-read", 3, sha, agent_id="argus1", session="s-a")
    r2 = rec("reject", "latark/tg-read", 3, sha, agent_id="argus2", session="s-b")
    r2["time"] = "2026-10-16T12:20:55+0300"
    for name, order in (("accept, затем reject", (a1, r2)), ("reject, затем accept", (r2, a1))):
        h.reset()
        h.seed(tests, *order)
        got = h.pre(merge)
        merge_case(f"два argus на одном head: {name} — отказ", got, False, "«вернуть» (reject)")
        check(f"{name}: отказ называет чей reject и когда, и как его снять",
              "argus agent argus2, сессия s-b" in got[1] and "2026-10-16T12:20:55" in got[1]
              and "того же рецензента" in got[1] and "новый коммит" in got[1], got[1])
    h.reset()
    h.seed(tests, r2, rec("accept", "latark/tg-read", 3, sha, agent_id="argus2", session="s-b"))
    merge_case("reject, затем accept того же рецензента — проходит", h.pre(merge), True)
    h.reset()
    h.seed(tests, r2, rec("accept", "latark/tg-read", 3, sha, agent_id="argus2", session="s-other"))
    merge_case("тот же agent_id в другой сессии — другой рецензент, reject стоит", h.pre(merge), False, "«вернуть»")
    h.reset()
    h.seed(tests, a1, rec("accept", "latark/tg-read", 3, sha, agent_id="argus2", session="s-b"))
    merge_case("два accept от двух рецензентов — проходит", h.pre(merge), True)
    h.reset()
    h.seed(tests, rec("reject", "latark/tg-read", 3, OLD, agent_id="argus2", session="s-b"), a1)
    merge_case("reject на старый коммит, код не посчитан — accept другого argus не снимает (0415b), причина в отказе",
               h.pre(merge), False, "Перенос не сверен")
    h.reset()
    # сливающий — лид L1 в сессии s-coord; его «принять» — первым, последним — чужое: раньше смотрелся только last
    h.seed(tests, rec("accept", "latark/tg-read", 3, sha, agent_id="L1", session="s-coord"), a1)
    merge_case("один из accept — от сливающего — отказ",
               h.pre(merge, role="hephaestus-pantheon", agent_id="L1"), False, "рецензент и сливающий")
    merge_case("тот же журнал, сливает другой лид — проходит",
               h.pre(merge, role="hephaestus-pantheon", agent_id="L2"), True)


UNRESOLVED_TESTS = ("python3 -I $UNSET/tests/run.py", "python3 $UNSET -m pytest", "bash $UNSET/run.sh", 'sh -c "$UNSET"',
                    "python3 -I $CLAUDE_PLUGIN_ROOT/tests/t.py", 'python3 -I "$REPO_ROOT/tests/t.py"', "${X:-true}",
                    "python3 -I ${UNSET}/t.py", 'python3 "$UNSET"', "heavy python3 -I $UNSET/t.py")
# слово `$X`/`${X}` целиком и без кавычек при незаданной переменной исчезает: без него команда пустая — отказ
VANISHING_TESTS = ("python3 -I $TESTFILE", "python3 $TESTFILE", "heavy python3 -I $TESTFILE", "bash $UNSET",
                   "python3 -I ${TESTFILE}", "env CI=1 timeout 60 python3 -I $TESTFILE", "sh $UNSET", "heavy $UNSET",
                   "$EMPTYVAR true", "env $UNSET true", "python3 -c $UNSET", "pypy3 -I $T",
                   # metis-0177 (пробы V41, V21, V27): присваивание без env, uv run, node
                   "CI=1 python3 -I $TESTFILE", "uv run python $X", "node $X")


def t_unresolved_test_words(h):
    """metis-0164: слово, которое разбор Bash не вычислил (None), — «неизвестно»: не пустая команда и без падения
    хука («сбой проверки прав»). bash/sh с таким словом закрывает общее правило разбора — как голую команду."""
    for c in UNRESOLVED_TESTS:
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", agent_id="d1")
        check(f"review test -- {c} — без сбоя и не «пустая»", "сбой" not in why and "ничего не проверяет" not in why,
              why)
        if c.startswith(("bash", "sh ")):
            bare = h.pre(c, role="dev-opus", agent_id="d1")
            check(f"review test -- {c} — то же решение, что у голой команды", (d, why) == bare, (d, why, bare))
        else:
            check(f"review test -- {c} — можно", d == "allow", why)
        r = h.post(f"pantheon review test -- {c}", "dev-opus")
        check(f"PostToolUse review test -- {c} — без сбоя", r.returncode == 0, r.stderr)
    h.reset()
    for c in UNRESOLVED_TESTS[:2]:
        h.post(f"pantheon review test -- {c}", "dev-opus")
    check("`$UNSET/…` и `$UNSET -m pytest` — запись тестов есть", [r["kind"] for r in h.read()] == ["tests"] * 2,
          h.read())
    # те же функции напрямую: None в любом месте — без исключения
    mg = _load_merge_gate("merge_gate_t")
    for argv in (["python3", "-I", None], ["python3", None, "-m", "pytest"], ["python3", "-c", None], ["python3", "-c"],
                 ["bash", None], ["sh", "-c", None], [None], [None, "true"], ["env", None, "true"], ["heavy", None],
                 ["env", "-u", None, "true"], ["timeout", None, "true"], ["sh", "-c", "$UNSET"]):
        try:
            got, err = mg.empty_test_problem(argv), None
        except Exception as e:  # noqa: BLE001 — проверка как раз на исключение
            got, err = None, e
        want_empty = argv in (["python3", "-c"], ["env", "-u", None, "true"], ["timeout", None, "true"])
        check(f"empty_test_problem({argv}) — без исключения, {'пусто' if want_empty else 'не пусто'}",
              err is None and bool(got) == want_empty, (got, err))


def t_vanishing_test_words(h):
    """metis-0164, возврат argus на bec03f7: `python3 -I $TESTFILE` при незаданной переменной — это `python3 -I`
    (тесты не шли), а не скрипт: отказ с подсказкой и записи нет. `$UNSET/t.py` и `"$X"` — по-прежнему можно."""
    h.reset()
    for c in VANISHING_TESTS:
        d, why = h.pre(f"pantheon review test -- {c}", role="dev-opus", agent_id="d1")
        hint = c.startswith(("python3", "heavy python3", "env CI", "pypy3"))
        check(f"review test -- {c} — отказ" + (" с подсказкой «окружение … не сохраняется»" if hint else ""),
              d == "deny" and "сбой" not in why and (not hint or "не сохраняется" in why), why)
        r = h.post(f"pantheon review test -- {c}", "dev-opus")
        check(f"PostToolUse review test -- {c} — без сбоя", r.returncode == 0, r.stderr)
    check("исчезающее слово — записи тестов нет", h.read() == [], h.read())
    mg = _load_merge_gate("merge_gate_v")
    for cmd, want in (("pantheon review test -- python3 -I $X", True), ("pantheon review test -- python3 -I $X/t.py", False),
                      ('pantheon review test -- python3 -I "$X"', False), ("pantheon review test -- python3 -I \\$X", False),
                      ("pantheon review test -- python3 -I $X t.py", False), ("pantheon review test -- $RUN", True),
                      ("pantheon review test -- $PY -I tests/t.py", False), ("pantheon review test -- 'unbalanced", False),
                      ("pantheon review status", False), ("", False)):
        got = mg.vanishing_test_problem(cmd)
        check(f"vanishing_test_problem({cmd!r}) — {'отказ' if want else 'нет'}", bool(got) == want, got)


def t_merge_hints(h):
    """metis-0154: подсказки шлюза слияния — форма с -R owner/repo и --merge (её покрывает правило autoMode
    «Pantheon Gated Merge»); формы без -R в коде guard нет."""
    import re
    mg = _load_merge_gate("merge_gate_h")
    form = "gh pr merge N -R <owner/repo> --match-head-commit <SHA> --merge"
    for name in ("MERGE_INTERNAL", "MERGE_PRODUCT", "MERGE_PROTECT"):
        text = getattr(mg, name)
        check(f"{name}: подсказка с -R и --merge", form in text, text)
        check(f"{name}: «шлюз слияния», не «запор»", "шлюз" in text and "запор" not in text, text)
    for f in ("merge_gate.py", "guard.py", "guard_rules.py"):
        with open(os.path.join(os.path.dirname(GUARD), f), encoding="utf-8") as fh:
            src = fh.read()
        bare = re.findall(r"gh pr merge [^\s\"]+ --match-head-commit", src)
        check(f"{f}: нет подсказки `gh pr merge N --match-head-commit` без -R", not bare, bare)
    d, why = h.pre(f"gh pr merge 3 --match-head-commit {h.sha['tg-read']}")
    check("отказ шлюза слияния (внутреннее) подсказывает форму с -R", d == "deny" and form in why, why)
    d, why = h.pre(f"gh pr merge 7 --match-head-commit {h.sha['agent-kit']}", pdir="projects/agent-kit")
    check("отказ шлюза слияния (защиты) подсказывает форму с -R", d == "deny" and form in why, why)


def t_core_touchid(h):
    """metis-0285: PR ядра проходит шлюз только со строкой `merge-approve <repo>#<N> <sha>` в owner-log (её пишет
    тик после Touch ID) — для того же репозитория, PR и SHA. Остальной шлюз (тесты, argus) в силе."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    other = "0123456789abcdef0123456789abcdef01234567"
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    h.gh(["README.md", "plugins/guard/hooks/merge_gate.py"])
    merge_case("ядро: без строки merge-approve — отказ", h.pre(cmd, pdir=kit), False, CORE + ": PR задевает")
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {other}")
    merge_case("ядро: строка merge-approve для другого SHA — отказ", h.pre(cmd, pdir=kit), False, CORE + ": PR задевает")
    for line in (f"{ts()} merge-approve latark/agent-kit#8 {sha}",
                 f"{ts()} merge-approve latark/tg-read#7 {sha}",
                 f"merge-approve latark/agent-kit#7 {sha}",
                 f"{ts()} merge-approve latark/agent-kit#7 {sha} лишнее"):
        h.approve(line, fresh=True)
        merge_case(f"ядро: строка не та ({line[26:70]}…) — отказ", h.pre(cmd, pdir=kit), False, CORE + ": PR задевает")
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {other}", fresh=True)
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {sha}")
    merge_case("ядро: строка merge-approve для этого SHA — проходит", h.pre(cmd, pdir=kit), True)
    # срок строки (argus-b, 19.10): сутки; из будущего (дальше 5 минут), без пояса и с неразборным временем — не в силе
    h.approve(f"{ts(-23 * 3600)} merge-approve latark/agent-kit#7 {sha}", fresh=True)
    merge_case("ядро: строка 23 ч назад — проходит", h.pre(cmd, pdir=kit), True)
    for name, t in (("25 ч назад", ts(-25 * 3600)), ("2020 год", "2020-01-01T00:00:00+03:00"),
                    ("через час", ts(3600)), ("без пояса", ts()[:19]), ("время «x»", "x")):
        h.approve(f"{t} merge-approve latark/agent-kit#7 {sha}", fresh=True)
        merge_case(f"ядро: строка «{name}» — отказ", h.pre(cmd, pdir=kit), False, CORE + ": PR задевает")
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {sha}", fresh=True)
    # строка не снимает остального шлюза: другой head у PR, нет «принять»
    h.gh(["plugins/guard/hooks/merge_gate.py"], head=other)
    merge_case("ядро: строка есть, но PR на другом коммите — отказ", h.pre(cmd, pdir=kit), False, "на другом коммите")
    h.gh(["plugins/guard/hooks/merge_gate.py"])
    shutil.rmtree(os.path.dirname(h.records))
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"))
    merge_case("ядро: строка есть, но нет «принять» argus — отказ", h.pre(cmd, pdir=kit), False, "нет «принять»")
    # симлинк вместо файла — согласия нет
    h.seed(rec("accept", "latark/agent-kit", 7, sha))
    real = h.j("approve-real.log")
    shutil.move(h.approve_path, real)
    os.symlink(real, h.approve_path)
    merge_case("ядро: merge-approve.log — симлинк — отказ", h.pre(cmd, pdir=kit), False, CORE + ": PR задевает")
    # Touch ID снимает только Д3, а не проверки GitHub (слияние #79 и #88)
    os.remove(h.approve_path)
    shutil.move(real, h.approve_path)
    merge_case("ядро: строка merge-approve есть — снова проходит", h.pre(cmd, pdir=kit), True)
    h.ci([dict(AFFECTED, conclusion="FAILURE"), TRACES], name="agent-kit")
    merge_case("ядро: строка merge-approve есть, но проверка GitHub красная — отказ", h.pre(cmd, pdir=kit), False,
               "tests/affected красная")


CASES = [t_empty_tests, t_core_paths, t_wrapped_review_test, t_core_marketplace, t_canary_b1, t_reviewers, t_unresolved_test_words, t_vanishing_test_words, t_merge_hints, t_core_touchid, t_core_0598, t_version_bump_refused]


if __name__ == "__main__":
    sys.exit(main(CASES))
