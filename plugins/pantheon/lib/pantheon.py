#!/usr/bin/env python3
"""Пантеон: планировщик pantheon-tick и команда pantheon.

Всё, что Пантеон делает сам по времени, идёт через одну задачу launchd `pantheon-tick` (раз в 60 с).
Список задач — ~/ai/pantheon/schedule.toml (правит Пританей); метки запусков — ~/.local/state/pantheon/
(свои у каждого Mac). Что пора запускать, плановый проход решает по меткам, а не по часам: пропуски за сон Mac
сливаются в один запуск. Лёгкие задачи (копия, коммит, дежурный) идут сразу; тяжёлые — по одной,
с паузой, не в первые минуты после пробуждения, от сети, а задачи на Claude — ещё при простое и
свободном пятичасовом лимите; предел ожидания max_delay снимает эти условия. Задачи с
hosts = "primary" идут только на главном Mac (primary_host).

Команды:
  pantheon jobs                         что установлено, когда шло, что дальше и почему ждёт
  pantheon jobs pause|resume|disable|enable <задача>   (--all — весь планировщик)
  pantheon jobs renew <задача> [дней]   продлить аренду задачи
                                        (службы [[service]] — те же pause|resume|disable|enable: launchd снимается сразу)
  pantheon qmd config|update|embed|serve|install|status   общий поиск qmd: index.yml из ~/ai/pantheon/qmd.toml,
                                        освежить индекс, сервер MCP (служба), подключить к Claude на этом Mac
  pantheon qmd where "вопрос" [--collection X]   где лежит (metis-0856): коллекция | путь | заголовок | направление-хозяин,
                                        без текста документов; для окна Пританея — по коллекциям проектов направлений
  pantheon plugins update [--quiet]     новые версии плагинов agent-kit (плановый проход раз в 10 мин): ставит
                                        выпуск, если запись в releases.json каталога совпала с ним (версия и дерево);
                                        тесты — в GitHub Actions до слияния, локального прогона нет (п. 8, 27.10);
                                        на новом выпуске смотрит tests на main: красный — тревога на коммит (metis-0587);
                                        после установки плановый проход перезапускает свободные окна (metis-0181)
  pantheon plugins accept [--new] [guard] [pantheon]   принять установленное дерево как проверенное (verified.json):
                                        живой код и окна ролей идут только на проверенное (metis-0321); только руками
  pantheon direction check <имя>        что готово у нового направления (навык new-direction): реестр, «да»,
                                        папки, STATUS.md, domains.json, AGENTS.md, доверие, autoMode
  pantheon direction init <имя>         папка ~/projects/<имя> по вашей галочке: git init, AGENTS.md, локальный
                                        коммит; без remote. ~/ai/life/<имя> — то же, свой git у каждой
                                        области; сам ~/ai/life — простая папка без .git
  pantheon migrate-paths <перенос>… [--dry-run]   после переноса папки: старые пути → новые во всех текстовых
                                        файлах ~/ai и ~/.claude (код agent-kit — нет), папки истории ~/.claude/projects
                                        и записи projects в ~/.claude.json под новый ключ; переносы: agent-kit,
                                        workshop, finances. Без --dry-run — только когда старой папки уже нет
  pantheon check --moved                старые пути перенесённых папок в живых файлах — предупреждение
  pantheon instructions [--quiet]       дойдут ли инструкции целиком: Codex (лимит на путь), MEMORY.md
                                        (200 строк / 25 КБ), CLAUDE.md с импортами длиннее 200 строк
  pantheon alert "<строка>" [--from кто] [--critical]   дописать строку в ~/ai/pantheon/alerts.md
                                          (--critical — ещё и уведомление macOS: COMM-08)
  pantheon archive                      «Сделано» доски старше 7 дней и тревоги старше 30 — в archive/
  pantheon domains build                ~/ai/pantheon/directions.toml → ~/.local/state/pantheon/domains.json
                                        и настройки окон ролей с песочницей …/settings/<направление>.json;
                                        окнам из карты plugins-by-role.toml — enabledPlugins: false и
                                        permissions.deny mcp__<сервер> вне их «оставить» (metis-0238)
  pantheon view [--quiet]               обновить копию ~/ai/pantheon-view для Obsidian
  pantheon board                        доска владельца ~/ai/pantheon-view/Доска: карточки, ваши ходы, сводка
  pantheon board archive [--days N]     датированные блоки board.md («Сейчас», «Сессии и хозяйство») старше N дней
                                        (по умолчанию 7) — в archive/ГГГГ-ММ.md без потерь; check следит за board.md
  pantheon status                       один экран для отладки: плановый проход, сессии, вопросы к вам, тревоги, защиты, sync, места heavy, версии
  pantheon night [status|report]        недельный лимит: неделя, линия, запас, зона, ночь, снимок; report — блок
                                        «Лимит» для сводки (lib/night.py)
  pantheon night ask <id> <направление> [ГГГГ-ММ-ДД]   вопрос о ночной пачке для окна вопросов Зевса: ночь
                                        открывается только по вашему «Да — ночь <дата>», sha256 пачки сверяется
  pantheon read request|run|status|cancel   чтение переписки по заявке (metis-0267, 0508, lib/read.py): папка, чаты
                                        по имени, @имени или ссылке → проход находит чаты → ваше «да» на [read-<rid>]
                                        со списком чатов → выгрузка и один разбор → вы одобряете пункты; источник —
                                        надстройка из [read] в STATE/config.toml
  pantheon merge request|run|status|cancel   слияние PR ядра по Touch ID (metis-0285, lib/merge.py): заявка роли →
                                        плановый проход заново сверяет шлюз → окно Touch ID → gh pr merge этого SHA;
                                        `request N1 N2 … -R repo` — пачка: одно окно, сливает по очереди (metis-0668)
  pantheon batch start|pr <story>      пачка — одна ветка и один PR (lib/batch.py, metis-0757): start — ветка
                                        batch/<story> от origin/main и копия .claude/worktrees/batch-<story>;
                                        pr — один PR ветки в main, в теле задачи пачки и Closes (--dry-run — показать)
  pantheon outside test|serve|status|stop|run   проверка вне окна роли (lib/outside.py, [sb-simplify] п. 7):
                                        тесты проекта или dev-сервер (своя копия на коммите, порт 4300–4399, не
                                        больше двух) под sandbox-exec без ключей, браузеров и
                                        местного прокси → код и хвост журнала или адрес; сам тесты после «принять»
                                        argus не гоняет — заявку подаёт роль, дежурный тревожит через 1 ч
  pantheon browser health|open|read|eval|allow|click|type|submit|delete|status|run   браузер владельца для роли
                                        charon без пароля и порта (lib/browser.py, metis-0760, 0765): заявка из окна →
                                        проход вне окна; чтение — сайты reads.toml; действия — по поручению (allow),
                                        отправка и удаление — Touch ID или «да» на каждую; оплата и важные формы — нет
  pantheon handoff route|touch|status|cancel|run   отказ роли → кто умеет (lib/handoff.py, metis-0832, 0775): route —
                                        подсказка (Харон, Гестия, outside, read, «да» через Зевса); touch — действие из
                                        белого списка (worktree-remove, deploy, cdp-restart) → проход вне окна → окно
                                        Touch ID с этим действием целиком → исполнение один раз по sha256 текста
  pantheon traces [--markers ФАЙЛ] | install-hook   личные следы до push (lib/traces.py, metis-0414): та же проверка, что CI
                                        check-traces; маркеры — файл вне репозитория; нет файла — отказ, код 2; install-hook ставит pre-push
  pantheon mmv [--days N]               минуты владельца на систему по дням (по меткам owner-log) → STATE/mmv.jsonl
  pantheon sync-answers                 ваш ответ на доске по карантину ~/.claude — применить сразу (sync.sh), без новой сессии
  pantheon check [файл…] [--quiet]      проверить шапки задач по схеме v1 (schema.md) и правила metis-0308: задача пачки без mode,
                                        закрытая по слиянию без release/actual, review больше суток без PR, нет приёмки; done
                                        без closed — исправляет сам (closed из updated); навыки (SKILL.md плагина и ~/.claude/skills):
                                        шапка, name = папка, description ≤ 1024, ссылки на файлы (metis-0258); directions.toml: coordinator не true/false — ошибка,
                                        у выключенного направления открыт координатор или нет лида — предупреждение (с --quiet —
                                        тревога об открытом координаторе)
  pantheon who-canvas [--force]         пересобрать «Кто есть кто.canvas» по ролям, реестру и статусу задач; место карточек
                                        и размеры берёт с холста; в расписании — command =
                                        "~/.local/share/pantheon/current/scripts/who-canvas.sh", every = 5; пишет только
                                        при смене входов (metis-0825)
  pantheon autoclose fetch              сетевой проход (задача расписания): gh про слитые и открытые PR из [merge_repos] →
                                        кэш; на главном Mac сразу проход по кэшу (и плановый проход каждую минуту) закрывает задачи, чей номер в
                                        ветке или после «Closes» в теле PR — в том же проходе, что увидел слияние (metis-0868)
  pantheon task new --direction D --title T [--type task|story --status S --priority N --due ГГГГ-ММ-ДД[TЧЧ:ММ]
                    --next X --owner O --release R --batch X --night ГГГГ-ММ-ДД --estimate X --actual X
                    --acceptance принято|вернуть|к владельцу --parent ПАЧКА --mode self|single|parallel|undecided --mode-why X --touches ПУТЬ …
                    --project P --waiting-on W --question Q --why W --option "А — … Цена: …" --option …
                    --recommend "А — потому что …" --if-no-answer "…" --depends-on ID --executor auto|claude|codex
                    --text|--body "текст" | --body-file ПУТЬ
                    --from слово владельца|отчёт|ревью|остаток|план|по ходу --source ID|ПУТЬ#якорь   откуда задача (metis-0502)
                    --done-when "пункт" …]   пункты раздела «Готово, когда» (повторяемый); без него в теле — раздел с подсказкой;
                    у --type story пункт обязателен (--done-when или раздел в --body), иначе отказ (metis-0766)
                    текст задачи (цель, «готово, когда») обязателен: без --text/--body/--body-file — отказ, код 2;
                    без текста можно только вопрос владельцу: --question, --why и не меньше двух --option, иначе код 2;
                    неизвестный флаг (и «--флаг=значение») — отказ с его именем, код 2, файл не создан (metis-0402);
                    повторяются только --option, --touches, --depends-on; другой флаг дважды (два --body) — отказ, код 2;
                    новая задача → файл-уведомление «…-task-ID.md» в directions/<направление>/inbox/ координатору
                    (не находка; «От:» — PANTHEON_SESSION, PANTHEON_ROLE или «агент»)
                    без --owner «Кому» — координатор направления; owner= (пусто) в task set — отказ;
                    --batch без --mode (и без mode в шапке) — отказ: режим обязателен при сборке пачки (metis-0308);
                    --depends-on / depends_on= с несуществующим id, самой собой или циклом — отказ при записи (metis-0248)
  pantheon task set ID поле=значение … [--option "вариант" …] [--note "строка в журнал"] [--body "текст" | --body-file ПУТЬ]
                    [--force "причина"]  (status=done при неотмеченных «Готово, когда» у задач с 27.10 — отказ; --force пишет причину в журнал)
                    --body[-file] заменяет текст задачи между «# заголовок» и «## Журнал» («Заметки владельца» остаются),
                    свои пункты — в тексте строкой «## Готово, когда» и списком «- [ ] пункт»: раздел заменяет прежний (metis-0591);
                    в журнал — «текст задачи заменён (было N знаков…)»; неизвестный флаг и повтор флага, кроме --option, —
                    отказ, код 2; время строки журнала ставит pantheon: время в начале --note («23:45 — …») не пишется
                    (предупреждение); карточки изменились (task set/new/claim/…) — задачи расписания view и board сразу (metis-0868)
                    плановый проход (check --quiet): открытая задача без текста дольше часа — тревога; слово владельца с [id]
                    (decisions.md, окно вопросов, ответ в чате) дольше 30 мин без задачи — тревога один раз на id: связь — [id] в
                    тексте задачи до «## Журнал» (любой статус) или строка «не задача: [id] — причина» в decisions.md;
                    тревога называет до 12 новых id, остальные — следующим проходом; источник не прочитался — проход
                    пропущен; id в пометке — как в окне вопросов (бывает без дефиса). Пустые --option не варианты;
                    пустой --body/--body-file в task set — отказ, код 2; вопрос с текстом без --why/вариантов — предупреждение
  pantheon task show ID
  pantheon task goal ID [ID …]   строка цели окна по задаче на эту минуту (metis-0725, metis-0738): «<id>: снята с цели
                    окна — почему» (закрыта, во входящих, ведёт другая сессия — owner не окно PANTHEON_SESSION и не его
                    команда, «ждёт» владельца с вопросом или задачу-блокер) или «<id>: остаётся в цели окна — почему»;
                    нет задачи — код 1. task set owner=… из окна печатает ту же строку
  pantheon task ready [--direction D] [--owner O]   pantheon task claim ID --by КТО [--hours 1]
                    ready в stderr предупреждает, если touches готовой задачи пересекаются с открытым PR (metis-0667)
  pantheon task batch-suggest [--direction D] [--json] [--apply]   (metis-0595) открытые задачи без пачки → «в существующую
                    пачку», «новая пачка из N задач», «дубли — объединить?»: общие файлы, похожесть, ссылки, общий PR; без
                    модели. Ничего не меняет; --apply прикрепляет только «уверенно» в существующую пачку
  pantheon batch-suggest run [--force]  плановая сводка раз в 3–4 суток → Доска/Пачки-предложения.md (задача расписания)
  pantheon task failures [--days 7]   (metis-0859) сводка по классам: счётчики строк журнала «провал: <класс> — <довод>»
                    за N дней (непонятная задача, неверный подход, не хватило контекста, трудная логика, прочее) и id задач
  pantheon task overlap ID   перед раздачей (metis-0665): touches задачи против живых (doing, review) задач её
                    направления и файлов открытых PR его репозиториев ([merge_repos] policy.toml; gh, не ответил — кэш
                    планового прохода, нет и его — строка «не проверено»); пересечение — выбор с командами: очередь
                    (ждать слияния PR) или ветка от ветки PR, argus — только дельта. Предупреждение, не отказ: код 0.
                    То же предупреждение — в stderr после task set ID status=doing и task claim
  pantheon task migrate-project [--write]   project карточек → имя проекта из directions.toml; без --write — сухой
                    прогон «id: было → станет», с --write — запись через task set со строкой в журнал (metis-0323)
  pantheon task migrate-batches [--dry-run]   поле batch «имя · место» → пачка (story) «имя», задача прикреплена по месту
  pantheon task migrate-mode [--dry-run]   разово: открытым задачам всех направлений без mode — mode undecided («не
                    решено»); задачи пачек, пачки, закрытые и входящие не трогает; с --dry-run — только план (metis-0505)
  pantheon task split ID --title "остаток" [--done-when "пункт" …] [--text "описание"] [--mode M --mode-why X]
                    остаток исходной задачи — новой задачей в том же направлении: from=остаток, source=ID, тег «остаток»,
                    та же пачка; пункты — из --done-when, иначе неотмеченные из исходной; строка в журнале обеих (metis-0502)
  pantheon task attach ID ПАЧКА | detach ID   задача в пачку (story) и обратно; show ПАЧКА — состав и сумма оценок
  pantheon executors                    набор исполнителей кода (Claude всегда, Codex — дополнение) и включён ли Codex
  pantheon executors check              проверить Codex: на PATH → вход (CODEX_HOME роли) → hello-проба
  pantheon executors --add codex | --remove <имя>   добавить Codex (через проверку, без входа) | убрать (Claude — отказ)
  pantheon executors pick <id задачи> [--kind mechanics|code|hard]   кто пишет задачу: dev-* или codex-dev
  pantheon exec codex <worktree> <файл поручения>   запуск Codex для codex-dev: среда без секретов, монитор тишины,
                                        защищённые пути, коммит с трейлером Executor: codex; push — никогда
  pantheon start <направление> [поручение]   координатор: фоновая сессия domain-coordinator в окне направления
  pantheon start workshop <задача> [поручение]   мастерская: daedalus-<задача> в ~/ai/workshop/<задача> (до
                                        переноса, пока ~/ai/workshop нет, — в старой папке workshop в ~/projects)
  pantheon start zeus                   Пританей: ваша сессия hq в ~/ai/pantheon с окном hq.json   (--from zeus|tick|owner)
                                        start, дошедший до запуска сессии, пишет замер в capacity.jsonl; --from zeus без слова владельца — отказ (код 2); красный замер или «нет сигнала» — только предупреждение (stderr, тревога раз в день), запуск идёт; в окне роли origin берётся из PANTHEON_ROLE, явный --from там только свой (hq → zeus, иная роль → tick); wake пишет строку замера и не откладывает, wake <имя> "задание" из окна роли без слова владельца — отказ (код 2)
  pantheon start <направление> --at ЧЧ:ММ [поручение]   разовый запуск плановым проходом вместо sleep в сессии;
                                        --at-list — записи, --at-cancel <id> — отменить (lib/night.py)
  pantheon wake [--dry-run]             поднять прерванные сессии Пантеона с открытой задачей и сказать «продолжай»
  --over-cap (start, wake)              недельный потолок владельца достигнут — start и wake отказаны (код 2), кроме
                                        start zeus и wake hestia; флаг запускает сверх потолка только из вашего терминала (metis-0444)
  pantheon watch [--dry-run]            дежурный (плановый проход раз в 5 мин): сессии, STATUS.md, swap, worktree, версия Claude Code,
                                        паузы, самозапуск по вашим решениям; --dry-run — кого поднял бы и почему нет
  pantheon reboot-reminder [--now]      пятница после 09:30: Mac не перезагружался с прошлой пятницы — карточка и уведомление
  pantheon agents | who                 снимок claude agents для строки статуса | таблица координаторов
  pantheon roster                       реестр демона Claude Code без ключей сокетов: JSON с updatedAt и у каждого воркера
                                        id, pid, startedAt; сам файл агентам закрыт (guard daemon-roster, metis-0871)
  pantheon revisits                     пересмотры к сроку и по событиям (плановый проход раз в сутки)
  pantheon wake <имя> ["задание"]        поднять уснувшую сессию направления той же сессией; задание из окна роли
                                        — только по слову владельца в окне Зевса за 15 мин, иначе код 2
  pantheon wake hestia --task <id> [--restart] [--dry-run]   Гестия в своём окне песочницы (settings/hestia.json) с открытой
                                        задачей; без задачи или с закрытой — отказ «нет задачи» (код 2); из окна
                                        роли — только по слову владельца в окне Зевса за 15 мин, иначе код 2;
                                        из окна hq — как start --from zeus
  pantheon wake <направление> --task <id> [--dry-run]   направление с coordinator = false в directions.toml ведёт
                                        Пританей (metis-0155): start/wake координатора — отказ (код 2), а это поднимает
                                        фоновое окно лида hephaestus-<коротко> с окном и ролью координатора (settings/<направление>.json,
                                        --agent domain-coordinator) и задачей как целью; задача — открытая этого
                                        направления, иначе «нет задачи» (код 2); слово владельца — как у wake hestia
  pantheon stop <имя>|--all, resume <имя>|--all   остановить (метка «остановлено вами», claude stop и claude rm —
                                        сессия уходит из фоновых сессий Claude Code) и вернуть
  pantheon pause <имя>|--all --reason limit|swap|manual ["почему"], pause --off [<имя>|--all]   пауза по нагрузке
  pantheon restart --prepare [причина]|--status|--go [--force]|--done|--cancel   технический перезапуск всех сессий
  pantheon saved --by <имя> --state <путь>   сессия сохранилась перед техперезапуском; без техперезапуска —
                                        метка «можно» для перезапуска после обновления плагинов
  pantheon infra-check                  опоры системы после обновления Claude Code
  pantheon wt done <путь> [--dry-run]   убрать копию .claude/worktrees/<имя> после отчёта субагента или слияния PR
                                        (metis-0835): без вопроса и сырого git, только без живой сессии, процесса,
                                        субагента и правок моложе 10 мин в ней; ветка остаётся (detached — ветка
                                        archive/wt-<имя>), грязная — сначала патч, неотслеживаемое и игнорируемое
                                        (.env.local) — в архив в STATE/wt-archive. В окне роли — заявка в
                                        кэш окна, её исполняет плановый проход (раз в 5 мин); занятая копия ждёт в
                                        заявке. Код: 0 — убрана или заявка принята, 1 — нельзя (причина), 2 — не та папка
  pantheon wt plan [<папка> …]          сухой прогон уборки копий: что дежурный сделал бы с каждой копией; ничего не меняет
  pantheon reap [--apply] [--pid N …]   виновники памяти (lib/culprits.py, metis-0568): процессы claude/node/tsx/
                                        next/vitest/pnpm и сироты multiprocessing старше 2 ч — чей, память, возраст;
                                        --apply гасит только брошенное (worktree удалён, задача закрыта, сирота в
                                        папках Пантеона) и печатает вопрос «[id] …» об остальном своём; --pid — после
                                        «да» владельца, только процессы Пантеона (у Гестии — по `pantheon consent`)
  pantheon reap --auto                  плановый проход раз в 30 мин (metis-0617): гасит только брошенное старше
                                        30 мин — сироты multiprocessing и сироты в песочнице окна, процессы удалённых
                                        worktree и закрытых задач, language server без живого claude (прямо под
                                        launchd, ppid 1, — только в удалённой копии или копии закрытой задачи; в
                                        живой копии не гасит); строка «погашено: …» в alerts.md
  pantheon usage [дней]                 отчёт расхода в ~/ai/pantheon/metrics/usage/ (плановый проход раз в неделю);
                                        запись закрыта (окно роли) — отчёт в stdout, причина в stderr, код 1
  pantheon metrics sync|summary|run     учёт по задачам: строки закрытых задач в ~/ai/pantheon/metrics/tasks.jsonl
                                        (пишет и `task set status=done|dropped`), свод недели — week-<неделя>.md
                                        и заметки Пульта; summary — свод в окно
  pantheon metrics backfill --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] [--dry-run]   задним числом: строки закрытых за
                                        эти дни задач с пометкой «оценка» (у кого строки нет)
  pantheon roles build                  роли ~/.claude/agents/*.md из общих шаблонов плагина (roles/*.tmpl,
                                        roles/_parts/*.part) и личного слоя ~/.claude/agents (*.tmpl, _parts/*.part
                                        перекрывают общие по имени); подстановки — из [person] directions.toml;
                                        роли из карты plugins-by-role.toml получают в disallowedTools шапки
                                        mcp__<сервер> каждого MCP каталога вне своего «оставить» (metis-0238)
  pantheon roles build --out <папка> [--src <папка шаблонов>]   проба: собрать роли в --out, личный слой — из
                                        --src (по умолчанию ~/.claude/agents) поверх общего; живые роли не трогает,
                                        сигналов нет; --out в ~/.claude/agents или внутри — отказ (код 2)
  pantheon role propose <имя> --direction D   заявка на личную роль (metis-0262): черновик ~/ai/pantheon/roles/
                                        proposed/<имя>.tmpl → карточка «Применить роль <имя> [<sha256>]?» Да/Нет,
                                        статус proposed в ~/.local/state/pantheon/roles/status.jsonl
  pantheon role apply <имя>             поставить роль по вашей галочке «Да» (журнал доски, ≤ 14 дней, на карточке
                                        заявки, тот же полный sha256 черновика): имя не общей роли и не лида, ≤ 5 КБ,
                                        без hooks/settings/mcpServers/permissionMode и повторов ключей в шапке →
                                        пробная сборка, шапка собранной роли сверяется так же → <имя>.tmpl в
                                        ~/.claude/agents → roles build; плановый проход делает это сам, «Нет» — rejected
  pantheon role status [<имя>] | cancel <имя>   заявки на роли | отозвать открытую заявку
  pantheon approve [list] | add --site S --allow "…" [--limits "…"] | remove N   заранее разрешённое (только вы)
  pantheon launch-question <id> запустить|перезапустить|вернуть <направление>   вопрос и варианты для окна вопросов
                                        Зевса: ваш выбор «Да — запустить <имя>» плановый проход исполняет сам
                                        (metis-0523); «вернуть» снимает и «остановлено вами»
  pantheon consent <id> [--days N]      ваш ответ Зевсу на вопрос <id> (журнал owner-log Зевса, по умолчанию 7 дней) —
                                        для исполнителя: согласие, данное в окне Зевса
  pantheon consent bind <id> --log-at <ЧЧ:ММ[:СС] | ГГГГ-ММ-ДД ЧЧ:ММ[:СС]>   только окно Зевса: привязать к <id>
                                        ваше прямое слово без вопроса с [id] — одну строку owner-log/zeus.md без
                                        пометки (своего текста команда не берёт); consent <id> покажет её дословно,
                                        метку Гестии и согласие браузера она не даёт (metis-0843)
  pantheon review test -- <команда…>    тесты для шлюза слияния (guard 0.5.9): в чистом дереве git запустить
                                        команду (без оболочки); HEAD и дерево после неё те же — выход с её кодом
                                        и SHA; запись в журнал делает хук guard (PostToolUse), сама команда не пишет;
                                        пустая программа (true, echo, heavy :…) записи не даёт
  pantheon review accept <owner/repo> <PR> <SHA> --opened "<что открыл>" --ran "<что запустил>"
                                        --unchecked "<что не проверял>"   «принять» argus с перечнем проверенного
                                        (без трёх полей шлюз не пускает); reject — те же флаги по желанию;
                                        talos <owner/repo> <PR> <SHA> — проверка talos. Команда проверяет формат,
                                        запись — хук guard и только по роли (accept, reject — argus). Шлюз считает
                                        последний вердикт каждого рецензента (сессия + агент) на (repo, PR, SHA) и
                                        пускает, только если последний у каждого — «принять» с полным перечнем и ни
                                        один рецензент не сливающий
  pantheon review begin <owner/repo> <PR> <SHA 40 знаков>   метка «ревью идёт» (argus позван, вердикта нет), чтобы
                                        второго argus не звали одновременно. Пишет только
                                        STATE/review-pending/<owner>__<repo>__<PR>.json; это НЕ вердикт и НЕ согласие,
                                        шлюз её не читает. Гаснет по вердикту (accept/reject) на этот PR и через 2 часа
  pantheon review miss <owner/repo>#<PR> --by <argus> --text "<что пропустил>" [--class защиты|ядро|вне ядра]
                                        пометка пропуска (metis-0401): ошибка найдена в PR, который argus принял;
                                        нужен «принять» на этот PR в журнале шлюза. Строка в
                                        STATE/argus-misses.jsonl (кто принял и сколько argus — из журнала), доля — в
                                        своде недели metrics/week-*.md. Не вердикт и не согласие, шлюз её не читает
  pantheon review sample   выборочная проверка недели: PR ядра с одним argus (от 3 в одном репозитории — одним
                                        запуском), потолок 1 запуск в неделю, 2 — после недели с пропуском
  pantheon review report <owner/repo> <PR> <agent8>[/<сессия8>] [--out ПУТЬ]   последний отчёт прежнего argus
                                        из его транскрипта ~/.claude/projects/*/<сессия>/subagents/agent-<id>.jsonl
                                        (пара — из `review status`): после /clear SendMessage к нему не идёт, а новый
                                        argus ведёт повторный круг по дельте с этим отчётом (metis-0602). Нет файла,
                                        несколько совпадений, нет вердикта пары в журнале или «Head:» отчёта ≠ head её
                                        последнего вердикта — отказ, код 1; --out только под $TMPDIR или /private/tmp
  pantheon review status [<owner/repo> <PR>]   записи журнала ~/.local/state/pantheon/merge-gate/records.jsonl и
                                        метки «ревью идёт»; у вердикта — рецензент (agent_id/сессия, по 8 знаков),
                                        с PR — строка «итог на <head>: принять N, вернуть M» по последнему вердикту
                                        каждого argus: «принять» — только с полным перечнем, на любой модели (вне
                                        ядра шлюз так и считает); если часть «принять» не на Opus — ещё строка «для PR
                                        ядра» с числами только по Opus. По ним решают об узком повторе, metis-0393
  pantheon commit                       commit → pull без rebase → push ~/ai/pantheon
  pantheon install | uninstall          поставить или снять задачу launchd pantheon.tick
  pantheon tick                         один проход планировщика (его вызывает launchd)
Уведомления (lib/notify.py): присутствие по простою, тихие часы, утренний дайджест, повтор и «долго ждёт», склейка
по id решения, бюджет в день; пороги — таблица [notify] в schedule.toml, состояние и журнал — notify.json и
notify-log.jsonl в ~/.local/state/pantheon/.
Для синтетических тестов: PANTHEON_HOME, PANTHEON_STATE, PANTHEON_NOW — «сейчас», PANTHEON_HOST,
PANTHEON_FAKE_WAKE, PANTHEON_FAKE_AC, PANTHEON_FAKE_IDLE — простой в секундах, PANTHEON_FAKE_LIMIT, PANTHEON_DRYRUN,
PANTHEON_NO_NOTIFY — без уведомлений, PANTHEON_NOTIFY_LOG — уведомления строкой «заголовок|текст|ссылка|группа» в файл.
Тест или проба (PANTHEON_TEST или папка состояния не настоящая) на экран уведомлений не шлёт: они идут строкой
в STATE/notify-test.log (metis-0307).
"""
import contextlib
import errno
import fcntl
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

if sys.version_info < (3, 11):
    sys.exit("pantheon: нужен Python 3.11+ (здесь %d.%d, нет tomllib)" % sys.version_info[:2])
import tomllib

HOME = os.path.expanduser("~")
AI_HOME = os.path.join(HOME, "ai")  # рабочие папки системы: pantheon, pantheon-view, knowledge (переезд 14.10)
PANTHEON = os.path.realpath(os.environ.get("PANTHEON_HOME") or os.path.join(AI_HOME, "pantheon"))
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
VIEW = os.environ.get("PANTHEON_VIEW") or os.path.join(AI_HOME, "pantheon-view")
LIB = os.path.dirname(os.path.realpath(__file__))
PLUGIN = os.path.dirname(LIB)
LABEL = "pantheon.tick"
# Неизменный путь к плагину: на него смотрят задача launchd, команда ~/.local/bin/pantheon и обработчики слияния
# в ~/ai/pantheon/.git/config. Ссылка ведёт на УСТАНОВЛЕННУЮ версию — папку кэша из installed_plugins.json
# (metis-0321), а не на клон маркетплейса: клон `claude plugin marketplace update` в plugins-update пересоздаёт
# головой main сразу после слияния, и непроверенный код ожил бы у тика и всех задач мимо шлюза выпуска. Перевешивают
# её `pantheon install` и успешная установка в plugins-update (_plugin_install); установки нет — копия, из которой
# запущен install (рабочая копия при разработке).
CURRENT = os.path.join(HOME, ".local", "share", "pantheon", "current")
# Папка демона хуков guard (metis-0330, metis-0845): сокет, собранный клиент, pantheon-hookd службы. Окнам ролей — ни
# записи, ни сокета (GRANT_NO_WRITE, denyWrite каждого окна); службу ставит плановый проход (_hookd_sync)
HOOKD_HOME = "~/.cache/pantheon/hookd"
HOOKD_DIR = os.path.join(HOME, ".cache", "pantheon", "hookd")
TEMPFAIL = 75   # задача ждёт (нет сети): не сбой, тревоги нет
# plugins update (metis-0573): локального прогона тестов нет, остались две сетевые команды claude. По журналу
# logs/plugins-update.log последние 12 проходов — 11–27 с на всё; потолки с запасом в разы, а не 300/600 с
PLUGINS_CATALOG_TIMEOUT = 90    # claude plugin marketplace update: вышло — TEMPFAIL, тревоги нет
PLUGIN_INSTALL_TIMEOUT = 180    # claude plugin update одного плагина: вышло — сбой установки, тревога, сверка по хешу
ALERTED = 76    # сбой, о котором задача уже сообщила сама: вторую тревогу не давать
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LABEL + ".plist")
LIMIT_SNAPSHOT = os.path.join(HOME, ".local", "state", "claude-statusline", "five-hour")
DEFAULTS = {"heavy_gap_min": 2, "wake_quiet_min": 10, "idle_min": 10, "limit_max_pct": 70}


# --- общее --------------------------------------------------------------------

def now():
    return float(os.environ.get("PANTHEON_NOW") or time.time())


def stamp(t=None):
    return datetime.fromtimestamp(t if t is not None else now()).strftime("%Y-%m-%d %H:%M")


_HOST = None


def host():
    """Имя Mac — LocalHostName (не меняется от сети, в отличие от имени ядра)."""
    global _HOST
    if os.environ.get("PANTHEON_HOST"):
        return os.environ["PANTHEON_HOST"]
    if _HOST is None:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
        _HOST = out or socket.gethostname().split(".")[0]
    return _HOST


def path(*parts):
    return os.path.join(STATE, *parts)


# Окно Зевса пишет только в STATE/hq-rw/locks и STATE/hq-rw/autostart-reset (metis-0523, ревью безопасности): там замки
# имён сессий (start-*, wake) и метки сброса самозапуска, которые берут его `pantheon start|wake|stop|resume`. Замки
# прохода (tick, watch, board, notify, git…) — в STATE/locks, куда окно не пишет. Файл в hq-rw открывается
# hq_open: O_NOFOLLOW|O_NONBLOCK через дескриптор папки, затем fstat — обычный файл, одна ссылка, владелец — мы; иначе
# UnsafeFile, и файл не тронут. Ждущий замок в hq-rw ждёт не дольше HQ_LOCK_WAIT: окно не повесит проход.
HQ_RW = "hq-rw"
HEAVY_QUEUE = "heavy-queue"  # папка билетов очереди heavy в STATE/locks (metis-0659)
# start-req — заявки Зевса на запуск (metis-0771); saved — метка `pantheon saved --by zeus*`, когда в STATE/maintenance и
# STATE/plugins окно писать не может (metis-0577)
HQ_RW_DIRS = ("locks", "autostart-reset", "start-req", "saved")
HQ_LOCK_WAIT = float(os.environ.get("PANTHEON_HQ_LOCK_WAIT") or 60)  # с; переменная — для тестов
# errno, которые даёт подложенная запись (ссылка, FIFO без читателя, папка, не папка на месте папки) — это UnsafeFile
HQ_BAD_ERRNO = {errno.ELOOP, errno.ENXIO, errno.EISDIR, errno.ENOTDIR, errno.EMLINK, errno.EOPNOTSUPP}


class UnsafeFile(OSError):
    """Файл в папке окна Зевса — ссылка, жёсткая ссылка, не обычный файл или чужой: не пишем."""


def hq_lock_name(name):
    """Замок, который берёт и окно Зевса, — живёт в STATE/hq-rw/locks."""
    return name.startswith("start-") or name == "wake"


def hq_open(sub, fname):
    """Дескриптор для дозаписи STATE/hq-rw/<sub>/<fname> (создаётся, 0600) после проверки; иначе UnsafeFile/OSError."""
    if sub not in HQ_RW_DIRS or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", fname or ""):
        raise UnsafeFile(f"{sub}/{fname}: имя не по образцу")
    d = path(HQ_RW, sub)
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileExistsError:
        raise UnsafeFile(f"{sub}: на месте папки не папка") from None
    except OSError as e:
        if e.errno in HQ_BAD_ERRNO:
            raise UnsafeFile(f"{sub}: на месте папки ссылка или не папка ({e.strerror})") from None
        raise
    try:
        fd = os.open(fname, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=dfd)
    except OSError as e:
        if e.errno in HQ_BAD_ERRNO:
            raise UnsafeFile(f"{sub}/{fname}: ссылка, FIFO или папка ({e.strerror})") from None
        raise
    finally:
        os.close(dfd)
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
        os.close(fd)
        raise UnsafeFile(f"{sub}/{fname}: не обычный файл, ссылок {st.st_nlink} или владелец {st.st_uid}")
    return fd


def hq_mark(sub, fname, text):
    """Метка в STATE/hq-rw/<sub>: подложенную запись на месте имени (ссылку, FIFO, жёсткую ссылку) снимаем через
    дескриптор папки (unlink ссылку не проходит) и пишем заново. Не вышло — предупреждение и False, без исключения."""
    try:
        try:
            fd = hq_open(sub, fname)
        except UnsafeFile:
            dfd = os.open(path(HQ_RW, sub), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with contextlib.suppress(OSError):
                    os.unlink(fname, dir_fd=dfd)
            finally:
                os.close(dfd)
            fd = hq_open(sub, fname)
        try:
            os.write(fd, text.encode())
        finally:
            os.close(fd)
        return True
    except OSError as e:
        print(f"pantheon: метка {sub}/{fname} не записана — {e}", file=sys.stderr)
        return False


def hq_put(sub, fname, text):
    """Файл STATE/hq-rw/<sub>/<fname> с этим текстом (перезапись, проверки как у hq_open). UnsafeFile/OSError — наружу."""
    fd = hq_open(sub, fname)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, text.encode())
    finally:
        os.close(fd)


LOCK_CONTENDED = None  # имя замка, который в последний раз не взят потому, что его держит другой процесс (metis-0717)


@contextlib.contextmanager
def lock(name, block=True):
    """flock на файле в STATE/locks/ (замки имён сессий — в STATE/hq-rw/locks, см. выше). Отдаёт True, если взята.
    Не взята из-за чужого владельца (а не подложенной записи или отказа в праве) — LOCK_CONTENDED == name."""
    global LOCK_CONTENDED
    LOCK_CONTENDED = None
    shared = hq_lock_name(name)
    try:
        if shared:
            fd = hq_open("locks", name + ".lock")
        else:
            os.makedirs(path("locks"), exist_ok=True)
            fd = os.open(path("locks", name + ".lock"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        fh = os.fdopen(fd, "a")
    except UnsafeFile as e:
        print(f"pantheon: блокировка {name} не взята — {e}", file=sys.stderr)
        yield False
        return
    except OSError as e:
        if not (isinstance(e, PermissionError) and block and (name.startswith("start-") or name in ("alerts", "unlinked"))):
            if not shared:
                raise
            # любой иной сбой на пути hq-rw — отказ замка с предупреждением, а не падение start и прохода
            print(f"pantheon: блокировка {name} не взята — {type(e).__name__}: {e}", file=sys.stderr)
            yield False
            return
        # окно без записи в папку замков (собранное до metis-0523, metis-0078): ждущую блокировку имени сессии pantheon
        # stop берёт, чтобы подъём, начатый до метки «остановлено», не проскочил после неё. Без права записи метка
        # stopped/<имя> всё равно ставится первой, а проскочить может только подъём, уже прошедший проверку метки в ту
        # же секунду, — stop идёт без блокировки с предупреждением. Замок alerts — тоже: строка тревоги дописывается
        # одним write в режиме append, она не рвётся. Неблокирующие замки (start, тик) и git без файла не берутся.
        where = path(HQ_RW, "locks") if shared else path("locks")
        print(f"pantheon: нет права записи в {where.replace(HOME, '~')} ({e.strerror}) — работаю без "
              f"блокировки {name}: подъём этой же сессии в ту же секунду может проскочить", file=sys.stderr)
        yield True
        return
    got = False
    if shared and block:  # окно Зевса держит этот замок сколько угодно — проход ждёт не дольше HQ_LOCK_WAIT
        deadline = time.monotonic() + HQ_LOCK_WAIT
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    print(f"pantheon: блокировка {name} занята дольше {HQ_LOCK_WAIT:.0f} с — иду без него", file=sys.stderr)
                    break
                time.sleep(0.2)
    else:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))
            got = True
        except BlockingIOError:
            got = False
            LOCK_CONTENDED = name
    try:
        yield got
    finally:
        if got:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def locked(name):
    with lock(name, block=False) as got:
        return not got


def lock_held(name):
    """Держит ли кто замок name — для показа (metis-0266). Файл замка открывается только на чтение и проверяется
    LOCK_SH|LOCK_NB: чужой LOCK_EX отказывает, создавать и писать ничего не нужно, так что окно с песочницей, куда в
    STATE/locks не пишут (pantheon jobs), не падает с PermissionError. → True — держат; False — свободен или файла нет
    (замок не брали); None — не знаю: файл не читается, подложена ссылка (O_NOFOLLOW) или это не обычный файл."""
    p = path(HQ_RW, "locks", name + ".lock") if hq_lock_name(name) else path("locks", name + ".lock")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return None
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def read_json(p, default=None):
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _job_name(name):
    if not JOB_NAME.fullmatch(str(name)):
        raise ValueError(f"имя задачи не по образцу: {name!r}")
    return name


def job_state(name):
    return read_json(path("jobs", _job_name(name) + ".json"))


def save_job_state(name, st):
    write_json(path("jobs", _job_name(name) + ".json"), st)


def load_schedule():
    """schedule.toml; задачи с именем не по образцу [a-z0-9-] отбрасываются (имя идёт в пути меток и блокировок)."""
    p = os.path.join(PANTHEON, "schedule.toml")
    with open(p, "rb") as fh:
        sched = tomllib.load(fh)
    sched["defaults"] = {**DEFAULTS, **(sched.get("defaults") or {})}
    sched["notify"] = notify_mod().settings(sched.get("notify"))
    jobs = []
    for j in sched.get("job") or []:
        if isinstance(j, dict) and JOB_NAME.fullmatch(str(j.get("name", ""))):
            jobs.append(j)
        else:
            sched.setdefault("bad_names", []).append(str(j.get("name") if isinstance(j, dict) else j))
    sched["job"] = jobs
    # Службы (SCHED-05): постоянные процессы под launchd с KeepAlive — имена общие с задачами (одна метка состояния)
    services, names = [], {j["name"] for j in jobs}
    for s in sched.get("service") or []:
        if isinstance(s, dict) and JOB_NAME.fullmatch(str(s.get("name", ""))) and s["name"] not in names:
            services.append(s)
            names.add(s["name"])
        else:
            sched.setdefault("bad_names", []).append(str(s.get("name") if isinstance(s, dict) else s))
    sched["service"] = services
    return sched


CACHE_BIN = re.compile(r"(?:^|/)plugins/cache/[^/]+/(?P<plugin>[^/]+)/(?P<ver>[^/]+)/bin/?$")


def _vkey(v):
    """Ключ версии: числа, а не строки (0.5.10 > 0.5.9); пререлиз (1.2.0-rc1) старше выпуска 1.2.0."""
    base, _, pre = v.partition("-")
    nums = tuple(int(x) if x.isdigit() else 0 for x in base.split("."))
    return (nums, 0, pre) if pre else (nums, 1, "")


def installed_plugin_dir():
    """Эталон «своей» версии: установленная (realpath ссылки CURRENT), иначе запущенная (PLUGIN). Запущенная может быть
    старее установленной: окно, запущенное из сессии на прежней версии, не должно получить её bin первым."""
    try:
        real = os.path.realpath(CURRENT)
        if os.path.isdir(real):
            return real
    except OSError:
        pass
    return os.path.realpath(PLUGIN)


def clean_path(path_value, plugin_dir=None):
    """PATH без bin старых версий плагинов из кэша (metis-0342). Окно, запущенное из сессии на прежней версии, наследует
    её plugins/cache/<рынок>/<плагин>/<версия>/bin на первых местах, и `pantheon` идёт из старого кода. Свой плагин:
    остаётся только bin установленной версии (plugin_dir, по умолчанию installed_plugin_dir()). Чужой плагин: убирается
    bin версии, если рядом в кэше есть новее. Прочие пути и их порядок не меняются."""
    plugin_dir = os.path.realpath(plugin_dir or installed_plugin_dir())
    cur_ver, cur_plugin = os.path.basename(plugin_dir), os.path.basename(os.path.dirname(plugin_dir))
    out = []
    for d in (path_value or "").split(":"):
        m = CACHE_BIN.search(d)
        if m and d:
            parent = os.path.dirname(os.path.dirname(d.rstrip("/")))
            if m["plugin"] == cur_plugin:
                if m["ver"] != cur_ver:
                    continue
            else:
                try:
                    newer = [v for v in os.listdir(parent) if _vkey(v) > _vkey(m["ver"])]
                except OSError:
                    newer = []
                if newer:
                    continue
        out.append(d)
    return ":".join(out)


def nvm_bin():
    """bin версии node по умолчанию из nvm (alias/default, иначе новейшая): там node, pnpm и corepack. Окна запускает
    launchd без ~/.zprofile, и nvm в их PATH не было — `pnpm check` разработчика не находил pnpm (metis-0563)."""
    root = os.path.join(os.environ.get("NVM_DIR") or os.path.join(HOME, ".nvm"), "versions", "node")
    try:
        vers = sorted((v for v in os.listdir(root) if v.startswith("v")), key=lambda v: _vkey(v[1:]))
    except OSError:
        return None
    try:
        want = open(os.path.join(os.path.dirname(os.path.dirname(root)), "alias", "default")).read().strip().lstrip("v")
    except OSError:
        want = ""
    pick = [v for v in vers if want and (v[1:] == want or v[1:].startswith(want + "."))]
    v = (pick or vers or [None])[-1]
    return os.path.join(root, v, "bin") if v else None


def run_env():
    env = dict(os.environ)
    if env.get("PATH"):
        env["PATH"] = clean_path(env["PATH"])
    # первым — current/bin ссылкой, а не bin версии из кэша (metis-0772): окно живёт дольше версии и наследует этот PATH
    # (и демон claude тоже), а bin версии остался бы старым после обновления — heavy без очереди мест, старый pantheon
    own_bin = os.path.join(CURRENT, "bin") if os.path.isdir(os.path.join(CURRENT, "bin")) else \
        os.path.join(installed_plugin_dir(), "bin")
    extra = [own_bin, os.path.dirname(sys.executable), "/opt/homebrew/bin", os.path.join(HOME, ".local", "bin")]
    nvm = nvm_bin()
    if nvm and nvm not in (env.get("PATH") or "").split(":"):
        extra.insert(1, nvm)
    env["PATH"] = ":".join(extra + [env.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"])
    env["PANTHEON_PYTHON"] = sys.executable  # bin/pantheon дочерних задач берёт тот же интерпретатор (lib/find-python.sh)
    return env


# Роль окна и её агент — переменные ОКНА, а не машины (metis-0321, находка СБ 20.10): `claude --bg`, `claude agents`,
# respawn и прочие вызовы claude поднимают общий `claude daemon`, он наследует окружение первого позвавшего, а фоновые
# окна идут из его запасных процессов. Запущенный из окна Пританея демон раздал бы PANTHEON_ROLE=hq всем фоновым окнам.
ROLE_ENV = ("PANTHEON_ROLE", "PANTHEON_SESSION", "CLAUDE_CODE_AGENT", "PANTHEON_ORIGIN")


def claude_env():
    """Окружение для любого запуска claude из pantheon: run_env без ROLE_ENV. Роль окну задаёт его --settings (env)."""
    env = run_env()
    for k in ROLE_ENV:
        env.pop(k, None)
    return env


def alert(text, who="pantheon"):
    """Строка в ~/ai/pantheon/alerts.md: время · кто · что. Файл только дописывается."""
    text, who = " ".join(str(text).split()), " ".join(str(who).split()) or "pantheon"
    if os.environ.get("PANTHEON_DRYRUN") == "1" and not os.environ.get("PANTHEON_ALERTS_IN_DRYRUN"):
        print(f"[alert] {who} · {text}")
        return
    p = os.path.join(PANTHEON, "alerts.md")
    with lock("alerts"):
        new = not os.path.exists(p)
        with open(p, "a", encoding="utf-8") as fh:
            if new:
                fh.write("# Тревоги\n\nТолько дописывание: `pantheon alert`. Строка — время · кто · что. "
                         "В «ждёт вас» на доске переносит Пританей; старше 30 дней уносит `pantheon archive`.\n\n")
            if "ждёт вас" in text and _alert_dup(p, who, text):  # metis-0230: та же «ждёт вас» за сутки — одна
                return
            fh.write(f"{stamp()} · {who} · {text}\n")


ALERT_WINDOW = 86400  # metis-0230: окно слияния одинаковых строк и тревог о файле


def _alert_dup(p, who, text):
    """Такая же строка «кто · что» уже есть в alerts.md моложе ALERT_WINDOW (читается хвост файла)."""
    tail = f" · {who} · {text}"
    since = stamp(now() - ALERT_WINDOW)
    with contextlib.suppress(OSError):
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            for ln in fh.read().decode("utf-8", "replace").splitlines():
                if ln[:16] >= since and ln[16:] == tail and re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d$", ln[:16]):
                    return True
    return False


def alert_daily(key, text, who="pantheon", window=ALERT_WINDOW):
    """Тревога о файле или состоянии не чаще раза в window секунд на ключ, как бы ни менялся текст (metis-0230)."""
    mark = once_path("daily-" + key)
    t = now()
    try:
        last = float(open(mark).read())
        if last <= t < last + window:  # замер из будущего (часы назад) окно не продлевает
            return
    except (OSError, ValueError):
        pass
    alert(text, who)
    os.makedirs(path("once"), exist_ok=True)
    open(mark, "w").write(str(t))


def alert_once(key, value, text, who="pantheon", note=None, group=None, policy=None, critical=False):
    """Тревога (и уведомление note — сбой класса «скоро», через политику уведомлений) один раз на значение value:
    повтор того же состояния молчит. group — вид уведомления: новое того же вида заменяет прежнее в Центре
    уведомлений и считается тем же сбоем для повтора (по умолчанию — ключ тревоги). policy — политика, уже взятая
    под lock("notify") (проход доски), иначе берётся своя. critical — класс COMM-08 (подделка журнала ваших слов и
    т. п.): уведомление сразу, и ночью, и когда вы у Mac — в счёт бюджета и в журнал."""
    mark = once_path(key)
    try:
        if open(mark).read() == str(value):
            return
    except OSError:
        pass
    alert(text, who)
    if note and critical:
        notify_critical(note, group=group or key, policy=policy)
    elif note:
        notify_soon(key, note, group=group or key, policy=policy)
    os.makedirs(path("once"), exist_ok=True)
    open(mark, "w").write(str(value))


def once_path(key):
    safe = re.sub(r"[^\w.-]", "_", key)[:60]
    return path("once", f"{safe}-{hashlib.sha1(key.encode()).hexdigest()[:8]}")


def clear_once(key):
    with contextlib.suppress(FileNotFoundError):
        os.remove(once_path(key))


JOB_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
# Подкоманды pantheon, которые может запускать тик. Пульт (install, uninstall, jobs, run-job, tick, archive) — нет.
TICK_SUBCOMMANDS = {"view", "commit", "domains", "watch", "revisits", "scout", "board", "sync-answers", "check",
                    "instructions", "agents", "usage", "qmd", "plugins", "reboot-reminder", "read", "autoclose",
                    "archive", "batch-suggest", "reap"}
CLAUDE_VALUE_FLAGS = {"--agent", "--model", "--max-turns", "--name"}
# Окна задач расписания (P0-3, metis-0063): `claude -p --agent <роль>` из schedule.toml идёт с песочницей
# settings/job-<роль>.json (собирает sandbox_build), а не без неё. Роль вне таблицы тик не запускает. write — куда
# пишет Bash роли (сверх памяти ролей и своей папки кэша); model — модель задачи вместо любой из команды: у iris в
# шапке haiku, а задаче разведчика нужен sonnet. agents — субагенты, которых роль задачи зовёт по своему шаблону
# (хук agents.py, как у штаба и координаторов, P0-6): шаблоны clio, prometheus и iris субагентов не зовут — пусто.
JOB_ROLES = {
    "clio": {"write": [os.path.join(AI_HOME, "knowledge")], "agents": []},
    "prometheus": {"write": [os.path.join(AI_HOME, "knowledge")], "agents": []},
    "iris": {"write": [os.path.join(PANTHEON, "scout")], "model": "sonnet", "agents": []},
}
JOB_EXCLUDED = ["pantheon alert *"]
# Пустой список agents.py считает сбоем и закрывает всё, и навыки без context: fork тоже (у clio — claude-md-improver).
# Поэтому пустое окно задачи получает имя-заглушку: такого субагента нет, Agent любого типа и навык-fork — отказ, а
# обычный навык идёт. Оно же — в тексте отказа («Этому окну можно: никого»)
JOB_NO_AGENTS = "никого"
# Встроенные типы Claude Code — в deny окна задачи вместе с ролями из ~/.claude/agents и лидами реестра
BUILTIN_AGENTS = ["general-purpose", "claude", "Explore", "Plan", "statusline-setup", "claude-code-guide"]
# Окно Гестии (metis-0245): мимо песочницы — только выпуск плагинов (`pantheon plugins update`: сверка с записью
# выпуска, установка, сверка хеша, проверенное дерево — голый `claude plugin update` оставил бы непроверенное и
# закрыл окна ролей), сборка окон и ролей, технический перезапуск окон и тревога. Остальные подкоманды pantheon — в песочнице, а какие ей
# вообще можно, решает guard (правило hestia). Файловых правок, веба и субагентов у окна нет.
# `pantheon reap` (metis-0568) — тоже мимо песочницы: в ней ps, lsof и kill чужих процессов не работают; что гасить,
# решает сама команда (только брошенное в папках Пантеона, остальное — по «да» владельца через consent)
# Наружу (metis-0562, «Да, по consent» владельца 27.10 22:38): сеть у песочницы пустая; мимо неё — только `git push`
# и запись в PR (`gh pr create|edit`; в песочнице macOS они не работают, как у окон направлений) и `pantheon consent`
# (читает журнал владельца). Условие — в guard: push и запись в PR без свежей метки именно этой задачи (PANTHEON_TASK
# окна; метку ставит `pantheon consent` только на явное «да») — отказ
HESTIA_EXCLUDED = ["pantheon plugins update", "pantheon plugins update *", "pantheon domains build",
                   "pantheon restart *", "pantheon alert *", "pantheon consent *", "pantheon reap", "pantheon reap *",
                   "git push", "git push *", "gh pr create *", "gh pr edit *"]
HESTIA_DENY_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Agent"]


def job_window(role):
    return path("settings", f"job-{role}.json")


def job_window_problem(argv):
    """Окно песочницы задачи `claude -p` (P0-3): None — обычный файл на месте или задача не claude; иначе причина."""
    if not argv or argv[0] != "claude":
        return None
    if "--settings" not in argv[:-1]:
        return "нет окна песочницы (--settings)"
    p = argv[argv.index("--settings") + 1]
    try:
        st = os.lstat(p)
    except OSError:
        return f"нет окна песочницы {p.replace(HOME, '~')}"
    if not stat.S_ISREG(st.st_mode):
        return f"окно песочницы {p.replace(HOME, '~')} — не обычный файл"
    return None


def parse_command(cmd):
    """Команда задачи из schedule.toml → argv без оболочки, или None (задача не идёт). Разрешено только:
      pantheon <view|commit|domains|watch|revisits|scout|board|sync-answers|…> [аргументы без спецсимволов];
      claude -p --agent <роль> [--model M] [--max-turns N] [--name N] "<поручение>" — без флагов прав и настроек,
        роль — из JOB_ROLES; argv получает --settings <окно задачи роли> (и --model из таблицы, если он там есть);
      скрипт из bin/ или scripts/ самого плагина."""
    if not isinstance(cmd, str) or re.search(r"[;&|`$<>\n\\]", cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if not argv:
        return None
    if argv[0] == "pantheon":
        if len(argv) < 2 or argv[1] not in TICK_SUBCOMMANDS:
            return None
        if argv[1] == "qmd" and argv[2:3] not in (["update"], ["embed"], ["serve"]):
            return None  # install (claude mcp add уровня пользователя) и прочее — только руками
        if argv[1] == "plugins" and (argv[2:3] != ["update"] or any(a != "--quiet" for a in argv[3:])):
            return None
        if argv[1] == "batch-suggest" and argv[2:] != ["run"]:
            return None  # задача прохода — только `batch-suggest run`; --force и task batch-suggest --apply — руками
        if argv[1] == "read" and argv[2:] != ["run"]:
            return None  # заявку подаёт окно, а не задача прохода; проход — только `read run`
        if argv[1] == "reap" and argv[2:] != ["--auto"]:
            return None  # проход гасит только брошенное (`reap --auto`, metis-0617); --apply и --pid — руками и Гестия
        return [os.path.join(PLUGIN, "bin", "pantheon")] + argv[1:]
    if argv[0] == "claude":
        if argv[1:2] != ["-p"]:
            return None
        seen, j = {}, 2
        while j < len(argv) - 1:
            flag = argv[j]
            if flag not in CLAUDE_VALUE_FLAGS or flag in seen or argv[j + 1].startswith("-"):
                return None
            seen[flag] = argv[j + 1]
            j += 2
        if j != len(argv) - 1 or argv[-1].startswith("-") or not JOB_NAME.fullmatch(seen.get("--agent", "")):
            return None
        conf = JOB_ROLES.get(seen["--agent"])
        if conf is None:
            return None  # роль без окна задачи — без песочницы не идёт (P0-3)
        if conf.get("model"):
            seen["--model"] = conf["model"]
        out = ["claude", "-p", "--settings", job_window(seen["--agent"])]
        for flag, value in seen.items():
            out += [flag, value]
        return out + [argv[-1]]
    real = os.path.realpath(os.path.expanduser(argv[0]))
    if any(real.startswith(os.path.join(PLUGIN, d) + os.sep) for d in ("bin", "scripts")):
        return [real] + argv[1:]
    return None


APP = os.path.join(HOME, "Applications", "Доска.app")


def board_url(name="Доска.base"):
    return tasks_mod().view_file_url(VIEW, "Доска/" + name)


def _notifier():
    for c in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier"):
        if os.path.exists(c):
            return c
    return None


def notify_offscreen():
    """Уведомление не для экрана: признак теста PANTHEON_TEST или папка состояния — не настоящая (временный
    PANTHEON_STATE или временный HOME). Настоящая — ~/.local/state/pantheon домашней папки владельца из учётной
    записи, а не из HOME: тесты подменяют HOME. Так тест, забывший PANTHEON_NOTIFY_LOG, не покажет владельцу
    ложную тревогу (metis-0307: «push не проходит» и «давно не синхронизируется» из test_commit_push)."""
    if os.environ.get("PANTHEON_TEST"):
        return True
    import pwd
    try:
        owner_home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        return True
    real = os.path.realpath(os.path.join(owner_home, ".local", "state", "pantheon"))
    cur = os.path.realpath(os.environ.get("PANTHEON_STATE") or
                           os.path.join(os.path.expanduser("~"), ".local", "state", "pantheon"))
    return STATE != real or cur != real


def notify(text, title="Пантеон", target=None, group=None):
    """Уведомление macOS. Через terminal-notifier 3 (UserNotifications): щелчок открывает target — карточку или доску,
    group заменяет прежнее уведомление о том же. Без него — обычное уведомление без перехода."""
    if os.environ.get("PANTHEON_NOTIFY_LOG"):  # для тестов: что и куда ушло бы
        with open(os.environ["PANTHEON_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
            fh.write(f"{title}|{text}|{target or ''}|{group or ''}\n")
        return
    if os.environ.get("PANTHEON_NO_NOTIFY") or os.environ.get("PANTHEON_DRYRUN") == "1":
        return
    text = " ".join(str(text).split())
    if notify_offscreen():  # тест или проба: на экран владельца — никогда, только в файл (metis-0307)
        with contextlib.suppress(OSError):
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, "notify-test.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{title}|{text}|{target or ''}|{group or ''}\n")
        return
    tn = _notifier()
    if tn:
        args = [tn, "-title", title, "-message", text, "-open", target or board_url()]
        if group:
            args += ["-group", "pantheon-" + re.sub(r"[^\w.-]", "_", group)[:60]]
        try:
            r = subprocess.run(args, capture_output=True, timeout=15)
            if r.returncode == 0:
                return
        except subprocess.TimeoutExpired:  # зависший notifier не обрывает проход (metis-0709): пробуем osascript
            pass
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                       capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:  # и он завис — уведомление потеряно, проход идёт дальше
        pass


# --- состояние Mac: пробуждение, питание, простой, лимит ------------------------

def wake_time():
    if os.environ.get("PANTHEON_FAKE_WAKE"):
        return float(os.environ["PANTHEON_FAKE_WAKE"])
    best = 0.0
    for key in ("kern.waketime", "kern.boottime"):
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout
        m = re.search(r"sec = (\d+)", out)
        if m:
            best = max(best, float(m.group(1)))
    return best


def on_ac():
    if os.environ.get("PANTHEON_FAKE_AC") is not None:
        return os.environ["PANTHEON_FAKE_AC"] == "1"
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    return "AC Power" in out or "Battery Power" not in out


def idle_sec():
    if os.environ.get("PANTHEON_FAKE_IDLE"):
        return float(os.environ["PANTHEON_FAKE_IDLE"])
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


def limit_pct():
    """Пятичасовой лимит по снимку строки статуса; None — снимка нет."""
    if os.environ.get("PANTHEON_FAKE_LIMIT"):
        return float(os.environ["PANTHEON_FAKE_LIMIT"])
    try:
        pct, resets_at, _ = open(LIMIT_SNAPSHOT).read().split()[:3]
    except (OSError, ValueError):
        return None
    return 0.0 if now() > float(resets_at) else float(pct)


# --- тик ------------------------------------------------------------------------

def every_sec(job):
    every = job.get("every", "tick")
    return 0 if every == "tick" else float(every) * 60


def due(job, st, t):
    """(пора ли, с какого момента пора). У задачи, которая ещё не шла, опоздание считается с первого
    тика, на котором она ждала, — иначе max_delay для неё никогда бы не наступал."""
    if st.get("last_start") is None:
        return True, st.get("waiting_since", t)
    period = every_sec(job)
    due_at = st["last_start"] + period
    return t >= due_at - 5, due_at


def lease_expired(job, st, t):
    return bool(job.get("lease_days")) and st.get("lease_until") is not None and t > st["lease_until"]


def heavy_wait_reason(job, sched, t, overdue):
    """Почему тяжёлая задача ждёт. max_delay (overdue) снимает все условия, кроме лимита у задач на Claude: сессия
    `claude -p` при упоре в лимит обрывается на середине (TOOL-04), поэтому её тик переносит, а не запускает."""
    d = sched["defaults"]
    if overdue:
        pct = limit_pct() if job.get("claude") else None
        if pct is not None and pct >= d["limit_max_pct"]:
            return f"пятичасовой лимит {pct:.0f} % ≥ {d['limit_max_pct']} % (задача на Claude ждёт и после max_delay)"
        return None
    if t - wake_time() < d["wake_quiet_min"] * 60:
        return f"первые {d['wake_quiet_min']} мин после пробуждения — только лёгкие"
    if not on_ac():
        return "ждёт питания от сети"
    if job.get("claude"):
        idle = idle_sec()
        if idle < d["idle_min"] * 60:
            return f"ждёт простоя {d['idle_min']} мин (сейчас {int(idle // 60)} мин)"
        pct = limit_pct()
        if pct is not None and pct >= d["limit_max_pct"]:
            return f"пятичасовой лимит {pct:.0f} % ≥ {d['limit_max_pct']} %"
    return None


# --- пропуск прогонов тика без изменений (metis-0149) ---------------------------------------------------
# Четыре задачи тика идут каждую минуту, а почти всегда ничего не находят: каждая — запуск Python и обход папок. Тик
# пропускает такую задачу, если её входы не менялись с прошлого удачного прогона. Только по отпечатку stat
# (путь, размер, время изменения), содержимое не читается. Пропуск — только из тика: ручной `pantheon <команда>` и
# `pantheon run-job` идут всегда. Раз в TICK_SKIP_MAX секунд задача идёт в любом случае — ловит то, чего отпечаток не
# видит (время, внешние процессы). Задача вне таблицы или с другими аргументами идёт как раньше.
#
# Вход каждой команды (что она читает; свои же выходы в отпечаток не входят, иначе он менялся бы после каждого прогона):
#   команда (аргументы)       вход                                                           не входит
#   view --quiet              дерево PANTHEON без .git (размер, время) + «лишние» файлы      сама копия VIEW: rsync
#                             копии VIEW вне оригинала, вне .obsidian и Доска/ (их разбирает  меняет её после прогона
#                             view-sync.sh)
#   board                     карточки VIEW/Доска/*.md; задачи (task_dirs: inbox/tasks,       board.json, журнал
#                             directions/*/tasks); входящие directions/*/inbox; directions.toml, владельца и политика
#                             schedule.toml (primary, уведомления); хозяева задач:            уведомлений — выходы;
#                             STATE/agents.json и STATE/stopped/ (metis-0868)                  owner-sids.json
#   sync-answers              HOME/.claude/.sync-held и .sync-incoming, owner-log/board.jsonl и zeus.md  —
#   agents                    HOME/.claude/daemon/roster.json, sessions/*.json (имя, pid),     ответ `claude agents`
#                             jobs/*/* — признаки, по которым демон Claude меняет список       (снимок нужен лишь как
#                                                                                              запасной вариант)
TICK_SKIP_MAX = 900


def _stat_rec(rel, p):
    try:
        s = os.lstat(p)
    except OSError:
        return (rel, None, None)
    return (rel, s.st_size, s.st_mtime_ns)


def _fp_tree(root, skip_dirs=(".git",)):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in skip_dirs)
        for f in sorted(files):
            p = os.path.join(d, f)
            out.append(_stat_rec(os.path.relpath(p, root), p))
    return out


def _fp_files(paths):
    return [_stat_rec(p, p) for p in paths]


def _fp_dir(d, depth=2):
    """Список d и (при depth 2) файлов на уровень глубже; без обхода всего дерева."""
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return [(d, None, None)]
    for n in names:
        p = os.path.join(d, n)
        out.append(_stat_rec(p, p))
        if depth > 1 and os.path.isdir(p) and not os.path.islink(p):
            out += _fp_dir(p, depth - 1)
    return out


def _fp_view_extras():
    """Файлы копии VIEW, которых нет в оригинале (кроме .obsidian, Доска/ и служебных с точкой): view-sync.sh их
    переносит или удаляет. После обычного прогона их нет, поэтому отпечаток от прогона не зависит."""
    out = []
    if not os.path.isdir(VIEW):
        return [("view-missing", None, None)]
    for d, dirs, files in os.walk(VIEW):
        rel_d = os.path.relpath(d, VIEW)
        dirs[:] = [x for x in dirs if not (rel_d == "." and x in (".obsidian", "Доска"))]
        for f in files:
            rel = os.path.normpath(os.path.join(rel_d, f))
            if not f.startswith(".") and not os.path.exists(os.path.join(PANTHEON, rel)):
                out.append(_stat_rec(rel, os.path.join(VIEW, rel)))
    return out


def _fp_board_inputs():
    T = tasks_mod()
    out = _fp_files(sorted(T.task_files(PANTHEON)))
    out += _fp_files(sorted(glob.glob(os.path.join(PANTHEON, "directions", "*", "inbox", "*.md"))))
    out += _fp_files(sorted(glob.glob(os.path.join(BOARD, "*.md"))))
    out += _fp_files([os.path.join(PANTHEON, "directions.toml"), os.path.join(PANTHEON, "schedule.toml")])
    out += _fp_files([os.path.join(PANTHEON, "board.md")])  # строка встраивания ![[board-auto]] (metis-0397)
    out += _fp_files([path("agents.json")]) + _fp_dir(path("stopped"), 1)  # хозяева задач (metis-0868)
    out += _fp_board_auto()
    try:  # следы работы для статусов (metis-0397, п. 7): записи worktree и живые копии, PR, закрывающие задачи
        S = boardstatus_mod()
        roots = sorted({r for rs in S.roots(board_domains()).values() for r in rs})
        out += [_stat_rec(p, p) for root in roots for p in S.wt_heads(root)]
        out += [("worktrees", root, S.live_worktrees(root)) for root in roots]
        ops = read_json(path("autoclose-prs.json"), {}).get("open_prs")
        out.append(("open_closing", sorted((r, str(p.get("number")), repr(p.get("closes")), bool(p.get("part")))
                                           for r, ps in (ops if isinstance(ops, dict) else {}).items()
                                           if isinstance(ps, list) for p in ps if isinstance(p, dict))))
    except Exception as e:  # noqa: BLE001 — сломанный вход: отпечаток другой, проход не пропускается
        out.append(("board-status-inputs", repr(e), now()))
    return out


def _fp_board_auto():
    """Входы автоблока board-auto.md (metis-0397): ревью, STATUS.md, decisions.md, журнал владельца — размер и время
    правки; открытые PR и неделя — по содержимому кэша и целым процентам (fetch и строка статуса пишут их часто)."""
    B = boardtext_mod()
    return _fp_files(B.watch_files(PANTHEON, STATE)) + [("open_prs", B.open_prs(path("autoclose-prs.json"))),
                                                        ("pr_stale", B.pr_stale(path("autoclose-prs.json"))),
                                                        ("week", board_week())]


TICK_SKIP = {
    ("view", "--quiet"): lambda: _fp_tree(PANTHEON) + _fp_view_extras(),
    ("board",): _fp_board_inputs,
    ("sync-answers",): lambda: _fp_files([os.path.join(SYNC_DIR, ".sync-held"), os.path.join(SYNC_DIR, ".sync-incoming"),
                                          os.path.join(STATE, "owner-log", "board.jsonl"),
                                          os.path.join(STATE, "owner-log", "zeus.md")]),
    ("agents",): lambda: (_fp_files([os.path.join(HOME, ".claude", "daemon", "roster.json")])
                          + _fp_files(sorted(glob.glob(os.path.join(HOME, ".claude", "sessions", "*.json"))))
                          + _fp_dir(os.path.join(HOME, ".claude", "jobs"))),
}


def tick_fingerprint(job):
    """Отпечаток входов задачи из TICK_SKIP или None (задачи нет в таблице — пропуску не подлежит)."""
    argv = parse_command(job.get("command"))
    if not argv or os.path.basename(argv[0]) != "pantheon":
        return None
    fn = TICK_SKIP.get(tuple(argv[1:]))
    if fn is None:
        return None
    try:
        return hashlib.sha1(repr(fn()).encode("utf-8", "replace")).hexdigest()
    except Exception:  # любой сбой разбора — не пропускать, а запустить
        return None


def tick_skippable(job, st, t):
    fp, at = st.get("skip_fp"), st.get("skip_at")
    if not fp or at is None or not 0 <= t - float(at) < TICK_SKIP_MAX or st.get("last_rc") != 0:
        return False
    return tick_fingerprint(job) == fp


def launch(name, t):
    """Запуск задачи отдельным процессом (или запись в журнал решений при PANTHEON_DRYRUN)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        st = job_state(name)
        st.update(last_start=t, last_end=t, last_rc=0, waiting=None)
        save_job_state(name, st)
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(t)} {name}\n")
        return
    # загрузчик run.py (модуль, .pyc из lib/__pycache__), тот же интерпретатор, что у тика
    subprocess.Popen([sys.executable, "-I", os.path.join(LIB, "run.py"), "run-job", name],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env=run_env(), cwd=HOME)


REFRESH_ARGV = (("view", "--quiet"), ("board",))  # задачи расписания, которые рисуют карточки: копия Obsidian и доска


def refresh_kick():
    """После правки карточки (pantheon task …, автозакрытие) — копия Obsidian и доска сразу, без отдельной команды и без
    ожидания тика (metis-0868, п. 4): те же задачи расписания (`pantheon view --quiet`, `pantheon board`) отдельным
    процессом через launch, под их замками job-<имя>. Уже идёт или пауза — не трогаем: следующий тик увидит новый
    отпечаток входов. Окно роли (песочница не даёт писать в STATE) — тихо пропускаем: догонит тик через минуту.
    Тест или проба на временной папке (notify_offscreen) — только с PANTHEON_REFRESH=1; PANTHEON_REFRESH=0 — выключено.
    → имена запущенных задач."""
    flag = os.environ.get("PANTHEON_REFRESH")
    if flag == "0" or (flag != "1" and notify_offscreen()) or os.path.exists(path("paused")):
        return []
    try:
        sched = load_schedule()
        with lock("refresh-kick", block=False) as got:  # проба записи в STATE: из окна роли — PermissionError
            if not got:
                return []
    except (OSError, ValueError):
        return []
    me, primary, out = host(), sched.get("primary_host"), []
    for job in sched.get("job") or []:
        argv = parse_command(job.get("command"))
        if not argv or os.path.basename(argv[0]) != "pantheon" or tuple(argv[1:]) not in REFRESH_ARGV:
            continue
        st = job_state(job["name"])
        if job.get("enabled") is False or st.get("disabled") or st.get("paused"):
            continue
        if job.get("hosts", "all") == "primary" and (not primary or me != primary):
            continue
        if lock_held("job-" + job["name"]):
            continue
        launch(job["name"], now())
        out.append(job["name"])
    return out


def card_now():
    """Время записи в карточку (metis-0868, п. 5) — часы системы. PANTHEON_NOW («сейчас» синтетических проб) берётся,
    только если хранилище задач не настоящее (временный PANTHEON_HOME): агент не проставит в журнал настоящей
    карточки своё время переменной окружения. Настоящее — ~/ai/pantheon домашней папки из учётной записи, а не из
    HOME (тесты подменяют HOME); PANTHEON_TEST здесь не в счёт — его может поставить и агент."""
    if os.environ.get("PANTHEON_NOW") and real_store():
        return time.time()
    return now()


def real_store():
    """PANTHEON — настоящее хранилище задач владельца (~/ai/pantheon его учётной записи)."""
    import pwd
    try:
        owner_home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        return True
    return PANTHEON == os.path.realpath(os.path.join(owner_home, "ai", "pantheon"))


def job_cap_hold(name, argv, st, t, memo=None):
    """metis-0444: задача `claude -p` при достигнутом недельном потолке владельца не запускается, а ждёт — причина в
    st["waiting"] (её показывает `pantheon jobs`), срок не сдвигается, сбоем не считается. memo — словарь на один
    проход тика: потолок считается один раз. → True, если задача ждёт."""
    if not argv or argv[0] != "claude":
        return False
    memo = {} if memo is None else memo
    if "why" not in memo:
        memo["why"] = night_mod().launch_cap("tick", t=t)
    if not memo["why"]:
        return False
    st["waiting"] = memo["why"]
    st.setdefault("waiting_since", t)
    save_job_state(name, st)
    return True


def tick():
    os.makedirs(STATE, exist_ok=True)
    with lock("tick", block=False) as got:
        if not got:
            return
        t = now()
        with open(path("last-tick"), "w") as fh:
            fh.write(f"{int(t)}\n")
        if os.path.exists(path("paused")):
            return
        try:
            sched = load_schedule()
        except (OSError, ValueError) as e:
            mark = path("schedule-error")
            if not os.path.exists(mark):
                open(mark, "w").write(str(e))
                alert(f"schedule.toml не читается: {e}", "pantheon-tick")
            return
        with contextlib.suppress(FileNotFoundError):
            os.remove(path("schedule-error"))
        me, primary = host(), sched.get("primary_host")
        for bad in sched.get("bad_names") or []:
            alert_once("badname-" + re.sub(r"[^\w-]", "_", bad)[:40], bad, f"schedule.toml: задача или служба с именем не по образцу "
                       f"или повтором имени ({bad[:60]!r}; только a-z, 0-9, дефис, имена не повторяются) — пропущена", "pantheon-tick")
        heavy, skipped, cap_memo = [], [], {}
        for job in sched.get("job") or []:
            name = job["name"]
            st = job_state(name)
            if job.get("enabled") is False or st.get("disabled"):
                continue
            if job.get("hosts", "all") == "primary":
                if not primary:
                    alert_once("no-primary", "1", "в schedule.toml нет primary_host: задачи с общим результатом "
                               "(hosts = \"primary\") не идут ни на одном Mac", "pantheon-tick")
                    continue
                if me != primary:
                    continue
            if parse_command(job.get("command")) is None:
                alert_once("badcmd-" + name, job.get("command"), f"задача {name}: команда не разрешённого вида "
                           "(только pantheon …, claude -p …, скрипт плагина; без ; & | $ > <) — пропущена",
                           "pantheon-tick", note=f"Задача {name} пропущена: команда не разрешена")
                continue
            if st.get("paused"):
                continue
            if job.get("lease_days") and st.get("lease_until") is None:
                st["lease_until"] = t + float(job["lease_days"]) * 86400
                save_job_state(name, st)
            if lease_expired(job, st, t):
                st.update(paused=True, paused_reason="аренда истекла")
                save_job_state(name, st)
                alert(f"задача {name}: аренда истекла, поставлена на паузу — продлить: pantheon jobs renew {name}",
                      "pantheon-tick")
                notify_soon("lease-" + name, f"Задача {name} на паузе: аренда истекла")
                continue
            is_due, due_at = due(job, st, t)
            if not is_due or locked("job-" + name):
                continue
            if tick_skippable(job, st, t):  # входы не менялись с прошлого удачного прогона (metis-0149)
                skipped.append(name)
                continue
            if job_cap_hold(name, parse_command(job.get("command")), st, t, cap_memo):
                continue
            if job.get("class", "light") == "heavy":
                heavy.append((job, st, due_at))
            else:
                launch(name, t)
        if heavy:
            tick_heavy(sched, heavy, t)
        write_json(path("tick-skipped.json"), {"time": t, "skipped": skipped})
        try:
            services_sync(sched)
        except Exception as e:  # сбой служб не должен останавливать задачи тика
            alert_once("svc-sync", type(e).__name__, f"службы: сверка с launchd упала ({type(e).__name__}: {e})",
                       "pantheon-tick")
        try:
            hookd_stats_tick(t)  # доля откатов и canary-diff демона хуков раз в сутки (F9, metis-0845)
        except Exception as e:  # сбой сводки не должен останавливать тик
            alert_once("hookd-stats-tick", type(e).__name__, f"демон хуков: сводка упала ({type(e).__name__}: {e})",
                       "pantheon-tick")
        merge_kick()
        outside_kick()
        handoff_kick()
        try:
            browser_mod().kick()  # браузер владельца для ролей вне окна (lib/browser.py, metis-0760)
        except Exception as e:  # сбой браузера не должен останавливать тик
            alert_once("browser-kick", type(e).__name__, f"браузер ролей: {type(e).__name__}: {e}", "pantheon-tick")
        probes_tick(t)
        try:
            roles_tick()  # личные роли по вашей галочке на доске (metis-0262 PR 4)
        except Exception as e:  # сбой ролей не должен останавливать тик
            alert_once("roles-tick", type(e).__name__, f"личные роли: проход упал ({type(e).__name__}: {e})",
                       "pantheon-tick")
        if not primary or me == primary:  # общий результат (задачи, gh) — на одном Mac
            try:
                board_auto_watch(t, sched)
            except Exception as e:  # сбой проверки не должен останавливать тик
                alert_once("board-auto-watch", type(e).__name__, f"board-auto.md: проверка свежести упала "
                           f"({type(e).__name__}: {e})", "pantheon-tick")
            try:
                autoclose_tick(t)
            except Exception as e:  # сбой автозакрытия не должен останавливать тик
                alert_once("autoclose-tick", type(e).__name__, f"автозакрытие задач: проход упал ({type(e).__name__}: {e})",
                           "pantheon-tick")
            try:
                release_tick_mod().tick(t)  # выпуск без Actions: release.py --push из копии main (metis-0880)
            except Exception as e:  # сбой выпуска не должен останавливать тик
                alert_once("release-tick-crash", type(e).__name__, f"выпуск без Actions: проход упал "
                           f"({type(e).__name__}: {e})", "pantheon-tick")


def tick_heavy(sched, heavy, t):
    gap = sched["defaults"]["heavy_gap_min"] * 60
    hs = read_json(path("heavy.json"))
    # heavy-cmd-1/2 — два места общей блокировки тяжёлых команд направлений (обёртка `heavy`, MEM-03, шаг 1.2)
    busy = (locked("heavy-run") or locked("heavy-cmd-1") or locked("heavy-cmd-2")
            or (hs.get("last_end") is not None and t - hs["last_end"] < gap))
    heavy.sort(key=lambda x: (-int(x[0].get("priority", 0)), x[2]))
    started = False
    for job, st, due_at in heavy:
        overdue = job.get("max_delay") is not None and t - due_at >= float(job["max_delay"]) * 60
        reason = ("идёт другая тяжёлая задача, сборка или тесты направления, или пауза между ними"
                  if (busy or started) else heavy_wait_reason(job, sched, t, overdue))
        if reason:
            st["waiting"] = reason
            st.setdefault("waiting_since", t)
            save_job_state(job["name"], st)
            continue
        st.pop("waiting", None)
        st.pop("waiting_since", None)
        save_job_state(job["name"], st)
        launch(job["name"], t)
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            write_json(path("heavy.json"), {"last_end": t})
        started = True


# --- службы (SCHED-05) ------------------------------------------------------------------
# [[service]] в schedule.toml — постоянный процесс (сервер qmd, позже бот одобрения, Pixel Agents, «Пульт»). Каждая —
# своя задача launchd pantheon.svc.<имя> с KeepAlive; запускает её `pantheon service-run <имя>`, который
# перечитывает schedule.toml и проверяет команду (только `pantheon …` или скрипт плагина). Тик сверяет launchd с
# расписанием: нужна и не запущена — поднять, пауза, выключена, убрана из расписания или чужой Mac — снять.
# Служба по требованию (ключ `socket = <порт>`, metis-0151) — без KeepAlive: порт 127.0.0.1:<порт> слушает launchd
# (ключ Sockets), первое соединение запускает службу, после простоя (`idle_min`, по умолчанию 30 мин) она выходит
# сама. «Загружена, процесса нет» для неё — обычное ожидание запроса, а не сбой: тик её не толкает и не тревожит.

SVC_PREFIX = "pantheon.svc."
# Прежние метки (com.<кто-то>.pantheon-tick и com.<кто-то>.pantheon-svc.<имя>) узнаём по маске файлов, без имён в коде:
# тик и `pantheon install` снимают их и удаляют plist, пока не поднялись новые (иначе две копии службы дерутся за порт)
OLD_TICK_GLOB = "com.*.pantheon-tick.plist"
OLD_SVC_GLOB = "com.*.pantheon-svc.*.plist"
SVC_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{bin}</string><string>service-run</string><string>{name}</string></array>
{launch}
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


SVC_KEEPALIVE = """  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>"""
SVC_SOCKET = """  <key>Sockets</key>
  <dict><key>Listeners</key><dict>
    <key>SockNodeName</key><string>127.0.0.1</string>
    <key>SockServiceName</key><string>{port}</string>
    <key>SockType</key><string>stream</string>
    <key>SockFamily</key><string>IPv4</string>
  </dict></dict>"""
SVC_IDLE_MIN = 30
# Служба демона хуков guard (metis-0845): [[service]] с name = "hookd" — без command. Её plist, pantheon-hookd и
# закрепление дерева (pantheon-hookd.hooks) ставит не SVC_TMPL, а установщик guard scripts/hookd-install.sh из
# проверенного дерева (installed_dir) — _hookd_sync. Сокет Unix держит launchd, демон выходит сам после простоя:
# «загружена, процесса нет» — ожидание запроса (как служба по требованию). command, socket и idle_min у неё не читаются
HOOKD_SVC = "hookd"
HOOKD_INSTALL_TIMEOUT = 180  # сборка клиента cc и plutil — секунды; запас на холодный кэш компилятора
HOOKD_RETRY = 3600           # не поставилась из того же дерева guard — повтор через час, а не на каждом проходе
HOOKD_STATS_EVERY = 86400    # hookd-stats (F9) — раз в сутки


def svc_socket(svc):
    """Порт службы по требованию (ключ socket) или None — обычная служба с KeepAlive. Плохое значение — ValueError."""
    v = svc.get("socket")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 1024 <= v <= 65535:
        raise ValueError(f"socket: нужен порт 1024–65535, а не {v!r}")
    return v


def svc_idle(svc):
    """Простой службы по требованию до выхода, в секундах (ключ idle_min, минуты)."""
    v = svc.get("idle_min", SVC_IDLE_MIN)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 24 * 60:
        raise ValueError(f"idle_min: нужно число минут больше 0 и не больше суток, а не {v!r}")
    return float(v) * 60


def svc_on_demand(svc):
    if svc.get("name") == HOOKD_SVC:
        return True
    with contextlib.suppress(ValueError):
        return svc_socket(svc) is not None
    return False


def parse_service_command(cmd):
    """Команда службы: как у задачи, но без `claude -p` — служба живёт постоянно, а сессия Claude — нет."""
    argv = parse_command(cmd)
    if argv is None or argv[0] == "claude":
        return None
    return argv


def service_wanted(svc, sched, st=None):
    """(нужна ли служба на этом Mac, почему нет)."""
    st = job_state(svc["name"]) if st is None else st
    if svc.get("enabled") is False or st.get("disabled"):
        return False, "выключена"
    if st.get("paused"):
        return False, "пауза"
    if svc.get("hosts", "all") == "primary" and host() != sched.get("primary_host"):
        return False, "не этот Mac"
    if svc.get("name") == HOOKD_SVC:
        return True, ""  # ставит установщик guard, команды нет (_hookd_sync)
    if parse_service_command(svc.get("command")) is None:
        return False, "команда не разрешена"
    try:
        svc_socket(svc)
        svc_idle(svc)
    except ValueError as e:
        return False, str(e)
    return True, ""


def _svc_plist(name):
    return os.path.join(HOME, "Library", "LaunchAgents", SVC_PREFIX + name + ".plist")


def svc_running(name):
    """pid службы по launchctl print, 0 — загружена, но не идёт, None — не загружена."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return read_json(path("svc-dry.json")).get(name)
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SVC_PREFIX}{name}"], capture_output=True,
                       text=True, timeout=15)
    if r.returncode != 0:
        return None
    m = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else 0


def svc_last_exit(name):
    """Последний код выхода службы по launchctl print («last exit code»); не выходила или не узнать — None."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return (read_json(path("svc-dry.json")).get("exit") or {}).get(name)
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SVC_PREFIX}{name}"], capture_output=True,
                       text=True, timeout=15)
    m = re.search(r"^\s*last exit code = (-?\d+)", r.stdout, re.M) if r.returncode == 0 else None
    return int(m.group(1)) if m else None


def _launchctl(verb, target, name):
    """launchctl bootstrap|bootout|kickstart; при PANTHEON_DRYRUN — строка в dryrun.log и мнимое состояние."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} svc-{verb} {name}\n")
        dry = read_json(path("svc-dry.json"))
        if verb == "bootout":
            dry.pop(name, None)
        else:
            dry[name] = 4242
        write_json(path("svc-dry.json"), dry)
        return True, ""
    r = subprocess.run(["launchctl", verb, *target], capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def old_plists(pattern):
    """Файлы ~/Library/LaunchAgents по маске прежних меток (OLD_TICK_GLOB, OLD_SVC_GLOB)."""
    agents = os.path.join(HOME, "Library", "LaunchAgents")
    with contextlib.suppress(OSError):
        return sorted(os.path.join(agents, f) for f in os.listdir(agents) if fnmatch.fnmatchcase(f, pattern))
    return []


def drop_old(pattern):
    """bootout и удаление plist прежних меток. → число снятых (не снятая — загружена после неудачного bootout — не
    считается, её plist остаётся). При PANTHEON_DRYRUN — строка `old-bootout` в dryrun.log."""
    n = 0
    for p in old_plists(pattern):
        label = os.path.basename(p)[:-len(".plist")]
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            with open(path("dryrun.log"), "a") as fh:
                fh.write(f"{int(now())} old-bootout {label}\n")
        else:
            target = f"gui/{os.getuid()}/{label}"
            r = subprocess.run(["launchctl", "bootout", target], capture_output=True, timeout=30)
            if r.returncode != 0 and subprocess.run(["launchctl", "print", target], capture_output=True,
                                                    timeout=15).returncode == 0:
                # bootout не снял, а задача загружена: plist оставляем — иначе службу никто не найдёт, а новая
                # встанет рядом (две копии дерутся за порт)
                print(f"pantheon: прежняя служба {label} не снимается (launchctl bootout, код {r.returncode}); "
                      f"plist оставлен, снимите её вручную", file=sys.stderr)
                continue
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
        n += 1
    return n


def _svc_path():
    """PATH служб — тот же, что у задачи тика (python3 из него запускает pantheon): от того, каким python вызван
    `pantheon jobs`, plist не меняется и служба не перезапускается зря (ревью argus 15.10)."""
    import plistlib
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        with open(next((p for p in [PLIST, *old_plists(OLD_TICK_GLOB)] if os.path.exists(p)), PLIST), "rb") as fh:
            return str(plistlib.load(fh)["EnvironmentVariables"]["PATH"])
    return ":".join([os.path.dirname(sys.executable), "/opt/homebrew/bin", os.path.join(HOME, ".local", "bin"),
                     "/usr/bin:/bin:/usr/sbin:/sbin"])


def hookd_installer(tree):
    return os.path.join(tree, "scripts", "hookd-install.sh")


def _hookd_env():
    """Окружение установщика и сводки guard: только HOME и PATH — окружение тика задаёт launchd, а его меняет
    launchctl setenv; установщик сам зовёт команды по абсолютным путям."""
    return {"HOME": HOME, "PATH": os.environ.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"}


def _read_text(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _last_line(*texts):
    """Последняя непустая строка первого текста, где она есть (причина сбоя — последней строкой)."""
    for t in texts:
        lines = [x.strip() for x in (t or "").splitlines() if x.strip()]
        if lines:
            return lines[-1][:200]
    return ""


def _hookd_sync():
    """Служба hookd нужна: поставить или переставить её установщиком guard из проверенного дерева (metis-0845).
    Ничего не делает и launchd не трогает, если всё совпало: pantheon-hookd.hooks называет папку hooks этого дерева
    (после выпуска guard там прежняя версия — демон отвечал бы «F stale» на каждый вызов), plist — ровно то, что даёт
    `hookd-install.sh --print`, служба загружена. Иначе — `hookd-install.sh --no-probe`: окна macOS о доступе к папкам
    из фона не всплывают, проход не ждёт. pantheon-hookd поставлен впервые или пересобран (метка .sum другая) — тревога
    «проверьте доступ» с командой --check. Сбой — тревога с последней строкой вывода; повтор из того же дерева — через
    HOOKD_RETRY. Нет проверенного дерева guard или в нём нет установщика — тревога, служба не трогается."""
    tree = installed_dir("guard")
    if not tree:
        alert_once("svc-hookd", "no-guard", "служба hookd: нет проверенного дерева guard — не ставлю и не переставляю "
                   "(pantheon plugins accept guard, README agent-kit «Живой код»)", "pantheon-tick")
        return
    ver, inst = os.path.basename(tree), hookd_installer(tree)
    if not os.path.isfile(inst):
        alert_once("svc-hookd", f"no-installer {tree}", f"служба hookd: в guard {ver} нет scripts/hookd-install.sh — "
                   "служба не ставится до выпуска guard с установщиком", "pantheon-tick")
        return
    hooks = os.path.join(tree, "hooks")
    svc_bin = os.path.join(HOOKD_DIR, "bin", "pantheon-hookd")
    pin = (_read_text(svc_bin + ".hooks") or "").strip()
    plist = _svc_plist(HOOKD_SVC)
    try:
        r = subprocess.run(["/bin/sh", inst, "--print"], capture_output=True, text=True, timeout=30, env=_hookd_env(),
                           stdin=subprocess.DEVNULL)
        printed = r.stdout if r.returncode == 0 and r.stdout else None
    except (OSError, subprocess.SubprocessError):
        printed = None
    if pin == hooks and printed is not None and _read_text(plist) == printed and svc_running(HOOKD_SVC) is not None:
        clear_once("svc-hookd")
        return
    st = read_json(path("svc-hookd.json"))
    st = st if isinstance(st, dict) else {}
    with contextlib.suppress(TypeError, ValueError):
        if st.get("failed_tree") == tree and 0 <= now() - float(st.get("failed_at") or 0) < HOOKD_RETRY:
            return
    before = _read_text(svc_bin + ".sum")
    try:
        r = subprocess.run(["/bin/sh", inst, "--no-probe"], capture_output=True, text=True,
                           timeout=HOOKD_INSTALL_TIMEOUT, env=_hookd_env(), stdin=subprocess.DEVNULL)
        code, why = r.returncode, _last_line(r.stderr, r.stdout)
    except subprocess.TimeoutExpired:
        code, why = "timeout", f"не уложился в {HOOKD_INSTALL_TIMEOUT} с"
    except OSError as e:
        code, why = type(e).__name__, str(e)
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} svc-hookd-install {ver} {code}\n")
        if code == 0:  # мнимое состояние launchd — как у _launchctl bootstrap
            dry = read_json(path("svc-dry.json"))
            dry[HOOKD_SVC] = 0
            write_json(path("svc-dry.json"), dry)
    if code != 0:
        st.update(failed_tree=tree, failed_at=now(), failed_code=code)
        write_json(path("svc-hookd.json"), st)
        alert_once("svc-hookd", f"{tree} {code}", f"служба hookd: установка из guard {ver} не прошла (код {code}): "
                   f"{why or 'без вывода'}; повтор через час или руками: /bin/sh {inst.replace(HOME, '~')}",
                   "pantheon-tick", note="Демон хуков не поставлен")
        return
    write_json(path("svc-hookd.json"), {"tree": tree, "at": now(), "from": pin or None})
    clear_once("svc-hookd")
    after = _read_text(svc_bin + ".sum")
    if after != before:
        # pantheon-hookd новый — macOS спросит доступ к папкам заново; пробы из фона нет, спросит команда владельца
        alert_once("svc-hookd-tcc", (after or "").strip()[:16], f"служба hookd поставлена из guard {ver}, "
                   f"pantheon-hookd {'пересобран' if before else 'поставлен впервые'}: доступ к Рабочему столу, "
                   f"Документам, Загрузкам и iCloud Drive не проверен — в терминале: /bin/sh {inst.replace(HOME, '~')} "
                   "--check", "pantheon-tick", note="Демон хуков: проверьте доступ к папкам")


def hookd_stats_tick(t):
    """Сводка демона хуков (F9) раз в сутки, пока служба стоит (есть её plist): `hookd-stats.py --json` из проверенного
    дерева guard. Код 3 — за сутки есть canary-diff (демон решил не так, как медленный путь): тревога раз в день с
    уведомлением — в тихие часы оно ждёт утреннего итога. Другой код, таймаут, нет файла, не JSON — тревога «сводка не
    прошла», тик не падает. Время запуска пишется до вызова: сбой не повторяется на каждом проходе."""
    if not os.path.exists(_svc_plist(HOOKD_SVC)):
        return
    st = read_json(path("hookd-stats.json"))
    st = st if isinstance(st, dict) else {}
    last = st.get("at")
    if isinstance(last, (int, float)) and 0 <= t - last < HOOKD_STATS_EVERY:
        return
    write_json(path("hookd-stats.json"), {**st, "at": t})
    tree = installed_dir("guard")
    launcher = os.path.join(tree, "hooks", "python.sh") if tree else ""
    script = os.path.join(tree, "scripts", "hookd-stats.py") if tree else ""
    data, out, err = None, "", ""
    if not (tree and os.path.isfile(launcher) and os.path.isfile(script)):
        code = "нет hookd-stats.py в проверенном дереве guard"
    else:
        try:
            r = subprocess.run(["/bin/sh", launcher, script, "--json"], capture_output=True, text=True, timeout=120,
                               env=_hookd_env(), stdin=subprocess.DEVNULL)
            code, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            code = "timeout"
        except OSError as e:
            code = type(e).__name__
    if code in (0, 3):
        with contextlib.suppress(ValueError, IndexError):
            data = json.loads(out.strip().splitlines()[-1])
        if not isinstance(data, dict):
            code, data = f"{code}, вывод не JSON", None
    write_json(path("hookd-stats.json"), {"at": t, "code": code, "stats": data})
    if code == 3:
        clear_once("hookd-stats-fail")
        alert_once("hookd-canary", stamp(t)[:10], f"демон хуков: canary-diff {data.get('canary_diff')} за сутки — "
                   "демон решил не так, как медленный путь guard; разбор: ~/.local/state/pantheon/logs/hookd-fallback.log "
                   "и hookd-install.sh --check (README guard, «Демон хуков»)", "pantheon-tick",
                   note="Демон хуков: решения расходятся с guard (canary-diff)")
    elif code == 0:
        clear_once("hookd-stats-fail")
    else:
        why = _last_line(err, out)
        alert_once("hookd-stats-fail", str(code), f"демон хуков: сводка hookd-stats не прошла (код {code})"
                   + (f": {why}" if why else ""), "pantheon-tick")


def services_sync(sched, only=None):
    """Сверить задачи launchd служб с расписанием. only — одна служба (пульт: пауза снимает её сразу). Тик и пульт
    сверяют под одной блокировкой — иначе двойной bootstrap и ложная тревога."""
    with lock("svc"):
        _services_sync(sched, only)


def _services_sync(sched, only):
    uid = os.getuid()
    env_path = _svc_path()  # до снятия прежних plist: PATH берётся и из прежнего тика
    # прежние службы — до запуска новых: две копии одной службы дерутся за порт; при only — только эта служба
    drop_old(f"com.*.pantheon-svc.{glob.escape(only)}.plist" if only else OLD_SVC_GLOB)
    want = {}
    for svc in sched.get("service") or []:
        ok, _ = service_wanted(svc, sched)
        if ok:
            want[svc["name"]] = svc
    agents = os.path.join(HOME, "Library", "LaunchAgents")
    have = set()
    with contextlib.suppress(OSError):
        have = {f[len(SVC_PREFIX):-6] for f in os.listdir(agents) if f.startswith(SVC_PREFIX) and f.endswith(".plist")}
    for name in sorted(have | set(want)):
        if only and name != only:
            continue
        plist = _svc_plist(name)
        if name not in want:
            if svc_running(name) is not None:
                _launchctl("bootout", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            with contextlib.suppress(FileNotFoundError):
                os.remove(plist)
            continue
        if name == HOOKD_SVC:
            _hookd_sync()
            continue
        port = svc_socket(want[name])
        launch = SVC_KEEPALIVE if port is None else SVC_SOCKET.format(port=port)
        text = SVC_TMPL.format(label=SVC_PREFIX + name, bin=os.path.join(CURRENT, "bin", "pantheon"), name=name,
                               path=env_path, log=path("logs", f"svc-{name}.log"), launch=launch)
        try:
            same = open(plist).read() == text
        except OSError:
            same = False
        state = svc_running(name)
        if not same:
            os.makedirs(agents, exist_ok=True)
            os.makedirs(path("logs"), exist_ok=True)
            with open(plist, "w") as fh:
                fh.write(text)
            if state is not None:
                _launchctl("bootout", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            state = None
        if state is None:
            ok, err = _launchctl("bootstrap", [f"gui/{uid}", plist], name)
            if not ok and svc_running(name) is None:
                alert_once("svc-" + name, err[:80], f"служба {name}: launchd не принял ({err[:160]})", "pantheon-tick",
                           note=f"Служба {name} не запустилась")
                continue
            clear_once("svc-" + name)
        elif state == 0 and port is not None:
            # служба по требованию ждёт соединения на сокете launchd — так и должно быть, если последний запуск
            # кончился чисто (прокси выходит по простою с кодом 0); ненулевой код — служба падает при запуске
            code = svc_last_exit(name)
            if code:
                alert_once("svc-down-" + name, f"exit-{code}", f"служба по требованию {name} падает при запуске: "
                           f"последний код выхода {code}; журнал {path('logs', f'svc-{name}.log').replace(HOME, '~')}",
                           "pantheon-tick", note=f"Служба {name} падает при запуске")
            else:
                clear_once("svc-down-" + name)
        elif state == 0:
            # загружена, но процесса нет (KeepAlive сдался после частых падений) — толкнуть, раз в тик
            _launchctl("kickstart", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            alert_once("svc-down-" + name, "down", f"служба {name} не работает — launchd её перезапускает; журнал "
                       f"{path('logs', f'svc-{name}.log').replace(HOME, '~')}", "pantheon-tick",
                       note=f"Служба {name} не работает")
        else:
            clear_once("svc-down-" + name)


# --- пульт задач -------------------------------------------------------------------

def ago(t):
    if not t:
        return "—"
    s = now() - t
    return f"{int(s)} с назад" if s < 90 else f"{int(s // 60)} мин назад" if s < 5400 else stamp(t)


# --- pantheon status: один экран для отладки --------------------------------------------------------------------
# Только читает: тик, задачи тика, сессии, вопросы к владельцу, тревоги, guard, карантин ~/.claude, места heavy,
# управляемые настройки, версии, память. Первая строка — итог: «всё в порядке» или число того, что требует внимания.
MANAGED = "/Library/Application Support/ClaudeCode/managed-settings.json"


def _sh(*cmd, timeout=20, env=None):
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _plugin_version(name):
    """Установленная версия (кэш), а не голова клона маркетплейса: клон опережает выпуск (metis-0321)."""
    d = installed_dir(name)  # живая — проверенная (verified.json), а не голова клона и не непроверенная установка
    if not d:
        return "нет проверенной"
    with contextlib.suppress(OSError, ValueError):
        return json.load(open(os.path.join(d, ".claude-plugin", "plugin.json"))).get("version", "?")
    return "?"


def status():
    t = now()
    warn, sections = [], []

    def section(title, lines):
        sections.append((title, lines or ["—"]))

    # тик и его задачи
    lt = None
    with contextlib.suppress(OSError, ValueError):
        lt = float(open(path("last-tick")).read())
    lines = [f"последний проход: {ago(lt)}" if lt else "ещё не шёл (pantheon install)"]
    if not lt or t - lt > 180:
        warn.append("плановый проход стоит")
        lines[0] += " — СТОИТ"
    if os.path.exists(path("paused")):
        lines.append("весь планировщик на паузе (pantheon jobs resume --all)")
    try:
        jobs_list = load_schedule().get("job") or []
    except (OSError, ValueError) as e:
        jobs_list = []
        lines.append(f"schedule.toml не прочитать: {type(e).__name__}")
        warn.append("schedule.toml")
    for job in jobs_list:
        st = job_state(job["name"])
        if job.get("enabled") is False or st.get("disabled"):
            continue
        if parse_command(job.get("command")) is None:
            bad = "команда не разрешена"
        elif job_window_problem(parse_command(job.get("command"))):
            bad = job_window_problem(parse_command(job.get("command")))
        elif st.get("paused"):
            bad = "на паузе"
        elif st.get("last_rc") not in (None, 0):
            bad = f"упала, код {st['last_rc']} ({ago(st.get('last_start'))})"
        else:
            continue
        lines.append(f"{job['name']}: {bad}")
        warn.append(f"задача {job['name']}")
    with contextlib.suppress(OSError, ValueError):
        sched_s = load_schedule()
        for svc in sched_s.get("service") or []:
            ok, why = service_wanted(svc, sched_s)
            if ok and svc_on_demand(svc):
                if svc_running(svc["name"]) is None:
                    lines.append(f"служба {svc['name']}: НЕ ЗАГРУЖЕНА (по требованию) — журнал "
                                 f"~/.local/state/pantheon/logs/svc-{svc['name']}.log")
                    warn.append(f"служба {svc['name']}")
            elif ok and not svc_running(svc["name"]):
                lines.append(f"служба {svc['name']}: НЕ ИДЁТ — журнал ~/.local/state/pantheon/logs/svc-{svc['name']}.log")
                warn.append(f"служба {svc['name']}")
            elif not ok and (why in ("пауза", "команда не разрешена") or why.startswith(("socket:", "idle_min:"))):
                lines.append(f"служба {svc['name']}: {why}")
    # дежурный (watch.py): время прохода и упавшие проверки; метка техперезапуска; паузы по нагрузке
    wl = read_json(path("watch-last"), None)
    if wl and wl.get("time"):
        line = f"дежурный: {ago(wl['time'])}"
        if t - float(wl["time"]) > 900:
            line += " — НЕ ХОДИТ (задача watch раз в 5 мин)"
            warn.append("дежурный")
        if wl.get("failed"):
            line += f"; упали проверки: {', '.join(wl['failed'])}"
            warn.append("проверки дежурного")
        lines.append(line)
    m = maintenance_active()
    if m:
        lines.append(f"технический перезапуск: с {str(m.get('id'))[11:16]} ({m.get('reason')}) — pantheon restart --status")
        warn.append("техперезапуск")
    with contextlib.suppress(OSError):
        ps = sorted(f[:-5] for f in os.listdir(path("pauses")) if f.endswith(".json"))
        if ps:
            lines.append("пауза по нагрузке: " + ", ".join("все" if p == "_all" else p for p in ps))
    section("Плановый проход", lines)

    # сессии
    data = agents_all()
    lines = []
    if data is None:
        lines.append("claude agents не ответил")
        warn.append("claude agents")
    else:
        by = {}
        for a in data:
            if a.get("kind") == "interactive":
                by.setdefault("interactive", []).append(a)
                continue
            # metis-0250: «ждёт вас» без процесса и без вопроса — не ждёт, а снята Claude Code (reconcile_agents)
            by.setdefault("gone" if a.get("noProcess") else a.get("state") or "?", []).append(a)
        order = ("interactive", "working", "blocked", "failed", "gone", "done", "stopped")
        word = {"interactive": "открыты в терминале", "working": "фоновые работают", "blocked": "ждут вас",
                "failed": "упали", "gone": "без процесса", "done": "закончили ход", "stopped": "остановлены"}
        lines.append(" · ".join(f"{word.get(k, k)}: {len(by[k])}" for k in sorted(by, key=lambda k: (
            order.index(k) if k in order else 9))) or "фоновых сессий нет")
        for k in ("blocked", "failed", "gone"):
            for a in by.get(k, []):
                # пустая причина — без тире (metis-0250 п. 4); у «без процесса» — что сделать
                why = " ".join(str(a.get("waitingFor") or a.get("status") or "").split())[:80]
                if k == "gone":
                    why = f"ждать нечего, процесс снял Claude Code — убрать: claude rm {a.get('id')}"
                lines.append(f"{word[k]}: {a.get('name') or a.get('id')}" + (f" — {why}" if why else ""))
                if k != "gone":
                    warn.append(f"сессия {a.get('name') or a.get('id')}")
    section("Сессии", lines)

    # вопросы к владельцу на доске
    lines = []
    with contextlib.suppress(Exception):
        waiting = [(tid, head) for tid, (_, head, _) in tasks_mod().load_tasks(PANTHEON).items()
                   if head.get("status") == "waiting" and head.get("waiting_on") == "human"]
        lines = [f"{len(waiting)} на доске"] + [f"{tid}: {str(h.get('title'))[:70]}" for tid, h in waiting[:5]]
    section("Ждут вас", lines)

    # тревоги за сутки
    lines = []
    day = stamp(t - 86400)[:16].replace("T", " ")
    with contextlib.suppress(OSError):
        recent = [ln.strip() for ln in open(os.path.join(PANTHEON, "alerts.md"), encoding="utf-8")
                  if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d · ", ln) and ln[:16] >= day]
        lines = [f"за сутки: {len(recent)}"] + [ln[:110] for ln in recent[-3:]]
    section("Тревоги", lines)

    # guard и защиты
    lines = []
    n_fail = 0
    with contextlib.suppress(OSError):
        since = stamp(t - 86400)[:19]
        n_fail = sum(1 for ln in open(path("logs", "guard-failures.log"), encoding="utf-8") if ln[:19] >= since)
    lines.append(f"сбоев guard за сутки: {n_fail}")
    if n_fail:
        warn.append("сбои guard")
    # сверка — с проверенным деревом guard (verified.json), как у прохода (merge.managed_source), а не с клоном маркетплейса:
    # клон впереди выпуска, и status показывал «отстали» там, где проход ничего не покажет (metis-0718)
    if not os.path.exists(MANAGED):
        lines.append("управляемые настройки: НЕ установлены (README guard, sudo)")
        warn.append("управляемые настройки")
    else:
        try:
            src = merge_mod().managed_source()
        except Exception:  # noqa: BLE001 — сбой разбора не ломает экран
            src = None
        if src is None:
            lines.append("управляемые настройки: проверенного дерева guard нет — сверить не с чем (pantheon plugins accept)")
            warn.append("управляемые настройки")
        elif open(MANAGED, "rb").read() != src[1]:
            lines.append("управляемые настройки: отстали от guard — обновить той же командой sudo")
            warn.append("управляемые настройки")
        else:
            lines.append("управляемые настройки: установлены, совпадают с guard")
    section("Защиты", lines)

    # синхронизация ~/.claude
    lines, cfg = [], os.path.join(HOME, ".claude")
    marks = {".sync-held": "карантин правок — ответ на доске", ".sync-incoming": "правка с другого компьютера — на доске",
             ".sync-conflict": "конфликт с другим компьютером", ".sync-error": "ошибка синхронизации"}
    for f, what in marks.items():
        if os.path.exists(os.path.join(cfg, f)):
            lines.append(what)
            warn.append("sync")
    section("Синхронизация ~/.claude", lines or ["в порядке"])

    # недельный лимит и ночь (metis-0127, 0129)
    try:
        lines = night_mod().status_lines(t)
    except Exception as e:  # noqa: BLE001 — сбой расчёта не ломает остальной экран
        lines = [f"не посчитать: {type(e).__name__}: {str(e)[:120]}"]
    if any(ln.startswith("лимит неизвестен") or "зона: красная" in ln or "зона: жёлтая" in ln for ln in lines):
        warn.append("лимит")
    section("Лимит и ночь", lines)

    # места heavy, память, версии
    lines = []
    for name in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
        p = path("locks", name + ".lock")
        if not os.path.exists(p):
            lines.append(f"{name}: нет (pantheon install)")
            continue
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                lines.append(f"{name}: свободно")
            except OSError:
                lines.append(f"{name}: занято")
            finally:
                os.close(fd)
        except OSError:
            lines.append(f"{name}: не открыть")
    sw = re.search(r"used = ([\d.,]+)M", _sh("sysctl", "vm.swapusage"))
    if sw:
        used = float(sw.group(1).replace(",", "."))
        lines.append(f"swap: {used / 1024:.1f} ГБ")
        if used > 4096:
            warn.append("swap")
    with contextlib.suppress(Exception):
        lines.append(awake_mod().status_line())
    lines.append(f"Claude Code {(_sh('claude', '--version', env=claude_env()).split() or ['?'])[0]} · guard {_plugin_version('guard')} · "
                 f"pantheon {_plugin_version('pantheon')}")
    section("Mac", lines)

    head = "всё в порядке" if not warn else f"требует внимания: {len(warn)} — " + ", ".join(dict.fromkeys(warn))
    print(f"Пантеон · {host()} · {stamp(t)[:16].replace('T', ' ')} · {head}\n")
    for title, lines in sections:
        print(title)
        for ln in lines:
            print(f"  {ln}")
        print()
    return 0 if not warn else 1


def jobs_set(action, name, arg=None):
    if name == "--all":
        if action not in ("pause", "resume"):
            print("--all бывает только у pause и resume", file=sys.stderr)
            return 2
        if action == "pause":
            open(path("paused"), "w").write(stamp())
            alert("весь планировщик на паузе (pantheon jobs pause --all)", "pantheon")
        elif action == "resume":
            with contextlib.suppress(FileNotFoundError):
                os.remove(path("paused"))
        return 0
    sched = load_schedule()
    job = next((j for j in (sched.get("job") or []) + (sched.get("service") or []) if j["name"] == name), None)
    if not job:
        print(f"нет задачи или службы {name}; список — pantheon jobs", file=sys.stderr)
        return 2
    is_svc = job in (sched.get("service") or [])
    if is_svc and action == "renew":
        print("у служб нет аренды", file=sys.stderr)
        return 2
    st = job_state(name)
    if action == "pause":
        st.update(paused=True, paused_reason="вы")
    elif action == "resume":
        st.update(paused=False, paused_reason=None)
    elif action == "disable":
        st["disabled"] = True
    elif action == "enable":
        st["disabled"] = False
    elif action == "renew":
        days = float(arg or job.get("lease_days") or 30)
        st.update(lease_until=now() + days * 86400, paused=False, paused_reason=None)
    save_job_state(name, st)
    if is_svc:
        services_sync(sched, only=name)  # служба встаёт или поднимается сразу, а не на следующем тике
    return 0


# --- задачи ------------------------------------------------------------------------


def git(*args, check=True):
    return subprocess.run(["git", "-C", PANTHEON, *args], capture_output=True, text=True, check=check,
                          env=run_env())


def clear_push_failures():
    with contextlib.suppress(OSError):
        os.remove(path("push-fail.json"))
    clear_once("push-fail")


def write_atomic(p, text):
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, p)


# Имена окон, которые не направления: sandbox_build пишет settings/hq.json, workshop.json, hestia.json (metis-0245) и
# job-<роль>.json; направление с таким именем записало бы свои настройки в чужой файл — а при сбое второй записи они
# там и остались бы (metis-0163)
RESERVED_DIRECTIONS = ("hq", "workshop", "hestia")


def reserved_direction(name):
    """Текст ошибки, если имя направления зарезервировано под окно hq, workshop, hestia или job-*; иначе None."""
    if isinstance(name, str) and (name in RESERVED_DIRECTIONS or name.startswith("job-")):
        return (f"имя «{name}» зарезервировано под окна системы (hq, workshop, hestia, job-*): настройки направления "
                "записались бы в чужой файл окна — выберите другое имя")
    return None


def domains_build(if_changed=False):
    """Реестр направлений → domains.json для guard. Привилегий тут нет: они в ~/.claude/pantheon/policy.toml.
    Папку привилегированного координатора (из [coordinators] policy.toml) чужое направление получить не может:
    такая папка пропускается с тревогой — иначе правкой реестра можно было бы отдать чужому код guard или me/."""
    reg_path = os.path.join(PANTHEON, "directions.toml")
    policy_path = os.path.join(HOME, ".claude", "pantheon", "policy.toml")
    if if_changed:
        built = read_json(path("domains.json")).get("built_ts") or 0
        # и новые папки сессий: правило Read окна штаба закрывает чужие шаблонами по префиксам — новый префикс тоже должен
        # попасть в hq.json
        # и каталог ролей: новая роль с memory: должна попасть в песочницу окон (metis-0051). Цикла нет: roles_build
        # пишет файл, только если текст изменился, — пересборка одна, следующий тик уже тихий
        # и проектные настройки папок запуска направлений: allow с gh pr merge роняет окно (metis-0137)
        launches = [launch_folder(fs) for fs in (read_json(path("domains.json")).get("domains") or {}).values()]
        # и реестр установленных плагинов: путь guard.py и agents.py окон берётся из него — обновили guard, окна
        # пересобираются на новый путь (metis-0321, ревью 90a)
        watched = (reg_path, policy_path, os.path.join(HOME, ".claude", "projects"), AGENTS, CLAUDE_TMP, INSTALLED_PLUGINS,
                   _verified_path(),
                   # и настройки владельца: enabledPlugins сверяется с каталогом карты плагинов (plugin-map-unknown
                   # приходит только при сборке, metis-0601 Д5)
                   os.path.join(HOME, ".claude", "settings.json"),
                   *(os.path.join(l, ".claude", fn) for l in launches if l for fn in PROJECT_SETTINGS_FILES))
        newest = max([os.path.getmtime(p) for p in watched if os.path.exists(p)] + [roles_newest()])
        # и пропавшее окно задачи расписания (P0-3): без него задача не идёт — в том числе сразу после обновления
        # и grants.toml: правка — сразу, срок разрешения — к сроку (grants_next)
        newest = max(newest, os.path.getmtime(GRANTS) if os.path.exists(GRANTS) else 0)
        due = read_json(path("domains.json")).get("grants_next")
        # и папка мастерской: появилась ~/ai/workshop (перенос) — окно workshop и текст роли на новую (metis-0899)
        if built >= newest and not (due and now() >= due) and all(os.path.isfile(job_window(r)) for r in JOB_ROLES) \
                and read_json(path("domains.json")).get("workshop") == workshop_dir():
            return 0
    with open(reg_path, "rb") as fh:
        reg = tomllib.load(fh)
    try:
        with open(policy_path, "rb") as fh:
            priv = tomllib.load(fh).get("coordinators") or {}
    except (OSError, ValueError):
        priv = {}
    norm = lambda p: os.path.realpath(os.path.expanduser(p))
    overlap = lambda a, b: a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
    domains, stores, leads = {}, {}, {}
    for d in reg.get("direction") or []:
        name = d.get("name", "")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            print(f"пропущено направление с именем не по образцу: {name!r}", file=sys.stderr)
            continue
        bad = reserved_direction(name)
        if bad:
            print(f"пропущено направление: {bad}", file=sys.stderr)
            alert_once(f"direction-reserved-{name}", "1", f"directions.toml: {bad}", "pantheon")
            continue
        folders = []
        for f in d.get("folders") or []:
            owner = next((o for o, ps in priv.items() if o != name and any(overlap(norm(f), norm(p)) for p in ps)), None)
            if owner:
                alert_once(f"domains-{name}-{f}", "1", f"directions.toml: папка {f} отдана направлению {name}, "
                           f"но это папка {owner} (policy.toml) — пропущена при сборке domains.json", "pantheon")
                continue
            folders.append(f)
        domains[name] = folders
        if isinstance(d.get("pnpm_store"), str):
            stores[name] = d["pnpm_store"]
        # лиды направления — субагенты его окна (P0-6); имена как у roles_build
        bases = d.get("leads") if isinstance(d.get("leads"), list) else []
        if re.fullmatch(r"[a-z0-9]+-[a-z0-9-]+", name):
            short = name.split("-", 1)[1]
            leads[name] = [f"{b}-{short}" for b in LEAD_ROLES if b in bases]
    write_json(path("domains.json"), {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml. Руками не править.",
        "built": stamp(), "built_ts": now(), "domains": domains, "grants_next": grants_load()[1],
        "workshop": workshop_dir()})
    # живую сессию с проблемой проектных allow останавливает только путь тика (--if-changed): ручная сборка и тесты
    # зовут её с настоящим claude в PATH — claude stop из них остановил бы ваши сессии
    built = sandbox_build(domains, policy_path, stores, leads, stop_live=if_changed)
    with contextlib.suppress(OSError):  # файл или ссылка на месте папки — не повод ронять сборку
        os.makedirs(path("locks", "heavy-queue"), exist_ok=True)  # билеты очереди обёртки heavy (metis-0659)
    os.makedirs(path("locks"), exist_ok=True)
    for slot in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):  # места обёртки heavy: роль в песочнице сама их не создаст
        open(path("locks", slot + ".lock"), "a").close()
    roles = roles_build()
    if roles:
        print(f"роли: {', '.join(roles)}")
    if not if_changed:
        print(f"domains.json: {len(domains)} направлений → {path('domains.json').replace(HOME, '~')}; "
              f"настройки окон ролей: {', '.join(built)} → {path('settings').replace(HOME, '~')}/")
    return 0


# Песочница окон ролей (SEC-19): файл для `claude … --settings <файл>` у каждого направления и у мастерской.
# Строгий вид: без отката мимо песочницы, без неё сессия не стартует. Писать можно в папку запуска, папки
# направления внутри ~/projects и ~/ai/knowledge, своё ~/ai/pantheon/directions/<имя>/, свою папку кэшей и временную
# папку. Общие кэши инструментов закрыты: ими пользуются ваши сессии без песочницы, поэтому кэши направления
# (npm, pnpm, uv, pip, corepack, ~/.cache через XDG_CACHE_HOME) — свои, через переменные окружения. Сверх
# этого — только [sandbox_write] из policy.toml (правит Метида), не из реестра: правкой реестра права не выдать.
# .git/config и .git/hooks закрыты для записи: сетевой git направлений (и мастерской с SSH-remote) и gh идут мимо песочницы.
# Личное из [private] policy.toml закрыто для чтения всем, кроме координаторов с этой привилегией.
# Сеть — через прокси песочницы: хосты вне списка проверяет классификатор режима auto.
# Пути в файле — настоящие абсолютные (свои у каждого Mac): ссылка, подставленная позже, их не сдвинет.
# Хранилище pnpm по умолчанию не подменяется: node_modules помнит своё хранилище, и разные хранилища у координатора и
# ваших сессий в одной папке ломают pnpm (вопрос «modules directory will be removed», без терминала — код 0 и ничего не
# поставлено). Общее хранилище направления — поле pnpm_store реестра (путь внутри папок направления): окно получает
# npm_config_store_dir, а ваш терминал — тот же store-dir в .npmrc проекта (вариант А athena-0001, 15.10). Переменная
# нужна копиям разработчиков: .npmrc вне git в них не попадает.
# Координаторам там же — окно сжатия 200k (CTX-04).
# Папки направлений для песочницы — только внутри этих. Первые SANDBOX_STRICT — только папки внутри (не сам корень):
# ~/projects/<x> и ~/ai/life/<x> (личное владельца, metis-0899); ~/ai/knowledge, мастерская ~/ai/workshop и код
# Пантеона ~/ai/agent-kit (папка metis-pantheon) — и сам корень. Остальное в ~/ai (pantheon, pantheon-view) — нет
WORKSHOP_DIR = "~/ai/workshop"   # мастерская Дедала после переноса (metis-0899); живая папка — workshop_dir()
LIFE_DIR = "~/ai/life"   # области жизни владельца: простая папка без .git, у каждой области свой git (Зевс 06.11, metis-0899)
AGENT_KIT_DIR = "~/ai/agent-kit"   # рабочая копия agent-kit (metis-0899; до переноса — в ~/projects)
SANDBOX_ROOTS = ["~/projects", LIFE_DIR, "~/ai/knowledge", WORKSHOP_DIR, AGENT_KIT_DIR]
SANDBOX_STRICT = 2
SANDBOX_DOMAINS = ["registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org",
                   "github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                   "raw.githubusercontent.com"]
# Мимо песочницы: gh (в ней не работает — TLS Go на macOS) — только эти подкоманды; дописать тревогу. Всё, что не
# исключено, в песочнице просто падает — это и есть отказ (P0-4, metis-0064): `gh api` и запись в `gh issue` (любые
# записи в GitHub) не выпускаются; из `gh pr`, `gh issue` и `gh run` — только чтение (`gh run cancel|rerun|delete`
# падают). Голые формы — отдельно: шаблон «… *» их не покрывает (metis-0533: status и gh issue view|list добавлены)
GH_PR_READ = [f"gh pr {c}{tail}" for c in ("view", "checks", "diff", "list", "status") for tail in ("", " *")]
GH_ISSUE_READ = [f"gh issue {c}{tail}" for c in ("view", "list") for tail in ("", " *")]
GH_RUN_READ = [f"gh run {c}{tail}" for c in ("view", "list", "watch") for tail in ("", " *")]
SANDBOX_EXCLUDED = GH_PR_READ + GH_ISSUE_READ + GH_RUN_READ + ["gh repo view *", "gh auth status",
                                 "pantheon alert *", "pantheon consent *", "pantheon saved *"]
# PR создают и правят (заголовок, описание, метки — `gh pr edit`, metis-0247) лиды, сливает координатор или лид —
# только окна направлений; кто и что сливает, проверяет guard (merge_problem). Мастерской — нет. metis-0533: ещё
# `gh pr comment` (ответ ревью в PR) и `gh pr ready` (снять черновик) — без произвольного кода; текст — через
# --body-file. `gh pr close|reopen|review`, запись в `gh issue`, `gh api`, `gh auth token`, `gh extension` — в песочнице
GH_PR_WRITE = ["gh pr create *", "gh pr edit *", "gh pr merge *", "gh pr comment *", "gh pr ready *"]
# штаб (metis-0247, «да» владельца 19.10 [zeus-0247-yes]): сети у окна нет, а gh в песочнице всё равно падает (TLS Go,
# x509 -26276) — мимо неё только чтение PR и правка. Слияния здесь нет (решение Зевса 19.10, metis-0247 r4): gh pr
# merge, gh api и прочий gh остаются в песочнице без сети и падают; guard (hq-gh) вдобавок отказывает слиянию в любой
# форме — `gh -R o/r pr merge`, GH_REPO=…, gh api …/merge. metis-0626 (решение Метиды 01.11): ещё gh pr list — без
# списка открытых PR сводка доски устаревает; guard (hq-gh) пускает его только с -R из [merge_repos] и без --search.
# gh pr diff и gh run — нет: лишний чужой текст в окне
HQ_GH = [f"gh pr {c}{tail}" for c in ("view", "checks", "list") for tail in ("", " *")] + ["gh pr edit *"]
# git по SSH в песочнице macOS не работает, по HTTPS push упирается в помощник учётных данных: окну каждого направления
# сетевые команды git — мимо неё; мастерской — только при SSH-remote. push в main/master, --force и --delete не
# пускает guard (_PUSH_BAD). Только сеть, без записи в рабочую копию (metis-0971, решение Зевса 07.11, вариант А):
# `git pull` вне песочницы вливал коммит в рабочую копию защищённого репозитория (~/.claude, ~/ai/pantheon), если cwd
# внутри allowWrite. Подтянуть — `git fetch` мимо песочницы, затем `git merge` в ней: запись там судит песочница.
# Список команд, меняющих рабочую копию, держит тест test_window_rules.py (WORKTREE_WRITE)
GIT_NETWORK = ["git push", "git push *", "git fetch", "git fetch *"]
COORDINATOR_COMPACT = 200000
# Пароль демона CDP (~/.claude/tools/cdp-daemon.mjs, браузер с входами владельца): без него демон отвечает 401. Окнам
# ролей файл закрыт на чтение — и песочницей Bash, и правилом Read ([sb-simplify] 27.10)
CDP_TOKEN_DIR = os.path.join(HOME, ".config", "cdp-daemon")
# Правила слияния через шлюз guard (permissions.allow и autoMode.allow окон координаторов) — в lib/window_rules.py:
# он в ядре защит (metis-0174), его PR ждёт слияния владельцем. Имена здесь — для прежних вызовов и тестов
def _window_rules():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_window_rules", os.path.join(LIB, "window_rules.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


WINDOW_RULES = _window_rules()

# Карта «окно или роль × плагин и MCP» (metis-0238) — plugins-by-role.toml, разбор — lib/plugin_map.py; оба — ядро
# защит (metis-0598, решение владельца 30.10). Окна: enabledPlugins и permissions.deny mcp__*; роли: disallowedTools
# шапки при roles build.
PLUGIN_MAP_FILE = os.path.join(PLUGIN, "plugins-by-role.toml")


def _plugin_map_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_plugin_map", os.path.join(LIB, "plugin_map.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PLUGIN_MAP = _plugin_map_mod()


def plugin_map_names(kind, src=None):
    """Известные имена записей карты для сборки kind: «window» — окна (hq, hestia, workshop, direction, job-<роль
    расписания>, имена направлений реестра), «roles» — роли (шаблоны .tmpl плагина и личного слоя). Возвращает пару
    (окна, роли) для PLUGIN_MAP.load; имена другого рода и нечитаемый реестр — None (не сверять): каждая сборка
    ловит опечатку в своих записях, а чужая не ломает её (roles build не зависит от реестра окон)."""
    if kind == "roles":
        roles = set()
        for d in (os.path.join(PLUGIN, "roles"), PLUGIN_ROLES, AGENTS, src):
            try:
                roles |= {f[:-5] for f in os.listdir(d) if f.endswith(".tmpl")} if d else set()
            except OSError:
                pass
        return None, roles
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            reg = tomllib.load(fh)
        dirs = {d.get("name") for d in reg.get("direction") or [] if isinstance(d, dict)}
    except (OSError, ValueError):
        return None, None
    return {"direction", "hq", "hestia", "workshop"} | {"job-" + r for r in JOB_ROLES} | dirs, None


def plugin_map_load(alert=True, kind="window", src=None):
    """Карта из PLUGIN_MAP_FILE или None, если файл не читается или неверен: тогда окна и роли остаются как были (всё
    включено), а причина — в тревоге (alert) и в stderr: молча «не применено» было бы ложным «отключено». С alert ещё
    сверка с enabledPlugins пользователя (~/.claude/settings.json): включённый плагин вне каталога карта не выключает
    нигде — тревога plugin-map-unknown один раз на список; пробная сборка (alert=False) тревог не шлёт и не снимает."""
    try:
        pmap = PLUGIN_MAP.load(PLUGIN_MAP_FILE, *plugin_map_names(kind, src))
    except ValueError as e:
        print(f"plugins-by-role: {e} — карта не применена, у окон и ролей всё включено", file=sys.stderr)
        if alert:
            alert_once("plugin-map-bad", str(e), f"{e} — карта не применена, у окон и ролей всё включено (Метида)",
                       "pantheon")
        return None
    for entry in pmap["skipped"]:  # неизвестное имя окна или роли: запись пропущена, остальная карта действует
        print(f"plugins-by-role: запись {entry} — такого окна или роли нет, пропущена (опечатка или удалённое "
              "направление); остальная карта действует", file=sys.stderr)
    if alert:
        clear_once("plugin-map-bad")
        for entry in pmap["skipped"]:  # одна тревога на запись, повтор молчит
            alert_once("plugin-map-name-" + entry, entry, f"plugins-by-role: запись {entry} — такого окна или роли "
                       "нет, она не применяется (опечатка или удалённое направление); остальная карта действует "
                       "(Метида)", "pantheon")
        # запись исправлена или убрана — метка снята, следующая опечатка встревожит снова
        stem = re.sub(r"[^\w.-]", "_", "plugin-map-name-")
        try:
            for f in os.listdir(path("once")):
                if f.startswith(stem):
                    mark = path("once", f)
                    own = "[role." if kind == "roles" else "[window."  # чужого рода метку снимает своя сборка
                    text = open(mark).read()
                    if text.startswith(own) and text not in pmap["skipped"]:
                        os.remove(mark)
        except OSError:
            pass
        try:
            with open(os.path.join(HOME, ".claude", "settings.json"), encoding="utf-8") as fh:
                enabled = json.load(fh).get("enabledPlugins")
        except (OSError, ValueError, AttributeError):
            return pmap  # нет настроек, битые или не прочесть — сверять не с чем; прежнюю тревогу не снимаем
        unknown = PLUGIN_MAP.unknown_enabled(pmap, enabled)
        if unknown:
            alert_once("plugin-map-unknown", " ".join(unknown), f"plugins-by-role: {', '.join(unknown)} включены у вас, "
                       "но их нет в [catalog] карты — карта их не выключает ни в одном окне; добавить в каталог и "
                       "«оставить» нужным окнам (Метида)", "pantheon")
        else:
            clear_once("plugin-map-unknown")
    return pmap
COORDINATOR_ALLOW = WINDOW_RULES.COORDINATOR_ALLOW
MERGE_REPO_RE = WINDOW_RULES.MERGE_REPO_RE
GATED_MERGE_RULE = WINDOW_RULES.GATED_MERGE_RULE
LEAD_DELIVERY_RULE = WINDOW_RULES.LEAD_DELIVERY_RULE
REVIEW_RECORD_RULE = WINDOW_RULES.REVIEW_RECORD_RULE
coordinator_auto_allow = WINDOW_RULES.coordinator_auto_allow

# Роли главных сессий: их память в песочницу не добавляется, даже если в шапке есть memory:
MAIN_ROLES = ("hq", "domain-coordinator", "workshop")
# Субагенты главной сессии окна (P0-6; SEC-09, SEC-13, ROLE-32): штаб и координатор зовут только этих — general-purpose
# и claude (веб и все инструменты) обошли бы запреты окна. Проверяет хук hooks/agents.py и только у главной сессии (в
# её событии нет agent_id): tools: Agent(…) в шаблоне роли и permissions.deny действуют и на субагентов окна — лид не
# позвал бы своих dev-*, навык audit — general-purpose. В deny окна — только жёсткие границы, не нужные и лидам.
# Координатору — ещё свои лиды (из реестра). Explore — только чтение: без него координатор читает код в свой контекст
# (CTX-09); веба через него не больше, чем через prometheus и лидов. clio зовут Зевс и mnemo-brain (роль clio).
# momus — ревизор навыка audit (metis-0095, решение владельца 15.10): только чтение и веб, пишет лишь свой отчёт в
# ~/ai/knowledge/Inbox. Координаторам его нет — без отдельного слова владельца.
HQ_AGENTS = ["prometheus", "clio", "chiron", "momus", "palamedes", "charon", "Explore"]
# dev-haiku, dev-sonnet, dev-opus — разработчики: координатор отдаёт им мелкие правки сам, не гоняя лида (эпик
# «Альфа»); codex-dev сюда не входит — его зовёт только лид по правилу executor. palamedes — исполнитель без кода
# (metis-0224): тексты, юридический разбор, синтез; веба и Bash у него нет, пишет только свой черновик.
COORDINATOR_AGENTS = ["argus", "talos", "prometheus", "palamedes", "Explore", "dev-haiku", "dev-sonnet", "dev-opus"]
COORDINATOR_EXTRA_AGENTS = {"mnemo-brain": ["clio"]}
# Skill — навык с context: fork идёт субагентом своего agent: мимо инструмента Agent (Claude Code 2.1.292)
AGENT_MATCHER = "Agent|Task|Skill"
# копия из ~/.claude/plugins, а не рабочая копия agent-kit — довод как у MARKET_GUARD (guard_script)
# Отдельный файл, а не команда ctx.py: старая копия ctx.py без команды пропускала бы всё, а отсутствующий agents.py
# — код 2 у python, то есть блок (onFailure: block работает только с Claude Code 2.1.295).
MARKET_AGENTS = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "pantheon", "hooks",
                             "agents.py")
# terminal-notifier по щелчку открывает ссылку или выполняет команду — от имени владельца, вне песочницы. Ролям его
# не прочитать, а значит и не запустить: уведомления Пантеона шлёт только тик (поддельное «от Пантеона» не пройдёт).
NOTIFIER_PATHS = ["/opt/homebrew/Cellar/terminal-notifier", "/opt/homebrew/opt/terminal-notifier",
                  "/usr/local/Cellar/terminal-notifier", "/usr/local/opt/terminal-notifier"]


def ssh_remote(folder):
    """Есть ли у репозитория в папке (или в её подпапках первого уровня) remote по SSH."""
    root = os.path.expanduser(folder)
    repos = [root] + ([os.path.join(root, x) for x in sorted(os.listdir(root))] if os.path.isdir(root) else [])
    for r in repos:
        if not os.path.exists(os.path.join(r, ".git")):
            continue
        out = subprocess.run(["git", "-C", r, "remote", "-v"], capture_output=True, text=True).stdout
        if re.search(r"\s(ssh://|[\w.-]+@[\w.-]+:)", out):
            return True
    return False


def hq_state_dirs():
    """Настоящие пути STATE/hq-rw/locks и STATE/hq-rw/autostart-reset (создаются) — запись окну Зевса. Сама hq-rw ему
    не даётся: подменить подпапку ссылкой окно не может. Ссылка или не папка — не даётся."""
    out = []
    if os.path.islink(path(HQ_RW)):
        return out
    for n in HQ_RW_DIRS:
        p = path(HQ_RW, n)
        with contextlib.suppress(OSError):
            os.makedirs(p, mode=0o700, exist_ok=True)
        if os.path.isdir(p) and not os.path.islink(p):
            out.append(os.path.realpath(p))
    return out


def _real_dir(p, roots, strict=False, create=False):
    """Папка от ~/ внутри одной из roots → её настоящий абсолютный путь; None — вне них, ссылка или папки нет.
    В настройки идёт настоящий путь, а не «~/…»: подмена папки ссылкой после сборки не сдвинет границу."""
    if not isinstance(p, str) or not p.startswith("~/") or "*" in p or ".." in p.split("/"):
        return None
    x = os.path.expanduser(p)
    if create and not os.path.lexists(x):
        os.makedirs(x, exist_ok=True)
    if os.path.islink(x) or not os.path.isdir(x):
        return None
    k = os.path.realpath(x)
    for r in roots:
        rk = os.path.realpath(os.path.expanduser(r))
        if k.startswith(rk + "/") or (k == rk and not strict):
            return k
    return None


# закрытые штабу папки (индексы qmd, копии больших корпусов, сырые выгрузки — чужой текст; штабу его не читать: у
# штаба личное и действия наружу) — [hq].closed_dirs policy.toml, в коде их нет (metis-0182, разбор — hq_policy в
# hooks/ctx.py). Вопросы по ним — координатору направления поручением; коллекции qmd штабу закрывает хук qmd-query


# выводы фоновых задач и TMPDIR песочницы всех сессий Claude Code: /tmp/claude-<uid> (на macOS по умолчанию). Не из
# CLAUDE_CODE_TMPDIR: внутри сессии Claude Code ставит его уже с /claude-<uid> на конце. PANTHEON_CLAUDE_TMP — тестам
CLAUDE_TMP = os.path.realpath(os.environ.get("PANTHEON_CLAUDE_TMP") or os.path.join("/tmp", f"claude-{os.getuid()}"))
# Seatbelt не собирает профиль больше 64 КБ: Bash окна не запускается совсем («sandbox-exec: data object length …
# exceeds maximum (65535)», hq 15.10 — 4359 путей). Оценка — сумма байтов путей песочницы окна; это не размер
# профиля: 15.10 hq с 985 путями (~150 КБ путей) Bash запускал, а 4359 путей дали 69 833 байт, — порог с запасом в
# безопасную сторону. Списки ~/.claude/settings.json, которые сливаются с окном, не учтены. Выше порога окно не
# пересобирается (остаётся прежний файл) и приходит тревога
try:
    SANDBOX_SIZE_LIMIT = int(os.environ.get("PANTHEON_SANDBOX_LIMIT") or 48 * 1024)
except ValueError:
    SANDBOX_SIZE_LIMIT = 48 * 1024
GLOB_SAFE = re.compile(r"[A-Za-z0-9._-]+")


def _others_globs(names, own, keep=()):
    """Папки чужих сессий среди names → немного шаблонов «<префикс>*» (и точных имён), ни один из которых не совпадает
    со своими: own, own--claude-worktrees-* и имена на префиксы keep (они остаются открыты). Префикс — до первой
    буквы, где имя расходится со всеми своими, поэтому тысячи guard-test-* дают один «g*»: список не растёт с числом
    папок. Имя с символами шаблона пропускается — вернётся в skipped."""
    wt = own + "--claude-worktrees-"
    mine = (own, wt) + tuple(keep)
    out, skipped = set(), []
    for n in names:
        if n == own or n.startswith(wt) or n.startswith(tuple(keep)):
            continue
        p = next((n[:i] for i in range(1, len(n) + 1) if not any(m.startswith(n[:i]) for m in mine)), None)
        x = n if p is None else p + "*"
        if GLOB_SAFE.fullmatch(n if p is None else p):
            out.add(x)
        else:
            skipped.append(n)
    return sorted(out), skipped


def sandbox_size(data):
    """Байты путей песочницы окна: списки filesystem и правила Read/Edit (Claude Code добавляет их в песочницу)."""
    fs = (data.get("sandbox") or {}).get("filesystem") or {}
    perms = data.get("permissions") or {}
    items = [x for k in ("allowWrite", "denyWrite", "denyRead", "allowRead") for x in fs.get(k) or []]
    items += [x for k in ("deny", "allow", "ask") for x in perms.get(k) or [] if x.startswith(("Read(", "Edit("))]
    return sum(len(x.encode()) + 1 for x in items)


# Ручные разрешения окнам ([sb-simplify] п. 6): ~/.claude/pantheon/grants.toml — его правит владелец или Метида
# (protect-config), выпуск его не стирает. Каждое — со сроком: сборка применяет его по «until» включительно, потом
# снимает сама (тик пересобирает окна к сроку) и пишет тревогу. Записи в ключи, конфиг и браузер — не даются
GRANTS = os.path.join(HOME, ".claude", "pantheon", "grants.toml")
GRANT_KEYS = {"allow": ("permissions", "allow"), "write": ("sandbox", "filesystem", "allowWrite"),
              "domains": ("sandbox", "network", "allowedDomains")}
# запись не даётся в ключи, конфиг, автозапуск, код и состояние Пантеона (STATE, ~/.local целиком, PANTHEON) и в папку
# демона хуков guard (HOOKD_DIR, metis-0845): окно с записью туда подменило бы клиент с его меткой — «пропустить» на всё.
# Папка выше тоже не даётся: grant write = ["~/.cache"] отклоняется целиком, как ["~"]
GRANT_NO_WRITE = ("~/.claude", "~/.config", "~/.ssh", "~/.gnupg", "~/Library", "~/.local", "~/.zshrc", "~/.zprofile",
                  "~/.bashrc", "~/.profile", HOOKD_HOME, STATE, PANTHEON)
GRANT_STAR_SKIP = re.compile(r"hq|hestia|job-.+")  # «*» — окнам направлений и мастерской, не служебным


def grants_load():
    """grants.toml → (разрешения в силе, ближайший срок окончания в секундах или None, ошибки, истёкшие)."""
    try:
        with open(GRANTS, "rb") as fh:
            raw = tomllib.load(fh).get("grant") or []
    except FileNotFoundError:
        return [], None, [], []
    except (OSError, ValueError) as e:
        return [], None, [f"grants.toml не читается: {e}"], []
    live, errors, expired, nxt = [], [], [], None
    for i, g in enumerate(raw if isinstance(raw, list) else [], 1):
        win, until = g.get("window"), str(g.get("until") or "")
        try:
            end = (datetime.strptime(until, "%Y-%m-%d") + timedelta(days=1)).timestamp()
        except ValueError:
            errors.append(f"grant {i}: until — дата ГГГГ-ММ-ДД, а не {until!r}")
            continue
        if not isinstance(win, str) or not re.fullmatch(r"[a-z0-9-]+|\*", win):
            errors.append(f"grant {i}: window — имя окна или «*», а не {win!r}")
            continue
        bad = [k for k in g if k not in GRANT_KEYS and k not in ("window", "until", "why")]
        lists = {k: g[k] for k in GRANT_KEYS if k in g}
        if bad or not lists or not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in lists.values()):
            errors.append(f"grant {i} ({win}): ключи — {', '.join(GRANT_KEYS)} списками строк" +
                          (f"; лишние: {', '.join(bad)}" if bad else ""))
            continue
        norm = lambda x: os.path.realpath(os.path.expanduser(x))  # noqa: E731
        glob_w = [x for x in lists.get("write", []) if re.search(r"[*?\[\]{}]", x) or not x.startswith(("/", "~/"))]
        if glob_w:
            errors.append(f"grant {i} ({win}): write — только путь от / или ~/ без шаблонов: {', '.join(glob_w)}")
            continue
        closed = [x for x in lists.get("write", []) if any(
            norm(x) == norm(c) or norm(x).startswith(norm(c).rstrip("/") + "/") or norm(c).startswith(norm(x).rstrip("/") + "/")
            for c in GRANT_NO_WRITE)]
        if closed:
            errors.append(f"grant {i} ({win}): запись в ключи, конфиг и автозапуск не даётся: {', '.join(closed)}")
            continue
        if end <= now():
            expired.append((i, win, until))
            continue
        live.append({"window": win, "until": until, **lists})
        nxt = end if nxt is None else min(nxt, end)
    return live, nxt, errors, expired


def grants_apply(name, data, grants):
    """Разрешения окна name (и «*») — в его настройки, без повторов."""
    for g in grants:
        if g["window"] != name and not (g["window"] == "*" and not GRANT_STAR_SKIP.fullmatch(name)):
            continue
        for k, keys in GRANT_KEYS.items():
            if k not in g:
                continue
            node = data
            for key in keys[:-1]:
                node = node.setdefault(key, {})
            vals = list(node.get(keys[-1]) or [])  # копия: списки окна бывают общими константами модуля
            for x in g[k]:
                x = os.path.realpath(os.path.expanduser(x)) if k == "write" else x
                if x not in vals:
                    vals.append(x)
            node[keys[-1]] = vals


def grants_check():
    """Тревоги сборки: ошибки в grants.toml и истёкшие разрешения (одна на разрешение)."""
    _, _, errors, expired = grants_load()
    if errors:
        alert_once("grants-bad", "; ".join(errors), "grants.toml: " + "; ".join(errors[:5]) + " — эти разрешения "
                   "не применены (Метида)", "pantheon")
    else:
        clear_once("grants-bad")
    for i, win, until in expired:
        alert_once(f"grant-expired-{win}-{until}-{i}", "1", f"grants.toml: разрешение {i} окну {win} истекло {until} — "
                   "снято при сборке; продлить или удалить запись (Метида)", "pantheon")


def write_window(out_dir, name, data):
    """Файл окна, если его песочница в пределах SANDBOX_SIZE_LIMIT; иначе тревога и прежний файл остаётся.
    Разрешения grants.toml — сюда же; файлы запущенных сессий этого окна (settings/run/) обновляются: Claude Code
    перечитывает их на ходу, и выданное или истёкшее разрешение доходит без перезапуска."""
    grants_apply(name, data, grants_load()[0])
    size, key = sandbox_size(data), f"sandbox-size-{name}"
    if size > SANDBOX_SIZE_LIMIT:
        print(f"песочница {name}: {size} байт путей > {SANDBOX_SIZE_LIMIT} — окно не пересобрано", file=sys.stderr)
        alert_once(key, "over", f"песочница окна {name}: {size} байт путей, предел {SANDBOX_SIZE_LIMIT} (профиль Seatbelt "
                   "до 64 КБ, иначе Bash окна не запускается) — окно не пересобрано, оставлен прежний файл. Сжать "
                   "списки в sandbox_build (каталоги и шаблоны вместо перечисления)", "pantheon",
                   note=f"Песочница окна {name} не помещается в предел — окно не пересобрано")
        return False
    clear_once(key)
    write_json(os.path.join(out_dir, name + ".json"), data)
    run_dir = os.path.join(out_dir, "run")
    for f in os.listdir(run_dir) if os.path.isdir(run_dir) else []:
        old = read_json(os.path.join(run_dir, f), {}) if f.endswith(".json") else {}
        env = old.get("env") or {}
        if env.get("PANTHEON_WINDOW") != name:
            continue
        new = json.loads(json.dumps(data))
        new.setdefault("env", {}).update({k: env[k] for k in RUN_ENV if k in env})
        if new != old:
            write_json(os.path.join(run_dir, f), new)
    return True


def hq_project_dirs(domains, reg=None):
    """metis-0771: папки проектов направлений, закрытые окну hq (настоящие пути). Не закрыты metis-pantheon,
    направления с coordinator = false (их ведёт Пританей), папки в ~/ai или PANTHEON или содержащие их либо открытую
    папку (~/projects у направления закрыл бы agent-kit) и папки вне HOME или в скрытых. То же считает guard
    hq_project_roots — правило Read/Grep/Glob."""
    # Счёт — в hooks/ctx.py: тем же списком хук qmd-query закрывает штабу коллекции этих папок (metis-0778)
    return ctx_mod().hq_project_dirs(domains, list(hq_led(reg)), HOME, AI_HOME, PANTHEON)


def _allow_blocked(a, denies):
    """metis-0771: allowRead `a` открыл бы закрытое — запрет из `denies` закрывает `a` или папку выше либо лежит внутри
    `a`. Шаблоны (*, ?, [) — через fnmatch: его «*» шире, чем у песочницы, поэтому сомнение — в пользу запрета."""
    for x in denies:
        x = x[:-3] if x.endswith("/**") else x
        if any(c in x for c in "*?["):
            up = a
            while up not in ("/", ""):
                if fnmatch.fnmatchcase(up, x):
                    return True
                up = os.path.dirname(up)
            if fnmatch.fnmatchcase(x, a + "/*"):
                return True
        elif a == x or a.startswith(x.rstrip("/") + "/") or x.startswith(a + "/"):
            return True
    return False


def _under(p, top):
    """p — та же папка, что top, или внутри неё (оба — настоящие абсолютные пути)."""
    return p == top or p.startswith(top.rstrip("/") + "/")


def _deny_forms(paths):
    """Запрет и в виде «~/…», и настоящим путём: правила разрешений — настоящие пути, запреты должны совпасть."""
    out = []
    for p in paths:
        for x in (p, os.path.realpath(os.path.expanduser(p))):
            if x not in out:
                out.append(x)
    return out


# Строгий guard окна роли (SEC-29): тот же guard.py, но с --strict и onFailure "block" — сбой, таймаут, плохой вход
# или пропавший файл защиты останавливают действие, а не пропускают. Путь — только клон маркетплейса внутри
# ~/.claude/plugins (туда ролям писать нельзя: protect-config), а не «рядом с этим плагином»: рабочая копия
# agent-kit (AGENT_KIT_DIR) — папка metis-pantheon, её правят субагенты, и подменённый там guard стал бы защитой окон
# (находка проверки безопасности 14.10). Ваших сессий без роли это не касается. Agent|Task|Skill — правила
# hq-telegram и chiron (P0-1, P0-2): штабу — ни tg-reader, ни telegram-read; коуч с личным — только у Зевса.
GUARD_MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|Agent|Task|Skill"
MARKET_GUARD = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "hooks", "guard.py")


def _installed_hook(name, market_path):
    """Тот же файл хука из ПРОВЕРЕННОГО дерева плагина (installed_dir: хеш совпал с verified.json, metis-0321). Клон
    маркетплейса — никогда: plugins-update пересоздаёт его головой main сразу после слияния. Проверенного нет —
    несуществующий путь внутри кэша (ролям туда не записать): строгий guard окна с onFailure block не пропустит ни
    одного действия, sandbox_build поднимет тревогу guard-missing."""
    rel = os.path.relpath(market_path, os.path.join(HOME, ".claude", "plugins", "marketplaces", MARKETPLACE,
                                                    "plugins", name))
    d = installed_dir(name)
    if d:
        p = os.path.join(d, rel)
        if os.path.isfile(p) and not os.path.islink(p):
            return os.path.realpath(p)
    return os.path.join(HOME, ".claude", "plugins", "cache", MARKETPLACE, name, "нет-проверенного", rel)


def guard_script():
    return _installed_hook("guard", MARKET_GUARD)


def agents_script():
    return _installed_hook("pantheon", MARKET_AGENTS)


def hook_python_cmd(script, *args):
    """Команда хука окна на Python: через hooks/python.sh рядом со скриптом (Python 3.11+, metis-0571). Проверенное
    дерево старее запускателя (его нет рядом) — прежняя форма `python3 <скрипт>`: guard сам перезапустится на 3.11+."""
    tail = " ".join(shlex.quote(x) for x in (script, *args))
    launcher = os.path.join(os.path.dirname(script), "python.sh")
    if os.path.isfile(launcher):
        return f"/bin/sh {shlex.quote(launcher)} {tail}"
    return f"python3 {tail}"


def agents_window(data, allowed, deny, script):
    """Окну (P0-6): хук `agents.py <список>` для главной сессии и правила deny Agent(<тип>) на всё окно. Запись
    guard и прежние правила (Read у штаба) остаются; без дублей, порядок стабильный."""
    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append({"matcher": AGENT_MATCHER, "hooks": [{
        "type": "command", "command": hook_python_cmd(script, ','.join(uniq(allowed))),
        "timeout": 10, "onFailure": "block"}]})
    rules = data.setdefault("permissions", {}).setdefault("deny", [])
    rules.extend([r for r in uniq(f"Agent({x})" for x in deny) if r not in rules])
    return data


def role_settings(folders, own_dir, extra_write, cache, ssh, deny_read, compact=None, guard=None, auto_allow=None,
                  own_agents=False):
    allow = list(folders) + ([own_dir] if own_dir else []) + list(extra_write) + [cache]
    # .git/config и .git/hooks — внутри каждой разрешённой папки (её настоящим путём) и под ~ в целом
    # .claude/agents — роли агентов репозитория: guard protect-config закрывает запись хуком (guard 0.5.6, #26), но
    # Bash-запись мимо хука останавливает только песочница (metis-0140); и в worktree внутри репозитория тоже.
    # own_agents (metis-0841, «да» владельца 05.11 16:09): окно направления правит роли своего проекта — в папках
    # folders песочница .claude/agents не закрывает, их текст судит guard protect-config (ключи tools, hooks и т. п.)
    # папка демона хуков (HOOKD_DIR, metis-0845) — каждому окну: allowWrite выше неё (sandbox_write ~/.cache) её не
    # откроет, запрет сильнее разрешения (проверка F7 — hookd-check.py windows)
    agents = ("/.claude/agents", "/**/.claude/agents")
    deny_write = ["~/**/.git/config", "~/**/.git/hooks"] + [f"{r}{sub}" for r in allow for sub in (
        "/.git/config", "/.git/hooks", "/**/.git/config", "/**/.git/hooks") + (
        () if own_agents and r in folders else agents)]
    deny_write += _deny_forms([HOOKD_HOME])
    data = {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml и policy.toml (SEC-19). Руками не править.",
        "env": {
            "XDG_CACHE_HOME": os.path.join(cache, "xdg"),
            "npm_config_cache": os.path.join(cache, "npm"),
            "npm_config_devdir": os.path.join(cache, "node-gyp"),
            "COREPACK_HOME": os.path.join(cache, "corepack"),
            "UV_CACHE_DIR": os.path.join(cache, "uv"),
            "PIP_CACHE_DIR": os.path.join(cache, "pip"),
            "NEXT_TELEMETRY_DISABLED": "1",
            "TURBO_TELEMETRY_DISABLED": "1",
            "DO_NOT_TRACK": "1",
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": SANDBOX_EXCLUDED + (GIT_NETWORK if ssh else []),
            "filesystem": {
                "allowWrite": allow,
                "denyWrite": deny_write,
                "denyRead": _deny_forms(deny_read) + NOTIFIER_PATHS + _deny_forms([CDP_TOKEN_DIR]),
            },
            "network": {"allowedDomains": SANDBOX_DOMAINS},
        },
        # пароль демона CDP — и инструментам Read, Grep, Glob (песочница держит только Bash)
        "permissions": {"deny": [f"Read({x}/**)" if x.startswith("~") else f"Read(/{x}/**)"
                                 for x in _deny_forms([CDP_TOKEN_DIR.replace(HOME, "~", 1)])]},
    }
    if guard:
        data["hooks"] = {"PreToolUse": [{"matcher": GUARD_MATCHER, "hooks": [{
            "type": "command", "command": hook_python_cmd(guard, "--strict"), "timeout": 10,
            "onFailure": "block"}]}]}
    if compact:
        # координатор: окно сжатия 200k (CTX-04); фоновая сессия уходит в свою worktree, и worktree работников лида
        # ответвляются от неё (HEAD ветки эпика), а не от основной ветки (по умолчанию — "fresh")
        data["autoCompactWindow"] = compact
        data["worktree"] = {"baseRef": "head"}
    if auto_allow:
        # окна координаторов: исключения классификатора auto под шлюз слияния (coordinator_auto_allow, metis-0098)
        data["autoMode"] = WINDOW_RULES.auto_mode(auto_allow)
    return data


def _read_small_regular(p, limit=8 << 20):
    """Текст обычного файла не больше limit, иначе None. Папки проекта пишут роли, а читает тик вне песочницы:
    FIFO, устройство или ссылка вместо файла не должны его повесить, огромный файл — съесть память."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def memory_dirs():
    """Папки ~/.claude/agent-memory/<роль> ролей-субагентов с ключом memory: в шапке (metis-0051): их Bash-запись
    песочнице окна иначе недоступна. Настоящие пути; папку создаёт, ссылку вместо папки пропускает."""
    out = []
    try:
        names = sorted(os.listdir(AGENTS))
    except OSError:
        return out
    for f in names:
        role = f[:-3]
        if not f.endswith(".md") or not ROLE_NAME.fullmatch(role) or role in MAIN_ROLES:
            continue
        text = _read_small_regular(os.path.join(AGENTS, f))
        if text is None or "memory" not in (_head_keys(text) or []):
            continue
        d = _real_dir(f"~/.claude/agent-memory/{role}", ["~/.claude/agent-memory"], strict=True, create=True)
        if d:
            out.append(d)
    return out


def pnpm_store_check(name, folders, store):
    """node_modules на этом Mac собраны с другим хранилищем (store-dir в .npmrc не в git — на другой Mac не приезжает):
    pnpm в окне спросит, сносить ли node_modules, и без терминала молча ничего не поставит — тревога с командой."""
    for f in folders:
        try:
            subs = sorted(os.path.join(f, x) for x in os.listdir(f) if not x.startswith(".")
                          and stat.S_ISDIR(os.lstat(os.path.join(f, x)).st_mode))
        except OSError:
            subs = []
        for d in [f] + subs:
            text = _read_small_regular(os.path.join(d, "node_modules", ".modules.yaml"))
            if text is None:
                continue
            m = re.search(r"^storeDir:\s*(\S+)", text, re.M)
            got = os.path.realpath(m.group(1)) if m else ""
            if got and got != store and os.path.dirname(got) != store:
                alert_once(f"pnpm-store-{name}-{d}", got, f"{name}: {d.replace(HOME, '~')}/node_modules собраны с "
                           f"хранилищем {got.replace(HOME, '~')}, а у направления {store.replace(HOME, '~')} — pnpm в окне "
                           f"ничего не поставит. В {d.replace(HOME, '~')}: .npmrc со строкой store-dir={store} (в "
                           ".git/info/exclude), затем CI=true pnpm install --frozen-lockfile", "pantheon")


# [private] из policy.toml читается по правилу guard 0.5.9 (metis-0163): окно и guard не должны расходиться во мнении,
# у кого личное. Умолчание — то же, что DEFAULT_PRIVATE у guard.
DEFAULT_PRIVATE = {"roles": ["hq", "chiron"], "coordinators": ["mnemo-brain"],
                   "paths": ["~/ai/knowledge/me", "~/ai/knowledge/.git/git-crypt", "~/ai/pantheon/.git/git-crypt",
                             "~/.local/state/pantheon/owner-log/zeus.md"]}


def private_conf(policy):
    """[private]: не таблица — всё по умолчанию; ключа нет или значение не список — умолчание; список — только его
    строки (strip, пустые убраны). roles и coordinators: пустой список — никого; paths: пустой список или без строк —
    умолчание."""
    p = policy.get("private") if isinstance(policy, dict) else None
    if not isinstance(p, dict):
        p = {}
    conf = {}
    for k, v in DEFAULT_PRIVATE.items():
        val = p.get(k)
        if not isinstance(val, list):
            conf[k] = list(v)
            continue
        items = [x.strip() for x in val if isinstance(x, str) and x.strip()]
        conf[k] = items if items or k != "paths" else list(v)
    return conf


# Образцы команд слияния в обход шлюза слияния: правило allow, которому подходит любая из них, срабатывает раньше
# классификатора режима auto, и формы --admin и --auto классификатор не судит (metis-0137)
MERGE_SAMPLES = ("gh pr merge 12 --admin", "gh pr merge 12 --auto --merge")
MERGE_CMD = "gh pr merge"
PROJECT_SETTINGS_FILES = ("settings.json", "settings.local.json")


# Обёртки, запускающие любую команду: правило `env *` пускает и `env gh pr merge 12 --admin`. У оболочек обёртка —
# только `-c` (`bash ./run.sh *` — свой скрипт); флаги env с аргументом снимаются вместе с ним
WRAP_SHELLS = ("bash", "sh", "zsh")
ENV_ARG_FLAGS = ("-u", "-c", "-p")
ASSIGN_RX = r"[a-z_][a-z0-9_]*=\S*"


def unwrap_rule(inner):
    """(остаток, была ли обёртка): снимает с начала шаблона VAR=значение, путь к программе (`/x/y/gh` → `gh`) и
    обёртки env, command, xargs, eval, `bash|sh|zsh -c` с необязательной кавычкой. Остаток None — `command -v …`:
    поиск программы, а не запуск."""
    wrapped = False
    while True:
        words = inner.split(" ") if inner else []
        while len(words) > 1 and re.fullmatch(ASSIGN_RX, words[0]):
            words = words[1:]
        if not words:
            return "", wrapped
        prefix, slash, base = words[0].rpartition("/")
        if slash and base and not base.startswith("*") and "*" not in prefix:
            words[0] = base
        first, words = words[0], words[1:]
        if first == "env":  # VAR= после флагов снимет следующий проход цикла
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ENV_ARG_FLAGS else words[1:]
        elif first in ("command", "xargs"):
            while words and words[0].startswith("-"):
                if first == "command" and "v" in words[0]:
                    return None, True
                words = words[1:]
        elif first in WRAP_SHELLS:
            short = lambda w: w.startswith("-") and not w.startswith("--")  # noqa: E731
            while words and short(words[0]) and "c" not in words[0]:
                words = words[1:]
            if words and short(words[0]):
                words = words[1:]
            elif not (words and words[0].startswith("*")):  # не -c и не звёздочка на его месте — запуск скрипта
                return " ".join([first, *words]), wrapped
            if words and words[0][:1] in ("'", '"'):
                q, words[0] = words[0][0], words[0][1:]
                if words[-1].endswith(q):
                    words[-1] = words[-1][:-1]
                words = [w for w in words if w]
        elif first != "eval":
            return " ".join([first, *words]), wrapped
        wrapped = True
        inner = " ".join(words)


def allow_rule_merges(rule):
    """Пускает ли правило permissions.allow `gh pr merge`: "Bash", "Bash(*)", Bash(<шаблон>), где буквальное начало
    шаблона до первой звёздочки — начало «gh pr merge» или само начинается с «gh pr merge» (флаги в любом порядке,
    точная форма без звёздочки тоже), либо шаблон как glob подходит к одному из MERGE_SAMPLES. Пробелы схлопываются,
    регистр не важен, «:*» на конце — « *». Перед проверкой unwrap_rule снимает ведущие VAR=значение, путь к
    программе (`/opt/homebrew/bin/gh *` — это `gh *`) и обёртки, пускающие любую команду: env с флагами и VAR=,
    command, xargs с флагами, eval, `bash|sh|zsh -c`. Поэтому `env *`, `bash -c *`, `command /x/gh *` ловятся, а
    обёртка без звёздочки и без команды после неё (`env`, `command -v gh`) — нет. Не ловятся свои скрипты-обёртки
    (`./run.sh *`), sudo, nohup, timeout, `exec gh *`, `time gh *`, `nice gh *` и подобное: граница — песочница и
    guard (README)."""
    if not isinstance(rule, str):
        return False
    rule = rule.strip()
    if rule == "Bash":
        return True
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    inner = rule[5:-1].strip()
    if inner.endswith(":*"):
        inner = inner[:-2] + " *"
    inner = " ".join(inner.split()).lower()
    inner, wrapped = unwrap_rule(inner)
    if inner is None or (wrapped and not inner):
        return False
    head = inner.split("*", 1)[0]
    if MERGE_CMD.startswith(head) or head.startswith(MERGE_CMD):
        return True
    rx = ".*".join(re.escape(x) for x in inner.split("*"))
    return any(re.fullmatch(rx, smp) for smp in MERGE_SAMPLES)


def project_allow_problems(launch):
    """[(файл, правило)] — allow в .claude/settings.json и settings.local.json папки запуска, пускающие `gh pr merge`."""
    found = []
    for fn in PROJECT_SETTINGS_FILES:
        f = os.path.join(launch, ".claude", fn)
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        perms = data.get("permissions") if isinstance(data, dict) else None
        allow = perms.get("allow") if isinstance(perms, dict) else None
        for r in allow if isinstance(allow, list) else []:
            if allow_rule_merges(r):
                found.append((f, r))
    return found


def project_allow_text(name, problems):
    shown = lambda f: f.replace(HOME, "~", 1) if f.startswith(HOME + os.sep) else f  # noqa: E731
    return (f"направление {name}: " + "; ".join(f"{shown(f)} — allow «{r}» пускает gh pr merge" for f, r in problems)
            + " — правило срабатывает раньше классификатора auto и открывает слияние --admin/--auto мимо шлюза "
            "слияния: убрать правило или сузить его до нужных команд gh (gh pr view *, gh pr checks *…)")


def drop_window(name):
    """Убрать оба файла окна: settings/<имя>.json и файл запуска settings/run/<имя>.json — `claude respawn` берёт
    прежние флаги с путём к нему (ревью argus PR #32). Без файла окна не поднимают ни pantheon start, ни wake, ни
    дежурный."""
    for f in (path("settings", name + ".json"), path("settings", "run", name + ".json")):
        with contextlib.suppress(OSError):
            os.remove(f)


def allow_gate(name, folders=None):
    """Проектные allow папки запуска направления name (metis-0137): есть правило с gh pr merge — оба файла окна
    убираются. Зовут сборка, тик (check) и каждый подъём сессии: сборка по --if-changed сравнивает только mtime, а
    файл со старым mtime (cp -p, rsync -a, tar) её не запускает (ревью argus PR #32). folders — папки из domains.json;
    не направление (мастерская, штаб) — проверки нет. → список проблем."""
    if folders is None:
        folders = (read_json(path("domains.json"), {}).get("domains") or {}).get(name)
    problems = project_allow_problems(launch_folder(folders)) if folders else []
    if problems:
        drop_window(name)
    return problems


def project_allow_report(name, problems, quiet=True):
    """Проблемы папки запуска направления (allow_gate): тревога (quiet) или строка в stdout; без проблем тревога
    снимается. → список проблем."""
    key = "project-allow-" + name
    if problems:
        text = project_allow_text(name, problems)
        if quiet:
            alert_once(key, json.dumps(problems), text, "pantheon")
        else:
            print(f"предупреждение · {text}")
    else:
        clear_once(key)
    return problems


def project_allow_stop(name, problems):
    """Тик нашёл у направления allow с gh pr merge: Claude Code перечитывает настройки на ходу, и в работающем окне
    правило уже действует — живую сессию (и её копии «имя (2)») останавливаем claude stop, с тревогой. Окно уже
    убрано, поэтому поднять её снова не даст никто (pantheon start, wake, дежурный). Вкладку терминала claude stop не
    остановит — она в тревоге. → id остановленных."""
    live = live_copies(name, agents_all() or [])
    if not live:
        clear_once("project-allow-stop-" + name)
        return []
    ids = [a for a in live if a.get("id")]
    tabs = [a for a in live if not a.get("id")]
    stop_copies(name, ids, "stop-project-allow")
    text = (f"{name}: остановлена работающая сессия ({', '.join(a['id'] for a in ids) or '—'}) — "
            + project_allow_text(name, problems)
            + (f"; открыта во вкладке терминала (pid {', '.join(str(a.get('pid')) for a in tabs)}) — её закройте сами"
               if tabs else "")
            + ". Поднять снова — после правки и pantheon domains build")
    alert_once("project-allow-stop-" + name, ",".join(str(a.get("id") or a.get("pid")) for a in live), text, "pantheon")
    return [a["id"] for a in ids]


def sandbox_build(domains, policy_path, stores=None, leads=None, stop_live=False):
    """domains.json и policy.toml → ~/.local/state/pantheon/settings/<направление>.json и workshop.json.
    leads — {направление: ["hephaestus-<коротко>", "apollo-<коротко>"]}: субагенты окна (P0-6). stop_live — путь тика
    (domains build --if-changed): живую сессию направления с проблемой проектных allow остановить."""
    try:
        with open(policy_path, "rb") as fh:
            policy = tomllib.load(fh)
    except (OSError, ValueError):
        policy = {}
    grants_check()
    extra = policy.get("sandbox_write") or {}
    private = private_conf(policy)
    private_paths = [p for p in private["paths"] if p.startswith("~/")]
    private_dirs = set(private["coordinators"])
    caches = "~/Library/Caches/pantheon-sandbox"
    out_dir = path("settings")
    guard = guard_script()
    if not os.path.isfile(guard):
        alert_once("guard-missing", guard, f"нет {guard.replace(HOME, '~')}: окна ролей не пропустят ни одной записи "
                   "(строгий guard, SEC-29) — нет проверенного дерева guard или файла в нём: pantheon plugins accept guard "
                   "(README agent-kit, «Живой код»)", "pantheon")
    agents_py = agents_script()
    if not os.path.isfile(agents_py):
        alert_once("agents-missing", agents_py, f"нет {agents_py.replace(HOME, '~')}: окна Пританея и координаторов не позовут ни одного "
                   "субагента (хук agents.py, P0-6) — переустановить плагин pantheon", "pantheon")
    leads = leads or {}
    all_leads = [x for n in leads for x in leads[n]]
    os.makedirs(out_dir, exist_ok=True)

    memory = memory_dirs()
    pmap = plugin_map_load()
    # очередь обёртки heavy по порядку прихода (metis-0659): билет — файл в STATE/locks/heavy-queue, окно роли без
    # записи туда ждёт опросом мест. Запись — только в эту папку (не во весь locks: там замки прохода и Touch ID),
    # «да» владельца 02.11 в окне agent-kit-62. Ссылка на месте папки — не даём: иначе запись ушла бы по ссылке
    queue = path("locks", HEAVY_QUEUE)
    with contextlib.suppress(OSError):  # файл или висячая ссылка на месте папки — без записи, сборка окон идёт дальше
        os.makedirs(queue, mode=0o700, exist_ok=True)
    queue = os.path.realpath(queue) if os.path.isdir(queue) and not os.path.islink(queue) else None

    def one(name, folders, own, compact, deny, allow=None, agents=None, direction=False, auto_allow=None):
        if direction:
            # проектные allow папки запуска с gh pr merge (metis-0137): окно не собирается, оба прежних файла окна
            # убирает allow_gate
            problems = project_allow_report(name, allow_gate(name, folders))
            if problems:
                print(f"песочница {name}: окно не собрано — {project_allow_text(name, problems)}", file=sys.stderr)
                if stop_live:
                    project_allow_stop(name, problems)
                return False
        real = [_real_dir(f, SANDBOX_ROOTS[:SANDBOX_STRICT], strict=True) or _real_dir(f, SANDBOX_ROOTS[SANDBOX_STRICT:])
                for f in folders]
        skipped = [f for f, r in zip(folders, real) if not r]
        if skipped:
            print(f"песочница {name}: вне {', '.join(SANDBOX_ROOTS)}, ссылка или нет папки — только через Write/Edit: "
                  f"{skipped}", file=sys.stderr)
        own_real = os.path.realpath(own) if os.path.isdir(own) and not os.path.islink(own) else None
        write = [r for r in (_real_dir(p, ["~/.cache", "~/Library/Caches"], strict=True) for p in extra.get(name, [])) if r]
        hookd = [r for r in write if _under(r, os.path.realpath(HOOKD_DIR))]
        if hookd:  # папка демона хуков и всё в ней — никому (metis-0845); папка выше остаётся, её режет denyWrite
            print(f"песочница {name}: sandbox_write в папку демона хуков не даётся: {hookd}", file=sys.stderr)
            write = [r for r in write if r not in hookd]
        write += memory
        write += [queue] if queue else []  # в песочницу (Bash), не в правила Edit/Write
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        ok = [r for r in real if r]
        # сетевой git: окну направления — всегда, мастерской — при SSH-remote (P0-4, metis-0064)
        data = role_settings(ok, own_real, write, cache, direction or any(ssh_remote(r) for r in ok), deny, compact,
                             guard, auto_allow, own_agents=direction)
        if direction:
            data["sandbox"]["excludedCommands"] += GH_PR_WRITE
        if name == "metis-pantheon":
            # навык new-direction (metis-0042): `pantheon direction init` создаёт ~/projects/<новое> и ~/ai/life/<новое> — вне папок окна
            # Метиды, в песочнице упал бы. Мимо неё — только эта подкоманда и только у Метиды; ворота у команды свои:
            # галочка владельца в журнале доски owner-log, который пишет тик, — роли её не подделают.
            data["sandbox"]["excludedCommands"].append("pantheon direction init *")
            # заявка на слияние ядра по Touch ID (metis-0285) пишет в STATE/merge-queue — вне песочницы окна. Сливает
            # не она: `pantheon merge run` ролям закрыт guard, окно Touch ID показывает только плановый проход
            data["sandbox"]["excludedCommands"] += MERGE_REQUEST_CMDS
        # окна направлений и мастерская сами поднимают dev-сервер и гоняют тесты своего проекта ([sb-simplify] 27.10):
        # Unix-сокеты (tsx IPC, профиль Chromium) — только в своём кэше окна, не в $TMPDIR (/tmp/claude-<uid> общий у
        # всех сессий). Местных портов (allowLocalBinding) нет: он открывает весь localhost — и местный прокси (выход наружу
        # мимо allowedDomains), и 9222 браузера; проверено в бинарнике 2.1.311, ревью 27.10
        data["sandbox"]["network"]["allowUnixSockets"] = [cache]
        # TMPDIR песочница ставит свой (/tmp/claude-<uid>, env окна его не перебивает — проба 27.10): тесты с сокетами
        # запускают `TMPDIR=$PANTHEON_TMP …`
        os.makedirs(os.path.join(cache, "tmp"), exist_ok=True)
        data["env"]["PANTHEON_TMP"] = os.path.join(cache, "tmp")
        if allow:
            data.setdefault("permissions", {}).setdefault("allow", []).extend(allow)
        if agents:
            agents_window(data, agents[0], agents[1], agents_py)
        store = (stores or {}).get(name)
        if store:
            st = os.path.realpath(os.path.expanduser(store))
            if any(st.startswith(r.rstrip("/") + "/") for r in ok):
                data["env"]["npm_config_store_dir"] = st
                pnpm_store_check(name, ok, st)
            else:
                alert_once(f"pnpm-store-{name}", store, f"directions.toml: pnpm_store {store} направления {name} — вне "
                           "его папок, окно его не получит", "pantheon")
        if pmap:
            PLUGIN_MAP.window_apply(data, pmap, name, direction)
        write_window(out_dir, name, data)
        return True

    merge_repos = policy.get("merge_repos") if isinstance(policy.get("merge_repos"), dict) else {}
    built = []
    for name, folders in domains.items():
        mine = leads.get(name, [])
        # chiron видит личное (me/) — только Зевсу (P0-2); главные роли и чужие лиды не нужны и лидам окна
        # hestia — только своим окном (`pantheon wake hestia --task`), не субагентом (metis-0245)
        agents = (mine + COORDINATOR_AGENTS + COORDINATOR_EXTRA_AGENTS.get(name, []),
                  ["chiron", "hestia"] + list(MAIN_ROLES) + [x for x in all_leads if x not in mine])
        if one(name, folders, os.path.join(PANTHEON, "directions", name), COORDINATOR_COMPACT,
               [] if name in private_dirs else private_paths, COORDINATOR_ALLOW, agents, direction=True,
               # окну с доступом к личному правило слияния не выдаётся — его PR сливает владелец (metis-0156)
               auto_allow=coordinator_auto_allow([] if name in private_dirs else merge_repos.get(name))):
            built.append(name)
    # мастерская пишет в папку запуска (workshop_dir()/<задача>: ~/ai/workshop, до переноса старая в ~/projects) и в
    # workshop/ доски; список субагентов — вне P0-6
    one("workshop", [workshop_dir()], os.path.join(PANTHEON, "workshop"), None, private_paths)
    built.append("workshop")
    # окна задач расписания (P0-3, metis-0063): `claude -p --agent <роль>` тика (parse_command добавляет --settings).
    # Пишет только своё (JOB_ROLES), память ролей и свой кэш; личное закрыто на чтение и запись; сети Bash нет (веб у
    # prometheus и iris — инструменты WebFetch/WebSearch, не Bash); мимо песочницы — только `pantheon alert`. Строгий
    # guard — как у остальных окон. Кэш задачи в списке built — штаб его не читает (выдача из веба)
    try:
        known = sorted(f[:-3] for f in os.listdir(AGENTS) if f.endswith(".md") and ROLE_NAME.fullmatch(f[:-3]))
    except OSError:
        known = []
    for role, conf in JOB_ROLES.items():
        name = "job-" + role
        own = []
        for p in conf["write"]:
            if os.path.isdir(p) and not os.path.islink(p):
                own.append(os.path.realpath(p))
            else:
                print(f"песочница {name}: нет папки или ссылка — Bash туда не пишет: {p.replace(HOME, '~')}",
                      file=sys.stderr)
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        job = role_settings(own, None, memory, cache, False, private_paths, None, guard)
        job["sandbox"]["excludedCommands"] = list(JOB_EXCLUDED)
        job["sandbox"]["network"]["allowedDomains"] = []
        job["sandbox"]["filesystem"]["denyWrite"] += _deny_forms(private_paths)
        job["env"]["PANTHEON_ROLE"] = role  # хукам: роль окна, как у штаба
        # субагенты (P0-6): главная сессия задачи зовёт только своих (хук agents.py); deny — все известные типы,
        # кроме своих: встроенные, роли из ~/.claude/agents, лиды реестра и главные роли
        mine = list(conf.get("agents") or [])
        agents_window(job, mine or [JOB_NO_AGENTS],
                      [x for x in BUILTIN_AGENTS + known + all_leads + list(MAIN_ROLES) if x not in mine], agents_py)
        if pmap:
            PLUGIN_MAP.window_apply(job, pmap, name)
        write_window(out_dir, name, job)
        built.append(name)
    # окно Гестии (metis-0245, решение владельца «А» 18.10): служебная роль ставит слитые выпуски и пересобирает и
    # перезапускает окна. Bash пишет только в TMPDIR (кэш — папка запуска, запись в него guard не пускает); ни одной папки проекта, памяти
    # ролей и ~/.claude — запись туда только командами пульта мимо песочницы (HESTIA_EXCLUDED), а не руками. Личное
    # закрыто на чтение (Bash — песочницей, Read и Grep — правилами deny); сети у Bash нет (выпуск качает `pantheon plugins update` вне песочницы); файловых правок и веба
    # нет. Субагентов не зовёт. Что ей можно в Bash сверх этого, решает guard по PANTHEON_ROLE=hestia (правило hestia)
    hs_cache = _real_dir(f"{caches}/hestia", [caches], strict=True, create=True)
    hs = role_settings([], None, [], hs_cache, False, private_paths, None, guard)
    hs["sandbox"]["excludedCommands"] = list(HESTIA_EXCLUDED)
    hs["sandbox"]["network"]["allowedDomains"] = []  # сети у песочницы нет; наружу — только excludedCommands + guard
    hs["sandbox"]["filesystem"]["denyWrite"] += _deny_forms(private_paths)
    hs.setdefault("permissions", {}).setdefault("deny", []).extend(HESTIA_DENY_TOOLS)
    # denyRead песочницы держит только Bash; Read и Grep её не проходят, а главная сессия окна приходит без agent_type
    # и guard личное не судит — поэтому те же личные пути закрываются правилами Read(...) и Grep(...) (как у hq)
    hs_rule = lambda tool, x: f"{tool}({x})" if x.startswith("~") else f"{tool}(/{x})"  # noqa: E731
    hs["permissions"]["deny"].extend(hs_rule(t, x + "/**") for t in ("Read", "Grep") for x in _deny_forms(private_paths))
    hs["permissions"]["deny"].extend(hs_rule(t, x) for t in ("Read", "Grep") for x in _deny_forms(private_paths))
    hs["env"]["PANTHEON_ROLE"] = "hestia"
    agents_window(hs, [JOB_NO_AGENTS], BUILTIN_AGENTS + known + all_leads + list(MAIN_ROLES), agents_py)
    if pmap:
        PLUGIN_MAP.window_apply(hs, pmap, "hestia")
    write_window(out_dir, "hestia", hs)
    built.append("hestia")
    # что закрыто штабу — [hq] policy.toml. Битый раздел — ошибка, а не «пусто»: окно Пританея не пересобираем, остаётся
    # прежнее (его файл не удаляется), и тревога — пока раздел не исправят
    try:
        hq_pol = ctx_mod().hq_policy(policy_path)
    except ValueError as e:
        alert_once("hq-policy-broken", str(e), f"policy.toml: {e} — окно Пританея не пересобрано, действует прежнее; "
                   "исправить раздел [hq] (Метида)", "pantheon")
        built.append("hq")
        for f in os.listdir(out_dir):
            if f.endswith(".json") and f[:-5] not in built:
                os.remove(os.path.join(out_dir, f))
        return built
    clear_once("hq-policy-broken")
    # штаб (SEC-26, вариант А): Зевс пишет только в ~/ai/pantheon, кроме .git и alerts.md; сеть закрыта (в веб он не
    # ходит, SEC-13); мимо песочницы — только `pantheon start|wake|alert`: запуск сессий и тревоги, и gh PR (HQ_GH).
    # Личное ему открыто (SEC-11), кроме ключей git-crypt.
    hq_cache = _real_dir(f"{caches}/hq", [caches], strict=True, create=True)
    root = os.path.realpath(PANTHEON)
    keys = [p for p in private_paths if "/.git/git-crypt" in p + "/"]  # ключи — не штабу: ~/ai/pantheon коммитит тик
    hq = role_settings([root], None, memory, hq_cache, False, keys, None, guard)
    hq["sandbox"]["excludedCommands"] = list(HQ_EXCLUDED) + HQ_GH
    hq["sandbox"]["filesystem"]["denyWrite"] += [os.path.join(root, ".git"), os.path.join(root, "alerts.md")]
    # [sb-simplify] п. 5 (metis-0523): замки имён сессий и метки сброса самозапуска — в STATE/hq-rw/{locks,autostart-reset}:
    # без них `pantheon stop|resume|wake|start` из его окна падали с PermissionError (15.10–27.10). Замки прохода
    # (STATE/locks), журналы ваших слов, метки «остановлено вами» и остальное состояние — по-прежнему нет
    hq["sandbox"]["filesystem"]["allowWrite"] += hq_state_dirs()
    hq["sandbox"]["network"]["allowedDomains"] = []
    # корпус лекций — чужой контент (SEC-13, metis-0025): у Зевса уже есть личное и действия наружу, поэтому корпус ему
    # закрыт (решение владельца 15.10) — guard corpus-role (команда corpus), хук qmd-query (поиск), а здесь — чтение
    # файлов: Read (Claude Code применяет его и к Grep, Glob) и cat/grep в песочнице
    # и временные файлы других ролей (их TMPDIR и кэши — песочные папки окон, в том числе брошенные после
    # переименования роли): у Фемиды там выдача корпуса
    cache_dirs = set(built)
    with contextlib.suppress(OSError):
        cache_dirs |= {n for n in os.listdir(os.path.expanduser(caches)) if n != "hq"}
    closed = hq_pol["closed_dirs"] + [f"{caches}/{n}" for n in sorted(cache_dirs)]
    # переписка сессий (координаторы зовут corpus search — выдача оседает в *.jsonl), большие выводы (tool-results) и
    # выводы фоновых задач и TMPDIR (CLAUDE_TMP) всех сессий, кроме своих. Своё — папка штаба и его worktree (имя как
    # у Claude Code: всё, кроме букв и цифр, → «-»); открыты свои выводы, автопамять (memory/*.md) и задачи штаба.
    # Не перечислением папок (15.10 их было 4121 — мусор тестов, профиль Seatbelt вырос за 64 КБ и Bash штаба не
    # запускался), а постоянным числом записей:
    # - шаблоны по префиксам, которые расходятся со своим именем (_others_globs): их число не растёт с числом папок.
    #   Одни и те же записи — правилом Read (инструменты Read, Grep, Glob) и в denyRead песочницы (Claude Code и так
    #   вливает правила Read в песочницу);
    # - закрыто содержимое чужих папок CLAUDE_TMP («<префикс>*/*» и «<префикс>*/*/**»), а не сами имена: CLAUDE_TMP —
    #   и общий $TMPDIR песочницы, в его корне лежат временные файлы Bash (heredoc zsh — $TMPPREFIX, mktemp, tempfile).
    #   Шаблон «<префикс>*» закрыл бы и их, а Claude Code срезает хвост «/**» и запрет-шаблон закрывает всё поддерево.
    #   Имена на «tmp» не закрываются: это временные папки самого штаба (mktemp -d — tmp.XXXX, tempfile — tmpXXXX),
    #   новая закрылась бы с момента создания. Цена — чужие tmp*-папки открыты (в 0.11.16 так же до пересборки);
    #   Корень открыт, как было до 0.11.17; allowRead не нужен (разрешение-шаблон в Seatbelt — точное имя, без поддерева)
    dash = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)  # noqa: E731
    own, home_d = dash(os.path.realpath(PANTHEON)), dash(os.path.realpath(HOME))
    tasks, projects = CLAUDE_TMP, os.path.join(HOME, ".claude", "projects")
    files = ["~/.claude/projects/**/*.jsonl", f"~/.claude/projects/{home_d}-projects-*/**/tool-results/**",
             f"{tasks}/{home_d}-projects-*/*", f"{tasks}/{home_d}-projects-*/*/**"]
    for base, short, tails, keep in ((projects, "~/.claude/projects", ("/**/tool-results/**",), ()),
                                     (tasks, tasks, ("/*", "/*/**"), ("tmp",))):
        try:
            names = os.listdir(base)
        except OSError:
            names = []
        globs, skipped = _others_globs(names, own, keep)
        files += [f"{short}/{g}{tail}" for g in globs for tail in tails]
        if skipped:
            print(f"песочница hq: имена с символами шаблона в {short} не закрыты: {skipped[:5]}",
                  file=sys.stderr)
    fsys = hq["sandbox"]["filesystem"]
    fsys["denyRead"] += _deny_forms(closed) + _deny_forms(files)
    # metis-0771: папки проектов направлений — работа их координаторов. Закрыто содержимое («P/*», «P/*/**»), а не сама
    # папка: `git -C P log` идёт. Открыты .git, README.md и AGENTS.md в корне (allowRead сильнее denyRead) — только если
    # ни один прежний запрет чтения (closed_dirs, личное, ключ в .git/config) не лежит внутри них и не закрывает их или
    # папку выше: иначе allowRead открыл бы закрытое. Read/Grep/Glob — guard hq-projects (правило Read исключений не
    # знает: deny сильнее allow). Модель угроз — drafts/0771-threat-model.md
    proj = hq_project_dirs(domains)
    deny_real = [os.path.realpath(os.path.expanduser(x)) for x in fsys["denyRead"]]
    fsys["denyRead"] += [p + tail for p in proj for tail in ("/*", "/*/**")]
    allow = [a for p in proj for a in (p + "/.git", p + "/README.md", p + "/AGENTS.md") if not _allow_blocked(a, deny_real)]
    if allow:
        fsys.setdefault("allowRead", []).extend(allow)
    rule = lambda x: f"Read({x})" if x.startswith("~") else f"Read(/{x})"  # noqa: E731 — «//» — абсолютный путь
    hq.setdefault("permissions", {}).setdefault("deny", []).extend(
        [rule(x + "/**") for x in _deny_forms(closed)] + [rule(x) for x in _deny_forms(files)])
    # P0-6: код — поручение направлению, а не лид в окне штаба; Гестия — своим окном (`pantheon wake hestia --task`)
    agents_window(hq, HQ_AGENTS, all_leads + list(MAIN_ROLES) + ["hestia"], agents_py)
    hq["env"]["PANTHEON_ROLE"] = "hq"  # хукам: в событиях фоновой сессии agent_type нет (15.10)
    if pmap:
        PLUGIN_MAP.window_apply(hq, pmap, "hq")
    write_window(out_dir, "hq", hq)
    built.append("hq")
    for f in os.listdir(out_dir):
        if f.endswith(".json") and f[:-5] not in built:
            os.remove(os.path.join(out_dir, f))
    return built


# --- запуск сессий (SEC-26, COMM-10, ROLE-01, ROLE-02) -----------------------------------
# Сессии Пантеона запускает только `pantheon start`: флаги — здесь, в коде, а не в файлах, которые пишет Зевс; настройки
# окна — из ~/.local/state/pantheon/settings/ (собирает `pantheon domains build`, Зевсу и ролям туда не записать). Флагов
# обхода разрешений нет и не будет. Поручение идёт позиционным аргументом и начинается с пометки «[Пантеон: …]»: хук
# журнала ваших слов (ctx.py owner-log) такую строку не пишет, а ваш первый ответ сессии — пишет. Та же пометка — у
# сообщения `pantheon wake`. Сессии с пометкой «остановлено вами» (~/.local/state/pantheon/stopped/<имя>, ставит
# `pantheon stop`, шаг 1.4) не будит никто.
# команды пульта штаба, которые пишут вне ~/ai/pantheon (alerts.md, ~/.local/state/pantheon) или запускают сессии со
# своей песочницей; guard проверяет их и здесь (pantheon-acl)
HQ_EXCLUDED = ["pantheon alert *", "pantheon start *", "pantheon wake", "pantheon wake *", "pantheon archive",
               "pantheon jobs *", "pantheon domains build", "pantheon roles build", "pantheon stop *",
               "pantheon resume *", "pantheon pause *", "pantheon restart *", "pantheon saved *", "pantheon who",
               "pantheon agents", "sessync find", "sessync find *", "pantheon qmd where *"]
# `pantheon qmd where` (metis-0856, «да» владельца 05.11 19:47): поиск «где лежит» по коллекциям проектов идёт по HTTP
# в местную службу qmd (127.0.0.1, порт из qmd.toml), а у песочницы штаба сети нет — поэтому мимо песочницы. Команда
# печатает только коллекцию, путь, заголовок и хозяина, без текста; закрытые [hq].closed_collections не отдаёт.
# `sessync find` (metis-0566, решение владельца 27.10): поиск прошлых разговоров читает транскрипты ~/.claude/projects, а
# окну штаба они закрыты — поэтому только эта команда и только здесь, мимо песочницы; вывод проходит маску ключей в самом
# sessync, а --raw и --no-mask отказывает guard (hq-sessync). Другим окнам команды нет: в их песочнице она не читает.
START_MARK = "[Пантеон:"
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def workshop_root():
    """Папка мастерской по факту на диске (вариант А, 06.11 18:06): ~/ai/workshop, если она есть и не ссылка, иначе
    старая папка workshop в ~/projects — до переноса окна и задачи мастерской остаются там. Правило здесь, а не в
    lib/moved.py: по нему sandbox_build (ядро) открывает запись окну workshop, а moved.py вне ядра (argus-4 Б1). Копии —
    moved.workshop_root и ctx.workshop_root; совпадение трёх держит test_workshop_sockets."""
    new = os.path.join(HOME, "ai", "workshop")
    return new if os.path.isdir(new) and not os.path.islink(new) else os.path.join(HOME, "projects", "workshop")


def workshop_dir():
    """workshop_root() в виде «~/…» — для песочницы, текста роли и сообщений."""
    root = workshop_root()
    return "~" + root[len(HOME):] if root.startswith(HOME + "/") else root


def claude_bin():
    import shutil
    return shutil.which("claude") or os.path.join(HOME, ".local", "bin", "claude")


def agents_all():
    r = subprocess.run([claude_bin(), "agents", "--json", "--all"], env=claude_env(), capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    data = data if isinstance(data, list) else data.get("agents") if isinstance(data, dict) else None
    return reconcile_agents(data) if isinstance(data, list) else data


ROSTER_WORKER_FIELDS = ("pid", "startedAt")  # из записи воркера; ключи сокетов (rvAuth, ptyAuth …) — нет


def roster_safe():
    """Реестр демона Claude Code ~/.claude/daemon/roster.json без ключей (metis-0871): {"updatedAt": …, "workers":
    {короткий id: {"pid": …, "startedAt": …}}}. В записях воркеров лежат ключи локальных сокетов демона (rvAuth,
    ptyAuth): их не берём — только поля из ROSTER_WORKER_FIELDS и только числа и строки. Это единственное место, где
    Пантеон читает файл; агентам guard его целиком не даёт (правило daemon-roster), нужные поля — `pantheon roster`.
    None — реестра нет или он не объект; workers None — поле не объект (о процессах тогда ничего не утверждаем)."""
    d = read_json(os.path.join(HOME, ".claude", "daemon", "roster.json"), False)  # нет или битый — False, не {}
    if not isinstance(d, dict):
        return None

    def scalar(v):
        return v if isinstance(v, (int, float, str)) and not isinstance(v, bool) else None
    w = d.get("workers")
    workers = {str(k): {f: scalar(v.get(f)) for f in ROSTER_WORKER_FIELDS} for k, v in w.items()
               if isinstance(v, dict)} if isinstance(w, dict) else None
    return {"updatedAt": scalar(d.get("updatedAt")), "workers": workers}


def roster_cmd(rest):
    """pantheon roster — реестр демона без ключей (roster_safe) одним JSON в stdout. Реестра нет или он не читается —
    причина последней строкой в stderr, код 1."""
    if rest:
        print("pantheon roster: аргументов нет — печатает updatedAt и у каждого воркера id, pid, startedAt",
              file=sys.stderr)
        return 2
    r = roster_safe()
    if r is None:
        print("pantheon roster: реестра демона нет или он не читается (~/.claude/daemon/roster.json)", file=sys.stderr)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def daemon_workers():
    """Процессы фоновых сессий из реестра демона Claude Code: короткий id → pid (roster_safe — без ключей). None —
    реестра нет или он не читается: тогда о процессах ничего не утверждаем."""
    r = roster_safe()
    if r is None or r["workers"] is None:
        return None
    return {k: w["pid"] for k, w in r["workers"].items()}


def roster_changed_at():
    """Когда демон последний раз переписал реестр (updatedAt roster.json, мс → с) или None. Демон пишет его при смене
    воркеров (старт, respawn, самоперезапуск), а не по таймеру: свежая правка — процесс мог только что смениться."""
    r = roster_safe()
    try:
        return float(r["updatedAt"]) / 1000
    except (TypeError, ValueError):
        return None


def session_started(a, t=None):
    """Когда нынешний процесс взял сессию a, в с, или 0 (metis-0864, ревью argus #332 Д2). claude agents пишет startedAt
    из записи реестра имён ~/.claude/sessions, пока процесс виден, а без него — createdAt задания (05.11: hermes-alex
    7c48114d без процесса — startedAt = createdAt state.json; zeus 7853263b с процессом после respawn — время respawn,
    а createdAt — 04.11). Пока новый процесс не виден (между снятием старого воркера и выдачей нового, metis-0662; из
    окна с песочницей, reconcile_agents (1)), startedAt старше прошлых перезапусков. Поэтому — самое позднее из
    startedAt записи, startedAt воркера этой сессии в реестре демона (roster.json: время выдачи процесса, respawn тоже)
    и записи реестра имён с её jobId или sessionId. Позже нынешнего процесса там времени нет: каждую из этих записей
    пишет выдача процесса этой сессии, старая запись — раньше. Реестр демона — через roster_safe: ключи сокетов не
    читаются (metis-0871). Значения не конечные (nan, inf: startedAt 1e400 читается как inf) и позже t (по умолчанию
    now()) отбрасываются (ревью argus #337)."""
    t = now() if t is None else t

    def ms(v):
        try:
            x = float(v) / 1000
        except (TypeError, ValueError):
            return 0.0
        return x if math.isfinite(x) and x <= t else 0.0
    best = ms(a.get("startedAt"))
    short, sid = str(a.get("id") or ""), a.get("sessionId")
    w = (roster_safe() or {}).get("workers") or {}
    if short and short in w:
        best = max(best, ms(w[short]["startedAt"]))
    sd = os.path.join(HOME, ".claude", "sessions")
    with contextlib.suppress(OSError):
        for f in os.listdir(sd):
            if not re.fullmatch(r"\d+\.json", f):
                continue
            rec = read_json(os.path.join(sd, f), {})
            if isinstance(rec, dict) and ((sid and rec.get("sessionId") == sid)
                                          or (short and str(rec.get("jobId") or "") == short)):
                best = max(best, ms(rec.get("startedAt")))
    return best


def claude_job_state(short):
    """state.json задания ~/.claude/jobs/<короткий id>/state.json (его пишет Claude Code, мы только читаем)."""
    if not re.fullmatch(r"[0-9a-zA-Z-]{4,64}", str(short or "")):
        return {}
    d = read_json(os.path.join(HOME, ".claude", "jobs", str(short), "state.json"), {})
    return d if isinstance(d, dict) else {}


def reconcile_agents(data, workers=None):
    """Сверка `claude agents --json --all` с заданием (jobs/<id>/state.json) и процессом (реестр демона), metis-0250.
    (1) Из окна с песочницей `claude agents` не видит живой процесс (kill(pid, 0) там — EPERM) и пишет живую сессию
    «failed» без pid (19.10: zeus и metis-pantheon «упали», а state.json — working). Процесс из реестра демона жив,
    задание working/blocked — берём состояние задания, pid — из реестра; прежнее состояние — в listedState.
    (2) Обратный случай: «blocked» без процесса и без вопроса (needs в state.json) — сессию снял Claude Code, ждать
    ей нечего (18.10, координатор без процесса весь день «ждёт вас»): noProcess. С вопросом — по-прежнему ждёт вас:
    ответ дойдёт через claude attach, он поднимет процесс.
    (2а) Призрак (metis-0651): working/blocked без живого процесса вообще (ни pid записи, ни реестра) — state
    становится failed, ghost=True: имя не держит, wake поднимает. Запись моложе минуты (или без startedAt) — не
    призрак: новая сессия могла ещё не попасть в реестр демона. pantheon start: призрак с вопросом (был blocked) —
    по-прежнему «ждёт вас», без вопроса — мёртвая (noProcess), заменяется новой. metis-0662: время берётся и из
    реестра демона — правлен меньше минуты назад (respawn: запись claude agents хранит старый startedAt, а процесс
    между снятием старого воркера и выдачей нового в реестре не виден) — не призрак; живой процесс этой сессии в
    реестре имён ~/.claude/sessions — тоже не призрак и не noProcess: после перезапуска демона живой воркер может
    выпасть из roster. Своя запись реестра — с jobId, равным id записи claude agents (у фоновой sessionId в реестре
    бывает другим), или с тем же sessionId, и только если её процесс тот самый (reg_same_process). Тёзка по имени —
    другая сессия, жизни этой записи не доказывает (ревью argus #249).
    (3) Причина для сводки: нет waitingFor — needs задания (blocked) или detail (failed)."""
    workers = daemon_workers() if workers is None else workers
    roster_at = roster_changed_at() if workers is not None else None
    reg = None  # реестр имён читается, только если нашлась сессия без процесса в roster
    for a in data:
        if not isinstance(a, dict) or a.get("kind") not in (None, "background") or not a.get("id"):
            continue
        js = claude_job_state(a["id"])
        wpid = (workers or {}).get(str(a["id"]))
        alive = bool(wpid) and pid_alive(wpid)
        if not alive and workers is not None and a.get("state") in ("working", "blocked"):
            reg = sessions_registry() if reg is None else reg
            mine = [reg_same_process(r) for r in reg
                    if (a.get("sessionId") and r.get("sessionId") == a.get("sessionId"))
                    or str(r.get("jobId") or "") == str(a["id"])]
            in_reg = any(m is not False for m in mine)  # None — ps недоступен: «не знаю» тоже не призрак (metis-0690)
        else:
            in_reg = False
        if alive and not a.get("pid"):
            a["pid"] = wpid
        if a.get("state") == "failed" and alive and js.get("state") in ("working", "blocked"):
            a["listedState"], a["state"] = "failed", js["state"]
        if (a.get("state") == "blocked" and workers is not None and not alive and not a.get("pid")
                and js and not js.get("needs") and not in_reg):
            a["noProcess"] = True
        # metis-0651: working/blocked без живого процесса — ни у записи, ни в реестре демона — призрак: процесс умер, а
        # строка осталась (02.11 metis-pantheon лежало 1,5 ч: wake отвечал «есть процесс»). Считается упавшей: имя не
        # держит, wake продолжает её же сессию. Реестр не читается — не утверждаем (workers None); из песочницы живой
        # процесс даёт EPERM, а это «жив» (pid_alive).
        if (a.get("state") in ("working", "blocked") and workers is not None and not alive
                and not (a.get("pid") and pid_alive(a["pid"]))  # pid 0: kill(0, 0) — своя группа, не доказательство
                and not in_reg and not just_listed(a, since=roster_at)):
            # вопрос — needs задания или исходный waitingFor claude agents, а не detail (он в state.json есть всегда:
            # ниже он ляжет в waitingFor упавшей); noProcess вопроса не имеет по определению (ревью argus-249a Б1)
            if a["state"] == "blocked" and not a.get("noProcess") and (a.get("waitingFor") or js.get("needs")):
                a["asks"] = True
            if a["state"] == "blocked" and not a.get("waitingFor") and js.get("needs"):
                a["waitingFor"] = " ".join(str(js["needs"]).split())[:200]  # вопрос владельцу остаётся виден
            a["listedState"], a["state"], a["ghost"] = a["state"], "failed", True
        if not a.get("waitingFor"):
            why = js.get("needs") if a.get("state") == "blocked" else js.get("detail") if a.get("state") == "failed" else None
            if why:
                a["waitingFor"] = " ".join(str(why).split())[:200]
    return data


def just_listed(a, grace=60, since=None):
    """Запись claude agents моложе grace секунд (startedAt в мс) или без даты: процесс мог ещё не попасть в реестр
    демона (новая сессия после pantheon start) — призраком её не считаем (metis-0651). since — время правки реестра
    демона в с (roster_changed_at, metis-0662): моложе grace — тоже «только что»; из будущего (часы, битая запись)
    не учитывается, иначе призрак не нашёлся бы никогда."""
    try:
        t = float(a.get("startedAt")) / 1000
    except (TypeError, ValueError):
        return True
    if since and since > now() + 300:
        since = None
    return now() - max(t, since or 0) < grace


def asks_owner(a):
    """Призрак с вопросом владельцу (metis-0651, 0662): процесс умер, а вопрос остался. Поднимает его ответ владельца
    (claude attach), а не wake и не самозапуск — как отказ pantheon start. Флаг asks ставит reconcile_agents: был
    blocked, не noProcess, есть needs задания или waitingFor из claude agents (detail вопросом не считается)."""
    return bool(a.get("ghost") and a.get("asks"))


def pid_alive(pid):
    try:
        if int(pid) <= 0:  # 0 и минус — группа процессов, а не процесс: kill их «находит» всегда (ревью argus #249)
            return False
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError) as e:
        return isinstance(e, PermissionError)
    return True


def sessions_registry():
    """Реестр имён Claude Code ~/.claude/sessions/<pid>.json: в нём и интерактивные вкладки, которых нет в
    `claude agents --json` (15.10 имя zeus держал забытый процесс вкладки). Только записи с живым процессом; ключи
    жетонов не читаются."""
    out, d = [], os.path.join(HOME, ".claude", "sessions")
    with contextlib.suppress(OSError):
        for f in os.listdir(d):
            if not re.fullmatch(r"\d+\.json", f):
                continue
            rec = read_json(os.path.join(d, f), {})
            if not isinstance(rec, dict) or not pid_alive(rec.get("pid")):
                continue
            out.append({"name": rec.get("name"), "sessionId": rec.get("sessionId"), "pid": rec.get("pid"),
                        "kind": "interactive" if rec.get("kind") == "interactive" else "background",
                        "cwd": rec.get("cwd"), "registry": True, "procStart": rec.get("procStart"), "file": f,
                        "jobId": rec.get("jobId")})
    return out


def proc_started(pid):
    """Время старта процесса по ps (lstart — в том же виде пишет procStart реестр имён Claude Code) или None: ps не
    запустился (в песочнице окна setuid-ps не идёт) или процесса нет."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    return " ".join(r.stdout.split()) or None


def reg_same_process(r):
    """Запись реестра имён написал тот процесс, что сейчас живёт под её pid: файл назван этим pid, а время старта
    процесса совпало с procStart записи. Устаревшая запись умершей сессии, чей pid занял другой процесс, жизнь не
    доказывает (ревью argus #249 Д1). procStart в записи нет — сверять нечего, запись принимается (True). ps недоступен
    (в песочнице окна он не идёт, metis-0679) при procStart в записи — третье состояние None, «не знаю» (metis-0690):
    жизнь не доказана, но и призрака утверждать нельзя — ложный призрак хуже задержки (pantheon start из окна
    остановил бы живого воркера). Решает tick из launchd, где ps есть. ps ответил и время чужое — False."""
    if str(r.get("file")) != f"{r.get('pid')}.json":
        return False
    want = " ".join(str(r.get("procStart") or "").split())
    if not want:
        return True
    got = proc_started(r.get("pid"))
    return None if got is None else got == want


def name_alias(name):
    """Имя и копии, которым Claude Code дал другое имя, потому что это было занято: «имя (2)», «имя-два-слова»."""
    return re.compile(re.escape(name) + r"(?: \(\d+\)|-[a-z]+-[a-z]+)?")


def live_copies(name, agents, registry=None):
    """Живые сессии с этим именем и его копии: работает (working), ждёт (blocked), открыта во вкладке (нет state) —
    плюс интерактивные вкладки из реестра ~/.claude/sessions, которых нет в claude agents. Сюда не входят остановленная
    (stopped — так claude agents пишет после claude stop, 15.10, metis-0041), упавшая (failed) и закончившая ход (done:
    с живым процессом её новый запуск останавливает сам, CTX-10). Имя держит не запись в claude agents, а живой процесс
    в реестре: пока остановленная копия не вышла, имя ещё занято — это ждёт wait_name_free."""
    alias = name_alias(name)
    out = [a for a in agents or [] if alias.fullmatch(str(a.get("name") or ""))
           and a.get("state") not in ("done", "stopped", "failed")]
    known = {a.get("sessionId") for a in agents or []}
    for r in sessions_registry() if registry is None else registry:
        if r.get("kind") == "interactive" and r.get("sessionId") not in known and alias.fullmatch(str(r.get("name") or "")):
            out.append({k: v for k, v in r.items() if k not in ("registry", "procStart", "file", "jobId")})
    return out


def maintenance_active():
    """Метка технического перезапуска (SCHED-15), если она стоит и не истекла: пока она есть, дежурный и
    pantheon wake никого не будят."""
    m = read_json(path("maintenance.json"), None)
    if not isinstance(m, dict) or not m:
        return None
    if now() > float(m.get("expires") or 0):
        return None
    return m


RUN_ENV = ("PANTHEON_ORIGIN", "PANTHEON_SESSION", "PANTHEON_ROLE", "PANTHEON_WINDOW", "PANTHEON_TASK",
           "PANTHEON_TASK_DIRECTION")


def run_settings(name, role, window, origin, extra_env=None):
    """Окно этого запуска: настройки окна + PANTHEON_ORIGIN (кто запустил), имя и роль — переменные сессии и её
    хуков. → путь файла или None (окна нет: pantheon domains build)."""
    win = path("settings", window + ".json")
    if not os.path.isfile(win):
        return None
    data = read_json(win, {})
    data.setdefault("env", {})["PANTHEON_ORIGIN"] = origin
    data["env"]["PANTHEON_SESSION"] = name
    data["env"]["PANTHEON_ROLE"] = role
    data["env"]["PANTHEON_WINDOW"] = window  # по нему сборка обновляет файл запущенной сессии (write_window)
    data["env"].update(extra_env or {})  # wake hestia: PANTHEON_TASK, PANTHEON_TASK_DIRECTION — задача окна (metis-0562)
    run = path("settings", "run", name + ".json")
    write_json(run, data)
    return run


COPY_NOTE = re.compile(r"started a copy as ([0-9a-f]{8})")


def push_text(session_id, text):
    """Текст, который хук ctx.py push отдаст сессии при следующем старте её процесса (SessionStart + asyncRewake):
    `claude respawn` сам хода не начинает, а команды «сказать фоновой сессии» у Claude Code нет (проверено 15.10)."""
    if not re.fullmatch(r"[0-9a-f-]{8,64}", str(session_id or "")) or not str(text).startswith(START_MARK):
        return None
    os.makedirs(path("push"), mode=0o700, exist_ok=True)
    p = path("push", session_id + ".txt")
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(str(text)[:4000])
    os.replace(p + ".tmp", p)
    return p


# Код отказа «нет окна»: сессию направления или мастерской без файла окна не поднимаем ни respawn, ни --resume, ни
# свежим стартом — без --settings она ушла бы без песочницы окна (ревью argus PR #32). Тревога — одна на причину
# (alert_once), поэтому wake и дежурный не повторяют свою тревогу о коде каждые 5 минут
NO_WINDOW = 3
# Код «пропуск» (metis-0291): под блокировкой имени выяснилось, что будить не нужно или нельзя по обычной причине (уже
# работает, остановлено вами, пауза, технический перезапуск, имя занято другим подъёмом). Не сбой: wake печатает
# «пропуск: <имя> — <причина>», выходит с 0, без тревоги. Причина — в SKIP_WHY (последний пропуск процесса)
SKIPPED = 4
SKIP_WHY = ""


def skipped(why):
    global SKIP_WHY
    SKIP_WHY = str(why)
    return SKIPPED


def window_missing(name, origin, why, how):
    """Отказ поднять name без окна: строка start.log «<how>-skip», тревога один раз на причину. → NO_WINDOW."""
    start_log(f"{how}-skip\t{name}\t{origin}\tнет окна: {why}")
    alert_once("no-window-" + name, why, f"{name}: не поднимаю ({origin}) — {why}. Без файла окна сессия ушла бы без "
               "песочницы окна; поднимет следующий запуск после сборки окна", "pantheon")
    return NO_WINDOW


def no_window_reason(window):
    """Почему нет окна window: allow проекта в папке запуска (metis-0137) или окно не собрано."""
    folders = (read_json(path("domains.json"), {}).get("domains") or {}).get(window)
    problems = project_allow_problems(launch_folder(folders)) if folders else []
    if problems:
        return "окно не собрано: " + project_allow_text(window, problems)
    return f"нет окна {tilde(path('settings', window + '.json'))} — pantheon domains build"


def cwd_allow_problems(name, a, role, launch, origin):
    """respawn и --resume поднимают сессию в её прежней папке (cwd из claude agents), а окно проверено по папке
    запуска. Папка координатора другая и её allow пускает gh pr merge — не поднимаем: строка resume-skip, тревога одна
    на причину. Окно не снимается: pantheon start и свежий старт идут из папки запуска. → NO_WINDOW или 0."""
    cwd = os.path.realpath(a["cwd"]) if role == "domain-coordinator" and isinstance(a.get("cwd"), str) and a["cwd"] else ""
    problems = project_allow_problems(cwd) if cwd and cwd != launch else []
    key = "project-allow-cwd-" + name
    if not problems:
        clear_once(key)
        return 0
    text = project_allow_text(name, problems)
    start_log(f"resume-skip\t{name}\t{origin}\tпапка сессии {tilde(cwd)}: allow пускает gh pr merge")
    alert_once(key, json.dumps(problems), f"{name}: не поднимаю ({origin}) — сессия работала в {tilde(cwd)}, не в папке "
               f"запуска: {text}. Свежий старт (pantheon start {name}) пойдёт из папки запуска", "pantheon")
    return NO_WINDOW


def _resume_session(name, a, text, origin):
    target, rest = (("workshop", [name[len("daedalus-"):]]) if name.startswith("daedalus-") else (name, []))
    got = start_target(target, rest)
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        print(f"[resume] {name} {a.get('id')} {origin}")
        return 0, None
    if not isinstance(got, str):
        allow_gate(name)  # allow со старым mtime сборка не заметила — окно снимается здесь (ревью argus PR #32)
        bad = cwd_allow_problems(name, a, got[1], got[2], origin)
        if bad:
            return bad, None
    run = run_settings(name, got[1], got[3], origin) if not isinstance(got, str) else None
    if not run:  # ни respawn (прежние флаги с прежним файлом запуска), ни --resume без --settings
        return window_missing(name, origin, got if isinstance(got, str) else no_window_reason(got[3]), "resume"), None
    clear_once("no-window-" + name)
    sid = a.get("sessionId")
    if not str(text).startswith(START_MARK):
        text = f"{START_MARK} поручение от {origin}] {text}"
    pushed = push_text(sid, text) if a.get("id") else None
    if pushed:  # без текста respawn поднял бы сессию молча — тогда сразу запасной путь, он текст передаёт
        r = subprocess.run([claude_bin(), "respawn", a["id"]], env=claude_env(), capture_output=True, text=True, timeout=180)
        start_log(f"respawn\t{name}\t{a['id']}\t{origin}\t{r.returncode}")
        if r.returncode == 0:
            rm_previous(name, "respawn", keep={a["id"]}, wait=True)
            return 0, None
        with contextlib.suppress(OSError):
            os.remove(pushed)
    # --resume не наследует роль (metis-0208): без --agent сессия поднялась бы голым Claude. Роль — та же, что у start и
    # свежего старта; штаб (zeus) — hq, хотя сюда он сегодня не доходит (start_target не знает zeus — отказ выше)
    role = "hq" if name == "zeus" else got[1]
    argv = [claude_bin(), "--resume", sid or a.get("id"), "--bg", "--agent", role, "--name", name, "--settings", run, text]
    before = {x.get("id") for x in agents_all() or [] if x.get("id")}
    r = subprocess.run(argv, cwd=a.get("cwd") or HOME, env=claude_env(), capture_output=True, text=True, timeout=180)
    m = COPY_NOTE.search((r.stdout or "") + (r.stderr or ""))
    start_log(f"resume\t{name}\t{a.get('id')}\t{origin}\t{r.returncode}" + (f"\tcopy {m.group(1)}" if m else ""))
    if m:  # метка копии (metis-0081 п. 4): копию сразу убираем (stop + rm без --discard-unpushed), исходная остаётся
        left = stop_and_rm(name, m.group(1), "copy-note")
        start_log(f"copy-removed\t{name}\t{m.group(1)}" + (f"\trefused {left}" if left else ""))
        alert(f"{name}: --resume сделал копию {m.group(1)} — исходная сессия {a.get('id')} ещё числится живой; "
              + ("копия убрана (claude stop + rm)" if not left else f"копию убрать не вышло ({left}) — claude agents, "
                 "лишнюю остановить"), "pantheon")
    elif r.returncode == 0:  # копию (исходная ещё живая) не разбираем сами — тревога выше, решает Зевс
        rm_previous(name, "--resume", before=before, keep={a.get("id")}, wait=True)
    return r.returncode, (m.group(1) if m else None)


# --- свежий старт вместо продолжения (metis-0147 п. 2, metis-0136) ---------------------------------
# `claude respawn` перезапускает процесс той же сессии с тем же разговором, `--resume` — тоже: контекст не уходит.
# Очистить окно можно только новой сессией: старую остановить (разговор сохраняется — claude attach <id>), имя
# дождаться свободным и поднять `claude --bg --agent <роль> --name <имя> --settings <окно роли>` с текстом
# «[Пантеон: …] прочитай <файл состояния>, продолжай».

_CTX = None


def ctx_mod():
    """hooks/ctx.py — замер контекста тот же, что у Stop-хука «пора очистить» (context_tokens, порог AT), и его метки."""
    global _CTX
    if _CTX is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_ctx", os.path.join(PLUGIN, "hooks", "ctx.py"))
        _CTX = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CTX)
    return _CTX


def tilde(p):
    for h in (HOME, os.path.realpath(HOME)):  # PANTHEON — настоящим путём, HOME — как в окружении
        if p == h or p.startswith(h + "/"):
            return "~" + p[len(h):]
    return p


def stop_and_rm(name, sid, why="stop"):
    """claude stop, затем claude rm <id> (metis-0239): остановленную сессию Claude Code сам перезапускает
    (daemon.log: settled (killed) → claimed-spare (fleet)), пока она в его списке. rm убирает из списка фоновую сессию
    (и её worktree, если он чистый); переписка остаётся, вернуть — pantheon start / resume. Без --discard-unpushed и
    --force-remove-worktree: сессию с неотправленной работой не удаляем насильно. Возвращает None или причину отказа."""
    try:
        st = subprocess.run([claude_bin(), "stop", sid], env=claude_env(), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"claude stop не выполнился: {e}"[:200]
    if st.returncode != 0:  # не остановилась — rm не зовём (rm сносит сессию, а она ещё может работать)
        return ("claude stop: " + (" ".join(((st.stderr or "") + " " + (st.stdout or "")).split())
                                   or f"код {st.returncode}"))[:200]
    return rm_session(sid, name=name, why=why)


def reap_log(name, sid, why):
    """Строка в logs/reap.log о каждом убранном claude rm: время, имя, id, причина, транскрипт (остаётся на месте), хост
    (metis-0081 п. 3)."""
    found = glob.glob(os.path.join(glob.escape(HOME), ".claude", "projects", "*", glob.escape(str(sid)) + "*.jsonl")) \
        if re.fullmatch(r"[0-9a-f-]{4,64}", str(sid)) else []
    tr = sorted(found)[0] if found else ""
    with contextlib.suppress(OSError):
        os.makedirs(path("logs"), exist_ok=True)
        with open(path("logs", "reap.log"), "a") as fh:
            fh.write(f"{stamp()}\t{name}\t{sid}\t{why}\t{tr}\t{host()}\n")


def rm_session(sid, tries=2, name="", why="rm"):
    """claude rm <id> без --discard-unpushed и --force-remove-worktree (metis-0239; уборка дежурного metis-0250):
    сессию с неотправленной работой в worktree Claude Code не удаляет, и мы не настаиваем. → None или причина отказа."""
    r = None
    for attempt in range(tries):  # stop возвращается раньше, чем процесс ушёл: rm на ещё живую сессию может отказать
        try:
            r = subprocess.run([claude_bin(), "rm", sid], env=claude_env(), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return f"claude rm не выполнился: {e}"[:200]
        if r.returncode == 0:
            reap_log(name, sid, why)
            return None
        if attempt + 1 < tries:
            time.sleep(1)
    return " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())[:200] or f"код {r.returncode}"


def refused_by(reason):
    """Кто отказал в stop_and_rm — для тревоги: «stop отказал» (сессия не остановилась, rm не звали) или «rm отказал»
    (ревью argus к #53: при коде stop ≠ 0 тревога писала «rm отказал»)."""
    return "stop отказал" if str(reason or "").startswith("claude stop") else "rm отказал"


def rm_previous(name, how, before=None, keep=(), loud=False, wait=False):
    """После успешного старта под именем name (pantheon start, свежий старт, продолжение wake/техперезапуска/дежурного):
    прежние фоновые сессии этого имени — `claude rm` (процесса нет) или claude stop + rm (процесс есть), чтобы в
    claude agents у имени осталась одна строка (metis-0250, слово владельца 19.10 через Зевса). Новая не трогается:
    новая — id, которого не было в before (снимок id до запуска; None — все нынешние старые), и id из keep (продолженная respawn/--resume сессия), если
    она живая. Пока живой новой с этим именем нет, ничего не удаляем (старт не подтвердился — прежние добьёт уборка
    дежурного); wait — подождать её появления PANTHEON_NAME_WAIT (10 с). Отказ rm (неотправленное в worktree) —
    start.log, тревога и, при loud, строка в stderr. → список (id, причина) отказов."""
    keep = set(keep)
    limit = 0.0
    if wait:
        limit = 10.0
        with contextlib.suppress(ValueError, TypeError):
            limit = max(0.0, float(os.environ.get("PANTHEON_NAME_WAIT") or limit))
    _, poll, _ = stop_wait_knobs()
    started = time.monotonic()
    while True:
        agents = agents_all()
        if agents is None:
            return []
        same = [a for a in agents if a.get("name") == name and a.get("id") and a.get("kind") in (None, "background")]
        old = {a["id"] for a in same} if before is None else before  # без снимка — нового нет, только keep
        kept = {a["id"] for a in same if a["id"] not in old
                or (a["id"] in keep and a.get("state") not in DOWN_STATES)}
        if not any(a["id"] not in kept for a in same):
            return []  # убирать нечего — и ждать нечего
        if any(a.get("state") not in DOWN_STATES for a in same if a["id"] in kept):
            break
        if time.monotonic() - started >= limit:
            start_log(f"rm-previous-skip\t{name}\t{how}\tновая сессия не видна живой")
            return []
        time.sleep(poll)
    left = []
    for a in same:
        if a["id"] in kept:
            continue
        # призрак (ghost, metis-0651) в списке «working/blocked», как и раньше: claude stop перед rm (metis-0348)
        has_process = (a.get("state") in ("working", "blocked") or a.get("ghost")
                       or (a.get("pid") and a.get("state") not in ("stopped", "failed")))
        reason = stop_and_rm(name, a["id"], how) if has_process else rm_session(a["id"], name=name, why=how)
        start_log(f"rm-previous\t{name}\t{a['id']}\t{a.get('state')}\t{how}")
        if reason:
            start_log(f"rm-refused\t{name}\t{a['id']}\t{reason}")
            alert(f"{name}: прежняя сессия {a['id']} осталась среди фоновых сессий Claude Code ({how}, "
                  f"{refused_by(reason)}): {reason}", "pantheon-stop")
            if loud:
                print(f"pantheon start: {name}: прежняя сессия {a['id']} осталась среди фоновых сессий Claude Code, "
                      f"причина: {reason}", file=sys.stderr)
            left.append((a["id"], reason))
    return left


def stop_copies(name, live, why="stop-restart"):
    # без rm (metis-0239): здесь сессию поднимают снова или оставляют для claude attach — rm её бы удалил
    for a in live:
        subprocess.run([claude_bin(), "stop", a["id"]], env=claude_env(), capture_output=True, text=True, timeout=60)
        start_log(f"{why}\t{name}\t{a.get('name')}\t{a['id']}")


DOWN_STATES = ("done", "stopped", "failed")


def stop_wait_knobs():
    """После claude stop: сколько ждать освобождения имени (с), как часто спрашивать claude agents и сколько имя
    должно простоять свободным (15.10 остановленная Фемида ожила через 7 с). Подменяются в тестах."""
    def num(var, default):
        with contextlib.suppress(ValueError, TypeError):
            v = float(os.environ.get(var) or default)
            if v >= 0:
                return v
        return default
    return num("PANTHEON_STOP_WAIT", 30.0), num("PANTHEON_STOP_POLL", 1.5), num("PANTHEON_STOP_SETTLE", 10.0)


def start_log(line):
    os.makedirs(path("logs"), exist_ok=True)
    with open(path("logs", "start.log"), "a") as fh:
        fh.write(f"{stamp()}\t{line}\n")


def launch_folder(folders):
    """Папка запуска координатора — одно правило для start, direction check и direction init: первая существующая
    папка записи (настоящим путём), иначе первая в списке, иначе ""."""
    real = [os.path.realpath(os.path.expanduser(f)) for f in folders or [] if isinstance(f, str) and f]
    return next((f for f in real if os.path.isdir(f)), real[0] if real else "")


def hq_led(reg=None):
    """metis-0155 (Б): направления, которые ведёт Пританей, — `coordinator = false` в записи directions.toml. → {имя:
    запись реестра}. По умолчанию координатор включён; выключает только булево false — другое значение `pantheon check`
    считает ошибкой, а запуск — включённым координатором. Реестр не читается — пусто (координаторы как раньше)."""
    if reg is None:
        try:
            with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
                reg = tomllib.load(fh)
        except (OSError, ValueError):
            return {}
    return {d["name"]: d for d in reg.get("direction") or []
            if isinstance(d, dict) and isinstance(d.get("name"), str) and d.get("coordinator") is False}


def hq_led_why(target):
    return (f"направление {target} ведёт Пританей (coordinator = false в directions.toml) — координатора не поднимаю; "
            f"задачу направления — pantheon wake {target} --task <id> (окно лида)")


def lead_session(target, entry):
    """Имя окна лида кода выключенного направления — hephaestus-<коротко>, как у субагента лида (domains_build,
    roles_build). → имя или None: имя направления не «бог-коротко» или в leads нет hephaestus."""
    bases = entry.get("leads") if isinstance(entry.get("leads"), list) else []
    if "hephaestus" not in bases or not re.fullmatch(r"[a-z0-9]+-[a-z0-9-]+", target):
        return None
    return "hephaestus-" + target.split("-", 1)[1]


def start_target(target, rest):
    """→ (имя сессии, роль, папка запуска, файл окна, поручение по умолчанию) или текст ошибки. Направление, которое
    ведёт Пританей (coordinator = false, metis-0155), — текст ошибки: координатора у него нет."""
    domains = read_json(path("domains.json"), {}).get("domains") or {}
    if target in domains and target in hq_led():
        return hq_led_why(target)
    return direction_target(target, rest, domains)


def direction_target(target, rest, domains):
    """start_target без проверки переключателя координатора: окно лида выключенного направления (wake_lead) берёт
    ту же папку и то же окно, что у координатора."""
    if target == "workshop":
        if not rest or not SESSION_NAME.fullmatch(rest[0]):
            return "pantheon start workshop <задача> [поручение]: имя задачи — a-z, 0-9, дефис"
        root = workshop_root()
        task, folder = rest[0], os.path.join(root, rest[0])
        os.makedirs(folder, exist_ok=True)
        if os.path.islink(folder) or not os.path.realpath(folder).startswith(os.path.realpath(root) + "/"):
            return f"папка задачи мастерской {folder} — ссылка или вне {workshop_dir()}"
        return (f"daedalus-{task}", "workshop", folder, "workshop",
                f"Прочитай ~/ai/pantheon/workshop/{task}.md и выполни задачу. Внешние действия — только по "
                "approvals.toml или после «да» владельца в этой сессии.")
    if target not in domains:
        return f"нет направления «{target}» в domains.json (реестр ~/ai/pantheon/directions.toml → pantheon domains build)"
    folder = launch_folder(domains[target])
    if not os.path.isdir(folder):
        return f"у направления {target} нет папки на этом Mac: {domains[target]}"
    return (target, "domain-coordinator", folder, target,
            f"Прочитай ~/ai/pantheon/directions/{target}/STATUS.md и inbox/, затем продолжай текущий эпик по нему.")


_WATCH = None


def watch_mod():
    """lib/watch.py одним экземпляром на процесс (пороги дежурного и чтение свопа — одно место)."""
    global _WATCH
    if _WATCH is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_watch", os.path.join(LIB, "watch.py"))
        _WATCH = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_WATCH)
        _WATCH.set_core(sys.modules[__name__])
    return _WATCH


# --- роли (ROLE-15, ROLE-16, ROLE-17) -------------------------------------------------------
# Два слоя шаблонов (metis-0182). Общий — в плагине: PLUGIN/roles/<роль>.tmpl и PLUGIN/roles/_parts/<часть>.part, без
# проектов, коллекций, браузера и имён владельца; приходит с выпуском плагина. Личный — ~/.claude/agents/ (у владельца
# его синхронизирует claude-config; правит только metis-pantheon — guard protect-config): личный <роль>.tmpl перекрывает
# общий по имени, личная _parts/<часть>.part — общую часть. Набор ролей — объединение слоёв. Сборка кладёт в
# ~/.claude/agents <роль>.md — то, что читает Claude Code; собранные файлы claude-config не синхронизирует (строки в
# ~/.claude/.gitignore): на каждом Mac их собирает тик вместе с domains.json, когда меняется шаблон, часть или реестр.
#   {{> часть}}         — текст части (одна общая формулировка: отчёт, находка, внешние действия, доведение до конца);
#   {{qmd_collections}} {{browser}} — во всех ролях, после вставки частей, из раздела [person] реестра (PERSON_*).
#   {{workshop}}        — папка мастерской по факту (workshop_dir(): ~/ai/workshop или до переноса старая в ~/projects).
#                         Пустое значение или нет раздела — строка шаблона с подстановкой выпадает целиком, вместе с
#                         переводом строки. Поэтому в шаблонах такая подстановка стоит в своей строке-фразе, а текст
#                         вокруг неё связен и без неё;
#   hephaestus, apollo  — роли лидов: по одной на направление с этим лидом в поле leads реестра,
#                         hephaestus-<коротко> (example-site → site), подстановки {{direction}} {{short}}
#                         {{project}} {{folders}}.
# Свой файл узнаётся по строке-метке после шапки; файл без метки (свой ли, чужой ли) сборка не трогает, собранный файл
# без шаблона — убирает. Ошибка в шаблоне (нет части, осталась {{…}}, значение реестра не по образцу) — роль не
# пишется, старая версия остаётся.
AGENTS = os.path.join(HOME, ".claude", "agents")
PARTS = os.path.join(AGENTS, "_parts")
# общий слой; PANTHEON_PLUGIN_ROLES подменяет его в тестах
PLUGIN_ROLES = os.path.realpath(os.environ.get("PANTHEON_PLUGIN_ROLES") or os.path.join(PLUGIN, "roles"))
PLUGIN_PARTS = os.path.join(PLUGIN_ROLES, "_parts")
LEAD_ROLES = ("hephaestus", "apollo")
ROLE_MARK = "<!-- собрано pantheon roles build из {tmpl} — правят шаблон, а не этот файл -->"
ROLE_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")
# значения из реестра в шаблон лида: одна строка без разметки YAML. Реестр может править штаб из песочницы, а шапка
# роли (hooks, mcpServers) запускает команды вне её — перевод строки в project дописал бы в шапку хук (проверка
# безопасности 15.10). Сверх образца — сверка ключей шапки до и после подстановки.
ROLE_PROJECT = re.compile(r"[\w][\w .,()«»+-]{0,59}")
ROLE_FOLDER = re.compile(r"~?/[\w.-]+(?:/[\w.-]+)*")
# [person] реестра → текст всех ролей. Довод тот же, что у ROLE_PROJECT (реестр правит штаб из песочницы, а текст
# попадает в роли всех): одна строка из букв, цифр, пробела и простой пунктуации — без {{ }}, обратных кавычек, < >,
# перевода строки; «---» запрещён отдельно (граница шапки YAML).
#   qmd_collections = ["имя" | "имя (что в ней)", …] — в роли через запятую;
#   browser = "одна строка" — браузер владельца для сайтов со входом и, если нужно, адрес демона CDP.
PERSON_ITEM = re.compile(r"[\w][\w .,:;()«»+/~—–-]{0,79}")
PERSON_TEXT = re.compile(r"[\w][\w .,:;()«»\"'+/~!?%#№—–-]{0,199}")
PERSON_KEYS = ("qmd_collections", "browser")
PERSON_MAX_ITEMS = 20


def _head_keys(text):
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    return [ln.split(":", 1)[0] for ln in text[4:end].splitlines() if re.match(r"[A-Za-z_]", ln)] if end > 0 else None


def _role_text(tmpl_text, parts=None):
    """Вставка частей {{> x}}: сначала <parts>/x.part (личный слой), потом общая часть плагина."""
    def part(m):
        if ROLE_NAME.fullmatch(m.group(1)):
            for d in (parts or PARTS, PLUGIN_PARTS):
                p = os.path.join(d, m.group(1) + ".part")
                if os.path.isfile(p):
                    return open(p, encoding="utf-8").read().rstrip("\n")
        raise ValueError(f"нет части {m.group(1)}")
    return re.sub(r"\{\{>\s*([\w-]+)\s*\}\}", part, tmpl_text)


def person_values(reg):
    """[person] реестра → ({ключ: текст или ""}, {ключ: ошибка}). Значение не по образцу — ошибка, а не пустота:
    роль с этой подстановкой не собирается, её старая версия остаётся."""
    person, values, bad = reg.get("person"), {k: "" for k in PERSON_KEYS}, {}
    if person is None:
        return values, bad
    if not isinstance(person, dict):
        return values, {k: "раздел [person] реестра — не таблица" for k in PERSON_KEYS}

    def ok(v, rx):
        return isinstance(v, str) and (not v.strip() or ("---" not in v and bool(rx.fullmatch(v.strip()))))
    cols = person.get("qmd_collections", [])
    if isinstance(cols, list) and len(cols) <= PERSON_MAX_ITEMS and all(ok(c, PERSON_ITEM) for c in cols):
        values["qmd_collections"] = ", ".join(c.strip() for c in cols if c.strip())
    else:
        bad["qmd_collections"] = "[person] qmd_collections в реестре не по образцу"
    browser = person.get("browser", "")
    if ok(browser, PERSON_TEXT):
        values["browser"] = browser.strip()
    else:
        bad["browser"] = "[person] browser в реестре не по образцу"
    return values, bad


def _person_text(text, values, bad):
    """Подстановки [person] построчно: строка с пустой подстановкой выпадает целиком; плохое значение — ValueError.
    В шапке YAML (между первыми ---) подстановка [person] запрещена целиком, и с пустым значением: в шапке живут
    хуки роли, они идут вне песочницы, а образец значений пропускает кавычки и «;» — значение стало бы командой."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    head = text[:end + 5] if end > 0 else ""
    in_head = [k for k in PERSON_KEYS if "{{" + k + "}}" in head]
    if in_head:
        raise ValueError("подстановка [person] в шапке роли запрещена: "
                         + ", ".join("{{" + k + "}}" for k in in_head))
    lines = []
    for ln in text.splitlines(keepends=True):
        keys = [k for k in PERSON_KEYS if "{{" + k + "}}" in ln]
        for k in keys:
            if k in bad:
                raise ValueError(bad[k])
        if any(not values[k] for k in keys):
            continue
        for k in keys:
            ln = ln.replace("{{" + k + "}}", values[k])
        lines.append(ln)
    out = "".join(lines)
    if _head_keys(out) != _head_keys(text):
        raise ValueError("подстановка [person] поменяла шапку роли")
    return out


def _marked(text, tmpl):
    """Метка — сразу после шапки YAML: файл роли должен начинаться с ---."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    if end < 0:
        raise ValueError("нет шапки YAML (--- … ---)")
    return text[:end + 5] + ROLE_MARK.format(tmpl=tmpl) + "\n" + text[end + 5:]


# Шаблоны, которые build пока не собирает (metis-0217, review-51-bypass): роль, которую нельзя звать до окна
# песочницы, не должна лежать в ~/.claude/agents — иначе её поднимет субагент мимо отказа wake. Строка — имя шаблона и
# задача, которая его откроет; уже собранный файл с меткой build убирает как устаревшую роль. Пусто с metis-0245:
# у hestia своё окно (sandbox_build) и правило guard «hestia».
ROLES_DEFERRED = {}


def _head_lines(text):
    """Строки шапки роли между --- и ---; [] — шапки нет."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    return text[4:end].splitlines() if end >= 0 else []


def _head_names(text):
    """Значения полей name: шапки роли без кавычек, по порядку; [] — шапки или поля нет, два и больше — повтор."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    if end < 0:
        return []
    return [ln.split(":", 1)[1].strip().strip("\"'") for ln in text[4:end].splitlines() if re.match(r"name\s*:", ln)]


def roles_build(src=None, out=None, role_errors=None):
    """Роли из общих шаблонов плагина (PLUGIN_ROLES) и личного слоя src (по умолчанию ~/.claude/agents; перекрывает
    общий по имени шаблона и части) в папку out (по умолчанию ~/.claude/agents). Режим с out — проба
    (metis-0097): пишет и чистит только в out, владельцу сигнал не шлёт; out в ~/.claude/agents или внутри — ValueError.
    role_errors — словарь {шаблон.tmpl: [ошибки]}: сюда же ошибки по ролям (role apply сверяет свою роль); печать в
    stderr и тревога — как без него, возвращается по-прежнему список изменённых файлов."""
    probe = out is not None
    src = src or AGENTS
    if probe:
        real_out, real_agents = os.path.realpath(os.path.expanduser(out)), os.path.realpath(AGENTS)
        if real_out == real_agents or real_out.startswith(real_agents + os.sep):
            raise ValueError(f"--out {out} совпадает с {AGENTS} или лежит внутри: пробная сборка живые роли не трогает")
        out = real_out
    else:
        out = AGENTS
    parts = os.path.join(src, "_parts")
    with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
        reg = tomllib.load(fh)
    person, person_bad = person_values(reg)
    want, errors = {}, []
    pmap = plugin_map_load(alert=not probe, kind="roles", src=src)

    def err(tmpl, text):
        errors.append(text)
        if role_errors is not None:
            role_errors.setdefault(tmpl, []).append(text)

    # роли, чей шаблон или подстановка с ошибкой: старую собранную версию не убирать (имя или начало имени лида)
    kept, kept_leads = set(), set()
    layer = {}  # объединение слоёв: личный шаблон из src перекрывает общий из плагина по имени
    for d in (PLUGIN_ROLES, src):
        for f in os.listdir(d) if os.path.isdir(d) else []:
            if f.endswith(".tmpl"):
                layer[f] = os.path.join(d, f)
    for f in sorted(layer):
        base = f[:-5]
        if base in ROLES_DEFERRED:
            continue
        if not ROLE_NAME.fullmatch(base):
            err(f, f"{f}: имя не по образцу")
            continue
        try:
            text = _person_text(_role_text(open(layer[f], encoding="utf-8").read(), parts), person, person_bad)
            text = text.replace("{{workshop}}", workshop_dir())
        except (OSError, ValueError) as e:
            err(f, f"{f}: {e}")
            if base in LEAD_ROLES:
                kept_leads.add(base + "-")
            else:
                kept.add(base + ".md")
            continue
        if pmap:
            try:
                text = PLUGIN_MAP.role_header(text, pmap, base)
            except ValueError as e:  # disallowedTools списком YAML: шапка как в шаблоне (всё включено), ошибка роли
                err(f, f"{f}: карта плагинов не применена — {e}")
        if base not in LEAD_ROLES:
            want[base + ".md"] = (f, text)
            continue
        for d in reg.get("direction") or []:
            name = d.get("name", "")
            if base not in (d.get("leads") or []) or not re.fullmatch(r"[a-z0-9]+-[a-z0-9-]+", name):
                continue
            short = name.split("-", 1)[1]
            project, folders = d.get("project", ""), d.get("folders") or []
            if not (isinstance(project, str) and (not project or ROLE_PROJECT.fullmatch(project))) \
                    or not isinstance(folders, list) \
                    or not all(isinstance(x, str) and ROLE_FOLDER.fullmatch(x) for x in folders):
                err(f, f"{f} → {base}-{short}.md: project или folders направления {name} не по образцу")
                kept.add(f"{base}-{short}.md")
                continue
            out_text = (text.replace("{{direction}}", name).replace("{{short}}", short)
                        .replace("{{project}}", project).replace("{{folders}}", ", ".join(folders)))
            if _head_keys(out_text) != _head_keys(text):
                err(f, f"{f} → {base}-{short}.md: подстановка поменяла шапку роли")
                kept.add(f"{base}-{short}.md")
                continue
            want[f"{base}-{short}.md"] = (f, out_text)
    # Claude Code зовёт роль по полю name:, а не по имени файла (argus-51d): личный hearth.tmpl с `name: hestia` дал бы
    # вторую hestia мимо её окна и правил. Несовпадение — роль не собирается, а прежний собранный файл убирается ниже
    for fname in sorted(want):
        got = _head_names(want[fname][1])
        if got != [fname[:-3]]:
            tmpl = want.pop(fname)[0]
            what = ("нет" if not got else f"«{got[0]}»" if len(got) == 1
                    else "повторён (" + ", ".join(f"«{g}»" for g in got) + ")")
            err(tmpl, f"{tmpl} → {fname}: поле name: в шапке {what} — не совпадает с именем роли «{fname[:-3]}», "
                f"роль не собрана")
    # шаблон Bash(...) в disallowedTools шапки: Claude Code 2.1.312 убирает из-за него Bash целиком (metis-0576, Гестия
    # осталась без Bash). Запреты по командам — в guard и deny окна, а не в шапке роли; роль не собирается, прежняя
    # собранная версия остаётся
    for fname in sorted(want):
        if any(re.match(r"disallowedTools\s*:.*\bBash\s*\(", ln) for ln in _head_lines(want[fname][1])):
            tmpl = want.pop(fname)[0]
            kept.add(fname)
            err(tmpl, f"{tmpl} → {fname}: Bash(...) в disallowedTools шапки убирает Bash целиком (metis-0576) — запрет "
                "команд ставят в guard или permissions.deny окна; роль не собрана")
    made = []
    if want:  # и на новой машине: ~/.claude/agents ещё нет, а общие роли плагина собрать надо
        os.makedirs(out, exist_ok=True)
    for fname, (tmpl, text) in sorted(want.items()):
        out_file = os.path.join(out, fname)
        try:
            if "{{" in text:
                raise ValueError("осталась подстановка {{…}}")
            text = _marked(text, tmpl)
        except ValueError as e:
            err(tmpl, f"{tmpl} → {fname}: {e}")
            continue
        old = open(out_file, encoding="utf-8").read() if os.path.exists(out_file) else None
        if old is not None and "pantheon roles build" not in old[:2000]:
            err(tmpl, f"{fname} есть и написан не сборкой — не трогаю (убрать его или шаблон {tmpl})")
            continue
        if old != text:
            write_atomic(out_file, text)
            made.append(fname)
    for f in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        p = os.path.join(out, f)
        if f in kept or any(f.startswith(x) for x in kept_leads):
            continue
        if f.endswith(".md") and f not in want and not os.path.islink(p) and os.path.isfile(p):
            if "pantheon roles build" in open(p, encoding="utf-8").read(2000):
                os.remove(p)
                made.append(f"-{f}")
    for e in errors:
        print(f"roles build: {e}", file=sys.stderr)
    if errors and not probe:
        alert_once("roles-build", "\n".join(errors), f"pantheon roles build: {errors[0]}"
                   + (f" (и ещё {len(errors) - 1})" if len(errors) > 1 else ""), "pantheon")
    if not probe:
        memo_line = who_is_who_alert()
        if memo_line:
            print(f"roles build: {memo_line}", file=sys.stderr)
    return made


# --- личная роль: заявка и установка по вашей галочке (metis-0262 PR 4, решения [zeus-role-apply], [zeus-role-board]) ---
# Черновик роли готовит агент: ~/ai/pantheon/roles/proposed/<имя>.tmpl. `pantheon role propose <имя> --direction D`
# заводит карточку «Применить роль <имя> [<sha256>]?» с вариантами Да/Нет и статус proposed в STATE/roles/status.jsonl
# (вне ~/ai/pantheon; файл пишут только команды role и тик). sha256 черновика — полный, все 64 знака: правка черновика
# после галочки меняет хеш, и старая галочка его не ставит; урезанный хеш агент подобрал бы вторым черновиком
# (argus-70b). Ваш ответ тик переносит в owner-log/board.jsonl (роли туда не пишут); `role apply` и тик верят только
# ему и только на карточке из статуса заявки. В ~/.claude/agents пишет только `role apply` (её зовёт и тик):
# ворота → пробная сборка во временной папке → сверка шапки собранной роли → <имя>.tmpl в личный слой → `roles build`.
ROLE_PROPOSED = os.path.join(PANTHEON, "roles", "proposed")
ROLE_STATUS = ("proposed", "applied", "rejected", "cancelled")
ROLE_MAX_BYTES = 5 * 1024
ROLE_APPROVE_DAYS = 14
ROLE_NEW_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
# ключи шапки, с которыми роль выходит из песочницы или меняет права окна: хуки идут вне песочницы, mcpServers поднимают
# процессы, permissionMode снимает вопросы; settings — на будущее (сравнение без учёта регистра)
ROLE_HEAD_DENY = ("hooks", "settings", "mcpservers", "permissionmode")
# имена, которые знают guard и хуки (роли окон, системные субагенты, встроенные типы Claude Code) — личной роли не даём
# (встроенные агенты Claude Code: general-purpose, Explore, Plan, statusline-setup, claude-code-guide, output-style-setup,
# claude, fork; на будущие встроенные — весь claude-*)
ROLE_RESERVED = {"hq", "zeus", "workshop", "domain-coordinator", "tg-reader", "general-purpose", "explore", "plan",
                 "statusline-setup", "claude-code-guide", "output-style-setup", "claude", "fork"}
ROLE_RESERVED_PREFIX = tuple(b + "-" for b in LEAD_ROLES) + ("dev-", "codex-", "daedalus-", "claude-")


def role_sha(data):
    """Полный sha256 черновика (64 знака): по нему вопрос карточки, статус заявки и сверка галочки."""
    return hashlib.sha256(data).hexdigest()


def role_question(name, sha):
    return f"Применить роль {name} [{sha}]?"


def role_status_all():
    """STATE/roles/status.jsonl → {имя: [запись, …]} по порядку; действующий статус — последняя запись."""
    out = {}
    try:
        with open(path("roles", "status.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("name"), str) and rec.get("status") in ROLE_STATUS:
                    out.setdefault(rec["name"], []).append(rec)
    except OSError:
        pass
    return out


def role_last(name):
    return (role_status_all().get(name) or [None])[-1]


def role_status_add(name, status, **rec):
    os.makedirs(path("roles"), exist_ok=True)
    rec = {"time": datetime.fromtimestamp(now()).strftime("%Y-%m-%dT%H:%M:%S"), "name": name, "status": status, **rec}
    fd = os.open(path("roles", "status.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def role_name_problem(name):
    """Почему имя не годится для личной роли, или None."""
    if not (isinstance(name, str) and ROLE_NEW_NAME.fullmatch(name) and 2 <= len(name) <= 40):
        return f"имя «{name}» не по образцу: латиница в нижнем регистре, цифры, дефис между словами, 2–40 знаков"
    if os.path.isfile(os.path.join(PLUGIN_ROLES, name + ".tmpl")) or name in ROLES_DEFERRED or name in LEAD_ROLES:
        return f"«{name}» — общая роль Пантеона: личная роль с этим именем не ставится"
    if name in ROLE_RESERVED or name.startswith(ROLE_RESERVED_PREFIX):
        return (f"имя «{name}» занято системой (роли окон, лиды hephaestus-/apollo-, dev-*, codex-*, встроенные агенты "
                f"Claude Code, claude-*)")
    return None


def _role_head_end(text):
    return text.find("\n---\n", 3) if text.startswith("---\n") else -1


def role_head_problem(text):
    """Шапка YAML роли: есть, в ней name и нет запрещённых ключей, повторов ключа и строк не по образцу «ключ:
    значение». → текст или None. Строки с отступом и «- » — продолжение значения ключа выше; ключ в кавычках, «<<:»,
    «? » — отказ. Повтор ключа — отказ: Claude Code разбирает шапку Bun.YAML.parse, где побеждает последний ключ, а
    ворота сверяют первый (argus-70b: «name: foo» и ниже «name: argus» заняли бы имя общей роли)."""
    end = _role_head_end(text)
    if end < 0:
        return "нет шапки YAML (--- … ---) в начале"
    seen = set()
    for ln in text[4:end].splitlines():
        if not ln.strip() or ln.lstrip().startswith("#") or ln[:1] in (" ", "\t") or ln.startswith("- "):
            continue
        m = re.match(r"([A-Za-z][\w-]*)\s*:(?:\s|$)", ln)
        if not m:
            return f"строка шапки не по образцу «ключ: значение»: {ln[:60]!r}"
        if m.group(1).lower() in ROLE_HEAD_DENY:
            return (f"в шапке запрещённый ключ {m.group(1)} (hooks, settings, mcpServers, permissionMode: работают "
                    f"вне песочницы или меняют права)")
        if m.group(1).lower() in seen:
            return f"ключ {m.group(1)} в шапке повторён: Claude Code возьмёт последний, ворота — первый"
        seen.add(m.group(1).lower())
    return None if "name" in seen else "в шапке нет name:"


def role_head_name(text):
    """Значение name: из шапки роли (без кавычек и комментария) или «»."""
    end = _role_head_end(text)
    m = re.search(r"(?m)^name\s*:(.*)$", text[:end]) if end >= 0 else None
    return re.sub(r"\s+#.*$", "", m.group(1)).strip().strip("'\"") if m else ""


def role_head_check(text, name):
    """Шапка без запрещённого и повторов, и name: в ней — ровно name. → текст ошибки или None. Зовут на черновик и на
    собранную роль: часть ({{> …}}) или подстановка могут вставить в шапку то, чего в черновике не было."""
    bad = role_head_problem(text)
    if bad:
        return bad
    given = role_head_name(text)
    return None if given == name else f"name: в шапке «{given}», а имя роли — «{name}»"


def role_draft(name):
    """Черновик роли → (байты, ошибка). Обычный файл, не ссылка, не больше ROLE_MAX_BYTES."""
    p = os.path.join(ROLE_PROPOSED, name + ".tmpl")
    shown = p.replace(HOME, "~")
    try:
        st = os.lstat(p)
    except OSError:
        return None, f"нет черновика {shown}"
    if not stat.S_ISREG(st.st_mode):
        return None, f"черновик {shown} — не обычный файл (ссылка?)"
    with open(p, "rb") as fh:
        data = fh.read(ROLE_MAX_BYTES + 1)
    if len(data) > ROLE_MAX_BYTES:
        return None, f"черновик больше {ROLE_MAX_BYTES // 1024} КБ ({st.st_size} байт)"
    return data, None


def role_static_gate(name):
    """Ворота без вашей галочки: имя, черновик, размер, шапка, name: в шапке = имя. → (байты, sha256, [ошибки])."""
    bad = role_name_problem(name)
    if bad:
        return None, None, [bad]
    data, bad = role_draft(name)
    if bad:
        return None, None, [bad]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, ["черновик не в UTF-8"]
    bad = role_head_check(text, name)
    return data, role_sha(data), [bad] if bad else []


def role_answers(name, req, days=ROLE_APPROVE_DAYS):
    """Ваши ответы на карточку заявки req (запись статуса proposed: card, time) «Применить роль <имя> [<sha256>]?» из
    owner-log/board.jsonl (его пишет тик по вашей галочке, роли туда не пишут), не старше days дней и не раньше заявки,
    по времени: [(время, sha256, «да»|«нет», запись)]. Засчитывается только ответ на карточке req["card"]: «Да» на
    чужой карточке с тем же вопросом, на отозванной заявке или на прежней, после которой роль удалили руками, — не
    галочка (argus-70a, argus-70b). Вопрос — ровно этот текст; скрытый текст Obsidian в нём (%%…%%, <!-- -->) — не
    ответ, как в owner_approved."""
    card = (req or {}).get("card")
    try:
        asked = time.mktime(time.strptime(str((req or {}).get("time") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return []
    if not isinstance(card, str) or not card:
        return []
    ask = re.compile(rf"Применить роль {re.escape(name)} \[([0-9a-f]{{64}})\]\?")
    yes = re.compile(r"да(?![а-яёa-z0-9])", re.I)
    no = re.compile(r"нет(?![а-яёa-z0-9])", re.I)
    since, out = max(now() - days * 86400, asked), []
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), str(rec.get("answer") or "").strip()
        if rec.get("kind") != "answer" or rec.get("id") != card or ts < since or not isinstance(q, str) \
                or re.search(r"%%|<", q):
            continue
        m = ask.fullmatch(q.strip())
        word = "да" if yes.match(a) else "нет" if no.match(a) else None
        if m and word:
            out.append((ts, m.group(1), word, rec))
    out.sort(key=lambda x: x[0])
    return out


def _role_card_close(card, status, result):
    """Карточку заявки — в «Готово» или «Отменено» с итогом; сбой (карточку убрали, шапка битая) не мешает делу."""
    if not card:
        return
    with contextlib.suppress(Exception):
        tasks_mod().task_set(PANTHEON, now(), card, {"status": status, "result": result}, actor="pantheon role")


def role_apply(name, by="pantheon role apply"):
    """Поставить личную роль по вашей галочке. → (код, текст): 0 — поставлена или уже стоит, 1 — отказ."""
    with lock("roles"):
        return _role_apply(name, by)


def _role_apply(name, by):
    data, sha, errs = role_static_gate(name)
    if errs:
        return 1, "; ".join(errs)
    last = role_last(name)
    tmpl, md = os.path.join(AGENTS, name + ".tmpl"), os.path.join(AGENTS, name + ".md")
    if last and last["status"] == "applied" and last.get("sha") == sha and os.path.isfile(md) \
            and os.path.isfile(tmpl) and open(tmpl, "rb").read() == data:
        return 0, f"роль {name} [{sha}] уже стоит"
    if not last or last["status"] != "proposed":
        return 1, (f"нет открытой заявки на роль {name} (статус: {last['status'] if last else 'нет'}) — "
                   f"сначала pantheon role propose {name} --direction <направление>")
    answers = role_answers(name, last)
    mine = [a for a in answers if a[1] == sha]
    if not mine:
        other = [a for a in answers if a[2] == "да"]
        if other:
            return 1, (f"галочка «Да» стоит на другой версии черновика [{other[-1][1]}], сейчас [{sha}]: черновик "
                       f"правлен после галочки — новая заявка: pantheon role propose {name} --direction <направление>")
        return 1, (f"нет вашей галочки «Да» на карточке {last.get('card')} «{role_question(name, sha)}» за "
                   f"{ROLE_APPROVE_DAYS} дней (журнал доски owner-log/board.jsonl)")
    _, _, word, rec = mine[-1]
    if word != "да":
        return 1, f"ваш последний ответ на «{role_question(name, sha)}» — «Нет»"
    if os.path.lexists(md) and (os.path.islink(md) or "pantheon roles build" not in
                                open(md, encoding="utf-8", errors="replace").read(2000)):
        return 1, f"{md.replace(HOME, '~')} есть и написан не сборкой — не трогаю"
    old = None
    if os.path.lexists(tmpl):
        old = None if os.path.islink(tmpl) else open(tmpl, "rb").read()
        ours = any(r["status"] == "applied" for r in role_status_all().get(name) or [])
        if old is None or (old != data and not ours):
            return 1, f"в личном слое уже есть свой {tmpl.replace(HOME, '~')} — не перекрываю"
    # пробная сборка: личный слой как есть + черновик, во временной папке; живые роли она не трогает
    with tempfile.TemporaryDirectory(prefix="role-apply-") as tmp:
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        os.makedirs(os.path.join(src, "_parts"))
        for d, dst, ext in ((AGENTS, src, ".tmpl"), (PARTS, os.path.join(src, "_parts"), ".part")):
            for f in os.listdir(d) if os.path.isdir(d) else []:
                p = os.path.join(d, f)
                if f.endswith(ext) and os.path.isfile(p) and not os.path.islink(p):
                    shutil.copyfile(p, os.path.join(dst, f))
        with open(os.path.join(src, name + ".tmpl"), "wb") as fh:
            fh.write(data)
        role_errs = {}
        with open(os.devnull, "w") as null, contextlib.redirect_stderr(null):
            roles_build(src, out, role_errors=role_errs)
        built = os.path.join(out, name + ".md")
        if role_errs.get(name + ".tmpl") or not os.path.isfile(built):
            return 1, "пробная сборка: " + "; ".join(role_errs.get(name + ".tmpl") or ["роль не собралась"])
        bad = role_head_check(open(built, encoding="utf-8").read(), name)
        if bad:
            return 1, f"пробная сборка (после вставки частей): {bad}"
    os.makedirs(AGENTS, exist_ok=True)
    part = f"{tmpl}.{os.getpid()}.tmp"
    with open(part, "wb") as fh:
        fh.write(data)
    os.replace(part, tmpl)
    role_errs = {}
    # живая сборка: ошибка по роли, нет .md, шапка .md не прошла сверку или исключение (диск, права) — откат шаблона
    try:
        roles_build(role_errors=role_errs)
        why = role_errs.get(name + ".tmpl") or ([] if os.path.isfile(md) else ["роль не собралась"])
        bad = None if why else role_head_check(open(md, encoding="utf-8").read(), name)
        why = why or ([f"шапка собранной роли: {bad}"] if bad else [])
    except Exception as e:  # noqa: BLE001 — любой сбой сборки оставлял бы непроверенный шаблон в личном слое
        why = [f"сбой {type(e).__name__}: {e}"]
    if why:
        if old is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmpl)
        else:
            with open(part, "wb") as fh:
                fh.write(old)
            os.replace(part, tmpl)
        with contextlib.suppress(Exception):
            roles_build()
        return 1, "сборка в личном слое: " + "; ".join(why) + " — шаблон возвращён как был"
    role_status_add(name, "applied", sha=sha, by=by, card=last.get("card"), answer_time=rec.get("time"),
                    answer_card=rec.get("id"))
    _role_card_close(last.get("card"), "done", f"Роль {name} [{sha}] поставлена в личный слой ~/.claude/agents")
    return 0, (f"роль {name} [{sha}] поставлена: ~/.claude/agents/{name}.tmpl → {name}.md "
               f"(ваша галочка {str(rec.get('time') or '')[:16].replace('T', ' ')})")


def roles_tick():
    """Плановый проход: заявка proposed с вашим ответом на её черновик — «Да» ставит роль (role apply), «Нет» — статус
    rejected. Отказ apply — тревога (раз на причину), заявка остаётся до ответа или отзыва."""
    for name, recs in sorted(role_status_all().items()):
        last = recs[-1]
        if last["status"] != "proposed" or role_name_problem(name):
            continue
        answers = [a for a in role_answers(name, last) if a[1] == last.get("sha")]
        if not answers:
            continue
        _, sha, word, rec = answers[-1]
        if word == "нет":
            with lock("roles"):
                if (role_last(name) or {}).get("status") == "proposed":
                    role_status_add(name, "rejected", sha=sha, by="tick", card=last.get("card"),
                                    answer_time=rec.get("time"))
                    _role_card_close(last.get("card"), "dropped", f"Роль {name} отклонена вашим ответом «Нет»")
            continue
        code, text = role_apply(name, by="tick")
        if code:
            alert_once("role-apply-" + name, text, f"pantheon role apply {name}: {text}", "pantheon-tick")
        else:
            clear_once("role-apply-" + name)


# --- сверка памятки «Кто есть кто.md» с ролями и реестром (metis-0120) ----------------------------
WHO_MEMO = "Кто есть кто.md"
# Роли окон названы по функции, а в памятке — именем бога: hq — `zeus`, workshop — `daedalus-<задача>`; роль
# domain-coordinator — это все координаторы, отдельного имени у неё в памятке нет.
WHO_ALIAS = {"hq": ("zeus",), "workshop": ("daedalus",)}
WHO_ANY_DIRECTION = ("domain-coordinator",)
# «Лишнее» ищем только среди имён, начинающихся с бога: такой код в обратных кавычках — имя роли или направления.
# Остальной код (команды, пути, `claude agents`) под образец не подходит. Список — боги из карты имён и прошлых
# направлений; нового бога дописать сюда (иначе его удалённая роль не будет найдена как лишняя).
WHO_GODS = ("zeus", "athena", "hermes", "themis", "calliope", "mnemo", "proteus", "metis", "janus", "daedalus",
            "apollo", "hephaestus", "argus", "chiron", "prometheus", "talos", "clio", "iris", "momus", "charon", "hestia", "palamedes")
WHO_TOKEN = re.compile(r"`([^`\n]+)`")
WHO_WORD = re.compile(r"[a-z][a-z0-9-]*")
# Ещё места, где роли названы (metis-0252): холст «Кто есть кто.canvas» — по-русски (имя бога или слово), system.md —
# именем роли. Роль без строки здесь — «+имя (файл)» в той же тревоге. Новую роль без бога в холсте искать по её имени.
WHO_CANVAS_RU = {"hq": "Зевс", "workshop": "Дедал", "argus": "Аргус", "momus": "Мом", "prometheus": "Прометей",
                 "chiron": "Хирон", "clio": "Клио", "iris": "Ирида", "talos": "Талос", "hestia": "Гестия", "palamedes": "Паламед",
                 "hephaestus": "Гефест", "apollo": "Аполлон", "dev": "Разработчик", "codex-dev": "Codex",
                 "tg-reader": "Telegram", "domain-coordinator": "координатор"}


def who_is_who_names(text, roles, canvas=False):
    """Имена ролей, которых нет в тексте холста (canvas=True) или system.md. Лидам хватает приставки роли."""
    low = text.lower()
    words = {w.strip("-") for w in WHO_WORD.findall(low)}
    out = []
    for r in sorted(roles):
        keys = [r, r.split("-")[0]] if r.split("-")[0] in LEAD_ROLES or r.startswith("dev-") else [r]
        if canvas:
            ru = [WHO_CANVAS_RU[k].lower() for k in keys if k in WHO_CANVAS_RU] or ([] if r in WHO_CANVAS_RU else [r])
            def has(x):  # граница слева, справа — падежное окончание: «мом» в «Момент» — не роль (metis-0252)
                return re.search(r"(?<!\w)" + re.escape(x) + r"(?:а|у|е|ом|ы|и|ов|ам|ами|ах)?(?!\w)", low) is not None
            ok = any(has(x) for x in ru) or (r.startswith("dev-") and has("разработчик"))
        else:
            ok = any(k in words for k in keys)
        if not ok:
            out.append(r)
    return out


def who_is_who_diff(memo_text, roles, directions):
    """([нет в памятке], [лишнее в памятке]) — имена. roles — стебли файлов ролей, directions — имена направлений."""
    tokens = set(WHO_TOKEN.findall(memo_text))

    def prefix(pre):
        return any(t == pre or t.startswith(pre + "-") for t in tokens)
    missing = []
    for r in sorted(roles):
        if r in WHO_ANY_DIRECTION:
            ok = bool(set(directions) & tokens)
        elif r in WHO_ALIAS:
            ok = r in tokens or any(prefix(a) for a in WHO_ALIAS[r])
        elif r.split("-")[0] in LEAD_ROLES:
            ok = prefix(r.split("-")[0])
        else:
            ok = r in tokens
        if not ok:
            missing.append(r)
    missing += sorted(d for d in directions if d not in tokens)
    known = set(roles) | set(directions) | {"zeus"}
    lead_pre = {r.split("-")[0] for r in roles if r.split("-")[0] in LEAD_ROLES}
    aliases = {a for al in WHO_ALIAS.values() for a in al}
    extra = []
    for t in sorted(tokens):
        if not ROLE_NAME.fullmatch(t) or t.split("-")[0] not in WHO_GODS or t in known:
            continue
        if t in lead_pre or t in aliases or t.startswith("daedalus-"):
            continue
        extra.append(t)
    return missing, extra


def who_is_who_check(memo=None, agents=None, reg_path=None):
    """Сверка памятки. Нет памятки, папки ролей или реестра — None (проверять нечего). Иначе (нет, лишнее)."""
    memo = memo or os.path.join(PANTHEON, WHO_MEMO)
    agents = agents or AGENTS
    reg_path = reg_path or os.path.join(PANTHEON, "directions.toml")
    if not (os.path.isfile(memo) and os.path.isdir(agents) and os.path.isfile(reg_path)):
        return None
    try:
        with open(reg_path, "rb") as fh:
            reg = tomllib.load(fh)
        text = open(memo, encoding="utf-8").read()
    except (OSError, ValueError):
        return None
    roles = {f[:-3] for f in os.listdir(agents)
             if f.endswith(".md") and os.path.isfile(os.path.join(agents, f))}
    # роли из общих шаблонов плагина, ещё не собранные в agents (новая роль сразу после слияния), минус отложенные
    if os.path.isdir(PLUGIN_ROLES):
        roles |= {f[:-5] for f in os.listdir(PLUGIN_ROLES)
                  if f.endswith(".tmpl") and f[:-5] not in ROLES_DEFERRED
                  and os.path.isfile(os.path.join(PLUGIN_ROLES, f))}
    roles = sorted(roles)
    dirs = [d.get("name") for d in reg.get("direction") or [] if isinstance(d.get("name"), str)]
    missing, extra = who_is_who_diff(text, roles, dirs)
    base = os.path.dirname(memo)
    for fname, canvas in (("Кто есть кто.canvas", True), ("system.md", False)):
        try:
            other = open(os.path.join(base, fname), encoding="utf-8").read()
        except OSError:
            continue  # файла нет — не проверяем
        missing += [f"{n} ({fname.rsplit('.', 1)[-1] if canvas else fname})"
                    for n in who_is_who_names(other, roles, canvas)]
    return missing, extra


def who_is_who_alert(**kw):
    """Сверка + тревога штабу «памятку обновить: +имя / −имя» один раз на состояние; совпало — тревога снята.
    Возвращает строку расхождения или ""."""
    got = who_is_who_check(**kw)
    if got is None:
        return ""
    missing, extra = got
    if not (missing or extra):
        clear_once("who-is-who")
        return ""
    sysm = [n for n in missing if n.endswith("(system.md)")]
    rest = [f"+{n}" for n in missing if n not in sysm] + [f"−{n}" for n in extra]
    parts = (["памятку обновить: " + " / ".join(rest)] if rest else [])
    if sysm:  # system.md — не памятка: в тексте тревоги называем его самим именем (metis-0252)
        parts.append("system.md обновить: " + " / ".join("+" + n[:-len(" (system.md)")] for n in sysm))
    line = "; ".join(parts)
    alert_once("who-is-who", line, f"Кто есть кто.md: {line}", "pantheon")
    return line


# --- холст «Кто есть кто.canvas» строится кодом (metis-0825, lib/whocanvas.py) ---------------------
_WHOCANVAS = None


def whocanvas_mod():
    global _WHOCANVAS
    if _WHOCANVAS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_whocanvas", os.path.join(LIB, "whocanvas.py"))
        _WHOCANVAS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_WHOCANVAS)
    return _WHOCANVAS


def who_canvas_inputs(agents=None, reg_path=None):
    """(роли {имя: файл}, направления [{name, short}], статусы задач {id: статус}) для пересборки холста."""
    W, T = whocanvas_mod(), tasks_mod()
    agents = agents or AGENTS
    roles = {}
    if os.path.isdir(PLUGIN_ROLES):  # шаблоны плагина, ещё не собранные в agents, минус отложенные
        roles.update({f[:-5]: os.path.join(PLUGIN_ROLES, f) for f in os.listdir(PLUGIN_ROLES)
                      if f.endswith(".tmpl") and f[:-5] not in ROLES_DEFERRED
                      and os.path.isfile(os.path.join(PLUGIN_ROLES, f))})
    if os.path.isdir(agents):
        roles.update({f[:-3]: os.path.join(agents, f) for f in os.listdir(agents)
                      if f.endswith(".md") and os.path.isfile(os.path.join(agents, f))})
    with open(reg_path or os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
        reg = tomllib.load(fh)
    dirs = [{"name": d["name"], "short": str(d.get("short") or "")} for d in reg.get("direction") or []
            if isinstance(d.get("name"), str)]
    want, statuses = set(W.task_refs()), {}
    for fp in T.task_files(PANTHEON):
        tid = os.path.basename(fp)[:-3]
        if tid in want:
            try:
                statuses[tid] = str((T.read(fp)[0] or {}).get("status") or "")
            except (T.HeaderError, OSError, UnicodeDecodeError):
                pass
    return roles, dirs, statuses


def who_canvas_sync(force=False, agents=None, reg_path=None, manual_out=None, report_out=None):
    """Пересобрать холст, если изменились роли, реестр или статус задач из карточек. 'written' | 'same' | 'unchanged' |
    'skip' (нет ни холста, ни памятки, ни реестра — вести нечего)."""
    canvas = os.path.join(PANTHEON, whocanvas_mod().CANVAS_NAME)
    reg_path = reg_path or os.path.join(PANTHEON, "directions.toml")
    if not os.path.isfile(reg_path) or not (os.path.exists(canvas) or os.path.isfile(os.path.join(PANTHEON, WHO_MEMO))):
        return "skip"
    roles, dirs, statuses = who_canvas_inputs(agents, reg_path)
    return whocanvas_mod().sync(canvas, path("who-canvas.json"), roles, dirs, statuses, force=force,
                                manual_out=manual_out, report_out=report_out)


def who_canvas_cmd(rest):
    """pantheon who-canvas [--force] — зовёт scripts/who-canvas.sh из расписания (every = 5, hosts = primary; самой
    команды нет в TICK_SUBCOMMANDS, parse_command пускает только скрипт плагина): пересборка только при смене
    входов (отпечаток в STATE/who-canvas.json), так что обычный проход ничего не пишет. Холст не читается или сбой —
    тревога, файл не затирается, код 1. В тик не вшито: tick() входит в сборку окон (ядро, metis-0404)."""
    if [a for a in rest if a != "--force"]:
        print("использование: pantheon who-canvas [--force]", file=sys.stderr)
        return 2
    try:
        report = {}
        got = who_canvas_sync(force="--force" in rest, report_out=report)
    except Exception as e:
        msg = f"Кто есть кто.canvas: не пересобран ({type(e).__name__}: {e})"
        alert_once("who-canvas", type(e).__name__, msg, "pantheon")
        print(msg, file=sys.stderr)
        return 1
    clear_once("who-canvas")
    # правка руками (текст, цвет, подпись группы): тревога один раз на текст карточки — значение хеш её текста, новая
    # правка руками даёт новую тревогу (metis-0838 Д9); карточка снова под кодом — метка снята
    for nid, h in sorted((report.get("manual_hash") or {}).items()):
        alert_once("who-canvas-manual-" + nid, h,
                   f"Кто есть кто.canvas: карточка {nid} правлена руками, код её не обновляет; "
                   "чтобы вернуть автосборку — удалите карточку", "pantheon")
    for nid in report.get("auto") or ():
        clear_once("who-canvas-manual-" + nid)
    if got == "written":
        print("Кто есть кто.canvas: пересобран по ролям, реестру и задачам")
    return 0


def roles_newest():
    files = [os.path.join(PANTHEON, "directions.toml")]
    for d in (AGENTS, PARTS, PLUGIN_ROLES, PLUGIN_PARTS):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".tmpl", ".part"))]
    return max((os.path.getmtime(p) for p in files if os.path.exists(p)), default=0)


def owner_approved(name, days=14):
    """Ваше «да» новому направлению: в журнале доски owner-log/board.jsonl (его пишет тик по вашей галочке, роли туда
    не пишут) ответ «Да…» на вопрос «Завести направление <имя>?»; ответу не больше days дней. Текст вопроса тик берёт
    из отмеченной вами карточки (её рисует тик) — правка файла задачи до или после ответа ничего не меняет."""
    since = now() - days * 86400
    # вопрос — ровно «Завести направление <имя>?» в начале, без скрытого Obsidian текста (%%…%%, <!-- -->, теги):
    # имя должно быть там, где вы его видите; ответ — «Да» отдельным словом («Давай позже» — не согласие)
    ask = re.compile(rf"Завести направление [`«\"]?{re.escape(name)}[`»\"]?(?![\w-])")
    yes = re.compile(r"да(?![а-яёa-z0-9])", re.I)
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q = rec.get("question")
        if (rec.get("kind") == "answer" and ts >= since and isinstance(q, str) and ask.match(q.strip())
                and not re.search(r"%%|<", q) and yes.match(str(rec.get("answer") or "").strip())):
            return True
    return False


# Пределы инструкций (исследование 15.10, ~/ai/knowledge/inbox/research-2026-10-15-agents-md.md; docs Claude Code memory).
CLAUDE_LINES = 200          # CLAUDE.md длиннее хуже соблюдается (рекомендация документации, файл грузится целиком)
CODEX_DEFAULT = 32 * 1024   # Codex project_doc_max_bytes: сверх — молча обрезает
SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "target", "__pycache__", "venv", ".venv", "coverage"}


def codex_setup():
    """→ (Codex на этом Mac, лимит байт, байт глобального AGENTS.md). Глобальный файл считаем в тот же бюджет:
    документация Codex говорит о «combined size» без уточнения — берём худший случай."""
    home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    here = os.path.isdir(home) or bool(shutil.which("codex"))
    limit = CODEX_DEFAULT
    try:
        with open(os.path.join(home, "config.toml"), "rb") as fh:
            limit = int(tomllib.load(fh).get("project_doc_max_bytes") or CODEX_DEFAULT)
    except (OSError, ValueError, TypeError):
        pass
    glob_size = 0
    for n in ("AGENTS.override.md", "AGENTS.md"):
        f = os.path.join(home, n)
        if os.path.isfile(f):
            glob_size = os.path.getsize(f)
            break
    return here, limit, glob_size


def _lines(f):
    try:
        with open(f, "rb") as fh:
            return fh.read(4 << 20).count(b"\n")
    except OSError:
        return 0


def _claude_lines(f, depth=0, seen=None):
    """Строки CLAUDE.md вместе с импортами @файл (как грузит Claude Code: до четырёх переходов)."""
    seen = seen if seen is not None else set()
    rf = os.path.realpath(f)
    if rf in seen or depth > 4 or not os.path.isfile(rf):
        return 0
    seen.add(rf)
    n = _lines(rf)
    try:
        text = open(rf, encoding="utf-8", errors="replace").read(1 << 20)
    except OSError:
        return n
    for m in re.finditer(r"(?m)^\s*@(\S+\.md)\s*$", text):
        target = os.path.expanduser(m.group(1))
        n += _claude_lines(target if os.path.isabs(target) else os.path.join(os.path.dirname(rf), target), depth + 1, seen)
    return n


def instruction_files(root, max_depth=5, max_dirs=5000):
    """Папки с инструкциями внутри root → [(папка, байт цепочки Codex от корня git, строк CLAUDE.md с импортами)].
    Codex склеивает AGENTS.override.md (или AGENTS.md) каждой папки от корня git до текущей."""
    out, count = [], 0
    stack = [(os.path.realpath(root), 0, 0)]
    while stack and count < max_dirs:
        d, depth, chain = stack.pop()
        count += 1
        if os.path.isdir(os.path.join(d, ".git")):
            chain = 0
        agents = next((os.path.join(d, n) for n in ("AGENTS.override.md", "AGENTS.md")
                       if os.path.isfile(os.path.join(d, n))), None)
        if agents:
            chain += os.path.getsize(agents)
        claude_md = os.path.join(d, "CLAUDE.md")
        cl = _claude_lines(claude_md) if os.path.isfile(claude_md) else (_lines(agents) if agents else 0)
        if agents or os.path.isfile(claude_md):
            out.append((d, chain, cl))
        if depth >= max_depth:
            continue
        try:
            subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)
                    and not e.name.startswith(".") and e.name not in SKIP_DIRS]
        except OSError:
            subs = []
        stack.extend((e.path, depth + 1, chain) for e in subs)
    return out


DIRECTION_NAME = re.compile(r"[a-z]+-[a-z0-9]+(?:-[a-z0-9]+)*")


def direction_gate(name):
    """Ворота нового направления — общие у `direction check` и `direction init`: имя по образцу, ваше «да» в
    decisions.md, ваша галочка в журнале доски, запись в directions.toml. → ([(готово, что)], запись реестра)."""
    res = []
    add = lambda ok, text: res.append((bool(ok), text))
    add(DIRECTION_NAME.fullmatch(name) and len(name) <= 40 and not reserved_direction(name),
        reserved_direction(name) or f"имя «{name}» по образцу <бог>-<проект>: латиница, цифры, дефис, до 40 знаков")
    try:
        dec = open(os.path.join(PANTHEON, "decisions.md"), encoding="utf-8").read()
    except OSError:
        dec = ""
    said = [l for l in dec.splitlines() if l.startswith("|") and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", l)
            and "Ваши слова" in l]
    add(said, "ваше «да» в decisions.md: строка с именем направления и «Ваши слова»")
    # decisions.md пишет Зевс — сама строка не доказательство; текст реплики тоже (простое «да» подошло бы к любому
    # вопросу). Доказательство — ваша галочка на карточке «Завести направление <имя>?» в журнале доски.
    add(owner_approved(name), "ваша галочка «Да…» на карточке с этим именем в журнале доски (не старше 14 дней)")
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            reg = {d.get("name"): d for d in tomllib.load(fh).get("direction") or []}
    except (OSError, ValueError):
        reg = {}
    d = reg.get(name) or {}
    add(d, "запись в directions.toml")
    return res, d


def direction_check(name):
    """Навык new-direction (ROLE-05, STATE-11): всё ли готово у направления. → [(готово, что)]."""
    res, d = direction_gate(name)
    add = lambda ok, text: res.append((bool(ok), text))
    god = name.split("-", 1)[0]
    add(d.get("does") and d.get("does_not") and 3 <= len(d.get("examples") or []) <= 6,
        "в записи есть does, does_not и 3–5 examples (ROLE-11)")
    folders = [os.path.realpath(os.path.expanduser(f)) for f in d.get("folders") or []]
    add(folders and all(os.path.isdir(f) for f in folders), "папки направления есть на этом Mac")
    launch = launch_folder(d.get("folders"))
    home_dir = os.path.join(PANTHEON, "directions", name)
    add(all(os.path.exists(os.path.join(home_dir, x)) for x in ("STATUS.md", "inbox", "tasks")),
        f"~/ai/pantheon/directions/{name}/: STATUS.md, inbox/, tasks/ (STATE-07)")
    dom = (read_json(path("domains.json"), {}).get("domains") or {}).get(name)
    add(dom, "направление в domains.json (pantheon domains build) — guard его знает")
    add(os.path.isfile(path("settings", name + ".json")), "окно роли settings/" + name + ".json")
    bad_allow = project_allow_problems(launch) if launch else []
    add(not bad_allow, "проектные allow папки запуска не пускают gh pr merge (иначе окно не соберётся, metis-0137)"
        + (": " + "; ".join(f"{os.path.basename(f)} «{r}»" for f, r in bad_allow) if bad_allow else ""))
    agents = os.path.join(launch, "AGENTS.md")
    claude_md = os.path.join(launch, "CLAUDE.md")
    cm = open(claude_md, encoding="utf-8").read(200) if os.path.isfile(claude_md) else None
    add(os.path.isfile(agents) and (cm is None or cm.lstrip().startswith("@AGENTS.md")),
        "AGENTS.md в папке запуска; CLAUDE.md нет или начинается с @AGENTS.md (STATE-12)")
    if os.path.isdir(launch):
        here, limit, glob_size = codex_setup()
        found = instruction_files(launch)
        worst = max((c + glob_size for _, c, _ in found), default=0)
        add(not here or worst <= limit, f"Codex: инструкции до {limit // 1024} КиБ на путь (сейчас {worst // 1024} КиБ"
            + ("" if here else "; Codex на этом Mac нет — не блокирует") + "): сверх Codex молча обрезает")
        longest = max((n for _, _, n in found), default=0)
        add(longest <= CLAUDE_LINES, f"Claude: CLAUDE.md с импортами до {CLAUDE_LINES} строк (сейчас {longest})")
    # доверие — по правилу Claude Code (watch.trusted): у каждой области свой git, «Да» нужно на ней самой
    add(watch_mod().trusted(launch),
        f"доверие к {launch.replace(HOME, '~')} — владелец, одна интерактивная сессия (без него claude --bg не стартует)")
    remote = ""
    if os.path.isdir(os.path.join(launch, ".git")):
        r = subprocess.run(["git", "-C", launch, "remote", "get-url", "origin"], capture_output=True, text=True)
        remote = r.stdout.strip() if r.returncode == 0 else ""
    owner = re.search(r"[:/]([\w.-]+)/[\w.-]+?(?:\.git)?$", remote)
    try:
        env = "\n".join(json.load(open(os.path.join(HOME, ".claude", "settings.json"), encoding="utf-8"))
                        .get("autoMode", {}).get("environment") or [])
    except (OSError, ValueError):
        env = ""
    add(not remote or (owner and (owner.group(1) + "/") in env),
        "владелец remote в autoMode.environment (" + (remote or "remote нет") + ")")
    # действующая часть имён — как в roles_build: личная перекрывает общую из плагина целиком
    mine = os.path.join(PARTS, "names.part")
    names_path = mine if os.path.isfile(mine) else os.path.join(PLUGIN_PARTS, "names.part")
    try:
        names = open(names_path, encoding="utf-8").read()
    except OSError:
        names = ""
    add(f"({name})" in names, f"бог направления ({god}) и его род — в _parts/names.part"
        + ("" if names_path == mine else " (личной нет: скопировать общую из плагина в ~/.claude/agents/_parts/ и дописать)"))
    for lead in d.get("leads") or []:
        short = name.split("-", 1)[-1]
        add(os.path.isfile(os.path.join(AGENTS, f"{lead}-{short}.md")), f"роль лида {lead}-{short} (pantheon roles build)")
    return res


# `pantheon direction init` (metis-0042): папку нового направления создаёт команда, а не Метида — её окну guard и
# песочница не дают писать в ~/projects/<новое>. Ворота — те же, что у check (ваша галочка в журнале доски). Создаёт
# только ровно ~/projects/<x> или ~/ai/life/<x>; существующие папки не трогает, ссылки и «..» — отказ; сначала
# проверяет все папки записи, потом создаёт. Повтор доделывает прерванный запуск и ничего не меняет у готового.
# ~/ai/life — простая папка без .git (Зевс 06.11, metis-0899): у каждой области свой git, init делает то же, что для
# ~/projects/<x>; ~/ai/life при необходимости создаётся как простая папка.
INIT_OWN = {".git", "AGENTS.md"}   # что оставляет init: папка только с этим — начатая им, её можно доделать
INIT_COMMIT = "AGENTS.md (pantheon direction init)"


def _git_env():
    """Окружение git без переменных, которые увели бы его в чужой репозиторий (вызов из хука git)."""
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}


def _init_own(p):
    """Папка пуста или в ней только то, что оставляет init: .git — папка, AGENTS.md — обычный файл, без ссылок; у
    репозитория нет remote и нет коммитов, кроме одного своего (INIT_COMMIT). Пустой клон с remote или чужой коммит —
    чужое, не трогаем. git — с явным --git-dir: сломанный .git не уведёт его в репозиторий выше."""
    try:
        names = os.listdir(p)
    except OSError:
        return False
    if not set(names) <= INIT_OWN:
        return False
    git, agents = os.path.join(p, ".git"), os.path.join(p, "AGENTS.md")
    if os.path.lexists(agents) and (os.path.islink(agents) or not os.path.isfile(agents)):
        return False
    if not os.path.lexists(git):
        return True
    if os.path.islink(git) or not os.path.isdir(git):
        return False
    env = _git_env()
    run = lambda *a: subprocess.run(["git", "--git-dir=" + git, *a], capture_output=True, text=True, env=env)
    r = run("config", "--local", "--get-regexp", r"^remote\.")
    if r.returncode != 1 or r.stdout.strip():   # 1 — ничего не найдено; 0 — есть remote; другое — не репозиторий
        return False
    if run("rev-parse", "--verify", "-q", "HEAD").returncode:
        return True
    return (run("rev-list", "--count", "HEAD").stdout.strip() == "1"
            and run("log", "-1", "--format=%s", "HEAD").stdout.strip() == INIT_COMMIT)


def direction_init(name):
    """pantheon direction init <имя>: папка нового направления по вашей галочке. → код выхода."""
    res, d = direction_gate(name)
    if not all(ok for ok, _ in res):
        for ok, text in res:
            print(("готово  " if ok else "НЕТ     ") + text)
        print("ничего не создано: ворота не пройдены")
        return 1
    folders = d.get("folders") or []
    if not isinstance(folders, list) or not folders:
        print(f"в записи {name} в directions.toml нет folders — нечего создавать")
        return 1
    real_home = os.path.realpath(HOME)
    roots = {"projects": (os.path.join(HOME, "projects"), os.path.join(real_home, "projects")),
             "life": (os.path.expanduser(LIFE_DIR), os.path.join(real_home, *LIFE_DIR[2:].split("/")))}
    short = lambda p: "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p

    def area(p):
        """Где папку можно создать: «projects» — ровно ~/projects/<x>, «life» — ровно ~/ai/life/<x>; None — нигде.
        Один компонент, не скрытый; корень — не ссылка в сторону (сравнение с настоящим путём HOME: сам HOME может
        быть ссылкой, как /var → /private/var)."""
        base = os.path.basename(p)
        if not base or base.startswith("."):
            return None
        for kind, (root, real) in roots.items():
            if os.path.dirname(p) == root and os.path.realpath(root) == real:
                return kind
        return None

    plan, bad = [], []   # plan: (путь, create | resume | skip | busy, projects | life | None)
    for f in folders:
        if not isinstance(f, str) or not f.strip():
            bad.append(f"{f!r}: пустая строка вместо папки — не создаю")
            continue
        if ".." in f.split("/"):
            bad.append(f"{f}: «..» в пути — не создаю")
            continue
        p = os.path.normpath(os.path.expanduser(f))
        a = area(p)
        if not os.path.isabs(p):
            bad.append(f"{f}: не абсолютный путь и не от ~/ — не создаю")
        elif os.path.islink(p):
            bad.append(f"{short(p)}: ссылка — не создаю и не трогаю")
        elif os.path.isdir(p):
            if not a:
                plan.append((p, "skip", a))
            elif _init_own(p):
                plan.append((p, "resume", a))
            else:
                plan.append((p, "busy", a))
        elif os.path.lexists(p):
            bad.append(f"{short(p)}: есть, но не папка — не трогаю")
        elif a:
            plan.append((p, "create", a))
        else:
            bad.append(f"{short(p)}: вне ~/projects и {LIFE_DIR} — не создаю (новая папка — только ~/projects/<имя> "
                       f"или {LIFE_DIR}/<имя>)")
    life = roots["life"][0]
    if any(a == "life" and kind == "create" for _, kind, a in plan) and os.path.lexists(life) and not os.path.isdir(life):
        bad.append(f"{short(life)}: есть, но не папка — не трогаю")
    if bad:
        for x in bad:
            print("отказ   " + x)
        print("ничего не создано: сначала поправить folders в directions.toml")
        return 1

    # папка запуска — по правилу start (launch_folder): первая существующая папка записи; после init есть все, значит
    # это первая папка записи. git init, AGENTS.md и коммит — только если её создаёт или доделывает init
    launch = plan[0][0]
    note = " — папка запуска: AGENTS.md в ней дописывает координатор направления"
    rc = 0
    for p, kind, a in plan:
        if kind == "skip":
            print(f"есть, пропущено {short(p)}" + (note if p == launch else ""))
            continue
        if kind == "busy":
            print(f"есть, не пуста — не трогаю {short(p)}" + (note if p == launch else ""))
            continue
        if kind == "create":
            try:
                os.makedirs(roots[a][0], exist_ok=True)
                os.mkdir(p)
            except OSError as e:
                print(f"отказ   {short(p)}: не создана ({e.strerror or e})")
                return 1
        if p != launch:
            print(f"создано {short(p)}" if kind == "create" else f"есть, пропущено {short(p)}")
            continue
        done, err = _init_launch(p, name, d)
        if kind == "create":
            print(f"создано {short(p)}" + (": " + ", ".join(done) if done else ""))
        elif done:
            print(f"доделано {short(p)}: " + ", ".join(done))
        elif not err:
            print(f"есть, пропущено {short(p)}")
        if err:
            print(f"сбой    {short(p)}: {err}")
            rc = 1
    return rc


def _init_launch(p, name, d):
    """Папка запуска: git init, стартовый AGENTS.md, первый коммит — только недостающее. → ([что сделано], ошибка)."""
    env = _git_env()
    git = lambda *a: subprocess.run(["git", "-C", p, *a], capture_output=True, text=True, env=env)
    done = []
    if not os.path.lexists(os.path.join(p, ".git")):
        r = git("init", "-q", "-b", "main")
        if r.returncode:
            return done, "git init: " + (r.stderr.strip() or f"код {r.returncode}")
        done.append("git init")
    agents = os.path.join(p, "AGENTS.md")
    if not os.path.lexists(agents):
        text = (f"# {d.get('project') or os.path.basename(p)}\n\n"
                f"Направление Пантеона `{name}`.\n\n"
                f"Что делает: {d.get('does') or '—'}\n\n"
                f"Чего не делает: {d.get('does_not') or '—'}\n\n"
                "Команды сборки и тестов — дополнит координатор.\n")
        try:
            with open(agents, "x", encoding="utf-8") as fh:   # "x": не перезапишет и не пройдёт по ссылке
                fh.write(text)
        except OSError as e:
            return done, f"AGENTS.md: {e.strerror or e}"
        done.append("AGENTS.md")
    if git("rev-parse", "--verify", "-q", "HEAD").returncode:
        r = git("add", "--", "AGENTS.md")
        if r.returncode == 0:
            r = git("commit", "-q", "-m", INIT_COMMIT, "--", "AGENTS.md")
        if r.returncode:
            return done, "git commit: " + ((r.stderr or r.stdout).strip() or f"код {r.returncode}") + \
                " — повтор `pantheon direction init` доделает"
        done.append("коммит")
    return done, ""


def direction(rest):
    """pantheon direction check <имя> — что готово у нового направления (навык new-direction).
    pantheon direction init <имя>  — папка ~/projects/<имя> по вашей галочке: git init, AGENTS.md, локальный коммит;
                                     без remote. ~/ai/life/<имя> — то же, свой git у каждой области."""
    if len(rest) != 2 or rest[0] not in ("check", "init"):
        print(direction.__doc__, file=sys.stderr)
        return 2
    if rest[0] == "init":
        return direction_init(rest[1])
    res = direction_check(rest[1])
    for ok, text in res:
        print(("готово  " if ok else "НЕТ     ") + text)
    return 0 if all(ok for ok, _ in res) else 1


# --- установка ----------------------------------------------------------------------

PLIST_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{tick}</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Standard</string>
  <key>AbandonProcessGroup</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


INSTALLED_PLUGINS = os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")


def _verified_path():
    return path("plugins", "verified.json")


_HASH_MEMO = {}


def _tree_stamp(root):
    """Отпечаток дерева без чтения файлов: sha256 по каждой записи — путь, ctime_ns, размер, inode, mtime_ns. Одного
    mtime мало (ревью 90b, круг 4): подмену файла с возвратом mtime через os.utime выдаёт ctime — его utime не вернуть;
    замену файла другим — inode; новая или удалённая запись меняет список."""
    rows = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
        for x in [d] + [os.path.join(d, f) for f in files + dirs]:
            with contextlib.suppress(OSError):
                st = os.lstat(x)
                rows.append((os.path.relpath(x, root), st.st_ctime_ns, st.st_size, st.st_ino, st.st_mtime_ns))
    return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()


def _tree_hash_cached(root):
    """_tree_hash с кэшем по (путь, отпечаток mtime дерева): сборка окон и проход тика не перечитывают кэш плагина
    каждый раз. Кэш — в памяти и в состоянии тика; записать не вышло (окно роли) — только в памяти."""
    if not isinstance(root, str) or not os.path.isdir(root):
        return None
    real = os.path.realpath(root)
    stamp_ = _tree_stamp(real)
    memo = _HASH_MEMO.get(real)
    if memo and memo[0] == stamp_:
        return memo[1]
    cache_p = path("plugins", "hash-cache.json")
    disk = read_json(cache_p, {})
    disk = disk if isinstance(disk, dict) else {}
    row = disk.get(real)
    if isinstance(row, dict) and row.get("stamp") == stamp_ and isinstance(row.get("hash"), str):
        _HASH_MEMO[real] = (stamp_, row["hash"])
        return row["hash"]
    h = _tree_hash(real)
    _HASH_MEMO[real] = (stamp_, h)
    disk[real] = {"stamp": stamp_, "hash": h}
    with contextlib.suppress(OSError):
        write_json(cache_p, {k: v for k, v in disk.items() if os.path.isdir(k)})
    return h


def _cache_tree(p):
    """realpath папки p, если это дерево плагина внутри ~/.claude/plugins/cache (есть .claude-plugin/plugin.json)."""
    cache = os.path.realpath(os.path.join(HOME, ".claude", "plugins", "cache")) + os.sep
    if isinstance(p, str) and os.path.realpath(p).startswith(cache) and os.path.isdir(p) \
            and os.path.isfile(os.path.join(p, ".claude-plugin", "plugin.json")):
        return os.path.realpath(p)
    return None


def verified_record(name):
    """Запись verified.json о плагине name: {hash, path, version, at, by}; нет, битая или без хеша — None."""
    data = read_json(_verified_path(), {})
    rec = data.get(name) if isinstance(data, dict) else None
    return rec if isinstance(rec, dict) and isinstance(rec.get("hash"), str) and rec["hash"] else None


def installed_dir(name, checked=True):
    """Дерево плагина name@agent-kit, с которым работает живой код: current, `pantheon install`, хуки окон ролей,
    версия в status (metis-0321). Разрешение, а не запрет: годится только дерево, чей хеш совпал с verified.json (его
    пишет успешная установка plugins-update — выпуск после CI и сверка — или ваша команда `pantheon plugins accept`).
    1. installPath из installed_plugins.json (уровень пользователя, внутри ~/.claude/plugins/cache) с хешем из записи.
    2. Иначе — последнее проверенное дерево по пути из записи, если оно цело (хеш тот же), и тревога.
    3. Иначе None и тревога: проверенного нет. Клон маркетплейса — никогда.
    checked=False — сырой installPath без сверки: только для записи в verified.json (accept). Тест-страж
    test_live_code не пускает checked=False за пределы plugins_accept."""
    data = read_json(INSTALLED_PLUGINS)
    rows = (data.get("plugins") if isinstance(data, dict) else None) or {}
    rows = rows.get(f"{name}@{MARKETPLACE}") if isinstance(rows, dict) else None
    raw = None
    for row in rows if isinstance(rows, list) else []:
        raw = _cache_tree(row.get("installPath") if isinstance(row, dict) and row.get("scope") == "user" else None)
        if raw:
            break
    if not checked:
        return raw
    rec = verified_record(name)
    if rec and raw and _tree_hash_cached(raw) == rec["hash"]:
        return raw
    last = _cache_tree(rec.get("path")) if rec else None
    if last and _tree_hash_cached(last) == rec["hash"]:
        if raw != last:
            _unverified_alert(name, raw or "—", f"живой код и окна остаются на последнем проверенном "
                              f"{last.replace(HOME, '~')}")
        return last
    _unverified_alert(name, raw or "—", "проверенного дерева нет: current не перевешивается, окна ролей закрыты "
                      "(строгий guard не найден)")
    return None


def _unverified_alert(name, where, what):
    with contextlib.suppress(Exception):  # окно роли не пишет в состояние — сборку и status это не роняет
        alert_once(f"plugins-unverified-{name}", f"{where} {what[:60]}",
                   f"{name}: установленное дерево {where.replace(HOME, '~')} не проверено (нет в verified.json) — {what}. "
                   f"Что делать — README agent-kit, «Живой код»; принять руками — pantheon plugins accept {name}",
                   "plugins-update")


def link_current(target):
    """CURRENT → target одной заменой (ссылка рядом и os.replace): тик, запущенный в эту секунду, не застанет дыры."""
    os.makedirs(os.path.dirname(CURRENT), exist_ok=True)
    if os.path.islink(CURRENT) and os.readlink(CURRENT) == target:
        return target
    tmp = f"{CURRENT}.new-{os.getpid()}"
    with contextlib.suppress(FileNotFoundError):
        os.remove(tmp)
    os.symlink(target, tmp)
    if os.path.isdir(CURRENT) and not os.path.islink(CURRENT):
        shutil.rmtree(CURRENT)  # не ссылка, а папка (ручная правка): os.replace на папку не встанет
    os.replace(tmp, CURRENT)
    return target


def install():
    """Задача launchd, команда pantheon и обработчики слияния ~/ai/pantheon — через неизменную ссылку CURRENT."""
    os.makedirs(path("logs"), exist_ok=True)
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    want = installed_dir("pantheon")  # только проверенное дерево (verified.json); клон и рабочая копия — никогда
    target = link_current(want) if want else (os.path.realpath(CURRENT) if os.path.lexists(CURRENT) else "—")
    if not want:
        print("pantheon install: проверенного дерева pantheon нет (verified.json) — current не тронута. "
              "Принять установленное: pantheon plugins accept", file=sys.stderr)
    tick_bin = os.path.join(CURRENT, "bin", "pantheon-tick")
    env_path = ":".join([os.path.dirname(sys.executable), "/opt/homebrew/bin",
                         os.path.join(HOME, ".local", "bin"), "/usr/bin:/bin:/usr/sbin:/sbin"])
    with open(PLIST, "w") as fh:
        fh.write(PLIST_TMPL.format(label=LABEL, tick=tick_bin, path=env_path, log=path("logs", "tick.log")))
    for cmd in ("pantheon", "heavy"):  # heavy — обёртка тяжёлых команд для ролей (MEM-03)
        link = os.path.join(HOME, ".local", "bin", cmd)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(os.path.join(CURRENT, "bin", cmd), link)
    link = os.path.join(HOME, ".local", "bin", "pantheon")
    with contextlib.suppress(OSError):  # файл или ссылка на месте папки — не повод ронять сборку
        os.makedirs(path("locks", "heavy-queue"), exist_ok=True)  # билеты очереди обёртки heavy (metis-0659)
    os.makedirs(path("locks"), exist_ok=True)
    for slot in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
        open(path("locks", slot + ".lock"), "a").close()
    if os.path.isdir(os.path.join(PANTHEON, ".git")):
        merge = os.path.join(CURRENT, "scripts", "git-crypt-merge.sh")
        git("config", "merge.gitcrypt-text.name", "git-crypt text merge")
        git("config", "merge.gitcrypt-text.driver", f"{merge} %O %A %B")
        git("config", "merge.gitcrypt-union.name", "git-crypt union merge (дописываемые файлы)")
        git("config", "merge.gitcrypt-union.driver", f"{merge} --union %O %A %B")
    uid = os.getuid()
    drop_old(OLD_TICK_GLOB)  # тик под прежней меткой — снять, пока не встал новый
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} install-bootstrap {LABEL}\n")
        print(f"установлено (dryrun): {PLIST.replace(HOME, '~')}")
        return 0
    build_app()
    merge_mod().build_helper(quiet=False)  # окно Touch ID для слияния ядра (metis-0285); не собран — заявки ждут
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    print(f"установлено: {PLIST.replace(HOME, '~')} и команда {link.replace(HOME, '~')} → "
          f"{CURRENT.replace(HOME, '~')} → {target.replace(HOME, '~')}")
    return 0


MERGE_REQUEST_CMDS = ["pantheon merge request *", "pantheon merge status", "pantheon merge cancel *"]


def merge_kick():
    """Заявки на слияние по Touch ID (metis-0285) и отставшие управляемые настройки guard (metis-0710) — отдельным
    процессом: окно ждёт пальца до двух минут, тик не ждёт."""
    try:
        if not (merge_mod().pending() or merge_mod().managed_check()) or locked("merge-run"):
            return
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            with open(path("dryrun.log"), "a") as fh:
                fh.write(f"{int(now())} merge-run\n")
            return
        # окружение — с нуля (metis-0303): окружение тика задаёт launchd, а его меняет launchctl setenv
        subprocess.Popen([os.path.join(PLUGIN, "bin", "pantheon"), "merge", "run"], env=merge_mod().pass_env(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:  # сбой слияния не должен останавливать тик
        alert_once("merge-kick", type(e).__name__, f"слияние по Touch ID: проход не запущен ({type(e).__name__}: {e})",
                   "pantheon-tick")


def handoff_kick():
    """Отказ роли → Touch ID владельца на одно действие из белого списка (metis-0832, 0775, lib/handoff.py) —
    отдельным процессом: окно ждёт пальца до двух минут, тик не ждёт. Без заявок и строк журнала в кэшах окон — нет."""
    try:
        if locked("handoff-run") or not handoff_mod().pending():
            return
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            with open(path("dryrun.log"), "a") as fh:
                fh.write(f"{int(now())} handoff-run\n")
            return
        subprocess.Popen([os.path.join(PLUGIN, "bin", "pantheon"), "handoff", "run"], env=outside_mod().pass_env(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:  # сбой прохода не должен останавливать тик
        alert_once("handoff-kick", type(e).__name__, f"Touch ID действий роли: проход не запущен ({type(e).__name__}: "
                   f"{e})", "pantheon-tick")


def outside_kick():
    """Проверки вне окна роли ([sb-simplify] п. 7, lib/outside.py) — два отдельных процесса со своими замками: проход
    тестов (`outside run`, тесты идут минутами и часами) и проход серверов (`outside run --serve`, сторож живёт, пока
    есть серверы). Сервер и «стоп» не ждут тестов (metis-0614)."""
    for name, flag, due in (("outside-run", [], "pending_test"), ("outside-serve", ["--serve"], "pending_serve")):
        try:
            if locked(name) or not getattr(outside_mod(), due)():
                continue
            if os.environ.get("PANTHEON_DRYRUN") == "1":
                with open(path("dryrun.log"), "a") as fh:
                    fh.write(f"{int(now())} {name}\n")
                continue
            subprocess.Popen([os.path.join(PLUGIN, "bin", "pantheon"), "outside", "run", *flag],
                             env=outside_mod().pass_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as e:  # сбой проверок не должен останавливать тик
            alert_once("outside-kick", type(e).__name__,
                       f"проверки вне окна: проход {name} не запущен ({type(e).__name__}: {e})", "pantheon-tick")

def build_app():
    """~/Applications/Доска.app: Spotlight «Доска» и значок в Dock открывают доску в Obsidian."""
    import tempfile
    with open(os.path.join(LIB, "board-app.applescript"), encoding="utf-8") as fh:
        src = fh.read().replace("BOARD_URL", board_url())
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "app.applescript")
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(src)
        os.makedirs(os.path.dirname(APP), exist_ok=True)
        r = subprocess.run(["osacompile", "-o", APP, sp], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"программа «Доска» не собрана: {r.stderr.strip()}", file=sys.stderr)
        return
    plist = os.path.join(APP, "Contents", "Info.plist")
    subprocess.run(["plutil", "-replace", "CFBundleIdentifier", "-string", "pantheon.board", plist],
                   capture_output=True)
    if not _notifier():
        print("для уведомлений с переходом в карточку: brew install terminal-notifier", file=sys.stderr)
    subprocess.run(["codesign", "--force", "--sign", "-", APP], capture_output=True)


def uninstall():
    dry = os.environ.get("PANTHEON_DRYRUN") == "1"
    if dry:
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} uninstall-bootout {LABEL}\n")
    else:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    drop_old(OLD_TICK_GLOB)
    drop_old(OLD_SVC_GLOB)
    agents = os.path.dirname(PLIST)
    with contextlib.suppress(OSError):
        for f in os.listdir(agents):
            if f.startswith(SVC_PREFIX) and f.endswith(".plist"):
                if not dry:
                    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{f[:-6]}"], capture_output=True)
                os.remove(os.path.join(agents, f))
    for p in (PLIST, os.path.join(HOME, ".local", "bin", "pantheon"), os.path.join(HOME, ".local", "bin", "heavy")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    print("снято: задачи launchd (плановый проход и службы) и команды pantheon и heavy (метки в ~/.local/state/pantheon остались)")
    return 0


_TASKS = None
_NOTIFY = None


def notify_mod():
    """lib/notify.py — политика уведомлений (загрузка как у tasks_mod: python3 -I не кладёт папку скрипта в путь)."""
    global _NOTIFY
    if _NOTIFY is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_notify", os.path.join(LIB, "notify.py"))
        _NOTIFY = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_NOTIFY)
    return _NOTIFY


_AWAKE = None


def awake_mod():
    """lib/awake.py — запрет сна Mac, возобновление после недельного лимита, возобновление ждущих сессий (ночной цикл,
    metis-0126/0127/0132)."""
    global _AWAKE
    if _AWAKE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_awake", os.path.join(LIB, "awake.py"))
        _AWAKE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_AWAKE)
        _AWAKE.set_core(sys.modules[__name__])
    return _AWAKE


_METRICS = None


def metrics_mod():
    """lib/metrics.py — учёт по задачам: исполнитель, модель, расход, круги argus (metis-0294)."""
    global _METRICS
    if _METRICS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_metrics", os.path.join(LIB, "metrics.py"))
        _METRICS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_METRICS)
    return _METRICS


def metrics_ctx():
    """Ctx учёта; repos — [merge_repos] из policy.toml: чей PR, названный в журнале задачи просто номером."""
    try:
        with open(os.path.join(HOME, ".claude", "pantheon", "policy.toml"), "rb") as fh:
            repos = tomllib.load(fh).get("merge_repos")
    except (OSError, ValueError, tomllib.TOMLDecodeError):  # ValueError — в том числе UnicodeDecodeError
        repos = None
    return metrics_mod().Ctx(PANTHEON, STATE, HOME, now(), BOARD, repos if isinstance(repos, dict) else None)


def metrics_on_close(T, tid):
    """Строка учёта при закрытии задачи. Не вышло (песочница роли не пускает в metrics/) — смена статуса остаётся,
    строку допишет плановый проход доски."""
    if os.environ.get("PANTHEON_METRICS") == "0":
        return
    try:
        metrics_mod().record(metrics_ctx(), T.load_tasks(PANTHEON, T.WORK_TYPES), tid)
    except PermissionError:
        # metis-0820: так всегда в окне роли (песочница). «предупреждение · … PermissionError» роли читали как сбой
        # task set и заводили задачи (hermes-0018, 05.11), хотя статус записан, а строку пишет плановый проход (sync)
        print(f"учёт {tid}: окно роли в metrics/ не пишет — строку учёта допишет плановый проход доски. Статус задачи "
              f"записан, это не сбой", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — учёт не должен ломать закрытие задачи
        print(f"предупреждение · учёт {tid} не записан ({type(e).__name__}): допишет плановый проход доски",
              file=sys.stderr)


def metrics_cmd(rest):
    M, T = metrics_mod(), tasks_mod()
    sub, args = (rest[0] if rest else ""), rest[1:]
    if sub == "run":
        return metrics_run()
    tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
    ctx = metrics_ctx()
    if sub == "sync":
        rows = M.sync(ctx, tasks)
        M.publish(ctx, tasks)
        print(f"учёт: строк дописано {len(rows)}; свод — {tilde(os.path.dirname(ctx.rows_path))}")
        return 0
    if sub == "summary":
        print(M.week_md(M.summary(M.read_rows(ctx.rows_path), ctx.t, M.post_merge_index(tasks),
                                M.merged_index(tasks)), ctx.t))
        return 0
    if sub == "backfill":
        opts, dry, i = {}, False, 0
        while i < len(args):
            if args[i] == "--dry-run":
                dry, i = True, i + 1
            elif args[i] in ("--from", "--to") and i + 1 < len(args) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", args[i + 1]):
                opts[args[i][2:]], i = args[i + 1], i + 2
            else:
                print(f"pantheon metrics backfill: непонятно «{args[i]}» — нужно --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] "
                      "[--dry-run]", file=sys.stderr)
                return 2
        if "from" not in opts:
            print("pantheon metrics backfill: нужно --from ГГГГ-ММ-ДД", file=sys.stderr)
            return 2
        rows = M.backfill(ctx, tasks, opts["from"], opts.get("to"), dry=dry)
        for r in rows:
            print(f"{r['id']}\t{r['closed']}\t{r['executor']}\t{r['model']}\t{r['effort']}\t${r['usd']:.2f}\t"
                  f"кругов {r['argus_rounds']}\tоценка")
        print(f"задним числом: {len(rows)} строк" + (" (проба, не записано)" if dry else f" → {tilde(ctx.rows_path)}"))
        if not dry:
            M.publish(ctx, tasks)
        return 0
    print("pantheon metrics sync | summary | run | backfill --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] [--dry-run]", file=sys.stderr)
    return 2


def owner_acts():
    """→ (ответы, переносы в «Нужен ответ»), оба {id: [метка времени, …]}. Ответы — из журнала доски (answer и
    request с вариантом, move не в «Нужен ответ») и окна вопросов Зевса (вопрос «[id] …»); перенос карточки в «Нужен
    ответ» вами самими — не ответ, а знак «пингов не надо». Только журналы, которые пишут хук и тик: поле answer
    файла задачи и текст других сессий ответом не считаются."""
    out, put = {}, {}
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
            t = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        kind, tid = rec.get("kind"), rec.get("id")
        if not isinstance(tid, str):
            continue
        if (kind in ("answer", "request") and isinstance(rec.get("answer"), str) and rec["answer"].strip()
                or kind == "move" and rec.get("dst") not in ("Нужен ответ", "Ждёт вас")):
            out.setdefault(tid, []).append(t)
        elif kind == "move":
            put.setdefault(tid, []).append(t)
    try:
        with open(path("owner-log", "zeus.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    # как consent: пометку «окно вопросов» или «ответ в чате» ставит хук, ответ — на вопрос, который начинается с [<id>]
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if not answers_mod().is_answer_head(m.group(2)):
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q = re.match(r"вопрос: \[([^\]\s]{1,40})\]", body, re.I)
        if not q:
            continue
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        out.setdefault(q.group(1).lower(), []).append(t)
    return out, put


def owner_log_fns():
    """→ (answered, owner_put). answered(id, since) — время (ISO) первого ответа владельца по id не раньше since,
    иначе None; owner_put(id, since) — вы сами перенесли карточку в «Нужен ответ» не раньше since. Журналы читаются
    один раз за проход и лениво — после того, как проход доски записал новые ходы."""
    cache = []

    def acts():
        if not cache:
            cache.append(owner_acts())
        return cache[0]

    def answered(tid, since):
        hits = sorted(x for x in acts()[0].get(tid, []) if x >= int(since))
        return notify_mod().iso(hits[0]) if hits else None

    def owner_put(tid, since):
        return any(x >= int(since) for x in acts()[1].get(tid, []))
    return answered, owner_put


def notify_policy(sched=None):
    """Политика уведомлений на этот проход; вызывать под lock("notify") и закончить save()."""
    N = notify_mod()
    if sched is None:
        try:
            sched = load_schedule()
        except (OSError, ValueError):
            sched = {}
    answered, owner_put = owner_log_fns()
    return N.Policy(path("notify.json"), path("notify-log.jsonl"), sched.get("notify") or N.settings(), now(),
                    idle=idle_sec, send=lambda text, title, target, group: notify(text, title, target, group),
                    answered=answered, owner_put=owner_put)


def notify_critical(text, title="Пантеон · критично", group="critical", policy=None):
    """Критичное (COMM-08): уведомление сразу, мимо блокировки прохода доски; учёт в бюджете и журнале — под
    lock("notify"), не взяли за 5 с — без учёта (отправка уже ушла). policy — уже взятая под блокировкой."""
    if policy is not None:
        policy.critical(text, title, group=group)
        return
    notify(text, title=title, group=group)
    deadline = time.time() + 5
    while True:
        with lock("notify", block=False) as got:
            if got:
                pol = notify_policy()
                pol.critical(text, title, send=False, group=group)
                pol.save()
                return
        if time.time() > deadline:
            return
        time.sleep(0.1)


def notify_soon(key, text, group=None, policy=None, once=False):
    """Сбой класса «скоро»: macOS только если вас нет у Mac, не ночью и в бюджете, одна на ключ события за час; иначе —
    в утреннюю сводку. key — событие (по нему повтор), group — вид в Центре уведомлений (заменяет прежнее того же
    вида). Событие, которое держится, вызывать каждый проход: дойдёт, когда вы уйдёте от Mac. policy — уже взятая под
    lock("notify") (flock в том же процессе второй раз не взять). once — событие, которое держится: одна macOS, пока
    его не снимет clear_fault."""
    if policy is not None:
        policy.fault(key, text, group=group, once=once)
        return
    with lock("notify"):
        pol = notify_policy()
        pol.fault(key, text, group=group, once=once)
        pol.save()


def clear_fault(*keys):
    """Событие снято — сбросить его в политике уведомлений (следующее такое — снова macOS). Без записи, если сбрасывать
    нечего: дежурный зовёт это на каждом проходе."""
    st = read_json(path("notify.json"))
    if not any(k in (st.get("faults") or {}) for k in keys):
        return
    with lock("notify"):
        pol = notify_policy()
        if any([pol.clear_fault(k) for k in keys]):
            pol.save()


def qmd_mod():
    """lib/qmd.py — общий поиск qmd (шаг 1.5)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_qmd", os.path.join(LIB, "qmd.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.set_core(sys.modules[__name__])
    return m


def executors_mod():
    """lib/executors.py — исполнители кода (Claude, Codex) и обёртка pantheon exec codex."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_executors", os.path.join(LIB, "executors.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _task_head(tid):
    got = tasks_mod().load_tasks(PANTHEON).get(tid)
    return got[1] if got else None


_NIGHT = None


def moved_mod():
    """lib/moved.py — таблица переносов папок, migrate-paths и check --moved (metis-0899)."""
    global _MOVED
    if _MOVED is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_moved", os.path.join(LIB, "moved.py"))
        _MOVED = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MOVED)
    return _MOVED


_MOVED = None
MOVED_EVERY = 6 * 3600   # check --quiet (тик) ищет старые пути не чаще раза в 6 ч: обход ~/ai и ~/.claude не мгновенный


def migrate_paths_cmd(rest):
    """pantheon migrate-paths <перенос>… [--dry-run] — переносы: agent-kit, workshop, finances (lib/moved.py)."""
    M = moved_mod()
    names = [a for a in rest if not a.startswith("-")]
    unknown = [a for a in rest if a.startswith("-") and a != "--dry-run"] + [n for n in names if n not in M.MOVES]
    if not names or unknown:
        print(f"pantheon migrate-paths <{'|'.join(M.MOVES)}>… [--dry-run]"
              + (f": не знаю {', '.join(unknown)}" if unknown else ""), file=sys.stderr)
        return 2
    return M.migrate(list(dict.fromkeys(names)), "--dry-run" in rest, HOME)


def check_moved(quiet=False, force=False):
    """Старые пути сделанных переносов в живых файлах (metis-0899) — предупреждение, а на тике — тревога раз в набор.
    Пока ни один перенос не сделан, не обходит ничего. → число файлов со старыми путями."""
    M = moved_mod()
    if not any(M.done(n, HOME) for n in M.MOVES):
        if not force:
            clear_once("check-moved")
            return 0
    elif quiet and not force:
        stamp = path("moved-check.stamp")
        with contextlib.suppress(OSError):
            if time.time() - os.stat(stamp).st_mtime < MOVED_EVERY:
                return 0
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(stamp), exist_ok=True)
            open(stamp, "w").close()
    found, pending, n_personal = M.check(HOME)
    short = lambda p: "~" + p[len(HOME):] if p.startswith(HOME + "/") else p
    # личное — только числом: имя файла в me/Self/Areas/People не уходит ни в вывод, ни в alerts.md (argus-2 Б2)
    personal = (f"личное ~/ai/knowledge ({', '.join(M.PERSONAL)}): {n_personal} файлов — его меняет Мнемозина"
                if n_personal else "")
    if force:
        for n in pending:
            print(f"перенос {n} ещё не сделан — его пути не проверяю")
    for p, k in (found if force else found[:20]):
        if not quiet:
            print(f"предупреждение · старый путь · {short(p)}: {k} — pantheon migrate-paths <перенос>")
    if len(found) > 20 and not force and not quiet:
        print(f"предупреждение · старый путь ещё в {len(found) - 20} файлах — pantheon check --moved")
    if personal and not quiet:
        print(f"предупреждение · старый путь · {personal}")
    total = len(found) + n_personal
    if quiet:
        if total:
            first = f"{short(found[0][0])}…" if found else personal
            alert_once("check-moved", "|".join(p for p, _ in found) + f"|personal={n_personal}",
                       f"старые пути перенесённых папок в {total} файлах: {first} — "
                       "pantheon check --moved, замена — pantheon migrate-paths", "check")
        else:
            clear_once("check-moved")
    elif force:
        print(f"старых путей: {total} файлов" if total else "старых путей нет")
    return total


def night_mod():
    """lib/night.py — темп недельного лимита и ночной цикл (metis-0127, 0128, 0129)."""
    global _NIGHT
    if _NIGHT is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_night", os.path.join(LIB, "night.py"))
        _NIGHT = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_NIGHT)
        _NIGHT.set_core(sys.modules[__name__])
    return _NIGHT


_READ = None


def read_mod():
    """lib/read.py — чтение личного чата по заявке с согласием владельца (metis-0267)."""
    global _READ
    if _READ is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_read", os.path.join(LIB, "read.py"))
        _READ = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_READ)
        _READ.set_core(sys.modules[__name__])
    return _READ


_MERGE = None


def merge_mod():
    """lib/merge.py — слияние PR ядра по заявке и Touch ID владельца (metis-0285)."""
    global _MERGE
    if _MERGE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_merge", os.path.join(LIB, "merge.py"))
        _MERGE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MERGE)
        _MERGE.set_core(sys.modules[__name__])
    return _MERGE


_OUTSIDE = None


def outside_mod():
    """lib/outside.py — тесты и dev-сервер вне окна роли ([sb-simplify] п. 7)."""
    global _OUTSIDE
    if _OUTSIDE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_outside", os.path.join(LIB, "outside.py"))
        _OUTSIDE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_OUTSIDE)
        _OUTSIDE.set_core(sys.modules[__name__])
    return _OUTSIDE

_HANDOFF = None


def handoff_mod():
    """lib/handoff.py — отказ роли → способный исполнитель, Touch ID на одно действие (metis-0832, 0775)."""
    global _HANDOFF
    if _HANDOFF is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_handoff", os.path.join(LIB, "handoff.py"))
        _HANDOFF = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_HANDOFF)
        _HANDOFF.set_core(sys.modules[__name__])
    return _HANDOFF


_RELEASE_TICK = None


def release_tick_mod():
    """lib/release_tick.py — выпуск без Actions: release.py --push из копии на origin/main (metis-0880)."""
    global _RELEASE_TICK
    if _RELEASE_TICK is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_release_tick", os.path.join(LIB, "release_tick.py"))
        _RELEASE_TICK = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_RELEASE_TICK)
        _RELEASE_TICK.set_core(sys.modules[__name__])
    return _RELEASE_TICK


_BROWSER = None


def browser_mod():
    """lib/browser.py — браузер владельца для ролей без пароля и порта (metis-0760)."""
    global _BROWSER
    if _BROWSER is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_browser", os.path.join(LIB, "browser.py"))
        _BROWSER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_BROWSER)
        _BROWSER.set_core(sys.modules[__name__])
    return _BROWSER


_MMV = None


def mmv_mod():
    """lib/mmv.py — замер минут владельца (metis-0169); самостоятельный модуль, STATE передаётся при вызове."""
    global _MMV
    if _MMV is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_mmv", os.path.join(LIB, "mmv.py"))
        _MMV = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MMV)
    return _MMV


def traces_mod():
    """lib/traces.py — личные следы до push (metis-0414); самостоятельный модуль."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_traces", os.path.join(LIB, "traces.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tasks_mod():
    """lib/tasks.py — схема задач и доска владельца (python3 -I не кладёт папку скрипта в путь импорта)."""
    global _TASKS
    if _TASKS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_tasks", os.path.join(LIB, "tasks.py"))
        _TASKS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TASKS)
        _TASKS.set_root(PANTHEON)  # внутри ~/ai/pantheon — ввод-вывод без перехода по ссылкам
    return _TASKS


_ANSWERS = None


def answers_mod():
    """lib/answers.py — какие записи owner-log считаются ответом владельца: окно вопросов и ответ в чате (metis-0405);
    общий с хуком hooks/ctx.py."""
    global _ANSWERS
    if _ANSWERS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_answers", os.path.join(LIB, "answers.py"))
        _ANSWERS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ANSWERS)
    return _ANSWERS


BOARD = os.path.join(VIEW, "Доска")


# --- ответ владельца по карантину ~/.claude (SEC-15) ---------------------------------------------------------
# sync.sh читает ответ с доски только при своём запуске — на старте сессии. Тик после board проверяет: есть
# держание (.sync-held или .sync-incoming), а в журнале ваших слов (owner-log/board.jsonl) по его задаче — ответ
# «отправить» или «откатить»; тогда запускает sync.sh сам. Решает по-прежнему sync.sh по тому же журналу; здесь —
# только «пора». Без ответа или «пока держать» — ничего не запускает. После sync.sh с кодом 0 функция сама снимает вопрос
# с карточки, если ответ есть в SYNC_ACT и держание задачи снято (sync.sh с кодом 0 мог ничего не применить: занят
# лок, нет папки, нет репозитория — тогда держание осталось, и вопрос остаётся). Код не 0, таймаут (240 с) и сбой
# запуска (код 1) и «Пока держать» — вопрос тоже остаётся. Держание после sync.sh, которое не удалось прочитать
# (не FileNotFoundError) или в котором нет task=, считается не снятым: вопрос остаётся, причина — в выводе;
# «применён» печатается по задаче только после этой проверки (metis-0364).
SYNC_DIR = os.path.join(HOME, ".claude")


def board_registry(T):
    """directions.toml → (направление → проект, проект → значок, проекты пульта). Один разбор для тика и check:
    счётчики заметок проектов сверяются по тому же реестру, по которому их писали."""
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            dirs = tomllib.load(fh).get("direction") or []
    except (OSError, ValueError):
        return {}, {}, {}
    projects = {d.get("name"): d.get("project") for d in dirs}
    marks = {}  # значок проекта — поле `mark` направления; ключ — project, иначе name
    for d in dirs:
        if isinstance(d.get("mark"), str):
            marks.setdefault(d.get("project") or d.get("name"), d["mark"])
    return projects, marks, T.project_registry(dirs)


BOARD_BUDGET = float(os.environ.get("PANTHEON_BOARD_BUDGET") or 45)  # с на проход доски; предел задания — 60 (metis-0709)
BOARD_NOTIFY_WAIT = 20.0  # с ждать блокировку notify: занята дольше — проход идёт без уведомлений, а не до таймаута
BOARD_AUTO_MIN = 8.0  # с: осталось меньше — сводку board-auto.md этого прохода пропускаем, соберёт следующий


class BoardClock:
    """Время частей прохода доски (metis-0709): одна строка «доска-время: …» в журнале задания. Бюджет — сколько секунд
    у прохода до предела задания: необязательное (ожидание блокировки, сводка) не берётся, если бюджет вышел."""

    def __init__(self, budget):
        self.t0, self.budget, self.parts, self.skipped, self.cur = time.monotonic(), budget, [], [], None

    def left(self):
        return self.budget - (time.monotonic() - self.t0)

    @contextlib.contextmanager
    def phase(self, name):
        t = time.monotonic()
        try:
            yield
        except BaseException:
            self.cur = name  # прервали (SIGTERM, сбой) — строка назовёт часть
            raise
        finally:
            self.parts.append((name, time.monotonic() - t))

    def line(self):
        out = " · ".join(f"{n} {d:.1f}" for n, d in self.parts)
        if self.cur:
            out += f" · прервано в «{self.cur}»"
        if self.skipped:
            out += " · пропущено: " + ", ".join(self.skipped)
        return f"доска-время: {out} · итого {time.monotonic() - self.t0:.1f} с"


@contextlib.contextmanager
def lock_wait(name, wait):
    """lock(name) с ожиданием не дольше wait секунд: не взяли — False, без зависания."""
    end = time.monotonic() + wait
    while True:
        with lock(name, block=False) as got:
            if got:
                yield True
                return
        if time.monotonic() >= end:
            yield False
            return
        time.sleep(0.2)


def board():
    """Доска владельца: ходы → задачи и журнал владельца, карточки ← задачи. Только на этом Mac, под блокировкой.
    Время частей — одной строкой в вывод; бюджет BOARD_BUDGET, SIGTERM (таймаут задания) не теряет строку (metis-0709)."""
    clock = BoardClock(BOARD_BUDGET)
    def on_term(*_):
        raise SystemExit(143)
    try:
        old = signal.signal(signal.SIGTERM, on_term)
    except ValueError:  # не главный поток
        old = None
    try:
        return _board(clock)
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)
        print(clock.line())


def _board(clock):
    T = tasks_mod()
    sched = load_schedule()
    primary = not sched.get("primary_host") or sched.get("primary_host") == host()
    with lock("board", block=False) as got:
        if not got:
            return 0
        with clock.phase("реестр"):
            projects, marks, registry = board_registry(T)
        with clock.phase("статусы"):
            status_lines = board_status_sync(T) if primary else []
        with clock.phase("хозяева"):
            status_lines += board_owner_sync(T) if primary else []
        # политика уведомлений — под своей блокировкой на весь проход: сбои из run-job ждут, а не теряются
        with clock.phase("блокировка-notify"):
            nl = lock_wait("notify", min(BOARD_NOTIFY_WAIT, max(clock.left(), 0)))
            held = nl.__enter__()
        try:
            if not held:
                clock.skipped.append("уведомления (блокировка notify занята)")
            pol = notify_policy(sched) if held else None
            night_end = "08:00"
            with contextlib.suppress(Exception):
                night_end = night_mod().config()[1]["end"]
            with clock.phase("карточки"):
                lines = T.board_sync(PANTHEON, BOARD, path("board.json"), path("owner-log", "board.jsonl"), now(),
                                     night_end=night_end, open_prs=autoclose_mod().open_pr_tasks(path("autoclose.json")),
                                     alert=lambda k, v, text, who="board", note=None: alert_once(
                                         k, v, text, who, note if held else None, policy=pol),
                                     primary=primary, projects=projects, policy=pol, marks=marks, registry=registry,
                                     **board_links())
            if pol is not None:
                pol.save()
        finally:
            nl.__exit__(None, None, None)
        with clock.phase("очистка"):
            once_dir = path("once")  # отметки «уже сообщали» старше 90 дней — убрать: папка не растёт без конца
            for f in os.listdir(once_dir) if os.path.isdir(once_dir) else []:
                fp = os.path.join(once_dir, f)
                if now() - os.path.getmtime(fp) > 90 * 86400:
                    os.remove(fp)
        if primary:
            if clock.left() < BOARD_AUTO_MIN:
                clock.skipped.append("сводка board-auto (бюджет)")
            else:
                with clock.phase("сводка"):
                    board_auto_sync(T)
    for ln in status_lines + lines:
        print(ln)
    if primary and os.environ.get("PANTHEON_METRICS") != "0":
        board_metrics(T)
    return 0


def board_links():
    """Ссылки на PR и коммиты и хвосты для карточек (metis-0501 [zeus-pr-link], metis-0572): индекс PR по кэшу gh,
    репозитории направлений из [merge_repos] и хвосты последнего check. Сбой — без ссылок: доска важнее."""
    out = {"tails": read_json(path("tails.json"), {})}
    if not isinstance(out["tails"], dict):
        out["tails"] = {}
    try:
        out["repos"] = metrics_ctx().repos
        cache, A = read_json(path("autoclose-prs.json"), {}), autoclose_mod()
        out["pr_index"] = A.pr_index(cache)
        out["batch_prs"] = A.batch_prs(cache)  # PR пачки — одно правило с board-auto и check (metis-0810)
    except Exception:  # noqa: BLE001
        pass
    return out


_CULPRITS = None


def culprits_mod():
    """lib/culprits.py — виновники памяти в красной зоне и pantheon reap (metis-0568)."""
    global _CULPRITS
    if _CULPRITS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_culprits", os.path.join(LIB, "culprits.py"))
        _CULPRITS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CULPRITS)
        _CULPRITS.set_core(sys.modules[__name__])
    return _CULPRITS


def boardstatus_mod():
    """lib/boardstatus.py — статусы задач и пачек по следам работы (metis-0397, расширение)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_boardstatus", os.path.join(LIB, "boardstatus.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def board_domains():
    d = read_json(path("domains.json"), {}).get("domains")
    return d if isinstance(d, dict) else {}


def board_status_sync(T):
    """Статусы в шаг с работой (metis-0397, п. 7–8): задача todo с живой worktree на ветке с её id → doing, пачка — по
    составу. До сборки видов доски: виды Obsidian сразу видят новые статусы. Задача, которую вернули в todo, а работа
    идёт, — тревога один раз на набор задач; пачка, которую проход не двигает, — один раз на набор «id и причина»:
    сменилась причина — тревога заново. Под блокировкой записи сдвиг сверяет статус, а у пачки ещё и вопрос владельцу
    (STORY_HOLD): поставили между планом и записью — не сдвигаем. Сбой — тревога, проход доски идёт дальше.
    → строки для вывода."""
    out = []
    try:
        S = boardstatus_mod()
        tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
        open_closing = {}
        cache = read_json(path("autoclose-prs.json"), {})
        for repo, prs in sorted((cache.get("open_prs") if isinstance(cache.get("open_prs"), dict) else {}).items()):
            for pr in prs if isinstance(prs, list) else []:
                if isinstance(pr, dict) and isinstance(pr.get("number"), int) and not pr.get("part"):
                    for tid in pr.get("closes") if isinstance(pr.get("closes"), list) else []:
                        if isinstance(tid, str):
                            open_closing.setdefault(tid, []).append((repo, pr["number"]))
        moves, stale = S.plan(tasks, board_domains(), open_closing)
        for tid, ch, note in moves:
            old = tasks[tid][1].get("status")

            def same(h, old=old, tid=tid):
                if h.get("status") != old:
                    raise ValueError(f"{tid}: статус уже {h.get('status')}")
                held = [f for f in S.STORY_HOLD if h.get(f)] if h.get("type") == "story" else []
                if held:  # вопрос поставили после плана: done стёр бы его (metis-0412)
                    raise ValueError(f"{tid}: ждёт ответа владельца ({', '.join(held)})")
            try:
                T.task_set(PANTHEON, now(), tid, ch, note=note, actor="плановый проход", precheck=same)
                out.append(f"статус · {tid}: {old} → {ch['status']}" if "status" in ch
                           else f"статус · {tid}: {old}, отметка в журнале")
            except ValueError as e:  # задачу правят прямо сейчас — следующий проход посмотрит заново
                out.append(f"статус · {tid}: не сдвинут ({e})")
    except Exception as e:  # noqa: BLE001 — сбой сверки статусов не ломает проход доски
        alert_once("board-status", type(e).__name__, f"доска: сверка статусов упала ({type(e).__name__}: {e})", "board")
        return out
    clear_once("board-status")
    held = {k: v for k, v in stale.items() if tasks.get(k, ("", {}, ""))[1].get("type") == "story"}
    stale = {k: v for k, v in stale.items() if k not in held}
    if stale:
        alert_once("board-todo-live", ",".join(sorted(stale)), "доска: задачи в todo, а работа по ним идёт — "
                   + "; ".join(f"{tid} ({why})" for tid, why in sorted(stale.items()))
                   + ". Взять в работу — pantheon task claim ID --by КТО, или закрыть след (worktree, PR)", "board")
    else:
        clear_once("board-todo-live")
    if held:  # пачку проход не двигает: решение за человеком (вопрос владельцу, ручной статус)
        reasons = "; ".join(f"{sid} ({why})" for sid, why in sorted(held.items()))  # ключ — id и причина (metis-0412)
        alert_once("board-story-hold", reasons, "доска: статус пачки по составу не поставлен — " + reasons
                   + ". Решить руками — pantheon task set ID status=…", "board")
    else:
        clear_once("board-story-hold")
    return out


AGENTS_FRESH = 30 * 60  # снимок сессий (STATE/agents.json) старше — о хозяевах задач ничего не утверждаем
OWNER_SIDS_KEEP = 30 * 86400  # sessionId, которого не видно дольше, из памяти имён уходит
ALERT_IDS = 12  # номеров задач в одной строке тревоги


def _ids_text(ids):
    ids = sorted(ids)
    return ", ".join(ids[:ALERT_IDS]) + (f" и ещё {len(ids) - ALERT_IDS}" if len(ids) > ALERT_IDS else "")


def board_owner_sync(T):
    """Хозяин задачи и следы работы (metis-0868, п. 2–3), проход доски на главном Mac, после сверки статусов:
    (1) сессию переименовали — owner открытых карточек за ней: имя ищется по sessionId (память имён STATE/owner-sids.json,
    снимок `pantheon agents` и реестр ~/.claude/sessions), а не по прежнему имени; (2) owner — сессия, которой нет среди
    окон, остановленная, или её остановил владелец — тревога «задача без хозяина» с командой передачи; (3) задача doing
    без ветки, worktree и PR с её номером и без правки дольше STALE_DOING_HOURS — тревога. Снимок сессий старше
    AGENTS_FRESH — (1) и (2) пропускаются: о живых окнах ничего не знаем. Сбой — тревога, проход доски идёт дальше.
    → строки для вывода."""
    out = []
    try:
        S = boardstatus_mod()
        t = now()
        tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
        directions = set(board_domains()) | {str(d.get("name")) for d in T.load_directions(PANTHEON) or [] if d.get("name")}
        snap = read_json(path("agents.json"), None)
        fresh = isinstance(snap, dict) and isinstance(snap.get("time"), (int, float)) and 0 <= t - snap["time"] < AGENTS_FRESH
        orphans = None
        if fresh:
            agents = [a for a in snap.get("agents") or [] if isinstance(a, dict)]
            seen = {a.get("sessionId") for a in agents}
            agents += [dict(r, state=None) for r in sessions_registry() if r.get("sessionId") not in seen]
            mem = read_json(path("owner-sids.json"), {})
            mem = mem if isinstance(mem, dict) else {}
            known = {k: v.get("name") for k, v in mem.items() if isinstance(v, dict) and isinstance(v.get("name"), str)}
            renames, names = S.owner_renames(tasks, agents, known, directions)
            for tid, old, new, sid in renames:

                def same_owner(h, old=old, tid=tid):  # owner сменили между планом и записью — не трогаем
                    if h.get("owner") != old:
                        raise ValueError(f"{tid}: owner уже {h.get('owner')}")
                try:
                    T.task_set(PANTHEON, t, tid, {"owner": new}, actor="плановый проход", precheck=same_owner,
                               note=f"owner: сессию {old} переименовали в {new} (sessionId {sid[:8]})")
                    out.append(f"хозяин · {tid}: {old} → {new} (сессию переименовали)")
                except ValueError as e:
                    out.append(f"хозяин · {tid}: не переименован ({e})")
            now_sids = {a.get("sessionId") for a in agents}
            mem = {sid: {"name": n, "seen": t if sid in now_sids else (mem.get(sid) or {}).get("seen", t)}
                   for sid, n in names.items()}
            write_json(path("owner-sids.json"), {k: v for k, v in mem.items()
                                                 if isinstance(v["seen"], (int, float)) and t - v["seen"] < OWNER_SIDS_KEEP})
            if renames:
                tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
            stopped = set(os.listdir(path("stopped"))) if os.path.isdir(path("stopped")) else set()
            orphans = S.orphan_owners(tasks, agents, directions, stopped)
        cache = read_json(path("autoclose-prs.json"), {})
        open_ids = {i for prs in ((cache.get("open_prs") if isinstance(cache, dict) else None) or {}).values()
                    if isinstance(prs, list) for p in prs if isinstance(p, dict)
                    for i in (p.get("ids") or []) + (p.get("closes") or []) if isinstance(i, str)}
        stale = S.stale_doing(tasks, board_domains(), open_ids, t, T.ts_of)
    except Exception as e:  # noqa: BLE001 — сбой сверки хозяев не ломает проход доски
        alert_once("board-owners", type(e).__name__, f"доска: сверка хозяев задач упала ({type(e).__name__}: {e})", "board")
        return out
    clear_once("board-owners")
    if orphans:
        groups = {}
        for tid, (owner, why) in orphans.items():
            d = tasks[tid][1].get("direction")
            groups.setdefault((owner, why, S.handover(owner, d, directions)), []).append(tid)
        parts = []
        for (owner, why, to), ids in sorted(groups.items()):
            ids = sorted(ids)
            cmd = (f"pantheon task set {ids[0]} owner={to}" if len(ids) == 1
                   else f"for id in {' '.join(ids[:ALERT_IDS])}; do pantheon task set $id owner={to}; done")
            more = (f" (первые {ALERT_IDS}; остальные — тем же циклом, список — pantheon task ready --owner {owner})"
                    if len(ids) > ALERT_IDS else "")  # строка тревоги — не сотни номеров
            parts.append(f"owner {owner} — {why}: {_ids_text(ids)}. Передать: {cmd}{more}")
        alert_once("board-orphan-owner", "|".join(sorted(f"{k}:{v[0]}" for k, v in orphans.items())),
                   "доска: задача без хозяина — " + "; ".join(parts), "board")
    elif orphans is not None:
        clear_once("board-orphan-owner")
    if stale:
        alert_once("board-doing-stale", ",".join(sorted(stale)),
                   f"доска: задача в работе (doing) без ветки, worktree и PR дольше {S.STALE_DOING_HOURS} ч — "
                   + "; ".join(f"{tid} ({stale[tid]} ч без правки, owner {tasks[tid][1].get('owner')})"
                               for tid in sorted(stale)[:ALERT_IDS])
                   + (f" и ещё {len(stale) - ALERT_IDS}" if len(stale) > ALERT_IDS else "")
                   + ". Работа идёт — ветка с номером задачи (git worktree add … <id>-…); нет — вернуть в очередь: "
                   + f"pantheon task set {sorted(stale)[0]} status=todo", "board")
    else:
        clear_once("board-doing-stale")
    return out


def boardtext_mod():
    """lib/boardtext.py — автоблок доски board-auto.md (metis-0397), общий с хуком hooks/ctx.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_boardtext", os.path.join(LIB, "boardtext.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def board_week():
    """Неделя лимита целыми процентами по снимку строки статуса; снимка нет или неделя сброшена — None."""
    with contextlib.suppress(Exception):
        w = night_mod().snapshot()["week"]
        if w and w[1] > now():
            return int(round(w[0]))
    return None


def board_auto_fp():
    return hashlib.sha1(repr(_fp_board_auto()).encode("utf-8", "replace")).hexdigest()


def boardmerged_mod():
    """lib/boardmerged.py — задачи при слитом PR, не закрытые (metis-0768)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_boardmerged", os.path.join(LIB, "boardmerged.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def board_merged_open(T, t):
    """Строки «PR слит, задача открыта» для board-auto.md: кэш autoclose fetch и журнал карточки, без gh (metis-0768).
    Сбой — пусто: сводка важнее."""
    try:
        return boardmerged_mod().merged_open(T.load_tasks(PANTHEON, T.WORK_TYPES), read_json(path("autoclose-prs.json"), {}),
                                             t, T, autoclose_mod(), autoclose_repo_dirs(),
                                             autoclose_mod().open_pr_tasks(path("autoclose.json")) or ())
    except Exception:  # noqa: BLE001
        return []


def boardmd_mod():
    """lib/boardmd.py — проверка и архив board.md (metis-0769)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_boardmd", os.path.join(LIB, "boardmd.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BOARD_MD_KEYS = ("size", "updated", "dates")


def board_md_check(quiet):
    """board.md (metis-0769): «Сейчас» длиннее предела, «Обновлено» старше суток, прошедшие сроки «По датам». Тик (quiet) —
    одна тревога на вид проверки; руками — предупреждения. Файла нет — молча."""
    p = os.path.join(PANTHEON, "board.md")
    try:
        with open(p, encoding="utf-8") as fh:
            found = {k: (v, text) for k, v, text in boardmd_mod().problems(fh.read(), now())}
    except OSError:
        found = {}
    for k in BOARD_MD_KEYS:
        if k in found:
            if quiet:
                alert_once(f"check-board-md-{k}", found[k][0], found[k][1], "check")
            else:
                print(f"предупреждение · {found[k][1]}")
        else:
            clear_once(f"check-board-md-{k}")


def _file_mark(st):
    """Отметка файла для сверки «не изменился ли»: inode (замена через rename), mtime в нс и размер."""
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _board_changed(board, seen):
    """board.md уже не тот, что прочитан (metis-0780) → True и строка отказа в stderr."""
    try:
        cur = _file_mark(os.stat(board))
    except OSError:
        cur = None
    if cur == seen:
        return False
    print("board.md изменился, повтори: pantheon board archive (ничего не записано)", file=sys.stderr)
    return True


def board_archive(rest):
    """`pantheon board archive [--days N]` (metis-0769): датированные блоки «Сейчас» и «Сессии и хозяйство» старше N дней
    (по умолчанию 7) — в ~/ai/pantheon/archive/ГГГГ-ММ.md; без потерь: сначала дописывается архив, потом board.md
    заменяется целиком. Нечего переносить — файлы не тронуты.
    board.md правят и руками (Зевс, владелец) без замка pantheon-git, поэтому перед записью архива и перед заменой
    board.md сверяются inode, mtime и размер с прочитанными (metis-0780): изменился — отказ «board.md изменился,
    повтори», код 1, board.md не тронут, дописанное в архив откатывается. Остаток — правка в те же доли секунды
    между последней сверкой и заменой. Сбой дописывания или замены (OSError) — строка «… — архив откатан, board.md не
    тронут», без трассировки; откат сам не удался — «архив НЕ откатан (архив: причина)», код 1 (metis-0810)."""
    M, days = boardmd_mod(), None
    args = list(rest)
    if args[:1] == ["--days"] and len(args) == 2 and args[1].isdigit():
        days = int(args[1])
    elif not args:
        days = M.DEFAULT_DAYS
    if days is None:
        print("pantheon board archive [--days N]  (N — целое число дней)", file=sys.stderr)
        return 2
    board = os.path.join(PANTHEON, "board.md")
    if not os.path.exists(board):
        print("board.md нет — нечего переносить")
        return 0
    with lock("pantheon-git"):
        with open(board, encoding="utf-8") as fh:
            text = fh.read()
            seen = _file_mark(os.fstat(fh.fileno()))
        kept, moved = M.split(text, now(), days)
        n = sum(len(v) for v in moved.values())
        if not n:
            print(f"board.md: блоков старше {days} дн. нет")
            return 0
        if _board_changed(board, seen):
            return 1
        os.makedirs(os.path.join(PANTHEON, "archive"), exist_ok=True)
        stamp = datetime.fromtimestamp(now()).strftime("%Y-%m-%d")
        undo = {}   # архив → размер до дописывания (None — файла не было)
        done = False

        def rollback():
            """Дописанное в архивы — обратно; → [«архив: причина»] того, что откатить не вышло (metis-0810)."""
            bad = []
            for ap, size in undo.items():
                try:
                    if size is None:
                        os.remove(ap)
                    else:
                        os.truncate(ap, size)
                except FileNotFoundError:
                    if size is not None:
                        bad.append(f"{os.path.relpath(ap, PANTHEON)}: файла нет")
                except OSError as e:
                    bad.append(f"{os.path.relpath(ap, PANTHEON)}: {type(e).__name__}: {e}")
            undo.clear()
            return bad

        def undone(bad):
            """Итог отката честно: откатан — так и пишем; нет — что осталось в каком архиве, код 1."""
            if bad:
                return ("архив НЕ откатан (" + "; ".join(bad) + ") — в нём строки, которые остались и в board.md: "
                        "убрать их из архива руками")
            return "архив откатан"
        try:
            for key, ls in sorted(moved.items()):
                ap = os.path.join(PANTHEON, "archive", f"{key}.md")
                undo[ap] = os.path.getsize(ap) if os.path.exists(ap) else None
                with open(ap, "a", encoding="utf-8") as fh:
                    fh.write(f"\n<!-- из board.md, перенос {stamp} -->\n" + "\n".join(ls) + "\n")
            if _board_changed(board, seen):
                bad = rollback()
                if bad:
                    print(f"pantheon board archive: {undone(bad)}", file=sys.stderr)
                return 1
            write_atomic(board, kept)
            done = True
        except OSError as e:   # metis-0792: сбой дописывания или замены — архив откатывается, board.md цел
            print(f"pantheon board archive: {type(e).__name__}: {e} — {undone(rollback())}, board.md не тронут",
                  file=sys.stderr)
            return 1
        finally:
            if not done:   # иной сбой (не OSError): откат и честная строка, трассировка уйдёт выше
                bad = rollback()
                if bad:
                    print(f"pantheon board archive: {undone(bad)}", file=sys.stderr)
    print(f"board.md: перенесено строк {n} в archive/{', '.join(k + '.md' for k in sorted(moved))}")
    return 0


def board_auto_sync(T):
    """Автоблок доски — отдельный файл board-auto.md (metis-0397): PR, пачки, неделя, STATUS.md, ответы владельца.
    board.md не пишет: только сверяет строку встраивания ![[board-auto]] вверху (нет — тревога). Удачная сборка
    записывает отпечаток входов в board-auto.json (по нему board_auto_watch видит, что сборка отстала). Сбой — тревога,
    проход доски идёт дальше."""
    try:
        B = boardtext_mod()
        fp, t = board_auto_fp(), now()
        tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
        data = B.collect(PANTHEON, STATE, tasks, t, board_week(),
                         owner=lambda h: T.Roles(()).name(T.assignee(h)) == T.OWNER_NODE,
                         own_of=batch_own_of(tasks, metrics_ctx().repos))
        data["merged_open"] = board_merged_open(T, t)
        res = B.sync(os.path.join(PANTHEON, B.AUTO_NAME), B.render(data, t))
        write_json(path("board-auto.json"), {"fp": fp, "built": t})
    except Exception as e:  # noqa: BLE001 — сбой автоблока не ломает проход доски
        alert_once("board-auto", type(e).__name__, f"board-auto.md: сборка упала ({type(e).__name__}: {e})", "board")
        return
    clear_once("board-auto")
    if data["broken"]:
        alert_once("board-auto-input", ",".join(data["broken"]), "board-auto.md: не читается вход "
                   f"{', '.join(data['broken'])} — сводка собрана без него", "board")
    else:
        clear_once("board-auto-input")
    if B.embed_ok(os.path.join(PANTHEON, "board.md")) is False:
        alert_once("board-auto-embed", "1", f"board.md: вверху нет строки {B.EMBED} — сводка прохода (board-auto.md) "
                   "не видна в доске; поставить её одной строкой в начало файла", "board")
    else:
        clear_once("board-auto-embed")
    if res == "written":
        print("board-auto.md: сводка прохода обновлена")


def board_auto_watch(t, sched):
    """Тик (primary): входы автоблока менялись, а удачной сборки после этого нет WATCH_GAP и больше — тревога без
    модели (молчаливый отказ генератора, исследование 24.10 разд. 7.8). Счёт — от первого расхождения после удачной
    сборки: входы, которые меняются чаще WATCH_GAP, его не сбрасывают. Одна тревога на расхождение. Сборка прошла
    (она пишет board-auto.json заново) — отметка снимается. Задачи
    `pantheon board` в расписании нет или она выключена — не сверяет: сборки и не ждут."""
    if not any((parse_command(j.get("command")) or [""])[1:] == ["board"] and j.get("enabled") is not False
               for j in sched.get("job") or []):
        return
    B = boardtext_mod()
    st = read_json(path("board-auto.json"), {}) or {}
    cur = board_auto_fp()
    if st.get("fp") == cur:
        if st.get("seen_fp") or st.get("seen_at"):
            st.pop("seen_fp", None), st.pop("seen_at", None)
            write_json(path("board-auto.json"), st)
        clear_once("board-auto-stale")
        return
    if not st.get("seen_at"):  # первое расхождение после удачной сборки — отсюда и счёт; новые правки его не сбрасывают
        st.update(seen_fp=cur, seen_at=t)
        write_json(path("board-auto.json"), st)
        return
    if st.get("seen_fp") != cur:
        st["seen_fp"] = cur
        write_json(path("board-auto.json"), st)
    seen = float(st["seen_at"])
    if t - seen >= B.WATCH_GAP:
        built = st.get("built")
        alert_once("board-auto-stale", repr(seen), f"board-auto.md: входы менялись в {B.hm(seen)}, а сборки нет "
                   f"{int((t - seen) // 60)} мин (последняя — {B.hm(float(built)) if built else 'не было'}); "
                   "смотреть задачу board: pantheon jobs, alerts.md", "pantheon-tick")


def batchsuggest_mod():
    """lib/batchsuggest.py — раскладка открытых задач по пачкам без модели (metis-0595)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_batchsuggest", os.path.join(LIB, "batchsuggest.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BATCH_SUGGEST_EVERY = 3 * 86400  # задача расписания раз в 3,5 суток (every = 5040); команда сама не чаще раза в 3 суток


def batch_suggest_run(rest):
    """pantheon batch-suggest run [--force] — плановая сводка (metis-0595): предложения по пачкам для всех направлений
    → Доска/Пачки-предложения.md (есть доска) и STATE/batch-suggest.md. Прикрепляет только предложения «уверенно» (task_attach, строка в журнал). Раньше чем через
    BATCH_SUGGEST_EVERY после прошлого прохода — пропуск (--force снимает). Тревога — одна строка, и только если среди
    предложений есть ещё не виденные (ключи в STATE/batch-suggest.json)."""
    if rest not in ([], ["run"], ["run", "--force"]):
        print("использование: pantheon batch-suggest run [--force]", file=sys.stderr)
        return 2
    t, st = now(), read_json(path("batch-suggest.json"), {})
    st = st if isinstance(st, dict) else {}
    last = st.get("last")
    if rest[-1:] != ["--force"] and isinstance(last, (int, float)) and 0 <= t - last < BATCH_SUGGEST_EVERY:
        print(f"batch-suggest: прошлый проход {stamp(last)}, следующий не раньше {stamp(last + BATCH_SUGGEST_EVERY)}")
        return 0
    T, B = tasks_mod(), batchsuggest_mod()
    tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
    dirs = sorted({h.get("direction") for _, h, _ in tasks.values() if h.get("type") == "task" and h.get("direction")})
    results = [B.suggest(tasks, d) for d in dirs]
    applied, skipped = [], []
    for res in results:  # «уверенно» прикрепляет сам проход (metis-0940); журнал задачи и пачки пишет task_attach
        d, sk = B.apply(res, tasks, lambda tid, sid: T.task_attach(PANTHEON, now(), tid, sid, actor="плановый проход"))
        applied += d
        skipped += sk
    if applied:
        tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
        results = [B.suggest(tasks, d) for d in dirs]
    results = [r for r in results if r["joins"] or r["groups"] or r["duplicates"]]
    keys = sorted(k for r in results for k in B.keys(r))
    seen = st.get("seen") if isinstance(st.get("seen"), list) else None
    fresh = [k for k in keys if seen is None or k not in seen]
    body = "\n\n".join(B.render(r) for r in results) or "Предложений нет."
    text = ("# Пачки: предложения\n\nСчитает плановый проход без модели, раз в 3–4 суток (`pantheon task batch-suggest`). "
            "Ничего не меняет: пачку ставит координатор — `pantheon task set ID parent=ПАЧКА` (для новой пачки сначала "
            "`pantheon task new --type story`). «Уверенно» прикрепляет сам проход (то же, что `pantheon task batch-suggest --apply`).\n\n"
            f"Проход: {stamp(t)}\n\n```\n{body}\n```\n")
    os.makedirs(STATE, exist_ok=True)
    write_atomic(path("batch-suggest.md"), text)
    if os.path.isdir(BOARD):
        pp = os.path.join(BOARD, "Пачки-предложения.md")
        old = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
        if old.split("Проход:")[-1].split("\n", 1)[-1] != text.split("Проход:")[-1].split("\n", 1)[-1]:
            write_atomic(pp, text)  # время прохода само файл не меняет: пишется только при новом составе
    write_json(path("batch-suggest.json"), {"last": t, "seen": keys})
    if fresh:
        n = {p: sum(1 for k in fresh if k.startswith(p + ":")) for p in ("group", "join", "dup")}
        alert(f"пачки: новых предложений {len(fresh)} (новых пачек {n['group']}, в существующую {n['join']}, дублей "
              f"{n['dup']}), список — Доска/Пачки-предложения.md", "pantheon-tick")
    print(f"batch-suggest: предложений {len(keys)}, новых {len(fresh)}, прикреплено {len(applied)}"
          + "".join(f"\n  прикреплено · {x}" for x in applied) + "".join(f"\n  пропущено · {x}" for x in skipped))
    return 0


def autoclose_mod():
    """lib/autoclose.py — закрытие задач при слиянии их PR (metis-0308)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_autoclose", os.path.join(LIB, "autoclose.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def autoclose_actual(T, tid):
    """Расход по закрытой задаче из учёта (metrics/tasks.jsonl, metis-0294) → строка actual; нет замера — None."""
    if os.environ.get("PANTHEON_METRICS") == "0":
        return None
    M, A = metrics_mod(), autoclose_mod()
    ctx = metrics_ctx()
    with contextlib.suppress(Exception):  # строки закрытия допишет плановый проход доски
        M.record(ctx, T.load_tasks(PANTHEON, T.WORK_TYPES), tid)
    rows = [r for r in M.read_rows(ctx.rows_path) if r.get("id") == tid]
    return A.actual_text(rows[-1]) if rows else None


def autoclose_repo_dirs():
    """{репозиторий: {направления}} из [merge_repos]: задачу закрывает только PR из репозитория её направления."""
    out = {}
    for d, repos in metrics_ctx().repos.items():
        for r in repos if isinstance(repos, list) else []:
            out.setdefault(r, set()).add(d)
    return out


def autoclose_alerts(repos, errors):
    """Ошибки gh и закрытия — одна тревога на репозиторий, пока не починится."""
    for repo in repos:
        key = "autoclose-" + re.sub(r"[^\w-]", "_", repo)[:50]
        bad = {k: v for k, v in errors.items() if k == repo or k.startswith(repo + "#")}
        if bad:
            alert_once(key, "|".join(sorted(bad)), "автозакрытие задач: " + "; ".join(f"{k}: {v}" for k, v in sorted(bad.items()))[:300],
                       "pantheon-tick")
        else:
            clear_once(key)


AUTOCLOSE_STALE = 3600


def autoclose_off_reason(t, repo_dirs=None):
    """Автозакрытие молча не работает: репозитории заданы, а кэша fetch нет или он старше часа → текст, иначе None."""
    if not (autoclose_repo_dirs() if repo_dirs is None else repo_dirs):
        return None
    fetched = autoclose_mod().load_state(path("autoclose-prs.json")).get("fetched")
    if not isinstance(fetched, (int, float)):
        return "автозакрытие выключено: нет строки autoclose-fetch в schedule.toml"
    if t - fetched > AUTOCLOSE_STALE:
        return "автозакрытие выключено: кэш старше часа (задача autoclose-fetch в schedule.toml не идёт)"
    return None


AUTOCLOSE_RUN_WAIT = 30  # с: проход fetch ждёт замок прохода по кэшу, пока его держит тик


def autoclose_tick(t, wait=0):
    """Проход по кэшу `pantheon autoclose fetch`: слитые PR → закрытие задач. В сеть не ходит. Зовут его тик (каждую
    минуту) и сам fetch сразу после записи кэша (metis-0868, п. 1): задача закрывается в том же проходе, что увидел
    слияние, а не на следующем круге. Замок autoclose-run — один проход за раз: тик и fetch не пишут одну задачу
    дважды; wait — сколько секунд ждать замок (тик не ждёт). Карточки изменились — view и доска сразу (refresh_kick)."""
    A, T = autoclose_mod(), tasks_mod()
    repo_dirs = autoclose_repo_dirs()
    if not repo_dirs:
        return
    off = autoclose_off_reason(t, repo_dirs)
    if off:
        alert_once("autoclose-off", off, off, "pantheon-tick")
    else:
        clear_once("autoclose-off")
    with lock_wait("autoclose-run", wait) as got:
        if not got:
            return
        log, errors = A.run(PANTHEON, path("autoclose.json"), path("autoclose-prs.json"), t, repo_dirs, T,
                            actual_for=lambda tid: autoclose_actual(T, tid))
    for ln in log:
        print(f"автозакрытие · {ln}")
    if log or errors:
        autoclose_alerts(sorted(repo_dirs), errors)
    if log:
        refresh_kick()


def autoclose_cmd(rest):
    """pantheon autoclose fetch — сетевой проход: gh про слитые и открытые PR → кэш для лёгкого тика. Задача расписания."""
    if rest != ["fetch"]:
        print("использование: pantheon autoclose fetch", file=sys.stderr)
        return 2
    repo_dirs = autoclose_repo_dirs()
    if not repo_dirs:
        return 0
    A = autoclose_mod()
    errors = A.fetch(path("autoclose-prs.json"), path("autoclose.json"), now(), sorted(repo_dirs), env=run_env(),
                     core=merge_mod().is_core, sandbox=lambda r, p, left=None: A.sandbox_core(r, p, run_env(), left=left))
    autoclose_alerts(sorted(repo_dirs), errors)
    for k, v in sorted(errors.items()):
        print(f"автозакрытие · {k}: {v}", file=sys.stderr)
    try:
        primary = load_schedule().get("primary_host")
    except (OSError, ValueError) as e:  # расписание не читается — закроет тик, когда его починят (тревогу даёт он же)
        print(f"автозакрытие · проход по кэшу пропущен: schedule.toml не читается ({e})", file=sys.stderr)
        return 0
    if not primary or host() == primary:  # как у тика: задачи (общий результат) правит один Mac
        autoclose_tick(now(), wait=AUTOCLOSE_RUN_WAIT)
    return 0


METRICS_EVERY = 30 * 60  # не чаще раза в 30 минут: учёт читает транскрипты за неделю (metis-0320)


def metrics_pass(T):
    """Один проход учёта: строки закрытий, которые роль из песочницы записать не смогла, и свод недели на Пульт.
    Первый проход после выпуска читает гигабайты транскриптов — дольше минуты, поэтому только из фонового процесса."""
    if os.environ.get("PANTHEON_METRICS_TEST_SLEEP"):  # проба в тестах: учёт, который долго работает
        time.sleep(float(os.environ["PANTHEON_METRICS_TEST_SLEEP"]))
    if os.environ.get("PANTHEON_METRICS_TEST_LOG"):
        with open(os.environ["PANTHEON_METRICS_TEST_LOG"], "a") as fh:
            fh.write(f"{os.getpid()}\n")
    M, tasks = metrics_mod(), T.load_tasks(PANTHEON, T.WORK_TYPES)
    ctx = metrics_ctx()
    M.sync(ctx, tasks)
    M.publish(ctx, tasks)


def trim_log(log_path, limit=400_000, keep=200_000):
    """Журнал дописывается; выше предела остаётся хвост в keep символов."""
    try:
        if os.path.getsize(log_path) > limit:
            with open(log_path, encoding="utf-8", errors="ignore") as fh:
                data = fh.read()[-keep:]
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(data)
    except OSError:
        pass


def metrics_run():
    """pantheon metrics run — фоновый проход под блокировкой metrics; занята — тихо выходит."""
    with lock("metrics", block=False) as got:
        if not got:
            return 0
        try:
            metrics_pass(tasks_mod())
        except Exception as e:  # noqa: BLE001 — сбой учёта не ломает ничего, кроме самого учёта
            alert_once("metrics", type(e).__name__, f"учёт по задачам: проход упал ({type(e).__name__}: {e})",
                       "board")
    return 0


def board_metrics(T):
    """Учёт по задачам после прохода доски — отдельным процессом: проход доски (таймаут 60 с) не ждёт транскрипты
    (metis-0320). Не чаще раза в 30 минут (отметка metrics-spawn) и не при занятой блокировке metrics. stdin/stdout/
    stderr — не pipe: процесс-сирота держал бы полный pipe."""
    stamp_p = path("metrics-spawn")
    try:
        if now() - os.path.getmtime(stamp_p) < METRICS_EVERY:
            return
    except OSError:
        pass
    if locked("metrics"):
        return
    try:
        os.makedirs(os.path.dirname(stamp_p), exist_ok=True)
        with open(stamp_p, "w") as fh:
            fh.write(stamp() + "\n")
        try:
            trim_log(path("metrics-run.log"))
            log = open(path("metrics-run.log"), "a")
        except OSError:
            log = subprocess.DEVNULL
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "metrics", "run"], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True, close_fds=True)
    except Exception as e:  # noqa: BLE001 — сбой запуска учёта не ломает доску
        alert_once("metrics", type(e).__name__, f"учёт по задачам: не запустился ({type(e).__name__}: {e})", "board")


def statelen_mod():
    """lib/statelen.py — длина файлов состояния, общая с хуком (hooks/ctx.py state-len)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_statelen", os.path.join(LIB, "statelen.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STATE_FILE_LIMIT = statelen_mod().STATE_FILE_LIMIT


def _check_long_state(quiet):
    """STATUS.md направлений и board.md штаба длиннее STATE_FILE_LIMIT знаков (символов, не байт): одна строка на
    файл. Без --quiet — печать; с ним (тик) — alert_daily: не чаще раза в сутки на файл, размер не в счёт."""
    sl = statelen_mod()
    for f in sl.state_files(PANTHEON):
        n = sl.length(f)
        if n is None:
            continue
        key = "state-long-" + re.sub(r"[^\w-]", "_", os.path.relpath(f, PANTHEON))[:60]
        if n <= STATE_FILE_LIMIT:
            continue
        shown = f.replace(HOME, "~", 1) if f.startswith(HOME + os.sep) else f
        text = (f"{shown}: {n} знаков при пределе {STATE_FILE_LIMIT} — после сжатия контекста хук кладёт только "
                f"первые ~9 800, хвост теряется: сократить, старое — в archive/")
        if quiet:
            alert_daily(key, text, "check")
        else:
            print(f"предупреждение · {text}")


def check_coordinators(quiet):
    """metis-0155: переключатель координатора в directions.toml. Ошибка — coordinator не булево (запуск считает такого
    координатора включённым). Предупреждения: у выключенного направления нет лида hephaestus (wake --task его не
    поднимет) или открыт координатор (его сессия с именем направления жива — Пританей и координатор вели бы его вдвоём).
    Тик (--quiet): открытый координатор — одна тревога на набор. → число ошибок."""
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            reg = tomllib.load(fh)
    except (OSError, ValueError):
        return 0
    errs, warns, live_off = [], [], []
    for d in reg.get("direction") or []:
        if isinstance(d, dict) and "coordinator" in d and not isinstance(d["coordinator"], bool):
            errs.append(f"directions.toml: у направления {d.get('name')} coordinator = {d['coordinator']!r} — нужно "
                        "true или false без кавычек; пока координатор считается включённым")
    off = hq_led(reg)
    for name, e in sorted(off.items()):
        if not lead_session(name, e):
            warns.append(f"directions.toml: {name} ведёт Пританей, но лида кода нет (leads = ['hephaestus']) — "
                         f"pantheon wake {name} --task <id> окно не поднимет")
    agents = None
    if off:
        with contextlib.suppress(Exception):
            agents = agents_all()
    for name in sorted(off):
        live = live_copies(name, agents) if agents is not None else []
        if live:
            ids = ", ".join(str(a.get("id") or a.get("name")) for a in live)
            live_off.append(name)
            warns.append(f"у направления {name} coordinator = false, а его координатор открыт ({ids}) — направление "
                         f"ведёт Пританей: остановить координатора — pantheon stop {name}")
    for e in errs:
        print(f"ОШИБКА · {e}")
    if not quiet:
        for w in warns:
            print(f"предупреждение · {w}")
    else:
        if live_off:
            alert_once("check-coord-off", ",".join(live_off), f"координатор открыт у направления, которое ведёт Пританей: "
                       f"{', '.join(live_off)} — pantheon stop <направление>", "check")
        else:
            clear_once("check-coord-off")
    return len(errs)


SKILL_DIRS = [d for d in (os.environ.get("PANTHEON_SKILL_DIRS") or "").split(os.pathsep) if d] or [
    os.path.join(PLUGIN, "skills"), os.path.join(HOME, ".claude", "skills")]


def skills_mod():
    """lib/skills_lint.py — линтер навыков (metis-0258)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_skills_lint", os.path.join(LIB, "skills_lint.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check_skills(paths=None, quiet=False):
    """Навыки по линтеру: (число проверенных, [(путь, ошибки)]). Ошибки печатает вызывающий; внимание — здесь."""
    L = skills_mod()
    rows = [(f, *L.lint_file(f)) for f in paths] if paths else L.lint_dirs(SKILL_DIRS)
    bad = []
    for f, errs, warns in rows:
        if errs:
            bad.append((f, errs))
        elif warns and not quiet:
            print(f"предупреждение · навык {f}: {'; '.join(warns)}")
    for f, errs in bad:
        print(f"ОШИБКА · навык {f}: {'; '.join(errs)}")
    return len(rows), bad


def _owner_answered(qid, since):
    """Есть ли ответ владельца на вопрос по задаче qid позже since: выбор в окне вопросов или в чате (owner-log/zeus.md) или галочка на
    доске (owner-log/board.jsonl) — те же признаки, что у `pantheon consent`. Журнал не читается — False."""
    try:
        with open(path("owner-log", "zeus.md"), encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        text = ""
    own = re.compile(r"вопрос: \[" + re.escape(qid) + r"\]", re.I)
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if not answers_mod().is_answer_head(m.group(2)):
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if t >= since and own.match(body) and re.search(r"^ответ: \S", body, re.M):
            return True
    try:
        with open(path("owner-log", "board.jsonl"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
            t = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), rec.get("answer")
        if rec.get("kind") == "answer" and rec.get("id") == qid and t >= since and isinstance(q, str) \
                and isinstance(a, str) and not re.search(r"%%|<", q):
            return True
    return False


def board_drift(T, tasks, cache, inbox):
    """Расхождения доски, которые владелец видит в Obsidian (metis-0441). Ничего не правит. tasks — T.load_tasks,
    cache — autoclose-prs.json (merged, open_prs), inbox — T.inbox_items. → [(ключ, текст)]."""
    A, out = autoclose_mod(), []
    cache = cache if isinstance(cache, dict) else {}
    open_ids = set()
    for repo, prs in sorted((cache.get("open_prs") or {}).items() if isinstance(cache.get("open_prs"), dict) else []):
        for pr in prs if isinstance(prs, list) else []:
            if not isinstance(pr, dict) or pr.get("part") or not isinstance(pr.get("closes"), list):
                continue  # как autoclose.review_pr: «часть» и неверная форма — пропуск, упоминание задачу не закрывает
            for tid in pr["closes"]:
                if not isinstance(tid, str):
                    continue
                open_ids.add(tid)
                st = (tasks.get(tid) or (None, {}, ""))[1].get("status")
                if st in ("todo", "done"):
                    out.append((tid, f"статус {st}, а PR {repo}#{pr.get('number')} открыт — ждёт слияния (review)"))
    for repo, rows in sorted((cache.get("merged") or {}).items() if isinstance(cache.get("merged"), dict) else []):
        for pr in rows if isinstance(rows, list) else []:
            if not isinstance(pr, dict) or any(not isinstance(pr.get(k), (str, type(None))) for k in ("body", "headRefName")) \
                    or A.is_part(pr.get("body")):
                continue
            mts = A.merged_ts(pr.get("mergedAt"))
            for tid in A.closing_ids(pr.get("headRefName"), pr.get("body")):
                h = (tasks.get(tid) or (None, {}, ""))[1]
                if h.get("status") in ("doing", "review") and tid not in open_ids \
                        and not (mts and (T.ts_of(h.get("updated")) or 0) > mts):
                    out.append((tid, f"статус {h['status']}, а PR {repo}#{pr.get('number')} уже слит"))
    out += batch_outside(T, tasks, cache, metrics_ctx().repos)
    for tid, (_, h, _) in sorted(tasks.items()):
        if h.get("status") == "waiting" and h.get("waiting_on") == "human":
            since = T.ts_of(h.get("question_at")) or T.ts_of(h.get("created")) or 0
            if _owner_answered(tid, since):
                out.append((tid, "владелец ответил на вопрос, а задача ещё в «От меня нужно» (waiting)"))
    for cid, it in sorted(inbox.items()):
        d = os.path.join(os.path.dirname(it["path"]), "done")
        same = [t for t, (_, h, _) in tasks.items() if h.get("direction") == it["direction"]
                and str(h.get("title") or "").strip() == it["title"]]
        archived = any(os.path.exists(os.path.join(d, pre + it["file"])) for pre in ("", "отклонено-"))
        if same or archived:
            out.append((f"{it['direction']}/inbox/{it['file']}", "записка обработана ("
                        + (f"задача {same[0]}" if same else "лежит в inbox/done") + "), а она ещё во «Входящих»"))
    return out


def batch_own_of(tasks, repos):
    """id пачки → репозитории её направления в нижнем регистре (autoclose.batch_pick, metis-0810): repos —
    [merge_repos] policy.toml (направление → [репозиторий]); его нет, он пуст или у направления пачки нет строки —
    None (любые), как у board-auto до правила (argus #341 Д1)."""
    if not isinstance(repos, dict) or not repos:
        return lambda sid: None

    def own(sid):
        mine = repos.get((tasks.get(sid) or (None, {}, ""))[1].get("direction"))
        return [r.lower() for r in mine if isinstance(r, str)] if isinstance(mine, list) else None
    return own


def batch_outside(T, tasks, cache, repos=None):
    """PR пачки (autoclose.batch_prs — одно правило с карточкой и board-auto, metis-0810) закрыл задачу, у которой parent
    — не эта пачка (metis-0799): состав пачки считается по parent, поэтому сделанное в её ветке ложится в чужую пачку
    или никуда, и карточка пачки показывает «1 из 13». Только открытые пачки (не done/dropped), PR из репозиториев
    направления пачки (repos — [merge_repos]; нет — любые); PR с «часть» задач не закрывает. parent не правим — его
    решает координатор: attach или поле пачки keep_outside — задачи, оставленные вне её состава (предупреждения о них
    нет). → [(id, текст)]."""
    A, out, seen = autoclose_mod(), [], set()
    own_of = batch_own_of(tasks, repos)
    for sid, rows in sorted(A.batch_prs(cache).items()):
        sh = (tasks.get(sid) or (None, {}, ""))[1]
        if sh.get("type") != "story" or sh.get("status") in ("done", "dropped"):
            continue
        own, keep = own_of(sid), set(sh.get("keep_outside") or [])
        for repo, num, _, ids in rows:
            if own is not None and repo not in own:
                continue
            for tid in ids:
                h = (tasks.get(tid) or (None, {}, ""))[1]
                if h.get("type") != "task" or h.get("parent") == sid or tid in keep or (tid, sid) in seen:
                    continue
                seen.add((tid, sid))
                out.append((tid, f"PR пачки {sid} ({repo}#{num}, ветка {T.BATCH_BRANCH}{sid}) закрывает задачу, "
                                 f"а её parent — {h.get('parent') or 'пусто'}: в составе {sid} её нет; "
                                 f"parent решает координатор (pantheon task attach {tid} {sid} или оставить вне пачки: "
                                 f"pantheon task set {sid} keep_outside=…,{tid})"))
    return out


def board_drift_report(T, quiet):
    """Печатает board_drift предупреждениями (код выхода check не меняет); тик (quiet) молчит."""
    if quiet:
        return
    for k, text in board_drift(T, T.load_tasks(PANTHEON, T.WORK_TYPES), read_json(path("autoclose-prs.json"), {}),
                               T.inbox_items(PANTHEON)):
        print(f"предупреждение · доска · {k}: {text}")


NO_PARENT_FROM = "2026-11-03"  # задачи старше плана 1.0 без пачки — старый хвост, не тревожим
NO_PARENT_AGE = 86400


def check_no_parent(T, quiet):
    """Открытая задача type task без parent, созданная больше суток назад и не раньше NO_PARENT_FROM (metis-0940, слово
    владельца 06.11). Тик (quiet) — одна тревога на пачку новых номеров, каждый номер один раз (STATE/no-parent-seen.json,
    ушедшие из списка забываются); руками — предупреждение со всем списком. → список номеров."""
    t = now()
    ids = sorted(tid for tid, (_, h, _) in T.load_tasks(PANTHEON, T.WORK_TYPES).items()
                 if h.get("type") == "task" and h.get("status") not in ("done", "dropped", "inbox")
                 and not h.get("parent") and not h.get("batch") and str(h.get("created") or "") >= NO_PARENT_FROM
                 and t - (T.ts_of(h.get("created")) or t) > NO_PARENT_AGE)
    if not quiet:
        if ids:
            print(f"предупреждение · задачи без пачки старше суток: {_ids_text(ids)} — pantheon task batch-suggest, "
                  "затем pantheon task set ID parent=… mode=single mode_why=…")
        return ids
    seen = read_json(path("no-parent-seen.json"), [])
    seen = seen if isinstance(seen, list) else []
    fresh = [i for i in ids if i not in seen]
    if fresh:
        alert(f"задачи без пачки старше суток: {_ids_text(fresh)} — положить в пачку: pantheon task batch-suggest, "
              "затем pantheon task set ID parent=… mode=single mode_why=…", "check")
    keep = sorted(set(seen) & set(ids) | set(fresh))
    if keep != sorted(seen):
        os.makedirs(STATE, exist_ok=True)
        write_json(path("no-parent-seen.json"), keep)
    return ids


def check_task_projects(T, quiet):
    """project задачи — только имя проекта из directions.toml (metis-0323). → число задач с чужим именем; на тике
    (quiet) — одна тревога на набор. Реестра нет — не сверяем."""
    dirs = T.load_directions(PANTHEON)
    bad = T.project_problems(T.load_tasks(PANTHEON, T.WORK_TYPES), dirs) if dirs else []
    for tid, text in bad[:20]:
        print(f"ОШИБКА · {tid}: {text}")
    if len(bad) > 20:
        print(f"ОШИБКА · ещё {len(bad) - 20} задач с project не из directions.toml: pantheon task migrate-project")
    if bad:
        if quiet:
            alert_once("check-task-projects", "|".join(i for i, _ in bad),
                       f"задачи с project не из directions.toml: {len(bad)} — pantheon task migrate-project", "check")
    else:
        clear_once("check-task-projects")
    return len(bad)


def check(paths=None, quiet=False):
    T = tasks_mod()
    skill_paths = [p for p in (paths or []) if os.path.basename(p) == "SKILL.md"]
    if skill_paths:  # pantheon check путь/SKILL.md — только линтер навыков
        paths = [p for p in paths if p not in skill_paths]
        n_sk, sk_bad = check_skills(skill_paths, quiet)
        if not quiet or sk_bad:
            print(f"навыков: {n_sk}, с ошибками: {len(sk_bad)}")
        if not paths:
            return 1 if sk_bad else 0
    files = paths or list(T.task_files(PANTHEON))
    skill_arg_bad = sk_bad if skill_paths else []  # ошибки навыков из аргументов входят в код выхода
    bad, noheader, n = [], 0, 0
    for f in files:
        kind, errs, warns = T.check_file(f)
        n += 1
        if kind == "noheader":
            noheader += 1
        elif kind in ("broken", "error"):
            bad.append((f, errs, warns))
        elif warns and not quiet:
            print(f"предупреждение · {os.path.relpath(f, PANTHEON)}: {'; '.join(warns)}")
    for f, errs, _ in bad:
        print(f"ОШИБКА · {os.path.relpath(f, PANTHEON) if f.startswith(PANTHEON) else f}: {'; '.join(errs)}")
    if not paths and os.path.isdir(BOARD):
        text = "# Проблемы задач\n\nФайлы, которые выпали из доски: шапка не по схеме (schema.md).\n\n" + (
            "\n".join(f"- `{os.path.relpath(f, PANTHEON)}` — {'; '.join(e)}" for f, e, _ in bad) or "Нет — всё в порядке.") + "\n"
        pp = os.path.join(BOARD, "Проблемы.md")
        old = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
        if old != text:
            with open(pp, "w", encoding="utf-8") as fh:
                fh.write(text)
    coord_errs = 0
    if not paths:
        _check_long_state(quiet)
        check_moved(quiet)   # предупреждение, на код выхода check не влияет
        coord_errs = check_coordinators(quiet)
        coord_errs += check_task_projects(T, quiet)
        check_no_parent(T, quiet)  # без пачки старше суток: предупреждение, код выхода не меняет (metis-0940)
        for dname, fs in sorted((read_json(path("domains.json"), {}).get("domains") or {}).items()):
            # allow со старым mtime сборка по --if-changed не видит: check снимает окно сам, иначе следующий wake поднял
            # бы сессию снова (ревью argus PR #32)
            problems = project_allow_report(dname, allow_gate(dname, fs), quiet)
            if problems and quiet:  # тик (check --quiet): окно могла убрать ручная сборка, а сессия ещё работает
                project_allow_stop(dname, problems)
    # счётчики на пульте пишет тик — вторая копия данных: расхождение с задачами — ошибка (metis-0069)
    drift = []
    if not paths and os.path.isdir(BOARD):
        drift = T.check_projects(BOARD, T.load_tasks(PANTHEON, T.WORK_TYPES), now(), board_registry(T)[2])
        for d in drift:
            print(f"ОШИБКА · Доска/{d}")
    field_errs, field_warns = [], []
    nobody, unlinked, tails = [], [], []
    if not paths:  # поля «Итогов пачек» и ожидание PR/приёмки (metis-0308)
        night_end = "08:00"
        with contextlib.suppress(Exception):
            night_end = night_mod().config()[1]["end"]
        tasks_now = T.load_tasks(PANTHEON, T.WORK_TYPES)
        fixed = T.fix_closed(PANTHEON, now(), tasks_now)
        if fixed:
            tasks_now = T.load_tasks(PANTHEON, T.WORK_TYPES)
        nobody = T.bodyless_tasks(tasks_now, now())  # metis-0402: открытая задача без описания старше часа
        srcs = [_read_strict(os.path.join(PANTHEON, "decisions.md")), _read_strict(path("owner-log", "zeus.md")),
                _read_strict(path("owner-log", "board.jsonl"))]
        # источник не прочитался (не «файла нет») — проход пропущен: иначе seen запомнил бы набор без него, и следующий
        # проход назвал бы одной строкой все его id (argus a2 п. 3)
        unlinked = None if any(x is None for x in srcs) else T.unlinked_decisions(
            tasks_now, srcs[0], srcs[1], srcs[2].splitlines(), now())
        tails = ([("хвост", f"{i}:{hashlib.sha1(ln.encode()).hexdigest()[:10]}", f"{i}: «{ln[:140]}»")
                  for i, ln in T.tail_lines(tasks_now, now())]
                 + [("отчёт", p, f"{p}:{n}") for p, n in T.inbox_orphans(tasks_now, os.path.join(AI_HOME, "knowledge", "inbox"), now())]
                 + [("ревью", p, f"{p}:{n}") for p, n in T.review_debts(tasks_now, PANTHEON, now())]
                 + [("часть", f"{i}:{hashlib.sha1(ln.encode()).hexdigest()[:10]}", f"{i}: «{ln[:140]}»")
                    for i, ln in T.part_stalled(tasks_now, now())]
                 # metis-0615: «часть» без неотмеченных пунктов — остаток не записан; сразу, не через сутки
                 + [("часть-пусто", f"{i}:{hashlib.sha1(ln.encode()).hexdigest()[:10]}",
                     f"{i}: «{ln[:140]}»") for i, ln in T.part_no_items(tasks_now)]
                 # metis-0868 п. 5: время строки журнала ставит код; строка «из будущего» дописана руками на глаз
                 + [("время", f"{i}:{hashlib.sha1(ln.encode()).hexdigest()[:10]}",
                     f"{i}: строка журнала позже часов системы — «{ln[:140]}»") for i, ln in T.journal_future(tasks_now, now())])
        stall = T.stalled(tasks_now, now())  # metis-0583: doing/review без записи в журнале дольше 2 суток — без тревоги
        # metis-0572: расхождения доски («ответил, а waiting», «PR слит, а задача открыта») — в Хвосты.md и на карточку
        off = [("доска", k, f"{k}: {text}") for k, text in board_drift(T, tasks_now, read_json(path("autoclose-prs.json"), {}),
                                                                       T.inbox_items(PANTHEON))]
        tails_board(tails + [("застой", i, f"{i}: {st}, без записи в журнале {d} сут") for i, st, d in stall] + off)
        if stall and not quiet:  # сводка check: одна строка, не тревога на каждую задачу
            print(f"внимание · застой: {len(stall)} задач в doing/review без записи в журнале дольше {T.STALL_DAYS} сут — "
                  + ", ".join(i for i, _, _ in stall[:TAIL_SHOWN]) + (f" и ещё {len(stall) - TAIL_SHOWN}" if len(stall) > TAIL_SHOWN else "")
                  + " (список — Доска/Хвосты.md)")
        field_errs, field_warns = T.board_problems(tasks_now, now(), night_end, autoclose_mod().open_pr_tasks(path("autoclose.json")))
        field_errs = [(i, "status done без closed — проставлен из updated") for i in fixed] + field_errs
        for tid, text in field_errs:
            print(f"ОШИБКА · {tid}: {text}")
        for tid, text in field_warns:
            if not quiet:
                print(f"внимание · {tid}: {text}")
        if not quiet:  # сводка по направлениям и пропуски «Кто делает» (metis-0505): строки, не тревоги и не код выхода
            for dname, c in T.direction_summary(tasks_now, T.direction_names(PANTHEON, T.load_directions(PANTHEON))).items():
                print(T.summary_line(dname, c))
                if c["no_mode"]:  # id — в плане migrate-mode --dry-run: тут их сотни у старых направлений
                    print(f"внимание · {dname}: без «Кто делает» (mode) открытых задач {c['no_mode']} — "
                          "список и правка: pantheon task migrate-mode --dry-run, затем без --dry-run")
    board_drift_report(T, quiet) if not paths else None  # расхождения доски (metis-0441)
    if not paths:
        board_md_check(quiet)  # board.md: размер «Сейчас», дата «Обновлено», сроки «По датам» (metis-0769)
    if not paths and not quiet:
        off = autoclose_off_reason(now())
        if off:
            print(f"предупреждение · {off}")
    view_drift = T.check_views(BOARD) if not paths else []  # у каждого вида Доска.base — строка «что здесь» (metis-0288)
    for d in view_drift:
        print(f"ОШИБКА · {d}")
    skill_bad = []
    if not paths:  # навыки: битая шапка молча отключает навык (metis-0258)
        n_sk, skill_bad = check_skills(None, quiet)
        if not quiet or skill_bad:
            print(f"навыков: {n_sk}, с ошибками: {len(skill_bad)}")
    if not quiet or bad:
        print(f"задач: {n}, с ошибками: {len(bad)}, без шапки: {noheader}")
    if quiet:  # тик: одна тревога на набор проблем, а не сбой задачи каждые 5 минут
        if bad:
            alert_once("check-problems", ",".join(sorted(f for f, _, _ in bad)),
                       f"задачи с битой шапкой: {len(bad)} — список в Доска/Проблемы.md", "check")
        else:
            clear_once("check-problems")
        if drift:
            alert_once("check-projects", "|".join(drift), f"пульт: счётчики проекта расходятся с задачами — {drift[0]}"
                       + (f" и ещё {len(drift) - 1}" if len(drift) > 1 else ""), "check")
        else:
            clear_once("check-projects")
        if view_drift:
            alert_once("check-views", "|".join(view_drift), f"доска: {view_drift[0]}", "check")
        else:
            clear_once("check-views")
        if skill_bad:
            alert_once("check-skills", "|".join(f for f, _ in skill_bad),
                       f"навыки с битой шапкой или ссылкой: {', '.join(os.path.basename(os.path.dirname(f)) for f, _ in skill_bad)[:200]}",
                       "check")
        else:
            clear_once("check-skills")
        if field_errs:
            alert_once("check-fields", "|".join(i for i, _ in field_errs),
                       f"задачи с пустыми полями «Итогов пачек» или done без closed: {', '.join(sorted({i for i, _ in field_errs}))[:200]}",
                       "check")
        else:
            clear_once("check-fields")
        if nobody:
            alert_once("check-nobody", "|".join(nobody),
                       f"задачи без описания дольше {T.NO_BODY_HOURS} ч (только заголовок и журнал): "
                       f"{', '.join(nobody[:12])}{f' и ещё {len(nobody) - 12}' if len(nobody) > 12 else ''} — "
                       "дописать цель и «готово, когда» (pantheon task set ID --body-file …) или закрыть", "check")
        else:
            clear_once("check-nobody")
        unlinked_alert(T, unlinked)
        tail_alert(T, tails)
        return 0
    return 1 if bad or drift or view_drift or field_errs or skill_bad or skill_arg_bad or coord_errs else 0


UNLINKED_SHOWN = 12  # сколько новых id называет одна тревога «без задачи»; остальные — следующим проходом


def unlinked_alert(T, unlinked):
    """Тревога «слово владельца с [id] без задачи» (metis-0402 г): один раз на id и только о новых. Показанные id — в
    STATE/unlinked-seen.json (id → когда впервые); показанным считается только названный в тревоге. Первый проход (файла нет или он испорчен) только запоминает то, что
    уже есть, без тревоги: старые вопросы окна Зевса задачи не имеют, и весь их набор стал бы шумом (argus a).
    unlinked None — источник не прочитался, проход пропущен. Под lock("unlinked") и запись раньше тревоги (metis-0409):
    два параллельных прохода не дадут одну строку дважды, а сбой записи не превращается в тревогу каждый проход.
    Сухой прогон без ALERTS_IN_DRYRUN только печатает тревогу и seen не пишет."""
    if unlinked is None:
        return
    p = path("unlinked-seen.json")
    dry = os.environ.get("PANTHEON_DRYRUN") == "1" and not os.environ.get("PANTHEON_ALERTS_IN_DRYRUN")
    with lock("unlinked"):
        try:
            with open(p, encoding="utf-8") as fh:
                seen = json.load(fh)
            if not isinstance(seen, dict):
                raise ValueError("не словарь")
        except (OSError, ValueError):
            seen = None
        t = now()
        fresh = [i for i in unlinked if i not in seen] if seen is not None else []
        shown = fresh[:UNLINKED_SHOWN]
        keep = {i: v for i, v in (seen or {}).items()
                if isinstance(v, (int, float)) and t - v <= (T.UNLINKED_DAYS + 1) * 86400}
        # показанными отмечаются только названные в тревоге (argus b, круг 2): иначе id с 13-го не появились бы нигде.
        # Первый проход запоминает всё; уже показанные, но вычищенные по сроку, — продлеваются, а не становятся новыми
        keep.update({i: t for i in unlinked if i not in keep and (seen is None or i in seen or i in shown)})
        if keep != seen and not dry:
            try:
                os.makedirs(STATE, exist_ok=True)
                write_atomic(p, json.dumps(keep, ensure_ascii=False, sort_keys=True))
            except OSError as e:
                print(f"предупреждение · unlinked-seen.json не записан ({e.strerror or e}) — тревога «без задачи» "
                      "отложена до следующего прохода", file=sys.stderr)
                return
        if shown:
            more = len(fresh) - len(shown)
            try:
                alert(f"слова владельца с [id] без задачи дольше {T.UNLINKED_MIN} мин: {', '.join(shown)}"
                      f"{f' и ещё {more} (назову следующим проходом)' if more else ''} — завести задачу "
                      "(pantheon task new, [id] в тексте) или дописать в decisions.md отдельной строкой «не задача: [id] — причина»",
                      "check")
            except Exception:
                if keep != seen and not dry and seen is not None:  # тревога не записана — id снова новые
                    with contextlib.suppress(OSError):
                        write_atomic(p, json.dumps(seen, ensure_ascii=False, sort_keys=True))
                raise


TAIL_SHOWN = 12
TAIL_TEXT = {"хвост": "хвост в журнале без задачи (нет id задачи в строке)",
             "отчёт": "файл inbox старше суток без задачи разбора (нет ссылки source/from или в тексте)",
             "ревью": "ревью с находкой Д без задачи (нет ссылки на файл ревью)",
             "часть": "PR слит с «часть», задача без движения дольше 24 ч (закрыть, завести остаток или записать ход)",
             "время": "строка журнала задачи позже часов системы — дописана руками, время на глаз (записи — через "
                      "pantheon task set --note, время ставит код)"}
# виды только для Доска/Хвосты.md: тревоги на каждую нет (metis-0583) — список и строка в сводке check
TAIL_BOARD_TEXT = dict(TAIL_TEXT, **{"застой": "застой doing/review (записать ход, закрыть или вернуть в очередь)",
                                     "доска": "доска расходится с задачей (поправить статус задачи или вход)",
                                     "часть-пусто": "PR слит с «часть», а неотмеченных пунктов «Готово, когда» нет (вписать "
                                                    "пункт остатка или закрыть задачу)"})
TAIL_CARD = {"хвост": "хвост в журнале", "часть": "PR слит с «часть», без движения", "застой": "застой",
             "доска": "доска", "время": "время журнала", "часть-пусто": "PR слит с «часть», остаток не записан"}  # подпись свойства «Хвост» карточки; отчёт и ревью — файлы, не задачи


def tails_by_task(items):
    """{id: [«подпись: текст»]} для свойства «Хвост» карточек (metis-0572, 0506): где — «<id>: …»."""
    out = {}
    for kind, _, where in items:
        tid, sep, rest = str(where).partition(": ")
        if kind in TAIL_CARD and sep and re.fullmatch(r"[a-z][a-z0-9]{1,11}-\d{3,}", tid):
            out.setdefault(tid, []).append(f"{TAIL_CARD[kind]}: {rest}"[:200])
    return out


def tails_board(items):
    """Доска/Хвосты.md (metis-0572): все хвосты, как их видит проход сейчас, а не только новые для тревоги — тревогу
    первый проход глотает, а владелец смотрит доску. Файла нет, пока доски нет; пишется только при изменении.
    Хвосты задач — ещё в STATE/tails.json: проход доски ставит их свойством «Хвост» карточки (вид «Хвосты»)."""
    by_task = tails_by_task(items)
    if read_json(path("tails.json"), None) != by_task:
        os.makedirs(STATE, exist_ok=True)
        write_atomic(path("tails.json"), json.dumps(by_task, ensure_ascii=False, sort_keys=True))
    if not os.path.isdir(BOARD):
        return
    rows = [f"- **{TAIL_BOARD_TEXT[kind].split(' (')[0]}** — {where}" for kind, _, where in items]
    text = ("# Хвосты\n\nЧто плановый проход считает потерянным: строка журнала без задачи, файл inbox и ревью без задачи, "
            "слитый PR «часть» без движения или без пунктов остатка, задача doing/review без записи в журнале дольше 2 суток. Погасить — строка "
            "в журнале задачи «→ <id>» или «не задача: …», задача на разбор или запись хода в журнал.\n\n"
            + ("\n".join(rows) or "Нет — всё в порядке.") + "\n")
    pp = os.path.join(BOARD, "Хвосты.md")
    old = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
    if old != text:
        write_atomic(pp, text)


def tail_alert(T, items):
    """Тревоги «хвосты не теряются» (metis-0504): items — [(вид, ключ, место)], вид хвост | отчёт | ревью, место — id
    задачи и строка журнала либо файл:строка. Стиль unlinked_alert: один раз на ключ, только о новых. Первый проход
    (файла STATE/tail-seen.json нет или он испорчен) запоминает всё и даёт одну сводную тревогу — сколько хвостов
    уже есть по видам и где список (Доска/Хвосты.md), без перечня: молча старые хвосты не пропадают (metis-0572), а
    сотня строк не становится шумом. Записи о том, чего в наборе
    больше нет (хвост поправили, задачу завели), из файла уходят; по виду называется не больше TAIL_SHOWN."""
    p = path("tail-seen.json")
    try:
        with open(p, encoding="utf-8") as fh:
            seen = json.load(fh)
        if not isinstance(seen, dict):
            raise ValueError("не словарь")
    except (OSError, ValueError):
        seen = None
    t = now()
    keep, shown_all = {}, set()
    for kind in TAIL_TEXT:
        mine = [(f"{kind}|{k}", where) for kd, k, where in items if kd == kind]
        fresh = [(k, w) for k, w in mine if k not in seen] if seen is not None else []
        shown = fresh[:TAIL_SHOWN]
        if shown:
            more = len(fresh) - len(shown)
            alert(f"{TAIL_TEXT[kind]}: {'; '.join(w for _, w in shown)}"
                  f"{f' и ещё {more} (назову следующим проходом)' if more else ''} — завести задачу "
                  "(pantheon task new, ссылка на файл или id в тексте)", "check")
        shown_all.update(k for k, _ in shown)
        # названные в тревоге и уже показанные остаются; неназванные (сверх TAIL_SHOWN) — нет; первый проход помнит всё
        keep.update({k: (seen or {}).get(k, t) for k, _ in mine if seen is None or k in seen or k in shown_all})
    if keep != seen:
        os.makedirs(STATE, exist_ok=True)
        write_atomic(p, json.dumps(keep, ensure_ascii=False, sort_keys=True))
    if seen is None and keep:  # после записи: сбой записи — следующий проход снова первый, а не тревога каждый тик
        by_kind = {}
        for k in keep:
            by_kind[k.split("|", 1)[0]] = by_kind.get(k.split("|", 1)[0], 0) + 1
        alert(f"хвосты: слежение начато, уже есть {len(keep)} — "
              + ", ".join(f"{TAIL_TEXT[kd].split(' (')[0]} {by_kind[kd]}" for kd in TAIL_TEXT if kd in by_kind)
              + "; список — Доска/Хвосты.md, дальше тревога только о новых", "check")


def _read_strict(p):
    """Текст файла; «файла нет» — пусто, любой другой сбой чтения — None (источник не прочитан)."""
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError):
        return None


# --- дежурный и управление сессиями (шаг 1.4) — lib/watch.py ---------------------------------------------------------
WATCH_CMDS = {"watch", "agents", "revisits", "stop", "resume", "pause", "restart", "saved", "who", "infra-check",
              "launch-question", "wt"}


def watch_cmd(cmd, rest, over=False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_watch", os.path.join(LIB, "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(sys.modules[__name__])
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    if cmd == "wake":
        return w.wake_one(rest, who, over)
    return {"watch": lambda: w.watch(dry="--dry-run" in rest), "agents": w.agents_cmd, "revisits": w.revisits,
            "stop": lambda: w.stop(rest, who), "resume": lambda: w.resume(rest, who), "pause": lambda: w.pause(rest, who),
            "restart": lambda: w.restart(rest, who), "saved": lambda: w.saved_cmd(rest, who), "who": w.who,
            "infra-check": w.infra_cmd, "launch-question": lambda: w.launch_question_cmd(rest),
            "wt": lambda: w.wt_cmd(rest)}[cmd]()


def usage_report(rest):
    """pantheon usage [дней] — отчёт расхода (scripts/usage.py) в ~/ai/pantheon/metrics/usage/<дата>.txt, строка в
    тревогах (SCHED-11: раз в неделю). Две записи независимы: файл не записан — отчёт целиком в stdout и «отчёт не
    сохранён: …» в stderr; тревога не записана — «тревога не записана: …» в stderr; хоть одна не удалась — код 1
    (плановый проход поднимет тревогу), отчёт при этом напечатан."""
    days = rest[0] if rest and rest[0].isdigit() else "7"
    r = subprocess.run([sys.executable, "-I", os.path.join(PLUGIN, "scripts", "usage.py"), days], capture_output=True,
                       text=True, timeout=600)
    if r.returncode:
        print(r.stderr[-2000:], file=sys.stderr)
        return r.returncode
    out = os.path.join(PANTHEON, "metrics", "usage", stamp()[:10] + ".txt")
    total = next((ln for ln in r.stdout.splitlines() if ln.startswith("Итого")), "").strip()
    code = 0
    saved = False
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        write_atomic(out, r.stdout)
        saved = True
    except OSError as e:
        # metis-0354: в песочнице окна роли metrics/usage закрыт на запись, а расход недели нужен — отчёт целиком
        # в stdout, причина в stderr, код 1 (плановый проход поднимет тревогу, сбой не теряется).
        # stdout буферизован в трубе run_job и выходит при завершении, поэтому flush до stderr: причина остаётся
        # последней строкой вывода — в тревоге «упала» и в хвосте журнала.
        sys.stdout.write(r.stdout)
        sys.stdout.flush()
        print(f"отчёт не сохранён: {e.strerror or e}", file=sys.stderr)
        sys.stderr.flush()
        code = 1
    if saved:  # тревога со ссылкой на файл — только если файл есть; иначе сбой поднимет тик по коду 1
        try:
            alert(f"отчёт расхода за {days} дн.: {total or 'готов'} — {out.replace(HOME, '~')}", "usage")
        except OSError as e:
            print(f"тревога не записана: {e.strerror or e}", file=sys.stderr)
            code = 1
    if saved:
        print(out)
    return code


# --- обновления плагинов agent-kit (metis-0052) ----------------------------------------------------------------
# Тик раз в 10 минут, вне песочницы: каталог agent-kit → новые версии установленных плагинов → claude plugin update.
# Тесты идут до слияния — workflow tests в GitHub Actions на каждый PR в main (п. 8 страницы упрощения 27.10); после
# слияния workflow release поднимает номер и пишет .claude-plugin/releases.json (metis-0512). Тик ставит версию, только
# если запись выпуска совпала с каталогом — та же версия и то же дерево (_release_problem); локального прогона тестов,
# порога свопа и давления памяти больше нет: выпуск доходит за один плановый проход. Хеш дерева каталога сверяется с
# тем, что встало: update сам обновляет каталог и может поставить другое дерево — тогда критическая тревога, живой
# код и окна остаются на последнем проверенном (verified.json, metis-0321).

MARKETPLACE = "agent-kit"


def _tree_hash(root):
    """sha256 дерева плагина: относительные пути и содержимое, ссылки — по тексту ссылки. Без .git и __pycache__ на
    любой глубине и без точечных файлов и папок верхнего уровня, кроме .claude-plugin (в кэше лишний `.in_use`).
    None — папки нет."""
    if not isinstance(root, str) or not os.path.isdir(root):
        return None
    h = hashlib.sha256()

    def walk(d, rel):
        for e in sorted(os.scandir(d), key=lambda e: e.name):
            if e.name in (".git", "__pycache__") or (not rel and e.name.startswith(".") and e.name != ".claude-plugin"):
                continue
            r = f"{rel}/{e.name}" if rel else e.name
            if e.is_symlink():
                h.update(b"L\0" + r.encode() + b"\0" + os.readlink(e.path).encode() + b"\0")
            elif e.is_dir():
                walk(e.path, r)
            elif e.is_file():
                fh = hashlib.sha256()
                with open(e.path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        fh.update(chunk)
                h.update(b"F\0" + r.encode() + b"\0" + fh.hexdigest().encode() + b"\0")

    walk(root, "")
    return h.hexdigest()


def _memory_pressure_direct():
    """Давление памяти macOS (kern.memorystatus_vm_pressure_level, как _load_snapshot): 1 норма, 2 предупреждение,
    4 критично; другое значение или сбой чтения — None. PANTHEON_FAKE_PRESSURE — подмена для тестов и проб, как
    PANTHEON_FAKE_SWAP; пустая строка — «не прочитано». Читает сам sysctl: в окне роли он даёт EPERM."""
    fake = os.environ.get("PANTHEON_FAKE_PRESSURE")
    try:
        if fake is not None:
            level = int(fake)
        else:
            r = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True,
                               text=True, timeout=10)
            level = int(r.stdout.strip()) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return level if level in (1, 2, 4) else None


# --- замеры вне окна (metis-0537) -------------------------------------------------------------------------------
# В окне роли sysctl памяти даёт EPERM, а `claude -p` без сети не работает. Замеры делает плановый проход (тик, вне
# окна) и пишет STATE/probes.json; окно только читает. Файл старше PROBE_MAX_AGE, битый или без поля — как «не
# прочитано» (None): поведение прежнее, ничего не падает.

PROBE_MAX_AGE = 600  # секунд: тик идёт раз в минуту-две, десять минут — запас на пропущенные проходы
CONTEXT_PROBE_HOURS = 6
CONTEXT_PROBE_TEXT_MAX = 6000


def probes_path():
    return path("probes.json")


def probe_fresh(section, max_age=PROBE_MAX_AGE):
    """Раздел файла замеров (dict) и его возраст в секундах; нет файла, битый, без времени, из будущего или старше
    max_age — None."""
    data = read_json(probes_path())
    sec = data.get(section) if isinstance(data, dict) else None
    if not isinstance(sec, dict):
        return None
    ts = sec.get("time")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    age = now() - ts
    if age < 0 or age > max_age:
        return None
    return sec, age


def probe_value(key):
    """Число из свежего замера памяти; нет, старое или не число — None."""
    got = probe_fresh("mem")
    v = got[0].get(key) if got else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _free_pct_direct():
    try:
        r = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"free percentage:\s*(\d+)%", r.stdout)
    return int(m.group(1)) if m else None


def probes_measure(t=None):
    """Замер памяти — только вне окна роли (тик): своп, давление, свободно %. Ничего не прочитано — файл не трогаем."""
    t = now() if t is None else t
    mem = {"time": t, "swap_gb": None, "pressure": _memory_pressure_direct(), "free_pct": _free_pct_direct()}
    with contextlib.suppress(Exception):
        mem["swap_gb"] = watch_mod().swap_gb()
    if all(mem[k] is None for k in ("swap_gb", "pressure", "free_pct")):
        return None
    data = read_json(probes_path())
    data = data if isinstance(data, dict) else {}
    data.update(v=1, mem=mem)
    write_json(probes_path(), data)
    return mem


def context_probe_hours():
    """Выключатель замера /context: файла STATE/probe-context нет — выключен (по умолчанию: claude -p стоит лимита).
    Есть — включён, в файле число часов между замерами (пусто или не число — CONTEXT_PROBE_HOURS)."""
    p = path("probe-context")
    if not os.path.isfile(p):
        return None
    try:
        h = float(open(p).read().strip())
    except (OSError, ValueError):
        return CONTEXT_PROBE_HOURS
    return h if h > 0 else CONTEXT_PROBE_HOURS


def probes_context_run(t=None):
    """Один замер `claude -p /context` (вне окна): текст и код выхода в probes.json. Сбой тоже записывается."""
    t = now() if t is None else t
    sec = {"time": t, "rc": None, "text": "", "error": None}
    try:
        r = subprocess.run([claude_bin(), "-p", "/context"], capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL, cwd=STATE, env=claude_env())
        sec.update(rc=r.returncode, text=r.stdout[:CONTEXT_PROBE_TEXT_MAX])
        if r.returncode != 0:
            sec["error"] = (r.stderr.strip().splitlines() or ["код выхода не 0"])[-1][:200]
    except (OSError, subprocess.TimeoutExpired) as e:
        sec["error"] = f"{type(e).__name__}: {e}"[:200]
    data = read_json(probes_path())
    data = data if isinstance(data, dict) else {}
    data.update(v=1, context=sec)
    write_json(probes_path(), data)
    return sec


def probes_tick(t):
    """Шаг тика: замер памяти каждый проход; /context — если включён и прошло N часов (отдельным процессом: claude -p
    идёт минутами). Время запуска пишется до старта, чтобы следующий тик не запустил второй замер."""
    try:
        probes_measure(t)
        hours = context_probe_hours()
        if hours is None or locked("probe-context"):
            return
        data = read_json(probes_path())
        last = (data.get("context") or {}).get("requested") if isinstance(data, dict) else None
        if isinstance(last, (int, float)) and 0 <= t - last < hours * 3600:
            return
        data = data if isinstance(data, dict) else {}
        ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
        ctx["requested"] = t
        data.update(v=1, context=ctx)
        write_json(probes_path(), data)
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            with open(path("dryrun.log"), "a") as fh:
                fh.write(f"{int(t)} probes-context\n")
            return
        subprocess.Popen([os.path.join(PLUGIN, "bin", "pantheon"), "probes", "context"], env=os.environ.copy(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:  # сбой замеров не должен останавливать тик
        alert_once("probes-tick", type(e).__name__, f"замеры вне окна: проход упал ({type(e).__name__}: {e})",
                   "pantheon-tick")


def probes_cmd(args):
    """pantheon probes [show|measure|context]: show (по умолчанию) — что лежит в файле замеров и с каким возрастом;
    measure — снять память сейчас (вне окна); context — снять /context сейчас (стоит лимита, только вне окна)."""
    sub = args[0] if args else "show"
    if sub == "measure":
        mem = probes_measure()
        print(json.dumps(mem, ensure_ascii=False) if mem else "не прочиталось ничего", file=sys.stdout if mem else sys.stderr)
        return 0 if mem else 1
    if sub == "context":
        with lock("probe-context", block=False) as got:
            if not got:
                print("замер /context уже идёт", file=sys.stderr)
                return 1
            sec = probes_context_run()
        print(f"/context: код {sec['rc']}" + (f", {sec['error']}" if sec["error"] else ""))
        return 0 if sec["rc"] == 0 else 1
    if sub != "show":
        print("pantheon probes [show|measure|context]", file=sys.stderr)
        return 2
    data = read_json(probes_path())
    for name in ("mem", "context"):
        sec = data.get(name) if isinstance(data, dict) else None
        ts = sec.get("time") if isinstance(sec, dict) else None
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            print(f"{name}: нет замера")
            continue
        age = now() - ts
        fresh = "свежий" if name == "context" or 0 <= age <= PROBE_MAX_AGE else "старый, окно его не берёт"
        body = {k: v for k, v in sec.items() if k not in ("time", "text")}
        print(f"{name}: {int(age)} с назад ({fresh}) {json.dumps(body, ensure_ascii=False)}")
        if name == "context" and sec.get("text"):
            print(sec["text"])
    print("замер /context: " + ("включён, раз в %g ч" % context_probe_hours() if context_probe_hours() else
                                "выключен (включить: записать число часов в %s)" % path("probe-context")))
    return 0


# --- команды в отдельных модулях lib/ (metis-0586) ------------------------------------------------------------------
# Группы команд вынесены в lib/<модуль>.py без изменения поведения. Модуль получает P — имена этого модуля — до
# выполнения своего файла, а его имена из __all__ становятся именами pantheon: main, остальной код, тесты и другие
# модули (P.xxx) зовут их как раньше. Сборка окон (sandbox_build и всё, на что она ссылается) остаётся здесь: её
# признак ядра в шлюзе guard (metis-0404) смотрит только этот файл.
class _Core:
    """P для lib/<модуль>.py: чтение и запись — прямо в globals() pantheon в момент обращения. Так подмены тестов
    (P.x = …) и запись P.HOME из merge.py видны и в модулях; сам модуль pantheon есть в sys.modules не всегда (тесты
    грузят pantheon.py по пути файла)."""
    __slots__ = ("_g",)

    def __init__(self, g):
        object.__setattr__(self, "_g", g)

    def __getattr__(self, name):
        try:
            return self._g[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._g[name] = value


def _attach(name):
    """lib/<name>.py: загрузить с P и сделать его имена (__all__) именами этого модуля."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_" + name, os.path.join(LIB, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    m.P = _Core(globals())
    spec.loader.exec_module(m)
    globals().update({k: getattr(m, k) for k in m.__all__})
    return m


_attach("review_rules")   # правило вердиктов argus — ядро защит (metis-0858); review.py берёт его через P
_attach("review")
_attach("plugins")
_attach("taskcli")
_attach("consent")
_attach("jobs")
_attach("archive")
_attach("quarantine")
_attach("instructions")
_attach("rolecmd")
_attach("sessions")
_attach("batch")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "review":
        return review_cmd(rest)
    if cmd == "tick":
        tick()
        return 0
    if cmd == "run-job":
        if not rest or not JOB_NAME.fullmatch(rest[0]):
            print("pantheon run-job: имя задачи не по образцу", file=sys.stderr)
            return 2
        return run_job(rest[0])
    if cmd == "jobs":
        if not rest:
            jobs_show()
            return 0
        if rest[0] in ("pause", "resume", "disable", "enable", "renew") and len(rest) >= 2:
            return jobs_set(rest[0], rest[1], rest[2] if len(rest) > 2 else None)
    if cmd == "alert" and rest:
        who = "agent"
        if "--from" in rest:
            i = rest.index("--from")
            if i + 1 >= len(rest):
                print("pantheon alert: после --from нужно имя", file=sys.stderr)
                return 2
            who, rest = rest[i + 1], rest[:i] + rest[i + 2:]
        critical = "--critical" in rest
        rest = [a for a in rest if a != "--critical"]
        if not " ".join(rest).strip():
            print("pantheon alert: пустая строка", file=sys.stderr)
            return 2
        alert(("КРИТИЧНО: " if critical else "") + " ".join(rest), who)
        if critical:  # COMM-08: безопасность, деньги, данные клиентов, юридическое, прод, контракт — сразу владельцу
            # отправителя называет он сам (--from, PANTHEON_ROLE — переменные вызова): заголовок не утверждает, кто
            # прислал, имя — в тексте со словами «со слов». Сразу всегда (и ночью), но в счёт бюджета и в журнал
            notify_critical(f"{' '.join(rest)[:200]} (со слов: {' '.join(who.split())[:40]})")
        return 0
    if cmd == "notify" and rest:  # metis-0907: уведомление macOS сразу (хук wait-owner); щелчок — доска или --target
        opts = {"--title": "Пантеон", "--group": None, "--target": None}
        words = []
        it = iter(rest)
        for a in it:
            if a in opts:
                v = next(it, None)
                if v is None:
                    print(f"pantheon notify: после {a} нужно значение", file=sys.stderr)
                    return 2
                opts[a] = v
            else:
                words.append(a)
        if not " ".join(words).strip():
            print("pantheon notify: пустой текст", file=sys.stderr)
            return 2
        notify(" ".join(words)[:300], title=opts["--title"], target=opts["--target"], group=opts["--group"])
        return 0
    if cmd == "archive":
        return archive()
    if cmd == "domains" and rest[:1] == ["build"]:
        return domains_build(if_changed="--if-changed" in rest)
    if cmd == "view":
        return view(quiet="--quiet" in rest)
    if cmd == "commit":
        return commit()
    if cmd == "board" and rest[:1] == ["archive"]:
        return board_archive(rest[1:])
    if cmd == "board":
        return board()
    if cmd == "sync-answers":
        return sync_answers()
    if cmd == "autoclose":
        return autoclose_cmd(rest)
    if cmd == "who-canvas":
        return who_canvas_cmd(rest)
    if cmd == "batch-suggest":
        return batch_suggest_run(rest)
    if cmd == "status":
        return status()
    if cmd == "check" and "--moved" in rest:
        return 1 if check_moved(force=True) else 0
    if cmd == "migrate-paths":
        return migrate_paths_cmd(rest)
    if cmd == "check":
        return check([a for a in rest if not a.startswith("-")] or None, quiet="--quiet" in rest)
    if cmd == "task":
        return task_cmd(rest)
    if cmd == "executors":
        return executors_mod().cli(rest, _task_head)
    if cmd == "exec":
        return executors_mod().exec_cli(rest)
    if cmd == "start":
        return start(rest)
    if cmd == "wake":
        over = OVER_CAP in rest  # metis-0444: флаг в любом месте строки, до разбора остального
        rest = [a for a in rest if a != OVER_CAP]
        if rest[:1] == ["hestia"]:
            return wake_hestia(rest)  # потолок Гестию не держит (CAP_FREE)
        if rest and not rest[0].startswith("-") and "--task" in rest:  # окно лида направления без координатора
            return wake_lead(rest, over)
        if rest and not rest[0].startswith("-") and rest[0] in hq_led():
            print(f"pantheon wake: {hq_led_why(rest[0])}", file=sys.stderr)
            return 2
        if rest and not rest[0].startswith("-"):
            return watch_cmd("wake", rest, over)
        return wake(rest, over)
    if cmd == "roles" and rest[:1] == ["build"]:
        src = out = None
        flags = rest[1:]
        try:
            if flags:
                if len(flags) % 2 or any(a not in ("--out", "--src") for a in flags[::2]) \
                        or len(set(flags[::2])) != len(flags) // 2 or "--out" not in flags[::2]:
                    raise ValueError("roles build [--out <папка> [--src <папка шаблонов>]]")
                kv = dict(zip(flags[::2], flags[1::2]))
                out, src = kv["--out"], kv.get("--src")
            made = roles_build(src, out)
        except ValueError as e:
            print(f"roles build: {e}", file=sys.stderr)
            return 2
        print(f"роли: {', '.join(made) if made else 'без изменений'}")
        return 0
    if cmd == "role":
        return role_cmd(rest)
    if cmd == "direction":
        return direction(rest)
    if cmd == "instructions":
        return instructions_check(quiet="--quiet" in rest)
    if cmd == "approve":
        return approve(rest)
    if cmd == "consent":
        return consent(rest)
    if cmd == "reap":
        return culprits_mod().reap(rest)
    if cmd in WATCH_CMDS:
        return watch_cmd(cmd, rest)
    if cmd == "roster":
        return roster_cmd(rest)
    if cmd == "usage":
        return usage_report(rest)
    if cmd == "metrics":
        return metrics_cmd(rest)
    if cmd == "reboot-reminder":
        return awake_mod().reboot_reminder(rest)
    if cmd == "night":
        return night_mod().main(rest)
    if cmd == "read":
        return read_mod().main(rest)
    if cmd == "merge":
        return merge_mod().main(rest)
    if cmd == "outside":
        return outside_mod().main(rest)
    if cmd == "browser":
        return browser_mod().main(rest)
    if cmd == "handoff":
        return handoff_mod().main(rest)
    if cmd == "batch":
        return batch_cmd(rest)
    if cmd == "probes":
        return probes_cmd(rest)
    if cmd == "traces":
        return traces_mod().main(rest)
    if cmd == "mmv":
        return mmv_mod().main(rest, STATE, now())
    if cmd == "qmd":
        return qmd_mod().main(rest)
    if cmd == "plugins":
        return plugins_cmd(rest)
    if cmd == "service-run":
        if len(rest) != 1 or not JOB_NAME.fullmatch(rest[0]):
            print("pantheon service-run: имя службы не по образцу", file=sys.stderr)
            return 2
        return service_run(rest[0])
    if cmd == "install":
        return install()
    if cmd == "uninstall":
        return uninstall()
    print(f"pantheon: не понял «{' '.join(argv)}». Справка — pantheon help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
