-- Доска Пантеона (собирает `pantheon install` в ~/Applications/Доска.app): Spotlight «Доска» и значок в Dock
-- открывают доску в Obsidian. Уведомления Пантеона шлёт terminal-notifier 3 — щелчок открывает нужную карточку.
on run
	open location "BOARD_URL"
end run
