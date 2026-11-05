#!/bin/sh
# Задача расписания: пересобрать «Кто есть кто.canvas» (metis-0825). Сама пересборка — pantheon who-canvas;
# скрипт плагина, потому что parse_command (lib/pantheon.py) пускает в расписание только его, а не новую команду pantheon.
exec "$(dirname "$0")/../bin/pantheon" who-canvas "$@"
