#!/usr/bin/env python3
"""Generate comprehensive report JSON for top 25 Stratzy credit spread algos."""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC = Path('/tmp/all_credit_spread_analysis.json')
OUT = Path(__file__).parent / 'report_data.json'

LOT_SIZE = {'NIFTY': 65, 'SENSEX': 20, 'BANKNIFTY': 30}


def classify_style(name: str) -> str:
    n = name.lower()
    if 'damper' in n or name == 'Damper Credit Spread':
        return 'intraday'
    if 'overnight' in n:
        return 'overnight'
    if 'expiry' in n:
        return 'weekly_expiry'
    if 'exit-early' in n or 'exit early' in n:
        return 'exit_early'
    return 'other'


def classify_trade_type(legs: list) -> dict:
    syms = [l.get('symbol', '') for l in legs]
    combined = ''.join(syms)
    has_ce = 'CE' in combined
    has_pe = 'PE' in combined
    n_legs = len(legs)

    if n_legs == 4:
        spread_kind = 'iron_condor'
    elif n_legs == 2:
        spread_kind = 'credit_spread'
    else:
        spread_kind = f'{n_legs}_leg'

    if has_ce and has_pe:
        side = 'both_ce_pe'
    elif has_ce:
        side = 'ce_only'
    elif has_pe:
        side = 'pe_only'
    else:
        side = 'unknown'

    return {'spread_kind': spread_kind, 'side': side, 'leg_count': n_legs}


def strike_width(legs: list) -> int | None:
    strikes = []
    for leg in legs:
        m = re.search(r'(\d{4,5})(CE|PE)$', leg.get('symbol', ''))
        if m:
            strikes.append(int(m.group(1)))
    if len(strikes) >= 2:
        return max(strikes) - min(strikes)
    return None


def entry_credit(legs: list) -> float | None:
    sells = [l for l in legs if l.get('transactionType') == 'SELL']
    buys = [l for l in legs if l.get('transactionType') == 'BUY']
    if sells and buys:
        return round(float(sells[0]['entryPrice']) - float(buys[0]['entryPrice']), 2)
    return None


