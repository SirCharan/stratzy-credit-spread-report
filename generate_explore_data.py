#!/usr/bin/env python3
"""Build unified Explore data + Stratzy headline metrics for all research algos."""
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
CS_REPORT = ROOT / 'report_data.json'
OB_REPORT = ROOT / 'option_buying_report_data.json'
OB_DIFF = ROOT / 'option_buying_diff.json'
CS_DIFF = ROOT / 'diff_data.json'
HEADLINES_OUT = ROOT / 'stratzy_headlines.json'
EXPLORE_OUT = ROOT / 'explore_data.json'
EXPLORE_DIFF_OUT = ROOT / 'explore_diff.json'
API = 'https://stratzy.in/api/web/algo/list'


def fetch_api_algos():
    with urllib.request.urlopen(API, timeout=30) as resp:
        return json.load(resp).get('data', [])


def stratzy_fields(api_algo):
    if not api_algo:
        return {}
    return {
        'one_year_pnl_pct': api_algo.get('oneYearPnl'),
        'past_return_pct': api_algo.get('pastReturn'),
        'three_month_pnl_pct': api_algo.get('threeMonthPnl'),
        'six_month_pnl_pct': api_algo.get('sixMonthPnl'),
        'min_capital': api_algo.get('minimumCapital'),
        'max_capital': api_algo.get('maximumCapital'),
        'display_category': api_algo.get('displayCategory'),
        'win_ratio_pct': api_algo.get('winRatio'),
        'drawdown_pct': api_algo.get('drawDown'),
        'max_drawdown_pct': api_algo.get('maxDrawdown'),
    }


def normalize_cs(algo, api_by_id):
    api = api_by_id.get(algo['id'], {})
    st = stratzy_fields(api)
    at = algo['all_time']
    ytd = algo['ytd_2026']
    return {
        'id': algo['id'],
        'name': algo['name'],
        'short_name': algo['name'].replace(' Credit Spread Overnight', '').replace(' Credit Spread Expiry', ' Expiry').replace(' Credit Spread', ''),
        'category': 'credit_spread',
        'display_category': st.get('display_category') or 'Credit Spread',
        'underlying': algo['underlying'],
        'style': algo['style'],
        'style_label': algo.get('style_label'),
        'research_rank_all': algo['rank'],
        'research_rank_2026': None,
        'all_time_pts': at['net_points'],
        'all_time_inr': at['net_inr'],
        'all_time_trades': at['trades'],
        'all_time_wr': at['win_rate'],
        'ytd_2026_pts': ytd['net_points'],
        'ytd_2026_inr': ytd['net_inr'],
        'ytd_2026_trades': ytd['trades'],
        'ytd_2026_wr': ytd['win_rate'],
        'detail_url': 'index.html',
        'in_research': True,
        **st,
    }


def normalize_ob(algo, api_by_id):
    api = api_by_id.get(algo['id'], {})
    st = stratzy_fields(api)
    live = algo.get('live') or algo.get('all') or {}
    ytd = algo.get('ytd_2026') or {}
    return {
        'id': algo['id'],
        'name': algo['name'],
        'short_name': algo['name'].replace("Stratzy's ", ''),
        'category': 'option_buying',
        'display_category': st.get('display_category') or 'Option Buying',
        'underlying': algo.get('underlying', 'NIFTY'),
        'style': (algo.get('style') or {}).get('exit_style'),
        'style_label': (algo.get('style') or {}).get('exit_style'),
        'research_rank_all': algo['rank'],
        'research_rank_2026': None,
        'all_time_pts': live.get('total_points'),
        'all_time_inr': live.get('total_inr'),
        'all_time_trades': live.get('trades'),
        'all_time_wr': live.get('win_rate'),
        'ytd_2026_pts': ytd.get('total_points'),
        'ytd_2026_inr': ytd.get('total_inr'),
        'ytd_2026_trades': ytd.get('trades'),
        'ytd_2026_wr': ytd.get('win_rate'),
        'detail_url': 'option-buying.html',
        'in_research': True,
        **st,
    }


