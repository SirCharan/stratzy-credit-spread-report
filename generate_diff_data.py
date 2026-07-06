#!/usr/bin/env python3
"""Generate diff-oriented comparison data + calendar heatmaps."""
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

SRC = Path('/tmp/all_credit_spread_analysis.json')
OUT = Path(__file__).parent

FAMILIES = [
    {
        'id': 'overnight_core',
        'title': 'Overnight NIFTY — same hold period, different signal',
        'subtitle': 'All enter ~3 PM, exit next morning. Same 400-pt vertical spread. Difference is WHICH side (CE/PE) and WHICH strikes the algo picks.',
        'members': [
            'IV-Imbalance Credit Spread Overnight',
            'Curvature Credit Spread Overnight',
            'Zen Credit Spread Overnight',
            'Mathematician\'s Credit Spread Overnight',
            'Flow Credit Spread Overnight',
            'Convex Credit Spread Overnight',
        ],
        'diff_key': 'ce_pe_selectivity',
    },
    {
        'id': 'overnight_other',
        'title': 'Overnight NIFTY — other variants',
        'subtitle': 'Same overnight hold but different Greek/signal names. Often correlated but not identical strikes.',
        'members': [
            'Gamma-Fluxer Credit Spread Overnight',
            'Wave-Return Credit Spread Overnight',
            'Delta-Leverage Credit Spread Overnight',
            'Sync-alpha Credit Spread Overnight',
            'Calm-Premium Credit Spread Overnight',
            'Delta-Ripple Credit Spread Overnight',
            'Chain-Sync Credit Spread Overnight',
            'ZenExit Credit Spread Overnight',
        ],
        'diff_key': 'signal_variant',
    },
    {
        'id': 'intraday',
        'title': 'Intraday — completely different game',
        'subtitle': 'Enters and exits same day. No overnight gap risk. Smaller wins/losses, more trades.',
        'members': ['Damper Credit Spread'],
        'diff_key': 'timing',
    },
    {
        'id': 'weekly_expiry',
        'title': 'Weekly expiry hold — days not hours',
        'subtitle': 'Sells spread and holds through expiry week. Higher entry credit, longer exposure.',
        'members': [
            'Theta-Harvest Credit Spread Expiry',
            'Delta-Rotation Credit Spread Expiry',
            'Vega-Shift Credit Spread Expiry',
            'Ripple-Return Credit Spread Expiry',
            'Ratio-Weave Credit Spread Expiry',
            'Ratio-Fluxer Credit Spread Expiry',
        ],
        'diff_key': 'hold_duration',
    },
    {
        'id': 'exit_early',
        'title': 'Exit-early — hybrid timing',
        'subtitle': 'May enter overnight-ish but exits before full decay; different from both intraday and full overnight.',
        'members': [
            'Ratio-Ripple Credit Spread Exit-Early',
            'Ratio-Return Credit Spread Exit-Early',
            'Ratio-Hunter2 Credit Spread Exit-Early',
        ],
        'diff_key': 'exit_timing',
    },
    {
        'id': 'sensex',
        'title': 'SENSEX — different index',
        'subtitle': 'SENSEX options, lot size 20. Points and margin not comparable to NIFTY.',
        'members': ['Deep-Rooted Credit Spread Overnight'],
        'diff_key': 'underlying',
    },
]

FAMILY_DIFFS = {
    'IV-Imbalance Credit Spread Overnight': 'Uses IV skew signal. Trades BOTH calls & puts (61% CE). Picks whichever side has better imbalance.',
    'Curvature Credit Spread Overnight': 'Uses volatility curvature signal. CALLS ONLY — never sells puts. Safest overnight variant.',
    'Zen Credit Spread Overnight': 'Mean-reversion / zen signal. More PUT-heavy (52% PE). Can diverge sharply from IV-Imbalance on same days.',
    'Mathematician\'s Credit Spread Overnight': 'Quant model variant. Similar mix to IV-Imbalance but weaker 2026 filter — more losing months.',
    'Flow Credit Spread Overnight': 'Order-flow signal. TRADES LESS (half the frequency). Higher per-trade edge when it fires.',
    'Convex Credit Spread Overnight': 'Convexity signal. 50% WR, deepest drawdown in family — inferior to siblings.',
    'Damper Credit Spread': 'ONLY intraday algo. Exits same session. ~35 pt wins vs ~60 pt overnight. Best when overnight algos bleed.',
    'Theta-Harvest Credit Spread Expiry': 'Holds to weekly expiry. Sells richer spreads (~117 pt credit). Lower WR, bigger winners.',
    'Delta-Rotation Credit Spread Expiry': 'Rotates delta exposure through the week. Similar to Theta-Harvest but lower return.',
    'Flow Credit Spread Overnight': 'Fewer, pickier entries based on flow. May sit out full months.',
    'Deep-Rooted Credit Spread Overnight': 'SENSEX overnight. ~5 trades/month. Bigger point moves (avg win +196 pts) but lot=20.',
    'Gamma-Fluxer Credit Spread Overnight': 'Gamma flux signal. CE-heavy (69%). 2026-only strong performer.',
    'Delta-Ripple Credit Spread Overnight': 'Newer (Feb 2026). Highest entry credit (~126 pts). Low 45% WR — boom or bust.',
    'Chain-Sync Credit Spread Overnight': 'Chain sync signal. Only top-25 member NEGATIVE in 2026 (−249 pts). Avoid.',
    'Ratio-Fluxer Credit Spread Expiry': 'Low frequency (~2 trades/month). Holds to expiry. Small sample, high WR.',
}


