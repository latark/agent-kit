#!/usr/bin/env python3
"""Запор слияния guard, часть «ui»: talos в продукте нужна, только если дифф PR задевает пути живого приложения из
[merge_client_ui] направления в policy.toml владельца (metis-0906, 0863). Нет раздела — как раньше, talos нужна.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_ui.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403

UI = ('[merge_client_ui]\nathena-shop = ["apps/web/**", "packages/shared/**", "package.json", '
      '"!**/*.check.ts", "!**/__fixtures__/**", "!**/AGENTS.md", "!**/README.md"]\n')


def _policy(h, section):
    """policy.toml шаблона Home и раздел section в конце (h.reset() policy.toml не трогает)."""
    path = h.j(".claude/pantheon/policy.toml")
    with open(path) as fh:
        base = fh.read().split("[merge_client_ui]")[0]
    with open(path, "w") as fh:
        fh.write(base + (section or ""))


def _product(h, files, section=UI, count=None, head=None, alert=True):
    """PR latark/broker#5 с файлами files: тесты и argus есть, строка alerts есть (alert), talos нет."""
    _policy(h, section)
    h.gh(files)
    h.ci(GREEN, name="broker", head=head, changedFiles=len(files) if count is None else count)
    sha = h.sha["broker"]
    h.seed(rec("tests", "latark/broker", None, sha, "dev-opus"), rec("accept", "latark/broker", 5, sha))
    if alert:
        h.alert("2026-10-15 20:01 · athena-shop · latark/broker#5 ушло: правила; откат: git revert abc")
    return h.pre(f"gh pr merge 5 --match-head-commit {sha}", pdir="projects/broker")


OUTSIDE = ["apps/web/lib/cadastre.check.ts", "apps/analyzer/x/__fixtures__/a.json", "AGENTS.md",
           "apps/web/README.md", "docs/plan.md", {"filename": "apps/web/old.check.ts", "status": "removed"}]


def t_ui_outside(h):
    merge_case("дифф вне путей живого приложения — без talos проходит", _product(h, OUTSIDE), True)


def t_ui_inside(h):
    for label, files in (("страница", ["apps/web/app/page.tsx"]),
                         ("вместе с тестом", ["apps/web/lib/a.check.ts", "packages/shared/src/money.ts"]),
                         ("корневой package.json", ["package.json"]),
                         ("конфиг раннера рядом", ["apps/web/vitest.config.ts"]),
                         ("снапшот", ["apps/web/__snapshots__/a.snap"]),
                         ("исключение — с учётом регистра", ["apps/web/a.CHECK.ts"]),
                         ("свой шаблон — без учёта регистра", ["Apps/Web/page.tsx"]),
                         ("переименование из приложения", [{"filename": "docs/x.md", "status": "renamed",
                                                           "previous_filename": "apps/web/app/page.tsx"}]),
                         ("удаление страницы", [{"filename": "apps/web/app/page.tsx", "status": "removed"}]),
                         ("имя файла не строка", [{"filename": None, "status": "modified"}])):
        h.reset()
        merge_case(f"дифф в путях ({label}) — без talos отказ", _product(h, files), False, "живое приложение")
    h.reset()
    h.seed(rec("talos", "latark/broker", 5, h.sha["broker"], who="talos", agent_id="t1"))
    merge_case("дифф в путях с записью talos — проходит", _product(h, ["apps/web/app/page.tsx"]), True)


def t_ui_no_section(h):
    merge_case("нет [merge_client_ui] — talos нужна, как раньше", _product(h, OUTSIDE, section=None), False,
               "нет [merge_client_ui]")
    h.reset()
    other = '[merge_client_ui]\nhermes-alex = ["apps/**"]\n'
    merge_case("раздел только чужого направления — talos нужна", _product(h, OUTSIDE, section=other), False,
               "нет [merge_client_ui] athena-shop")
    h.reset()
    bad = '[merge_client_ui]\nathena-shop = "apps/web/**"\n'
    merge_case("раздел не списком — talos нужна", _product(h, OUTSIDE, section=bad), False, "нет [merge_client_ui]")


def t_ui_unsure(h):
    merge_case("список файлов неполон — talos нужна", _product(h, OUTSIDE, count=len(OUTSIDE) + 1), False,
               "неполон")
    h.reset()
    merge_case("PR на другом коммите — talos нужна", _product(h, OUTSIDE, head="d" * 40), False,
               "(PR сейчас на другом коммите (dddd")
    h.reset()
    open(h.j("gh.api.fail"), "w").close()
    merge_case("сбой gh api (файлы) — talos нужна", _product(h, OUTSIDE), False, "неполон")
    h.reset()
    open(h.j("gh.ci.fail"), "w").close()
    merge_case("сбой gh pr view — talos нужна", _product(h, OUTSIDE), False, "нет проверки talos")


def t_ui_alerts_stay(h):
    """Без talos строка «что ушло» с откатом всё равно нужна."""
    merge_case("вне путей, но без строки alerts — отказ", _product(h, OUTSIDE, alert=False), False,
               "нет строки «что ушло»")


CASES = [t_ui_outside, t_ui_inside, t_ui_no_section, t_ui_unsure, t_ui_alerts_stay]


if __name__ == "__main__":
    sys.exit(main(CASES))
