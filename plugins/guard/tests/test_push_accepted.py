#!/usr/bin/env python3
"""Push в принятый PR (metis-0794): git push нового коммита в ветку открытого PR, у которого на текущем head «принять»
argus столько, сколько нужно для слияния (ядро — два Opus, вне ядра — одно), а «вернуть» нет, guard останавливает
подсказкой «долг — задачей, PR — к слиянию»; ролям и окнам без роли одинаково. С «вернуть», без вердиктов, при сбое
gh, со строкой «Б: …» в новом коммите и в прочих случаях push идёт как раньше (fail-open). Хук — настоящий, gh —
поддельный и HOME — временный из _merge_gate_common (общая часть тестов запора слияния).
Запуск: python3 -I plugins/guard/tests/test_push_accepted.py   (код 0 — все прошли)
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _merge_gate_common as tm  # noqa: E402  (Home, rec, git — помощники запора слияния)
from _py311 import mkroot  # noqa: E402  (metis-0729)

HERE = os.path.dirname(os.path.abspath(__file__))
MERGE_PY = os.path.join(HERE, "..", "..", "pantheon", "lib", "merge.py")
GATE_PY = os.path.join(HERE, "..", "hooks", "merge_gate.py")
REPO = "latark/agent-kit"
KIT = "projects/agent-kit"
BRANCH = "feat-0794"
HINT = "уже принят"
NON_CORE = ["README.md", "plugins/pantheon/lib/tasks.py"]
CORE_FILES = ["README.md", "plugins/guard/hooks/merge_gate.py"]
ROLES = (("роль", "domain-coordinator"), ("окно без роли", None))
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))


class Push:
    """Ветка BRANCH в agent-kit: tip — вершина на remote (refs/remotes/origin/BRANCH), new — новый коммит сверху."""

    def __init__(self, h):
        self.h, self.p = h, h.j(KIT)
        tm.git(self.p, "checkout", "-q", "-B", BRANCH, h.sha["agent-kit"])
        tm.git(self.p, "commit", "-q", "--allow-empty", "-m", "правка PR")
        self.tip = tm.git(self.p, "rev-parse", "HEAD")
        tm.git(self.p, "update-ref", f"refs/remotes/origin/{BRANCH}", self.tip)
        tm.git(self.p, "config", f"branch.{BRANCH}.remote", "origin")
        tm.git(self.p, "config", f"branch.{BRANCH}.merge", f"refs/heads/{BRANCH}")
        self.commit("долг ревью Д-A")

    def commit(self, msg):
        tm.git(self.p, "commit", "-q", "--allow-empty", "-m", msg)
        self.new = tm.git(self.p, "rev-parse", "HEAD")

    def pr(self, files=NON_CORE, **fields):
        view = {"state": "OPEN", "headRefName": BRANCH, "mergeable": "MERGEABLE"}
        view.update(fields)
        self.h.gh(files, head=fields.pop("head", self.tip), extra={k: v for k, v in view.items() if k != "head"})

    def accepts(self, n, sha=None, **kw):
        self.h.seed(*[tm.rec("accept", REPO, 7, sha or self.tip, agent_id=f"argus{i + 1}", **kw) for i in range(n)])

    def push(self, cmd=None, role="domain-coordinator"):
        return self.h.pre(cmd or f"git push origin {BRANCH}", role=role, pdir=KIT, cwd=KIT)

    def gh_calls(self):
        log = self.h.j("gh.log")
        return open(log).read() if os.path.exists(log) else ""


def stopped(name, got):
    check(name, got[0] == "deny" and HINT in got[1] and "pantheon task new" in got[1] and "Б: <причина>" in got[1],
          got)


def passed(name, got):
    check(name, got[0] == "allow", got)


def t_accepted_core(h):
    """Ядро: два «принять» на Opus на вершине ветки, «вернуть» нет — push нового коммита остановлен (и окну без роли)."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    for who, role in ROLES:
        got = s.push(role=role)
        stopped(f"ядро, два Opus «принять» — {who}: push остановлен", got)
        check(f"ядро — {who}: в подсказке PR, число и нужное", f"{REPO}#7" in got[1] and "argus 2 (нужно 2)" in got[1],
              got)
    stopped("git push без аргументов (ветка по @{push}) — остановлен", s.push("git push"))
    stopped("git push origin HEAD — остановлен", s.push("git push origin HEAD"))
    stopped(f"git push origin HEAD:{BRANCH} — остановлен", s.push(f"git push origin HEAD:{BRANCH}"))


