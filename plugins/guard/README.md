# guard

Правила, которые Claude Code проверяет сам, а не на память модели. Хук PreToolUse (Bash, Write, Edit, MultiEdit,
NotebookEdit, Read, Grep, Glob, WebFetch) и Stop; весь код — `hooks/guard.py`, его шапка перечисляет правила.

## От чего защищает (модель угроз, SEC-27, решено 14.10)

guard ловит **ошибки агента**: запись не в своё направление (domain), правку чужого файла штаба
(pantheon-acl), правку защит не той ролью (protect-config), команду пульта не той ролью, чтение ключей
(tg-secret), пометки об авторстве Claude, свой dev-сервер; с шага 1.2 — по ролям Пантеона: личное (private: `me/`,
ключи git-crypt, журнал штаба — только hq, chiron и mnemo-brain; ключи — никому из ролей), браузер владельца
(cdp-role: демон — prometheus читает, мастерская действует; прямой отладочный порт и WebFetch на локальные адреса —
никому; ловит по номеру порта, а не по записи адреса; у WebFetch — ещё имена вроде localtest.me и nip.io, а при Surge
имена разрешаются в 198.18/15 и настоящий адрес не виден — это предел правила), push (только в свою ветку, не в main/master, без force — в том
числе `+ветка` — и удаления; `gh api` с записью — нет; `gh pr merge` — только координатор из `[merge]` в policy.toml в своём репозитории, без `--admin` и `-R`; координатор с личным в папке — mnemo-brain —
не отправляет сам; отправляют только свой репозиторий — папки своего направления), печать в терминал (terminal: osascript, tmux
send-keys и т. п. — ввод от имени владельца), пополнение корпуса (corpus-role: `corpus add`, `channel --videos`,
`krisp`, скрипты Krisp и Диска и их ключи в Связке — ни одной роли, только через посредника; штабу корпус закрыт целиком). dev-серверы субагентам dev-* и talos в своей worktree — можно.

От **намеренного обхода и внедрённых инструкций** он не защищает: что пишет программа изнутри
(`python script.py`, `node -e`, `make`), он не видит, а свой разбор Bash мы больше не наращиваем. Настоящая
граница:

- **песочница macOS** в окнах ролей (SEC-19, SEC-26) — её собирает `pantheon domains build` в
  `~/.local/state/pantheon/settings/<направление>.json`;
- **управляемые настройки** `/Library/Application Support/ClaudeCode/managed-settings.json` (SEC-28) —
  главные запреты и хук guard, которые не перебить настройками проекта и модами.

Находку проверки безопасности по разбору Bash разбираем как «ошибка агента или граница песочницы», а не как
новый раунд поиска обходов.

## Режимы и поведение при сбое (SEC-10, SEC-29)

| Запуск | Кто вызывает | Сбой всего скрипта |
| --- | --- | --- |
| без аргумента | хук этого плагина | пропускает действие; если guard уже вызывают управляемые настройки (`--managed`), хук плагина молчит |
| `--managed` | хук из управляемых настроек | пропускает действие |
| `--strict` | хук окна роли с `onFailure: "block"` | выход 2 — действие остановлено; таймаут или пропавший файл тоже останавливают |

Внутри: сбой правил-подсказок (dev-server, attribution, cdp, nextjs) пропускает действие; сбой проверки прав
(domain, pantheon-acl, protect-config) и tg-secret останавливает роль. Каждый сбой — строка в
`~/.local/state/pantheon/logs/guard-failures.log` (время, режим, место, тип ошибки; без текста команды),
строка статуса показывает число сбоев за сутки.

## Управляемые настройки (SEC-28)

Ставятся один раз на Mac, в вашем терминале (нужен пароль):

    sudo mkdir -p "/Library/Application Support/ClaudeCode"
    sudo install -m 644 ~/.claude/plugins/marketplaces/agent-kit/plugins/guard/managed-settings.json \
      "/Library/Application Support/ClaudeCode/managed-settings.json"

Файл — `managed-settings.json` рядом с этим README: запреты (ключи в Связке, `.env`, разрушительный git,
`rm -rf`, terminal-notifier) и хук guard из клона маркетплейса. Обновить — та же команда после обновления
маркетплейса. Проверка: в папке с `.claude/settings.json`, где разрешено `Bash(git clean *)`, команда
`git clean -n` всё равно получает отказ.

## Данные и выключатель

- `~/.local/state/pantheon/domains.json` — карта направлений, собирает `pantheon domains build` из
  `~/ai/pantheon/directions.toml`;
- `~/.claude/pantheon/policy.toml` — привилегии (кто metis-pantheon и mnemo-brain, доступ к личному),
  образец — `policy.example.toml`, правит только metis-pantheon;
- выключить правило: `GUARD_OFF=dev-server,nextjs` в `env` файла settings.json.

## Проверки

    python3 -I tests/test_guard.py        # правила, карта прав, привилегии, protect-config, режимы и журнал сбоев
    python3 -I tests/test_shell_diff.py   # живая сверка разбора Bash с настоящими zsh и bash (~1 мин)
