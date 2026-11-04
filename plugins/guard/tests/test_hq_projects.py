#!/usr/bin/env python3
"""hq-projects (metis-0771): окно штаба (PANTHEON_ROLE=hq, и его субагенты) не читает папки проектов направлений —
Read, Grep, Glob — отказ с именем координатора. Открыты README.md, AGENTS.md в корне, .git, agent-kit (metis-pantheon),
направления с coordinator = false и ~/ai; Bash правило не судит (песочница — pantheon/test_tick). Строки модели угроз —
drafts/0771-threat-model.md.

Запуск: python3 -I plugins/guard/tests/test_hq_projects.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
RULES = os.path.join(os.path.dirname(GUARD), "guard_rules.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-hqproj-"))
os.environ["HOME"] = root
try:
    for d in ("projects/alexbroker/docs", "projects/alexbroker/.git", "projects/agent-kit", "projects/solo",
              "ai/pantheon/directions/hermes-alex/inbox", "ai/knowledge", ".local/state/pantheon", "links"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    os.symlink(os.path.join(root, "projects/alexbroker"), os.path.join(root, "links/ab"))
    with open(os.path.join(root, ".local/state/pantheon/domains.json"), "w") as fh:
        json.dump({"domains": {"hermes-alex": ["~/projects/alexbroker"], "metis-pantheon": ["~/projects/agent-kit"],
                               "mnemo-brain": ["~/ai/knowledge"], "solo-led": ["~/projects/solo"],
                               "wide": ["~/projects"]}}, fh)
    with open(os.path.join(root, "ai/pantheon/directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "solo-led"\ncoordinator = false\n')
    spec = importlib.util.spec_from_file_location("guard_under_test", RULES)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    P = os.path.join(root, "projects/alexbroker")

    def run(tool, inp, role="hq", agent_type=None):
        if role:
            os.environ["PANTHEON_ROLE"] = role
        else:
            os.environ.pop("PANTHEON_ROLE", None)
        ev = {"cwd": os.path.join(root, "ai/pantheon")}
        if agent_type:
            ev["agent_type"] = agent_type
        return g.check_hq_projects(ev, tool, inp)

    r = run("Read", {"file_path": P + "/docs/reviews-gaps.md"})
    check("1 Read файла проекта — отказ с именем координатора, inbox и pantheon start",
          bool(r) and "hq-projects" in r and "hermes-alex" in r
          and "~/ai/pantheon/directions/hermes-alex/inbox/" in r and "pantheon start hermes-alex" in r, r)
    r = run("Grep", {"pattern": "отзыв", "path": P + "/docs"})
    check("2 Grep внутри проекта — отказ", bool(r) and "hermes-alex" in r, r)
    r = run("Grep", {"pattern": "отзыв", "path": os.path.join(root, "projects")})
    check("2 Grep выше проекта (~/projects) — отказ", bool(r) and "hermes-alex" in r, r)
    r = run("Glob", {"pattern": P + "/**/*.md"})
    check("3 Glob абсолютный шаблон — отказ", bool(r) and "hermes-alex" in r, r)
    r = run("Glob", {"pattern": "**/*.html", "path": P})
    check("3 Glob с path проекта — отказ", bool(r), r)
    r = run("Read", {"file_path": P + "/docs/x.md"}, role="", agent_type="hq")
    check("5 agent_type hq без PANTHEON_ROLE — отказ", bool(r), r)
    r = run("Read", {"file_path": P + "/docs/x.md"}, agent_type="Explore")
    check("5 субагент Explore окна hq — отказ", bool(r), r)
    r = run("Read", {"file_path": P + "/docs/x.md"}, agent_type="palamedes")
    check("5 субагент palamedes окна hq — отказ", bool(r), r)
    r = run("Read", {"file_path": os.path.join(root, "links/ab/docs/x.md")})
    check("7 ссылка в проект — отказ (realpath)", bool(r) and "hermes-alex" in r, r)
    for cmd in ("pantheon outside status", "pantheon merge status 290", "pantheon board", f"git -C {P} log -3",
                f"git -C {P} rev-parse HEAD", f"cat {P}/docs/x.md"):
        r = run("Bash", {"command": cmd})
        check(f"9 Bash не судится правилом: {cmd.split(root)[0][:30]}", not r, r)
    for f in ("README.md", "AGENTS.md", "readme.md", ".git/HEAD", ".git/logs/HEAD"):
        r = run("Read", {"file_path": P + "/" + f})
        check(f"10/11 открыт {f}", not r, r)
    r = run("Read", {"file_path": P + "/docs/README.md"})
    check("10 README.md не в корне — отказ", bool(r), r)
    r = run("Grep", {"pattern": "x", "path": P + "/.git"})
    check("11 Grep по .git — проходит", not r, r)
    for p in ("ai/pantheon/directions/hermes-alex/inbox/x.md", "ai/pantheon/directions/hermes-alex/STATUS.md",
              "ai/knowledge/note.md"):
        r = run("Read", {"file_path": os.path.join(root, p)})
        check(f"12 открыт ~/{p}", not r, r)
    r = run("Grep", {"pattern": "x", "path": os.path.join(root, "ai")})
    check("12 Grep по ~/ai — проходит", not r, r)
    r = run("Read", {"file_path": os.path.join(root, "projects/agent-kit/plugins/x.py")})
    check("13 agent-kit (metis-pantheon) открыт", not r, r)
    r = run("Read", {"file_path": os.path.join(root, "projects/solo/x.py")})
    check("13 направление с coordinator = false открыто", not r, r)
    r = run("Read", {"file_path": os.path.join(root, "projects/other/x.py")})
    check("13 папка ~/projects у направления (содержит agent-kit) не закрывает чужое", not r, r)
    for role, at in (("domain-coordinator", None), ("", None), ("", "Explore")):
        r = run("Read", {"file_path": P + "/docs/x.md"}, role=role, agent_type=at)
        check(f"14 вне окна hq не действует: роль {role or '-'} / {at or '-'}", not r, r)
    os.environ["PANTHEON_ROLE"] = "hq"
    r = g.check_roles({"cwd": root}, "Read", {"file_path": P + "/docs/x.md"})
    check("check_roles: правило подключено", isinstance(r, str) and "hq-projects" in r, r)
finally:
    os.environ.pop("PANTHEON_ROLE", None)
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