def t_core_one(h):
    """Ядро: одно «принять» — мало (нужно два Opus): push идёт."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(1)
    for who, role in ROLES:
        passed(f"ядро, одно «принять» — {who}: push идёт", s.push(role=role))


def t_core_not_opus(h):
    """Ядро: два «принять» не на Opus в ядре не засчитаны (как в шлюзе) — push идёт."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2, checklist=dict(tm.CHECKLIST, ran="модель: claude-sonnet-4-5, тесты 10 из 10"))
    passed("ядро, два «принять» не на Opus: push идёт", s.push())


def t_non_core_one(h):
    """Вне ядра: одного «принять» (любая модель) хватает — push остановлен."""
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1, checklist=dict(tm.CHECKLIST, ran="модель: claude-sonnet-4-5, тесты 10 из 10"))
    for who, role in ROLES:
        got = s.push(role=role)
        stopped(f"вне ядра, одно «принять» — {who}: push остановлен", got)
        check(f"вне ядра — {who}: нужно 1", "argus 1 (нужно 1)" in got[1], got)


def t_non_core_files_fail(h):
    """Вне ядра, а список файлов PR не получен: считаем ядром (нужно два) — одно «принять» push не останавливает."""
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1)
    open(h.j("gh.api.fail"), "w").close()
    passed("файлы PR не получены, одно «принять»: push идёт", s.push())


def t_reject(h):
    """«Вернуть» на вершине: push идёт — и от третьего argus, и последним словом того, кто принял."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    h.seed(tm.rec("reject", REPO, 7, s.tip, agent_id="argus3"))
    for who, role in ROLES:
        passed(f"два «принять» и «вернуть» третьего — {who}: push идёт", s.push(role=role))
    h.reset()
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1)
    h.seed(tm.rec("reject", REPO, 7, s.tip, agent_id="argus1"))
    passed("«принять», затем «вернуть» того же argus: push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(CORE_FILES)
    h.seed(tm.rec("reject", REPO, 7, s.tip, agent_id="argus3"))
    s.accepts(2)
    passed("«вернуть» третьего раньше двух «принять» на том же head (итог review status: вернуть 1): push идёт",
           s.push())


def t_reject_floor(h):
    """«Вернуть» на другом head после «принять» (отсечка _floor шлюза): прежние «принять» не в счёт — push идёт."""
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(2)
    h.seed(tm.rec("reject", REPO, 7, tm.OLD, agent_id="argus3"))
    passed("«вернуть» после «принять» (на старом head): push идёт", s.push())


def t_off_base_lie(h):
    """Д6 долга #388: «принять» на другой base PR (base_counts, metis-0965) и с полем «вернули», которое называет
    рецензента без «вернуть» на PR (returned_lie, metis-0497), push не останавливают — как в шлюзе."""
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1, base="release")
    passed("вне ядра, «принять» на base release, PR на main: push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1, base=None)
    passed("вне ядра, «принять» без поля base (до 0965): push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(NON_CORE)
    h.seed(dict(tm.rec("accept", REPO, 7, s.tip, agent_id="argus1"), returned=["12345678/9abcdef0"]))
    passed("вне ядра, «принять» с полем «вернули» без «вернуть» в журнале: push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(NON_CORE)
    h.seed(dict(tm.rec("accept", REPO, 7, s.tip, agent_id="argus1"), returned=["argus1"]))
    stopped("контроль: поле «вернули» называет самого рецензента (не сверяется) — push остановлен", s.push())
    h.reset()
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(1)
    h.seed(tm.rec("accept", REPO, 7, s.tip, agent_id="argus2", base="release"))
    passed("ядро: два «принять», одно на base release — засчитано одно, push идёт", s.push())


def t_no_verdicts(h):
    """Без вердиктов — push идёт, gh не зовётся (нет записей «принять» на вершине)."""
    s = Push(h)
    s.pr(CORE_FILES)
    for who, role in ROLES:
        passed(f"без вердиктов — {who}: push идёт", s.push(role=role))
    h.seed(tm.rec("tests", REPO, 7, s.tip))
    passed("только запись tests: push идёт", s.push())
    check("без «принять» gh не вызван", "pr view" not in s.gh_calls(), s.gh_calls())
    s.accepts(2, sha=tm.OLD)
    passed("«принять» только на старом head: push идёт", s.push())
    check("«принять» не на вершине — gh не вызван", "pr view" not in s.gh_calls(), s.gh_calls())


def t_gh_fail(h):
    """Нет сети (gh падает): push идёт."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    open(h.j("gh.fail"), "w").close()
    for who, role in ROLES:
        passed(f"gh падает — {who}: push идёт", s.push(role=role))
    os.remove(h.j("gh.fail"))
    tm.Home.write_view(h, "agent-kit", raw="не json")
    passed("ответ gh pr view не JSON: push идёт", s.push())


