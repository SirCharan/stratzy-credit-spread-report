#!/usr/bin/env python3
"""Analyze Stratzy Option Buying algos from pastAdvices."""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

IN_PATH = Path('/tmp/all_option_buying_advices.json')
OUT_DIR = Path(__file__).parent

LOT_SIZE = {'NIFTY': 65, 'SENSEX': 20, 'BANKNIFTY': 30, 'FINNIFTY': 25, 'GOLD': 1, 'SILVER': 1, 'CRUDE OIL': 1}


def underlying_from_symbol(symbol):
    s = symbol.upper()
    for u in ['SENSEX', 'BANKNIFTY', 'FINNIFTY', 'NIFTY', 'GOLD', 'SILVER', 'CRUDEOIL', 'CRUDE']:
        if u in s or s.startswith(u[:4]):
            if u == 'CRUDE':
                return 'CRUDE OIL'
            return u if u != 'CRUDEOIL' else 'CRUDE OIL'
    return 'UNKNOWN'


def classify_style(name, algo):
    n = name.lower()
    if 'tsl' in n or 'trailing' in n:
        exit_style = 'trailing_sl'
    elif 'grid' in n:
        exit_style = 'grid'
    elif 'partial' in n or 'target' in n:
        exit_style = 'partial_target'
    elif 'fixedrr' in n.replace(' ', '') or 'rr 1:' in n.lower() or 'fixed rr' in n.lower():
        exit_style = 'fixed_rr'
    elif 'sl' in n.lower():
        exit_style = 'fixed_sl'
    else:
        exit_style = 'other'

    if 'only-calls' in n or 'only calls' in n:
        side_bias = 'ce_only'
    elif 'only-put' in n or 'only put' in n:
        side_bias = 'pe_only'
    else:
        side_bias = 'both'

    freq = (algo.get('avgFrequency') or '').lower()
    if 'intraday' in freq or 'same day' in freq:
        hold = 'intraday'
    elif 'swing' in freq or 'overnight' in freq:
        hold = 'overnight'
    else:
        hold = 'intraday'  # most option buying on stratzy is intraday

    return {'exit_style': exit_style, 'side_bias': side_bias, 'hold': hold}


def parse_trade(item, algo_underlying, lot_default=65):
    legs = item.get('legs') or item.get('trades') or []
    if not legs:
        return None

    # Option buying = long options (BUY primary leg)
    buys = [l for l in legs if l.get('transactionType') == 'BUY']
    sells = [l for l in legs if l.get('transactionType') == 'SELL']
    if not buys:
        return None

    primary = buys[0]
    sym = primary.get('symbol', '')
    underlying = underlying_from_symbol(sym)
    if underlying == 'UNKNOWN':
        underlying = algo_underlying
    leg_mult = primary.get('multiplier')
    target_mult = int(leg_mult) if leg_mult else LOT_SIZE.get(underlying, lot_default)

    entry = float(primary.get('entryPrice', 0))
    exit_ = float(primary.get('exitPrice') or entry)
    qty = primary.get('quantity', 1)
    mult = target_mult

    # points = premium move on bought option
    points = round(exit_ - entry, 2)
    calc_pnl = round((exit_ - entry) * mult * qty, 2)

    # multi-leg: sum all legs
    if len(legs) > 1:
        calc_pnl = 0
        points = 0
        for leg in legs:
            side = 1 if leg.get('transactionType') == 'BUY' else -1
            e = float(leg.get('entryPrice', 0))
            x = float(leg.get('exitPrice') or e)
            calc_pnl += side * (x - e) * target_mult * leg.get('quantity', 1)
        points = round(calc_pnl / target_mult, 2)

    side = 'CE' if 'CE' in sym else 'PE' if 'PE' in sym else 'MIX'

    closed = item.get('closedOn') or ''
    if 'T' in closed:
        closed = closed.split('T')[0]

    summary = item.get('summary') or []
    lots_traded = summary[0].get('lotsTraded') if summary else None

    return {
        'closed': closed[:10],
        'name': item.get('name') or '',
        'underlying': underlying,
        'multiplier': target_mult,
        'side': side,
        'leg_count': len(legs),
        'signalPnl': float(item.get('signalPnl') or item.get('pnl') or calc_pnl),
        'calc_pnl_1lot': round(calc_pnl, 2),
        'pnlPercent': item.get('pnlPercent'),
        'signal_pnl_pct': item.get('signalPnlPercent'),
        'points_net': points,
        'margin': item.get('marginRequired'),
        'max_lots': item.get('maxLots'),
        'lots_traded': lots_traded,
        'advice_capital_pct': item.get('adviceLevelCapital'),
        'entry_premium': entry,
        'exit_premium': exit_,
        'backtestTrade': item.get('backtestTrade') is True,
        'legs': legs,
    }


