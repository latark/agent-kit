# Хуки MorphStream — образцы для test_window_threats

Копии скриптов `~/projects/MorphStream/{app,gpu-worker}/.claude/hooks/*.sh` на 06.11.2026, без правок (protect-db.sh
не скопирован: читает только stdin). Тест класса 2 (metis-0933) кладёт их во временный репозиторий и запускает хуки
пакета proteus-morph из `packs/proteus-morph/hooks/hooks.json`. По ним видно, что прежний check-reexport.sh пишет по
ссылке, подложенной окном, а замена `packs/_bin/repo_hooks.py` — нет.