def t_blocker_line(h):
    """Строка «Б: <причина>» в новом коммите (правка блокера) — push идёт; без двоеточия и пустая — нет."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    s.commit("guard: правка\n\nБ: argus Б1 — красный тест test_push_accepted")
    passed("строка «Б: …» в новом коммите: push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    s.commit("guard: правка\n\nБ2: владелец — блокер слияния")
    passed("строка «Б2: …»: push идёт", s.push())
    h.reset()
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    s.commit("guard: Б-правка без строки\n\nБ:   \nпро Б: в середине строки")
    stopped("«Б:» без причины и не в начале строки: push остановлен", s.push())


def t_not_this_pr(h):
    """PR закрыт, слит, на другой ветке или другом head, конфликт с base — push идёт."""
    for why, fields in (("PR слит", {"state": "MERGED"}), ("PR закрыт", {"state": "CLOSED"}),
                        ("у PR другая ветка", {"headRefName": "other"}), ("у PR другой head", {"head": tm.OLD}),
                        ("конфликт с base", {"mergeable": "CONFLICTING"})):
        h.reset()
        s = Push(h)
        s.pr(CORE_FILES, **fields)
        s.accepts(2)
        passed(f"{why}: push идёт", s.push())


def t_same_commit(h):
    """Отправляется тот же коммит, что на remote (вершина), — новых вердиктов не сожжёт: push идёт."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    tm.git(s.p, "reset", "-q", "--hard", s.tip)
    passed("тот же коммит: push идёт", s.push())
    passed("другой ветке без «принять»: push идёт", s.push("git push origin HEAD:feat-other"))


