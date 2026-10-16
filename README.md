# agent-kit

Маркетплейс плагинов Claude Code для системы агентов «Пантеон». Общие части собираются здесь сразу,
поэтому у Ксении работает то же, что у владельца; роли армии, хранилище знаний и ключи у каждого свои.
Приватный репозиторий `latark/agent-kit`; ведёт его metis-pantheon (изменения — после «да» владельца).

| Плагин | Что делает | Состояние |
| --- | --- | --- |
| `guard` | Правила, которые Claude Code проверяет сам: dev-server, attribution, cdp, tg-secret, nextjs, domain, pantheon-acl, protect-config, private, cdp-role, push, terminal; модель угроз и режимы — `plugins/guard/README.md` | работает с 14.10 (шаг 0.4); управляемые настройки — шаг 0.6, ставятся через `sudo` |
| `pantheon` | Планировщик `pantheon-tick` (launchd, раз в 60 с), команда `pantheon`, копия `~/ai/pantheon-view` для Obsidian, задачи и доска владельца, коммит `~/ai/pantheon`, настройки окон ролей с песочницей и строгим guard, сверка карты решений; хуки контекста (подсказка «пора очистить», продолжение после `/clear`, файл состояния после сжатия) и журнал ваших слов owner-log; запуск сессий (`pantheon start`, `wake`), сборка ролей (`pantheon roles build`), заранее разрешённое (`pantheon approve`), обёртка `heavy`, Stop-хук разработчика; дежурный без модели (`pantheon watch`: сессии, swap, worktree, версия Claude Code, паузы, самозапуск по вашим решениям, журналы ваших слов), пересмотры, остановка и пауза, технический перезапуск, продолжение сессий `claude respawn` с текстом через хук | работает с 14.10 (шаг 0.4); хуки — с шага 1.1; роли и запуск — с шага 1.2; дежурный и перезапуск — с 0.10.0 (шаг 1.4) |
| `project-tools` | Инструменты проекта по карте стеков `stacks.json`: MCP-серверы (next-devtools, chrome-devtools, shadcn) — в `.mcp.json` проекта с одобрением, плагины (Supabase) — в настройки проекта, блок для Codex; команда `project-tools` (check, apply, skip, outdated), навык, подсказка при старте сессии; отпечатки одобренных записей — предупреждение о подмене после `git pull` | с 14.10 (шаг 0.7) |

## Где что лежит

- `plugins/guard/hooks/guard.py` — все правила; шапка файла перечисляет их и выключатель `GUARD_OFF`.
  Данные: `~/.local/state/pantheon/domains.json` (собирает `pantheon domains build` из
  `~/ai/pantheon/directions.toml`) и `~/.claude/pantheon/policy.toml` — привилегии (образец —
  `plugins/guard/policy.example.toml`), правит только metis-pantheon.
- `plugins/pantheon/lib/pantheon.py` — планировщик и команда; `pantheon help` — список команд.
  Задачи — `~/ai/pantheon/schedule.toml`, метки и журналы запусков — `~/.local/state/pantheon/` (свои у каждого Mac).
- Размер песочницы окна (с 0.11.17): Seatbelt не собирает профиль больше 64 КБ, и тогда Bash окна не запускается
  совсем. Поэтому `sandbox_build` считает байты путей песочницы окна. Выше предела — 48 КБ, переменная
  `PANTHEON_SANDBOX_LIMIT` — окно не пересобирается: остаётся прежний файл, приходит одна тревога «песочница окна …».
  Штаб закрывает чужие папки в `/tmp/claude-<uid>` и `~/.claude/projects` шаблонами по префиксам, а не перечислением,
  поэтому мусор тестов список не раздувает. Корень `/tmp/claude-<uid>` и папки в нём на `tmp` открыты: это `$TMPDIR`
  песочницы, в нём временные файлы heredoc и mktemp и временные папки `mktemp -d` и `tempfile`.
