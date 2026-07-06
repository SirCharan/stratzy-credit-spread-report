#!/usr/bin/env python3
"""Generate Option Buying strategy guide cards with research bullets + Nifty alignment."""
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
ANALYSIS = ROOT / 'option_buying_analysis.json'
NIFTY_OUT = ROOT / 'nifty_daily.json'
GUIDE_OUT = ROOT / 'option_buying_strategy_guide.json'
API = 'https://stratzy.in/api/web/algo/list'

FAMILIES = [
    {
        'id': 'signal',
        'title': 'Proprietary entry signals',
        'subtitle': 'Unique signal picks CE vs PE and strike. Exit rules vary.',
        'members': [
            "Stratzy's Option Tracker", 'Index Scalper', 'TejNiti', 'SkewHunter',
            'SkewHunter TSL', 'Index Sniper',
        ],
    },
    {
        'id': 'grid',
        'title': 'GRID exit',
        'subtitle': 'Scale in/out at premium grid levels instead of a single stop.',
        'members': ['Burst GRID (30% SL)', 'Vacuum GRID (35% SL)', 'Watchful 33% SL Grid'],
    },
    {
        'id': 'tsl',
        'title': 'Trailing stop loss (TSL)',
        'subtitle': 'Trail stop as premium rises — ride momentum bursts.',
        'members': [
            'Settle-Down 40% TSL', 'Wise-Move 25% TSL', 'Nischay 40% TSL',
            'Only-Calls 40% TSL', 'Safe-Khel 40% TSL', 'Ghar-Aangan 30% TSL',
            'Aaram-Se 30% TSL', 'Aastha 35% TSL', 'Dhyaan 35% TSL',
            'Thrifty 40% TSL', 'Free-Lunch 30% TSL',
        ],
    },
    {
        'id': 'fixed_sl',
        'title': 'Fixed stop loss',
        'subtitle': 'Hard % cap on loss — exit when premium drops X%.',
        'members': [
            'Savdhaan 35% SL', 'Sookshma-Nazar 25% SL', 'Shanti 40% SL',
            'Sahas 40% SL', 'First-Step 25% SL',
        ],
    },
    {
        'id': 'fixed_rr',
        'title': 'Fixed risk-reward',
        'subtitle': 'Target fixed multiple of risk (RR 1:2 or 1:3).',
        'members': [
            'Fixed RR 1:3 (30% SL)', 'Prudent 30%SL FixedRR 1:3',
            'Fortuna 30%SL FixedRR 1:3', 'Equilibrium 25%SL FixedRR 1:3',
            'Aequitas 25%SL FixedRR 1:3', 'Patience 35%SL FixedRR 1:3',
            'Vigil 25%SL FixedRR 1:3', 'Seed-Fund 40% SL FixedRR 1:3',
            'Chhota-Move 30% SL FixedRR 1:2', 'Burst RR 1:2 (25% SL)',
        ],
    },
    {
        'id': 'partial',
        'title': 'Partial target',
        'subtitle': 'Book partial profits early, trail the remainder.',
        'members': [
            'Harbor 33%SL with Partial Target', 'Sunrise 33%SL + Partial Target',
            'Cornerstone 33%SL + Partial Target',
        ],
    },
]