def t_remote_url(h):
    """Remote адресом, а не именем, — tracking-ветки нет: push идёт (не судим)."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    passed("remote адресом: push идёт", s.push(f"git push https://github.com/{REPO} {BRANCH}"))


def _main_commit(s, name, msg):
    """Коммит в main на remote (refs/remotes/origin/main) поверх init main: файл name, сообщение msg."""
    tm.git(s.p, "checkout", "-q", "-B", "main-work", s.h.sha["agent-kit"])
    with open(os.path.join(s.p, name), "w") as fh:
        fh.write(name + "\n")
    tm.git(s.p, "add", name)
    tm.git(s.p, "commit", "-q", "-m", msg)
    tm.git(s.p, "update-ref", "refs/remotes/origin/main", tm.git(s.p, "rev-parse", "HEAD"))
    tm.git(s.p, "checkout", "-q", BRANCH)


class FilePush(Push):
    """Как Push, но вершина PR правит файл pr.txt (собственный дифф PR не пуст), а base в gh pr view — init main
    (коммит есть в git папки): отпечаток переноса «принять» считается."""

    def __init__(self, h):
        self.h, self.p = h, h.j(KIT)
        tm.git(self.p, "checkout", "-q", "-B", BRANCH, h.sha["agent-kit"])
        tm.git(self.p, "update-ref", "-d", "refs/remotes/origin/main")
        with open(os.path.join(self.p, "pr.txt"), "w") as fh:
            fh.write("pr\n")
        tm.git(self.p, "add", "pr.txt")
        tm.git(self.p, "commit", "-q", "-m", "правка PR")
        self.tip = self.new = tm.git(self.p, "rev-parse", "HEAD")
        tm.git(self.p, "update-ref", f"refs/remotes/origin/{BRANCH}", self.tip)
        tm.git(self.p, "config", f"branch.{BRANCH}.remote", "origin")
        tm.git(self.p, "config", f"branch.{BRANCH}.merge", f"refs/heads/{BRANCH}")

    def pr(self, files=NON_CORE, **fields):
        super().pr(files, **dict({"baseRefOid": self.h.sha["agent-kit"], "baseRefName": "main"}, **fields))

    def merge_main(self):
        tm.git(self.p, "merge", "-q", "--no-edit", "refs/remotes/origin/main")
        self.new = tm.git(self.p, "rev-parse", "HEAD")


def t_force(h):
    """metis-0809: amend и принудительная отправка (--force-with-lease, +ветка, -f) в принятый PR — окну без роли
    отказ, как новому коммиту; роли — отказ правилом push (флаг); amend со строкой «Б: …» — push идёт."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    tm.git(s.p, "reset", "-q", "--hard", s.tip)
    tm.git(s.p, "commit", "-q", "--amend", "--allow-empty", "-m", "правка PR, amend: долг ревью")
    for cmd in (f"git push --force-with-lease origin {BRANCH}", f"git push origin +{BRANCH}",
                f"git push -f origin {BRANCH}", f"git push --force origin HEAD:{BRANCH}",
                f"git push --force-with-lease={BRANCH} origin {BRANCH}", f"git push -uf origin {BRANCH}",
                "git push --force-with-lease", f"git push --force-if-includes --force-with-lease origin +HEAD:{BRANCH}"):
        stopped(f"окно без роли, «{cmd}»: push остановлен", s.push(cmd, role=None))
    got = s.push(f"git push --force-with-lease origin {BRANCH}")
    check("роль, --force-with-lease: отказ правилом push (флаг)", got[0] == "deny" and "--force-with-lease" in got[1],
          got)
    passed("окно без роли, удаление ветки (-d) — не судим: push идёт", s.push(f"git push -d origin {BRANCH}", role=None))
    tm.git(s.p, "commit", "-q", "--amend", "--allow-empty", "-m", "правка PR\n\nБ: argus Б1 — красный тест")
    passed("окно без роли, amend со строкой «Б: …» и --force-with-lease: push идёт",
           s.push(f"git push --force-with-lease origin {BRANCH}", role=None))