- Окна ролей (с 0.11.14, `sandbox_build`): окну координатора направления дано правило `Bash(gh pr merge *)` — слияние PR
  без вопроса классификатора auto (`COORDINATOR_ALLOW`); мастерской и штабу правила нет. Каждое слияние по-прежнему
  проверяет guard: только главная сессия domain-coordinator, свои папки, без `--admin` и `--auto`.
  Мимо песочницы gh (в ней не работает) — только чтение: `gh pr view|checks|diff|list`, `gh run view|list|watch`,
  `gh repo view`, `gh auth status`; `gh api`, `gh issue` и `gh run cancel|rerun|delete` в песочнице падают. `gh pr create|merge` и сетевой git (push, fetch, pull) —
  у окна каждого направления; мастерской — только сетевой git и только при SSH-remote; у штаба ничего из этого нет
  (metis-0064).
  Задачи расписания `claude -p --agent <роль>` идут в песочнице окна задачи `settings/job-<роль>.json` (metis-0063):
  роли — только из `JOB_ROLES` (clio, prometheus, iris; iris — с `--model sonnet`), тик сам добавляет `--settings`.
  Окно пишет только своё (clio и prometheus — `~/ai/knowledge`, iris — `~/ai/pantheon/scout`), память ролей и свой
  кэш; личное закрыто на чтение и запись; сети у Bash нет; мимо песочницы — только `pantheon alert`. Нет файла окна
  — задача не идёт, приходит одна тревога; `domains build --if-changed` пересобирает пропавшее окно. Субагентов
  роль задачи зовёт только из `agents` своей строки `JOB_ROLES` (сейчас — никого): хук `agents.py` с заглушкой
  «никого» и `deny Agent(…)` встроенным типам, ролям из `~/.claude/agents` и лидам; обычный навык идёт.
  Песочница всех окон (направления, мастерская, штаб) пускает запись в `~/.claude/agent-memory/<роль>` каждой
  роли-субагента, у которой в шапке `~/.claude/agents/<роль>.md` есть ключ `memory:` (роли главных сессий не берутся;
  папку сборка создаёт, ссылку вместо папки пропускает). Новый файл роли тик подхватывает сам. Риск: песочница пускает
  Bash-запись в память всех таких ролей, а guard (правило domain) — каждую роль только в её собственную папку, для
  Write/Edit и для тех записей Bash, которые он распознаёт. Запись в память чужой роли (например, argus) остаётся
  возможной только командой Bash, которую guard не разобрал (скрипт, интерпретатор). Исключение — главная сессия
  штаба: правило domain её не ограничивает (`check_domain` в guard.py), поэтому Зевс пишет в память любой такой роли
  и через Write/Edit (как и раньше), и обычной командой Bash (с 0.11.14). Субагенты в окне штаба ограничены своей
  папкой, как везде. Граница та же, что у остальных папок окна: guard — защита от ошибок, а не от намеренного обхода.
- `plugins/pantheon/lib/watch.py` — дежурный и управление сессиями (шаг 1.4): `pantheon watch [--dry-run]`, `agents`,
  `who`, `revisits`, `wake <имя>`, `stop|resume <имя>|--all`, `pause <имя>|--all --reason limit|swap|manual`,
  `restart --prepare|--status|--go|--cancel`, `saved`, `infra-check`. Подключает его `pantheon.py` (`watch_cmd`).
- Службы (с 0.11.0, SCHED-05): `[[service]]` в `schedule.toml` — постоянный процесс, своя задача launchd
  `com.latark.pantheon-svc.<имя>` с KeepAlive, запуск через `pantheon service-run <имя>` (команда — только `pantheon …`
  или скрипт плагина). Тик сверяет launchd с расписанием; `pantheon jobs pause|resume|disable|enable <служба>` действует
  сразу, `pantheon jobs` показывает pid. `pantheon jobs pause --all` и нечитаемый `schedule.toml` службы не трогают:
  они идут как шли (тик выходит раньше сверки), пауза службы — только по её имени.
