#!/usr/bin/env python3
"""Per Stratzy algo per day: advised P&L vs ck's realised Dhan P&L, gap split into
slippage / charges / copier top-up. Stdlib only.

Inputs (default research/vm_state/): dhan_trades.csv, copier_orders.csv, attribution.json,
stratzy-trades.jsonl (recorder, optional). Advice cache: data/advices/<id>/<date>.json.
Output: research/fills_overlay.json
"""
import csv, json, glob, os, re, sys, collections, calendar
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'research/vm_state')
OUT = os.path.join(ROOT, 'research/fills_overlay.json')
TAGS = ['COPIER', 'SPREAD', 'MARGIN_SOLO', 'NAKED']
MAX_DT_MIN = 30
ADVICE_END = '2026-10-23'

# ---------------- Dhan fills (logic from attr.py) ----------------
T = list(csv.DictReader(open(f'{IN}/dhan_trades.csv')))
C = list(csv.DictReader(open(f'{IN}/copier_orders.csv')))
ATTR = json.load(open(f'{IN}/attribution.json'))
cop = {r['dhan_order_id'] for r in C if r['dhan_order_id']}
n = len(T)
for i, r in enumerate(T):
    r['i'] = n - i; r['dt'] = datetime.fromisoformat(r['exchangeTime'])
    r['qty'] = int(float(r['qty'])); r['price'] = float(r['price']); r['strike'] = float(r['strike'])
T.sort(key=lambda r: (r['dt'], r['i']))
und = lambda r: r['customSymbol'].split()[0].upper()
for r in T:
    r['seg'] = 'CNC' if r['productType'] == 'CNC' else ('MCX' if und(r) in ('GOLDM', 'SILVERM') else 'OPT')
mg = [r for r in T if r['productType'] == 'MARGIN' and r['seg'] == 'OPT' and r['cp'] in ('CALL', 'PUT')]
by = collections.defaultdict(list)
for r in mg: by[(r['expiry'], r['cp'])].append(r)
for r in T:
    if r['seg'] == 'CNC': r['tag'] = 'CNC'
    elif r['orderId'] in cop: r['tag'] = 'COPIER'
    elif r['productType'] == 'MARGIN':
        sp = any(o['side'] != r['side'] and o['strike'] != r['strike'] and abs((o['dt'] - r['dt']).total_seconds()) <= 60
                 for o in by.get((r['expiry'], r['cp']), []))
        r['tag'] = 'SPREAD' if sp and r['seg'] == 'OPT' else 'MARGIN_SOLO'
    else: r['tag'] = 'NAKED'
opt = [r for r in T if r['seg'] == 'OPT']
ordtr = collections.defaultdict(list)
for r in opt: ordtr[r['orderId']].append(r)
for oid, l in ordtr.items():
    for r in l:
        p = r['price'] * r['qty']; b = 20 / len(l)
        ex = .000353 * p; se = 1e-6 * p
        stt = .001 * p if r['side'] == 'SELL' else 0
        st = .00003 * p if r['side'] == 'BUY' else 0
        r['chg'] = b + stt + ex + se + st + .18 * (b + ex + se)
est = sum(r['chg'] for r in opt)
RATIO = ATTR['calibration']['footer_total'] / est
for r in opt: r['chgs'] = r['chg'] * RATIO; r['alloc'] = 0

CPM = {'CALL': 'CE', 'PUT': 'PE'}
def ckey(r): return ('NIFTY' if und(r) == 'NIFTY' else und(r), r['expiry'], int(r['strike']), CPM[r['cp']])

# FIFO round trips; each piece carries open/close fill refs + allocated charges
rts = []; pos = collections.defaultdict(list)
def piece(f, m): return f['chgs'] * m / f['qty']
for r in T:
    if r['seg'] != 'OPT': continue
    q = r['qty']; L = pos[(r['customSymbol'], r['expiry'])]
    while q > 0 and L and L[0][0] != r['side']:
        o = L[0]; m = min(q, o[1]); of = o[3]
        sp, bp = (r['price'], o[2]) if r['side'] == 'SELL' else (o[2], r['price'])
        rts.append(dict(key=ckey(r), qty=m, pnl=(sp - bp) * m, otag=of['tag'], ofill=of, cfill=r,
                        chg=piece(of, m) + piece(r, m), open_px=o[2], close_px=r['price'], oside=o[0], settled=False))
        of['alloc'] += m; r['alloc'] += m
        o[1] -= m; q -= m
        if o[1] == 0: L.pop(0)
    if q > 0: L.append([r['side'], q, r['price'], r])
