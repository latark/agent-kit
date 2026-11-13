# Образцы пакетов окон направлений — для тестов

Пакеты окон — личные настройки пользователя: они лежат в `~/.claude/pantheon/packs/<направление>/`, а не в плагине
(решение владельца 12.11). Здесь — два выдуманных образца того же устройства (схема А, metis-0933). Тесты копируют их
во временный HOME под нужным именем направления.

- `god-proj` — проект с вложенными app и gpu-worker: хуки через `_bin/in_repo.py` (protect-db.sh, pre-commit с
  `--plain`, `repo_hooks.py` reexport, fsd, env-sync, cuda-safety), prompt-хук Stop, серверы MCP через
  `_bin/env_from.py` с точными версиями npx и с ключами из `.env.local`, плагины окна, deny.
- `god-mail` — репозиторий `other/mailbox`: защитные хуки `--always`, ask, deny, `sandbox.denyRead` и `deniedDomains`.

Образцы скриптов хуков для god-proj — `../morph-hooks`.
