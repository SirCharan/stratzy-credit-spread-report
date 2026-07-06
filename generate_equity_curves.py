#!/usr/bin/env python3
"""Generate cumulative equity curve data for overlay charts."""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / 'equity_curves.json'
REPORT = Path(__file__).parent / 'report_data.json'
LOT_SIZE = {'NIFTY': 65, 'SENSEX': 20}

CS_SRC = Path('/tmp/all_credit_spread_analysis.json')
OB_SRC = Path(__file__).parent / 'option_buying_analysis.json'


def short(name, cat):
    n = name.replace("Stratzy's ", '')
    if cat == 'credit_spread':
        n = n.replace(' Credit Spread Overnight', '').replace(' Credit Spread Expiry', ' Exp')
        n = n.replace(' Credit Spread Exit-Early', ' Exit').replace(' Credit Spread', '')
    return n[:30]


def trade_curve(rows, metric='inr'):
    rows = [r for r in rows if not r.get('backtestTrade')]
    rows.sort(key=lambda r: (r['closed'], r.get('name', '')))
    cum = 0.0
    points = []
    for i, r in enumerate(rows, 1):
        cum += r['calc_pnl_1lot'] if metric == 'inr' else r['points_net']
        points.append({
            'x': r['closed'],
            'y': round(cum, 2),
            'trade': i,
            'day_pnl': round(r['calc_pnl_1lot'] if metric == 'inr' else r['points_net'], 2),
        })
    return points


def daily_curve(rows, metric='inr'):
    """Calendar equity: cumulative by date, one point per trading day."""
    rows = [r for r in rows if not r.get('backtestTrade')]
    by_day = defaultdict(float)
    for r in rows:
        by_day[r['closed']] += r['calc_pnl_1lot'] if metric == 'inr' else r['points_net']
    if not by_day:
        return []
    start = min(by_day.keys())
    end = max(by_day.keys())
    d = datetime.strptime(start, '%Y-%m-%d').date()
    end_d = datetime.strptime(end, '%Y-%m-%d').date()
    cum = 0.0
    points = []
    while d <= end_d:
        iso = d.isoformat()
        if iso in by_day:
            cum += by_day[iso]
            points.append({'x': iso, 'y': round(cum, 2), 'day_pnl': round(by_day[iso], 2)})
        d += timedelta(days=1)
    return points


def algo_entry(a, category):
    rows = a.get('rows', [])
    live = a.get('live') or {}
    return {
        'id': a.get('id') or a.get('name'),
        'name': a['name'],
        'short': short(a['name'], category),
        'category': category,
        'underlying': a.get('underlying', 'NIFTY'),
        'total_inr': live.get('total_inr', 0),
        'total_pts': live.get('total_points', 0),
        'trades': live.get('trades', 0),
        'live_since': (a.get('liveSince') or '')[:10],
        'curves': {
            'daily_inr': daily_curve(rows, 'inr'),
            'daily_pts': daily_curve(rows, 'pts'),
            'trade_inr': trade_curve(rows, 'inr'),
            'trade_pts': trade_curve(rows, 'pts'),
        },
    }


def filter_curve(curve, from_date=None):
    if not from_date:
        return curve
    out = []
    last_y = 0
    for p in curve:
        if p['x'] >= from_date:
            # rebase to 0 at start of filter window
            if not out:
                # find cum just before window
                pass
            out.append(p)
    if not out:
        return []
    base = 0
    # rebase: subtract value at first point's implied start
    first_day_pnl = out[0].get('day_pnl')
    # simpler: filter daily and recompute cum from filtered days only
    return out


def daily_curve_from(rows, metric, from_date=None):
    c = daily_curve(rows, metric)
    if not from_date:
        return c
    filtered_rows = [r for r in rows if not r.get('backtestTrade') and r['closed'] >= from_date]
    return daily_curve(filtered_rows, metric)


def max_drawdown(curve):
    peak = float('-inf')
    max_dd = 0.0
    for p in curve:
        peak = max(peak, p['y'])
        max_dd = max(max_dd, peak - p['y'])
    return round(max_dd, 2)


