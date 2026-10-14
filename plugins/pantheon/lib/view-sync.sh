#!/bin/zsh
# Копия ~/pantheon только для чтения для Obsidian. Задача планировщика Пантеона `pantheon view` (каждый тик —
# страховка); сразу после записи агента в ~/pantheon её же запускает хук PostToolUse плагина pantheon.
# Проверено 14.10 на временных папках и отдельном экземпляре Obsidian 1.14.4.
# Заметки и вложения, созданные в копии по ошибке, не удаляются, а переносятся во входящие ~/knowledge.
SRC="${1:-$HOME/pantheon}"; DST="${2:-$HOME/pantheon-view}"; INBOX="${3:-$HOME/knowledge/inbox}"
mkdir -p "$DST"
stamp=$(date +%Y%m%d-%H%M%S)
find "$DST" -path "$DST/.obsidian" -prune -o -type f -print | while IFS= read -r f; do
  rel="${f#$DST/}"
  [[ -e "$SRC/$rel" ]] && continue          # файл из оригинала — его обновит rsync
  [[ "${rel:t}" == .* ]] && continue         # .DS_Store и прочие служебные — пусть удалит rsync
  [[ -s "$f" ]] || continue                  # пустая «Без названия.md» — тоже
  mkdir -p "$INBOX"
  mv "$f" "$INBOX/pantheon-view-$stamp-${rel//\//__}"
done
# -rlt без -p: права копии не тянем из оригинала, их снимает строка ниже
/usr/bin/rsync -rlt --delete --exclude .obsidian --exclude .git "$SRC/" "$DST/"
# только новые и обновлённые файлы (openrsync всё равно касается времени каждого файла — Obsidian это
# не замечает, проверено 14.10: событие modify приходит только на изменённый файл)
find "$DST" -path "$DST/.obsidian" -prune -o -type f -perm -u+w -exec chmod a-w {} +
