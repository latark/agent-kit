# agent-kit

Маркетплейс плагинов Claude Code для системы агентов «Пантеон». Общие части собираются здесь сразу,
поэтому у Ксении работает то же, что у владельца; роли армии, хранилище знаний и ключи у каждого свои.
Приватный репозиторий `latark/agent-kit`; ведёт его metis-pantheon (изменения — после «да» владельца).

| Плагин | Что делает | Состояние |
| --- | --- | --- |
| `guard` | Правила, которые Claude Code проверяет сам: dev-server, attribution, cdp, tg-secret, nextjs, domain, pantheon-acl, protect-config, private, cdp-role, push, terminal; модель угроз и режимы — `plugins/guard/README.md` | работает с 14.10 (шаг 0.4); управляемые настройки — шаг 0.6, ставятся через `sudo` |
| `pantheon` | Планировщик `pantheon-tick` (launchd, раз в 60 с), команда `pantheon`, копия `~/ai/pantheon-view` для Obsidian, задачи и доска владельца, коммит `~/ai/pantheon`, настройки окон ролей с песочницей и строгим guard, сверка карты решений; хуки контекста (подсказка «пора очистить», продолжение после `/clear`, файл состояния после сжатия) и журнал ваших слов owner-log; запуск сессий (`pantheon start`, `wake`), сборка ролей (`pantheon roles build`), заранее разрешённое (`pantheon approve`), обёртка `heavy`, Stop-хук разработчика | работает с 14.10 (шаг 0.4); хуки — с шага 1.1; роли и запуск — с шага 1.2 |
| `project-tools` | Инструменты проекта по карте стеков `stacks.json`: MCP-серверы (next-devtools, chrome-devtools, shadcn) — в `.mcp.json` проекта с одобрением, плагины (Supabase) — в настройки проекта, блок для Codex; команда `project-tools` (check, apply, skip, outdated), навык, подсказка при старте сессии; отпечатки одобренных записей — предупреждение о подмене после `git pull` | с 14.10 (шаг 0.7) |

## Где что лежит

- `plugins/guard/hooks/guard.py` — все правила; шапка файла перечисляет их и выключатель `GUARD_OFF`.
  Данные: `~/.local/state/pantheon/domains.json` (собирает `pantheon domains build` из
  `~/ai/pantheon/directions.toml`) и `~/.claude/pantheon/policy.toml` — привилегии (образец —
  `plugins/guard/policy.example.toml`), правит только metis-pantheon.
- `plugins/pantheon/lib/pantheon.py` — планировщик и команда; `pantheon help` — список команд.
  Задачи — `~/ai/pantheon/schedule.toml`, метки и журналы запусков — `~/.local/state/pantheon/` (свои у каждого Mac).
- `plugins/pantheon/lib/view-sync.sh` — копия `~/ai/pantheon` только для чтения для Obsidian.
- `plugins/pantheon/hooks/ctx.py` — хуки контекста и журнала ваших слов (шаг 1.1): `owner-log` (UserPromptSubmit,
  в фоне — строка только для ввода, который Claude Code сам пометил в транскрипте как ваш), `stop` (подсказка
  «пора очистить» на 150 тыс. и далее каждые +100 тыс.), `start` (после сжатия — файл состояния, штабу — новые
  тревоги и сводка журналов), `rewake` (после `/clear` будит Claude, если файл состояния обновлён после вашего
  последнего сообщения). Состояние — `~/.local/state/pantheon/ctx/` и `…/owner-log/` (ввод без пометки транскрипта —
  в `…/owner-log/unconfirmed/`, это не ваши слова); выключатель хуков контекста — `PANTHEON_CTX_OFF=1`. Хуки запускают
  `python3` из PATH (3.9+): на чистом Mac нужны Command Line Tools (`xcode-select --install`), иначе это заглушка.
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
    python3 -I plugins/pantheon/tests/test_tick.py    # планировщик: сон, пробуждение, питание, простой, лимит, главный Mac
    python3 -I plugins/pantheon/tests/test_baseline.py   # замер «как сейчас»: задачи по git commit, сообщения, возвраты, цена
    python3 -I plugins/pantheon/tests/test_hooks.py   # хуки контекста и owner-log (и на системном: CTX_TEST_PYTHON=/usr/bin/python3)
    python3 -I plugins/project-tools/tests/test_project_tools.py   # карта стеков, apply, одобрения, Codex, подсказка
    claude plugin validate .  &&  claude plugin validate plugins/guard  &&  claude plugin validate plugins/pantheon  &&  claude plugin validate plugins/project-tools

Изменение защит проверяется вживую в изоляции: временные папки, `--plugin-dir` и `--settings` на одну
сессию, Haiku, хеш `~/.claude/settings.json` до и после.