PAIRWISE_HIGHLIGHTS = [
    {
        'from': 'Burst GRID (30% SL)', 'to': 'Vacuum GRID (35% SL)',
        'headline': 'Momentum burst vs volatility vacuum — same GRID exit, different entry',
        'bullets': [
            'Burst enters on momentum expansion; Vacuum fades vol-collapse snaps.',
            'Burst ~3× more trades — higher turnover, more grid levels per month.',
        ],
    },
    {
        'from': 'SkewHunter', 'to': 'SkewHunter TSL',
        'headline': 'Same skew entry — only exit mechanics change',
        'bullets': [
            'Identical skew-hunt signal; TSL adds systematic trailing stop.',
            'Compare regime stats: TSL often more active in 2026.',
        ],
    },
    {
        'from': 'Savdhaan 35% SL', 'to': 'Sookshma-Nazar 25% SL',
        'headline': 'Both fixed SL — width is the main difference',
        'bullets': [
            'Savdhaan uses wider 35% hard stop; Sookshma caps at 25%.',
            'Tighter stop = smaller losses but fewer large winners.',
        ],
    },
    {
        'from': 'Harbor 33%SL with Partial Target', 'to': 'Sunrise 33%SL + Partial Target',
        'headline': 'Same partial-book exit — different entry / PE tilt',
        'bullets': [
            'Both book partial profits then trail the rest.',
            'Check CE/PE mix and bear-day performance to pick between them.',
        ],
    },
    {
        'from': 'Settle-Down 40% TSL', 'to': 'Wise-Move 25% TSL',
        'headline': 'Both TSL — vol-timing vs trail tightness',
        'bullets': [
            'Settle-Down waits for vol to calm; Wise-Move uses tighter 25% trail.',
            'Tighter TSL cuts winners earlier but limits give-back.',
        ],
    },
]

FAMILY_TREND_HINT = {
    'signal': 'hybrid',
    'grid': 'hybrid',
    'tsl': 'trend_following',
    'fixed_sl': 'hybrid',
    'fixed_rr': 'hybrid',
    'partial': 'mean_reverting',
}

EXIT_LABELS = {
    'grid': 'GRID level exits',
    'trailing_sl': 'trailing stop loss',
    'fixed_sl': 'fixed % stop loss',
    'fixed_rr': 'fixed risk-reward target',
    'partial_target': 'partial profit booking + trail',
    'signal': 'signal-based discretionary exit',
    'other': 'proprietary exit rules',
}


def short(name: str) -> str:
    return name.replace("Stratzy's ", '')


def parse_features(name: str) -> dict:
    n = name.lower()
    feats = {'exit': 'signal', 'side': 'both'}
    m = re.search(r'(\d+)%', name)
    if m:
        feats['sl'] = int(m.group(1))
    if 'tsl' in n:
        feats['exit'] = 'trailing_sl'
    elif 'grid' in n:
        feats['exit'] = 'grid'
    elif 'partial' in n or 'target' in n:
        feats['exit'] = 'partial_target'
    elif 'fixedrr' in n.replace(' ', '') or 'rr 1:' in n:
        feats['exit'] = 'fixed_rr'
        rr = re.search(r'1:(\d)', name)
        if rr:
            feats['rr'] = f'1:{rr.group(1)}'
    elif ' sl' in n or '%sl' in n.replace(' ', ''):
        feats['exit'] = 'fixed_sl'
    if 'only-calls' in n or 'only calls' in n:
        feats['side'] = 'ce_only'
    elif 'only-put' in n or 'only put' in n:
        feats['side'] = 'pe_only'
    return feats


def family_for(name: str) -> tuple[str, str, str]:
    for fam in FAMILIES:
        if name in fam['members']:
            return fam['id'], fam['title'], fam['subtitle']
    return 'other', 'Other', 'Algos not in a named exit family.'


def parse_strike(sym: str) -> tuple[int | None, str | None]:
    m = re.search(r'(\d{4,6})(CE|PE)$', sym)
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def classify_moneyness(strike: int, opt_type: str, spot: float) -> str:
    dist = strike - spot
    pct = abs(dist) / spot * 100
    if opt_type == 'CE':
        if dist <= 0:
            return 'ITM' if pct > 0.3 else 'ATM'
        if pct <= 0.5:
            return 'ATM'
        if pct <= 1.5:
            return 'OTM_near'
        return 'OTM_far'
    if dist >= 0:
        return 'ITM' if pct > 0.3 else 'ATM'
    if pct <= 0.5:
        return 'ATM'
    if pct <= 1.5:
        return 'OTM_near'
    return 'OTM_far'


def fetch_api_algos() -> dict:
    with urllib.request.urlopen(API, timeout=30) as resp:
        data = json.load(resp)
    return {
        a['_id']: a for a in data.get('data', [])
        if (a.get('displayCategory') or '').lower() == 'option buying'
    }


