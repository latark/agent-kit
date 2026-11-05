#!/usr/bin/env python3
"""Push в принятый PR (metis-0794): git push нового коммита в ветку открытого PR, у которого на текущем head «принять»
argus столько, сколько нужно для слияния (ядро — два Opus, вне ядра — одно), а «вернуть» нет, guard останавливает
подсказкой «долг — задачей, PR — к слиянию»; ролям и окнам без роли одинаково. С «вернуть», без вердиктов, при сбое
gh, со строкой «Б: …» в новом коммите и в прочих случаях push идёт как раньше (fail-open). Хук — настоящий, gh —
поддельный и HOME — временный из test_merge_gate.
Запуск: python3 -I plugins/guard/tests/test_push_accepted.py   (код 0 — все прошли)
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_merge_gate as tm  # noqa: E402  (Home, rec, git — помощники запора слияния)
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


def t_core_count_same():
    """CORE_ACCEPTS проверки push равно MIN_ACCEPTS шлюза владельца (pantheon merge.py): числа не разъехались."""
    want = re.search(r"^MIN_ACCEPTS = (\d+)", open(MERGE_PY, encoding="utf-8").read(), re.M)
    got = re.search(r"^CORE_ACCEPTS = (\d+)", open(GATE_PY, encoding="utf-8").read(), re.M)
    check("CORE_ACCEPTS == MIN_ACCEPTS", want and got and want.group(1) == got.group(1), (want, got))


CASES = [t_accepted_core, t_core_one, t_core_not_opus, t_non_core_one, t_non_core_files_fail, t_reject, t_reject_floor,
         t_no_verdicts, t_gh_fail, t_blocker_line, t_not_this_pr, t_same_commit, t_remote_url]


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
