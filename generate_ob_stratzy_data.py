#!/usr/bin/env python3
"""Build Stratzy-style option buying view data (capital curve, timeline %, lots)."""
import json
import statistics
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).parent / 'option_buying_stratzy.json'
ANALYSIS = Path(__file__).parent / 'option_buying_analysis.json'
GUIDE = Path(__file__).parent / 'option_buying_strategy_guide.json'
API = 'https://stratzy.in/api/web/algo/list'


def dmy_to_iso(dmy):
    d, m, y = dmy.split('/')
    return f'{y}-{m}-{d}'


def iso_to_dmy(iso):
    y, m, d = iso.split('-')
    return f'{d}/{m}/{y}'


def fetch_algos():
    with urllib.request.urlopen(API, timeout=30) as resp:
        data = json.load(resp)
    return {a['_id']: a for a in data.get('data', []) if (a.get('displayCategory') or '').lower() == 'option buying'}


def lots_stats(rows):
    traded = [r['lots_traded'] for r in rows if r.get('lots_traded')]
    max_lots = [r['max_lots'] for r in rows if r.get('max_lots')]
    mults = [r['multiplier'] for r in rows if r.get('multiplier')]
    margins = [r['margin'] for r in rows if r.get('margin')]
    cap_pcts = [r['advice_capital_pct'] for r in rows if r.get('advice_capital_pct') is not None]
    return {
        'avg_lots_traded': round(statistics.mean(traded), 1) if traded else None,
        'max_lots_seen': max(traded) if traded else None,
        'avg_max_lots': round(statistics.mean(max_lots), 1) if max_lots else None,
        'total_lots_traded': int(sum(traded)) if traded else 0,
        'lot_size': round(statistics.mode(mults)) if mults else None,
        'lot_sizes_seen': sorted(set(mults)),
        'avg_margin': round(statistics.mean(margins)) if margins else None,
        'avg_capital_pct_per_trade': round(statistics.mean(cap_pcts), 1) if cap_pcts else None,
    }


def build_performance_curve(performance, chart_base):
    if not performance:
        return [], []
    dates = sorted(performance.keys(), key=lambda x: datetime.strptime(x, '%d/%m/%Y'))
    run = 0.0
    equity = []
    timeline = []
    for d in dates:
        day_pct = float(performance[d])
        run += day_pct
        equity.append({
            'x': dmy_to_iso(d),
            'y': round(chart_base * (1 + run / 100), 2),
            'cum_pct': round(run, 4),
            'day_pct': round(day_pct, 4),
        })
        timeline.append({
            'x': dmy_to_iso(d),
            'y': round(day_pct, 4),
        })
    return equity, timeline


def build_pts_curve(rows):
    by_day = {}
    for r in rows:
        by_day[r['closed']] = by_day.get(r['closed'], 0) + r['points_net']
    if not by_day:
        return []
    start = min(by_day)
    end = max(by_day)
    d = datetime.strptime(start, '%Y-%m-%d').date()
    end_d = datetime.strptime(end, '%Y-%m-%d').date()
    cum = 0.0
    out = []
    while d <= end_d:
        iso = d.isoformat()
        if iso in by_day:
            cum += by_day[iso]
            out.append({'x': iso, 'y': round(cum, 2), 'day_pts': round(by_day[iso], 2)})
        d += timedelta(days=1)
    return out


def max_drawdown(curve):
    if not curve:
        return None
    peak = float('-inf')
    max_dd = 0.0
    for p in curve:
        peak = max(peak, p['y'])
        max_dd = max(max_dd, peak - p['y'])
    return round(max_dd, 2)


def trade_rows(rows):
    out = []
    for r in rows:
        out.append({
            'date': r['closed'],
            'name': r.get('name', ''),
            'side': r.get('side'),
            'points': r.get('points_net'),
            'signal_inr': round(r.get('signalPnl', 0), 2),
            'lots_traded': r.get('lots_traded'),
            'max_lots': r.get('max_lots'),
            'lot_size': r.get('multiplier'),
            'margin': r.get('margin'),
            'capital_pct': r.get('advice_capital_pct'),
            'day_pct': r.get('signal_pnl_pct'),
            'entry': r.get('entry_premium'),
            'exit': r.get('exit_premium'),
        })
    return out


def build_strategy_block(guide_entry, min_cap):
    if not guide_entry:
        return None
    m = guide_entry.get('metrics') or {}
    return {
        'bullets': guide_entry.get('bullets', []),
        'trend_label': guide_entry.get('trend_label'),
        'market_fit': guide_entry.get('market_fit'),
        'family_id': guide_entry.get('family_id'),
        'family_title': guide_entry.get('family_title'),
        'ce_pct': guide_entry.get('ce_pct'),
        'pe_pct': guide_entry.get('pe_pct'),
        'trades_per_month': guide_entry.get('trades_per_month'),
        'avg_frequency': guide_entry.get('avg_frequency'),
        'inactive_2026': guide_entry.get('inactive_2026', False),
        'dominant_moneyness': m.get('dominant_moneyness'),
        'moneyness_pct': m.get('moneyness_pct', {}),
        'regime': m.get('regime', {}),
        'best_regime': m.get('best_regime'),
        'period_label': m.get('period_label'),
        'investment_basis_inr': min_cap,
    }