- Обновления плагинов (с 0.11.8, metis-0052): `pantheon plugins update [--quiet]` — тик раз в 10 минут, вне песочницы.
  Обновляет каталог agent-kit (не вышло — код 75), для установленных плагинов уровня пользователя с новой версией в
  каталоге гоняет `tests/test_*.py` новой и установленной версии во временной папке на `python3` и `/usr/bin/python3`.
  Новых падений нет — `claude plugin update <плагин>@agent-kit` без `-y` и тревога «обновлён X → Y»; есть — не ставит,
  тревога с логом, эту версию больше не гоняет. Метки, журнал и логи тестов — `~/.local/state/pantheon/plugins/`.
  Встало не то, что проверялось (другая версия или хеш дерева), — критическая тревога. Проверить ту же версию заново —
  удалить запись плагина из `~/.local/state/pantheon/plugins/marks.json`.
- `plugins/pantheon/lib/qmd.py` — общий поиск qmd (шаг 1.5): `pantheon qmd config|update|embed|serve|install|status`.
  Коллекции — `~/ai/pantheon/qmd.toml` (только штаб); `~/.config/qmd/index.yml` пересобирается из него перед каждым
  запуском qmd и без ключа `update` (его qmd исполняет через bash). Сервер MCP — служба `qmd` на 127.0.0.1:8181;
  подключение на новом Mac — `npm install -g @tobilu/qmd`, затем `pantheon qmd install` (MCP уровня пользователя).
  Хук `ctx.py qmd-query` пропускает только поиск `vec`/`lex` в названных коллекциях с `rerank: false` (QMD-04).
- `plugins/pantheon/lib/view-sync.sh` — копия `~/ai/pantheon` только для чтения для Obsidian.
- `plugins/pantheon/hooks/ctx.py` — хуки контекста и журнала ваших слов (шаг 1.1): `owner-log` (UserPromptSubmit,
  в фоне — строка только для ввода, который Claude Code сам пометил в транскрипте как ваш), `stop` (подсказка
  «пора очистить» на 150 тыс. и далее каждые +100 тыс.), `start` (после сжатия — файл состояния, штабу — новые
  тревоги и сводка журналов), `rewake` (после `/clear` будит Claude, если файл состояния обновлён после вашего
  последнего сообщения). Состояние — `~/.local/state/pantheon/ctx/` и `…/owner-log/` (ввод без пометки транскрипта —
  в `…/owner-log/unconfirmed/`, это не ваши слова); выключатель хуков контекста — `PANTHEON_CTX_OFF=1`. Хуки запускают
  `python3` из PATH (3.9+): на чистом Mac нужны Command Line Tools (`xcode-select --install`), иначе это заглушка.
- `ctx.py` с 0.10.0 (шаг 1.4): `maint-post` и `maint-pre` — при метке техперезапуска сессия из списка один раз получает
  «сохранись», после `pantheon saved` ей закрыты инструменты (кроме отчёта Зевсу); `push` (SessionStart, asyncRewake) —
  отдаёт сессии текст из `~/.local/state/pantheon/push/<сессия>.txt` после `claude respawn`. Уборку журналов ваших слов
  делает дежурный, хук только дописывает.
- `plugins/pantheon/hooks/agents.py` (0.11.19, P0-6) — PreToolUse `Agent|Task|Skill` в окнах штаба и координаторов:
  главная сессия зовёт только субагентов из списка окна, навык с `context: fork` проверяется по своему `agent:`.
  Субагенты окна (лиды с их dev-*, argus) не проверяются. Списки — в `pantheon.py`: `HQ_AGENTS`, `COORDINATOR_AGENTS`,
  `COORDINATOR_EXTRA_AGENTS`, у координатора ещё свои лиды из реестра. В окна добавлены и правила `deny Agent(…)`:
  штабу — все лиды и главные роли, направлению — chiron, главные роли и лиды других направлений. Любой сбой хука —
  код 2, то есть отказ. После выпуска нужны `pantheon domains build` и перезапуск окон. С 0.11.23 штабу открыт
  momus — ревизор навыка audit (`agent: momus`): только чтение и веб, пишет лишь свой отчёт в `~/ai/knowledge/Inbox`.