def index_ob_members(ob_diff):
    by_name = {}
    family_of = {}
    pairwise_index = {}
    families_slim = []
    for fam in ob_diff.get('families', []):
        members = []
        for m in fam.get('members', []):
            by_name[m['name']] = {**m, 'family_id': fam['id'], 'family_title': fam['title']}
            family_of[m['name']] = fam['id']
            members.append({
                'name': m['name'],
                'short': m['short'],
                'one_liner': m.get('one_liner'),
                'rank': m.get('rank'),
                'ce_pct': m.get('ce_pct'),
                'pe_pct': m.get('pe_pct'),
                'all_pts': m.get('all_pts'),
                'ytd_pts': m.get('ytd_pts'),
                'win_rate': m.get('win_rate'),
                'avg_win': m.get('avg_win'),
                'avg_loss': m.get('avg_loss'),
                'trades_pm': m.get('trades_pm'),
                'min_capital': m.get('min_capital'),
            })
        for p in fam.get('pairwise', []):
            pairwise_index[(p['from'], p['to'])] = p
        families_slim.append({
            'id': fam['id'],
            'title': fam['title'],
            'subtitle': fam.get('subtitle'),
            'members': members,
            'pairwise': fam.get('pairwise', []),
        })
    return by_name, family_of, pairwise_index, families_slim


def index_cs_members(cs_diff):
    by_name = {}
    families_slim = []
    for fam in cs_diff.get('families', []):
        members = []
        for m in fam.get('members', []):
            by_name[m['name']] = {**m, 'family_id': fam['id'], 'family_title': fam['title']}
            members.append(m)
        families_slim.append({
            'id': fam['id'],
            'title': fam['title'],
            'subtitle': fam.get('subtitle'),
            'diff_key': fam.get('diff_key'),
            'members': members,
        })
    return by_name, families_slim


def lookup_pairwise(pairwise_index, a_name, b_name):
    return pairwise_index.get((a_name, b_name)) or pairwise_index.get((b_name, a_name))


def parse_ob_features(name):
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


def ob_exit_label(feats):
    labels = {
        'grid': 'GRID levels',
        'trailing_sl': 'trailing stop',
        'fixed_sl': 'fixed % stop',
        'fixed_rr': f"fixed RR {feats.get('rr', '1:3')}",
        'partial_target': 'partial profit + trail',
        'signal': 'signal-based exit',
    }
    return labels.get(feats.get('exit'), feats.get('exit', 'unknown'))


def invert_pairwise_bullets(existing, higher, lower):
    """Flip pairwise bullets when stored order is lower→higher vs ladder higher→lower."""
    if existing['from'] == higher['name']:
        return list(existing.get('bullets', []))
    bullets = []
    for b in existing.get('bullets', []):
        text = b
        for old, new in [
            (existing['from_short'], 'TEMP_A'),
            (existing['to_short'], existing['from_short']),
            ('TEMP_A', existing['to_short']),
        ]:
            text = text.replace(old, new)
        bullets.append(text)
    return bullets


