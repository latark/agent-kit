#!/bin/zsh
# Копия ~/ai/pantheon только для чтения для Obsidian. Задача планировщика Пантеона `pantheon view` (каждый тик —
# страховка); сразу после записи агента в ~/ai/pantheon её же запускает хук PostToolUse плагина pantheon.
# Проверено 14.10 на временных папках и отдельном экземпляре Obsidian 1.14.4.
#
# Файлы копии — без права записи, папки (кроме корня и .obsidian) — тоже: Obsidian не даст ни править,
# ни переименовать, ни перенести, ни удалить заметку. Если лишний файл всё же появился (новая заметка в корне,
# корзина Obsidian .trash, сбой прав): копию файла оригинала (переименование, перенос, корзина) просто
# удаляем, остальное переносим во входящие внутри зашифрованного ~/ai/pantheon (inbox-view/ — разбирает штаб).
# В незашифрованное (например ~/ai/knowledge) отсюда ничего не уходит: в ~/ai/pantheon имена и дела клиентов.
SRC="${1:-$HOME/ai/pantheon}"; DST="${2:-$HOME/ai/pantheon-view}"; INBOX="${3:-$SRC/inbox-view}"
# Доска владельца — единственная записываемая папка копии: её карточки рисует `pantheon board`, двигает владелец;
# копия её не трогает (ни перенос «лишнего», ни rsync --delete, ни снятие прав).
BOARD="Доска"
mkdir -p "$DST"
stamp=$(date +%Y%m%d-%H%M%S)

# открыть папки копии на время обновления (rsync и перенос лишнего пишут в них)
find "$DST" -mindepth 1 \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" \) -prune -o -type d ! -perm -u+w -print0 | xargs -0 chmod u+w 2>/dev/null

src_hashes=""
find "$DST" \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" \) -prune -o -type f -print | while IFS= read -r f; do
  rel="${f#$DST/}"
  [[ -e "$SRC/$rel" ]] && continue          # файл из оригинала — его обновит rsync
  [[ "${rel:t}" == .* ]] && continue         # .DS_Store и прочие служебные — удалит rsync
  [[ -s "$f" ]] || continue                  # пустая «Без названия.md» — тоже
  [[ -n "$src_hashes" ]] || src_hashes=$(find "$SRC" -path "$SRC/.git" -prune -o -type f -print0 \
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
/usr/bin/rsync -rlt --delete --exclude .obsidian --exclude .git --exclude "/$BOARD" "$SRC/" "$DST/"
# только новые и обновлённые файлы (openrsync всё равно касается времени каждого файла — Obsidian это
# не замечает, проверено 14.10: событие modify приходит только на изменённый файл)
find "$DST" \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" \) -prune -o -type f -perm -u+w -exec chmod a-w {} +
find "$DST" -mindepth 1 \( -path "$DST/.obsidian" -o -path "$DST/$BOARD" \) -prune -o -type d -perm -u+w -print0 | xargs -0 chmod a-w 2>/dev/null
exit 0