def analyze_algo(algo: dict) -> dict:
    rows = [r for r in algo.get('rows', []) if not r.get('backtestTrade')]
    name = algo['name']
    underlying = algo.get('underlying', 'NIFTY')
    style = classify_style(name)
    lot = LOT_SIZE.get(underlying, 65)

    # trade type breakdown
    spread_kinds = defaultdict(int)
    sides = defaultdict(int)
    widths = []
    credits = []

    for r in rows:
        legs = r.get('legs', [])
        tc = classify_trade_type(legs)
        spread_kinds[tc['spread_kind']] += 1
        sides[tc['side']] += 1
        w = strike_width(legs)
        if w:
            widths.append(w)
        c = entry_credit(legs)
        if c is not None:
            credits.append(c)

    wins = [r for r in rows if r['points_net'] > 0]
    losses = [r for r in rows if r['points_net'] < 0]
    flats = [r for r in rows if r['points_net'] == 0]

    # monthly
    monthly = defaultdict(lambda: {'trades': 0, 'pts': 0.0, 'inr': 0.0, 'wins': 0, 'losses': 0})
    for r in rows:
        m = r['closed'][:7]
        monthly[m]['trades'] += 1
        monthly[m]['pts'] += r['points_net']
        monthly[m]['inr'] += r['calc_pnl_1lot']
        if r['points_net'] > 0:
            monthly[m]['wins'] += 1
        elif r['points_net'] < 0:
            monthly[m]['losses'] += 1

    # 2026 day-level
    days_2026 = defaultdict(lambda: {'pts': 0.0, 'inr': 0.0, 'trades': 0})
    rows_2026 = [r for r in rows if r['closed'].startswith('2026')]
    for r in rows_2026:
        d = r['closed']
        days_2026[d]['pts'] += r['points_net']
        days_2026[d]['inr'] += r['calc_pnl_1lot']
        days_2026[d]['trades'] += 1

    win_days_2026 = sum(1 for d, v in days_2026.items() if v['pts'] > 0)
    loss_days_2026 = sum(1 for d, v in days_2026.items() if v['pts'] < 0)
    flat_days_2026 = sum(1 for d, v in days_2026.items() if v['pts'] == 0)

    ytd_pts = sum(r['points_net'] for r in rows_2026)
    ytd_inr = sum(r['calc_pnl_1lot'] for r in rows_2026)
    ytd_wins = sum(1 for r in rows_2026 if r['points_net'] > 0)
    ytd_losses = sum(1 for r in rows_2026 if r['points_net'] < 0)

    months_active = len(monthly) or 1
    months_2026 = len(set(r['closed'][:7] for r in rows_2026)) or 1

    margins = [r['margin'] for r in rows if r.get('margin')]

    # drawdown
    cum = peak = 0.0
    max_dd = 0.0
    for r in sorted(rows, key=lambda x: x['closed']):
        cum += r['points_net']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    live = algo.get('live') or {}
    total_pts = sum(r['points_net'] for r in rows)
    total_inr = sum(r['calc_pnl_1lot'] for r in rows)

    # human description
    side_desc = []
    total_side = sum(sides.values()) or 1
    if sides.get('ce_only'):
        side_desc.append(f"Call (CE) spreads {round(100*sides['ce_only']/total_side)}%")
    if sides.get('pe_only'):
        side_desc.append(f"Put (PE) spreads {round(100*sides['pe_only']/total_side)}%")
    if sides.get('both_ce_pe'):
        side_desc.append(f"Mixed CE+PE {round(100*sides['both_ce_pe']/total_side)}%")

    iron = spread_kinds.get('iron_condor', 0)
    credit = spread_kinds.get('credit_spread', 0)

    style_labels = {
        'overnight': 'Overnight — enter ~3 PM, exit next morning (~15h hold)',
        'intraday': 'Intraday — enter and exit same trading session',
        'weekly_expiry': 'Weekly expiry — hold spread through expiry week',
        'exit_early': 'Exit-early — intraday-to-overnight hybrid, exits before full decay',
        'other': 'Other timing',
    }

    return {
        'rank': 0,
        'id': algo.get('id'),
        'name': name,
        'underlying': underlying,
        'lot_size': lot,
        'live_since': (algo.get('liveSince') or '')[:10],
        'style': style,
        'style_label': style_labels.get(style, style),
        'trade_structure': {
            'spread_type': 'Iron condor (4-leg)' if iron else 'Vertical credit spread (2-leg)',
            'iron_condor_trades': iron,
            'credit_spread_trades': credit,
            'iron_condor_pct': round(100 * iron / max(len(rows), 1), 1),
            'avg_strike_width': round(sum(widths) / len(widths)) if widths else None,
            'avg_entry_credit_pts': round(sum(credits) / len(credits), 1) if credits else None,
            'ce_only_pct': round(100 * sides.get('ce_only', 0) / max(len(rows), 1), 1),
            'pe_only_pct': round(100 * sides.get('pe_only', 0) / max(len(rows), 1), 1),
            'both_pct': round(100 * sides.get('both_ce_pe', 0) / max(len(rows), 1), 1),
            'side_summary': ' · '.join(side_desc) if side_desc else 'N/A',
        },
        'all_time': {
            'trades': len(rows),
            'net_points': round(total_pts, 1),
            'net_inr': round(total_inr),
            'win_rate': round(100 * len(wins) / max(len(rows), 1), 1),
            'wins': len(wins),
            'losses': len(losses),
            'flats': len(flats),
            'avg_win_pts': round(sum(r['points_net'] for r in wins) / len(wins), 1) if wins else 0,
            'avg_loss_pts': round(sum(r['points_net'] for r in losses) / len(losses), 1) if losses else 0,
            'avg_win_inr': round(sum(r['calc_pnl_1lot'] for r in wins) / len(wins)) if wins else 0,
            'avg_loss_inr': round(sum(r['calc_pnl_1lot'] for r in losses) / len(losses)) if losses else 0,
            'pts_per_trade': round(total_pts / max(len(rows), 1), 1),
            'inr_per_trade': round(total_inr / max(len(rows), 1)),
            'trades_per_month': round(len(rows) / months_active, 1),
            'max_drawdown_pts': round(max_dd, 1),
            'avg_margin': round(sum(margins) / len(margins)) if margins else None,
            'first_trade': min((r['closed'] for r in rows), default=''),
            'last_trade': max((r['closed'] for r in rows), default=''),
        },
        'ytd_2026': {
            'trades': len(rows_2026),
            'net_points': round(ytd_pts, 1),
            'net_inr': round(ytd_inr),
            'win_rate': round(100 * ytd_wins / max(len(rows_2026), 1), 1),
            'wins': ytd_wins,
            'losses': ytd_losses,
            'avg_win_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] > 0) / max(ytd_wins, 1), 1),
            'avg_loss_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] < 0) / max(ytd_losses, 1), 1),
            'trades_per_month': round(len(rows_2026) / months_2026, 1),
            'win_days': win_days_2026,
            'loss_days': loss_days_2026,
            'flat_days': flat_days_2026,
            'trading_days': len(days_2026),
        },
        'monthly': {
            m: {
                'trades': v['trades'],
                'pts': round(v['pts'], 1),
                'inr': round(v['inr']),
                'wins': v['wins'],
                'losses': v['losses'],
            }
            for m, v in sorted(monthly.items())
        },
        'monthly_2026': {
            m: {
                'trades': v['trades'],
                'pts': round(v['pts'], 1),
                'inr': round(v['inr']),
            }
            for m, v in sorted(monthly.items()) if m.startswith('2026')
        },
    }


def main():
    with open(SRC) as f:
        data = json.load(f)

    algos = [a for a in data if 'credit spread' in a['name'].lower() and a.get('live')]
    algos.sort(key=lambda a: a['live']['total_points'], reverse=True)
    top25 = algos[:25]

    report = {
        'generated_at': datetime.now().isoformat(),
        'methodology': {
            'points': 'Net option premium captured: (sell_entry - buy_entry) - (sell_exit - buy_exit)',
            'inr': 'Points × lot size (NIFTY=65, SENSEX=20), 1 lot per signal',
            'iron_condor': '4-leg position with both CE and PE spreads; all Stratzy credit spread algos use 2-leg vertical spreads only',
            'win_day': 'Calendar day where sum of closed trades net points > 0',
            'loss_day': 'Calendar day where sum of closed trades net points < 0',
        },
        'summary': {
            'total_credit_spread_algos': len(algos),
            'top_n': 25,
            'note': 'Ranked by all-time live net premium points',
        },
        'algos': [],
    }

    for i, algo in enumerate(top25, 1):
        entry = analyze_algo(algo)
        entry['rank'] = i
        report['algos'].append(entry)

    with open(OUT, 'w') as f:
        json.dump(report, f, indent=2)

    print(f'Wrote {OUT} with {len(top25)} algos')


if __name__ == '__main__':
    main()