def fetch_nifty_daily(start: str, end: str) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit('yfinance required: pip install yfinance')

    end_dt = datetime.strptime(end, '%Y-%m-%d').date() + timedelta(days=5)
    df = yf.download('^NSEI', start=start, end=end_dt.isoformat(), progress=False)
    if df.empty:
        return {}

    if hasattr(df.columns, 'levels'):
        open_col = df['Open']['^NSEI'] if '^NSEI' in df['Open'].columns else df['Open'].iloc[:, 0]
        close_col = df['Close']['^NSEI'] if '^NSEI' in df['Close'].columns else df['Close'].iloc[:, 0]
    else:
        open_col, close_col = df['Open'], df['Close']

    out = {}
    prev_close = None
    for idx in open_col.index:
        iso = idx.strftime('%Y-%m-%d')
        o = float(open_col.loc[idx])
        c = float(close_col.loc[idx])
        ret = ((c - prev_close) / prev_close * 100) if prev_close else 0.0
        out[iso] = {'open': round(o, 2), 'close': round(c, 2), 'day_return_pct': round(ret, 3)}
        prev_close = c
    return out


def day_regime(ret: float) -> str:
    if ret > 0.4:
        return 'bull'
    if ret < -0.4:
        return 'bear'
    return 'sideways'


