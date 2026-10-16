"""Расход токенов Claude Code по локальным транскриптам: только поля usage, без текста переписки.
Стоимость — в эквиваленте цен API (USD за 1M токенов, platform.claude.com/docs/en/about-claude/pricing, 12.10.2026)."""
import glob, json, math, os, sys, time
from collections import defaultdict

# in, cache write 5m, cache write 1h, cache read, out
PRICE = {
    'opus-5-5': (4, 5, 8, 0.20, 20),
    'sonnet-5-5': (2, 2.5, 4, 0.10, 10),
    'haiku-5-5': (0.10, 0.125, 0.20, 0.01, 0.50),
    'haiku-5-5-long': (0.50, 0.625, 1, 0.05, 2.50),
    'fable-5-1': (10, 12.5, 20, 0.25, 50),
    'opus-5': (5, 6.25, 10, 0.50, 25),
    'sonnet-5': (2, 2.5, 4, 0.20, 10),
}

def family(model):
    m = (model or '').replace('claude-', '')
    for k in ('opus-5-5', 'sonnet-5-5', 'haiku-5-5', 'fable-5-1', 'opus-5', 'sonnet-5'):
        if m.startswith(k):
            return k
    return None

def cost(fam, u):
    w5 = (u.get('cache_creation') or {}).get('ephemeral_5m_input_tokens', 0) or 0
    w1 = (u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens', 0) or 0
    if not (w5 or w1):
        w5 = u.get('cache_creation_input_tokens', 0) or 0
    inp, rd, out = u.get('input_tokens', 0) or 0, u.get('cache_read_input_tokens', 0) or 0, u.get('output_tokens', 0) or 0
    if fam == 'haiku-5-5' and inp + w5 + w1 + rd > 100_000:
        fam = 'haiku-5-5-long'
    p = PRICE[fam]
    parts = {'input': inp * p[0], 'write': w5 * p[1] + w1 * p[2], 'read': rd * p[3], 'output': out * p[4]}
    return {k: v / 1e6 for k, v in parts.items()}, {'input': inp, 'write': w5 + w1, 'read': rd, 'output': out,
            'thinking': ((u.get('output_tokens_details') or {}).get('thinking_tokens', 0) or 0)}

def session_of(f):
    """Id сессии: основной транскрипт — его имя; субагент — папка перед /subagents/."""
    if '/subagents/' in f:
        return f.split('/subagents/')[0].rsplit('/', 1)[-1]
    return os.path.basename(f)[:-len('.jsonl')]

def main_role(f):
    """Роль основной сессии — служебная запись agent-setting; нет записи — None. Текст переписки не читается."""
    role = None
    for line in open(f, errors='replace'):
        if '"agent-setting"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get('type') == 'agent-setting' and d.get('agentSetting'):
            role = d['agentSetting']
    return role

def sub_role(f):
    """Роль субагента — agentType из agent-<id>.meta.json рядом с транскриптом; нет файла — None."""
    try:
        with open(f[:-len('.jsonl')] + '.meta.json') as fh:
            return json.load(fh).get('agentType') or None
    except (OSError, ValueError, AttributeError):
        return None

def main():
    DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    since = time.time() - DAYS * 86400
    files = [f for f in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'), recursive=True)
             if os.path.getmtime(f) >= since]

    agg = defaultdict(lambda: defaultdict(float))       # (kind, model, effort) -> sums
    sess_ctx = defaultdict(list)                         # main session -> context sizes per request
    spawn_first = []                                     # first-request context of each subagent
    by_role = defaultdict(lambda: defaultdict(float))   # роль -> requests, $
    role_sess = defaultdict(set)                         # роль -> id сессий
    sess_cost = defaultdict(float)                       # id сессии -> $ (основная + её субагенты)
    sess_role = {}                                       # id сессии -> роль основной
    seen = set()
    unknown = defaultdict(int)
    for f in files:
        kind = 'subagent' if '/subagents/' in f else 'main'
        first = True
        sid = session_of(f)
        if kind == 'main':
            role = main_role(f) or 'без роли'
            sess_role[sid] = role
        else:
            role = sub_role(f) or 'субагент без типа'
        for line in open(f, errors='replace'):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get('message') or {}
            u = m.get('usage')
            if d.get('type') != 'assistant' or not u:
                continue
            ts = d.get('timestamp', '')
            try:
                if time.mktime(time.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S')) < since:
                    continue
            except ValueError:
                pass
            key = d.get('requestId') or m.get('id')
            if key in seen:
                continue
            seen.add(key)
            fam = family(m.get('model'))
            if not fam:
                unknown[m.get('model')] += 1
                continue
            k = 'subagent' if (kind == 'subagent' or d.get('isSidechain')) else 'main'
            eff = d.get('effort') or '-'
            c, t = cost(fam, u)
            tc = sum(c.values())
            by_role[role]['requests'] += 1
            by_role[role]['$'] += tc
            role_sess[role].add(sid)
            sess_cost[sid] += tc
            a = agg[(k, fam, eff)]
            a['requests'] += 1
            for kk, v in c.items():
                a['$' + kk] += v
            for kk, v in t.items():
                a[kk] += v
            ctx = t['input'] + t['write'] + t['read']
            if k == 'main':
                sess_ctx[f].append(ctx)
            elif first:
                spawn_first.append(ctx)
            first = False

    tot = sum(sum(v for kk, v in a.items() if kk.startswith('$')) for a in agg.values())
    print(f'Период: {DAYS} дн., файлов: {len(files)}, запросов: {len(seen)}, неизвестные модели: {dict(unknown)}')
    print(f'Итого в ценах API: ${tot:,.0f}\n')
    print(f"{'кто':9} {'модель':11} {'effort':7} {'запр.':>6} {'$':>8} {'доля':>5} | {'чтение кэша':>11} {'запись':>7} {'вывод':>7} {'из них мысли':>12} | {'$чтение':>7} {'$запись':>7} {'$вывод':>7}")
    for (k, fam, eff), a in sorted(agg.items(), key=lambda x: -sum(v for kk, v in x[1].items() if kk.startswith('$'))):
        s = sum(v for kk, v in a.items() if kk.startswith('$'))
        print(f"{k:9} {fam:11} {eff:7} {a['requests']:6.0f} {s:8.0f} {s / tot:5.0%} | {a['read'] / 1e6:10.1f}M {a['write'] / 1e6:6.1f}M {a['output'] / 1e6:6.2f}M {a['thinking'] / 1e6:11.2f}M | {a['$read']:7.0f} {a['$write']:7.0f} {a['$output']:7.0f}")

    print('\nПо ролям (основная сессия — по agent-setting, субагент — по agentType из meta):')
    print(f"{'роль':26} {'запр.':>6} {'$':>8} {'доля':>5} {'сессий':>7}")
    for r, a in sorted(by_role.items(), key=lambda x: -x[1]['$']):
        print(f"{r[:26]:26} {a['requests']:6.0f} {a['$']:8.0f} {a['$'] / tot if tot else 0:5.0%} {len(role_sess[r]):7}")

    if sess_cost:
        ranked = sorted(sess_cost.items(), key=lambda x: -x[1])
        n = max(1, math.ceil(len(ranked) * 0.10))
        top = ranked[:n]
        share = sum(v for _, v in top) / tot if tot else 0
        print(f'\nТоп-10 % сессий (сессия = основной транскрипт вместе с его субагентами): {n} из {len(ranked)}, '
              f'на них ${sum(v for _, v in top):,.0f} = {share:.0%} всех $')
        for sid, v in top[:5]:
            print(f"  {sid[:8]}  {sess_role.get(sid, 'без роли'):26} ${v:,.0f}")

    ctxs = sorted(x for v in sess_ctx.values() for x in v)
    if ctxs:
        q = lambda p: ctxs[min(len(ctxs) - 1, int(p * len(ctxs)))]
        print(f'\nКонтекст одного запроса основной сессии: медиана {q(.5)/1e3:.0f}K, 75% {q(.75)/1e3:.0f}K, 90% {q(.9)/1e3:.0f}K, макс {ctxs[-1]/1e3:.0f}K')
        big = sum(1 for x in ctxs if x >= 150_000) / len(ctxs)
        print(f'Запросов основной сессии с контекстом от 150K: {big:.0%}')
    if spawn_first:
        spawn_first.sort()
        print(f'Субагентов: {len(spawn_first)}, стартовый контекст: медиана {spawn_first[len(spawn_first)//2]/1e3:.0f}K')


if __name__ == '__main__':
    main()
