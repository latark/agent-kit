#!/usr/bin/env python3
"""guard, часть «merge»: gh pr merge: [merge], [merge_repos] и -R, схема guard 0.5.0, защиты через запор (кто, где, в каком виде), защиты по remote и сбой — отказ (2eda45f), лиды, тексты отказов по режиму.

Общее (подменённый HOME, фикстуры, вызов хука внутри процесса и через процесс, прогон таблицы) — _guard_common.py;
разрез test_guard.py — metis-1148 (план 1.0, Т2).
Запуск: python3 -I plugins/guard/tests/test_guard_merge.py   (код выхода 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard_common import *  # noqa: E402, F403


def merge_security_checks(home, cases):
    """Находка проверки безопасности 2eda45f: защиты по remote, любой сбой — отказ; лиды (metis-0054). С guard 0.5.4
    поштучного «да» владельца нет — его заменил запор (test_merge_gate_*.py). Возвращает число упавших проверок."""
    failed = 0
    ak, ec = "projects/agent-kit", "projects/lecture-notes"

    def check(name, ok):
        nonlocal failed
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} {name}")

    def M(h, cmd, pdir=ak, cwd=None, tuid=None, raw=False):
        return run(h, pdir, "domain-coordinator", "Bash", {"command": cmd}, cwd=cwd, tuid=tuid, raw=raw)

    def variant(policy_fn=None, domains_fn=None):
        h = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
        setup(h)
        if policy_fn:
            pol = os.path.join(h, ".claude/pantheon/policy.toml")
            text = _read(pol)
            with open(pol, "w") as fh:
                fh.write(policy_fn(text))
        if domains_fn:
            dom = os.path.join(h, ".local/state/pantheon/domains.json")
            text = _read(dom)
            with open(dom, "w") as fh:
                fh.write(domains_fn(text))
        return h

    deny = lambda out: '"deny"' in out
    # --- сбой в политике и реестре — отказ по правилу, а не пропуск и не сбой скрипта ---
    for name, kw in (
            ("нет metis-pantheon в [coordinators]",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]\n', ""))),
            ("metis-pantheon строкой",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', 'metis-pantheon = "~/projects/agent-kit"'))),
            ("metis-pantheon пустой список",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', "metis-pantheon = []"))),
            ("metis-pantheon не из строк",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', "metis-pantheon = [1]"))),
            # guard читает [private] мягко (0163, проверка умолчаний — test_misc.py), а шлюз слияния на неверном — закрыт
            ("[private].coordinators не из строк", dict(policy_fn=lambda t: t + "\n[private]\ncoordinators = [1]\n")),
            ("[private].paths строкой", dict(policy_fn=lambda t: t + '\n[private]\npaths = "~/ai/knowledge/me"\n')),
            ("domains.json битый", dict(domains_fn=lambda t: "{не json")),
            ("domains.json: папки строкой",
             dict(domains_fn=lambda t: json.dumps({"domains": {"themis-library": "~/projects/lecture-notes"}}))),
            ("domains.json без направлений", dict(domains_fn=lambda t: '{"domains": {}}')),
            ("два направления с одним корнем",
             dict(domains_fn=lambda t: json.dumps(dict(json.loads(t), domains=dict(
                 json.loads(t)["domains"], **{"themis-twin": ["~/projects/lecture-notes"]}))))),
    ):
        out = run(variant(**kw), ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True)
        check(f"сбой — отказ: {name}", deny(out) and "сбой проверки" not in out)
    # 0163: отказ на неверном [private] — именно по [private]; пустой список coordinators — «никого», слияние как было
    out = run(variant(policy_fn=lambda t: t + "\n[private]\ncoordinators = [1]\n"), ec, "domain-coordinator", "Bash",
              {"command": "gh pr merge 1"}, raw=True)
    check("[private].coordinators = [1] — отказ называет [private]",
          deny(out) and ("[private] в policy.toml не разобрать" in out))
    got = M(variant(policy_fn=lambda t: t + "\n[private]\ncoordinators = []\nroles = []\n"), "gh pr merge 1", pdir=ec)
    check(f"[private] с пустыми roles и coordinators — слияние как было: {got}", got == "allow")
    # paths = [] — умолчание, как у guard (private_conf; ревью PR #35): шлюз не закрывается, личное не открывается
    hp = variant(policy_fn=lambda t: t + "\n[private]\npaths = []\n")
    got = M(hp, "gh pr merge 1", pdir=ec)
    check(f"[private] paths = [] — слияние как было: {got}", got == "allow")
    me = os.path.join(hp, "ai/knowledge/me/finance.md")
    got = (run(hp, "projects/shopKeeperApp", "dev-sonnet", "Read", {"file_path": me}, sub=True),
           run(hp, ec, "domain-coordinator", "Bash", {"command": f"cat {me}"}))
    check(f"[private] paths = [] — личное закрыто: Read субагента и cat координатора — отказ: {got}",
          got == ("deny", "deny"))
    got = M(variant(policy_fn=lambda t: t + '\n[private]\npaths = [" "]\n'), "gh pr merge 1", pdir=ec)
    check(f'[private] paths = [" "] — отказ, как раньше: {got}', got == "deny")
    # -R latark/agent-kit в чужом [merge_repos] — это защиты, а не внутреннее
    h = variant(policy_fn=lambda t: t.replace('themis-library = ["latark/lecture-notes", "latark/law-feed"]',
                                              'themis-library = ["latark/lecture-notes", "latark/agent-kit"]'))
    got = (M(h, "gh pr merge 5 -R latark/agent-kit", pdir=ec), M(h, "gh pr merge 2 -R latark/lecture-notes", pdir=ec))
    check(f"защиты по -R: latark/agent-kit в [merge_repos] Фемиды — отказ, свой -R — как было: {got}",
          got == ("deny", "allow"))
    # корень направления-родитель («~/projects») не открывает папку другого направления внутри
    # широкий корень — первым в реестре: проверка «по первому совпадению» отдала бы ему sitebuilder
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict({"zeta-wide": ["~/projects"]},
                                                                 **json.loads(t)["domains"])}),
                policy_fn=lambda t: t.replace("[merge_repos]\n", '[merge_repos]\nzeta-wide = ["latark/zz-own"]\n'))
    git_repo(os.path.join(h, "projects/zz-own"), "main", "https://github.com/latark/zz-own")
    os.makedirs(os.path.join(h, "projects/zz-plain"), exist_ok=True)
    got = (M(h, "gh pr merge 1", pdir="projects", cwd="projects/sitebuilder"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-own"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-plain"))
    check(f"чужая папка: корень «~/projects» над sitebuilder — отказ, своя папка — можно, не репозиторий git — отказ: {got}",
          got == ("deny", "allow", "deny"))
    # битая запись одного направления не выпадает молча: иначе его папку «унаследовал» бы широкий корень
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict(json.loads(t)["domains"], **{
        "zeta-wide": ["~/projects"], "hermes-site": "~/projects/sitebuilder"})}))
    out = M(h, "gh pr merge 1", pdir="projects", cwd="projects/sitebuilder", raw=True)
    check("сбой — отказ: папки одного направления строкой — широкий корень не получает его папку",
          deny(out) and ("domains.json" in out))
    # ревью argus 210766a: domains.json битый или удалён — без отката на старый ~/.claude/hooks/domains.json, где
    # направление шире (broker = shopKeeperApp + sitebuilder + law-feed): Гермес слил бы в law-feed
    legacy = {"domains": {"broker": ["~/projects/shopKeeperApp", "~/projects/sitebuilder", "~/projects/law-feed"]}}
    for label, broken in (("битый", True), ("удалён", False)):
        h = variant()
        os.makedirs(os.path.join(h, ".claude/hooks"), exist_ok=True)
        with open(os.path.join(h, ".claude/hooks/domains.json"), "w") as fh:
            json.dump(legacy, fh)
        dom = os.path.join(h, ".local/state/pantheon/domains.json")
        if broken:
            with open(dom, "w") as fh:
                fh.write("{не json")
        else:
            os.remove(dom)
        out = M(h, "gh pr merge 2", pdir="projects/sitebuilder", cwd="projects/law-feed", raw=True)
        check(f"старый реестр: domains.json {label}, ~/.claude/hooks/domains.json есть — Гермес в law-feed — отказ",
              deny(out) and ("domains.json" in out))
    # папка защит с .git, у которой remote не читается, — отказ всем; без .git — защищена только по пути
    h = variant(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]',
                                              'metis-pantheon = ["~/projects/agent-kit", "~/projects/broken-prot"]'))
    os.makedirs(os.path.join(h, "projects/broken-prot"), exist_ok=True)
    with open(os.path.join(h, "projects/broken-prot/.git"), "w") as fh:
        fh.write("gitdir: /nonexistent-gitdir\n")
    out = M(h, "gh pr merge 1", pdir=ec, raw=True)
    os.remove(os.path.join(h, "projects/broken-prot/.git"))
    got = M(h, "gh pr merge 1", pdir=ec)
    check(f"сбой git: у папки защит сломан .git — отказ всем, без .git — как было: {got}",
          deny(out) and ("не читается git remote" in out) and got == "allow")
    # --- включение новой схемы строкой [merge_client]: без неё — как в 0.4.7 (решение лида, 15.10) ---
    no_client = lambda t: t.replace('[merge_client]\nathena-shop = ["~/projects/shopKeeperApp", '
                                    '"~/projects/broker-landing"]\n', "")
    h = variant(policy_fn=no_client)
    alex, br, lw = "projects/sitebuilder", "projects/shopKeeperApp", "projects/law-feed"
    got = (M(h, "gh pr merge 1", pdir=ec), M(h, "gh pr merge 2 -R latark/lecture-notes", pdir=lw),
           M(h, "gh pr merge 1", pdir=alex), M(h, "gh pr merge 1", pdir=br),
           M(h, "gh pr merge 5 --squash"), M(h, "gh pr merge 13"),
           M(h, "gh pr merge 3", cwd="projects/other/tg-read-dev"), M(h, "gh pr merge 1", pdir=ec, cwd=alex))
    check(f"без [merge_client] (схема 0.4.7): Фемида и её -R — можно, Гермес и Афина — нельзя, Метида в "
          f"agent-kit по записям запора — можно, без записей — нельзя, её внутренняя папка (нет в [merge]) — нельзя, "
          f"Фемида в чужой папке (cwd без cd) — нельзя: {got}",
          got == ("allow", "allow", "deny", "deny", "allow", "deny", "deny", "deny"))
    h = variant(policy_fn=lambda t: no_client(t) + "[merge_client]\n")
    got = (M(h, "gh pr merge 1", pdir=alex), M(h, "gh pr merge 1", pdir=br), M(h, "gh pr merge 1", pdir=ec))
    check(f"пустая [merge_client] — новая схема: Гермес, Афина и Фемида в своих папках — можно: {got}",
          got == ("allow", "allow", "allow"))
    h = variant(policy_fn=lambda t: 'merge_client = "x"\n' + no_client(t))  # ключ верхнего уровня — до таблиц
    got = M(h, "gh pr merge 1", pdir=alex)
    check(f"[merge_client] не таблицей — как без неё (0.4.7): Гермес — нельзя: {got}", got == "deny")
    # --- защиты через запор (guard 0.5.4): поштучного «да» нет, остальное — как было
    tg, br, alex = "projects/other/tg-read-dev", "projects/shopKeeperApp", "projects/sitebuilder"
    os.makedirs(os.path.join(home, ak, "sub"), exist_ok=True)
    got = (M(home, "gh pr merge 5 --squash", pdir=br, cwd=ak), M(home, "gh pr merge 5", pdir=br, cwd=ak + "/sub"),
           run(home, ak, "domain-coordinator", "Bash", {"command": "gh pr merge 5"}, sub=True),
           run(home, ak, "dev-sonnet", "Bash", {"command": "gh pr merge 5"}, sub=True),
           M(home, "gh pr merge 5 --auto"), M(home, "gh pr merge 5 6"),
           M(home, "gh pr merge 3 -R latark/tg-read --auto", cwd=tg), M(home, "gh pr merge 3 -R latark/sitebuilder", cwd=tg),
           M(home, f"cd {home}/{ak} && gh pr merge 5", cwd=tg), M(home, "GH_REPO=latark/agent-kit gh pr merge 5"))
    check(f"защиты: другой координатор в agent-kit, субагенты Метиды, --auto, два номера, -R вне [merge_repos], cd и "
          f"GH_REPO — отказ: {got}", got == ("deny",) * 10)
    out = M(home, "gh pr merge 5 --auto", raw=True)
    check("защиты: отказ не просит «да» владельца, а называет шлюз слияния и Д3",
          deny(out) and (("шлюз слияния" in out and "(Д3)" in out and "окн" not in out and "--subject" not in out)
                        ))

    # metis-0054: лид Метиды (hephaestus-pantheon субагентом) — по тем же правилам, что Метида
    def L(h, cmd, role="hephaestus-pantheon", pdir=ak, cwd=None, raw=False):
        return run(h, pdir, role, "Bash", {"command": cmd}, sub=True, cwd=cwd, raw=raw)
    got = (L(home, "gh pr merge 5 --squash"), L(home, "gh pr merge 3 -R latark/tg-read", cwd=tg))
    check(f"защиты: лид Метиды сливает защиты и -R из [merge_repos] по запору — можно: {got}",
          got == ("allow", "allow"))
    got = (L(home, "gh pr merge 5 --auto"), L(home, "gh pr merge 5 6"), L(home, "gh pr merge 3 -R latark/sitebuilder", cwd=tg),
           L(home, "gh pr merge 3 -R latark/tg-read -R latark/agent-kit", cwd=tg),
           L(home, "gh pr merge 5", pdir=br, cwd=ak), L(home, "gh pr merge 5", role="hephaestus-shop"),
           L(home, "gh pr merge 5", role="apollo-pantheon", pdir="ai/pantheon", cwd=ak))
    check(f"защиты: лид Метиды с --auto, двумя номерами, -R вне [merge_repos], двумя -R; лид Афины в "
          f"agent-kit и из своей сессии; лид в сессии штаба — отказ: {got}", got == ("deny",) * 7)
    # metis-0054: кто не лид — отказ с текстом «сливает лид или координатор, остальные — PR и отчёт лиду»
    for r in ("dev-sonnet", "argus", "talos", "prometheus", "hephaestus", "hephaestus-"):
        out = L(home, "gh pr merge 1", role=r, pdir=br, raw=True)
        check(f"merge: {r} субагентом — отказ, текст про лида и отчёт лиду",
              deny(out) and (("лид направления" in out and "отчёте лиду" in out)))
    out = L(home, "gh pr merge 4", role="hephaestus-shop", pdir=alex, raw=True)
    check("merge: лид чужого направления (hephaestus-shop в сессии hermes-site) — отказ, текст про своё направление",
          deny(out) and ("не лид направления этой сессии (hermes-site)" in out))
    out = L(home, "gh pr merge 1", role="hephaestus-shop", pdir=br, raw=True)
    check("merge: лид своего направления — можно (текст отказа не про лида)",
          not deny(out))
    # реестр «по ошибке» отдал agent-kit/sub Афине (athena-shop-2): его лид — hephaestus-shop-2, защиты ему закрыты
    got = (L(home, "gh pr merge 5", role="hephaestus-shop-2", pdir=ak + "/sub"),
           L(home, "gh pr merge 5 -R latark/agent-kit", role="hephaestus-shop-2", pdir=ak + "/sub"))
    check(f"merge: лид athena-shop-2 в agent-kit/sub (защиты) — отказ и с -R: {got}", got == ("deny", "deny"))
    # лид mnemo-brain: у направления личное — как и координатор, не сливает
    h = variant(domains_fn=lambda t: json.dumps(dict(json.loads(t), domains=dict(
        json.loads(t)["domains"], **{"mnemo-brain": ["~/ai/knowledge"]}))))
    out = L(h, "gh pr merge 1", role="hephaestus-brain", pdir="ai/knowledge", raw=True)
    check("merge: лид mnemo-brain (hephaestus-brain) — отказ, у направления личное",
          deny(out) and ("личному" in out))
    # [merge_protect] больше не читается: consent = false ничего не открывает и не ломает
    h = variant(policy_fn=lambda t: t + "[merge_protect]\nconsent = false\n")
    got = (M(h, "gh pr merge 5"), M(h, "gh pr merge 13"))
    check(f"[merge_protect] consent = false не читается: по запору — можно, без записей — отказ: {got}",
          got == ("allow", "deny"))
    h = variant()
    shutil.rmtree(os.path.join(h, ".local/state/pantheon"))
    out = M(h, "gh pr merge 5", raw=True)
    check("нет папки состояния — отказ по правилу, без сбоя скрипта", deny(out) and "сбой проверки" not in out)
    return failed


def policy_checks(home, cases):
    """После таблицы: [merge] и [merge_repos] не списком, тексты отказов по режиму, нет policy.toml, [private] —
    на своих HOME (кроме текстов). Возвращает число упавших проверок."""
    failed = 0
    # [merge] со строкой вместо списка не открывает слияние всем (ревью argus 15.10)
    home2 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home2)
    pol = os.path.join(home2, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace(
        'themis-library = ["~/projects/lecture-notes", "~/projects/law-feed"]',
        'themis-library = "~/projects/lecture-notes"')
    open(pol, "w").write(text)
    # 0.5.0: свои папки — из domains.json, поэтому проверка — на чужой папке: строка по буквам дала бы корень «/»
    got = run(home2, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, cwd=alex)
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge: строка вместо списка в [merge] — чужая папка не открывается: {got}")
    # [merge_client] строкой — то же
    text = _read(pol) + '\n[merge_client]\nhermes-site = "~/projects/sitebuilder"\n'
    text = text.replace('[merge_client]\nathena-shop = ["~/projects/shopKeeperApp", "~/projects/broker-landing"]\n', "")
    open(pol, "w").write(text)
    got = run(home2, alex, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, cwd=br)
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge: строка вместо списка в [merge_client] — чужая папка не открывается: {got}")
    # 0.5.0: тексты отказов — по режиму, с тем, что делать вместо
    texts = {
        "закрыто": run(home, br, "dev-opus", "Bash", {"command": "gh pr merge 1"}, sub=True, raw=True),
        "внутреннее": run(home, alex, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --admin"}, raw=True),
        "продукт": run(home, br, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --admin"}, raw=True),
        "защиты": run(home, ak, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --auto"}, raw=True),
        "личное": run(home, "ai/knowledge", "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True),
    }
    want = {"закрыто": ("gh pr create", "отчёте лиду"), "внутреннее": ("argus", "--admin"),
            "продукт": ("talos", "откат", "--match-head-commit"), "защиты": ("шлюз слияния", "argus", "(Д3)"),
            "личное": ("личному",)}
    ok = all('"deny"' in texts[k] and all(w in texts[k] for w in ws) for k, ws in want.items()) \
        and "talos" not in texts["внутреннее"]
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: тексты отказов по режиму (закрыто, внутреннее, продукт, защиты, личное)")
    return failed


def policy_text_checks(cases):
    """Нет policy.toml, координатор из [private], [merge_repos] не списком — на своих HOME. → число упавших."""
    failed = 0
    # нет policy.toml — отказ всем, даже Фемиде
    home4 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home4)
    os.remove(os.path.join(home4, ".claude/pantheon/policy.toml"))
    got = (run(home4, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True),
           run(home4, br, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True))
    ok = all('"deny"' in x and "политика" in x for x in got)  # отказ по правилу, а не сбой скрипта
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: нет policy.toml — отказ всем, текст про политику")
    # координатор из [private].coordinators, в чьей папке нет личного из [private].paths, — тоже не сливает
    home5 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home5)
    pol = os.path.join(home5, ".claude", "pantheon", "policy.toml")
    text = _read(pol) + '\n[private]\ncoordinators = ["mnemo-brain"]\npaths = ["~/ai/pantheon/.git/git-crypt"]\n'
    open(pol, "w").write(text)
    out = run(home5, "ai/knowledge", "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True)
    ok = '"deny"' in out and "личному" in out
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: координатор из [private].coordinators — отказ про личное")
    # [merge_repos] строкой — -R закрыт (подстрока «latark/lecture-notes» не должна совпасть по буквам)
    home3 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home3)
    pol = os.path.join(home3, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace('themis-library = ["latark/lecture-notes", "latark/law-feed"]',
                              'themis-library = "latark/lecture-notes"')
    open(pol, "w").write(text)
    got = run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/lecture-notes"})
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: строка вместо списка в [merge_repos] — отказ: {got}")
    # [merge_repos] списком на верхнем уровне — -R закрыт, обычное слияние без -R работает (ревью argus 15.10)
    text = _read(pol)
    text = text[:text.index("[merge_repos]\n")] + text[text.index("[merge_client]\n"):]
    open(pol, "w").write('merge_repos = ["latark/lecture-notes"]\n' + text)  # ключ верхнего уровня — до таблиц
    got = (run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/lecture-notes"}),
           run(home3, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 2"}))
    ok = got == ("deny", "deny")
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: merge_repos не таблицей — закрыто и -R, и без -R (запор, 0.5.4): {got}")
    return failed


def main():
    home = new_home()
    P, W, E, B, R, G, K, A = helpers(home)
    cases = [
        # (имя, ожидание, папка запуска, роль, субагент, (инструмент, вход)[, папка cwd[, env окна]])
        # --- push: gh pr merge координатору из [merge] (metis-0027) ---
        ("merge: Фемида сливает свой PR — можно", "allow", ec, "domain-coordinator", False, B("gh pr merge 1 --squash")),
        ("merge: Фемида без номера (текущая ветка) — отказ: запор сверяет записи на номер", "deny", ec,
         "domain-coordinator", False,
         B("gh pr merge --merge --delete-branch")),
        ("merge: Фемида с заголовком слияния — можно", "allow", ec, "domain-coordinator", False,
         B("gh pr merge 1 --squash --subject 'Индекс только для чтения'")),
        ("merge: Фемида с --admin — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge 1 --admin")),
        ("merge: Фемида с --admin=true — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge 1 --admin=true")),
        ("merge: Фемида в чужой репозиторий -R — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge 1 -R latark/sitebuilder")),
        ("merge: Фемида по ссылке — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge https://github.com/latark/sitebuilder/pull/1")),
        ("merge: Фемида через cd в чужую папку — отказ", "deny", ec, "domain-coordinator", False,
         B(f"cd {home}/{alex} && gh pr merge 1")),
        ("merge: лид Фемиды (hephaestus-library) — можно (metis-0054)", "allow", ec, "hephaestus-library", True,
         B("gh pr merge 1")),
        ("merge: лид Фемиды с --admin — отказ", "deny", ec, "hephaestus-library", True, B("gh pr merge 1 --admin")),
        ("merge: dev-sonnet Фемиды — отказ", "deny", ec, "dev-sonnet", True, B("gh pr merge 1")),
        ("merge: Фемида с GH_REPO — отказ", "deny", ec, "domain-coordinator", False,
         B("GH_REPO=latark/sitebuilder gh pr merge 1")),
        ("merge: Фемида gh pr -R … merge — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr -R latark/sitebuilder merge 1")),
        ("merge: Афина gh pr -R … merge — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr -R latark/sitebuilder merge 1")),
        ("merge: Фемида $N вместо номера — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge $N")),
        ("merge: Афина gh pr create --title merge — можно", "allow", br, "domain-coordinator", False,
         B("gh pr create --title merge --body x")),
        ("merge: Фемида gh pr list -S merge — можно", "allow", ec, "domain-coordinator", False, B("gh pr list -S merge")),
        ("merge: Афина gh pr checkout merge — можно", "allow", br, "domain-coordinator", False, B("gh pr checkout merge")),
        ("corpus-role: -c у скрипта, а не у python — можно", "allow", br, "domain-coordinator", False,
         B("python3 tools/report.py -c ydapi")),
        ("corpus-role: pytest -c по тестам Krisp — можно", "allow", br, "dev-sonnet", True,
         B("python3 -m pytest -c pytest.ini tests/test_krisp_trash.py")),
        ("corpus-role: python -c с runpy скрипта Krisp — отказ", "deny", br, "dev-sonnet", True,
         B("python3 -c 'import runpy; runpy.run_path(\"tools/krisp_trash.py\")'")),
        # --- merge -R из [merge_repos]: Фемида в law-feed сливает PR lecture-notes (themis-0015) ---
        ("merge -R: Фемида из law-feed в lecture-notes — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes --merge")),
        ("merge -R: --repo= и регистр — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo=Latark/Lecture-Notes --squash")),
        ("merge -R: github.com/owner/repo — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo github.com/latark/lecture-notes")),
        ("merge -R: -Rowner/repo слитно — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 -Rlatark/lecture-notes")),
        ("merge -R: gh pr -R … merge — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr -R latark/lecture-notes merge 2")),
        ("merge -R: другой репозиторий — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/sitebuilder")),
        ("merge -R: похожее имя — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes-fork")),
        ("merge -R: чужой хост — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R evil.example/latark/lecture-notes")),
        ("merge -R: два -R, второй чужой — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes -R latark/sitebuilder")),
        ("merge -R: без номера — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge -R latark/lecture-notes --merge")),
        ("merge -R: -R без значения — отказ", "deny", lw, "domain-coordinator", False, B("gh pr merge 2 -R")),
        ("merge -R: с --admin — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes --admin")),
        ("merge -R: $REPO вместо имени — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R $REPO")),
        ("merge -R: лид Фемиды из [merge_repos] — можно", "allow", lw, "hephaestus-library", True,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: лид Фемиды вне [merge_repos] — отказ", "deny", lw, "hephaestus-library", True,
         B("gh pr merge 2 -R latark/sitebuilder")),
        ("merge -R: dev-sonnet Фемиды — отказ", "deny", lw, "dev-sonnet", True,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: Афина с репо Фемиды — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: склеенные -dR<чужой> — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/sitebuilder")),
        ("merge -R: склеенные -dR<чужой> из папки репозитория — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/sitebuilder")),
        ("merge -R: gh pr -sR<чужой> merge — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr -sRlatark/sitebuilder merge 2")),
        ("merge -R: -dR <чужой> через пробел — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dR latark/sitebuilder")),
        ("merge -R: склеенные -dR<свой> — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/lecture-notes")),
        ("merge -R: -R=<свой> — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R=latark/lecture-notes")),
        ("merge: -tR… — R в заголовке, а не -R — можно", "allow", ec, "domain-coordinator", False,
         B("gh pr merge 2 -tRelease")),
        ("merge -R: Фемида с GH_REPO — по-прежнему отказ", "deny", lw, "domain-coordinator", False,
         B("GH_REPO=latark/lecture-notes gh pr merge 2")),
        ("merge: Афина без [merge] — можно: папки из domains.json (0.5.0)", "allow", br, "domain-coordinator", False,
         B("gh pr merge 1")),
        ("merge: Фемида git push в main — по-прежнему отказ", "deny", ec, "domain-coordinator", False,
         B("git push origin main")),
        # --- guard 0.5.0 (metis-0038): слияние по схеме владельца ---
        # внутреннее: своё направление по domains.json
        ("merge 0.5: Гермес в своей папке — можно", "allow", alex, "domain-coordinator", False, B("gh pr merge 4 --squash")),
        ("merge 0.5: Гермес в чужой папке (cwd без cd) — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 4"), br),
        ("merge 0.5: Гермес из своей папки с cd в чужую — отказ", "deny", alex, "domain-coordinator", False,
         B(f"cd {home}/{br} && gh pr merge 4")),
        ("merge 0.5: лид Гермеса hephaestus-site — можно", "allow", alex, "hephaestus-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид дизайна Гермеса apollo-site — можно", "allow", alex, "apollo-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид Гермеса в чужой папке (cwd без cd) — отказ", "deny", alex, "hephaestus-site", True,
         B("gh pr merge 4"), br),
        ("merge 0.5: лид Гермеса в сессии Афины — отказ", "deny", br, "hephaestus-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид Афины в сессии Гермеса — отказ", "deny", alex, "hephaestus-shop", True, B("gh pr merge 4")),
        ("merge 0.5: dev-sonnet Гермеса — отказ", "deny", alex, "dev-sonnet", True, B("gh pr merge 4")),
        # продукт: [merge_client] — пропуск так же, папка из [merge_client] вне domains.json — тоже
        ("merge 0.5: Афина в shopKeeperApp — можно", "allow", br, "domain-coordinator", False,
         B("gh pr merge 7 --squash --delete-branch")),
        ("merge 0.5: Афина в папке [merge_client] вне domains.json — можно", "allow", br, "domain-coordinator", False,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Афины в продукте — можно", "allow", br, "hephaestus-shop", True, B("gh pr merge 7")),
        ("merge 0.5: apollo-shop в [merge_client] вне domains.json — можно", "allow", br, "apollo-shop", True,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Гермеса в [merge_client] Афины — отказ", "deny", alex, "hephaestus-site", True,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: Гермес в продукте Афины — отказ", "deny", alex, "domain-coordinator", False, B("gh pr merge 7"), br),
        ("merge 0.5: Гермес в [merge_client] Афины — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: Афина в продукте с --admin — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 7 --admin")),
        ("merge 0.5: Афина в продукте с --auto — отказ (запор, 0.5.4)", "deny", br, "domain-coordinator", False,
         B("gh pr merge 7 --auto --squash")),
        # кому слияние закрыто
        ("merge 0.5: hq — отказ", "deny", ".", "hq", False, B("gh pr merge 1"), ak),
        ("merge 0.5: мастерская — отказ", "deny", ws, "workshop", False, B("gh pr merge 1")),
        ("merge 0.5: лид главной сессией — отказ", "deny", br, "hephaestus-shop", False, B("gh pr merge 1")),
        ("merge 0.5: dev-opus — отказ", "deny", br, "dev-opus", True, B("gh pr merge 1")),
        ("merge 0.5: argus — отказ", "deny", br, "argus", True, B("gh pr merge 1")),
        ("merge 0.5: talos — отказ", "deny", br, "talos", True, B("gh pr merge 1")),
        ("merge 0.5: prometheus — отказ", "deny", br, "prometheus", True, B("gh pr merge 1")),
        ("merge 0.5: лид без agent_type-префикса (general-purpose) — отказ", "deny", br, "general-purpose", True,
         B("gh pr merge 1")),
        ("merge 0.5: лид в сессии штаба (~/ai/pantheon) — отказ", "deny", "ai/pantheon", "hephaestus-pantheon", True,
         B("gh pr merge 1"), ak),
        ("merge 0.5: лид в мастерской — отказ", "deny", ws, "hephaestus-workshop", True, B("gh pr merge 1")),
        ("merge 0.5: mnemo-brain в ~/ai/knowledge — отказ", "deny", "ai/knowledge", "domain-coordinator", False,
         B("gh pr merge 1")),
        # защиты: только Метида и её лид, через запор (guard 0.5.4): поштучного «да» владельца больше нет, ядро защит
        # (Д3) — PR ждёт слияния владельцем. Сам запор — test_merge_gate_*.py; здесь — кто, где и в каком репозитории
        ("защиты: Метида по записям запора — можно", "allow", ak, "domain-coordinator", False, B("gh pr merge 5 --squash")),
        ("защиты: Метида с --subject — можно (заголовок больше не нужен и не мешает)", "allow", ak, "domain-coordinator",
         False, B('gh pr merge 5 --squash --subject "guard 0.5.4"')),
        ("защиты: Метида со склеенным -st — можно", "allow", ak, "domain-coordinator", False,
         B('gh pr merge 5 "-stguard 0.5.4"')),
        ("защиты: Метида без номера (текущая ветка) — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge --squash")),
        ("защиты: Метида на непроверенном коммите — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 5 --match-head-commit " + "c" * 40)),
        ("защиты: PR без записей запора — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 13")),
        ("защиты: --auto — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 --auto")),
        ("защиты: --admin — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 --admin")),
        ("защиты: субагент dev-opus Метиды — отказ", "deny", ak, "dev-opus", True, B("gh pr merge 5")),
        ("защиты: лид Метиды — можно (metis-0054)", "allow", ak, "hephaestus-pantheon", True, B("gh pr merge 5")),
        ("защиты: лид Метиды с --auto — отказ", "deny", ak, "hephaestus-pantheon", True, B("gh pr merge 5 --auto")),
        ("защиты: лид Метиды с двумя номерами — отказ", "deny", ak, "hephaestus-pantheon", True, B("gh pr merge 5 6")),
        ("защиты: apollo-pantheon — можно", "allow", ak, "apollo-pantheon", True, B("gh pr merge 5")),
        ("защиты: лид Афины в agent-kit — отказ", "deny", br, "hephaestus-shop", True, B("gh pr merge 5"), ak),
        ("Метида внутреннее: лид без -R — можно", "allow", ak, "hephaestus-pantheon", True,
         B("gh pr merge 3 --squash"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: лид с -R из [merge_repos] — можно", "allow", ak, "hephaestus-pantheon", True,
         B("gh pr merge 3 -R latark/tg-read"), "projects/other/tg-read-dev"),
        ("защиты: другой координатор в agent-kit — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 5"), ak),
        ("защиты: реестр отдал agent-kit/sub Афине — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 5"), ak + "/sub"),
        ("защиты: Метида с cd в agent-kit — отказ", "deny", ak, "domain-coordinator", False,
         B(f"cd {home}/{ak} && gh pr merge 5"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: без -R — можно", "allow", ak, "domain-coordinator", False,
         B("gh pr merge 3 --squash"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R из [merge_repos] — можно", "allow", ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/tg-read"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R вне [merge_repos] — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/claude-config"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R и --auto — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/tg-read --auto"), "projects/other/tg-read-dev"),
        ("Метида из tg-read-dev как папки запуска: -R — можно", "allow", "projects/other/tg-read-dev",
         "domain-coordinator", False, B("gh pr merge 3 -R latark/tg-read")),
        ("Фемида -R из [merge_repos] — можно", "allow", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes")),
        # --- находка проверки безопасности 2eda45f: защиты по репозиторию (remote), сбой — отказ ---
        ("защиты по remote: клон agent-kit в tg-read-dev — Метида по запору — можно", "allow", ak,
         "domain-coordinator", False, B("gh pr merge 5"), "projects/other/tg-read-dev/x"),
        ("защиты по remote: клон agent-kit (другой регистр, git@) у Фемиды — отказ", "deny", lw, "domain-coordinator",
         False, B("gh pr merge 5"), lw + "/akclone"),
        ("защиты по remote: клон через псевдоним ssh у Гермеса — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/alias-clone"),
        ("защиты: симлинк на agent-kit в папке Гермеса — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/ak-link"),
        ("защиты: путь в другом регистре — Гермес — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), "projects/AGENT-KIT"),
        ("защиты: путь в другом регистре — Метида по запору — можно", "allow", ak, "domain-coordinator", False,
         B("gh pr merge 5"), "projects/Agent-Kit"),
        ("защиты: worktree agent-kit во внутренней папке Метиды — по запору можно", "allow", ak, "domain-coordinator",
         False, B("gh pr merge 5"), "projects/other/tg-read-dev/wt"),
        ("защиты: worktree agent-kit вне направлений (как /tmp) — Гермес — отказ", "deny", alex, "domain-coordinator",
         False, B("gh pr merge 5"), "wt-ak"),
        ("защиты: worktree agent-kit вне направлений — Метида по запору — можно", "allow", ak, "domain-coordinator",
         False, B("gh pr merge 5"), "wt-ak"),
        ("защиты: Метида -R latark/agent-kit из agent-kit — можно (есть в [merge_repos])", "allow", ak,
         "domain-coordinator", False, B("gh pr merge 5 -R latark/agent-kit")),
        ("репозиторий: репозиторий без remote — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/no-remote"),
        ("запор: два номера PR в команде — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 6")),
        ("ssh-псевдоним: клон agent-kit через gh-alt — Метида по запору — можно", "allow", ak,
         "domain-coordinator", False, B("gh pr merge 5"), "projects/other/tg-read-dev/alias"),
        ("gh-resolved: клон форка у Гермеса, set-default = latark/agent-kit — отказ", "deny", alex, "domain-coordinator",
         False, B("gh pr merge 5"), alex + "/fork"),
        ("gh-resolved: «base» — сам remote, своё слияние — можно", "allow", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/base-clone"),
    ]
    failed = run_table(home, cases)
    failed += policy_checks(home, cases)
    failed += policy_text_checks(cases)
    failed += merge_security_checks(home, cases)
    finish(cases, failed)


if __name__ == "__main__":
    main()
