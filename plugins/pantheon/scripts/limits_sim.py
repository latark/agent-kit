"""Шаг 2: модель новой системы на reqs.json — три сценария, недели 5x/20x, пятичасовое окно.
Лимиты в ценах API (замер 13.10): 5x окно ~$170, неделя ~$1 300-1 450; 20x неделя ~$2 300 ($23 на 1%)."""
import json, datetime as dt
from collections import defaultdict
P = {'opus-5-5': (4, 5, 8, 0.20, 20), 'sonnet-5-5': (2, 2.5, 4, 0.10, 10), 'haiku-5-5': (0.10, 0.125, 0.20, 0.01, 0.50),
     'fable-5-1': (10, 12.5, 20, 0.25, 50), 'opus-5': (5, 6.25, 10, 0.50, 25), 'sonnet-5': (2, 2.5, 4, 0.20, 10)}
DO = {'Read', 'Edit', 'Write', 'MultiEdit', 'Bash', 'Grep', 'Glob', 'NotebookEdit', 'LSP', 'BashOutput'}
WEB = {'WebFetch', 'WebSearch'}
R = json.load(open('reqs.json'))
M = lambda d, h, mi=0: dt.datetime(2026, 10, d, h, mi).timestamp()
def cost(r, rd=None, extra_w=0, fam=None):
    p = P[fam or r['fam']]; rd = r['rd'] if rd is None else rd
    return (r['inp'] * p[0] + r['w5'] * p[1] + (r['w1'] + extra_w) * p[2] + rd * p[3] + r['out'] * p[4]) / 1e6
SC = {  # LIMIT: когда чистим; BASE: контекст после очистки; a: доля «делания» -> Sonnet; b: -> Haiku;
        # k: лишние шаги Sonnet; sub: контекст работника относительно основного; xh: xhigh->high; ov: накладные иерархии
    'оптимистичный': dict(LIMIT=150e3, BASE=35e3, a=.75, b=.15, k=1.1, sub=.6, xh=.85, ov=.15),
    'реалистичный':  dict(LIMIT=200e3, BASE=50e3, a=.60, b=.10, k=1.25, sub=.75, xh=.9, ov=.30),
    'пессимистичный': dict(LIMIT=250e3, BASE=60e3, a=.40, b=.05, k=1.4, sub=.9, xh=.95, ov=.50),
}
now = R[-1]['ts']; days = (now - M(3, 0)) / 86400
base = sum(cost(r) for r in R)
by_file = defaultdict(list)
for r in R: by_file[r['f']].append(r)
hour_new = {}
for name, s in SC.items():
    new = 0.0; clears = 0; parts = defaultdict(float); hourly = defaultdict(float)
    for f, rr in by_file.items():
        main = not rr[0]['sub'] and rr[0]['ep'] == 'cli'
        off = 0.0
        for r in rr:
            if not main:
                c = cost(r); new += c; parts['конвейеры и субагенты как есть'] += c; hourly[int(r['ts']//3600)] += c; continue
            ctx = r['inp'] + r['w5'] + r['w1'] + r['rd']
            if ctx <= off: off = 0.0
            extra = 0
            if ctx - off > s['LIMIT']:
                off = ctx - s['BASE']; clears += 1; extra = s['BASE']
            rd = max(0.0, r['rd'] - off)
            t = set(r['tools'])
            opus = cost(r, rd, extra)
            if r['eff'] == 'xhigh': opus *= s['xh']
            if t & DO:
                rd_sub = rd * s['sub']
                son = cost(r, rd_sub, extra, 'sonnet-5-5') * s['k']
                hai = cost(r, rd_sub, extra, 'haiku-5-5') * s['k']
                c = s['a'] * son + s['b'] * hai + (1 - s['a'] - s['b']) * opus
                parts['работа с кодом: Sonnet/Haiku + Opus-лиды'] += c
            elif t & WEB:
                c = cost(r, rd * s['sub'], extra, 'sonnet-5-5') * s['k']; parts['исследователь Sonnet'] += c
            else:
                c = opus; parts['штаб, координаторы: Opus high'] += c
            c *= 1 + s['ov']
            new += c; hourly[int(r['ts']//3600)] += c
    hour_new[name] = hourly
    print(f"\n{name}: ${new:,.0f} вместо ${base:,.0f} -> x{new/base:.2f}; очисток контекста {clears}")
    for k, v in sorted(parts.items(), key=lambda x: -x[1]): print(f'   {k:45} ${v:7,.0f}')
    for lbl, rate in [('средний темп с 03.10', base / days * 7), ('темп на 5x (07-11.10)', 2973), ('темп на 20x (11-13.10)', 3612)]:
        print(f'   {lbl:28} ${rate:6,.0f}/нед -> ${rate*new/base:6,.0f}/нед; 5x (~$1 400): {1400/(rate*new/base)*7:4.1f} дн.; 20x (~$2 300): {2300/(rate*new/base)*7:4.1f} дн.')
# hourly burn now vs new (active hours only), and worst rolling 5h
hb = defaultdict(float)
for r in R: hb[int(r['ts']//3600)] += cost(r)
def roll5(h):
    ks = sorted(h); best = 0
    for k in ks: best = max(best, sum(h.get(k+i, 0) for i in range(5)))
    return best
vals = sorted(v for v in hb.values() if v > 1)
print(f"\nсейчас: $ в активный час медиана {vals[len(vals)//2]:.0f}, p90 {vals[int(len(vals)*.9)]:.0f}; худшие 5 ч подряд ${roll5(hb):.0f}")
for n, h in hour_new.items():
    v = sorted(x for x in h.values() if x > 1)
    print(f"{n}: активный час медиана ${v[len(v)//2]:.0f}, p90 ${v[int(len(v)*.9)]:.0f}; худшие 5 ч подряд ${roll5(h):.0f}")
