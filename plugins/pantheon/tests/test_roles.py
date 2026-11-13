#!/usr/bin/env python3
"""pantheon roles build в два слоя (metis-0182): общие шаблоны плагина и личный слой ~/.claude/agents.

Запуск: python3 -I plugins/pantheon/tests/test_roles.py  (код выхода 0 — все прошли)
Подменены HOME, PANTHEON_HOME, PANTHEON_STATE и папка ролей плагина (PANTHEON_PLUGIN_ROLES): настоящие
~/.claude/agents и папка плагина не трогаются. Проверяет: роль только из плагина, личный шаблон и личная часть
перекрывают общие, подстановки [person] (значение, пустое — строка выпала, не по образцу — ошибка и файл не записан),
roles_newest и пересборку domains build по правке в плагине, direction check по действующей части имён.
"""
import json
import os
import re
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import time
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="roles-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


REG = ('[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\n'
       'does = "Демо"\ndoes_not = "Чужое — соседям"\nexamples = ["раз", "два", "три"]\n')


def check_longrun(out_real, devs, flat):
    """metis-0905: долгие команды субагентов — в фоне, итог — уведомлением о конце; лиды не принимают
    промежуточное уведомление за отчёт."""
    # metis-0905: /clear у запустившего обрывает Bash субагента на переднем плане (137), фоновый — нет: долгие команды
    # (тесты, heavy, мутанты, run-tests.py) — run_in_background и ожидание уведомления о конце, а не Monitor и не опрос
    longrun = ("## Долгие команды — в фоне (metis-0905)", "обрывает твою команду Bash на переднем плане (код 137)",
               "запускай в Bash с `run_in_background: true`",
               "своё `> <файл>` не нужно: Stop-хук разработчика считает перенаправление правкой", "закончи ход одной строкой «жду итога <ID>: <что идёт>»",
               "Это не отчёт: отчёт пишешь после итога", "«completed (exit code 0)» или «failed with exit code N»",
               "Оно будит тебя и после /clear у запустившего", "Файл вывода в цикле не опрашивай",
               "`sleep` и Monitor ради одного итога не ставь", "В фон уводи только команду, которая кончится сама",
               "`pantheon review test|accept|reject|talos` — только на переднем плане",
               "Долгий набор для записи — `pantheon outside test --wait 590`, его можно в фоне",
               "лог до уведомления не читай",
               "Пока итога нет, хук возвращает тебя «дождись итога» в общем счёте возвратов")
    for f in devs + ["argus.tmpl", "codex-dev.tmpl", "talos.tmpl"]:
        text = " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split())
        miss = [x for x in longrun if x not in text]
        check(f"{f[:-5]}: долгие команды — в фоне, итог — уведомлением, записи шлюза — на переднем плане (metis-0905)"
              + (f"; нет: {miss}" if miss else ""), not miss)
        check(f"{f[:-5]}: старого «Monitor с условием, а не конец хода со словом «жду»» нет (metis-0905)",
              "Monitor с условием" not in text and "Monitor-ом с условием" not in text and "словом «жду»" not in text
              and "Monitor или цикл `until`" not in text and "Monitor-ом или циклом `until`" not in text)
    for f in devs:
        text = " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split())
        check(f"{f[:-5]}: outside test и узкие тесты дольше минуты — в фоне, не «Bash не в фоне, timeout 600000» (metis-0905)",
              "`pantheon outside test --wait 590` — в фоне (раздел «Долгие команды»)" in text
              and "дольше минуты — тоже в фоне" in text and "Bash не в фоне, с timeout 600000" not in text
              and "соседние) гоняй на переднем плане" not in text)
    # лиды (merge.part): промежуточное уведомление «ждёт свою фоновую работу» — не отчёт, TaskStop не делать;
    # долгий набор для записи шлюза — outside test, его можно в фоне (metis-0905)
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        check(f"{f}: «is waiting on its own background work» — не отчёт, TaskStop не делать; outside test в фоне (metis-0905)",
              "Уведомление «is waiting on its own background work» (в нём «may be interim») — не отчёт" in flat[f]
              and "`TaskStop` ему не делай и работу не перепоручай" in flat[f]
              and "его можно в фоне: запись пишет плановый проход, и /clear её не теряет" in flat[f])