def analyze_algo(algo: dict, nifty: dict, api: dict) -> dict:
    name = algo['name']
    feats = parse_features(name)
    fam_id, fam_title, _ = family_for(name)
    api_algo = api.get(algo['id'], {})
    live_rows = [r for r in algo['rows'] if not r.get('backtestTrade')]
    ytd_rows = [r for r in live_rows if r['closed'].startswith('2026')]
    inactive_2026 = len(ytd_rows) == 0

    analysis_rows = ytd_rows if ytd_rows else live_rows
    period_label = '2026 YTD' if ytd_rows else 'all-time live'

    moneyness = defaultdict(int)
    regime = {
        'bull': {'trades': 0, 'pts': 0.0, 'wins': 0},
        'bear': {'trades': 0, 'pts': 0.0, 'wins': 0},
        'sideways': {'trades': 0, 'pts': 0.0, 'wins': 0},
    }
    trend_scores = {'ce_with_up': [], 'ce_with_down': [], 'pe_with_up': [], 'pe_with_down': []}
    daily_pnl = defaultdict(float)

    for r in analysis_rows:
        if r['underlying'] != 'NIFTY':
            continue
        buy = next((l for l in r['legs'] if l['transactionType'] == 'BUY'), r['legs'][0])
        strike, opt_type = parse_strike(buy.get('symbol', ''))
        day = r['closed']
        nd = nifty.get(day)
        if nd and strike and opt_type:
            moneyness[classify_moneyness(strike, opt_type, nd['open'])] += 1
            reg = day_regime(nd['day_return_pct'])
            regime[reg]['trades'] += 1
            regime[reg]['pts'] += r['points_net']
            if r['points_net'] > 0:
                regime[reg]['wins'] += 1
            ret = nd['day_return_pct']
            if r['side'] == 'CE':
                (trend_scores['ce_with_up'] if ret > 0 else trend_scores['ce_with_down']).append(r['points_net'])
            elif r['side'] == 'PE':
                (trend_scores['pe_with_up'] if ret > 0 else trend_scores['pe_with_down']).append(r['points_net'])

        daily_pnl[day] += r['points_net']

    total_m = sum(moneyness.values()) or 1
    moneyness_pct = {k: round(100 * v / total_m, 1) for k, v in sorted(moneyness.items())}
    dominant_m = max(moneyness, key=moneyness.get) if moneyness else 'unknown'

    regime_summary = {}
    for k, v in regime.items():
        n = v['trades'] or 0
        regime_summary[k] = {
            'trades': n,
            'avg_pts': round(v['pts'] / n, 1) if n else 0,
            'win_rate': round(100 * v['wins'] / n, 1) if n else 0,
        }

    best_regime = max(regime_summary, key=lambda k: regime_summary[k]['avg_pts']) if any(
        regime_summary[k]['trades'] for k in regime_summary
    ) else 'sideways'

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else 0

    ce_up, ce_down = avg(trend_scores['ce_with_up']), avg(trend_scores['ce_with_down'])
    pe_up, pe_down = avg(trend_scores['pe_with_up']), avg(trend_scores['pe_with_down'])

    trend_score = 0
    if ce_up > ce_down:
        trend_score += 1
    if pe_down > pe_up:
        trend_score += 1
    if ce_down > ce_up:
        trend_score -= 1
    if pe_up > pe_down:
        trend_score -= 1

    if trend_score >= 1:
        trend_label = 'trend_following'
    elif trend_score <= -1:
        trend_label = 'mean_reverting'
    else:
        trend_label = FAMILY_TREND_HINT.get(fam_id, 'hybrid')

    ce_pct, pe_pct = algo['ce_pct'], algo['pe_pct']
    live = algo.get('live') or {}
    months = max(len(algo.get('monthly', {})), 1)
    trades_pm = round(live.get('trades', 0) / months, 1)
    ytd = algo.get('ytd_2026') or {}

    if ce_pct >= 75:
        side_note = 'call-heavy'
    elif pe_pct >= 75:
        side_note = 'put-heavy'
    elif abs(ce_pct - pe_pct) <= 15:
        side_note = 'balanced CE/PE'
    else:
        side_note = 'mixed directional'

    if best_regime == 'bull' and ce_pct >= 55:
        market_fit = 'bull_market'
        market_desc = 'Performs best when Nifty rallies — call exposure aligns with up-days.'
    elif best_regime == 'bear' and pe_pct >= 55:
        market_fit = 'bear_market'
        market_desc = 'Performs best when Nifty sells off — put exposure aligns with down-days.'
    elif best_regime == 'sideways':
        market_fit = 'sideways_market'
        market_desc = 'Grinds best on range-bound days — less dependent on directional trend.'
    elif best_regime == 'bull':
        market_fit = 'bull_day_alpha'
        market_desc = 'Wins on up-days despite mixed CE/PE — signal catches intraday momentum.'
    elif best_regime == 'bear':
        market_fit = 'bear_day_alpha'
        market_desc = 'Wins on down-days — often fades rallies or trades vol expansion on selloffs.'
    else:
        market_fit = 'all_weather'
        market_desc = 'No strong regime preference in the data window.'

    moneyness_labels = {
        'ATM': 'at-the-money (±0.5% of Nifty open)',
        'OTM_near': 'slightly out-of-the-money (0.5–1.5%)',
        'OTM_far': 'deep out-of-the-money (>1.5%)',
        'ITM': 'in-the-money (higher delta, more intrinsic value)',
    }
    m_sorted = sorted(moneyness_pct.items(), key=lambda x: -x[1])
    moneyness_desc = ', '.join(f"{v}% {moneyness_labels.get(k, k)}" for k, v in m_sorted[:3])

    exit_style = EXIT_LABELS.get(feats.get('exit'), feats.get('exit', 'unknown'))
    freq_api = api_algo.get('avgFrequency') or 'intraday'

    trend_desc = {
        'trend_following': 'Trend-following — CE trades do better on up-days, PE on down-days.',
        'mean_reverting': 'Mean-reverting — often buys calls after dips or puts after spikes.',
        'hybrid': 'Hybrid — mixes momentum bursts with fade setups depending on signal.',
    }[trend_label]

    regime_line = (
        f"Best on {best_regime} days ({regime_summary[best_regime]['avg_pts']:+.1f} pts avg, "
        f"{period_label}): bull {regime_summary['bull']['avg_pts']:+.1f}, "
        f"sideways {regime_summary['sideways']['avg_pts']:+.1f}, "
        f"bear {regime_summary['bear']['avg_pts']:+.1f}"
    )

    bullets = [
        'Long single-leg option buyer — buys one CE or PE, profits when premium rises (not a credit spread).',
        f"Strike selection ({period_label}): {moneyness_desc or 'insufficient NIFTY strike data'}.",
        f"Trade frequency: ~{trades_pm} trades/month (Stratzy lists: \"{freq_api}\").",
        f"Exit mechanic: {exit_style}" + (f" ({feats['sl']}% stop)" if feats.get('sl') else '') + '.',
        trend_desc,
        f"Direction mix: {ce_pct}% calls / {pe_pct}% puts ({side_note}).",
        regime_line,
        market_desc,
    ]

    cum = 0.0
    cum_curve = []
    for d in sorted(daily_pnl):
        cum += daily_pnl[d]
        cum_curve.append({'x': d, 'y': round(cum, 1)})

    nifty_curve = []
    base = None
    for d in sorted(daily_pnl):
        if d in nifty and nifty[d]['close']:
            if base is None:
                base = nifty[d]['close']
            nifty_curve.append({'x': d, 'y': round(100 * nifty[d]['close'] / base, 2)})

    return {
        'id': algo['id'],
        'name': name,
        'short_name': short(name),
        'family_id': fam_id,
        'family_title': fam_title,
        'inactive_2026': inactive_2026,
        'underlying': algo.get('underlying', 'NIFTY'),
        'rank_all': algo.get('rank'),
        'ytd_2026_pts': ytd.get('total_points', 0),
        'all_time_pts': live.get('total_points', 0),
        'ce_pct': ce_pct,
        'pe_pct': pe_pct,
        'trades_per_month': trades_pm,
        'avg_frequency': freq_api,
        'exit_style': feats.get('exit'),
        'trend_label': trend_label,
        'market_fit': market_fit,
        'bullets': bullets,
        'metrics': {
            'moneyness_pct': moneyness_pct,
            'dominant_moneyness': dominant_m,
            'regime': regime_summary,
            'best_regime': best_regime,
            'period_label': period_label,
            'trend_score': trend_score,
        },
        'nifty_overlay': {
            'daily_pnl': {d: round(v, 1) for d, v in sorted(daily_pnl.items())},
            'cum_pnl': cum_curve[-60:],
            'nifty_indexed': nifty_curve[-60:],
        },
    }