for (sym, exp), L in pos.items():
    if exp <= '2026-10-30':
        for o in L:
            pr = o[3]; sp, bp = (0, o[2]) if o[0] == 'BUY' else (o[2], 0)
            rts.append(dict(key=ckey(pr), qty=o[1], pnl=(sp - bp) * o[1], otag=pr['tag'], ofill=pr, cfill=None,
                            chg=piece(pr, o[1]), open_px=o[2], close_px=0.0, oside=o[0], settled=True))
            pr['alloc'] += o[1]
        L.clear()
# charges on still-open (Dec) quantity: no round trip
leftover_chg = collections.defaultdict(float)
for r in opt:
    rem = r['qty'] - r['alloc']
    if rem: leftover_chg[r['tag']] += piece(r, rem)

# ---------------- Stratzy advices ----------------
names = {a['_id']: a['name'] for a in json.load(open(f'{ROOT}/data/algo_list.json'))}
MON = {m: i for i, m in enumerate(['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'], 1)}
LET = {'O': 10, 'N': 11, 'D': 12}
def parse_sym(s):
    """-> (und, expiry_date|None, month_window|None, strike, cp)"""
    m = re.fullmatch(r'(NIFTY)(\d{2})([1-9OND])(\d{2})(\d{5})(CE|PE)', s)
    if m:
        mo = LET.get(m[3]) or int(m[3])
        return m[1], f'20{m[2]}-{mo:02d}-{m[4]}', None, int(m[5]), m[6]
    m = re.fullmatch(r'(NIFTY)(\d{2})([A-Z]{3})(\d{5})(CE|PE)', s)
    if m:
        y, mo = 2000 + int(m[2]), MON[m[3]]
        return m[1], None, (y, mo), int(m[4]), m[5]
    return None
def ist(z): return datetime.fromisoformat(z.replace('Z', '+00:00')).replace(tzinfo=None) + timedelta(hours=5, minutes=30)

dhan_exp = sorted({r['expiry'] for r in opt})
def monthly_expiry(y, mo):
    dim = calendar.monthrange(y, mo)[1]
    c = [e for e in dhan_exp if e.startswith(f'{y}-{mo:02d}') and int(e[8:]) > dim - 7]
    return c[-1] if c else None

advs = {}; skipped = collections.Counter()
for f in glob.glob(f'{ROOT}/data/advices/*/*.json'):
    p = f.split('/')
    if p[-1][:10] < '2026-06-25': continue
    for a in json.load(open(f)):
        if a.get('backtestTrade'): skipped['backtest'] += 1; continue
        if a['_id'] in advs: continue
        a['_adv'] = p[-2]; advs[a['_id']] = a
legs_by = collections.defaultdict(list)   # (key, side, date) -> [leg]
adv_rows = {}
for aid, a in advs.items():
    legs = []
    for t in a['trades']:
        ps = parse_sym(t['symbol'])
        if not ps: skipped['non_nifty_leg'] += 1; continue
        u, ed, mw, k, cp = ps
        if ed is None: ed = monthly_expiry(*mw)
        ex = t.get('avgExitPrice', t.get('finalExitPrice', t.get('exitPrice')))
        if ex is None: ex = t.get('exitPrice')
        sgn = 1 if t['transactionType'] == 'BUY' else -1
        unit = sgn * (ex - t['entryPrice'])
        sq = a['maxLots'] * t['multiplier'] * t['quantity']
        leg = dict(aid=aid, key=(u, ed, k, cp), side=t['transactionType'], entry=t['entryPrice'], exit=ex, unit=unit,
                   mult=t['multiplier'], sqty=sq, t0=ist(a['createdAt']), ck_qty=0, ck_gross=0.0, ck_chg=0.0, matched=False)
        legs.append(leg)
        legs_by[(leg['key'], leg['side'], leg['t0'].date().isoformat())].append(leg)
    sells = [l for l in legs if l['side'] == 'SELL']; buys = [l for l in legs if l['side'] == 'BUY']
    sub = a.get('subCategory') or ''
    if len(legs) == 2 and sells and buys: st = 'credit_spread'
    elif len(legs) == 2 and len(sells) == 2: st = 'straddle' if legs[0]['key'][2] == legs[1]['key'][2] else 'strangle'
    elif len(legs) == 1 and buys: st = 'naked_buy'
    elif len(legs) == 1: st = 'naked_sell'
    else: st = 'other'
    adv_rows[aid] = dict(a=a, legs=legs, structure=st, date=ist(a['createdAt']).date().isoformat())