- `plugins/pantheon/bin/heavy` — тяжёлые команды через общую блокировку: два места, `--server` — один долгий процесс (MEM-03).
- `plugins/pantheon/hooks/dev-stop-verify.py` — Stop разработчика (в шапке ролей dev-*): красная проверка проекта
  возвращает, не больше трёх раз; очередь `heavy` — не возврат (DONE-02).
- `plugins/pantheon/scripts/git-crypt-merge.sh` — слияние файлов под git-crypt как текста (для `~/ai/pantheon` и `me/`).
- `plugins/pantheon/scripts/decision-map-check.py` — сверка карты решений с `revisits.toml`.
- `plugins/pantheon/scripts/baseline.py` — замер «как сейчас» по git и транскриптам (ORD-06); правила подсчёта — в шапке.
- `plugins/pantheon/scripts/config-check.py` — проверка правок `~/.claude` для `sync.sh`: код и подозрительное — в
  карантин с объяснением на доске, остальное уходит само (SEC-15).
- `plugins/guard/managed-settings.json` — управляемые настройки (SEC-28), ставятся через `sudo` (README guard).
- `plugins/project-tools/stacks.json` — карта стеков (признак → что подключить); `plugins/project-tools/lib/project_tools.py`
  — команда `project-tools`. Пишет только записи из карты; в окнах ролей запись в `.mcp.json` и `.claude/settings*.json`
  запрещена песочницей и guard — там только `check`.

## Проверки

    python3 -I plugins/guard/tests/test_guard.py      # карта прав ~/ai/pantheon, domain, привилегии, protect-config, режимы
    python3 -I plugins/guard/tests/test_shell_diff.py # разбор Bash против настоящих zsh и bash
    python3 -I plugins/pantheon/tests/test_board.py   # задачи и доска владельца
    python3 -I plugins/pantheon/tests/test_config_check.py   # правила карантина правок ~/.claude (SEC-15)
    bash plugins/pantheon/tests/test_sync_quarantine.sh ~/.claude/sync.sh "$(readlink ~/.local/bin/pantheon)" "$PWD/plugins/pantheon"
    python3 -I plugins/pantheon/tests/test_start.py   # start, wake, roles build, approve, heavy, Stop-хук разработчика
    python3 -I plugins/pantheon/tests/test_watch.py   # дежурный: самозапуск, сбои, паузы, стоп, техперезапуск, журналы, пересмотры
    python3 -I plugins/pantheon/tests/test_tick.py    # планировщик: сон, пробуждение, питание, простой, лимит, главный Mac
    python3 -I plugins/pantheon/tests/test_plugins_update.py   # обновления agent-kit тиком: тесты, база, метки, коды
    python3 -I plugins/pantheon/tests/test_baseline.py   # замер «как сейчас»: задачи по git commit, сообщения, возвраты, цена
    python3 -I plugins/pantheon/tests/test_hooks.py   # хуки контекста и owner-log (и на системном: CTX_TEST_PYTHON=/usr/bin/python3)
    python3 -I plugins/project-tools/tests/test_project_tools.py   # карта стеков, apply, одобрения, Codex, подсказка
    claude plugin validate .  &&  claude plugin validate plugins/guard  &&  claude plugin validate plugins/pantheon  &&  claude plugin validate plugins/project-tools

Изменение защит проверяется вживую в изоляции: временные папки, `--plugin-dir` и `--settings` на одну
сессию, Haiku, хеш `~/.claude/settings.json` до и после.