def check_plan10(texts, flat, callers):
    """План 1.0, шаг 0 (решения 10.11, «да» владельца 12.11): модель и effort ролей по таблице раздела 6а,
    повторный круг argus (оба head, Р1, затронутые тесты), оценки в единицах конвейера, effort dev-opus и
    prometheus у тех, кто зовёт."""
    plan6a = {"argus.md": ("opus", "medium"), "dev-opus.md": ("opus", "medium"), "chiron.md": ("opus", "medium"),
              "workshop.md": ("opus", "medium"), "prometheus.md": ("sonnet", "medium"), "momus.md": ("fable", "medium")}
    for f, (model, effort) in plan6a.items():
        fm = texts.get(f, "").split("---")[1] if texts.get(f, "").count("---") >= 2 else ""
        check(f"{f}: в шапке model: {model} и effort: {effort} (план 1.0, раздел 6а)",
              f"\nmodel: {model}\n" in fm and f"\neffort: {effort}\n" in fm)
    # argus на повторном круге (план 1.0, шаг 0): оба head в поручении, новый сверяет с PR; Р1; затронутые тесты
    argus_rules = (
        ("повторный круг: прошлый и новый head, новый сверен с headRefOid PR",
         "Поручение «Повторный круг: прошлый head <sha>, новый head <sha>, правка: <файл:строка>, вернули: "
         "<agent8>/<сессия8>, …» — автор поправил код после возврата. Новый head из поручения сверь с `gh pr view <N> "
         "-R <owner/repo> --json headRefOid`: не совпал — head ушёл после поручения, проверяешь текущий и пишешь "
         "расхождение в отчёт."),
        ("Р1: со второго круга новые Д и С не возвращают, «вернуть» по коду — только при Б",
         "Со второго круга (повторный круг, узкий повтор, круг 3+) новые Д и С PR не возвращают (Р1, план 1.0, "
         "12.11): «вернуть» по коду — только при Б. Новые Д — в список «Долг», С — строкой в отчёт; вердикт по ним "
         "не меняется."),
        ("тесты — затронутые (--affected), на повторе база — прошлый head",
         "прогони через `heavy` затронутые тесты проекта, а не все (план 1.0, 12.11)"),
        ("на повторе база --affected — прошлый head", "На повторном круге и узком повторе в agent-kit база — прошлый "
         "head: `--affected --base <прошлый head>`."))
    for label, rule in argus_rules:
        check(f"argus.md: {label}", rule in flat.get("argus.md", ""))
    # metis-0784: старого «в ядре повторный круг всегда полный» и дельты через merge-tree B, T в повторном круге нет
    check("argus.md: нет «в ядре повторный круг — полный» и дельты повторного круга через «шаг 3 узкого повтора»",
          "В ядре повторный круг — полный" not in flat.get("argus.md", "")
          and "3. Дельта — шаг 3 узкого повтора" not in flat.get("argus.md", "") and "argus.md" in flat)
    # оценки в единицах конвейера (план 1.0, раздел 4в): у всех, кто планирует — Зевс, координатор, лиды
    estimate = ("## Оценки — в единицах конвейера, не в часах (план 1.0, раздел 4в)",
                "- число задач, PR, кругов argus, окон Touch ID и заявок тестов;",
                "- % недельного лимита — из стоимости похожих задач по истории (`pantheon metrics summary`, "
                "`metrics/tasks.jsonl`);",
                "- диапазоном P50–P90 по прошлым похожим пачкам, а не точкой и не чутьём.",
                "«N часов работы», «займёт день» не пиши.")
    for f in ("hq.md", "domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        miss = [x for x in estimate if x not in " ".join(texts.get(f, "").split())]
        check(f"{f}: оценки — в единицах конвейера, не в часах" + (f" (нет: {miss})" if miss else ""), not miss)
    check("hephaestus: оценка в плане эпика — в единицах конвейера, не в часах",
          "оценка — в единицах конвейера (раздел «Оценки» ниже), не в часах" in flat.get("hephaestus-demo.md", ""))
    # effort разработчика и исследователя: dev-opus medium, после красной узкой записи или Б argus — high
    # ([metis-plan-devopus], decisions.md; Д5 argus #426), глубокая тема — Fable
    dev_effort = ("dev-opus — Opus medium из файла роли; после красной узкой записи тестов или блокера (Б) argus "
                  "следующий заход — dev-opus с `effort: \"high\"` (решение [metis-plan-devopus]), выше high не "
                  "поднимай. prometheus — Sonnet medium из файла роли; глубокая тема (много источников, вывод меняет "
                  "решение владельца) — вызов с `model: \"fable\"`.")
    miss = [f for f in callers if dev_effort not in flat.get(f, "")]
    check("лиды, координатор и Зевс: dev-opus medium, high — после красной узкой записи или Б argus; prometheus "
          "Sonnet, глубокая тема — Fable" + (f" (нет у: {miss})" if miss else ""), not miss)
    triage = ("high и после красной узкой записи или Б argus при любом классе ([metis-plan-devopus]). Выше high не "
              "поднимай (план 1.0, раздел 6а).")
    triage4 = ("4. трудная логика (гонки, безопасность, алгоритм) → dev-opus с `effort: \"high\"` один раз на задачу, "
               "не при лимите владельца на исходе;")
    miss = [f for f in ("hephaestus-demo.md", "apollo-demo.md")
            if triage not in flat.get(f, "") or triage4 not in flat.get(f, "")]
    check("лиды: разбор провала — трудная логика на dev-opus high, high и после красной записи или Б argus"
          + (f" (нет у: {miss})" if miss else ""), not miss)
    miss = [f for f in ("hq.md", "domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md", "argus.md")
            if "xhigh" in texts.get(f, "")]
    check("Зевс, координатор, лиды и argus: нет effort xhigh (выше high не поднимать, план 1.0, раздел 6а)"
          + (f" (есть у: {miss})" if miss else ""), not miss and "hq.md" in texts)
    # запись тестов лида: вне ядра — узкая outside test --affected (metis-0734), полный — ядро и пачки (Д4 argus #426)
    rec = ("PR вне ядра — узкая запись: `pantheon outside test --affected --sha <head> --wait 590` (metis-0734), если "
           "проверка в `.pantheon-verify` — `run-tests.py`; полный набор — для PR ядра и пачек.")
    miss = [f for f in callers if f != "hq.md" and rec not in flat.get(f, "")]
    check("координатор и лиды: запись тестов вне ядра — outside test --affected, полный — ядро и пачки"
          + (f" (нет у: {miss})" if miss else ""), not miss)
    # hq: prometheus на глубокой теме — Fable, исключения Fable названы (второй argus #426, Д1)
    hq_rules = ("глубокая тема (много источников, вывод меняет решение владельца) — вызов prometheus с "
                "`model: \"fable\"` (решение 10.11);",
                "Fable — решения владельца 10.11: momus на Fable medium из файла роли и prometheus на глубокой теме — "
                "вызов с `model: \"fable\"`; другой роли — только решением владельца.")
    miss = [x[:50] for x in hq_rules if x not in flat.get("hq.md", "")]
    check("hq.md: prometheus на глубокой теме — Fable, исключения Fable — momus и prometheus"
          + (f" (нет: {miss})" if miss else ""), not miss)
    # hq: Fable не «после двух неудач Opus xhigh» — выше high не поднимать (план 1.0, раздел 6а; Д6 argus #426)
    hq = flat.get("hq.md", "")
    check("hq.md: выше high не поднимать, Fable — momus и глубокая тема prometheus, нет xhigh",
          "xhigh" not in hq and "Effort выше high не поднимай (план 1.0, раздел 6а): не справляется — сначала "
          "проверка своей работы, потом effort на ступень выше, потом модель старше." in hq
          and "другой роли — только решением владельца." in hq)
    # повторный круг (metis-0784, argus #426): нет ответа delta — полный; в ядре дельта — только у того же вызова;
    # --affected у outside test — только при run-tests.py в .pantheon-verify (Б1)
    a = flat.get("argus.md", "")
    for label, rule in (
            ("delta не ответила — круг полный", "Команда не ответила (сбой gh, команды ещё нет) — круг полный."),
            ("в ядре дельта — только у того же вызова, замена — полный",
             "В ядре дельта-круг — только у того же вызова, что вернул: позвали новым argus вместо вернувшего — круг "
             "в ядре полный."),
            ("тесты — строка dev: .pantheon-verify, в agent-kit run-tests.py --affected от origin/main",
             "строка `dev:` файла `.pantheon-verify` (в agent-kit — `run-tests.py --affected`, база `origin/main`), "
             "без неё — первая строка или `heavy pnpm test`."),
            ("accept с кодом 1 — «head не готов», лиду — подать тесты на head",
             "Тогда в отчёте — «head не готов: <причина из вывода>», лиду — подать тесты на head; «принять» без "
             "записи не считается."),
            ("outside test --affected — только при run-tests.py в .pantheon-verify",
             "Нужен порт или сокет — `pantheon outside test --wait 590`; `--affected` к нему добавляй, только если "
             "проверка в `.pantheon-verify` — `run-tests.py`: с другой командой заявка с `--affected` откажет.")):
        check(f"argus.md: {label}", rule in a)
    check("argus.md: нет `pantheon outside test --affected` без условия", "outside test --affected --wait" not in a)
    lead = ("Команда не ответила (сбой gh, команды ещё нет) — круг полный. В ядре дельта-круг ведёт только тот же "
            "вернувший вызов: новый argus вместо него (вызов не продолжить) ведёт полный круг.",
            "Вне ядра это не повод для полного круга: отчёт прежнего argus лежит в его транскрипте; в ядре новый argus "
            "ведёт полный круг (выше).")
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        miss = [x[:40] for x in lead if x not in flat.get(f, "")]
        check(f"{f}: повторный круг — delta не ответила или замена в ядре — полный"
              + (f" (нет: {miss})" if miss else ""), not miss)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="roles-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    plugin = os.path.join(tmp, "plugin", "roles")
    agents = os.path.join(tmp, ".claude", "agents")
    os.makedirs(os.path.join(tmp, "projects", "demo"))
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_PLUGIN_ROLES": plugin, "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp")}
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])
    reg = os.path.join(home, "directions.toml")
    write(reg, REG)

    def run(*args):
        return subprocess.run([PY311, "-I", RUN_PY, *args], env=env, capture_output=True, text=True, timeout=60)

    def py(code):
        """Код с модулем pantheon под именем m, в окружении теста (константы берутся из него при загрузке)."""
        boot = ("import importlib.util\n"
                f"spec = importlib.util.spec_from_file_location('pantheon_t', {LIB!r})\n"
                "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n" + code)
        return subprocess.run([PY311, "-I", "-c", boot], env=env, capture_output=True, text=True, timeout=60)

    # общий слой (плагин)
    write(os.path.join(plugin, "_parts", "report.part"), "## Отчёт\n\nОтчёт: общий\n")
    write(os.path.join(plugin, "_parts", "finding.part"), "Находка: общая\n")
    write(os.path.join(plugin, "_parts", "qmd.part"),
          "Системные коллекции: knowledge, pantheon.\nКоллекции этого Пантеона: {{qmd_collections}}.\nКонец qmd.\n")
    write(os.path.join(plugin, "_parts", "names.part"), "- он: Зевс (штаб, zeus)\n")
    write(os.path.join(plugin, "argus.tmpl"), "---\nname: argus\n---\n\nРевьюер.\n{{> report}}\n{{> qmd}}\n")
    write(os.path.join(plugin, "clio.tmpl"),
          "---\nname: clio\n---\n\nБиблиотекарь. Браузер владельца тебе недоступен.\n"
          "Браузер владельца: {{browser}}.\nДальше.\n{{> finding}}\n")
    write(os.path.join(plugin, "talos.tmpl"), "---\nname: talos\n---\n\nОбщий talos.\n")
    # личный слой
    write(os.path.join(agents, "talos.tmpl"), "---\nname: talos\n---\n\nЛичный talos.\n{{> report}}\n")
    write(os.path.join(agents, "_parts", "report.part"), "## Отчёт\n\nОтчёт: личный\n")
    write(os.path.join(agents, "iris.tmpl"), "---\nname: iris\n---\n\nТолько личная.\n")

    r = run("roles", "build")
    clio, argus, talos = (read(os.path.join(agents, f + ".md")) for f in ("clio", "argus", "talos"))
    check("роль только из плагина собрана: метка, часть плагина, нет {{",
          r.returncode == 0 and re.match(r"---\nname: clio\ndisallowedTools: [\w, -]+\n---\n<!-- собрано pantheon roles build из clio.tmpl", clio)
          and "Находка: общая" in clio and "{{" not in clio)
    check("личный шаблон перекрывает общий по имени", "Личный talos" in talos and "Общий talos" not in talos)
    check("личная часть перекрывает общую — и в роли из плагина, и в личной",
          "Отчёт: личный" in argus and "Отчёт: общий" not in argus and "Отчёт: личный" in talos)
    check("роль только из личного слоя собрана", "Только личная" in read(os.path.join(agents, "iris.md")))
    check("нет [person] — строки с {{browser}} и {{qmd_collections}} выпали целиком, соседние на месте",
          "Браузер владельца:" not in clio and "Библиотекарь. Браузер владельца тебе недоступен.\nДальше.\n" in clio
          and "Коллекции этого Пантеона" not in argus
          and "Системные коллекции: knowledge, pantheon.\nКонец qmd." in argus and "{{" not in argus)

    write(reg, REG + '[person]\nqmd_collections = ["legal", "corpus (лекции)"]\n'
                     'browser = "Nova — демон CDP 127.0.0.1:9400"\n')
    r = run("roles", "build")
    clio, argus = read(os.path.join(agents, "clio.md")), read(os.path.join(agents, "argus.md"))
    check("[person] подставлен: коллекции через запятую, браузер одной строкой",
          r.returncode == 0 and "Коллекции этого Пантеона: legal, corpus (лекции).\n" in argus
          and "Браузер владельца: Nova — демон CDP 127.0.0.1:9400.\nДальше." in clio)
    write(reg, REG + '[person]\nqmd_collections = ["", " "]\nbrowser = "  "\n')
    run("roles", "build")
    check("[person] с пустыми значениями — строки выпали, как без раздела",
          "Браузер владельца:" not in read(os.path.join(agents, "clio.md"))
          and "Коллекции этого Пантеона" not in read(os.path.join(agents, "argus.md")))

    # плохие значения: роль с этой подстановкой не собрана (проба — файла нет; живая — старая версия осталась)
    write(reg, REG + '[person]\nbrowser = "Nova — демон"\n')
    run("roles", "build")
    good_clio = read(os.path.join(agents, "clio.md"))
    bad = [('browser = "x\\nhooks: y"', "clio"), ('browser = "a {{b}}"', "clio"), ('browser = "a `rm` b"', "clio"),
           ('browser = "a <script> b"', "clio"), ('browser = "a --- b"', "clio"), ('browser = "' + "a" * 300 + '"', "clio"),
           ("browser = 5", "clio"), ('qmd_collections = ["ok", "x\\ny"]', "argus"),
           ('qmd_collections = ["{{x}}"]', "argus"), ('qmd_collections = "legal"', "argus")]
    for i, (line, role) in enumerate(bad):
        write(reg, REG + "[person]\n" + line + "\n")
        out = os.path.join(tmp, f"probe-{i}")
        r = run("roles", "build", "--out", out)
        other = "argus" if role == "clio" else "clio"
        check(f"[person] {line[:40]!r} — ошибка, {role}.md не записан, {other}.md собран",
              r.returncode == 0 and "не по образцу" in r.stderr and not os.path.exists(os.path.join(out, role + ".md"))
              and os.path.exists(os.path.join(out, other + ".md")))
    write(reg, REG + '[person]\nbrowser = "x\\ny"\n')
    r = run("roles", "build")
    check("плохое значение в живой сборке — старая версия роли осталась, тревога в stderr",
          good_clio and read(os.path.join(agents, "clio.md")) == good_clio and "не по образцу" in r.stderr)
    # лид: старая версия остаётся и при ошибке подстановки в шаблоне лида, и при плохом project направления
    write(os.path.join(plugin, "hephaestus.tmpl"),
          "---\nname: hephaestus-{{short}}\n---\n\nЛид {{direction}} ({{project}}).\nБраузер: {{browser}}.\nКонец.\n")
    lead_reg = REG.replace('examples', 'leads = ["hephaestus"]\nexamples')
    write(reg, lead_reg)
    run("roles", "build")
    lead = os.path.join(agents, "hephaestus-demo.md")
    good_lead = read(lead)
    write(reg, lead_reg + '[person]\nbrowser = "x\\ny"\n')
    r = run("roles", "build")
    check("лид: плохое значение [person] — старая версия лида осталась",
          "Лид iris-demo (demo)" in good_lead and "Браузер:" not in good_lead and read(lead) == good_lead
          and "не по образцу" in r.stderr)
    write(reg, lead_reg.replace('project = "demo"', 'project = "x\\ny"'))
    r = run("roles", "build")
    check("лид: project не по образцу — старая версия лида осталась", read(lead) == good_lead and "не по образцу" in r.stderr)
    os.remove(os.path.join(plugin, "hephaestus.tmpl"))
    write(reg, REG)
    run("roles", "build")
    check("лид: шаблон убран — собранный лид убран", not os.path.exists(lead))
    write(reg, 'person = "Nova"\n' + REG)
    out = os.path.join(tmp, "probe-table")
    r = run("roles", "build", "--out", out)
    check("person не таблица — роли с подстановками не собраны, остальные собраны",
          "не таблица" in r.stderr and not os.path.exists(os.path.join(out, "clio.md"))
          and not os.path.exists(os.path.join(out, "argus.md")) and os.path.exists(os.path.join(out, "talos.md")))
    # подстановка [person] в шапке — ошибка при любом значении: хуки шапки идут вне песочницы, а образец значений
    # пропускает кавычки, «;» и «#». Личный шаблон (его может править тот, кто правит реестр) и живая сборка
    momus_t, momus = os.path.join(agents, "momus.tmpl"), os.path.join(agents, "momus.md")
    write(reg, REG)
    write(momus_t, "---\nname: momus\nhooks:\n  Stop:\n    - command: echo ok\n---\n\nТело.\n")
    run("roles", "build")
    good_momus = read(momus)
    write(momus_t, '---\nname: momus\nhooks:\n  Stop:\n    - command: echo "{{browser}}"\n---\n\nТело.\n')
    for label, extra in (("непустое", "[person]\nbrowser = 'x\"; touch pwn; echo \"a: b #c'\n"), ("пустое", "")):
        write(reg, REG + extra)
        r = run("roles", "build")
        check(f"[person] в строке шапки, значение {label} — роль не собрана, ошибка названа, прежний файл цел",
              "echo ok" in good_momus and read(momus) == good_momus and "touch pwn" not in read(momus)
              and "в шапке роли запрещена: {{browser}}" in r.stderr)
    write(reg, REG)
    os.remove(momus_t)
    run("roles", "build")

    # roles_newest и пересборка domains build по правке в плагине
    future = time.time() + 10_000
    for sub in ("_parts/finding.part", "clio.tmpl"):
        p = os.path.join(plugin, sub)
        os.utime(p, (future, future))
        r = py("print(m.roles_newest())")
        check(f"roles_newest видит правку в плагине: {sub}", r.returncode == 0 and abs(float(r.stdout) - future) < 1)
        future += 10_000
    r = run("domains", "build")
    dj = os.path.join(state, "domains.json")
    check("domains build собирает и роли из плагина", r.returncode == 0 and os.path.isfile(dj)
          and "Находка: общая" in read(os.path.join(agents, "clio.md")))
    d = json.load(open(dj))
    d["built_ts"] = future + 10_000  # сборка «позже» всех правок
    write(dj, json.dumps(d))
    finding = os.path.join(plugin, "_parts", "finding.part")
    write(finding, "Находка: новая\n")
    os.utime(finding, (future, future))
    py("m.domains_build(if_changed=True)")
    check("domains build --if-changed: правка в плагине старше сборки — пересборки нет",
          "Находка: общая" in read(os.path.join(agents, "clio.md")))
    os.utime(finding, (future + 20_000, future + 20_000))
    r = py("m.domains_build(if_changed=True)")
    check("domains build --if-changed: часть плагина новее сборки — роли пересобраны",
          r.returncode == 0 and "Находка: новая" in read(os.path.join(agents, "clio.md")))

    # direction check: бог — в действующей части имён (личная, если есть, иначе плагина)
    def god_line():
        out = run("direction", "check", "iris-demo").stdout
        return next((ln for ln in out.splitlines() if "бог направления" in ln), "")
    os.remove(os.path.join(agents, "_parts", "report.part"))
    write(os.path.join(plugin, "_parts", "names.part"), "- она: Ирида (iris-demo)\n")
    check("direction check: личной части имён нет — бог найден в части плагина",
          god_line().startswith("готово  бог направления"))
    write(os.path.join(plugin, "_parts", "names.part"), "- он: Зевс (штаб, zeus)\n")
    line = god_line()
    check("direction check: ни в личной, ни в плагине — НЕТ и подсказка скопировать общую",
          line.startswith("НЕТ     бог направления") and "скопировать общую" in line)
    write(os.path.join(agents, "_parts", "names.part"), "- она: Ирида (iris-demo)\n")
    check("direction check: личная часть имён есть — бог найден в ней", god_line().startswith("готово  бог направления"))
    write(os.path.join(plugin, "_parts", "names.part"), "- она: Ирида (iris-demo)\n")
    write(os.path.join(agents, "_parts", "names.part"), "- он: Зевс (штаб, zeus)\n")
    check("direction check: личная перекрывает целиком — бог только в плагине не засчитан",
          god_line().startswith("НЕТ     бог направления"))

    # настоящие общие шаблоны плагина: личного слоя нет, сборка в --out. ROLES_PROBE_OUT — оставить итог для глаз
    real = os.path.join(os.path.dirname(os.path.dirname(LIB)), "roles")
    probe = os.environ.get("ROLES_PROBE_OUT") or os.path.join(tmp, "probe-real")
    home2 = os.path.join(tmp, "home2")
    os.makedirs(home2)
    env.update({"HOME": home2, "PANTHEON_HOME": os.path.join(home2, "ai", "pantheon"), "PANTHEON_PLUGIN_ROLES": real})
    reg2 = os.path.join(env["PANTHEON_HOME"], "directions.toml")
    lead_reg = REG.replace('examples', 'leads = ["hephaestus", "apollo"]\nexamples')
    tmpls = sorted(f[:-5] for f in os.listdir(real) if f.endswith(".tmpl"))
    owner_lines = ("Браузер владельца у этого Пантеона:", "Коллекции направлений:")
    for label, extra in (("без [person]", ""), ("с [person]", '[person]\nqmd_collections = ["legal", "docs (справка)"]\n'
                                                             'browser = "Nova — демон CDP 127.0.0.1:9400"\n')):
        write(reg2, lead_reg + extra)
        out = os.path.join(probe, "plain" if not extra else "person")
        r = run("roles", "build", "--out", out)
        built = sorted(os.listdir(out)) if os.path.isdir(out) else []
        texts = {f: read(os.path.join(out, f)) for f in built}
        # длинные редкие порядки вынесены в roles/_ref (metis-0386): роль называет файл, текст правил проверяем вместе
        # с ним; ссылка на несуществующий файл _ref — красный
        raw_texts = dict(texts)
        for f in list(texts):
            for m in re.finditer(r"roles/_ref/([\w.-]+\.md)", texts[f]):
                rp = os.path.join(real, "_ref", m.group(1))
                texts[f] += "\n" + (read(rp) if os.path.isfile(rp) else "")
        want = {t + ".md" for t in tmpls if t not in ("hephaestus", "apollo")} | {"hephaestus-demo.md", "apollo-demo.md"}
        check(f"общие шаблоны плагина {label}: собраны все роли, без ошибок, нет {{{{",
              r.returncode == 0 and not r.stderr.strip() and want <= set(built)
              and not any("{{" in t for t in texts.values()))
        has = {ln for t in texts.values() for ln in owner_lines if ln in t}
        check(f"общие шаблоны плагина {label}: строки о браузере и коллекциях "
              + ("выпали" if not extra else "подставлены"),
              not has if not extra else (has == set(owner_lines)
                                         and "Коллекции направлений: legal, docs (справка)." in texts["argus.md"]))
    check("координатор: в приёмке ночи есть шаг pantheon task set <id> --acceptance принято|вернуть|к владельцу",
          "pantheon task set <id> --acceptance принято|вернуть|к владельцу" in texts.get("domain-coordinator.md", ""))
    check("координатор: acceptance с --note-вердиктом и для своих/ядра/спорных только после «принять» Зевса",
          all(x in texts.get("domain-coordinator.md", "") for x in (
              '--note "<вердикт: файл ревью, запись шлюза или ответ Зевса>"',
              "поле им ставь только после «принять» Зевса, до этого оставь пустым")))
    # постоянный контекст ролей (metis-0386): длинные редкие порядки — в roles/_ref, роль называет файл и не держит текст
    refs = sorted(os.listdir(os.path.join(real, "_ref")))
    named = {m.group(1) for t in raw_texts.values() for m in re.finditer(r"roles/_ref/([\w.-]+\.md)", t)}
    check("roles/_ref: каждый файл назван хотя бы в одной роли, каждое имя в ролях — существующий файл",
          named == set(refs) and bool(refs))
    for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md"):
        check(f"{f}: «Повторный круг» и «Находки ревью: Б, Д, С» не в роли, а в _ref/merge-rounds.md; ссылка на файл есть",
              "Повторный круг после возврата (metis-0420)" not in raw_texts[f]
              and "Находки ревью: Б, Д, С" not in raw_texts[f] and "roles/_ref/merge-rounds.md" in raw_texts[f])
    check("координатор: порядок приёмки ночи — в _ref/night-accept.md, в роли только ссылка",
          "Итог по каждой задаче ночной пачки" not in raw_texts["domain-coordinator.md"]
          and "roles/_ref/night-accept.md" in raw_texts["domain-coordinator.md"])
    check("apollo: навык frontend-design не предзагружается шапкой (skills:), вызывается по требованию",
          re.search(r"^skills:", raw_texts["apollo-demo.md"].split("---")[1], re.M) is None
          and "frontend-design:frontend-design` (Skill)" in raw_texts["apollo-demo.md"])
    # размер координатора вырос по двум причинам: metis-0271 (+~400 — правила из decisions.md: findings, /clear между PR,
    # модель угроз, «решение внесено, только когда оно в роли»; дубли сжаты) и metis-0665 (+100 — строка «перед раздачей —
    # pantheon task overlap»; у лида уложилась в прежний потолок, лидов потолок не поднят)
    # metis-0653: +~450 — TaskStop после отчёта субагента (merge.part) и «ждать на переднем плане» (persist.part)
    # metis-0832: +~430 — раздел handoff.part «отказ — передай тому, кто умеет; владельцу только «да/нет»» (с [person]:
    # координатор 31546, лид 24367)
    # metis-0905: +~430 — merge.part (промежуточное уведомление субагента — не отчёт; outside test для записи — в фоне)
    # и persist.part (своя фоновая команда — ждать уведомления о конце)
    # план 1.0, шаг 0 (12.11): +~1300 — оценки в единицах конвейера и effort dev-opus и prometheus (brief.part), оба
    # head, «вернули» и Р1 в поручении повторного круга (merge.part); metis-0784: +~210 — `pantheon review delta` перед
    # повторным кругом и accept с кодом 1 без тестов и CI (merge.part), план 1.0, пачка 0; argus #426 (план 1.0):
    # +~350/+~440 — код 1 у accept только без тестов и CI, узкая запись вне ядра (merge.part), high после красной
    # записи или Б (brief, triage)
    check("размер роли после выноса: координатор и лиды не больше потолка (знаков)",
          len(raw_texts["domain-coordinator.md"]) <= 34850 and len(raw_texts["hephaestus-demo.md"]) <= 29000)  # metis-1115: +~230/+~340 (merge.part и hephaestus: строка ci: — тесты в CI); metis-0951: +150 (packs и window_launch в ядре merge.part); metis-0900: +244 (external.part «жду вас в окне»); metis-0832: +400/+500 (handoff.part, [person]); metis-0859: +~1150 (triage.part); metis-0858: +~150 (review_rules.py, answers.py в ядре merge.part)
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        check(f"{f}: перед раздачей — pantheon task overlap, очередь или ветка от ветки PR, argus — только дельта (metis-0665)",
              all(x in " ".join(raw_texts[f].split()) for x in ("Перед раздачей — `pantheon task overlap <id>`",
                                                       "очередь или ветка от ветки PR", "argus — только дельта своего PR")))
    # самопроверка до сдачи (metis-0357): шесть пунктов и строка отчёта у разработчиков, требование в поручении лидов
    # сверка по тексту без переносов строк: пробелы схлопнуты, иначе перенос строки в шаблоне ломает поиск фразы
    flat = {f: " ".join(t.split()) for f, t in texts.items()}
    # dev-сервер на коммите PR (metis-0614): talos и разработчики не переключают ветку и не ставят зависимости сами
    check("talos: dev-сервер — outside serve --sha, без checkout --detach и pnpm install (metis-0614)",
          "outside serve --sha" in flat.get("talos.md", "") and "checkout --detach" not in flat.get("talos.md", "")
          and "pnpm install" not in flat.get("talos.md", "") and "talos.md" in flat)
    for f in ("dev-opus.md", "dev-sonnet.md", "dev-haiku.md"):
        check(f"{f}: dev.part — outside serve [--sha …] [--app …], ветку не переключать, зависимости не ставить (metis-0614)",
              "outside serve [--sha <коммит>] [--app ИМЯ]" in flat.get(f, "") and "pnpm install" not in flat.get(f, ""))
    # тела всех шести пунктов и формат строки отчёта с доказательством (review-0357-argus-d): мутант любого убит
    selfcheck = (
        "## Самопроверка до сдачи",
        "почти всегда по одному из этих пунктов. Пройди их до отчёта:",
        "1. Кто ещё вызывает правку: поиск по имени функции, команды, файла — окна ролей, плановый проход, хуки, службы.",
        "2. Сбой: код выхода не 0, причина видна в выводе последней строкой, сообщение не врёт о том, что записано.",
        "3. Тест падает на откате правки, и мутант каждой новой ветки убит (`1` → `0`, условие → `True`).",
        "4. Обходы через соседние пути: окружение (`PYTHONEXECUTABLE`, `HOME`, `PATH`), другие входы и форматы, "
        "отрицание, пустое и нулевое значение.",
        "5. DOC-01: поведение поменялось — README компонента и шапка скрипта обновлены.",
        "6. Весь набор тестов проекта, а не только свой файл: все файлы `tests/` репозитория, включая соседние плагины. "
        "Основная ветка ушла вперёд — `git fetch`, прогон на временном слиянии с `origin/main` в отдельной копии "
        "(`git worktree add` во временную папку); в свою ветку её не сливай. Общей команды прогона нет — запусти "
        "циклом по всем файлам и сохрани в лог код каждого.",
        "В «Подробностях» отчёта — строка «Самопроверка:» по всем шести, у пункта одно из значений:",
        # формат доказательства пп. 2, 3, 6 (argus-e/f): сбой — не по зелёному прогону; у 3 откат и мутант, у 6 слияние с main
        "- «сделано (доказательство)». Пункт 2 — проба сбоя: «команда → код N (не 0), последняя строка вывода» или "
        "«тест сбоя файл:имя → мутант убит»; зелёный прогон для него не доказательство.",
        "Пункт 3 — нужны оба: «откат → <тест> красный; мутант файл:строка → убит тестом <тест>», мутант на каждую "
        "новую ветку; мутант выжил — в тестах дыра, пункт не сделан.",
        "Пункт 6 — «временное слияние с origin/main <sha>: команда → файлов F, всего N тестов, FAIL 0, код, путь к "
        "логу»; один свой файл — не пункт 6.",
        "Пункты 1, 4, 5 — команда поиска или проба и что нашла. Без доказательства пункт не сделан;",
        "- «не применимо (почему)» — причина обязательна. Пункты 3 и 6 «не применимо» — только если в диффе нет кода "
        "и тестов. Пункт 2 — только если в диффе нет новых и изменённых путей выхода и ошибок; в причине — команда "
        "поиска по диффу (`git diff <база>..HEAD | grep -nE 'exit|raise|throw|catch|except|die|return (-?[1-9]|false|False|null|nil)'`; "
        "для другого языка — свой шаблон путей выхода и ошибок) и что она нашла.")
    for f in ("dev-opus.md", "dev-sonnet.md", "dev-haiku.md", "codex-dev.md"):
        miss = [x for x in selfcheck if x not in flat.get(f, "")]
        check(f"{f}: часть selfcheck — тела шести пунктов, «сделано (доказательство)», «не применимо (почему)»"
              + (f" (нет: {miss})" if miss else ""), not miss)
    # проверка мутантом в dev.part (metis-0785): «убит», а не «покраснел»
    for f in ("dev-opus.md", "dev-sonnet.md", "dev-haiku.md"):
        check(f"{f}: dev.part — новый тест проверен мутантом, «тест его убил» (metis-0785)",
              "сломай проверяемое правило (мутант) и убедись, что тест его убил." in flat.get(f, ""))
    # доработка после /clear (metis-0602): новому исполнителю — отчёт прежнего, не с нуля
    brief = ("Доработка после /clear или перезапуска: прежнего исполнителя не продолжить (SendMessage: No transcript "
             "found) — новому дай его отчёт, а не начинай с нуля")
    for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md"):
        check(f"{f}: поручения — после /clear новому исполнителю отчёт прежнего (metis-0602)", brief in flat.get(f, ""))
    # проверка строки самопроверки до argus (metis-0366): лид, apollo и координатор без лида; три значения пункта;
    # порядок «сначала сам открой отчёт, потом argus»; у argus своей проверки строки нет (отчёт до него не доходит)
    three = "«сделано (доказательство)», «не применимо (причина)» или «по отчёту Codex: путь»"
    order = {"hephaestus-demo.md": ("сначала сам открой его отчёт", "Потом зови argus"),
             "apollo-demo.md": ("до вызова argus сам открой его отчёт", "argus не зови"),
             "domain-coordinator.md": ("до вызова argus сам открой его отчёт", "argus не зови")}
    for f, (first, then) in order.items():
        t = flat.get(f, "")
        want = (three, "строка «Самопроверка:» по шести пунктам", "codex-dev, пункты 2–4",
                "верни разработчику «открыто: самопроверка», argus не зови.", first, then)
        miss = [x for x in want if x not in t]
        ok = not miss and t.find(first) < t.find(then)
        check(f"{f}: сам открывает отчёт до вызова argus, три значения пункта, нет строки — возврат"
              + (f" (нет: {miss})" if miss else ""), ok)
    # разбор провала (metis-0859): шаг во всех лидах, строка причины у argus
    for f in ("hephaestus-demo.md", "apollo-demo.md"):
        t = " ".join(flat.get(f, "").split())
        miss = [x for x in ("## Разбор провала", "провал: <класс> — <довод>", "непонятная задача", "неверный подход",
                            "не хватило контекста", "трудная логика", "один раз на задачу", "Третий возврат argus")
                if x not in t]
        check(f"{f}: шаг «Разбор провала» с четырьмя классами и действиями (metis-0859)"
              + (f" (нет: {miss})" if miss else ""), not miss)
    check("argus: в «вернуть» строка «Причина (предположительно)» с четырьмя классами (metis-0859)",
          "Причина (предположительно): непонятная задача | неверный подход | не хватило контекста | трудная логика"
          in " ".join(flat.get("argus.md", "").split()))
    check("argus: правила «нет строки самопроверки — вернуть» нет (отчёт до argus не доходит)",
          "нет строки самопроверки" not in flat.get("argus.md", "")
          and "без строки «Самопроверка:»" not in flat.get("argus.md", ""))
    # страховка от зацикливания (metis-0419): maxTurns в шапке, поле работает у агентов плагина
    # (plugins-reference: «Plugin agents support … maxTurns»)
    for f, n in (("argus.md", 150), ("dev-haiku.md", 80), ("dev-sonnet.md", 150), ("dev-opus.md", 200),
                 ("hephaestus-demo.md", 300), ("apollo-demo.md", 300)):
        hd = texts.get(f, "").split("---")[1] if texts.get(f, "").count("---") >= 2 else ""
        got = [ln for ln in hd.splitlines() if ln.startswith("maxTurns:")]
        check(f"{f}: в шапке ровно одна строка maxTurns: {n}", got == [f"maxTurns: {n}"])
    # codex-dev код не правит (argus-a/b/d): пункты уходят Codex; сам — 1, 5 и 6 на временном слиянии; 2–4 —
    # «по отчёту Codex», только если там есть ответ, иначе «не сделано Codex» и второй запуск
    codex_self = ("Только допиши в конец «Не трогай:» со списком защищённых путей и шесть пунктов самопроверки — оба "
                  "из разделов ниже — с просьбой ответить в отчёте Codex по каждому пункту.",
                  "У тебя пункты выполняет Codex: они уходят в поручение (шаг 1), мутанта и правки кода сам не делаешь.",
                  "Сам сверяешь только то, что видно без правки: 1 — поиск вызывающих по имени (`grep`), 5 — README и "
                  "шапку в `git diff <база>..HEAD`, 6 — свой прогон проверки на временном слиянии с основной веткой в "
                  "отдельной копии (`git worktree add` во временную папку, слияние там), а не только на ветке.",
                  "Формат доказательства пунктов 2 и 6 — тот же, что выше.",
                  "По пунктам 2, 3 и 4 в строке «Самопроверка» — «по отчёту Codex: <путь к отчёту>», только если в "
                  "отчёте Codex есть ответ на этот пункт с доказательством.",
                  "Ответа нет — «не сделано Codex» и второй запуск Codex с этими пунктами (шаг 3: всего не больше двух); "
                  "после второго — статус «частично».")
    miss = [x for x in codex_self if x not in flat.get("codex-dev.md", "")]
    check("codex-dev.md: пункты — в поручение Codex, сам 1, 5 и 6 на временном слиянии, 2–4 «по отчёту Codex» при ответе"
          + (f" (нет: {miss})" if miss else ""),
          not miss and "Пункты сверяешь сам по итогу Codex" not in flat.get("codex-dev.md", ""))
    # сколько argus звать (metis-0393): правило по риску (владелец 24.10 02:22, metis-0401) и узкий повтор (#118 круг 3)
    # по одной проверке на правило: мутанта любой строки убивает ровно своя проверка
    lead_rules = (
        ("ядро — список один с шлюзом, два argus на Opus",
         "- Ядро — дифф трогает путь из списка «Ядро защит» выше. Список один, как у шлюза guard (`CORE_DIR` и "
         "`CORE_FILES` в `plugins/guard/hooks/merge_gate.py`; тест сверяет этот текст с кодом шлюза)."),
        # владелец 02.11 (metis-0271, В3): argus на Opus, model в вызове нет; план 1.0, раздел 6а (12.11): в файле
        # роли medium, первый argus ядра — с effort high, второй и вне ядра — без effort
        ("ядро — вызов без model, первый с effort high, второй без effort", "В PR ядра — два независимых argus на "
         "Opus: вызов без `model`; первого — с `effort: \"high\"`, второго — без `effort` (Opus и medium из файла "
         "роли)."),
        ("вне ядра — один argus на Opus без model и effort, второго не зови, метка не добавляет",
         "- Остальное, в том числе остальные «Защищённые пути» (`plugins/pantheon/roles/_parts/protected.part`) — один "
         "argus на Opus, вызов без `model` и без `effort` (Opus и medium из файла роли). Второго не зови: сложность "
         "задачи и метка «Сложная» этого не меняют."),
        # план 1.0, Р1 и шаг 0 (12.11): поручение повторного круга — оба head и «вернули»; со второго круга Д и С
        # PR не возвращают
        ("поручение повторного круга — прошлый и новый head и «вернули», Р1 со второго круга",
         "Поручение повторного круга называет прошлый и новый head и «вернули: <agent8>/<сессия8>, …» — всех argus, "
         "вернувших на прошлом head. Со второго круга новые Д и С PR не возвращают (Р1): «принять» с Д — сливай, Д "
         "— в задачи."),
        # владелец 02.11 (metis-0271, В1; metis-0669): PR на задачу; argus — при зелёном CI или записи тестов;
        # metis-0784: повторный круг — дельта или полный по `pantheon review delta`, и в ядре
        ("одна задача — один PR; одни файлы — одна ветка или очередь; ядро — пачка до ~400 строк",
         "Одна задача — один PR (владелец 02.11); задачи на одни файлы — одной веткой или в очередь за открытым PR, "
         "ядро — пачкой до ~400 строк диффа."),
        # отдельный пункт для любого PR, ядра тоже, а не хвост пункта «Остальное» (argus-252a Б1)
        # код 1 у accept — только без записи тестов и без зелёного CI; свежесть main — подсказка delta (Д4 argus #426)
        ("любой PR: argus — при зелёном CI или записи тестов, нет обоих — accept код 1, свежесть main — подсказка",
         "- Любой PR: argus — при зелёном CI или записи тестов шлюза на head (metis-0669): нет ни того, ни другого — "
         "`pantheon review accept` у argus выйдет с кодом 1 и «принять» не запишет. Полный круг — на свежем "
         "`origin/main`; отставание от base видит только `pantheon review delta`, и это подсказка, а не отказ accept."),
        ("повтор: перед повторным кругом review delta — дельта и в ядре, полный — на свежем base",
         "повтор — только при новом диффе; перед повторным кругом — `pantheon review delta <owner/repo> <N>`: "
         "«дельта» — argus смотрит только правку, и в ядре, «полный» — весь дифф на свежем base;"),
        ("второй (только ядро) не видит первого, строка «Второй argus»", "- Второй argus (только ядро) ищет только "
         "обходы и отчёта первого не видит. Принято, когда последний вердикт каждого позванного argus — «принять». "
         "Строка первого «Второй argus: нужен — ядро» — зови второго."),
        ("повтор только при новом диффе: шлюз переносит «принять» сам", "- Повтор — только при новом диффе. Подтянул "
         "main — сначала тесты на новом head и слияние: если собственный дифф PR тот же, шлюз переносит «принять» сам "
         "(README guard), argus не нужен."),
        ("узкий повтор — только по журналу шлюза: «вернуть 0», «принять» по числу argus, в ядре 2",
         "«вернуть 0», а «принять» не меньше числа argus круга (в ядре — два, по строке «для PR ядра»). Иначе — полный "
         "круг: слова лида и отчёты журнал не заменяют."),
        ("поручение без путей отчётов — argus берёт свой последний отчёт", "Поручение «Узкий повтор: прошлый head "
         "<sha>»: пути отчётов не называй — argus опирается на последний свой отчёт по этому PR."),
        ("узкий повтор ведёт тот же argus, дельта с merge-коммитами, нет диффа — нет повтора", "Его ведёт тот же argus, "
         "тем же вызовом через SendMessage (в ядре — оба), по дельте; дельту он сверяет вместе с merge-коммитами, тесты "
         "на новом head — запись шлюза, пункт 1 о шлюзе в разделе о слиянии твоей роли. Нового диффа нет (head тот же) — повтора нет, argus не зови."),
        ("вне ядра два круга формулировок — решает лид", "- Вне ядра: два круга подряд вернули только за формулировки, "
         "без бага, обхода и теста, — третьего полного круга не зови. Оставшиеся замечания по тексту решает лид или "
         "координатор и пишет решение в план эпика, у задачи без эпика — в её журнал."),
        ("путь «правка текста» с перечнем вернувших", "Текст поправил — поручение «Узкий повтор: прошлый head <sha>, "
         "правка текста: <файл:строка>, решение: <файл плана>, вернули: <agent8>/<сессия8>, …»."),
        ("путь «оставить» с перечнем вернувших, единственный повтор на том же head", "Решил оставить как есть — "
         "поручение «Узкий повтор: тот же head <sha>, решение: <файл плана>, вернули: <agent8>/<сессия8>, …» "
         "(единственный повтор на том же head: он снимает «вернуть» в журнале шлюза)."),
        ("в «вернули» — продолженные argus по 8 знаков, сверка с «reject» прошлого head", "В «вернули» — каждый argus, "
         "которого ты продолжил, по 8 знаков agent_id и сессии, как у вердикта в `pantheon review status`; argus "
         "сверит их с рецензентами «reject» на прошлом head."),
        ("все вернувшие — тем же вызовом, не продолжил одного — полный круг", "- Оба пути ведут все вернувшие argus, "
         "каждый — тем же вызовом через SendMessage: шлюз узнаёт argus по вызову, и «вернуть» прежнего вызова новый "
         "вызов не снимет. Исключение — путь «правка текста» (код другой), когда вызов не продолжить: новый argus сам "
         "достаёт отчёты прежних через `pantheon review report` (абзац «Вызов не продолжить»); путь «тот же head» — "
         "только прежние вызовы. Не продолжил хоть одного вернувшего и отчёта его нет — полный круг: на новом head "
         "шлюз прошлые «вернуть» держит. «Принять» другого argus снимает их, только если код отличается от кода, на котором вернули."),
        ("argus сам открывает отчёты двух кругов, не формулировка — полный круг", "argus сам открывает свои отчёты двух "
         "прошлых кругов. Замечание с багом, обходом, тестом или мутантом — не формулировка: он ставит «вернуть» с "
         "причиной «не формулировка — полный круг»."),
        ("в ядре формулировку не решает лид", "- В ядре формулировку не решает лид: текст ядра и есть правило. Новый "
         "head в ядре, кроме подтягивания main, проверяют оба argus: после возврата по коду — повторным кругом (ниже), "
         "иначе обычным кругом."),
        # повторный круг после возврата по коду (metis-0420, N1): тот же вызов, свой отчёт и дельта вместо всего диффа
        ("повторный круг: тот же вызов каждого argus прошлого круга, и принявшего", "- Повторный круг после возврата "
         "(metis-0420): автор поправил код, за который вернули, — продолжи тем же вызовом через SendMessage (или новым "
         "argus с `pantheon review report`, когда вызов не продолжить — ниже) каждого argus прошлого круга, в ядре — "
         "обоих, и того, кто принял: шлюз считает последний вердикт каждого argus на новом head."),
        # план 1.0, шаг 0 (12.11): прошлый и новый head — argus считает дельту по двум head
        ("повторный круг: поручение с прошлым и новым head и полем «вернули»", "Поручение «Повторный круг: прошлый "
         "head <sha>, новый head <sha>, правка: <файл:строка>, вернули: <agent8>/<сессия8>, …» — все три поля "
         "обязательны"),
        # Р1 (план 1.0, 12.11): со второго круга новые Д и С PR не возвращают
        ("Р1: со второго круга новые Д и С не возвращают, «принять» с Д — сливай", "- Со второго круга (повторный "
         "круг, узкий повтор, круг 3+) новые Д и С PR не возвращают (Р1, план 1.0, 12.11): argus ставит «вернуть» "
         "только при Б. «Принять» с новыми Д — сливай по правилам слияния, Д — в задачи; ради Д и С нового круга "
         "argus не зови."),
        ("повторный круг: дельта вместо диффа, выданное не повторяет", "argus берёт свой прошлый отчёт и дельту прошлый "
         "head → новый head, а не весь дифф; выданное не повторяет."),
        # metis-0784 (план 1.0, пачка 0): повторный круг узкий по дельте и в ядре, если review delta пишет «дельта»
        ("повторный круг: review delta решает — дельта и в ядре, иначе полный на свежем base",
         "- Какой повторный круг, решает `pantheon review delta <owner/repo> <N>` (metis-0784): вызови его из клона "
         "перед поручением. «Дельта» — прошлый head предок нового, дельта до 200 строк и не задевает ядро, файлы шлюза "
         "и сборку окон: круг узкий и в ядре, argus смотрит `git diff <прошлый head> <head>`. «Полный» — круг по всему "
         "диффу PR, и head не должен отставать от base: отстаёт — сначала rebase на свежий base."),
        ("повторный круг: ради дельты rebase не делать", "Ради дельты rebase не делай: он рвёт дельту, и круг снова "
         "полный."),
        ("повторный круг: полный по выводу review delta — весь дифф", "На полном круге по выводу `pantheon review "
         "delta` он читает весь дифф PR заново."),
        ("повторный круг: в «вернули» — все вернувшие на прошлом head, сверка с «reject», не совпало — «вернуть»",
         "В «вернули» — каждый argus, чей последний вердикт на прошлом head — «вернуть», по 8 знаков agent_id и "
         "сессии, как у вердикта в `pantheon review status`; argus сверит их с рецензентами «reject» на прошлом head; "
         "не совпало — он ставит «вернуть» с причиной «вернувший argus не продолжен — продолжи его», а не принимает "
         "сам."),
        ("повторный круг: шире или новые файлы — полный круг", "Дельта шире заявленной или "
         "задевает новые файлы — он сам ведёт полный круг. Тесты на новом head — запись шлюза, пункт 1 о шлюзе в разделе о слиянии твоей роли."),
        ("вызов не продолжить — новый argus с отчётом прежнего (review report), по дельте вне ядра (metis-0602)",
         "Вызов не продолжить (metis-0602): SendMessage отвечает «No transcript found» — после /clear, перезапуска, "
         "пауза дольше сессии. Вне ядра это не повод для полного круга"),
        ("вызов не продолжить: argus сам вызывает review report на каждую пару из «вернули», лид файлов не передаёт",
         "файлов и отчётов в поручении не передавай: argus сам вызывает `pantheon review report <owner/repo> <N> "
         "<agent8>/<сессия8>` на каждую пару из «вернули» (в ядре — и на принявшего, которого заменяет)"),
        ("вызов не продолжить: одно «принять» нового argus снимает все «вернуть»", "закрывает Б всех вернувших: его "
         "одно «принять» на другом коде снимает все их «вернуть»"),
        ("вызов не продолжить: полный круг только при отказе команды или чужом Head", "Любой отказ команды по любой "
         "паре (нет файла, нет отчёта, «Head:» не совпал) — полный круг"))
    lead_old = ("PR ядра проверяют два argus", "На PR ядра — полный круг теми же argus", "один узкий argus",
                "новый head проверяет узкий argus.", "Сложную задачу помечает в поручении лид или координатор",
                "или песочницу окон (`sandbox_build`, `window_rules.py`)", "- Остальное ядро —", "- Вне ядра —",
                "новый head проверяет узкий повтор, правка в поручении названа", "- Оба пути ведёт тот же argus",
                "и только если на прошлом head последний вердикт каждого argus — «принять»", "вернули: <M>",
                "M — «вернуть» из строки",
                "Новый head на защитах, кроме main и версии, проверяют оба argus обычным кругом.",
                # metis-0512: номер поднимает workflow release, а не PR — исключений «версии» в кругах больше нет
                "кроме main и версии", "или подъёма версии",
                # упрощение п. 9 (27.10): второй argus и Opus только в ядре, метка «Сложная» второго не добавляет, пути
                # отчётов в узком повторе не от лида, модель argus не «всегда Opus»
                "всегда два argus, при любом размере", "второй только на сложной задаче",
                "Метка «Сложная: <почему>» в поручении может добавить", "отчёты: <пути отчётов всех argus",
                "Модель argus не меняй: он всегда на Opus", "а на защитах — не меньше 2", "Вне защит — один argus",
                # владелец 02.11 (metis-0271, В3): Sonnet у argus больше нет, model opus в вызове не нужен
                "argus на Sonnet", "«Принять» на Sonnet", "`model: \"opus\"`, без `effort`",
                # план 1.0, раздел 6а (12.11): в файле роли argus medium, вне ядра effort в вызове не передают
                "Opus и high из файла роли", "с `effort: \"medium\"`", "<agent_id/сессия, …>",
                # metis-0784: повторный круг в ядре больше не всегда полный — решает `pantheon review delta`
                "Повторный круг в ядре — полный", "в ядре — полный;", "Это вне ядра; в ядре он читает весь дифф")
    lead_release = ("PR в agent-kit не трогает `version` в `plugin.json` и `.claude-plugin/releases.json`",
                    "номер поднимает workflow release на main после слияния (metis-0512",
                    "`.github/` (workflow release с правом записи в main)")
    for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md"):
        t = flat.get(f, "")
        for label, rule in lead_rules:
            check(f"{f}: «Сколько argus звать» — {label}", rule in t)
        check(f"{f}: нет старых правил (узкий список защит, «остальное ядро», «вне ядра», узкий повтор без условия)",
              not any(x in t for x in lead_old))
        # metis-0512: правило шлюза о номере версии и ядро .github — в тексте слияния лида
        check(f"{f}: PR не трогает version и releases.json, номер — workflow release, .github — ядро",
              all(x in t for x in lead_release))
    # упрощение п. 9: список ядра в тексте лидов — тот же, что у шлюза guard (CORE_DIR, CORE_FILES), второго списка нет
    import ast as _ast
    gate_src = read(os.path.join(os.path.dirname(os.path.dirname(real)), "guard", "hooks",
                                 "merge_gate.py"))
    gate_core = {}
    for node in _ast.parse(gate_src).body:
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") in (
                "CORE_DIR", "CORE_FILES"):
            gate_core[node.targets[0].id] = _ast.literal_eval(node.value)
    core_dirs, core_files = gate_core.get("CORE_DIR", ()), gate_core.get("CORE_FILES", ())
    for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md"):
        t = flat.get(f, "")
        miss_dirs = [d for d in core_dirs if d not in t]
        miss_files = [x for x in core_files if x not in t and not any(x.startswith(d + "/") for d in core_dirs)]
        check(f"{f}: все папки и файлы ядра шлюза (CORE_DIR, CORE_FILES) названы в тексте слияния"
              + (f" (нет: {miss_dirs + miss_files})" if miss_dirs or miss_files else ""),
              len(core_dirs) >= 3 and len(core_files) >= 5 and not miss_dirs and not miss_files)
    # ссылка лидов на список ведёт в настоящий файл, и он же собран в роль argus
    protected = os.path.join(real, "_parts", "protected.part")
    check("protected.part существует и собран в argus.md («Защищённые пути — их не трогает Codex»)",
          os.path.exists(protected) and "Защищённые пути — их не трогает Codex" in flat.get("argus.md", ""))
    # metis-0601, Д4: карта плагинов — ядро защит (0598), argus видит её среди защищённых путей
    check("protected.part и argus.md называют plugins/pantheon/lib/plugin_map.py и plugins/pantheon/plugins-by-role.toml",
          all(x in read(protected) and x in flat.get("argus.md", "")
              for x in ("plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml")))
    a = flat.get("argus.md", "")
    argus_rules = (
        # metis-0784 (план 1.0, пачка 0): какой повторный круг — по `pantheon review delta`, дельта и в ядре;
        # полный — по всему диффу, «вне дельты не ищешь» там не действует, head не отстаёт от base
        ("повторный круг: первым шагом review delta", "Какой круг, решает `pantheon review delta <owner/repo> <N>` "
         "(metis-0784): выполни его из клона первым шагом."),
        ("повторный круг: «дельта» и в ядре — отчёт прошлого круга и git diff прошлый..новый", "«Дельта» — прошлый "
         "head предок нового, дельта до 200 строк и не задевает ядро, файлы шлюза и сборку окон. Тогда и в ядре весь "
         "дифф PR заново не читаешь: опора — отчёт прошлого круга и дельта `git diff <прошлый head> <head>`."),
        # отставание от base — «head не готов», без reject (Д1 argus #426)
        ("повторный круг: «полный» — весь дифф, отстаёт от base — head не готов, вердикта нет",
         "«Полный» — круг по всему диффу PR, как первый: «вне дельты новых находок не ищешь» там не действует. Head "
         "при полном круге отстаёт от base — не «вернуть»: в отчёте «head не готов: rebase на свежий base» с причиной "
         "из вывода команды, вердикт не записываешь, как при `pantheon review accept` с кодом 1."),
        ("accept — код 1 без записи тестов и зелёного CI на head (metis-0669)", "`pantheon review accept` выходит с "
         "кодом 1 и «принять» не пишет, если на head нет записи тестов шлюза и CI head не зелёный (metis-0669)."),
        ("второй argus — только ядро; список шлюза с origin/main", "Второй независимый argus — только PR, "
         "который задевает ядро. Ядро — список шлюза guard: `CORE_DIR` и `CORE_FILES` в "
         "`plugins/guard/hooks/merge_gate.py` и сборка окон `sandbox_build` с запуском окна `window_launch` в "
         "`plugins/pantheon/lib/pantheon.py`. "
         "Читай список с `origin/main`"),
        ("вне ядра argus один; сложность и метка второго не добавляют", "Вне ядра argus один: "
         "сложность по диффу и метка «Сложная» в поручении второго не добавляют."),
        ("строка «Второй argus»", "строка «Второй argus: нужен — ядро: <пути>» или «Второй argus: не нужен — вне ядра, "
         "<строк, файлов>»"),
        ("узкий повтор: опора — последний свой отчёт, не пути от лида", "Поручение «Узкий повтор: прошлый head <sha>» — "
         "новый head после подтягивания main. Опора — твой последний отчёт по этому PR в этом разговоре, а не пути "
         "отчётов от лида и не head из поручения"),
        ("узкий повтор: своего отчёта нет — полный круг", "Нет ни своего отчёта, ни отчётов прежнего — «вернуть» с причиной «своего отчёта нет — полный круг»."),
        ("узкий повтор: head отчёта равен текущему — повтора нет", "H0 равен текущему head — нового диффа нет, повтора "
         "нет"),
        ("узкий повтор — сначала журнал шлюза, а не отчёты", "Журнал шлюза, а не отчёты: `pantheon review status "
         "<owner/repo> <N>`, строка «итог на <первые 12 знаков H0>»."),
        ("по журналу: «вернуть 0», «принять» по числу argus, в ядре 2", "Узкий повтор — только если там «вернуть 0», а "
         "«принять» не меньше числа argus круга, в ядре — не меньше 2 (строка «для PR ядра» под итогом). Строки нет, в "
         "ней «вернуть» или принявших меньше — «вернуть» с причиной «на прошлом head не «принять» — полный круг»."),
        ("дельта от head своего отчёта, промежуточный head входит", "Дельта считается от H0, а не от «прошлого head» "
         "поручения: не совпали — между ними был промежуточный head, и его дельта входит в твою."),
        ("новая база — merge-base с origin/main после fetch", "`git fetch`, затем новая база B — `git merge-base <head> "
         "origin/main` (не второй родитель merge"),
        ("дерево T — merge-tree head своего отчёта с B", "`git merge-tree --write-tree H0 B` — первая строка вывода, "
         "дерево T"),
        ("diff T head", "`git diff --stat T <head>` и `git diff T <head>`."),
        ("пустая дельта — принять после тестов; правка — круг по новому диффу", "Дельта пуста — в ней только подтянутый "
         "main, нового диффа нет: тесты проекта на новом head зелёные (та же команда, что в полном круге) — «принять». "
         "В дельте есть правка — это новый дифф: круг по новому диффу."),
        ("два пути лида — только вне ядра", "Два пути по решению лида — только вне ядра, после двух кругов «вернуть» за "
         "формулировки:"),
        ("путь «правка текста» с перечнем вернувших", "- «Узкий повтор: прошлый head <sha>, правка текста: <файл:строка>, "
         "решение: <файл плана>, вернули: <agent8>/<сессия8>, …» — лид поправил текст."),
        ("путь «оставить» с перечнем вернувших", "- «Узкий повтор: тот же head <sha>, решение: <файл плана>, вернули: "
         "<agent8>/<сессия8>, …» — лид решил оставить формулировки как есть."),
        ("оба пути: перечень вернувших сверен с «reject» прошлого head", "В обоих путях сначала сверь журнал: в "
         "`pantheon review status <owner/repo> <N>` выпиши рецензентов argus, чей последний вердикт на прошлом head — "
         "«reject», — пары agent_id/сессия по 8 знаков в конце строки вердикта. Набор пар в поручении «вернули: …» с "
         "ними совпадает — лид продолжил всех вернувших. Не совпало, поля нет или в нём число — «вернуть» с причиной "
         "«вернувший argus не продолжен — полный круг»: на новом head шлюз прошлые «вернуть» держит. "
         "«Принять» другого argus снимает их, только если код отличается от кода, на котором вернули."),
        ("свои отчёты двух кругов, не формулировка — полный круг", "Затем прочитай решение в плане и сам открой свои "
         "отчёты двух прошлых кругов. Каждое поправленное или оставленное замечание — только формулировка: без бага, "
         "обхода, теста и мутанта. Иначе — «вернуть» с причиной «не формулировка — полный круг»."),
        ("вернувшие — тот же вызов через SendMessage, новый вызов — полный круг", "Своих прошлых кругов в этом разговоре нет — тебя позвали заново. Путь «правка текста» (код другой): опора — "
         "отчёты прежнего argus"),
        ("ядро: «оставить» и правка текста — полный круг", "Вне ядра формулировки в узком повторе — не причина "
         "«вернуть»: пиши их замечаниями лиду. В ядре текст и есть правило: формулировка, которая меняет его смысл, — "
         "замечание и «вернуть», как в полном круге. Решения лида «оставить» и правки текста узким повтором в ядре нет "
         "— «вернуть» с причиной «ядро — полный круг»."),
        # повторный круг после возврата по коду (metis-0420, N1): по якорю на шаг — мутанта любого убивает своя проверка
        ("повторный круг: поручение, тот же вызов, не узкий повтор, в ядре тоже", "Это не узкий повтор: правка — "
         "новый код, её проверяешь ты, и в ядре тоже."),
        ("повторный круг: сверка журнала — рецензенты «reject» на прошлом head", "1. Сначала сверь журнал: в "
         "`pantheon review status <owner/repo> <N>` выпиши рецензентов argus, чей последний вердикт на прошлом head — "
         "«reject», — пары agent_id/сессия по 8 знаков в конце строки вердикта."),
        ("повторный круг: «вернули» не совпало с журналом — «вернуть», не свой круг", "«вернули: …» с ними совпадает — лид назвал всех вернувших. Не совпало, поля нет или в нём число — «вернуть» с причиной "
         "«вернувший argus не продолжен — продолжи его», как в узком повторе"),
        ("повторный круг: опора — последний твой отчёт, не отчёт по названному head", "2. Опора — последний твой отчёт в этом разговоре, а после вызова заново — отчёты прежнего argus из `pantheon "
         "review report` (выше), а не отчёт с тем head, который назвал лид."),
        ("повторный круг: head последнего отчёта не совпал — полный круг; отчёта нет — тоже", "«Head:» отчёта с «прошлым head» из поручения не совпал — полный круг: между ними был промежуточный head, и его Б "
         "у прежнего не закрыты. Отчёта нет — полный круг."),
        ("повторный круг: после вызова заново argus сам вызывает review report на каждую пару, отказ — полный круг",
         "для каждой пары agent8/сессия8 из него (в ядре — и для принявшего argus, которого ты заменяешь) выполни "
         "`pantheon review report <owner/repo> <N> <agent8>/<сессия8>`"),
        ("повторный круг: Head каждого отчёта = прошлый head, одно «принять» снимает все «вернуть»", "«Head:» каждого "
         "отчёта должен равняться «прошлому head» из поручения"),
        ("повторный круг: любой отказ команды по любой паре — полный круг", "Любой отказ по любой паре (нет "
         "транскрипта, нет отчёта, «Head:» не равен) — полный круг сам, в этом же вызове."),
        # metis-0784: на дельта-круге прошлый head — предок нового, дельта — git diff прошлый..новый
        ("повторный круг: дельта — git diff прошлый head..head", "3. Дельта — `git diff --stat <прошлый head> <head>` "
         "и `git diff <прошлый head> <head>`: на дельта-круге прошлый head — предок нового."),
        ("повторный круг: файлы прошлого head, шире заявленной — полный круг сам", "4. Файлы PR на прошлом head — `git "
         "diff --name-only origin/<base PR>...<прошлый head>`. В дельте только правка из поручения и только в этих "
         "файлах. Иначе дельта шире заявленной — полный круг сам, в этом же вызове."),
        ("повторный круг: каждый свой Б — закрыт или нет с доказательством", "5. Каждый свой Б из прошлого отчёта — "
         "«закрыт» или «не закрыт» с доказательством на новом head: тест краснеет на откате правки, команда и вывод. Не "
         "закрыт — снова Б."),
        ("повторный круг: новый код дельты — как в полном круге", "6. Новый код дельты проверяешь как в полном круге: "
         "тесты правки, плохой вход, мутант."),
        ("повторный круг: выданное не повторяет, вне дельты не ищет", "7. Выданные Д и С не повторяешь; вне дельты новых "
         "находок не ищешь — тот код ты уже проверил."),
        ("повторный круг: тесты проекта на новом head", "8. Тесты проекта на новом head зелёные — та же команда, что в "
         "полном круге."),
        ("повторный круг: строка «Круг:» в отчёте, вердикт на новом head", "В отчёте после «Head:» — строка «Круг: "
         "повторный, дельта <прошлый head>..<head>, файлов <N>» или «Круг: полный — <причина>», затем Б прошлого круга с "
         "итогом. «Второй argus:» — по диффу всего PR, как в полном круге. Вердикт и команда шлюза — на новом head."),
        ("строка «Head:» в отчёте", "Строка «Head: <полный sha проверенного head>», затем `Вердикт: принять | вернуть`"),
        ("Opus — в PR ядра", "а PR задевает ядро — не «принять», а «вернуть» с причиной "
         "«нужна проверка на Opus»"),
        ("защиты: шлюз слияния владельца и песочница окон", "шлюз слияния владельца `plugins/pantheon/lib/merge.py`"),
        ("защиты: sandbox_build и всё, что он записывает", "песочница окон — `sandbox_build` в "
         "`plugins/pantheon/lib/pantheon.py` и всё, что он записывает"))
    for label, rule in argus_rules:
        check(f"argus.md: {label}", rule in a)
    # metis-0512: PR с номером версии argus возвращает; исключений «кроме версии» в кругах нет
    check("argus.md: PR меняет version или releases.json — вернуть, новый и удалённый plugin.json можно",
          "PR в agent-kit меняет `version` в `plugins/*/.claude-plugin/plugin.json` или трогает "
          "`.claude-plugin/releases.json` — вернуть: номер поднимает workflow release на main после слияния "
          "(metis-0512). Новый и удалённый plugin.json — можно." in a)
    check("argus.md: нет исключений версии в кругах", not any(x in a for x in (
        "кроме версии", "или подъёма версии", "кроме main и версии")))
    # сортировка находок (metis-0406): тест держит структуру, а не формулировки — в каждой собранной роли есть раздел
    # признаков Б (от «Б — блокер» до «Д — долг»), и в нём по одному якорю на пункт; текст вокруг якорей свободный
    anchors = ("секреты и личное", "дефект нового кода", "неверно по критерию")
    for f in ("argus.md", "hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md"):
        t = flat.get(f, "")
        sect = t.split("Б — блокер", 1)[1].split("Д — долг", 1)[0] if "Б — блокер" in t and "Д — долг" in t else ""
        check(f"{f}: раздел признаков Б есть, в нём пункты: " + ", ".join(anchors),
              bool(sect) and all(x in sect for x in anchors))

    check("argus.md: нет старого узкого списка ядра, range-diff и «<новая база>» без источника",
          not any(x in a for x in ("или песочницу окон (`sandbox_build`, `window_rules.py`)", "остальное ядро; вне ядра",
                                   "Ядро защит — PR задевает", "`git range-diff <старая база>", "<новая база>",
                                   "Формулировки в узком повторе — не причина", "ядро защит", "Эти пути ведёт тот же",
                                   "хотя первый написал «Второй argus: нужен»", "grep -E '^(Вердикт|Второй argus):'",
                                   "вернули: <M>", "«вернуть» ровно столько, сколько в поручении")))
    check("лиды, координаторы и Зевс: в образце поручения строка «Сложная:» с ориентирами",
          all("Сложная: <почему> — у сложной задачи по диффу всего PR (больше ~300 строк или несколько модулей; при "
              "любом размере — разбор команд, путей и флагов, allow/deny, секреты и личное, удаление, миграции "
              "состояния): вторым argus метка не становится — он только в ядре (merge.part)" in texts.get(f, "")
              for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md", "hq.md")))
    check("лиды и координаторы: в образце поручения строка «Самопроверка» для разработчика",
          all("Самопроверка: разработчику — «в отчёте строка по шести пунктам самопроверки роли: сделано "
              "(доказательство), не применимо (почему) или по отчёту Codex: путь»" in texts.get(f, "")
              for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md", "hq.md")))
    # metis-0583: автозакрытие закрывает задачу по «Closes <id>» в теле PR — правило у тех, кто открывает и сливает PR
    closes_rule = ("Тело PR называет каждую задачу, которую он закрывает: `Closes <id>` или списком `Closes metis-0522, "
                   "metis-0534 и 0535`. Это правило — для PR в любом репозитории направления (agent-kit, BA, сайт): автозакрытие читает тела PR всех репозиториев из [merge_repos]. По этой строке плановый проход ставит задаче done при слиянии, и под общей веткой "
                   "тоже (metis-0583). Слово «часть» в теле — все задачи PR остаются открытыми; если частичная только одна — отдельный "
                   "PR или без Closes и без её номера в имени ветки.")
    miss = [f for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md") if closes_rule not in flat.get(f, "")]
    check("лиды и координатор: тело PR — «Closes <id>» списком, «часть» оставляет открытыми все задачи PR (metis-0583)"
          + (f" (нет у: {miss})" if miss else ""), not miss)
    miss = [f for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md")
            if "в любом репозитории направления" not in flat.get(f, "")]
    check("лиды и координатор: правило Closes — для PR в любом репозитории направления" + (f" (нет у: {miss})" if miss else ""), not miss)
    miss = [f for f in ("dev-opus.md", "dev-sonnet.md", "dev-haiku.md") if "`Closes <id>` каждой задачи" not in flat.get(f, "")]
    check("разработчики: ветка с номером задачи и `Closes <id>` каждой задачи в коммите" + (f" (нет у: {miss})" if miss else ""), not miss)
    # сама роль (без приклеенного _ref) несёт строку-ссылку: без неё правило Closes роль не увидит (argus #241 круг 2, Б1)
    miss_raw = [f for f in ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md")
                if "Тело PR: `Closes <id>, …` — подробности в `_ref/merge-rounds.md`" not in raw_texts.get(f, "")]
    check("лиды и координатор: строка «Тело PR: Closes» в самой роли, не только в _ref (metis-0583)"
          + (f" (нет у: {miss_raw})" if miss_raw else ""), not miss_raw)
    # effort argus (metis-0176): модель в вызове не передают, шлюз сверяет модель по транскрипту
    # владелец 02.11 (metis-0271, В3): argus и вне ядра на Opus — Opus в файле роли, model в вызове не передают
    # план 1.0, раздел 6а (решения 10.11, «да» 12.11): в файле роли medium; первый argus ядра — с effort high
    effort_rule = ("Модель и effort argus (metis-0176, владелец 27.10, 02.11 и 10.11): в файле роли argus — Opus и "
                   "medium, модель в вызове не передавай: шлюз «принять» на другой модели в PR ядра не засчитает. Вне "
                   "ядра защит зови его без `model` и `effort`. В PR ядра первого argus зови с `effort: \"high\"`, "
                   "второго — без `effort`, на medium из файла роли.")
    callers = ("hephaestus-demo.md", "apollo-demo.md", "domain-coordinator.md", "hq.md")
    miss = [f for f in callers if effort_rule not in flat.get(f, "")]
    check("лиды, координатор и Зевс: argus — Opus и medium из файла роли без model, первый argus ядра — с effort high"
          + (f" (нет у: {miss})" if miss else ""), not miss)
    check("hq: каждый вопрос владельцу вопрос на решение начинается с «[<id>]», карточка — по «Вопрос на решение» (metis-0408)",
          "Вопрос владельцу на решение — в окне вопросов, в карточке, в сообщении — начинается с «[<id>]»"
          in flat.get("hq.md", "") and "(`--question`, `--why`, два `--option`, `--recommend`)" in flat.get("hq.md", "")
          and "вопрос о карточке сверх лимита — с id задачи-причины" in flat.get("hq.md", ""))
    check("hq: решение владельца под согласие исполнителя — одно окно вопросов с [id] в том же ходе, прямое слово — "
          "consent bind по строке owner-log без пометки (metis-0843)",
          "— в том же ходе одно окно вопросов с «[<id>]» его вопроса, а не просьба «ответьте цифрой»" in flat.get("hq.md", "")
          and "`pantheon consent bind <id> --log-at <ЧЧ:ММ[:СС]>`" in flat.get("hq.md", "")
          and "своего текста не передаёшь; пересказ — не согласие" in flat.get("hq.md", ""))
    # потолок владельца (metis-0444, metis-0588): отказ start/wake не повторять и не обходить; владельцу — --over-cap
    # его командой или поднять потолок; Гестию потолок не держит
    # metis-0832: владельцу — вопрос «да/нет», а не команда для его терминала
    check("hq: отказ start/wake «недельный потолок владельца» — не повторять и не обходить, владельцу вопрос «да/нет» "
          "(подождать или поднять потолок) без команды для терминала, Гестию будить можно (metis-0588, 0832)",
          "`pantheon start` или `pantheon wake` отказали кодом 2 с причиной «недельный потолок владельца…» — не повторяй и "
          "не обходи (`--over-cap` тебе не дан); владельцу — вопрос «да/нет» в окне вопросов: подождать недели или "
          "поднять потолок; команду для его терминала не пиши. Гестию будить можно: потолок её не держит;"
          in flat.get("hq.md", ""))
    argus_md = texts.get("argus.md", "")
    check("argus: в файле роли effort: medium и model: opus; знает, что первого argus ядра зовут с high, а шлюз "
          "сверяет модель с транскриптом",
          "\neffort: medium\n" in argus_md.split("---")[1] and "\nmodel: opus\n" in argus_md.split("---")[1]
          and "В файле роли у тебя effort medium (план 1.0, раздел 6а): так тебя зовут вне ядра и вторым argus ядра, "
          "первого argus ядра — с effort high." in flat.get("argus.md", "")
          and "Шлюз сверяет модель из `--ran` с твоим транскриптом" in flat.get("argus.md", "")
          and "вне ядра шлюз засчитает и другую модель" in flat.get("argus.md", "")
          and "Sonnet" not in flat.get("argus.md", ""))
    # навык с model: внутри argus (metis-0413 п. 4): его ответы — в транскрипте argus на другой модели, шлюз откажет
    check("argus: в ядре навык с model: в шапке — только отдельным агентом",
          "В ядре не запускай навык с `model:` в шапке: его ответы ложатся в твой транскрипт на другой модели, и "
          "«принять» не засчитается. Нужен такой навык — запусти его отдельным агентом: у агента свой транскрипт."
          in flat.get("argus.md", ""))
    check_plan10(texts, flat, callers)
    # Гестия (metis-0245): окно песочницы есть — роль собирается; запреты шаблона на месте
    tmpl_h = read(os.path.join(real, "hestia.tmpl"))
    head = tmpl_h.split("---")[1] if tmpl_h.count("---") >= 2 else ""
    deny = next((ln for ln in head.splitlines() if ln.startswith("disallowedTools:")), "")
    built_h = texts.get("hestia.md", "")
    # metis-0576: Bash(...) в шапке убирает Bash целиком — коммит, merge, gh api запрещает guard (правило hestia)
    check("hestia: роль собрана (name: hestia), запрещены Edit/Write, Agent, Bash(...) в шапке нет; выпуск — "
          "pantheon plugins update, окно — wake hestia --task",
          all(t in deny for t in ("Edit", "Write", "Agent")) and "Bash" not in deny
          and built_h.startswith("---\nname: hestia\n") and "pantheon plugins update" in built_h
          and "pantheon wake hestia --task" in built_h and "Гестия (hestia" in texts.get("argus.md", ""))
    # metis-0562 п. 1 (F4): установщик один — плановый проход; Гестия выпуски не ставит, только сверяет
    fh = flat.get("hestia.md", "")
    check("hestia: выпуски ставит плановый проход, сама Гестия не ставит (F4) — якорь в теле и в шапке",
          "Выпуски ставишь не ты: установщик один — плановый проход" in fh
          and "Ни `pantheon plugins update`, ни голый `claude plugin update` сама не запускай" in fh
          and "ставит слитые выпуски" not in fh and "Поставить слитый выпуск" not in fh
          and "проверяет, что слитый выпуск встал (ставит его плановый проход, не она)" in fh)
    # п. 2: сеть, push и запись в PR — только по consent; push из запретов шапки снят, merge и gh api остались
    check("hestia: сеть, git push, gh pr create|edit — только по `pantheon consent <id>`; Bash(...) нет в шапке",
          "## Наружу — по consent" in fh and "запусти `pantheon consent <id задачи>`" in fh
          and "Bash" not in deny
          and "Сети у тебя нет." in fh and "Push — на имя remote, не в main и не принудительно" in fh
          and "`git push` и запись в PR — только после «да» владельца (`pantheon consent <id>`)" in fh)
    # п. 3 (F9): пакет для бага и возврат пейджера Метиде
    check("hestia: обязанности F9 — собрать пакет для бага (не отправлять, не чинить) и «Возврат пейджера» Метиде",
          "Собрать пакет для бага: когда задача — сбой системы, не отправляй его и не чини" in fh
          and "Возврат пейджера: три неудачи подряд" in fh
          and "«Возврат пейджера: Метиде — <id задачи>" in fh
          and 'pantheon alert "возврат пейджера: <id>"' in fh)
    # поле name: в шапке — имя роли для Claude Code (argus-51d): личный шаблон с чужим name: не собирается, а его
    # прежняя сборка убрана; повтор поля name: — тоже
    mine_dir = os.path.join(home2, ".claude", "agents")
    old = os.path.join(tmp, "probe-old")
    write(os.path.join(mine_dir, "hearth.tmpl"), "---\nname: hestia\ndescription: x\n---\nтело\n")
    write(os.path.join(mine_dir, "twin.tmpl"), "---\nname: twin\nname: twin\ndescription: x\n---\nтело\n")
    write(os.path.join(mine_dir, "fine.tmpl"), "---\nname: fine\ndescription: x\n---\nтело\n")
    write(os.path.join(old, "hearth.md"),
          "---\nname: hestia\n---\n<!-- собрано pantheon roles build из hearth.tmpl -->\nстарая\n")
    write(os.path.join(old, "mine.md"), "---\nname: mine\n---\nнаписан руками\n")
    r = run("roles", "build", "--out", old)
    hs = read(os.path.join(old, "hestia.md")) if os.path.exists(os.path.join(old, "hestia.md")) else ""
    check("name: hearth.tmpl с «name: hestia» — не собран, прежний hearth.md убран, ошибка в stderr; hestia.md — "
          "из hestia.tmpl",
          not os.path.exists(os.path.join(old, "hearth.md")) and "hearth.tmpl → hearth.md: поле name:" in r.stderr
          and "«hestia»" in r.stderr and "из hestia.tmpl" in hs and "тело" not in hs)
    check("name: повтор name: в шапке — роль не собрана, ошибка; верная личная роль собрана, файл руками цел",
          not os.path.exists(os.path.join(old, "twin.md")) and "twin.tmpl → twin.md: поле name: в шапке повторён" in r.stderr
          and os.path.isfile(os.path.join(old, "fine.md")) and os.path.exists(os.path.join(old, "mine.md"))
          and os.path.isfile(os.path.join(old, "argus.md")))
    for f in ("hearth.tmpl", "twin.tmpl", "fine.tmpl"):
        os.remove(os.path.join(mine_dir, f))
    # metis-0576: Bash(...) в disallowedTools шапки — роль не собрана, прежняя сборка цела, ошибка в stderr
    write(os.path.join(mine_dir, "narrow.tmpl"),
          "---\nname: narrow\ndescription: x\ndisallowedTools: Edit, Bash(git commit *)\n---\nтело\n")
    write(os.path.join(old, "narrow.md"), "---\nname: narrow\n---\n<!-- собрано pantheon roles build из narrow.tmpl -->\nстарая\n")
    r = run("roles", "build", "--out", old)
    check("Bash(...) в disallowedTools — роль не собрана, прежняя сборка цела, ошибка в stderr",
          "narrow.tmpl → narrow.md: Bash(...) в disallowedTools" in r.stderr
          and "старая" in read(os.path.join(old, "narrow.md")) and os.path.isfile(os.path.join(old, "argus.md")))
    os.remove(os.path.join(mine_dir, "narrow.tmpl"))
    agents2 = os.path.join(home2, ".claude", "agents")
    r = run("roles", "build")
    check("новая машина: ~/.claude/agents ещё нет — живая сборка создаёт папку и кладёт общие роли",
          r.returncode == 0 and os.path.isfile(os.path.join(agents2, "argus.md")))

    # metis-0573: роли разработчика и talos называют pantheon outside — сборка настоящих шаблонов плагина
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "roles")
    env_real = dict(env, PANTHEON_PLUGIN_ROLES=real, HOME=os.path.join(tmp, "home-real"))
    os.makedirs(env_real["HOME"])
    out_real = os.path.join(tmp, "real-out")
    r = subprocess.run([PY311, "-I", RUN_PY, "roles", "build", "--out", out_real], env=env_real,
                       capture_output=True, text=True, timeout=120)
    devs = [f for f in sorted(os.listdir(real)) if f.startswith("dev-") and f.endswith(".tmpl")]
    check("настоящие шаблоны плагина собираются, dev-*.tmpl найдены", r.returncode == 0 and len(devs) >= 3)
    for f in devs:
        text = read(os.path.join(out_real, f[:-5] + ".md"))
        check(f"{f[:-5]}: тестам с портом — pantheon outside test --wait 590, dev-серверу — serve [--sha …] --wait 120",
              "pantheon outside test --wait 590" in text
              and "pantheon outside serve [--sha <коммит>] [--app ИМЯ] --wait 120" in text
              and "pantheon outside stop" in text)
    # metis-0653: полный набор исполнители и argus сами не гоняют; запускающий делает TaskStop
    check_longrun(out_real, devs, flat)
    for f in devs + ["argus.tmpl", "codex-dev.tmpl"]:
        text = " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split())
        check(f"{f[:-5]}: полный набор сам не гоняет (metis-0653)",
              "полный набор тестов репозитория" in text.lower() and "не гоняй" in text)
    # persist.part: свою фоновую команду ждут уведомлением о конце (metis-0905), субагента — так же концом хода
    persist = ("Свою фоновую команду ждут её уведомлением о конце", "закончи ход строкой «жду итога <ID>»",
               "Субагента ждут так же — концом хода")
    for f in devs + ["codex-dev.tmpl", "workshop.tmpl"]:
        text = " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split())
        check(f"{f[:-5]}: persist — свою фоновую команду ждут уведомлением о конце, субагента концом хода (metis-0905)",
              all(x in text for x in persist) and "Свою фоновую команду ждут на переднем плане" not in text)
    # persist.part и dev.part проверяются порознь: workshop берёт persist без dev.part, dev-* — оба
    wtext = " ".join(read(os.path.join(out_real, "workshop.md")).split())
    check("workshop (persist.part без dev.part): своя фоновая команда — уведомлением, субагент — концом хода; фразы dev.part нет",
          all(x in wtext for x in persist) and "Есть строка `dev:`" not in wtext)
    for f in devs:
        check(f"{f[:-5]}: Bash уводит команду в фон через ~180 с — ждать Monitor/until, не timeout 600000 (metis-0653)",
              "примерно через 180 с" in " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split()))
    check("argus: Bash уводит команду в фон через ~180 с (metis-0653)",
          "примерно через 180 с" in " ".join(read(os.path.join(out_real, "argus.md")).split()))
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        check(f"{f}: persist — субагента ждут концом хода, не Monitor-ом (metis-0653)",
              "Субагента ждут так же — концом хода" in flat[f]
              and ("закончи ход и жди уведомления" in flat[f] or f == "apollo-demo.md"))
    # dev.part: запрет полного набора привязан к строке dev:
    for f in devs:
        text = " ".join(read(os.path.join(out_real, f[:-5] + ".md")).split())
        check(f"{f[:-5]}: полный набор не гоняй — только при строке `dev:`, без неё проверка — первая строка (metis-0653)",
              "Есть строка `dev:`" in text and "Строки `dev:` нет" in text)
        # metis-1115: строка ci: — тесты agent-kit в CI, локально только её команда, outside test — запасной путь
        check(f"{f[:-5]}: строка `ci:` — тесты в CI, локально только ruff, outside test — когда Actions не запустились",
              "Есть строка `ci:` в `.pantheon-verify` (agent-kit) — тесты идут в CI" in text
              and "`pantheon outside test --wait 590` — только если Actions не запустились" in text
              and "«тесты — в CI»" in text)
        # Д4 argus #430: мутант — встроенный в тест (CI сам мутанты не гоняет), полный набор при ci: — Actions
        check(f"{f[:-5]}: при строке `ci:` мутант встроен в тест, а не «проверяет CI»; пункт 6 — GitHub Actions",
              "Откат проверяет сам тест: он подменяет исходник и ждёт, что check упадёт — мутант убит" in text
              and "проверяет CI на PR" not in text
              and "«не проверял: полный набор — его делает GitHub Actions»" in text)
    argus_md = " ".join(read(os.path.join(out_real, "argus.md")).split())
    check("argus: при строке `ci:` мутант встроен в тест, полный набор — GitHub Actions (Д4 argus #430)",
          "мутант — встроенный в тест (подмена исходника, check краснеет" in argus_md
          and "его делает плановый проход или лид, а при строке `ci:` — GitHub Actions" in argus_md)
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        check(f"{f}: запись тестов при строке ci: — review test с ruff, outside test — только без Actions (metis-1115)",
              "при зелёной CI запись — `pantheon review test -- uvx ruff@0.17.3 check .`; `outside test` — только если "
              "Actions не запустились" in flat[f])
    for f in ("dev-opus", "dev-sonnet", "dev-haiku", "codex-dev"):
        text = " ".join(read(os.path.join(out_real, f + ".md")).split())
        check(f"{f}: пункт 6 самопроверки при долгом наборе — узкие тесты и «не проверял: полный набор»",
              "не проверял: полный набор" in text)
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "apollo-demo.md"):
        text = flat[f]
        check(f"{f}: после отчёта субагента — TaskStop его id, в передаче дел список живых (metis-0653)",
              "сразу `TaskStop` его id" in text and "список живых субагентов" in text)
    talos_real = read(os.path.join(out_real, "talos.md"))
    check("talos: dev-сервер — pantheon outside serve --sha … --wait 120, гасит stop",
          "pantheon outside serve --sha <head PR> [--app ИМЯ] --wait 120" in talos_real and "pantheon outside stop" in talos_real)
    # metis-0900: ожидание владельца в окне роли — строка Зевсу до действия (external.part)
    for f in ("domain-coordinator.md", "hephaestus-demo.md", "workshop.md", "hq.md"):
        text = " ".join(read(os.path.join(out_real, f)).split())
        check(f"{f}: перед подтверждением владельца в окне — строка Зевсу «[id] жду вас в окне <роль>: <что>» (metis-0900)",
              "сначала строка Зевсу «[id] жду вас в окне <роль>: <что>», потом действие" in text
              and "Окну Зевса не нужно" in text)

    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