def combine_what_if(members, source_data, year=None):
    """Sum daily P&L when running multiple strategies @ 1 lot each."""
    algos = []
    daily_per = []
    for name in members:
        a = next(x for x in source_data if x['name'] == name)
        algos.append(a)
        rows = [r for r in a['rows'] if not r.get('backtestTrade')]
        if year:
            rows = [r for r in rows if r['closed'].startswith(year)]
        by_day = defaultdict(lambda: {'inr': 0.0, 'pts': 0.0, 'trades': 0})
        for r in rows:
            by_day[r['closed']]['inr'] += r['calc_pnl_1lot']
            by_day[r['closed']]['pts'] += r['points_net']
            by_day[r['closed']]['trades'] += 1
        daily_per.append(by_day)

    all_days = sorted(set().union(*[set(d.keys()) for d in daily_per]))
    combined_by_day = defaultdict(lambda: {'inr': 0.0, 'pts': 0.0, 'trades': 0})
    overlap_days = 0
    for d in all_days:
        active = sum(1 for da in daily_per if d in da)
        if active > 1:
            overlap_days += 1
        for da in daily_per:
            if d in da:
                combined_by_day[d]['inr'] += da[d]['inr']
                combined_by_day[d]['pts'] += da[d]['pts']
                combined_by_day[d]['trades'] += da[d]['trades']

    def to_curves():
        cum_inr = cum_pts = 0.0
        daily_inr = []
        daily_pts = []
        for d in all_days:
            v_inr = combined_by_day[d]['inr']
            v_pts = combined_by_day[d]['pts']
            cum_inr += v_inr
            cum_pts += v_pts
            daily_inr.append({'x': d, 'y': round(cum_inr, 2), 'day_pnl': round(v_inr, 2)})
            daily_pts.append({'x': d, 'y': round(cum_pts, 2), 'day_pnl': round(v_pts, 2)})
        return daily_inr, daily_pts

    daily_inr, daily_pts = to_curves()
    solo = []
    for a, da in zip(algos, daily_per):
        rows = [r for r in a['rows'] if not r.get('backtestTrade')]
        if year:
            rows = [r for r in rows if r['closed'].startswith(year)]
        solo.append({
            'name': a['name'],
            'trading_days': len(da),
            'trades': len(rows),
            'total_inr': round(sum(r['calc_pnl_1lot'] for r in rows), 2),
            'total_pts': round(sum(r['points_net'] for r in rows), 2),
            'max_dd_inr': max_drawdown(daily_curve(rows, 'inr')),
            'max_dd_pts': max_drawdown(daily_curve(rows, 'pts')),
        })

    day_sets = [set(d.keys()) for d in daily_per]
    only_sets = [day_sets[i] - set().union(*[day_sets[j] for j in range(len(day_sets)) if j != i])
                 for i in range(len(day_sets))]

    return {
        'overlap_days': overlap_days,
        'total_days': len(all_days),
        'solo_only_days': [len(s) for s in only_sets],
        'trades': sum(combined_by_day[d]['trades'] for d in all_days),
        'total_inr': round(sum(combined_by_day[d]['inr'] for d in all_days), 2),
        'total_pts': round(sum(combined_by_day[d]['pts'] for d in all_days), 2),
        'max_dd_inr': max_drawdown(daily_inr),
        'max_dd_pts': max_drawdown(daily_pts),
        'solo': solo,
        'curves': {'daily_inr': daily_inr, 'daily_pts': daily_pts},
    }


def _classify_side(legs):
    combined = ''.join(l.get('symbol', '') for l in legs)
    if 'CE' in combined and 'PE' in combined:
        return 'both_ce_pe'
    if 'PE' in combined:
        return 'pe_only'
    if 'CE' in combined:
        return 'ce_only'
    return 'unknown'


def _entry_credit(legs):
    sells = [l for l in legs if l.get('transactionType') == 'SELL']
    buys = [l for l in legs if l.get('transactionType') == 'BUY']
    if sells and buys:
        return round(float(sells[0]['entryPrice']) - float(buys[0]['entryPrice']), 2)
    return None


def _strike_width(legs):
    strikes = []
    for leg in legs:
        m = re.search(r'(\d{4,5})(CE|PE)$', leg.get('symbol', ''))
        if m:
            strikes.append(int(m.group(1)))
    return max(strikes) - min(strikes) if len(strikes) >= 2 else None


def _period_returns(monthly, avg_margin):
    months = sorted(monthly.keys())
    if not months:
        return {}

    def pack(ms):
        inr = sum(monthly[m]['inr'] for m in ms)
        pts = sum(monthly[m]['pts'] for m in ms)
        return {
            'inr': round(inr),
            'pts': round(pts, 1),
            'pct_on_margin': round(100 * inr / avg_margin, 1) if avg_margin else None,
            'months': len(ms),
        }

    return {
        '1M': pack(months[-1:]),
        '3M': pack(months[-3:]),
        '6M': pack(months[-6:]),
        '1Y': pack(months[-12:]),
        'all': pack(months),
    }


