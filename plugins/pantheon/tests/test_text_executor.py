#!/usr/bin/env python3
"""Исполнитель без кода palamedes и изоляция лидов (metis-0224, аудит v2 §12.5–12.7).

Запуск: python3 -I plugins/pantheon/tests/test_text_executor.py  (код выхода 0 — все прошли)
Проверяет:
  - Stop-хук hooks/text-stop-verify.py: пропуск при годном итоге и отказ (выход 2), когда нет строки «Итог:», файла,
    таблицы «утверждение → источник», источника в строке, есть заглушка или слово из stop-words.txt направления;
    чтение отчёта из транскрипта, три возврата и отпуск, текст итога в вывод не попадает;
  - шапки ролей: нет isolation у hephaestus и apollo (в папке без git лид бы не поднялся), у palamedes — свой
    Stop-хук, закрыты веб, Bash, Agent и Skill (навык с context: fork поднял бы агента с вебом), список tools: —
    только файлы, ToolSearch и MCP qmd;
  - тексты: координатор передаёт лиду isolation только из папки в git и знает palamedes, brief.part — исключение «модель в вызове», имя в
    names.part, palamedes в списках окон HQ_AGENTS и COORDINATOR_AGENTS;
  - сборку ролей из шаблонов плагина (Python 3.11+): palamedes.md со Skill в запрете, лиды без isolation.
HOME, PANTHEON_HOME и PANTHEON_STATE подменены временной папкой. PANTHEON_TEST_TEXT_STOP_HOOK — путь к другой копии
хука (прогон мутантов).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import atexit
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

_ROOT = tempfile.mkdtemp(prefix="text-exec-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES = os.path.join(PLUGIN, "roles")
HOOK = os.environ.get("PANTHEON_TEST_TEXT_STOP_HOOK") or os.path.join(PLUGIN, "hooks", "text-stop-verify.py")
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
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


def head(text):
    end = text.find("\n---\n", 3)
    return text[4:end] if text.startswith("---\n") and end > 0 else ""


GOOD = ("# Объявление\n\nДом 120 м², задаток 10 %. Секрет-строка-черновика.\n\n"
        "| Утверждение | Источник |\n|---|---|\n| Площадь 120 м² | lots/7.md:3 |\n| Задаток 10 % | lots/7.md:9 |\n")


def hook_tests():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="text-stop-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state}
    drafts = os.path.join(home, "directions", "example-content", "drafts")
    good = os.path.join(drafts, "c-1-avito.md")
    write(good, GOOD)
    n = [0]

    def stop(report=None, transcript=None, agent=None, extra_env=None, raw=None):
        n[0] += 1
        ev = {"agent_id": agent or f"p-{n[0]}", "agent_type": "palamedes", "hook_event_name": "SubagentStop",
              "cwd": tmp}
        if report is not None:
            ev["last_assistant_message"] = report
        if transcript is not None:
            ev["agent_transcript_path"] = transcript
        return subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(ev),
                              env=dict(env, **(extra_env or {})), capture_output=True, text=True, timeout=30)

    def rep(path):
        return f"Статус: готово\nЧто сделано: объявление\nНужно решение: нет\nПодробности: ветка нет\nИтог: {path}\n"

    r = stop(rep(good))
    check("text-stop: годный итог — пропуск без вывода", r.returncode == 0 and not r.stderr)
    r = stop(rep(good.replace(tmp, "~")))
    check("text-stop: путь от ~ — пропуск", r.returncode == 0)
    r = stop("Статус: готово\nПодробности: ветка нет\n- **Итог:** `" + good + "`\n")
    check("text-stop: «- **Итог:** `путь`» в разметке — пропуск", r.returncode == 0)
    r = stop("Статус: готово\nПодробности: Итог: " + good + "\n")
    check("text-stop: «Итог:» не отдельной строкой — отказ", r.returncode == 2 and "Итог:" in r.stderr)
    spaced = os.path.join(drafts, "c 2 пост.md")
    write(spaced, GOOD)
    r = stop(rep("`" + spaced + "`"))
    check("text-stop: путь с пробелами в обратных кавычках — пропуск", r.returncode == 0)

    r = stop("Статус: готово\nПодробности: черновик готов\n")
    check("text-stop: нет строки «Итог:» — отказ", r.returncode == 2 and "Итог:" in r.stderr and "1 из 3" in r.stderr)
    r = stop(rep("drafts/c-1-avito.md"))
    check("text-stop: путь не абсолютный — отказ", r.returncode == 2 and "не абсолютный" in r.stderr)
    r = stop(rep(os.path.join(drafts, "нет-такого.md")))
    check("text-stop: файла итога нет — отказ", r.returncode == 2 and "нет — сначала запиши" in r.stderr)
    sh = os.path.join(drafts, "x.sh")
    write(sh, GOOD)
    r = stop(rep(sh))
    check("text-stop: итог не .md/.txt — отказ", r.returncode == 2 and "не .md" in r.stderr)
    empty = os.path.join(drafts, "empty.md")
    write(empty, "  \n")
    r = stop(rep(empty))
    check("text-stop: пустой итог — отказ", r.returncode == 2 and "пуст" in r.stderr)

    cases = {
        "no-table.md": ("# Текст\n\nБез таблицы.\n", "нет таблицы"),
        "wrong-head.md": ("| Факт | Ссылка |\n|---|---|\n| a | b |\n", "нет таблицы"),
        "no-src-col.md": ("| Утверждение | Ссылка |\n|---|---|\n| a | b |\n", "нет таблицы"),
        "no-sep.md": ("| Утверждение | Источник |\n| a | b |\n", "нет таблицы"),
        "no-rows.md": ("| Утверждение | Источник |\n|---|---|\n\nТекст.\n", "пустая"),
        "dash.md": (GOOD + "| Срок 30 дней | — |\n", "не заполнены строки 9"),
        "blank.md": (GOOD + "| Срок 30 дней |  |\n", "не заполнены строки 9"),
        "short.md": (GOOD + "| Срок 30 дней |\n", "не заполнены строки 9"),
        "no-claim.md": (GOOD + "| ? | lots/7.md:1 |\n", "не заполнены строки 9"),
        "todo.md": (GOOD + "\nTODO: дописать цену\n", "«TODO» (строка 10)"),
        "src-ph.md": (GOOD.replace("lots/7.md:9", "[источник]"), "«[источник]»"),
        "insert.md": ("Цена [вставить цену]\n\n" + GOOD, "«[вставить …]»"),
        "ai.md": (GOOD + "\nКак языковая модель, я не могу.\n", "как языковая модель"),
        "lorem.md": (GOOD + "\nLorem ipsum dolor.\n", "lorem ipsum"),
        "xxx.md": (GOOD + "\nЦена XXX руб.\n", "«XXX»"),
    }
    for name, (text, want) in cases.items():
        p = os.path.join(drafts, name)
        write(p, text)
        r = stop(rep(p))
        check(f"text-stop: {name} — отказ «{want}»", r.returncode == 2 and want in r.stderr)
    p = os.path.join(drafts, "ok-words.md")
    write(p, GOOD + "\nТодорова — фамилия, xxx в нижнем регистре, ИИСУС — не слово «ИИ».\n")
    r = stop(rep(p))
    check("text-stop: похожие слова (Тодорова, xxx, ИИСУС) — не заглушки, пропуск", r.returncode == 0)

    # список направления: только для итога в папке направления
    write(os.path.join(home, "directions", "example-content", "stop-words.txt"),
          "# слова канала\nуникальное предложение\n\n")
    p = os.path.join(drafts, "words.md")
    write(p, GOOD + "\nЭто Уникальное предложение!\n")
    r = stop(rep(p))
    check("text-stop: слово из stop-words.txt направления — отказ",
          r.returncode == 2 and "«уникальное предложение» (строка 10)" in r.stderr)
    out = os.path.join(tmp, "outside", "words.md")
    write(out, GOOD + "\nЭто Уникальное предложение!\n")
    r = stop(rep(out))
    check("text-stop: итог вне папки направления — список направления не действует", r.returncode == 0)
    write(os.path.join(home, "directions", "example-content", "stop-words.txt"), "TODO\n")
    p = os.path.join(drafts, "todo2.md")
    write(p, GOOD + "\ntodo\n")
    r = stop(rep(p))
    check("text-stop: список направления встроенные слова не снимает", r.returncode == 2 and "TODO" in r.stderr)

    # отчёт из транскрипта, когда поля last_assistant_message нет
    tr = os.path.join(tmp, "agent.jsonl")
    with open(tr, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": rep(good)}]}}) + "\n")
        fh.write(json.dumps({"type": "user", "message": {"content": "спасибо"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}}) + "\n")
    r = stop(transcript=tr)
    check("text-stop: отчёт из транскрипта (последний текст ассистента) — пропуск", r.returncode == 0)
    with open(tr, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Готово."}]}}) + "\n")
    r = stop(transcript=tr)
    check("text-stop: последний текст транскрипта без «Итог:» — отказ", r.returncode == 2 and "Итог:" in r.stderr)
    r = stop(transcript=os.path.join(tmp, "нет.jsonl"))
    check("text-stop: ни поля, ни транскрипта — не держит", r.returncode == 0)

    # три возврата подряд и отпуск; удача обнуляет счёт
    bad = os.path.join(drafts, "no-table.md")
    codes = [stop(rep(bad), agent="same").returncode for _ in range(3)]
    r = stop(rep(bad), agent="same")
    check("text-stop: три возврата (2, 2, 2), на четвёртый отпускает со «заблокировано»",
          codes == [2, 2, 2] and r.returncode == 0 and "заблокировано" in r.stderr)
    r = stop(rep(bad), agent="same")
    check("text-stop: после отпуска счёт заново — снова 1 из 3", r.returncode == 2 and "1 из 3" in r.stderr)
    stop(rep(good), agent="same")
    r = stop(rep(bad), agent="same")
    check("text-stop: годный итог обнуляет счёт", r.returncode == 2 and "1 из 3" in r.stderr)

    r = stop(rep(os.path.join(drafts, "dash.md")))
    check("text-stop: текст итога в вывод не попадает", "Секрет-строка" not in r.stderr + r.stdout)
    r = stop(raw="не json")
    check("text-stop: не JSON на входе — не держит", r.returncode == 0)
    r = stop(rep(bad), extra_env={"PANTHEON_TEXT_STOP_OFF": "1"})
    check("text-stop: PANTHEON_TEXT_STOP_OFF=1 — выключен", r.returncode == 0)


PALAMEDES_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "ToolSearch", "mcp__qmd__query", "mcp__qmd__get",
                   "mcp__qmd__multi_get", "mcp__qmd__status"}


def palamedes_tools(h):
    m = re.search(r"^tools:\s*(.+)$", h, re.M)
    return {x.strip() for x in m.group(1).split(",") if x.strip()} if m else None


def template_tests():
    t = {f[:-5]: read(os.path.join(ROLES, f)) for f in os.listdir(ROLES) if f.endswith(".tmpl")}
    for lead in ("hephaestus", "apollo"):
        check(f"{lead}.tmpl: в шапке нет isolation (Б1 ревью #137: папка без git)", "isolation" not in head(t[lead]))
    pal = t.get("palamedes", "")
    h = head(pal)
    check("palamedes.tmpl: name palamedes, без isolation", re.search(r"^name:\s*palamedes\s*$", h, re.M) is not None
          and "isolation" not in h)
    dis = re.search(r"^disallowedTools:\s*(.+)$", h, re.M)
    dis = {x.strip() for x in dis.group(1).split(",")} if dis else set()
    check("palamedes.tmpl: закрыты веб, Bash, Agent, Task, SendMessage, браузеры",
          {"WebFetch", "WebSearch", "Bash", "Agent", "Task", "SendMessage", "mcp__claude-in-chrome",
           "mcp__chrome-devtools", "mcp__computer-use"} <= dis)
    check("palamedes.tmpl: Skill закрыт целиком (Б2 ревью #137), а не отдельный навык", "Skill" in dis)
    tools = palamedes_tools(h)
    check("palamedes.tmpl: есть список tools: и в нём только разрешённое — файлы, ToolSearch, MCP qmd",
          tools is not None and {"Read", "Write", "Edit", "Glob", "Grep"} <= tools and tools <= PALAMEDES_TOOLS)
    check("palamedes.tmpl: в tools: нет Bash, Skill, веба, Agent, SendMessage и mcp__ кроме qmd",
          tools is not None and not any(x in ("Bash", "Skill", "Agent", "Task", "SendMessage") or x.startswith("Web")
                                        or x.split("(")[0] in ("Bash", "Skill", "Agent", "Task")
                                        or (x.startswith("mcp__") and not x.startswith("mcp__qmd__"))
                                        for x in tools))
    check("palamedes.tmpl: нет предзагрузки навыков (skills:) и велено читать SKILL.md, а не звать Skill",
          re.search(r"^skills:", h, re.M) is None and "Прочитай этот файл (Read)" in pal
          and "загрузи его до начала (Skill)" not in pal)
    m = re.search(r'command:\s*python3 "\$HOME/\.local/share/pantheon/current/hooks/([\w.-]+)"', h)
    check("palamedes.tmpl: Stop-хук — text-stop-verify.py, файл есть в hooks/",
          m is not None and m.group(1) == "text-stop-verify.py" and "\n  Stop:" in h
          and os.path.isfile(os.path.join(PLUGIN, "hooks", m.group(1))))
    check("palamedes.tmpl: в отчёте строка «Итог: <путь>» и таблица «утверждение → источник»",
          "`Итог: <абсолютный путь к файлу>`" in pal and "| Утверждение | Источник |" in pal)
    dc = t["domain-coordinator"]
    check("domain-coordinator.tmpl: isolation лиду — только из папки в git, иначе без неё",
          'Лиду `isolation: "worktree"` передаёшь в вызове, только если твоя папка в git' in dc
          and "git rev-parse --is-inside-work-tree" in dc and "зови без isolation" in dc
          and "Лида зовёшь с `isolation" not in dc)
    check("domain-coordinator.tmpl: работа без кода — palamedes, модель и effort в вызове",
          "palamedes (Паламед)" in dc and "(`model`, `effort`)" in dc)
    check("hq.tmpl: palamedes и модель в вызове", "palamedes (Паламед)" in t["hq"] and "(`model`, `effort`)" in t["hq"])
    brief = read(os.path.join(ROLES, "_parts", "brief.part"))
    check("brief.part: исключение из «модель в вызове не передавай» — palamedes",
          "Модель в вызове не передавай" in brief and "Исключение — palamedes" in brief)
    check("names.part: Паламед (palamedes) среди «он»",
          re.search(r"- он:[^\n]*(?:\n  [^\n]*)*Паламед \(palamedes\)", read(os.path.join(ROLES, "_parts", "names.part")))
          is not None)
    src = read(LIB)
    for var in ("HQ_AGENTS", "COORDINATOR_AGENTS"):
        m = re.search(r"^" + var + r" = \[([^\]]*)\]", src, re.M)
        check(f"pantheon.py: palamedes в {var}", m is not None and '"palamedes"' in m.group(1))


def build_test():
    if not PY311:
        print("skip сборка ролей: нет Python 3.11+")
        return
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="text-build-"))
    home = os.path.join(tmp, "ai", "pantheon")
    write(os.path.join(home, "directions.toml"),
          '[[direction]]\nname = "example-content"\nproject = "example"\nfolders = ["~/projects/example"]\n'
          'leads = ["hephaestus", "apollo"]\ndoes = "Тексты"\ndoes_not = "Код"\nexamples = ["а", "б", "в"]\n')
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_PLUGIN_ROLES": ROLES, "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp")}
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])
    out = os.path.join(tmp, "out")
    r = subprocess.run([PY311, "-I", LIB, "roles", "build", "--out", out], env=env, capture_output=True, text=True,
                       timeout=120)
    errs = [x for x in r.stderr.splitlines() if x.startswith("roles build:")]
    pal = read(os.path.join(out, "palamedes.md"))
    check("roles build: шаблоны плагина собираются без ошибок", r.returncode == 0 and not errs)
    check("roles build: palamedes.md собран, части вставлены, хук в шапке",
          pal.startswith("---\nname: palamedes\n") and "{{" not in pal and "Отчёт наверх" in pal
          and "text-stop-verify.py" in head(pal))
    for lead in ("hephaestus-content", "apollo-content"):
        built = read(os.path.join(out, lead + ".md"))
        check(f"roles build: {lead}.md собран, в шапке нет isolation (папка ~/projects/example без git)",
              built.startswith("---\nname: " + lead + "\n") and "isolation" not in head(built))
    check("roles build: palamedes.md — Skill в disallowedTools",
          re.search(r"^disallowedTools:[^\n]*\bSkill\b", head(pal), re.M) is not None)
    built_tools = palamedes_tools(head(pal))
    check("roles build: palamedes.md — tools: дошёл до сборки тем же списком",
          built_tools is not None and {"Read", "Write"} <= built_tools and built_tools <= PALAMEDES_TOOLS)


def main():
    hook_tests()
    template_tests()
    build_test()
    bad = results.count(False)
    print(f"{len(results) - bad}/{len(results)} проверок прошли")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