def t_blocker_from_main(h):
    """metis-0809: «Б:» только из коммитов PR. main со строкой «Б:» подтянут слиянием, а сверху свой коммит долга без
    «Б:» — push остановлен (раньше «Б:» из main его пропускал)."""
    s = FilePush(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    _main_commit(s, "main.txt", "guard: правка в main\n\nБ: argus Б1 — блокер другого PR")
    s.merge_main()
    with open(os.path.join(s.p, "debt.txt"), "w") as fh:
        fh.write("долг\n")
    tm.git(s.p, "add", "debt.txt")
    s.commit("долг ревью Д-A")
    for who, role in ROLES:
        stopped(f"«Б:» только в коммите main, свой коммит без «Б:» — {who}: push остановлен", s.push(role=role))
    s.commit("правка блокера\n\nБ: argus Б1 — красный тест")
    passed("«Б:» в своём коммите PR поверх слияния main: push идёт", s.push())


def t_base_merge(h):
    """metis-0809: подтянуть main без правок (merge-rounds.md) — push идёт: собственный дифф PR тот же, шлюз перенесёт
    «принять». Слияние с правкой (дифф PR другой) — остановлен, подсказка называет git merge; отпечаток не посчитать
    (base PR нет в git папки) — пропуск."""
    s = FilePush(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    _main_commit(s, "main.txt", "pantheon: правка в main")
    s.merge_main()
    for who, role in ROLES:
        passed(f"чистое слияние origin/main — {who}: push идёт", s.push(role=role))
    h.reset()
    s = FilePush(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    _main_commit(s, "main.txt", "pantheon: правка в main")
    s.merge_main()
    with open(os.path.join(s.p, "pr.txt"), "w") as fh:
        fh.write("pr, правка при слиянии\n")
    tm.git(s.p, "add", "pr.txt")
    tm.git(s.p, "commit", "-q", "--amend", "--no-edit")
    s.new = tm.git(s.p, "rev-parse", "HEAD")
    got = s.push(role=None)
    stopped("слияние main с правкой своего файла: push остановлен", got)
    check("подсказка называет подтягивание base без правок", "git merge origin/<base>" in got[1], got)
    h.reset()
    s = FilePush(h)
    s.pr(CORE_FILES, baseRefOid=tm.BASE)
    s.accepts(2)
    _main_commit(s, "main.txt", "pantheon: правка в main")
    s.merge_main()
    with open(os.path.join(s.p, "debt.txt"), "w") as fh:
        fh.write("долг\n")
    tm.git(s.p, "add", "debt.txt")
    tm.git(s.p, "commit", "-q", "--amend", "--no-edit")
    s.new = tm.git(s.p, "rev-parse", "HEAD")
    passed("слияние, а base PR нет в git папки (отпечаток не посчитать): push идёт", s.push())


def t_checklist(h):
    """«Принять» без перечня проверенного (старый формат, Б6) не засчитано, как в шлюзе: вне ядра — push идёт."""
    s = Push(h)
    s.pr(NON_CORE)
    s.accepts(1, checklist=None)
    passed("вне ядра, одно «принять» без перечня: push идёт", s.push())
    s.accepts(1, checklist={"opened": "x", "ran": "модель: claude-opus-5-5", "unchecked": " "})
    passed("вне ядра, «принять» с пустым полем перечня: push идёт", s.push())


def t_parse_fail_open(h):
    """metis-0809: разбор push внутри try — git не запустить (нет в PATH): окно без роли не останавливается."""
    s = Push(h)
    s.pr(CORE_FILES)
    s.accepts(2)
    got = h.pre("git push", role=None, pdir=KIT, cwd=KIT, extra_env={"PATH": h.j("bin")})
    passed("git нет в PATH, git push без аргументов — окно без роли: push идёт", got)


def t_files_parallel(h):
    """metis-0809: файлы PR запрашиваются вместе с gh pr view, а не после, только если осталось время. Время кончилось
    после view (_gh_fits: да, затем нет) — PR вне ядра с одним «принять» всё равно узнан: push остановлен."""
    import threading
    s = Push(h)
    mg = tm._load_merge_gate("merge_gate_push")
    started = threading.Event()
    view = {"state": "OPEN", "headRefName": BRANCH, "headRefOid": s.tip, "mergeable": "MERGEABLE",
            "baseRefOid": tm.BASE, "baseRefName": "main", "changedFiles": len(NON_CORE)}
    waited = []

    def gh(args):
        if args[0] == "api":
            started.set()
            return [{"filename": f, "status": "modified"} for f in NON_CORE]
        waited.append(started.wait(10))
        return [dict(view)]
    fits = iter([True])
    mg._gh_json = gh
    mg._gh_fits = lambda: next(fits, False)
    mg.read_records = lambda: [tm.rec("accept", REPO, 7, s.tip)]
    why = mg.accepted_push_problem(s.p, "origin", [("HEAD", BRANCH)])
    check("время кончилось после gh pr view: PR вне ядра узнан — push остановлен", why and HINT in why, why)
    check("gh pr view дождался запроса файлов (запросы параллельно)", waited == [True], waited)


LIGHT_FILES = [{"filename": "plugins/guard/tests/test_new.py", "status": "added", "additions": 9, "deletions": 0},
               {"filename": "README.md", "status": "modified", "additions": 1, "deletions": 1,
                "patch": "@@ -1 +1 @@\n-a\n+b"}]


def t_light_core(h):
    """metis-1065: лёгкий PR ядра (только добавленные тесты и README) — хватает одного «принять» Opus с effort high,
    как в шлюзе владельца: push остановлен. Effort medium, без efforts, не лёгкий PR — нужно два, push идёт."""
    def case(files, efforts):
        h.reset()
        s = Push(h)
        s.pr(files)
        r = tm.rec("accept", REPO, 7, s.tip)
        r["models"] = ["claude-opus-5-5"]
        if efforts is not None:
            r["efforts"] = efforts
        h.seed(r)
        return s.push()
    got = case(LIGHT_FILES, ["high"])
    stopped("лёгкий PR ядра, одно «принять» Opus high: push остановлен", got)
    check("лёгкий PR ядра: нужно 1", "argus 1 (нужно 1)" in got[1], got)
    passed("лёгкий PR ядра, одно «принять» Opus medium: push идёт", case(LIGHT_FILES, ["medium"]))
    passed("лёгкий PR ядра, одно «принять» без efforts: push идёт", case(LIGHT_FILES, None))
    heavy = [dict(LIGHT_FILES[0], deletions=1), LIGHT_FILES[1]]
    passed("удалённая строка в тесте — не лёгкий, одно «принять» Opus high: push идёт", case(heavy, ["high"]))
    passed("ядро (merge_gate.py), одно «принять» Opus high: push идёт", case(CORE_FILES, ["high"]))


def t_light_head_swap(h):
    """metis-1065, TOCTOU: файлы PR идут отдельным запросом — после него gh pr view ещё раз. Push в PR между запросами
    (head другой или changedFiles другие), gh не ответил, время хука кончилось — не лёгкий: одного «принять» Opus high
    мало, push идёт. Тот же head и число файлов — лёгкий, push остановлен."""
    s = Push(h)
    view = {"state": "OPEN", "headRefName": BRANCH, "headRefOid": s.tip, "mergeable": "MERGEABLE",
            "baseRefOid": tm.BASE, "baseRefName": "main", "changedFiles": len(LIGHT_FILES)}

    def case(after, fits=True):
        mg = tm._load_merge_gate("merge_gate_swap")
        views = iter([[dict(view)], after])
        calls = []

        def gh(args):
            calls.append(args[:2])
            if args[0] == "api" and "/files" in args[1]:
                return [dict(f) for f in LIGHT_FILES]
            return next(views, None) if args[:2] == ["pr", "view"] else None
        mg._gh_json = gh
        left = iter([True, fits])
        mg._gh_fits = lambda: next(left, False)
        r = tm.rec("accept", REPO, 7, s.tip)
        r["models"], r["efforts"] = ["claude-opus-5-5"], ["high"]
        mg.read_records = lambda: [r]
        return mg.accepted_push_problem(s.p, "origin", [("HEAD", BRANCH)]), calls
    why, calls = case([dict(view)])
    check("head и число файлов те же после списка файлов: лёгкий, push остановлен",
          why and HINT in why and "(нужно 1)" in why, why)
    check("gh pr view спрошен второй раз после файлов", calls.count(["pr", "view"]) == 2, calls)
    other = "f" * 40
    for name, after, fits in (("head сменился между запросами", [dict(view, headRefOid=other)], True),
                              ("changedFiles сменилось между запросами", [dict(view, changedFiles=3)], True),
                              ("changedFiles true вместо числа", [dict(view, changedFiles=True)], True),
                              ("второй gh pr view не ответил", None, True),
                              ("время хука кончилось до второго gh pr view", [dict(view)], False)):
        why, _ = case(after, fits)
        check(f"{name}: не лёгкий, одного «принять» мало — push идёт", why is None, why)


def t_core_count_same():
    """CORE_ACCEPTS проверки push равно MIN_ACCEPTS шлюза владельца (pantheon merge.py): числа не разъехались."""
    want = re.search(r"^MIN_ACCEPTS = (\d+)", open(MERGE_PY, encoding="utf-8").read(), re.M)
    got = re.search(r"^CORE_ACCEPTS = (\d+)", open(GATE_PY, encoding="utf-8").read(), re.M)
    check("CORE_ACCEPTS == MIN_ACCEPTS", want and got and want.group(1) == got.group(1), (want, got))


CASES = [t_accepted_core, t_core_one, t_core_not_opus, t_non_core_one, t_non_core_files_fail, t_reject, t_reject_floor,
         t_off_base_lie, t_no_verdicts, t_gh_fail, t_blocker_line, t_not_this_pr, t_same_commit, t_remote_url, t_force,
         t_blocker_from_main, t_base_merge, t_checklist, t_parse_fail_open, t_files_parallel, t_light_core, t_light_head_swap]


def main():
    t_core_count_same()
    base = None if not os.path.realpath(tempfile.gettempdir()).startswith(("/tmp", "/private/tmp")) else "/var/tmp"
    tmp = os.path.realpath(mkroot("push-accepted-test-", first=base))
    try:
        h = tm.Home(tmp)
        only = set(sys.argv[1:])
        for case in CASES:
            if only and case.__name__ not in only:
                continue
            h.reset()
            case(h)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