def analyze_combined_detailed(members, cs_data):
    """Stratzy-style detailed stats for a multi-algo portfolio."""
    member_algos = [next(x for x in cs_data if x['name'] == name) for name in members]
    rows = []
    for a in member_algos:
        for r in a['rows']:
            if r.get('backtestTrade'):
                continue
            rows.append({**r, '_algo': a['name']})
    rows.sort(key=lambda r: (r['closed'], r['_algo']))

    sides = defaultdict(int)
    widths = []
    credits = []
    margins = []
    for r in rows:
        legs = r.get('legs', [])
        sides[_classify_side(legs)] += 1
        w = _strike_width(legs)
        if w:
            widths.append(w)
        c = _entry_credit(legs)
        if c is not None:
            credits.append(c)
        if r.get('margin'):
            margins.append(r['margin'])

    wins = [r for r in rows if r['points_net'] > 0]
    losses = [r for r in rows if r['points_net'] < 0]

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

    by_day = defaultdict(lambda: {'pts': 0.0, 'inr': 0.0, 'trades': 0, 'margin': 0.0, 'entry_credit': 0.0})
    for r in rows:
        d = r['closed']
        by_day[d]['pts'] += r['points_net']
        by_day[d]['inr'] += r['calc_pnl_1lot']
        by_day[d]['trades'] += 1
        by_day[d]['margin'] += r.get('margin') or 0
        c = _entry_credit(r.get('legs', []))
        if c is not None:
            by_day[d]['entry_credit'] += c

    win_days = sum(1 for v in by_day.values() if v['pts'] > 0)
    loss_days = sum(1 for v in by_day.values() if v['pts'] < 0)
    flat_days = sum(1 for v in by_day.values() if v['pts'] == 0)
    overlap_days = sum(1 for v in by_day.values() if v['trades'] > 1)

    rows_2026 = [r for r in rows if r['closed'].startswith('2026')]
    days_2026 = defaultdict(lambda: {'pts': 0.0, 'inr': 0.0, 'trades': 0})
    for r in rows_2026:
        days_2026[r['closed']]['pts'] += r['points_net']
        days_2026[r['closed']]['inr'] += r['calc_pnl_1lot']
        days_2026[r['closed']]['trades'] += 1
    ytd_wins = sum(1 for r in rows_2026 if r['points_net'] > 0)
    ytd_losses = sum(1 for r in rows_2026 if r['points_net'] < 0)
    win_days_2026 = sum(1 for v in days_2026.values() if v['pts'] > 0)
    loss_days_2026 = sum(1 for v in days_2026.values() if v['pts'] < 0)

    total_pts = sum(r['points_net'] for r in rows)
    total_inr = sum(r['calc_pnl_1lot'] for r in rows)
    months_active = len(monthly) or 1
    months_2026 = len(set(r['closed'][:7] for r in rows_2026)) or 1

    daily_pts_curve = daily_curve(rows, 'pts')
    daily_inr_curve = daily_curve(rows, 'inr')
    max_dd_pts = max_drawdown(daily_pts_curve)
    max_dd_inr = max_drawdown(daily_inr_curve)

    avg_margin_trade = round(sum(margins) / len(margins)) if margins else None
    overlap_margins = [v['margin'] for v in by_day.values() if v['trades'] > 1]
    solo_margins = [v['margin'] for v in by_day.values() if v['trades'] == 1]
    avg_margin_overlap_day = round(sum(overlap_margins) / len(overlap_margins)) if overlap_margins else None
    avg_margin_solo_day = round(sum(solo_margins) / len(solo_margins)) if solo_margins else None

    overlap_credits = [v['entry_credit'] for v in by_day.values() if v['trades'] > 1]
    solo_credits = [v['entry_credit'] for v in by_day.values() if v['trades'] == 1]
    avg_credit_per_spread = round(sum(credits) / len(credits), 1) if credits else None
    avg_credit_overlap_day = round(sum(overlap_credits) / len(overlap_credits), 1) if overlap_credits else None
    avg_credit_solo_day = round(sum(solo_credits) / len(solo_credits), 1) if solo_credits else None

    total_side = len(rows) or 1
    side_bits = []
    if sides.get('ce_only'):
        side_bits.append(f"Call (CE) spreads {round(100 * sides['ce_only'] / total_side)}%")
    if sides.get('pe_only'):
        side_bits.append(f"Put (PE) spreads {round(100 * sides['pe_only'] / total_side)}%")

    monthly_out = {
        m: {
            'trades': v['trades'],
            'pts': round(v['pts'], 1),
            'inr': round(v['inr']),
            'wins': v['wins'],
            'losses': v['losses'],
        }
        for m, v in sorted(monthly.items())
    }

    capital_base = avg_margin_overlap_day or avg_margin_trade or 1

    return {
        'name': ' + '.join(short(m, 'credit_spread') for m in members),
        'underlying': 'NIFTY',
        'lot_size': 65,
        'style': 'overnight',
        'style_label': 'Portfolio — both overnight NIFTY credit spreads @ 1 lot each',
        'live_since': min((r['closed'] for r in rows), default=''),
        'trade_structure': {
            'spread_type': 'Portfolio: 2× vertical credit spread (4 legs max/day)',
            'iron_condor_trades': 0,
            'iron_condor_pct': 0.0,
            'credit_spread_trades': len(rows),
            'avg_strike_width': round(sum(widths) / len(widths)) if widths else 400,
            # Per-spread average (one 2-leg trade). Use portfolio fields for combined-day totals.
            'avg_entry_credit_pts': avg_credit_per_spread,
            'avg_entry_credit_per_spread': avg_credit_per_spread,
            'avg_entry_credit_overlap_day': avg_credit_overlap_day,
            'avg_entry_credit_solo_day': avg_credit_solo_day,
            'ce_only_pct': round(100 * sides.get('ce_only', 0) / total_side, 1),
            'pe_only_pct': round(100 * sides.get('pe_only', 0) / total_side, 1),
            'side_summary': ' · '.join(side_bits) if side_bits else 'N/A',
        },
        'portfolio': {
            'members': [short(m, 'credit_spread') for m in members],
            'overlap_days': overlap_days,
            'solo_days': len(by_day) - overlap_days,
            'avg_margin_per_trade': avg_margin_trade,
            'avg_margin_overlap_day': avg_margin_overlap_day,
            'avg_margin_solo_day': avg_margin_solo_day,
            'est_capital_overlap': avg_margin_overlap_day,
            'avg_entry_credit_overlap_day': avg_credit_overlap_day,
            'avg_entry_credit_solo_day': avg_credit_solo_day,
            'avg_entry_credit_per_spread': avg_credit_per_spread,
        },
        'returns': _period_returns(monthly_out, capital_base),
        'all_time': {
            'trades': len(rows),
            'net_points': round(total_pts, 1),
            'net_inr': round(total_inr),
            'win_rate': round(100 * len(wins) / max(len(rows), 1), 1),
            'wins': len(wins),
            'losses': len(losses),
            'avg_win_pts': round(sum(r['points_net'] for r in wins) / len(wins), 1) if wins else 0,
            'avg_loss_pts': round(sum(r['points_net'] for r in losses) / len(losses), 1) if losses else 0,
            'avg_win_inr': round(sum(r['calc_pnl_1lot'] for r in wins) / len(wins)) if wins else 0,
            'avg_loss_inr': round(sum(r['calc_pnl_1lot'] for r in losses) / len(losses)) if losses else 0,
            'pts_per_trade': round(total_pts / max(len(rows), 1), 1),
            'inr_per_trade': round(total_inr / max(len(rows), 1)),
            'trades_per_month': round(len(rows) / months_active, 1),
            'max_drawdown_pts': max_dd_pts,
            'max_drawdown_inr': max_dd_inr,
            'win_days': win_days,
            'loss_days': loss_days,
            'flat_days': flat_days,
            'trading_days': len(by_day),
            'day_win_rate': round(100 * win_days / max(len(by_day), 1), 1),
            'first_trade': min((r['closed'] for r in rows), default=''),
            'last_trade': max((r['closed'] for r in rows), default=''),
        },
        'ytd_2026': {
            'trades': len(rows_2026),
            'net_points': round(sum(r['points_net'] for r in rows_2026), 1),
            'net_inr': round(sum(r['calc_pnl_1lot'] for r in rows_2026)),
            'win_rate': round(100 * ytd_wins / max(len(rows_2026), 1), 1),
            'wins': ytd_wins,
            'losses': ytd_losses,
            'avg_win_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] > 0) / max(ytd_wins, 1), 1),
            'avg_loss_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] < 0) / max(ytd_losses, 1), 1),
            'trades_per_month': round(len(rows_2026) / months_2026, 1),
            'win_days': win_days_2026,
            'loss_days': loss_days_2026,
            'trading_days': len(days_2026),
            'day_win_rate': round(100 * win_days_2026 / max(len(days_2026), 1), 1),
        },
        'monthly': monthly_out,
        'monthly_2026': {m: v for m, v in monthly_out.items() if m.startswith('2026')},
    }


