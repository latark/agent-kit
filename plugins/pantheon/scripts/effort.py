"""Запросы, вызовы инструментов и стоимость на одно сообщение пользователя по уровням effort (основные сессии Opus 5.5).
Только счётчики из транскриптов, без текста."""
import glob, json, os, sys, time
from collections import defaultdict

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
since = time.time() - DAYS * 86400
P = (4, 5, 8, 0.20, 20)  # Opus 5.5: in, write 5m, write 1h, read, out

def is_human(d):
    if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain'):
        return False
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return not c.startswith('<') and bool(c.strip())
    if isinstance(c, list):
        return any(b.get('type') == 'text' and not str(b.get('text', '')).startswith('<') for b in c if isinstance(b, dict)) \
            and not any(b.get('type') == 'tool_result' for b in c if isinstance(b, dict))
    return False

turns = defaultdict(lambda: defaultdict(float))   # effort -> sums
for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
    if os.path.getmtime(f) < since:
        continue
    cur = None          # current turn accumulator
    seen = set()
    def close():
        if cur and cur['req'] and cur['effort']:
            t = turns[cur['effort']]
            t['turns'] += 1
            for k in ('req', 'tools', 'cost', 'ctx', 'think'):
                t[k] += cur[k]
    for line in open(f, errors='replace'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if is_human(d):
            close()
            cur = {'req': 0, 'tools': 0, 'cost': 0.0, 'ctx': 0, 'think': 0, 'effort': None}
            continue
        m = d.get('message') or {}
        u = m.get('usage')
        if cur is None or d.get('type') != 'assistant' or d.get('isSidechain'):
            continue
        cur['tools'] += sum(1 for b in (m.get('content') or []) if isinstance(b, dict) and b.get('type') == 'tool_use')
        key = d.get('requestId') or m.get('id')
        if not u or key in seen or not str(m.get('model', '')).startswith('claude-opus-5-5'):
            continue
        seen.add(key)
        cc = u.get('cache_creation') or {}
        w5, w1 = cc.get('ephemeral_5m_input_tokens', 0) or 0, cc.get('ephemeral_1h_input_tokens', 0) or 0
        inp, rd, out = u.get('input_tokens', 0) or 0, u.get('cache_read_input_tokens', 0) or 0, u.get('output_tokens', 0) or 0
        cur['req'] += 1
        cur['cost'] += (inp * P[0] + w5 * P[1] + w1 * P[2] + rd * P[3] + out * P[4]) / 1e6
        cur['ctx'] += inp + w5 + w1 + rd
        cur['think'] += ((u.get('output_tokens_details') or {}).get('thinking_tokens', 0) or 0)
        cur['effort'] = cur['effort'] or d.get('effort')
    close()

print(f"{'effort':7} {'сообщений':>9} {'запросов/сообщ.':>15} {'инструментов/сообщ.':>19} {'контекст/запрос':>15} {'мысли/сообщ.':>12} {'$/сообщ.':>8}")
for e in ('low', 'medium', 'high', 'xhigh', 'max'):
    t = turns.get(e)
    if not t or not t['turns']:
        continue
    n = t['turns']
    print(f"{e:7} {n:9.0f} {t['req']/n:15.1f} {t['tools']/n:19.1f} {t['ctx']/t['req']/1e3:14.0f}K {t['think']/n/1e3:11.1f}K {t['cost']/n:8.2f}")
