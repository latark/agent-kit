# Команды Зевса под песочницей окна Пританея (metis-1009)

Готово: каждая команда, которую зовёт роль Зевса, даёт либо путь, либо одну понятную строку, без трассировки.

- Источник списка — `roles/hq.tmpl`, `HQ_EXCLUDED` в `pantheon.py` и строки задачи metis-1009.
- Таблицу собирает тест `plugins/pantheon/tests/test_hq_commands.py` с `HQ_AUDIT_OUT=<файл>`. Для неё STATE закрыт
  правами файлов, открыты только `hq-rw/{locks,autostart-reset,start-req,saved}`, а `claude` подменён заглушкой.
- Столбец «мимо песочницы» показывает, совпадает ли команда с `excludedCommands` окна hq. Такая команда, вызванная
  одна, в настоящем окне идёт мимо песочницы и пишет STATE. Код в таблице — худший случай: команду вызвали в составе
  цепочки, и она осталась в песочнице.
- Столбец seatbelt заполняется только вне песочницы, где работает `sandbox-exec`, то есть в прогоне
  `pantheon outside test`. В окне разработчика вложенная песочница недоступна, поэтому там стоит «—».

Что изменилось:

| было | стало |
|---|---|
| `start <направление> "текст"` — трассировка PermissionError | поручение файлом во входящие направления и заявка start-req, код 0 |
| `start --restart` и `--over-cap` — заявка молча теряла флаг или трассировка | отказ одной строкой (код 2) до шлюза и до остановки копий: флаги проверяет start_gate там, где запуск идёт сразу |
| `start --at-cancel` — трассировка EPERM | строка `cancel` в заявке, плановый проход гасит разовый запуск, код 0 |
| `start --at` — трассировка | одна строка (код 1): oneshot.json закрыт, поднять сейчас — `start` с поручением |
| `agents` — трассировка снимка | список сессий и строка «снимок обновит плановый проход», код 0 |
| `reap`, `reap --auto` — «ps не прочитан» | та же строка с хвостом: это задача планового прохода (код 3, как был) |
| любая другая запись, закрытая песочницей | `run.py`: в окне роли одна строка «не сделано — песочница не даёт записать <путь>», код 1 |

