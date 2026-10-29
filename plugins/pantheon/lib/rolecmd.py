"""Пантеон: pantheon role propose|apply|status|cancel — заявка на личную роль (metis-0262). Сборка ролей и
установка по галочке остаются в pantheon.py: они в сборке окон (ядро guard, metis-0404).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import sys

__all__ = [
    "role_propose", "role_cancel", "role_cmd",
]


def role_propose(name, direction):
    """Заявка: ворота без галочки, карточка с вопросом и статус proposed. Повтор с тем же черновиком — та же карточка;
    с правленым — новая, прежняя уходит в «Отменено». → (код, текст)."""
    with P.lock("roles"):
        data, sha, errs = P.role_static_gate(name)
        if errs:
            return 1, "; ".join(errs)
        last = P.role_last(name)
        if last and last["status"] == "proposed" and last.get("sha") == sha:
            return 0, f"заявка на роль {name} [{sha}] уже есть: карточка {last.get('card')}"
        q = P.role_question(name, sha)
        tid, _ = P.tasks_mod().task_new(
            P.PANTHEON, P.now(), direction, f"Применить личную роль {name}", actor="pantheon role", status="waiting",
            waiting_on="human", question=q,
            why=f"Черновик роли готов: roles/proposed/{name}.tmpl, {len(data)} байт. Галочка «Да» ставит его в ваш "
                f"личный слой ~/.claude/agents; правка черновика после галочки её отменяет.",
            options=[f"Да — поставить роль {name} в личный слой", "Нет — отклонить заявку"],
            recommend="Да — если черновик прочитан и роль нужна", if_no_answer="Роль не ставится, заявка ждёт.",
            text=f"Черновик: `~/ai/pantheon/roles/proposed/{name}.tmpl`, хеш {sha}.\n"
                 f"Поставить из терминала: `pantheon role apply {name}` — тоже только по галочке «Да».")
        if last and last["status"] == "proposed":
            P._role_card_close(last.get("card"), "dropped", f"Заменена заявкой {tid}: черновик правлен")
        P.role_status_add(name, "proposed", sha=sha, card=tid, direction=direction)
        return 0, f"заявка на роль {name} [{sha}]: карточка {tid} «{q}»"


def role_cancel(name):
    with P.lock("roles"):
        last = P.role_last(name)
        if not last or last["status"] != "proposed":
            return 1, f"у роли {name} нет открытой заявки (статус: {last['status'] if last else 'нет'})"
        P.role_status_add(name, "cancelled", sha=last.get("sha"), card=last.get("card"))
        P._role_card_close(last.get("card"), "dropped", f"Заявка на роль {name} отозвана")
        return 0, f"заявка на роль {name} отозвана"


def role_cmd(rest):
    usage = "pantheon role propose <имя> --direction D | apply <имя> | status [<имя>] | cancel <имя>"
    sub, args = (rest[0], rest[1:]) if rest else ("", [])
    if sub == "status" and len(args) <= 1:
        allst = P.role_status_all()
        names = args or sorted(allst)
        if not names:
            print("заявок на роли нет")
        for n in names:
            last = (allst.get(n) or [None])[-1]
            print(f"{n}: {last['status']} [{last.get('sha') or ''}] {str(last.get('time') or '')[:16].replace('T', ' ')}"
                  + (f" · карточка {last['card']}" if last.get("card") else "") if last else f"{n}: заявки нет")
        return 0
    ok = (sub == "propose" and len(args) == 3 and args[1] == "--direction") \
        or (sub in ("apply", "cancel") and len(args) == 1)
    if not ok or args[0].startswith("-"):
        print(usage, file=sys.stderr)
        return 2
    name = args[0]
    try:
        code, text = (role_propose(name, args[2]) if sub == "propose" else P.role_apply(name) if sub == "apply"
                      else role_cancel(name))
    except (OSError, ValueError) as e:
        code, text = 1, str(e)
    if code:
        print(f"role {sub}: отказ — {text}", file=sys.stderr)
    else:
        print(text)
    return code