def fmt_trade(r):
    legs = r['legs']
    sell = next(l for l in legs if l['transactionType'] == 'SELL')
    buy = next(l for l in legs if l['transactionType'] == 'BUY')
    side = 'CE' if 'CE' in sell['symbol'] and 'PE' not in sell['symbol'] else 'PE' if 'PE' in sell['symbol'] else 'MIX'
    return {
        'date': r['closed'],
        'pts': r['points_net'],
        'inr': r['calc_pnl_1lot'],
        'side': side,
        'sell': {'sym': sell['symbol'], 'entry': sell['entryPrice'], 'exit': sell['exitPrice']},
        'buy': {'sym': buy['symbol'], 'entry': buy['entryPrice'], 'exit': buy['exitPrice']},
        'entry_credit': round(float(sell['entryPrice']) - float(buy['entryPrice']), 1),
    }


def short(name):
    return (name.replace(' Credit Spread Overnight', '')
              .replace(' Credit Spread Expiry', ' Exp')
              .replace(' Credit Spread Exit-Early', ' Exit')
              .replace(' Credit Spread', ''))


def parse_strike(sym):
    m = re.search(r'(\d{4,5})(CE|PE)$', sym)
    return int(m.group(1)) if m else None


def trade_side(row):
    sell = next(l for l in row['legs'] if l['transactionType'] == 'SELL')
    sym = sell['symbol']
    return 'PE' if 'PE' in sym else 'CE'


IV_IMBALANCE = 'IV-Imbalance Credit Spread Overnight'
CURVATURE = 'Curvature Credit Spread Overnight'