def cross_family_bullets(higher, lower, meta_h, meta_l):
    """Extra bullets when ladder neighbours are in different OB families."""
    bullets = []
    pf, nf = parse_ob_features(higher['name']), parse_ob_features(lower['name'])
    if pf.get('exit') != nf.get('exit'):
        bullets.append(
            f"Exit mechanics: {higher['short_name']} uses {ob_exit_label(pf)}; "
            f"{lower['short_name']} uses {ob_exit_label(nf)}."
        )
    elif pf.get('sl') and nf.get('sl') and pf['sl'] != nf['sl']:
        tighter = lower['short_name'] if nf['sl'] < pf['sl'] else higher['short_name']
        bullets.append(
            f"Stop width: {pf['sl']}% on {higher['short_name']} vs {nf['sl']}% on {lower['short_name']} "
            f"— {'tighter stop on ' + tighter}."
        )
    if pf.get('side') != nf.get('side'):
        side_txt = {'ce_only': 'calls only', 'pe_only': 'puts only', 'both': 'both sides'}
        bullets.append(
            f"Side filter: {higher['short_name']} = {side_txt.get(pf['side'], pf['side'])}; "
            f"{lower['short_name']} = {side_txt.get(nf['side'], nf['side'])}."
        )
    ce_h, ce_l = meta_h.get('ce_pct'), meta_l.get('ce_pct')
    if ce_h is not None and ce_l is not None and abs(ce_h - ce_l) >= 12:
        bullets.append(
            f"Directional mix: {higher['short_name']} {ce_h}% CE / {meta_h.get('pe_pct')}% PE vs "
            f"{lower['short_name']} {ce_l}% CE / {meta_l.get('pe_pct')}% PE."
        )
    wr_h, wr_l = meta_h.get('win_rate'), meta_l.get('win_rate')
    if wr_h is not None and wr_l is not None:
        wr_d = round(wr_l - wr_h, 1)
        bullets.append(
            f"Trade WR: {lower['short_name']} {wr_l}% vs {higher['short_name']} {wr_h}% "
            f"({wr_d:+.1f} pp)."
        )
    if meta_h.get('avg_win') and meta_l.get('avg_win'):
        bullets.append(
            f"Avg win/loss (pts): {higher['short_name']} +{meta_h['avg_win']}/{meta_h.get('avg_loss')} vs "
            f"{lower['short_name']} +{meta_l['avg_win']}/{meta_l.get('avg_loss')}."
        )
    tpm_h, tpm_l = meta_h.get('trades_pm'), meta_l.get('trades_pm')
    if tpm_h and tpm_l and abs(tpm_l - tpm_h) >= 1.5:
        bullets.append(
            f"Activity: {lower['short_name']} {tpm_l}/mo vs {higher['short_name']} {tpm_h}/mo."
        )
    fam_h = higher.get('ob_family_title') or meta_h.get('family_title')
    fam_l = lower.get('ob_family_title') or meta_l.get('family_title')
    if fam_h and fam_l and fam_h != fam_l:
        bullets.append(f"Family: {higher['short_name']} = {fam_h}; {lower['short_name']} = {fam_l}.")
    return bullets


def build_ladder_pair(higher, lower, pairwise_index, family_of, category, ob_by_name=None):
    """Compare higher-ranked (better 1Y) vs next algo on ladder."""
    h_name, l_name = higher['name'], lower['name']
    existing = lookup_pairwise(pairwise_index, h_name, l_name)

    shared_family = None
    if family_of.get(h_name) and family_of.get(h_name) == family_of.get(l_name):
        shared_family = family_of[h_name]

    bullets = []
    meta_h = (ob_by_name or {}).get(h_name, {})
    meta_l = (ob_by_name or {}).get(l_name, {})
    if existing:
        headline = existing.get('headline', '')
        bullets = invert_pairwise_bullets(existing, higher, lower)
    else:
        headline = f"{higher['short_name']} vs {lower['short_name']} — Stratzy 1Y neighbours"
        if shared_family:
            headline = f"same {shared_family} family on Explore ladder — how #{higher['rank_stratzy_1y']} beats #{lower['rank_stratzy_1y']}"
        elif category == 'option_buying' and not shared_family:
            pf, nf = parse_ob_features(h_name), parse_ob_features(l_name)
            headline = f"{ob_exit_label(pf)} vs {ob_exit_label(nf)} — Explore 1Y #{higher['rank_stratzy_1y']} vs #{lower['rank_stratzy_1y']}"
            bullets.extend(cross_family_bullets(higher, lower, meta_h, meta_l))

    ytd_h = higher.get('ytd_2026_pts') or 0
    ytd_l = lower.get('ytd_2026_pts') or 0
    stratzy_line = (
        f"Stratzy 1Y: {higher['short_name']} {higher.get('one_year_pnl_pct')}% "
        f"(#{higher.get('rank_stratzy_1y')}) vs {lower['short_name']} {lower.get('one_year_pnl_pct')}% "
        f"(#{lower.get('rank_stratzy_1y')}) — {round((higher.get('one_year_pnl_pct') or 0) - (lower.get('one_year_pnl_pct') or 0), 1)} pp gap."
    )
    if stratzy_line not in bullets:
        bullets.insert(0, stratzy_line)

    pts_line = (
        f"1-lot 2026 pts: {higher['short_name']} {ytd_h:+.1f} vs {lower['short_name']} {ytd_l:+.1f} "
        f"({ytd_h - ytd_l:+.1f} pts gap) — capital % and premium pts can diverge."
    )
    if not any('1-lot 2026' in b for b in bullets):
        bullets.append(pts_line)

    if higher.get('min_capital') and lower.get('min_capital') and higher['min_capital'] != lower['min_capital']:
        cap_line = f"Min capital: ₹{higher['min_capital']:,} vs ₹{lower['min_capital']:,}."
        if not any('Min capital' in b for b in bullets):
            bullets.append(cap_line)

    if category == 'credit_spread':
        if higher.get('style_label') and lower.get('style_label') and higher['style'] != lower['style']:
            bullets.append(f"Hold style: {higher['short_name']} = {higher.get('style_label', higher['style'])}; {lower['short_name']} = {lower.get('style_label', lower['style'])}.")

    return {
        'higher_rank': higher.get('rank_stratzy_1y'),
        'lower_rank': lower.get('rank_stratzy_1y'),
        'from': h_name,
        'to': l_name,
        'from_short': higher['short_name'],
        'to_short': lower['short_name'],
        'headline': headline,
        'bullets': bullets[:8],
        'shared_family': shared_family,
        'category': category,
    }