def summarize(rows, live_only=False):
    data = [r for r in rows if not live_only or not r.get('backtestTrade')]
    if not data:
        return None
    wins = [r for r in data if r['points_net'] > 0]
    losses = [r for r in data if r['points_net'] < 0]
    return {
        'trades': len(data),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(100 * len(wins) / len(data), 1),
        'total_points': round(sum(r['points_net'] for r in data), 1),
        'total_inr': round(sum(r['calc_pnl_1lot'] for r in data)),
        'avg_win_pts': round(sum(r['points_net'] for r in wins) / len(wins), 1) if wins else 0,
        'avg_loss_pts': round(sum(r['points_net'] for r in losses) / len(losses), 1) if losses else 0,
        'first_trade': min(r['closed'] for r in data if r['closed']),
        'last_trade': max(r['closed'] for r in data if r['closed']),
    }


def main():
    with open(IN_PATH) as f:
        raw = json.load(f)

    analyses = []
    for name, bundle in raw.items():
        algo = bundle['algo']
        underlying = algo.get('underlying', 'NIFTY')
        style = classify_style(name, algo)
        rows = []
        for day in bundle.get('trades', []):
            for item in day.get('items', []):
                row = parse_trade(item, underlying)
                if row:
                    rows.append(row)

        rows.sort(key=lambda r: r['closed'])
        live_rows = [r for r in rows if not r.get('backtestTrade')]
        ytd_rows = [r for r in live_rows if r['closed'].startswith('2026')]

        ce = sum(1 for r in live_rows if r['side'] == 'CE')
        pe = sum(1 for r in live_rows if r['side'] == 'PE')
        n = len(live_rows) or 1

        # 2026 day stats
        days_2026 = defaultdict(float)
        for r in ytd_rows:
            days_2026[r['closed']] += r['points_net']

        months = defaultdict(lambda: {'trades': 0, 'pts': 0, 'inr': 0})
        for r in live_rows:
            m = r['closed'][:7]
            months[m]['trades'] += 1
            months[m]['pts'] += r['points_net']
            months[m]['inr'] += r['calc_pnl_1lot']

        analyses.append({
            'name': name,
            'id': algo['_id'],
            'underlying': underlying,
            'lot_size': LOT_SIZE.get(underlying, 65),
            'liveSince': (algo.get('liveSince') or '')[:10],
            'min_capital': algo.get('minimumCapital') or algo.get('avgCapital'),
            'risk': algo.get('risk'),
            'win_ratio_headline': algo.get('winRatio'),
            'style': style,
            'ce_pct': round(100 * ce / n, 1),
            'pe_pct': round(100 * pe / n, 1),
            'all': summarize(rows),
            'live': summarize(rows, live_only=True),
            'ytd_2026': summarize(ytd_rows) if ytd_rows else None,
            'ytd_2026_days': {
                'win_days': sum(1 for v in days_2026.values() if v > 0),
                'loss_days': sum(1 for v in days_2026.values() if v < 0),
                'trading_days': len(days_2026),
            },
            'monthly': {m: {k: round(v[k], 1) if k == 'pts' else round(v[k]) for k in v} for m, v in sorted(months.items())},
            'rows': rows,
        })

    analyses = [a for a in analyses if a.get('live')]
    analyses.sort(key=lambda a: a['live']['total_points'], reverse=True)
    for i, a in enumerate(analyses, 1):
        a['rank'] = i

    top25 = analyses[:25]

    with open(OUT_DIR / 'option_buying_analysis.json', 'w') as f:
        json.dump(analyses, f, indent=2)

    with open(OUT_DIR / 'option_buying_report_data.json', 'w') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'category': 'Option Buying',
            'total_algos': len(analyses),
            'top_n': 25,
            'methodology': {
                'points': 'Premium move on bought option: exit_price - entry_price (per unit)',
                'inr': 'Points × lot size (NIFTY=65, SENSEX=20), 1 lot',
                'structure': 'Long option(s) — BUY CE or BUY PE (option buying, not spreads)',
            },
            'algos': [{k: a[k] for k in a if k != 'rows'} for a in top25],
        }, f, indent=2)

    # calendar 2026 for top 25
    cal = {}
    for a in top25:
        days = defaultdict(float)
        for r in a['rows']:
            if r.get('backtestTrade') or not r['closed'].startswith('2026'):
                continue
            days[r['closed']] += r['points_net']
        cal[a['name']] = {d: round(v, 1) for d, v in sorted(days.items())}

    with open(OUT_DIR / 'option_buying_calendar_2026.json', 'w') as f:
        json.dump(cal, f)

    print(f'Analyzed {len(analyses)} option buying algos, top 25 saved')
    print('\nTOP 25 OPTION BUYING (live net premium pts):')
    for a in top25:
        s = a['live']
        y = a.get('ytd_2026') or {}
        print(f"  {a['rank']:>2}. {a['name'][:40]:<40} {s['total_points']:>+8.0f} pts | ₹{s['total_inr']:>+9,} | WR {s['win_rate']}% | {a['underlying']}")


if __name__ == '__main__':
    main()