def build_algo(analysis, api_algo, guide_entry=None):
    rows = [r for r in analysis.get('rows', []) if not r.get('backtestTrade')]
    perf = (api_algo or {}).get('performance') or {}
    min_cap = (api_algo or {}).get('minimumCapital') or analysis.get('min_capital')
    avg_cap = (api_algo or {}).get('avgCapital')
    max_cap = (api_algo or {}).get('maximumCapital')
    chart_base = max_cap or avg_cap or min_cap or 300000
    invest_base = min_cap or chart_base

    equity, timeline = build_performance_curve(perf, chart_base)
    equity_min, _ = build_performance_curve(perf, invest_base)
    pts_curve = build_pts_curve(rows)
    lots = lots_stats(rows)

    live = analysis.get('live') or {}
    ytd = analysis.get('ytd_2026') or {}

    return {
        'id': analysis['id'],
        'name': analysis['name'],
        'short': analysis['name'].replace("Stratzy's ", ''),
        'underlying': analysis.get('underlying', 'NIFTY'),
        'category': 'Options',
        'risk': analysis.get('risk'),
        'live_since': (analysis.get('liveSince') or '')[:10],
        'rank_all': analysis.get('rank'),
        'capital': {
            'minimum': min_cap,
            'average': avg_cap,
            'maximum': max_cap,
            'chart_base': chart_base,
            'check_investments': (api_algo or {}).get('checkInvestments'),
        },
        'lots': lots,
        'stratzy_headline': {
            'past_return_pct': (api_algo or {}).get('pastReturn'),
            'one_year_pnl_pct': (api_algo or {}).get('oneYearPnl'),
            'drawdown_pct': (api_algo or {}).get('drawDown'),
            'max_drawdown_pct': (api_algo or {}).get('maxDrawdown'),
            'win_ratio': (api_algo or {}).get('winRatio'),
            'cagr': (api_algo or {}).get('cagr'),
        },
        'performance': {
            'equity_inr': equity,
            'equity_min_inr': equity_min,
            'timeline_pct': timeline,
            'pts_1lot': pts_curve,
            'max_dd_inr': max_drawdown(equity),
            'max_dd_min_inr': max_drawdown(equity_min),
            'max_dd_pts': max_drawdown(pts_curve),
            'final_equity_inr': equity[-1]['y'] if equity else None,
            'final_equity_min_inr': equity_min[-1]['y'] if equity_min else None,
            'final_cum_pct': equity[-1]['cum_pct'] if equity else None,
            'final_pts_1lot': pts_curve[-1]['y'] if pts_curve else None,
        },
        'summary': {
            'all': live,
            'ytd_2026': ytd,
            'ytd_pts': ytd.get('total_points', 0) if ytd else 0,
        },
        'strategy': build_strategy_block(guide_entry, invest_base),
        'trades': trade_rows(rows),
    }


def main():
    api_by_id = fetch_algos()
    analyses = json.load(open(ANALYSIS))
    guide_by_id = {}
    if GUIDE.exists():
        guide_by_id = {g['id']: g for g in json.load(open(GUIDE)).get('algos', [])}

    live = [a for a in analyses if a.get('live') and a['live'].get('trades', 0) > 0]
    live.sort(
        key=lambda a: (
            -(a.get('ytd_2026') or {}).get('total_points', 0),
            -(a.get('live') or {}).get('total_points', 0),
        )
    )

    algos = []
    for a in live:
        algos.append(build_algo(a, api_by_id.get(a['id']), guide_by_id.get(a['id'])))

    payload = {
        'generated_at': datetime.now().isoformat(),
        'algo_count': len(algos),
        'note': (
            'Stratzy equity curve = chart_base_inr × (1 + cumulative daily performance% / 100). '
            'equity_min_inr uses minimumCapital per algo. '
            'strategy block = research bullets from option_buying_strategy_guide.json. '
            'pts_1lot = premium points @ 1 exchange lot from scraped trades.'
        ),
        'algos': algos,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f'Wrote {OUT} ({len(algos)} algos)')
    burst = next((x for x in algos if x['id'] == '685848b09edddcb829103b9b'), None)
    if burst:
        print(
            f"Burst RR: min ₹{burst['capital']['minimum']:,}, "
            f"final @ min ₹{burst['performance']['final_equity_min_inr']:,.0f}, "
            f"market_fit={burst['strategy']['market_fit']}"
        )


if __name__ == '__main__':
    main()