# ---------------- join: each round trip -> advice leg via its OPEN fill ----------------
match_q = collections.Counter(); unmatched = {t: dict(trips=0, gross=0.0, charges=0.0, reasons=collections.Counter()) for t in TAGS}
for t in TAGS: unmatched[t]['charges'] += leftover_chg.get(t, 0.0)
for x in rts:
    of = x['ofill']; d = of['dt']; side = of['side']
    cands = legs_by.get((x['key'], side, d.date().isoformat()), [])
    best = None
    for l in cands:
        dtm = abs((of['dt'] - l['t0']).total_seconds()) / 60
        if dtm > MAX_DT_MIN: continue
        s = dtm * 0.2 + 20 * abs(of['price'] - l['entry']) / max(l['entry'], 1)
        if best is None or s < best[0]: best = (s, l, dtm)
    if best:
        l = best[1]; l['matched'] = True
        l['ck_qty'] += x['qty']; l['ck_gross'] += x['pnl']; l['ck_chg'] += x['chg']
        l.setdefault('ck_unit_slip', 0.0)
        l['ck_copier_gross'] = l.get('ck_copier_gross', 0.0) + (x['pnl'] if x['otag'] == 'COPIER' else 0.0)
        l['ck_copier_qty'] = l.get('ck_copier_qty', 0) + (x['qty'] if x['otag'] == 'COPIER' else 0)
        match_q['matched_trips'] += 1
    else:
        u = unmatched[x['otag']]; u['trips'] += 1; u['gross'] += x['pnl']; u['charges'] += x['chg']
        if d.date().isoformat() > ADVICE_END: u['reasons']['opened_after_advice_cache_end'] += 1
        elif not cands: u['reasons']['no_advice_leg_same_day_same_contract_side'] += 1
        else: u['reasons']['advice_leg_found_but_>30min_from_fill'] += 1

# ---------------- aggregate per algo / day ----------------
def r2(x): return round(x, 2)
byAlgo = {}; tot = collections.Counter()
for aid, ar in adv_rows.items():
    a = ar['a']; adv_id = a['_adv']
    g = byAlgo.setdefault(adv_id, dict(name=names.get(adv_id) or a['advisor']['name'], advices_in_cache=0,
        advised_pnl_all_advices=0.0, days=set(), advised_pnl=0.0, advised_pnl_1lot=0.0, ck_realised_gross=0.0, ck_copier_gross=0.0,
        ck_charges=0.0, ck_qty=0, stratzy_qty=0, slippage=0.0, topup_effect=0.0, missed_leg_effect=0.0, matched_trips=0,
        structures=collections.Counter(), byDay={}))
    g['advices_in_cache'] += 1
    g['advised_pnl_all_advices'] += a['pnl']
    if not any(l['matched'] for l in ar['legs']): continue
    ap = sum(l['sqty'] * l['unit'] for l in ar['legs'])
    if abs(ap - a['pnl']) > max(2, 0.001 * abs(a['pnl'])): tot['advice_pnl_mismatch'] += 1
    dd = g['byDay'].setdefault(ar['date'], dict(advised_pnl=0.0, advised_pnl_1lot=0.0, ck_realised_gross=0.0, ck_charges=0.0,
        slippage=0.0, topup_effect=0.0, missed_leg_effect=0.0, ck_qty=0, stratzy_qty=0, structures=[]))
    g['structures'][ar['structure']] += 1; dd['structures'].append(ar['structure'])
    g['days'].add(ar['date'])
    for l in ar['legs']:
        if l['matched']:
            slip = l['ck_gross'] - l['ck_qty'] * l['unit']
            top = (l['ck_qty'] - l['sqty']) * l['unit']
            miss = 0.0
        else:
            slip = top = 0.0; miss = -l['sqty'] * l['unit']
        adv = l['sqty'] * l['unit']
        for obj in (g, dd):
            obj['advised_pnl'] += adv; obj['advised_pnl_1lot'] += l['mult'] * l['unit']
            obj['ck_realised_gross'] += l['ck_gross']; obj['ck_charges'] += l['ck_chg']
            obj['slippage'] += slip; obj['topup_effect'] += top; obj['missed_leg_effect'] += miss
            if l['matched']: obj['ck_qty'] += l['ck_qty']; obj['stratzy_qty'] += l['sqty']
        g['ck_copier_gross'] += l.get('ck_copier_gross', 0.0)
        g['matched_trips'] += 0