def build_synthetic_iron_condor(by_name, all_days):
    """Days where Curvature (CE) and IV-Imbalance (PE) both fire — manual 4-leg iron condor."""
    curv_by_date = {}
    for r in by_name[CURVATURE]['rows']:
        if r.get('backtestTrade') or not r['closed'].startswith('2026'):
            continue
        curv_by_date[r['closed'][:10]] = r

    iv_pe_dates = set()
    days = []
    day_pts = defaultdict(float)

    for r in by_name[IV_IMBALANCE]['rows']:
        if r.get('backtestTrade') or not r['closed'].startswith('2026'):
            continue
        if trade_side(r) != 'PE':
            continue
        d = r['closed'][:10]
        iv_pe_dates.add(d)
        if d not in curv_by_date:
            continue

        r_curv = curv_by_date[d]
        ce_trade = fmt_trade(r_curv)
        pe_trade = fmt_trade(r)
        combined_pts = round(r['points_net'] + r_curv['points_net'], 1)
        combined_inr = round(r['calc_pnl_1lot'] + r_curv['calc_pnl_1lot'])

        days.append({
            'date': d,
            'combined_pts': combined_pts,
            'combined_inr': combined_inr,
            'ce_pts': ce_trade['pts'],
            'pe_pts': pe_trade['pts'],
            'ce_trade': ce_trade,
            'pe_trade': pe_trade,
            'ce_spread': f"{parse_strike(ce_trade['sell']['sym'])}/{parse_strike(ce_trade['buy']['sym'])}",
            'pe_spread': f"{parse_strike(pe_trade['sell']['sym'])}/{parse_strike(pe_trade['buy']['sym'])}",
            'same_expiry': ce_trade['sell']['sym'][5:11] == pe_trade['sell']['sym'][5:11],
            'status': 'win' if combined_pts > 0 else 'loss' if combined_pts < 0 else 'flat',
        })
        day_pts[d] = combined_pts

    days.sort(key=lambda x: x['date'])

    cells = []
    for d in all_days:
        if d in day_pts:
            p = round(day_pts[d], 1)
            cells.append({
                'date': d,
                'pts': p,
                'trades': 2,
                'status': 'win' if p > 0 else 'loss' if p < 0 else 'flat',
            })
        else:
            cells.append({'date': d, 'pts': 0, 'trades': 0, 'status': 'none'})

    wins = sum(1 for x in days if x['combined_pts'] > 0)
    losses = sum(1 for x in days if x['combined_pts'] < 0)
    total = len(days) or 1

    return {
        'label': 'Synthetic iron condor',
        'description': (
            'Curvature (always CE spread) + IV-Imbalance on days it picks PE. '
            'Same overnight hold, same expiry — 4 legs total. Not a Stratzy product; double margin.'
        ),
        'legs': {
            'ce': CURVATURE,
            'pe': f'{IV_IMBALANCE} (PE days only)',
        },
        'summary': {
            'total_days': len(days),
            'win_days': wins,
            'loss_days': losses,
            'win_rate_pct': round(100 * wins / total, 1),
            'net_pts': round(sum(x['combined_pts'] for x in days), 1),
            'net_inr': sum(x['combined_inr'] for x in days),
            'avg_combined_pts': round(sum(x['combined_pts'] for x in days) / total, 1),
            'curvature_days_2026': len(curv_by_date),
            'iv_pe_days_2026': len(iv_pe_dates),
            'overlap_pct_of_curvature': round(100 * len(days) / max(len(curv_by_date), 1), 1),
            'overlap_pct_of_iv_pe': round(100 * len(days) / max(len(iv_pe_dates), 1), 1),
        },
        'days': days,
        'calendar': {
            'short': 'Synth IC',
            'cells': cells,
            'win_days': wins,
            'loss_days': losses,
            'idle_days': sum(1 for c in cells if c['status'] == 'none'),
        },
    }


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def main():
    with open(SRC) as f:
        data = json.load(f)

    by_name = {a['name']: a for a in data}
    algos = [a for a in data if 'credit spread' in a['name'].lower() and a.get('live')]
    algos.sort(key=lambda a: a['live']['total_points'], reverse=True)
    top25 = [a['name'] for a in algos[:25]]

    start = date(2026, 1, 1)
    end = date(2026, 6, 15)
    all_days = list(business_days(start, end))

    # calendar per algo
    calendars = {}
    for name in top25:
        day_pts = defaultdict(float)
        day_trades = defaultdict(int)
        for r in by_name[name]['rows']:
            if r.get('backtestTrade'):
                continue
            if r['closed'].startswith('2026'):
                day_pts[r['closed']] += r['points_net']
                day_trades[r['closed']] += 1
        cells = []
        for d in all_days:
            if d in day_pts:
                p = round(day_pts[d], 1)
                cells.append({'date': d, 'pts': p, 'trades': day_trades[d], 'status': 'win' if p > 0 else 'loss' if p < 0 else 'flat'})
            else:
                cells.append({'date': d, 'pts': 0, 'trades': 0, 'status': 'none'})
        calendars[name] = {
            'short': short(name),
            'cells': cells,
            'win_days': sum(1 for c in cells if c['status'] == 'win'),
            'loss_days': sum(1 for c in cells if c['status'] == 'loss'),
            'idle_days': sum(1 for c in cells if c['status'] == 'none'),
        }

    # trade examples top 25
    examples = {}
    for name in top25:
        rows = [r for r in by_name[name]['rows'] if not r.get('backtestTrade')]
        wins = sorted([r for r in rows if r['points_net'] > 0], key=lambda x: -x['points_net'])
        losses = sorted([r for r in rows if r['points_net'] < 0], key=lambda x: x['points_net'])
        examples[name] = {
            'short': short(name),
            'best_win': fmt_trade(wins[0]) if wins else None,
            'typical_loss': fmt_trade(losses[len(losses) // 2]) if losses else None,
        }

    # same-day comparisons (divergent)
    comparisons = []
    trio = [
        'IV-Imbalance Credit Spread Overnight',
        'Curvature Credit Spread Overnight',
        'Zen Credit Spread Overnight',
    ]
    day_map = defaultdict(dict)
    for name in top25:
        for r in by_name[name]['rows']:
            if r.get('backtestTrade') or not r['closed'].startswith('2026'):
                continue
            day_map[r['closed']].setdefault(name, []).append(fmt_trade(r))

    for d in sorted(day_map.keys()):
        present = [n for n in trio if n in day_map[d]]
        if len(present) < 2:
            continue
        results = {short(n): round(sum(t['pts'] for t in day_map[d][n]), 1) for n in present}
        signs = {n: sum(t['pts'] for t in day_map[d][n]) > 0 for n in present}
        if len(set(signs.values())) > 1:
            comparisons.append({
                'date': d,
                'label': 'Same day, different outcome',
                'algos': {short(n): day_map[d][n][0] for n in present},
                'pts': results,
            })

    comparisons.sort(key=lambda x: -max(abs(v) for v in x['pts'].values()))
    comparisons = comparisons[:12]

    # family sheets
    families_out = []
    for fam in FAMILIES:
        members = [m for m in fam['members'] if m in by_name]
        rows = []
        for m in members:
            a = by_name[m]
            rows.append({
                'name': m,
                'short': short(m),
                'one_liner': FAMILY_DIFFS.get(m, ''),
                'ce_pct': next((x['trade_structure']['ce_only_pct'] for x in json.load(open(OUT / 'report_data.json'))['algos'] if x['name'] == m), None) if (OUT / 'report_data.json').exists() else None,
            })
        # get from live data
        for row in rows:
            a = by_name[row['name']]
            rows_data = [r for r in a['rows'] if not r.get('backtestTrade')]
            ce = sum(1 for r in rows_data if 'CE' in r['legs'][0]['symbol'] and 'PE' not in ''.join(l['symbol'] for l in r['legs']))
            pe = sum(1 for r in rows_data if 'PE' in r['legs'][0]['symbol'] and 'CE' not in ''.join(l['symbol'] for l in r['legs']))
            n = len(rows_data) or 1
            row['ce_pct'] = round(100 * ce / n, 1)
            row['pe_pct'] = round(100 * pe / n, 1)
            row['trades_pm'] = round(n / max(len(set(r['closed'][:7] for r in rows_data)), 1), 1)
            row['ytd_pts'] = round(sum(r['points_net'] for r in rows_data if r['closed'].startswith('2026')), 1)
            row['avg_win'] = round(sum(r['points_net'] for r in rows_data if r['points_net'] > 0) / max(sum(1 for r in rows_data if r['points_net'] > 0), 1), 1)
            row['avg_loss'] = round(sum(r['points_net'] for r in rows_data if r['points_net'] < 0) / max(sum(1 for r in rows_data if r['points_net'] < 0), 1), 1)

        families_out.append({**fam, 'members': rows})

    # simple decision tree text
    decision = [
        {'q': 'When do you exit?', 'a': {
            'Same day (intraday)': 'Damper only',
            'Next morning (overnight)': 'IV-Imbalance, Curvature, Zen, Flow, +15 others',
            'Hold to weekly expiry': 'Theta-Harvest, Delta-Rotation, Ratio-Fluxer, Vega-Shift',
            'Exit before full overnight decay': 'Ratio-Ripple Exit, Ratio-Return Exit',
        }},
        {'q': 'Calls, puts, or both?', 'a': {
            'Calls only': 'Curvature',
            'Both (signal decides)': 'IV-Imbalance, Zen, Flow, most overnight',
            'Mostly puts': 'Ratio-Ripple Exit (95% PE)',
        }},
        {'q': 'NIFTY or SENSEX?', 'a': {
            'NIFTY (lot 65)': '24 of top 25',
            'SENSEX (lot 20)': 'Deep-Rooted only in top 25',
        }},
    ]

    synthetic_ic = build_synthetic_iron_condor(by_name, all_days)

    out = {
        'generated_at': date.today().isoformat(),
        'date_range': {'start': all_days[0], 'end': all_days[-1], 'total_days': len(all_days)},
        'top25_short': [short(n) for n in top25],
        'families': families_out,
        'decision_tree': decision,
        'calendars': calendars,
        'synthetic_iron_condor': synthetic_ic,
        'examples': examples,
        'same_day_comparisons': comparisons,
        'legend': {
            'none': 'No trade that day (gray)',
            'win': 'Net profit day (green, darker = more pts)',
            'loss': 'Net loss day (red, darker = more pts)',
        },
    }

    with open(OUT / 'diff_data.json', 'w') as f:
        json.dump(out, f, indent=2)

    print(
        f'Wrote diff_data.json — {len(calendars)} calendars, '
        f'{synthetic_ic["summary"]["total_days"]} synthetic IC days, '
        f'{len(comparisons)} comparisons'
    )


if __name__ == '__main__':
    main()