def analyze_combined_detailed_ob(members, ob_data):
    """Stratzy-style detailed stats for a multi-algo option buying portfolio."""
    member_algos = [next(x for x in ob_data if x['name'] == name) for name in members]
    rows = []
    for a in member_algos:
        for r in a['rows']:
            if r.get('backtestTrade'):
                continue
            rows.append({**r, '_algo': a['name']})
    rows.sort(key=lambda r: (r['closed'], r['_algo']))

    sides = defaultdict(int)
    entries = []
    margins = []
    for r in rows:
        sides[r.get('side', 'MIX').lower()] += 1
        if r.get('entry_premium') is not None:
            entries.append(r['entry_premium'])
        if r.get('margin'):
            margins.append(r['margin'])

    wins = [r for r in rows if r['points_net'] > 0]
    losses = [r for r in rows if r['points_net'] < 0]

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

    by_day = defaultdict(lambda: {'pts': 0.0, 'inr': 0.0, 'trades': 0, 'margin': 0.0, 'entry_premium': 0.0})
    for r in rows:
        d = r['closed']
        by_day[d]['pts'] += r['points_net']
        by_day[d]['inr'] += r['calc_pnl_1lot']
        by_day[d]['trades'] += 1
        by_day[d]['margin'] += r.get('margin') or 0
        by_day[d]['entry_premium'] += r.get('entry_premium') or 0

    win_days = sum(1 for v in by_day.values() if v['pts'] > 0)
    loss_days = sum(1 for v in by_day.values() if v['pts'] < 0)
    flat_days = sum(1 for v in by_day.values() if v['pts'] == 0)
    overlap_days = sum(1 for v in by_day.values() if v['trades'] > 1)

    rows_2026 = [r for r in rows if r['closed'].startswith('2026')]
    days_2026 = defaultdict(lambda: {'pts': 0.0, 'inr': 0.0, 'trades': 0})
    for r in rows_2026:
        days_2026[r['closed']]['pts'] += r['points_net']
        days_2026[r['closed']]['inr'] += r['calc_pnl_1lot']
        days_2026[r['closed']]['trades'] += 1
    ytd_wins = sum(1 for r in rows_2026 if r['points_net'] > 0)
    ytd_losses = sum(1 for r in rows_2026 if r['points_net'] < 0)
    win_days_2026 = sum(1 for v in days_2026.values() if v['pts'] > 0)
    loss_days_2026 = sum(1 for v in days_2026.values() if v['pts'] < 0)

    total_pts = sum(r['points_net'] for r in rows)
    total_inr = sum(r['calc_pnl_1lot'] for r in rows)
    months_active = len(monthly) or 1
    months_2026 = len(set(r['closed'][:7] for r in rows_2026)) or 1

    daily_pts_curve = daily_curve(rows, 'pts')
    daily_inr_curve = daily_curve(rows, 'inr')
    max_dd_pts = max_drawdown(daily_pts_curve)
    max_dd_inr = max_drawdown(daily_inr_curve)

    avg_margin_trade = round(sum(margins) / len(margins)) if margins else None
    overlap_margins = [v['margin'] for v in by_day.values() if v['trades'] > 1]
    solo_margins = [v['margin'] for v in by_day.values() if v['trades'] == 1]
    avg_margin_overlap_day = round(sum(overlap_margins) / len(overlap_margins)) if overlap_margins else None
    avg_margin_solo_day = round(sum(solo_margins) / len(solo_margins)) if solo_margins else None

    overlap_entries = [v['entry_premium'] for v in by_day.values() if v['trades'] > 1]
    solo_entries = [v['entry_premium'] for v in by_day.values() if v['trades'] == 1]
    avg_entry = round(sum(entries) / len(entries), 1) if entries else None
    avg_entry_overlap_day = round(sum(overlap_entries) / len(overlap_entries), 1) if overlap_entries else None
    avg_entry_solo_day = round(sum(solo_entries) / len(solo_entries), 1) if solo_entries else None

    total_side = len(rows) or 1
    side_bits = []
    if sides.get('ce'):
        side_bits.append(f"Long CE {round(100 * sides['ce'] / total_side)}%")
    if sides.get('pe'):
        side_bits.append(f"Long PE {round(100 * sides['pe'] / total_side)}%")

    monthly_out = {
        m: {
            'trades': v['trades'],
            'pts': round(v['pts'], 1),
            'inr': round(v['inr']),
            'wins': v['wins'],
            'losses': v['losses'],
        }
        for m, v in sorted(monthly.items())
    }

    min_caps = [a.get('min_capital') or 0 for a in member_algos]
    capital_base = avg_margin_overlap_day or (sum(min_caps) if overlap_days else (min_caps[0] if min_caps else 1))

    exit_bits = [f"{short(a['name'], 'option_buying')} ({a.get('style', {}).get('exit_style', '?')})" for a in member_algos]

    return {
        'name': ' + '.join(short(m, 'option_buying') for m in members),
        'underlying': 'NIFTY',
        'lot_size': 65,
        'style': 'intraday',
        'style_label': 'Portfolio — both intraday option buying algos @ 1 lot each',
        'live_since': min((r['closed'] for r in rows), default=''),
        'trade_structure': {
            'spread_type': 'Portfolio: 2× long single-leg options (intraday)',
            'iron_condor_trades': 0,
            'iron_condor_pct': 0.0,
            'credit_spread_trades': 0,
            'avg_strike_width': None,
            'avg_entry_credit_pts': avg_entry,
            'avg_entry_credit_per_spread': avg_entry,
            'avg_entry_credit_overlap_day': avg_entry_overlap_day,
            'avg_entry_credit_solo_day': avg_entry_solo_day,
            'ce_only_pct': round(100 * sides.get('ce', 0) / total_side, 1),
            'pe_only_pct': round(100 * sides.get('pe', 0) / total_side, 1),
            'side_summary': ' · '.join(side_bits) if side_bits else 'N/A',
            'exit_styles': ' · '.join(exit_bits),
        },
        'portfolio': {
            'members': [short(m, 'option_buying') for m in members],
            'overlap_days': overlap_days,
            'solo_days': len(by_day) - overlap_days,
            'avg_margin_per_trade': avg_margin_trade,
            'avg_margin_overlap_day': avg_margin_overlap_day,
            'avg_margin_solo_day': avg_margin_solo_day,
            'est_capital_overlap': capital_base,
            'avg_entry_credit_overlap_day': avg_entry_overlap_day,
            'avg_entry_credit_solo_day': avg_entry_solo_day,
            'avg_entry_credit_per_spread': avg_entry,
        },
        'returns': _period_returns(monthly_out, capital_base),
        'all_time': {
            'trades': len(rows),
            'net_points': round(total_pts, 1),
            'net_inr': round(total_inr),
            'win_rate': round(100 * len(wins) / max(len(rows), 1), 1),
            'wins': len(wins),
            'losses': len(losses),
            'avg_win_pts': round(sum(r['points_net'] for r in wins) / len(wins), 1) if wins else 0,
            'avg_loss_pts': round(sum(r['points_net'] for r in losses) / len(losses), 1) if losses else 0,
            'avg_win_inr': round(sum(r['calc_pnl_1lot'] for r in wins) / len(wins)) if wins else 0,
            'avg_loss_inr': round(sum(r['calc_pnl_1lot'] for r in losses) / len(losses)) if losses else 0,
            'pts_per_trade': round(total_pts / max(len(rows), 1), 1),
            'inr_per_trade': round(total_inr / max(len(rows), 1)),
            'trades_per_month': round(len(rows) / months_active, 1),
            'max_drawdown_pts': max_dd_pts,
            'max_drawdown_inr': max_dd_inr,
            'win_days': win_days,
            'loss_days': loss_days,
            'flat_days': flat_days,
            'trading_days': len(by_day),
            'day_win_rate': round(100 * win_days / max(len(by_day), 1), 1),
            'first_trade': min((r['closed'] for r in rows), default=''),
            'last_trade': max((r['closed'] for r in rows), default=''),
        },
        'ytd_2026': {
            'trades': len(rows_2026),
            'net_points': round(sum(r['points_net'] for r in rows_2026), 1),
            'net_inr': round(sum(r['calc_pnl_1lot'] for r in rows_2026)),
            'win_rate': round(100 * ytd_wins / max(len(rows_2026), 1), 1),
            'wins': ytd_wins,
            'losses': ytd_losses,
            'avg_win_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] > 0) / max(ytd_wins, 1), 1),
            'avg_loss_pts': round(sum(r['points_net'] for r in rows_2026 if r['points_net'] < 0) / max(ytd_losses, 1), 1),
            'trades_per_month': round(len(rows_2026) / months_2026, 1),
            'win_days': win_days_2026,
            'loss_days': loss_days_2026,
            'trading_days': len(days_2026),
            'day_win_rate': round(100 * win_days_2026 / max(len(days_2026), 1), 1),
        },
        'monthly': monthly_out,
        'monthly_2026': {m: v for m, v in monthly_out.items() if m.startswith('2026')},
    }


