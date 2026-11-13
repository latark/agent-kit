# Тесты, красные в окне роли (metis-0773)

Замер 03.11 на origin/main 5c51ac9: `heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard plugins/pantheon plugins/project-tools`
в окне metis-pantheon. 31 файл из 98 красный без всяких правок. Лог до: строка «FAIL» в итоге раннера.

## Причина одна: песочница окна режет запись в определённые имена под папкой tmp кэша окна

TMPDIR раннера в окне — `~/Library/Caches/pantheon-sandbox/<окно>/tmp` (там разрешены сокеты). Под ней нельзя:

1. создать `.claude/agents` (EPERM) — тесты строят поддельный HOME с ролями;
2. записать `.git/config` и `.git/hooks` (EPERM, `git init` падает «не удалось установить core.repositoryformatversion»);
3. как следствие, кэш `xcrun_db` в /var/folders — шим /usr/bin/git пишет его вне TMPDIR (видно в логе test_setup).

В `/tmp/claude-<uid>` все три записи проходят (проверено пробой), но сокетов там нет — файлам из таблицы они не нужны.

| Файл | Что падает | Причина |
|---|---|---|
| guard/test_guard, test_drafts | setup(home): makedirs `.claude/agents` | 1 |
| pantheon/test_read, test_start, test_agent_allowlist, test_coord_switch, test_grants, test_plugin_map, test_role_apply, test_roles, test_window_ports, test_traces, test_workshop_sockets | HOME/.claude/agents | 1 |
| guard/test_merge_gate, pantheon/test_baseline, test_batch, test_check_traces, test_config_check, test_direction, test_executors, test_outside, test_outside_rerun, test_run_tests, test_sync_quarantine, project-tools/test_project_tools | `git init` | 2 |
| pantheon/test_setup | git (xcrun_db, `.git/hooks`) и роли в HOME/.claude/agents | 1, 2, 3 |
| pantheon/test_tick, test_tick_skip, test_watch, test_review | поддельные worktree/репозитории и `.claude/worktrees` под tmp | 1, 2 (следствие; проверено прогоном после правки) |
| pantheon/test_private_conf, test_sandbox_size | сборка domains/hq.json в поддельном HOME | 1 |

## Что сделано

`scripts/run-tests.py`: список `WINDOW_FS` (эти 31 файл + test_setup). Перед прогоном раннер пробует под своим корнем те же
`mkdir .claude/agents` и `git init`. Не вышло — файлы из списка идут в `/tmp/claude-<uid>/run-tests-*` (убирается в конце).
Не вышло и там — строка `skip <файл> · пропущено: окно режет запись …`, в итоге «пропущено N». Вне окна проба проходит,
ничего не меняется. Кода guard, hooks, window_rules и sandbox_build правка не касается.

Причина в ядре, не правилась: имена `.claude/agents`, `.git/config`, `.git/hooks` в запретах песочницы окна — решение метис.
Пропуск целым файлом, а не случаем: падение в общей подготовке (setup поддельного HOME / `git init`), независимых случаев
в этих файлах до неё нет.

## Итог (замер в окне)

До: FAIL 31 файл из 98 (лог before.log). После: ok 96, FAIL 0, пропущено 2 (итог раннера, 7855 проверок).
Пропущены строкой: guard/test_merge_gate (нужен репозиторий вне /tmp, а `.git/config` под tmp окна закрыт),
pantheon/test_outside (случаи serve поднимают серверы на локальных портах, bind в окне закрыт; блок «порт под слушателем»
внутри файла теперь пропускается случаем). test_setup идёт и в окне (запасной корень).

Код выхода раннера: пропущен хоть один файл окна (WINDOW_*) — код 4 (WINDOW_SKIP_CODE; 3 — «нечего гонять», его CI считает зелёным) и строка «пропущены файлы окна — для записи полного набора не годится».
Без этого зелёный прогон в окне (код 0) шлюз принял бы за полный набор (`FULL_TESTS`), хотя test_merge_gate не шёл. Без пропусков
коды прежние (0 ok, 1 FAIL). Проба bind срабатывает в любой песочнице без локальных портов, не только в окне роли.

## Почему файлом, а не случаем (AGENTS.md: пропускаются случаи)

- guard/test_merge_gate (с metis-1119 — части test_merge_gate_*.py, общее в _merge_gate_common.py): единственная подготовка (`Home` с `git init`) общая для всех ~сотен случаев, а корень вне /tmp в окне
  не годится для `git init` (`.git/config` закрыт), поэтому ни один случай без неё не стартует.
- pantheon/test_outside: независимая часть (проверки без серверов) идёт, пока файл не упрётся в bind; 37 случаев serve
  поднимают реальные серверы и сами требуют занять порт — их отдельный пропуск потребует переписать секции файла (задача metis-0777: вынести serve-случаи, чтобы остальное шло в окне).
- Остальные файлы WINDOW_FS: падение в общей подготовке (поддельный HOME / `git init`), для них вместо пропуска выбран перенос
  корня, поэтому они идут целиком и проверяют всё.
- Вне окна (CI, ноутбук): обе пробы проходят, `window_plan` возвращает прежний корень и пустой набор пропусков — тест
  «window_plan вне окна» в test_run_tests.py.

test_outside.py:864: `try/except PermissionError` вокруг проверки порта оставлен — в окне файл WINDOW_BIND снимается пробой, а вне окна это защита от падения на закрытом bind.
