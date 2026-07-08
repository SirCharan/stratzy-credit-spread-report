export const meta = {
  name: 'stratzy-algo-insights',
  description: 'Plain-English AI research profile for each deep-data Stratzy algo (generate + adversarial verify)',
  phases: [
    { title: 'Generate', detail: 'one agent per algo reads its facts file, writes judgment fields' },
    { title: 'Verify', detail: 'adversarial fact-check vs the source facts' },
  ],
};

// The workflow sandbox has no filesystem access, so agents Read each algo's small facts file
// (absolute path in the index passed as `args`). Agents emit ONLY judgment fields — the
// deterministic numbers (win/loss, regime buckets, neighbours, bias) are merged from _facts.json
// afterward by merge_algo_insights.py, so numbers never depend on the LLM.

const GEN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'summary', 'what_it_trades', 'style', 'style_evidence', 'expiry', 'hold', 'makes_money_when', 'iv_sensitivity'],
  properties: {
    id: { type: 'string' },
    summary: { type: 'string', description: '2-3 sentences a trader can skim: what it is + edge + when it works' },
    what_it_trades: { type: 'string', description: 'e.g. "~400-pt bull-put credit spreads on NIFTY, mostly CE side"' },
    style: { type: 'string', enum: ['mean-reverting / premium-selling', 'trend-following / momentum', 'neutral / range', 'mixed'] },
    style_evidence: { type: 'string', description: 'one line citing the regime/side numbers that justify the style label' },
    expiry: { type: 'string', description: 'inferred expiry cadence (weekly/monthly/daily); hedge with "inferred"' },
    hold: { type: 'string', description: 'qualitative hold based on style_label; NO invented intraday hours (data is date-level)' },
    makes_money_when: { type: 'string', description: 'best and worst direction×volatility regime, from the regime buckets' },
    iv_sensitivity: { type: 'string', description: 'MUST be framed as a realized-vol proxy, explicitly NOT implied vol' },
  },
};

const VERIFY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'ok', 'issues'],
  properties: {
    id: { type: 'string' },
    ok: { type: 'boolean' },
    issues: { type: 'array', items: { type: 'string' } },
    corrected: { type: 'object', additionalProperties: true, description: 'only when ok=false: corrected judgment fields to override' },
  },
};

function genPrompt(a) {
  return `You are writing a concise research profile for ONE Stratzy options strategy for a trader's research dashboard.
First Read its facts file: ${a.path}
It is JSON with: side_mix (ce_pct/pe_pct), trade_structure (CS: spread_type, avg_strike_width, side_summary, iron_condor_pct) or ob_strategy (OB: moneyness, trend_label, market_fit), win_loss (win_rate, avg_win_pts, avg_loss_pts, profit_factor, trades_per_month), regime.dir {bull,sideways,bear} + regime.vol {low,normal,high} (each with trades/avg_pts/win_rate), one_liner, style_label, neighbours.

Write plain-English judgment fields. STRICT rules:
- Ground EVERY claim in numbers from that file. Never invent.
- style: mean-reverting/premium-selling vs trend-following/momentum vs neutral/range. Infer: profit concentrated in sideways &/or low-vol => premium-selling/mean-revert; profit strongest in bull&bear or high-vol => directional/momentum; balanced both-sides / iron-condor heavy => neutral/range. Put the deciding numbers (e.g. "sideways avg +7.2, high-vol avg -12") in style_evidence.
- hold: base on style_label (e.g. "held overnight to expiry"). The data is DATE-LEVEL only — do NOT state a specific hour count beyond what style_label already says.
- iv_sensitivity: there is NO implied-vol data. Read the realized-vol buckets (regime.vol low/normal/high avg_pts) and describe how it does across them, EXPLICITLY calling it a "realized-vol proxy, not implied vol".
- expiry: infer softly from one_liner/style_label; include "(inferred)".
- makes_money_when: name the best AND worst direction×vol regimes from the buckets, with the avg_pts.
Echo the id exactly: ${a.id}`;
}

function verifyPrompt(a, p) {
  return `Adversarially fact-check this AI profile against its SOURCE facts. Be skeptical; default to ok=false if any claim is unsupported.
Read the facts file: ${a.path}
Profile under review: ${JSON.stringify(p)}
Set ok=false and list issues if ANY of: a number/direction/side/regime claim contradicts the facts; it invents a specific intraday hold time (only date-level data exists); it calls the volatility analysis "IV"/"implied vol" instead of a realized-vol proxy; the style label contradicts the regime distribution; or makes_money_when names the wrong best/worst regime.
IMPORTANT: whenever ok=false you MUST populate "corrected" with the FULL corrected value of every field you found wrong (same keys as the profile: summary/what_it_trades/style/style_evidence/expiry/hold/makes_money_when/iv_sensitivity) — a flagged issue without a corrected field is useless. If ok=true, omit "corrected". Echo id ${a.id}.`;
}

const A = typeof args === 'string' ? JSON.parse(args) : (args || {});
const index = A.algos || [];
log(`profiling ${index.length} algos`);

const results = await pipeline(
  index,
  (a) => agent(genPrompt(a), { label: `gen:${a.short}`, phase: 'Generate', schema: GEN_SCHEMA, model: 'sonnet' }).then((p) => ({ a, p })),
  ({ a, p }) =>
    p
      ? agent(verifyPrompt(a, p), { label: `chk:${a.short}`, phase: 'Verify', schema: VERIFY_SCHEMA, model: 'sonnet' }).then((v) => ({
          id: a.id,
          name: a.name,
          category: a.category,
          profile: v && v.ok === false && v.corrected ? { ...p, ...v.corrected } : p,
          verdict: v ? { ok: v.ok, issues: v.issues || [] } : null,
        }))
      : null
);

const good = results.filter(Boolean);
const corrected = good.filter((r) => r.verdict && r.verdict.ok === false).length;
log(`done: ${good.length}/${index.length} profiles, ${corrected} corrected by verify`);
return { generated_at: A.generated_at, n: good.length, corrected, algos: good };
