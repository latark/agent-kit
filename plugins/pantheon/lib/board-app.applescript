-- Доска Пантеона (собирает `pantheon install` в ~/Applications/Доска.app).
-- Запуск без уведомления в очереди — открыть в Obsidian карточку из последнего уведомления (если ему меньше
-- 15 минут) или доску. Запуск тиком с уведомлением в очереди — показать его от имени «Доски»: тогда кнопка
-- «Показать» в уведомлении запускает эту же программу, и она открывает нужную карточку.
on run
	set stateDir to (POSIX path of (path to home folder)) & ".local/state/pantheon/notify/"
	set msg to ""
	try
		set msg to do shell script "f=" & quoted form of (stateDir & "pending.txt") & "; if [ -f \"$f\" ]; then cat \"$f\"; rm -f \"$f\"; fi"
	end try
	if msg is not "" then
		set AppleScript's text item delimiters to (ASCII character 10)
		set parts to text items of msg
		set AppleScript's text item delimiters to ""
		if (count of parts) > 1 then display notification (item 2 of parts) with title (item 1 of parts)
		delay 1
		return
	end if
	set target to ""
	try
		set target to do shell script "f=" & quoted form of (stateDir & "target.txt") & "; if [ -f \"$f\" ] && [ $(( $(date +%s) - $(stat -f %m \"$f\") )) -lt 900 ]; then cat \"$f\"; rm -f \"$f\"; fi"
	end try
	if target is "" then set target to "BOARD_URL"
	open location target
end run