def build_what_if(cs_data, ob_data, algos_out):
    def aid(name_part):
        return next((a['id'] for a in algos_out if name_part in a['name']), '')

    OB_REPORT = Path(__file__).parent / 'option_buying_report_data.json'
    cs_reports = json.load(open(REPORT)).get('algos', []) if REPORT.exists() else []
    ob_reports = json.load(open(OB_REPORT)).get('algos', []) if OB_REPORT.exists() else []

    combos = [
        {
            'id': 'zen_curvature',
            'label': 'Zen + Curvature',
            'category': 'credit_spread',
            'source': 'cs',
            'combine_mode': 'half_sum',
            'description': (
                'Run both overnight NIFTY credit spreads @ 1 lot each. '
                'Chart shows (Zen + Curvature) ÷ 2 for relative gain vs solo algos.'
            ),
            'members': [
                'Zen Credit Spread Overnight',
                'Curvature Credit Spread Overnight',
            ],
            'notes': [
                'Curvature = calls only (100% CE). Zen picks CE or PE (~52% PE).',
                'They share 112 of 147 Zen days / 129 Curvature days (same overnight hold).',
                'Not an iron condor — both can sell CE on the same day (stacked call risk).',
            ],
        },
        {
            'id': 'burst_settle',
            'label': 'Burst GRID + Settle-Down',
            'category': 'option_buying',
            'source': 'ob',
            'combine_mode': 'full_sum',
            'description': (
                'Run both 2026-leading intraday option buyers @ 1 lot each. '
                'Burst GRID (grid exit, momentum) + Settle-Down (40% TSL, vol settle). '
                'Combined equity sums same-day P&L when both fire.'
            ),
            'members': [
                'Burst GRID (30% SL)',
                'Settle-Down 40% TSL',
            ],
            'notes': [
                'Burst GRID = grid exit on momentum bursts (#1 2026 YTD). Settle-Down = trailing SL after vol settles.',
                'Different trade frequency — Burst ~21 tr/mo vs Settle ~10 tr/mo in 2026.',
                'On overlap days you hold 2 long options intraday (2× premium deployed).',
                'Complementary exits: grid scales out vs TSL rides trend — not guaranteed to diversify.',
            ],
        },
    ]

    out = []
    for combo in combos:
        source = cs_data if combo['source'] == 'cs' else ob_data
        cat = combo['category']
        all_stats = combine_what_if(combo['members'], source)
        y2026 = combine_what_if(combo['members'], source, year='2026')
        reports = cs_reports if combo['source'] == 'cs' else ob_reports
        analyze = analyze_combined_detailed if combo['source'] == 'cs' else analyze_combined_detailed_ob
        member_reports = []
        for m in combo['members']:
            rep = next((a for a in reports if a['name'] == m), None)
            member_reports.append({
                'name': m,
                'short': short(m, cat),
                'report': rep,
            })
        out.append({
            **combo,
            'member_ids': [aid(m.split()[0]) if combo['source'] == 'cs' else aid(m.split('(')[0].strip()) for m in combo['members']],
            'member_shorts': [short(m, cat) for m in combo['members']],
            'stats': {'all': {k: v for k, v in all_stats.items() if k != 'curves'},
                      '2026': {k: v for k, v in y2026.items() if k != 'curves'}},
            'combined_curves': all_stats['curves'],
            'combined_curves_2026': y2026['curves'],
            'detailed': {
                'combined': analyze(combo['members'], source),
                'members': member_reports,
            },
        })
    return out