for adv_id, g in byAlgo.items():
    g['matched_trips'] = 0
# matched trips per algo: recount from legs
for ar in adv_rows.values():
    pass
trips_per = collections.Counter()
# (recount cheaply: rts matched were counted globally; per-algo count via leg ck fills)
for aid, ar in adv_rows.items():
    for l in ar['legs']:
        if l['matched']: trips_per[ar['a']['_adv']] += 1   # matched advice legs
for k, g in byAlgo.items(): g['matched_legs'] = trips_per[k]; g.pop('matched_trips')
out_algo = {}
for k, g in byAlgo.items():
    if not g['days']: continue
    net = g['ck_realised_gross'] - g['ck_charges']
    row = dict(name=g['name'], days=len(g['days']), structures=dict(g['structures']), matched_legs=g['matched_legs'],
        advices_in_cache=g['advices_in_cache'], advised_pnl_all_advices=r2(g['advised_pnl_all_advices']),
        advised_pnl=r2(g['advised_pnl']), advised_pnl_1lot=r2(g['advised_pnl_1lot']),
        ck_realised_gross=r2(g['ck_realised_gross']), ck_charges=r2(g['ck_charges']), ck_realised_net=r2(net),
        ck_copier_gross=r2(g['ck_copier_gross']),
        ck_qty_mult=round(g['ck_qty'] / g['stratzy_qty'], 2) if g['stratzy_qty'] else None,
        slippage=r2(g['slippage']), topup_effect=r2(g['topup_effect']), missed_leg_effect=r2(g['missed_leg_effect']),
        gap_check=r2(net - g['advised_pnl'] - (g['slippage'] + g['topup_effect'] + g['missed_leg_effect'] - g['ck_charges'])),
        byDay={d: {kk: (r2(v) if isinstance(v, float) else v) for kk, v in dd.items()} for d, dd in sorted(g['byDay'].items())})
    for d in row['byDay'].values(): d['ck_realised_net'] = r2(d['ck_realised_gross'] - d['ck_charges'])
    out_algo[k] = row
    for f in ('advised_pnl', 'ck_realised_gross', 'ck_charges', 'ck_realised_net', 'slippage', 'topup_effect', 'missed_leg_effect'):
        tot[f] += row[f]
for t in TAGS:
    u = unmatched[t]; u['gross'] = r2(u['gross']); u['charges'] = r2(u['charges']); u['net'] = r2(u['gross'] - u['charges'])
    u['reasons'] = dict(u['reasons'])
um_gross = sum(unmatched[t]['gross'] for t in TAGS); um_chg = sum(unmatched[t]['charges'] for t in TAGS)
all_net = tot['ck_realised_net'] + um_gross - um_chg
all_gross = tot['ck_realised_gross'] + um_gross
tag_gross = collections.Counter()
for x in rts: tag_gross[x['otag']] += x['pnl']
rec = []
rec.append(f"all-tags net: overlay {all_net:,.2f} vs attribution.json {ATTR['byTag']['ALL']['net_open']:,.2f} (diff {all_net - ATTR['byTag']['ALL']['net_open']:,.2f})")
for t in TAGS:
    rec.append(f"{t} gross: overlay {tag_gross[t]:,.2f} vs attribution.json {ATTR['byTag'][t]['gross_open']:,.2f} (diff {tag_gross[t] - ATTR['byTag'][t]['gross_open']:,.2f})")
