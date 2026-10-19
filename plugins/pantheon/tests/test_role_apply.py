#!/usr/bin/env python3
"""pantheon role propose|apply|status|cancel и проход тика (metis-0262 PR 4): личная роль по вашей галочке.

Запуск: python3 -I plugins/pantheon/tests/test_role_apply.py  (код выхода 0 — все прошли)
Подменены HOME, PANTHEON_HOME, PANTHEON_STATE и папка ролей плагина (PANTHEON_PLUGIN_ROLES): настоящие
~/.claude/agents, ~/ai/pantheon и журнал owner-log не трогаются. Галочку на доске изображает строка в
STATE/owner-log/board.jsonl — так её пишет тик по вашей отметке на карточке.
Проверяет: без галочки — отказ и пустой личный слой; галочка на другой версии черновика — отказ; с галочкой —
<имя>.tmpl в личном слое, <имя>.md собрана, статус applied, `pantheon check` код 0; запрещённые ключи шапки, имя
общей роли или лида, размер больше 5 КБ — отказ; тик с «Да» ставит роль сам, с «Нет» — статус rejected.
Замечания argus-70b: повтор ключа шапки — отказ; часть, вставляющая в шапку собранной роли name: или hooks:, —
отказ пробной сборки; sha в статусе и вопросе — полный sha256, «Да» на урезанный — не галочка; «Да» на чужой
карточке с тем же вопросом — не галочка ни для apply, ни для тика.
"""
import json
import os
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
_ROOT = tempfile.mkdtemp(prefix="role-apply-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
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


REG = ('[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\nleads = ["hephaestus"]\n'
       'does = "Демо"\ndoes_not = "Чужое — соседям"\nexamples = ["раз", "два", "три"]\n')


def role(name, body="Помогает с черновиками.", head=""):
    return f"---\nname: {name}\ndescription: Личная роль {name}\nmodel: sonnet\n{head}---\n\n{body}\n{{{{> report}}}}\n"


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="role-apply-test-"))
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    plugin = os.path.join(tmp, "plugin", "roles")
    agents = os.path.join(tmp, ".claude", "agents")
    proposed = os.path.join(home, "roles", "proposed")
    log = os.path.join(state, "owner-log", "board.jsonl")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_PLUGIN_ROLES": plugin, "PANTHEON_NO_NOTIFY": "1", "PANTHEON_HOST": "mac-a"}
    write(os.path.join(home, "directions.toml"), REG)
    write(os.path.join(home, "schedule.toml"), 'primary_host = "mac-a"\n')
    write(os.path.join(home, "directions", "iris-demo", "STATUS.md"), "# iris-demo\n")
    os.makedirs(os.path.join(home, "directions", "iris-demo", "tasks"))
    os.makedirs(os.path.join(tmp, "projects", "demo"))
    # общий слой: обычная роль, роль лида и часть
    write(os.path.join(plugin, "_parts", "report.part"), "## Отчёт\n\nОтчёт: общий\n")
    write(os.path.join(plugin, "argus.tmpl"), "---\nname: argus\n---\n\nРевьюер.\n{{> report}}\n")
    write(os.path.join(plugin, "hephaestus.tmpl"), "---\nname: hephaestus-{{short}}\n---\n\nЛид {{direction}}.\n")

    def run(*args, extra=None):
        e = dict(env, **(extra or {}))
        return subprocess.run([PY311, "-I", LIB, *args], env=e, capture_output=True, text=True, timeout=120)

    def status(name):
        recs = []
        p = os.path.join(state, "roles", "status.jsonl")
        for ln in read(p).splitlines():
            rec = json.loads(ln)
            if rec.get("name") == name:
                recs.append(rec)
        return recs[-1] if recs else {}

    def answer(name, sha, yes=True, days_ago=0.0, card=None, question=None):
        """Галочка на карточке — строка журнала доски, как её пишет тик. Карточка по умолчанию — из статуса заявки."""
        card = card or status(name).get("card") or "iris-0000"
        t = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days_ago * 86400))
        rec = {"time": t, "kind": "answer", "id": card,
               "answer": f"Да — поставить роль {name} в личный слой" if yes else "Нет — отклонить заявку",
               "question": question or f"Применить роль {name} [{sha}]?"}
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def sha_of(name):
        import hashlib
        return hashlib.sha256(open(os.path.join(proposed, name + ".tmpl"), "rb").read()).hexdigest()

    def card_head(tid):
        for root, _, files in os.walk(os.path.join(home, "directions")):
            if tid + ".md" in files:
                return read(os.path.join(root, tid + ".md"))
        return ""

    def personal():
        return sorted(f for f in os.listdir(agents)) if os.path.isdir(agents) else []

    # --- заявка ---
    r = run("role", "propose", "scribe", "--direction", "iris-demo")
    check("propose: черновика нет — код 1, «нет черновика», статуса нет",
          r.returncode == 1 and "нет черновика" in r.stderr and not status("scribe"))
    write(os.path.join(proposed, "scribe.tmpl"), role("scribe"))
    sha1 = sha_of("scribe")
    r = run("role", "propose", "scribe", "--direction", "iris-demo")
    st = status("scribe")
    card = st.get("card", "")
    head = card_head(card)
    check("propose: код 0, статус proposed с sha черновика, карточка с вопросом «Применить роль scribe [sha]?»",
          r.returncode == 0 and st.get("status") == "proposed" and st.get("sha") == sha1
          and f"Применить роль scribe [{sha1}]?" in head and "status: waiting" in head and "Да — поставить" in head)
    check("propose: sha — полный sha256 (64 знака) в статусе, вопросе карточки и ответе команды (argus-70b)",
          len(sha1) == 64 and len(st.get("sha") or "") == 64 and f"[{sha1}]" in head and f"[{sha1}]" in r.stdout)
    r = run("role", "propose", "scribe", "--direction", "iris-demo")
    check("propose повтор с тем же черновиком — та же карточка, новой записи нет",
          r.returncode == 0 and "уже есть" in r.stdout and status("scribe").get("card") == card)

    # --- без галочки ---
    r = run("role", "apply", "scribe")
    check("apply без галочки — код ≠0, в ~/.claude/agents ничего не появилось",
          r.returncode != 0 and "нет вашей галочки" in r.stderr and personal() == [])
    answer("scribe", sha1, question=f"Применить роль scribe [{sha1}]? %%скрыто%%")
    answer("scribe", sha1, question=f"Применить роль scribe [{sha1}]? И ещё одну")
    r = run("role", "apply", "scribe")
    check("apply: «Да» на вопрос со скрытым или лишним текстом — не галочка, отказ",
          r.returncode != 0 and "нет вашей галочки" in r.stderr and personal() == [])
    answer("scribe", sha1, days_ago=15)
    r = run("role", "apply", "scribe")
    check("apply: «Да» старше 14 дней — не галочка, отказ",
          r.returncode != 0 and "нет вашей галочки" in r.stderr and personal() == [])
    answer("scribe", sha1[:12], question=f"Применить роль scribe [{sha1[:12]}]?")
    r = run("role", "apply", "scribe")
    check("apply: «Да» на вопрос с урезанным sha (12 знаков) — не галочка, отказ",
          r.returncode != 0 and "нет вашей галочки" in r.stderr and personal() == [])
    answer("scribe", sha1, card="iris-9999")
    r = run("role", "apply", "scribe")
    check("apply: «Да» с тем же вопросом на чужой карточке (не из статуса заявки) — не галочка, отказ",
          r.returncode != 0 and "нет вашей галочки" in r.stderr and personal() == [])
    r = run("tick")
    check("тик: «Да» на чужой карточке — роль не ставится, статус proposed",
          personal() == [] and status("scribe").get("status") == "proposed")

    # --- галочка на другой версии черновика ---
    answer("scribe", sha1, card=card)
    write(os.path.join(proposed, "scribe.tmpl"), role("scribe", body="Правлено после галочки."))
    r = run("role", "apply", "scribe")
    check("apply: черновик правлен после галочки (другой sha) — отказ «другой версии», личный слой пуст",
          r.returncode != 0 and "другой версии" in r.stderr and personal() == [])
    r = run("tick")
    check("тик: галочка на другой версии — роль не ставится, статус proposed",
          personal() == [] and status("scribe").get("status") == "proposed")

    # --- с галочкой ---
    write(os.path.join(proposed, "scribe.tmpl"), role("scribe"))
    r = run("role", "apply", "scribe")
    md = read(os.path.join(agents, "scribe.md"))
    check("apply с галочкой — код 0, scribe.tmpl в личном слое = черновик",
          r.returncode == 0 and read(os.path.join(agents, "scribe.tmpl")) == read(os.path.join(proposed, "scribe.tmpl")))
    check("apply: scribe.md собрана сборкой (метка, часть вставлена), общие роли тоже",
          "<!-- собрано pantheon roles build из scribe.tmpl" in md and "Отчёт: общий" in md and "{{" not in md
          and os.path.isfile(os.path.join(agents, "argus.md")))
    st = status("scribe")
    check("apply: статус applied с sha, картой и временем вашей галочки",
          st.get("status") == "applied" and st.get("sha") == sha1 and st.get("card") == card and st.get("answer_time"))
    check("apply: карточка заявки закрыта (done)", "status: done" in card_head(card))
    r = run("check")
    check("pantheon check после apply — код 0", r.returncode == 0)
    r = run("role", "apply", "scribe")
    check("apply повтор — код 0, «уже стоит»", r.returncode == 0 and "уже стоит" in r.stdout)
    r = run("role", "status")
    check("role status — строка scribe: applied", r.returncode == 0 and "scribe: applied" in r.stdout)

    # --- запрещённое в черновике ---
    bad_heads = [("hooks", "hooks:\n  Stop:\n    - command: x\n"), ("mcpServers", "mcpServers:\n  x: {}\n"),
                 ("permissionMode", "permissionMode: bypassPermissions\n"), ("settings", "settings: x\n"),
                 ("ключ в кавычках", '"hooks": x\n'), ("часть в шапке", "{{> evil}}\n")]
    write(os.path.join(agents, "_parts", "evil.part"), "hooks: x")
    for i, (what, head) in enumerate(bad_heads):
        n = f"bad{i}"
        write(os.path.join(proposed, n + ".tmpl"), role(n, head=head))
        rp = run("role", "propose", n, "--direction", "iris-demo")
        answer(n, sha_of(n))
        ra = run("role", "apply", n)
        check(f"шапка с {what} — propose и apply отказ, в личном слое нет {n}.*",
              rp.returncode == 1 and ra.returncode != 0 and not status(n)
              and not any(f.startswith(n + ".") for f in personal()))
    # повтор ключа: Claude Code (Bun.YAML.parse) берёт последний, ворота сверяли первый — argus-70b
    for n, head in (("dupname", "name: argus\n"), ("dupcase", "Name: argus\n"), ("dupmodel", "model: opus\n"),
                    ("dupdesc", "description: ещё\n")):
        write(os.path.join(proposed, n + ".tmpl"), role(n, head=head))
        rp = run("role", "propose", n, "--direction", "iris-demo")
        check(f"шапка с повтором ключа ({head.split(':')[0]}) — propose отказ «повторён», заявки нет",
              rp.returncode == 1 and "повторён" in rp.stderr and not status(n))
    write(os.path.join(proposed, "dupname.tmpl"), role("dupname"))
    run("role", "propose", "dupname", "--direction", "iris-demo")
    answer("dupname", sha_of("dupname"))
    write(os.path.join(proposed, "dupname.tmpl"), role("dupname", head="name: argus\n"))
    ra = run("role", "apply", "dupname")
    check("apply: черновик с повтором name после заявки — отказ «повторён», личный слой без dupname и argus.tmpl",
          ra.returncode != 0 and "повторён" in ra.stderr and not os.path.exists(os.path.join(agents, "dupname.tmpl"))
          and not os.path.exists(os.path.join(agents, "argus.tmpl")))
    # часть внутри строки шапки вставляет ключ только в собранную роль: ворота черновика её не видят
    for n, part, why in (("injname", "b\nname: argus", "повторён"), ("injhooks", "b\nhooks: x", "запрещённый ключ")):
        write(os.path.join(agents, "_parts", n + ".part"), part)
        write(os.path.join(proposed, n + ".tmpl"), role(n, head=f"tools: Read {{{{> {n}}}}}\n"))
        rp = run("role", "propose", n, "--direction", "iris-demo")
        answer(n, sha_of(n))
        ra = run("role", "apply", n)
        check(f"часть в строке шапки добавляет в собранную роль {part.split(chr(10))[1]} — propose проходит, apply "
              f"отказ «пробная сборка … {why}», {n}.* в личном слое нет",
              rp.returncode == 0 and ra.returncode != 0 and "пробная сборка" in ra.stderr and why in ra.stderr
              and status(n).get("status") == "proposed" and not any(f.startswith(n + ".") for f in personal()))
    for n, why in (("argus", "общая роль"), ("hephaestus-demo", "занято системой"), ("hephaestus", "общая роль"),
                   ("dev-opus", "занято системой"), ("Bad_Name", "не по образцу"), ("claude", "занято системой"),
                   ("fork", "занято системой"), ("explore", "занято системой"), ("claude-helper", "занято системой")):
        write(os.path.join(proposed, n + ".tmpl"), role(n))
        rp = run("role", "propose", n, "--direction", "iris-demo")
        answer(n, sha_of(n))
        ra = run("role", "apply", n)
        check(f"имя {n} — отказ ({why}), личный слой не тронут",
              rp.returncode == 1 and why in rp.stderr and ra.returncode != 0 and why in ra.stderr
              and not os.path.exists(os.path.join(agents, n + ".tmpl")))
    write(os.path.join(proposed, "big.tmpl"), role("big", body="x" * 5200))
    r = run("role", "propose", "big", "--direction", "iris-demo")
    check("черновик больше 5 КБ — отказ", r.returncode == 1 and "5 КБ" in r.stderr)
    write(os.path.join(proposed, "other.tmpl"), role("someone"))
    r = run("role", "propose", "other", "--direction", "iris-demo")
    check("name: в шапке не совпадает с именем — отказ", r.returncode == 1 and "name:" in r.stderr)
    write(os.path.join(proposed, "hand.tmpl"), role("hand"))
    write(os.path.join(agents, "hand.md"), "---\nname: hand\n---\nнаписан руками\n")
    run("role", "propose", "hand", "--direction", "iris-demo")
    answer("hand", sha_of("hand"))
    r = run("role", "apply", "hand")
    check("hand.md написан руками — отказ, файл цел, hand.tmpl не появился",
          r.returncode != 0 and "не сборкой" in r.stderr and read(os.path.join(agents, "hand.md")).endswith("руками\n")
          and not os.path.exists(os.path.join(agents, "hand.tmpl")))

    # --- отзыв ---
    write(os.path.join(proposed, "later.tmpl"), role("later"))
    run("role", "propose", "later", "--direction", "iris-demo")
    r = run("role", "cancel", "later")
    answer("later", sha_of("later"))
    ra = run("role", "apply", "later")
    check("cancel: статус cancelled, apply после отзыва — отказ",
          r.returncode == 0 and status("later").get("status") == "cancelled" and ra.returncode != 0
          and not os.path.exists(os.path.join(agents, "later.tmpl")))

    # --- тик ---
    for n in ("helper", "noper"):
        write(os.path.join(proposed, n + ".tmpl"), role(n))
        run("role", "propose", n, "--direction", "iris-demo")
    r = run("tick")
    check("тик без ответа — заявки ждут, ролей нет",
          status("helper").get("status") == "proposed" and not os.path.exists(os.path.join(agents, "helper.tmpl")))
    answer("helper", sha_of("helper"), card=status("helper").get("card"))
    answer("noper", sha_of("noper"), yes=False, card=status("noper").get("card"))
    r = run("tick")
    check("тик с галочкой «Да» — роль поставлена сам: helper.tmpl и helper.md, статус applied, by tick",
          r.returncode == 0 and os.path.isfile(os.path.join(agents, "helper.tmpl"))
          and "pantheon roles build из helper.tmpl" in read(os.path.join(agents, "helper.md"))
          and status("helper").get("status") == "applied" and status("helper").get("by") == "tick")
    check("тик с «Нет» — статус rejected, роли нет, карточка в «Отменено»",
          status("noper").get("status") == "rejected" and not os.path.exists(os.path.join(agents, "noper.tmpl"))
          and "status: dropped" in card_head(status("noper").get("card")))
    r = run("check")
    check("pantheon check после тика — код 0", r.returncode == 0)
    r = run("role", "apply", "noper")
    check("apply после «Нет» — отказ", r.returncode != 0 and not os.path.exists(os.path.join(agents, "noper.tmpl")))

    # --- argus-70a: согласие привязано к карточке и времени заявки ---
    write(os.path.join(proposed, "nobefore.tmpl"), role("nobefore"))
    run("role", "propose", "nobefore", "--direction", "iris-demo")
    answer("nobefore", sha_of("nobefore"), yes=False)
    r = run("role", "apply", "nobefore")
    check("«Нет», затем role apply до тика — отказ «Нет», роли нет",
          r.returncode != 0 and "«Нет»" in r.stderr and not os.path.exists(os.path.join(agents, "nobefore.tmpl")))
    write(os.path.join(proposed, "revoke.tmpl"), role("revoke"))
    run("role", "propose", "revoke", "--direction", "iris-demo")
    answer("revoke", sha_of("revoke"))
    run("role", "cancel", "revoke")
    r = run("role", "propose", "revoke", "--direction", "iris-demo")
    run("tick")
    check("«Да» → cancel → propose с тем же черновиком → тик: старый ответ не засчитан, роль не стоит",
          r.returncode == 0 and status("revoke").get("status") == "proposed"
          and not os.path.exists(os.path.join(agents, "revoke.tmpl")))
    for f in ("helper.tmpl", "helper.md"):
        os.remove(os.path.join(agents, f))
    r = run("role", "propose", "helper", "--direction", "iris-demo")
    run("tick")
    check("роль поставлена → удалена руками → propose → тик: прежняя галочка не ставит её снова",
          r.returncode == 0 and status("helper").get("status") == "proposed"
          and not os.path.exists(os.path.join(agents, "helper.tmpl")))
    write(os.path.join(proposed, "early.tmpl"), role("early"))
    run("role", "propose", "early", "--direction", "iris-demo")
    answer("early", sha_of("early"), days_ago=0.02)
    r = run("role", "apply", "early")
    check("«Да» на карточке заявки, но временем раньше самой заявки — не галочка",
          r.returncode != 0 and "нет вашей галочки" in r.stderr
          and not os.path.exists(os.path.join(agents, "early.tmpl")))

    # --- argus-70a: живая сборка упала исключением — шаблон откатан, статус прежний ---
    fault = ("import importlib.util, json, sys\n"
             "spec = importlib.util.spec_from_file_location('pmod', sys.argv[1])\n"
             "P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)\n"
             "orig, hit = P.roles_build, []\n"
             "def boom(src=None, out=None, role_errors=None):\n"
             "    if out is None and not hit:\n"
             "        hit.append(1); raise OSError('диск полон (проба)')\n"
             "    return orig(src, out, role_errors=role_errors)\n"
             "P.roles_build = boom\n"
             "print(json.dumps(P.role_apply(sys.argv[2]), ensure_ascii=False))\n")
    write(os.path.join(proposed, "faulty.tmpl"), role("faulty"))
    run("role", "propose", "faulty", "--direction", "iris-demo")
    answer("faulty", sha_of("faulty"))
    r = subprocess.run([PY311, "-I", "-c", fault, LIB, "faulty"], env=env, capture_output=True, text=True, timeout=120)
    try:
        code, text = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        code, text = None, r.stderr[-300:]
    check("исключение в живой сборке — код 1, «сбой OSError», faulty.tmpl и .md нет, статус proposed",
          code == 1 and "сбой OSError" in text and not os.path.exists(os.path.join(agents, "faulty.tmpl"))
          and not os.path.exists(os.path.join(agents, "faulty.md")) and status("faulty").get("status") == "proposed")
    r = run("role", "apply", "faulty")
    check("после отката повтор apply ставит роль",
          r.returncode == 0 and os.path.isfile(os.path.join(agents, "faulty.md")))

    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
