#!/bin/sh
# Обработчик слияния для файлов под git-crypt: git видит их двоичными и при правках с двух Mac оставил бы
# только свою версию. Здесь три версии (%O база, %A наша, %B их) расшифровываются, сливаются как текст
# (git merge-file) и шифруются обратно в %A. Разные строки сливаются сами, одна и та же — маркеры конфликта.
# Подключение в репозитории (его делает установщик на каждом Mac, в .git/config, с репозиторием не едет):
#   git config merge.gitcrypt-text.name "git-crypt text merge"
#   git config merge.gitcrypt-text.driver "<путь>/git-crypt-merge.sh %O %A %B"
#   в .gitattributes: <шаблон> filter=git-crypt diff=git-crypt merge=gitcrypt-text
# git-crypt — полным путём через /opt/homebrew/bin: Obsidian, запущенный из Dock, видит короткий PATH.
# Проверено 13.10 на тестовых репозиториях (git-crypt 0.8.0).
GC="${GIT_CRYPT:-/opt/homebrew/bin/git-crypt}"
d=$(mktemp -d)
"$GC" smudge < "$1" > "$d/base" && "$GC" smudge < "$2" > "$d/ours" && "$GC" smudge < "$3" > "$d/theirs" || { rm -rf "$d"; exit 2; }
git merge-file -L ours -L base -L theirs "$d/ours" "$d/base" "$d/theirs"; rc=$?
"$GC" clean < "$d/ours" > "$2" || { rm -rf "$d"; exit 2; }
rm -rf "$d"
exit $rc