def main():
    with open(ANALYSIS) as f:
        analyses = json.load(f)

    live_algos = [a for a in analyses if a.get('live') and a['live'].get('trades', 0) > 0]
    live_algos.sort(key=lambda a: a.get('rank', 999))

    all_dates = [
        r['closed'] for a in live_algos for r in a['rows']
        if not r.get('backtestTrade') and r['closed']
    ]
    start, end = min(all_dates), max(all_dates)
    nifty = fetch_nifty_daily(start, end)

    with open(NIFTY_OUT, 'w') as f:
        json.dump(nifty, f, indent=2)

    api = fetch_api_algos()
    cards = [analyze_algo(a, nifty, api) for a in live_algos]

    families_out = []
    for fam in FAMILIES:
        members = [c['short_name'] for c in cards if c['family_id'] == fam['id']]
        if members:
            families_out.append({**fam, 'member_count': len(members), 'members': members})

    guide = {
        'generated_at': datetime.now().isoformat(),
        'scope': 'all_38_live_option_buying',
        'algo_count': len(cards),
        'methodology': {
            'strategy_type': 'Inferred from scraped pastAdvices legs (BUY CE/PE only).',
            'moneyness': 'Strike vs Nifty OPEN on trade date (±0.5% ATM, 0.5–1.5% near-OTM, >1.5% far-OTM).',
            'regime': 'Bull/bear/sideways from Nifty daily close-to-close return (±0.4% thresholds).',
            'trend': 'Compares CE/PE PnL on up-days vs down-days; cross-checked with exit family.',
            'not_stratzy_copy': 'Bullets are research-generated; Stratzy marketing "about" text is not used.',
        },
        'families': families_out,
        'algos': cards,
        'pairwise_highlights': PAIRWISE_HIGHLIGHTS,
    }

    with open(GUIDE_OUT, 'w') as f:
        json.dump(guide, f, indent=2)

    print(f'Wrote {GUIDE_OUT} — {len(cards)} algos, {len(nifty)} Nifty days')


if __name__ == '__main__':
    main()