def main():
    algos = []

    if CS_SRC.exists():
        cs = json.load(open(CS_SRC))
        cs_list = sorted([a for a in cs if a.get('live')], key=lambda a: -a['live']['total_points'])
        for a in cs_list[:25]:
            algos.append(algo_entry(a, 'credit_spread'))

    if OB_SRC.exists():
        ob = json.load(open(OB_SRC))
        for a in ob[:25]:
            algos.append(algo_entry(a, 'option_buying'))

    # 2026-only curves
    for ag in algos:
        rows = []
        src = next((a for a in json.load(open(CS_SRC)) if a['name'] == ag['name']), None) if CS_SRC.exists() else None
        if not src:
            src = next((a for a in json.load(open(OB_SRC)) if a['name'] == ag['name']), None)
        if src:
            rows = [r for r in src.get('rows', []) if not r.get('backtestTrade') and r['closed'].startswith('2026')]
        ag['curves_2026'] = {
            'daily_inr': daily_curve(rows, 'inr'),
            'daily_pts': daily_curve(rows, 'pts'),
            'trade_inr': trade_curve(rows, 'inr'),
            'trade_pts': trade_curve(rows, 'pts'),
        }

    def aid(name_part):
        return next((a['id'] for a in algos if name_part in a['name']), '')

    presets = [
        # Credit spread
        {'id': 'cs_top5', 'category': 'credit_spread', 'label': 'Top 5 Credit Spreads',
         'ids': [a['id'] for a in algos if a['category'] == 'credit_spread'][:5]},
        {'id': 'overnight_trio', 'category': 'credit_spread', 'label': 'IV-Imbalance vs Curvature vs Zen',
         'ids': [aid('IV-Imbalance'), aid('Curvature Credit Spread'), aid('Zen Credit Spread')]},
        {'id': 'cs_expiry', 'category': 'credit_spread', 'label': 'Expiry holds: Theta-Harvest + Ratio-Fluxer',
         'ids': [aid('Theta-Harvest'), aid('Ratio-Fluxer'), aid('Delta-Rotation')]},
        # Option buying
        {'id': 'ob_top5', 'category': 'option_buying', 'label': 'Top 5 Option Buying',
         'ids': [a['id'] for a in algos if a['category'] == 'option_buying'][:5]},
        {'id': 'ob_2026_grid', 'category': 'option_buying', 'label': '2026 GRID leaders',
         'ids': [aid('Burst GRID'), aid('Vacuum GRID'), aid('Savdhaan')], 'use_2026': True},
        {'id': 'ob_signals', 'category': 'option_buying', 'label': 'Signal algos: Tracker + Scalper + TejNiti',
         'ids': [aid("Stratzy's Option Tracker"), aid('Index Scalper'), aid('TejNiti'), aid('SkewHunter')]},
        {'id': 'ob_tsl', 'category': 'option_buying', 'label': 'TSL family',
         'ids': [aid('Settle-Down'), aid('SkewHunter TSL'), aid('Wise-Move'), aid('Nischay')]},
        {'id': 'ob_exit_styles', 'category': 'option_buying', 'label': 'Exit styles: GRID vs TSL vs Partial',
         'ids': [aid('Burst GRID'), aid('Settle-Down'), aid('Harbor')]},
        {'id': 'ob_top10', 'category': 'option_buying', 'label': 'Top 10 Option Buying',
         'ids': [a['id'] for a in algos if a['category'] == 'option_buying'][:10]},
        # Mixed
        {'id': 'grid_vs_iv', 'category': 'mixed', 'label': '2026: GRID vs IV-Imbalance (buy vs sell)',
         'ids': [aid('Burst GRID'), aid('Vacuum GRID'), aid('IV-Imbalance')], 'use_2026': True},
        {'id': 'your_stack', 'category': 'mixed', 'label': 'IV-Imbalance + Damper + Burst GRID',
         'ids': [aid('IV-Imbalance'), aid('Damper Credit Spread'), aid('Burst GRID')]},
        {'id': 'best_2026', 'category': 'mixed', 'label': 'Best 2026: CS + OB combined',
         'ids': [aid('Burst GRID'), aid('Vacuum GRID'), aid('IV-Imbalance'), aid('Savdhaan')], 'use_2026': True},
    ]
    presets = [{**p, 'ids': [i for i in p['ids'] if i]} for p in presets]

    palette = [
        '#3b9eff', '#22c55e', '#f59e0b', '#ef4444', '#a78bfa',
        '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16',
        '#06b6d4', '#e879f9', '#fb7185', '#4ade80', '#fbbf24',
    ]

    ob_raw = json.load(open(OB_SRC)) if OB_SRC.exists() else []
    what_if = []
    if CS_SRC.exists() or OB_SRC.exists():
        what_if = build_what_if(
            json.load(open(CS_SRC)) if CS_SRC.exists() else [],
            ob_raw,
            algos,
        )

    out = {
        'generated_at': datetime.now().isoformat(),
        'note': 'Cumulative P&L @ 1 lot per signal. INR for NIFTY ×65, SENSEX ×20.',
        'presets': presets,
        'palette': palette,
        'algos': algos,
        'what_if': {'combos': what_if},
    }

    with open(OUT, 'w') as f:
        json.dump(out, f)

    print(f'Wrote {OUT} — {len(algos)} algos, {len(what_if)} what-if combos')


if __name__ == '__main__':
    main()