"""Шаг 1 расчёта «хватит ли Max 5x»: запросы с 03.10 -> reqs.json (только счётчики и имена инструментов).
Запуск: cd <папка> && python3 -I limits_collect.py && python3 -I limits_sim.py"""
import glob, json, os, datetime as dt
from collections import defaultdict
P = {'opus-5-5': (4, 5, 8, 0.20, 20), 'sonnet-5-5': (2, 2.5, 4, 0.10, 10), 'haiku-5-5': (0.10, 0.125, 0.20, 0.01, 0.50),
     'fable-5-1': (10, 12.5, 20, 0.25, 50), 'opus-5': (5, 6.25, 10, 0.50, 25), 'sonnet-5': (2, 2.5, 4, 0.20, 10)}
def fam(m):
    m = (m or '').replace('claude-', '')
    for k in P:
        if m.startswith(k): return k
T0 = dt.datetime(2026, 10, 3).timestamp()
DO = {'Read', 'Edit', 'Write', 'MultiEdit', 'Bash', 'Grep', 'Glob', 'NotebookEdit', 'LSP', 'BashOutput'}
WEB = {'WebFetch', 'WebSearch'}
R = []; seen = set(); idx = {}
for f in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'), recursive=True):
    if os.path.getmtime(f) < T0: continue
    sub = '/subagents/' in f
    proj = f.split('/.claude/projects/')[1].split('/')[0]
    for line in open(f, errors='replace'):
        if '"usage"' not in line: continue
        try: d = json.loads(line)
        except ValueError: continue
        m = d.get('message') or {}; u = m.get('usage')
        if d.get('type') != 'assistant' or not u: continue
        k = d.get('requestId') or m.get('id')
        tl = [c.get('name') for c in (m.get('content') or []) if isinstance(c, dict) and c.get('type') == 'tool_use']
        if k in seen:
            if tl and k in idx: R[idx[k]]['tools'] += tl
            continue
        seen.add(k)
        fm = fam(m.get('model'))
        if not fm: continue
        ts = dt.datetime.fromisoformat(d['timestamp'].replace('Z', '+00:00')).timestamp()
        if ts < T0: continue
        cc = u.get('cache_creation') or {}
        w5, w1 = cc.get('ephemeral_5m_input_tokens', 0) or 0, cc.get('ephemeral_1h_input_tokens', 0) or 0
        if not (w5 or w1): w5 = u.get('cache_creation_input_tokens', 0) or 0
        inp, rd, out = u.get('input_tokens', 0) or 0, u.get('cache_read_input_tokens', 0) or 0, u.get('output_tokens', 0) or 0
        tools = tl
        idx[k] = len(R)
        R.append(dict(f=f, sub=sub or bool(d.get('isSidechain')), fam=fm, eff=d.get('effort') or '-', ts=ts, inp=inp, w5=w5, w1=w1, rd=rd, out=out,
                      tools=tools, proj=proj, ep=d.get('entrypoint') or '-'))
R.sort(key=lambda r: r['ts'])
json.dump(R, open('reqs.json', 'w'))
print(len(R), 'запросов с 03.10')