for line in rec: print(line)

recorder = os.path.join(IN, 'stratzy-trades.jsonl')
rec_rows = sum(1 for _ in open(recorder)) if os.path.exists(recorder) else 0
res = dict(byAlgo=out_algo, unmatchedDhan=unmatched,
    totals=dict(matched_advised_pnl=r2(tot['advised_pnl']), matched_ck_gross=r2(tot['ck_realised_gross']), matched_ck_charges=r2(tot['ck_charges']),
                matched_ck_net=r2(tot['ck_realised_net']), slippage=r2(tot['slippage']), topup_effect=r2(tot['topup_effect']),
                missed_leg_effect=r2(tot['missed_leg_effect']), unmatched_net=r2(um_gross - um_chg), all_gross=r2(all_gross), all_net=r2(all_net),
                matched_trips=match_q['matched_trips'], total_trips=len(rts), advice_pnl_mismatch=tot['advice_pnl_mismatch']),
    reconcile=rec,
    method=dict(
        advised='Per advice (backtestTrade excluded, algo=advisor folder id): leg unit pnl = sign*(avgExitPrice-entryPrice); advised_pnl = sum(maxLots*multiplier*quantity*unit) over legs of advices where ck matched >=1 leg (equals advice.pnl; mismatches counted). advised_pnl_1lot uses 1 lot. advised_pnl_all_advices = every advice in cache.',
        dhan='attr.py FIFO round trips per contract; leftovers on expired contracts settled at 0; tags COPIER/SPREAD/MARGIN_SOLO/NAKED as attr.py (round trip tagged by its opening fill).',
        join=f'Each round trip joins by its opening fill to an advice leg with same (NIFTY, expiry, strike, cp, side) and same IST entry date, createdAt within {MAX_DT_MIN} min of the fill; best = min(0.2*minutes + 20*relative entry-price gap). Monthly symbols map to the Dhan expiry in the last week of that month.',
        charges='attr.py per-order model (Rs20 brokerage split per order, STT, exch, SEBI, stamp, 18% GST) x calibration ratio to the Dhan footer; allocated to round trips by qty share of the opening and closing fills; charges on still-open Dec qty go to unmatched.',
        decomposition='ck_net - advised_pnl = slippage + topup_effect + missed_leg_effect - ck_charges (gap_check ~0). Per matched leg: slippage = ck_gross - ck_qty*advice_unit; topup_effect = (ck_qty - stratzy_qty)*advice_unit (negative if ck sized below Stratzy); missed_leg_effect = -stratzy_qty*advice_unit for advice legs ck never traded (e.g. a hedge leg).',
        topup_multiple='ck_qty_mult = ck matched leg qty / Stratzy qty (maxLots*multiplier) over matched legs.'),
    caveats=[f'VM unreachable (Twingate/adaptive down); used local data/recorder/stratzy-trades.jsonl copy ({rec_rows} rows, Sep 24-28 only) and its attrib has algo=None/source=fingerprint on all rows, so contract-level join only.',
             f'Advice cache ends {ADVICE_END}; Dhan trips opened later cannot match.',
             'Several algos often open the same contract in the same minute; the join picks the nearest advice by time then entry price, so per-algo splits can swap between simultaneous algos.',
             'ck qty is not Stratzy-only: SPREAD/MARGIN_SOLO/NAKED fills include ck manual trades that happen to share a contract-day with an advice.',
             'NIFTY only (no SENSEX fills in Dhan); MCX/CNC excluded as in attr.py.',
             'Per-tag net in this file allocates charges to the opening-fill tag of each round trip; attribution.json allocates by fill tag, so only gross and total net compare exactly.',
             f'Skipped advices/legs: {dict(skipped)}'])
json.dump(res, open(OUT, 'w'), indent=1)
print('wrote', OUT, 'algos', len(out_algo), 'matched trips', match_q['matched_trips'], '/', len(rts))