def build_category_ladder(algos, pairwise_index, family_of, category, ob_by_name=None):
    ranked = sorted(
        [a for a in algos if a.get('category') == category and a.get('one_year_pnl_pct') is not None],
        key=lambda a: a['one_year_pnl_pct'],
        reverse=True,
    )
    return [
        build_ladder_pair(
            ranked[i], ranked[i + 1], pairwise_index, family_of, category,
            ob_by_name=ob_by_name if category == 'option_buying' else None,
        )
        for i in range(len(ranked) - 1)
    ]


def enrich_ob_families(ob_families, merged):
    by_name = {a['name']: a for a in merged if a['category'] == 'option_buying'}
    for fam in ob_families:
        for m in fam.get('members', []):
            algo = by_name.get(m['name'], {})
            m['stratzy_1y_pct'] = algo.get('one_year_pnl_pct')
            m['stratzy_1y_rank'] = algo.get('rank_stratzy_1y')
            m['family_id'] = fam['id']
    return ob_families


def build_ob_comparison_table(merged):
    ob = [a for a in merged if a['category'] == 'option_buying']
    ranked = sorted(ob, key=lambda a: a.get('one_year_pnl_pct') or -1e9, reverse=True)
    rows = []
    for a in ranked:
        feats = parse_ob_features(a['name'])
        rows.append({
            'id': a['id'],
            'name': a['name'],
            'short_name': a['short_name'],
            'stratzy_1y_rank': a.get('rank_stratzy_1y'),
            'stratzy_1y_pct': a.get('one_year_pnl_pct'),
            'family_id': a.get('ob_family_id'),
            'family_title': a.get('ob_family_title'),
            'exit_style': ob_exit_label(feats),
            'exit_key': feats.get('exit'),
            'ce_pct': a.get('ce_pct'),
            'pe_pct': a.get('pe_pct'),
            'ytd_2026_pts': a.get('ytd_2026_pts'),
            'all_time_pts': a.get('all_time_pts'),
            'win_rate': a.get('all_time_wr'),
            'min_capital': a.get('min_capital'),
            'one_liner': a.get('one_liner'),
            'research_rank_all': a.get('research_rank_all'),
            'research_rank_2026': a.get('research_rank_2026'),
        })
    return rows


def attach_ranks(algos, key, field):
    ranked = sorted(
        [a for a in algos if a.get(field) is not None],
        key=lambda a: a[field],
        reverse=True,
    )
    for i, a in enumerate(ranked, 1):
        a[key] = i
    for a in algos:
        if a.get(field) is None:
            a[key] = None


