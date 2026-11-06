#!/bin/zsh
# Копия ~/ai/pantheon только для чтения для Obsidian. Задача планировщика Пантеона `pantheon view` (каждый тик —
# страховка); сразу после записи агента в ~/ai/pantheon её же запускает хук PostToolUse плагина pantheon.
# Проверено 14.10 на временных папках и отдельном экземпляре Obsidian 1.14.4.
#
# Файлы копии — без права записи, папки (кроме корня и .obsidian) — тоже: Obsidian не даст ни править,
# ни переименовать, ни перенести, ни удалить заметку. Если лишний файл всё же появился (новая заметка в корне,
# корзина Obsidian .trash, сбой прав): копию файла оригинала (переименование, перенос, корзина) просто
# удаляем, остальное переносим во входящие внутри зашифрованного ~/ai/pantheon (inbox-view/ — разбирает штаб).
# Служебное не переносим и не трогаем (metis-0920). Из 7779 файлов во входящих 7605 были `.claude__worktrees__agent-*`:
# рабочие копии агентов из ~/ai/pantheon/.claude/worktrees — rsync клал их в копию, а когда в оригинале их удаляли,
# перенос «лишнего» отправлял оставшееся в копии во входящие. Поэтому .claude/ в копии не переносится, не удаляется
# rsync и остаётся записываемой (там пишет Claude Code). Входящие inbox-view/ и архив уборки archive/inbox-view-*
# в копию не копируются (иначе круг: копия → входящие → копия), а уже попавшие в копию — удаляются.
# В незашифрованное (например ~/ai/knowledge) отсюда ничего не уходит: в ~/ai/pantheon имена и дела клиентов.
SRC="${1:-$HOME/ai/pantheon}"; DST="${2:-$HOME/ai/pantheon-view}"; INBOX="${3:-$SRC/inbox-view}"
# Доска владельца — единственная записываемая папка копии: её карточки рисует `pantheon board`, двигает владелец;
# копия её не трогает (ни перенос «лишнего», ни rsync --delete, ни снятие прав).
BOARD="Доска"
# оригинал и копия — одна папка (в том числе через ссылку или другой регистр): rm -rf входящих ниже удалил бы настоящие
if [[ "$SRC" -ef "$DST" ]]; then echo "view-sync: оригинал и копия — одна папка ($SRC)" >&2; exit 2; fi
mkdir -p "$DST"
# входящие внутри оригинала: путь от $SRC (по умолчанию inbox-view); снаружи оригинала — исключать нечего
INBOX_REL=""
[[ "$INBOX" == "$SRC"/* ]] && INBOX_REL="${INBOX#$SRC/}"
[[ "$INBOX_REL" == (*..*|/*) ]] && INBOX_REL=""
inbox_ex=()
[[ -n "$INBOX_REL" ]] && inbox_ex=(--exclude "/$INBOX_REL")
# Образец настроек Obsidian (тема, сниппеты, закладки; без workspace.json): кладётся только если в копии нет .obsidian
# совсем — на новом Mac или у нового пользователя; существующую папку не трогаем (metis-0131). Закладки в существующей
# папке досыпает тик доски (tasks.py _sync_bookmarks, metis-0324) из того же образца — сюда за ними ходить не нужно.
SAMPLE="${4:-${0:A:h}/../share/pantheon-view-obsidian}"
if [[ ! -e "$DST/.obsidian" && -d "$SAMPLE" ]]; then
  cp -R "$SAMPLE" "$DST/.obsidian" && chmod -R u+w "$DST/.obsidian"
fi
stamp=$(date +%Y%m%d-%H%M%S)

# входящие в копии Obsidian — след старого круга: убрать (папки копии открываются строкой ниже)
# открыть папки копии на время обновления (rsync и перенос лишнего пишут в них)
find "$DST" -mindepth 1 \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" -o -path "$DST/.claude" \) -prune -o -type d ! -perm -u+w -print0 | xargs -0 chmod u+w 2>/dev/null

for rel in inbox-view ${INBOX_REL:+"$INBOX_REL"} ${${(f)"$(cd "$DST" 2>/dev/null && print -l archive/inbox-view-*(N/))"}}; do
  [[ -d "$DST/$rel" && ! -L "$DST/$rel" ]] && { find "$DST/$rel" -type d -exec chmod u+w {} + 2>/dev/null; rm -rf "$DST/$rel"; }
done

src_hashes=""
find "$DST" \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" -o -path "$DST/.claude" \) -prune -o -type f -print | while IFS= read -r f; do
  rel="${f#$DST/}"
  [[ -e "$SRC/$rel" ]] && continue          # файл из оригинала — его обновит rsync
  [[ "${rel:t}" == .* ]] && continue         # .DS_Store и прочие служебные — удалит rsync
  [[ -s "$f" ]] || continue                  # пустая «Без названия.md» — тоже
  [[ -n "$src_hashes" ]] || src_hashes=$(find "$SRC" \( -path "$SRC/.git" -o -path "$SRC/${INBOX_REL:-inbox-view}" -o -path "$SRC/archive/inbox-view-*" \) -prune -o -type f -print0 \
    | xargs -0 shasum -a 256 2>/dev/null | cut -d' ' -f1)
  h=$(shasum -a 256 "$f" | cut -d' ' -f1)
  if [[ $'\n'"$src_hashes"$'\n' == *$'\n'"$h"$'\n'* ]]; then
    rm -f "$f"                               # копия файла оригинала: переименование, перенос, корзина
  else
    mkdir -p "$INBOX"
    mv "$f" "$INBOX/$stamp-${rel//\//__}"
  fi
done
# -rlt без -p: права копии не тянем из оригинала, их снимают строки ниже
/usr/bin/rsync -rlt --delete --exclude .obsidian --exclude .git --exclude /.claude --exclude "/$BOARD" \
  --exclude /inbox-view --exclude "/archive/inbox-view-*" "${inbox_ex[@]}" "$SRC/" "$DST/"
# только новые и обновлённые файлы (openrsync всё равно касается времени каждого файла — Obsidian это
# не замечает, проверено 14.10: событие modify приходит только на изменённый файл)
find "$DST" \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" -o -path "$DST/.claude" \) -prune -o -type f -perm -u+w -exec chmod a-w {} +
find "$DST" -mindepth 1 \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" -o -path "$DST/.claude" \) -prune -o -type d -perm -u+w -print0 | xargs -0 chmod a-w 2>/dev/null
exit 0