| команда | мимо песочницы (excludedCommands) | код (chmod) | последняя строка (chmod) | код (seatbelt) |
|---|---|---|---|---|
| `pantheon start win-a поручение: проверь сборку` | да | 0 | pantheon start: поручение — ~/ai/pantheon/directions/win-a/inbox/2026-11-08-214512-start-2fce3b.md; если окно win-a уже работает, заявка его не перезапустит — передай ему сообщением | — |
| `pantheon start win-a` | да | 0 | pantheon start: заявка принята, окно win-a поднимется на следующем проходе | — |
| `pantheon start win-a --restart` | да | 2 | pantheon start: отказ — запуск сразу окну hq не записать — песочница закрывает STATE/settings/run; флаги со словом владельца (--restart, --over-cap) проверяет start_gate только там, где запуск идёт сразу; без флагов — за | — |
| `pantheon start win-a --restart поручение` | да | 2 | pantheon start: отказ — запуск сразу окну hq не записать — песочница закрывает STATE/settings/run; флаги со словом владельца (--restart, --over-cap) проверяет start_gate только там, где запуск идёт сразу; без флагов — за | — |
| `pantheon start win-a --at 23:59 поручение` | да | 1 | pantheon start --at: не записан — песочница окна закрывает STATE/oneshot.json; поднять win-a сейчас — pantheon start win-a "поручение" (входящие и заявка, окно поднимет плановый проход) | — |
| `pantheon start --at-list` | да | 0 | at-20991231-2359-win-a: win-a в 2100-01-01 03:59, срок 04:59 | — |
| `pantheon start --at-cancel at-20991231-2359-win-a` | да | 0 | pantheon start --at-cancel: отмена at-20991231-2359-win-a принята — плановый проход погасит его до запуска | — |
| `pantheon start workshop metis-0001` | да | 1 | pantheon start: нет окна ~/.local/state/pantheon/settings/workshop.json — pantheon domains build | — |
| `pantheon start zeus` | да | 1 | нет окна Пританея — сначала pantheon domains build | — |
| `pantheon agents` | да | 0 | pantheon agents: сессий 0; снимок STATE/agents.json окну не записать (песочница) — его обновит плановый проход | — |
| `pantheon who` | да | 0 | win-a  нет сессии | — |
| `pantheon status` | нет | 1 | pantheon: нет права записи в ~/.local/state/pantheon/locks (Permission denied) — работаю без блокировки alerts: подъём этой же сессии в ту же секунду может проскочить | — |
| `pantheon jobs` | нет | 0 | reap    light  all  30 мин     —                 на ближайшем плановом проходе  ок | — |
| `pantheon wake win-a` | да | 0 | пропуск: win-a — нет уснувшей сессии (новая: pantheon start win-a) | — |
| `pantheon stop win-a` | да | 1 | pantheon stop: не сделано — окну hq песочница не даёт записать ~/.local/state/pantheon/stopped (Permission denied); эту запись делает плановый проход или запуск вне окна | — |
| `pantheon resume win-a` | да | 0 | win-a: метки «остановлено вами» нет; счётчик сбоев самозапуска сброшен | — |
| `pantheon pause win-a` | да | 2 | pantheon pause <имя>\|--all --reason limit\|swap\|manual ["почему"]  \|  pantheon pause --off [<имя>\|--all] | — |
| `pantheon restart --status` | да | 1 | технический перезапуск не готовится (pantheon restart --prepare) | — |
| `pantheon saved --by zeus` | да | 1 | технический перезапуск не готовится и перезапуска после обновления плагинов нет — отмечать нечего | — |
| `pantheon alert проверка из окна hq` | да | 0 | pantheon: нет права записи в ~/.local/state/pantheon/locks (Permission denied) — работаю без блокировки alerts: подъём этой же сессии в ту же секунду может проскочить | — |
| `pantheon archive` | да | 1 | pantheon archive: не сделано — окну hq песочница не даёт записать ~/.local/state/pantheon/locks/pantheon-git.lock (Permission denied); эту запись делает плановый проход или запуск вне окна | — |
| `pantheon night status` | нет | 0 | Разовый запуск at-20991231-2359-win-a: win-a в 2100-01-01 03:59, срок 04:59 | — |
| `pantheon usage` | нет | 0 | pantheon: нет права записи в ~/.local/state/pantheon/locks (Permission denied) — работаю без блокировки alerts: подъём этой же сессии в ту же секунду может проскочить | — |
| `pantheon executors` | нет | 0 | исполнители: claude | — |
| `pantheon task show metis-0001` | нет | 1 | нет задачи metis-0001 | — |
| `pantheon consent metis-0001` | да | 1 | ответа владельца на metis-0001 в окне вопросов, в чате Зевса, на доске и в привязках Зевса за 7 дн. нет | — |
| `pantheon handoff route -- команда не найдена` | нет | 0 | Пантеон (metis-0832): отказ (роль) — это умеет «да» владельца. Нужного исполнителя нет — вопрос владельцу «да/нет» через Зевса: `pantheon task new --direction <своё направление> --owner zeus --question "…" --why "…" --op | — |
| `pantheon outside status` | нет | 0 | итогов нет | — |
| `pantheon reap --auto` | нет | 3 | pantheon reap --auto: список процессов не прочитан (ps) — гасить нечего; в окне hq список процессов закрыт песочницей — это задача планового прохода (раз в 30 мин), он сделает её сам | — |
| `pantheon reap` | нет | 3 | pantheon reap: список процессов не прочитан (ps) — гасить нечего; в окне hq список процессов закрыт песочницей — брошенное раз в 30 мин гасит плановый проход (reap --auto), остальное выносит в вопрос его проверка «виновн | — |