def main():
    api_algos = fetch_api_algos()
    api_by_id = {a['_id']: a for a in api_algos}

    cs = json.load(open(CS_REPORT))
    ob = json.load(open(OB_REPORT))
    ob_diff = json.load(open(OB_DIFF)) if OB_DIFF.exists() else {'families': []}
    cs_diff = json.load(open(CS_DIFF)) if CS_DIFF.exists() else {'families': []}
    ob_by_name, ob_family_of, ob_pairwise_index, ob_families = index_ob_members(ob_diff)
    cs_by_name, cs_families = index_cs_members(cs_diff)

    merged = []
    for a in cs['algos']:
        merged.append(normalize_cs(a, api_by_id))
    for a in ob['algos']:
        entry = normalize_ob(a, api_by_id)
        meta = ob_by_name.get(entry['name'], {})
        entry['one_liner'] = meta.get('one_liner')
        entry['ce_pct'] = meta.get('ce_pct')
        entry['pe_pct'] = meta.get('pe_pct')
        entry['ob_family_id'] = ob_family_of.get(entry['name'])
        entry['ob_family_title'] = meta.get('family_title')
        merged.append(entry)

    for a in merged:
        if a['category'] == 'credit_spread':
            meta = cs_by_name.get(a['name'], {})
            a['one_liner'] = meta.get('one_liner')
            a['ce_pct'] = meta.get('ce_pct')
            a['pe_pct'] = meta.get('pe_pct')
            a['cs_family_id'] = meta.get('family_id')
            a['cs_family_title'] = meta.get('family_title')

    attach_ranks(merged, 'rank_stratzy_1y', 'one_year_pnl_pct')
    attach_ranks(merged, 'rank_2026_pts', 'ytd_2026_pts')
    attach_ranks(merged, 'rank_all_pts', 'all_time_pts')

    for a in merged:
        ytd_sorted = sorted(merged, key=lambda x: x.get('ytd_2026_pts') or -1e9, reverse=True)
        for i, x in enumerate(ytd_sorted, 1):
            if x['id'] == a['id']:
                a['research_rank_2026'] = i
                break

    merged_by_1y = sorted(
        merged,
        key=lambda a: a.get('one_year_pnl_pct') if a.get('one_year_pnl_pct') is not None else -1e9,
        reverse=True,
    )

    headlines = {
        'generated_at': datetime.now().isoformat(),
        'source': API,
        'by_id': {a['id']: stratzy_fields(api_by_id[a['id']]) for a in merged if a['id'] in api_by_id},
        'by_name': {a['name']: stratzy_fields(api_by_id.get(a['id'])) for a in merged},
    }

    explore = {
        'generated_at': datetime.now().isoformat(),
        'note': (
            'Unified Explore view: merges credit-spread + option-buying research algos. '
            'Default sort matches Stratzy Explore (oneYearPnl %). '
            '1-lot pts are from scraped pastAdvices — different metric than Stratzy capital %.'
        ),
        'summary': {
            'credit_spread_count': len(cs['algos']),
            'option_buying_count': len(ob['algos']),
            'total': len(merged),
            'with_stratzy_1y': sum(1 for a in merged if a.get('one_year_pnl_pct') is not None),
        },
        'algos': merged_by_1y,
    }

    ob_families = enrich_ob_families(ob_families, merged)
    ob_ladder = build_category_ladder(
        merged, ob_pairwise_index, ob_family_of, 'option_buying', ob_by_name=ob_by_name,
    )

    explore_diff = {
        'generated_at': datetime.now().isoformat(),
        'vs_credit_spread': ob_diff.get('vs_credit_spread'),
        'option_buying': {
            'comparison_table': build_ob_comparison_table(merged),
            'families': ob_families,
            'stratzy_1y_ladder': ob_ladder,
            'ladder_count': len(ob_ladder),
            'family_count': len(ob_families),
        },
        'credit_spread': {
            'families': cs_families,
            'stratzy_1y_ladder': build_category_ladder(merged, {}, {}, 'credit_spread'),
        },
    }

    HEADLINES_OUT.write_text(json.dumps(headlines, indent=2))
    EXPLORE_OUT.write_text(json.dumps(explore, indent=2))
    EXPLORE_DIFF_OUT.write_text(json.dumps(explore_diff, indent=2))
    print(f'Wrote {HEADLINES_OUT} ({len(headlines["by_id"])} algos)')
    print(f'Wrote {EXPLORE_OUT}')
    print(f'Wrote {EXPLORE_DIFF_OUT} — OB ladder {len(explore_diff["option_buying"]["stratzy_1y_ladder"])} pairs, '
          f'{len(ob_families)} OB families')
    print('\nTop 10 by Stratzy 1Y % (research universe):')
    for a in merged_by_1y[:10]:
        print(f"  #{a.get('rank_stratzy_1y','?'):>2} {a.get('one_year_pnl_pct','—'):>7}% | {a['display_category'][:14]:<14} | {a['short_name'][:40]}")


if __name__ == '__main__':
    main()