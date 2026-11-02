# Stratzy book verdicts (2026-11-03)

Evidence: composite rank · 12M / 3M net at frame lots · MDD · PF · real fills Jul–Oct (advised vs ck net, slippage) · copier fit. Lots are Stratzy lots on Auto; each FIT pick gets +1 copier SELL lot (2 effective).

## Book verdicts

| Algo | Verdict | Lots | Evidence |
|---|---|---|---|
| IV-Imbalance | keep | 1 (+1) | #4 · ₹5.09L / ₹1.01L · MDD ₹1.11L · PF 1.54 · adv ₹1,58,694 vs ck ₹79,851, slip −₹26,605, copier +₹46,463 · FIT |
| Curvature | unpark | 1 (+1) | #6 · ₹3.25L / ₹53,580 · MDD ₹75,421 · PF 1.34 · adv ₹34,694 vs ck −₹10,455, slip −₹25,945 · FIT |
| Delta-Rotation | resize | 1 (+1) | #12 · ₹2.99L / ₹14,636 · MDD ₹1.17L · PF 1.41 · adv −₹3,299 vs ck −₹26,000, slip only −₹3,326, sizing −₹29,221 · FIT |
| Ratio-Fluxer | copy-only | 1 (+1) | #144, fails trades<40 (18) · ₹1.93L / ₹1.21L · MDD ₹47,443 · PF 3.69 · adv ₹1,34,488 vs ck ₹41,512, slip −₹51,555, missed −₹51,480 · FIT |
| Index Scalper | resize 8→1 | 1 | #11 · ₹4.50L / ₹2.84L · MDD ₹1.61L (2 lots alone ₹82,671) · PF 1.44 · adv ₹72,495 vs ck ₹42,640, slip +₹9,577 · NO fit |
| Zen | drop (first reserve) | 0 | #5 · ₹4.33L / ₹72,588 · MDD ₹97,631 · PF 1.44 · adv ₹1,91,591 vs ck ₹1,470, slip −₹1,03,943 · FIT; any book with Zen breaks ₹75k (best ₹87,419) |
| Theta-Harvest | drop | 0 | #23 · ₹1.86L / −₹58,517 · MDD ₹1.57L · PF 1.19 · adv −₹75,433 vs ck −₹18,179 · FIT |
| Ratio-Weave | drop | 0 | #28 · ₹99,553 / ₹61,444 · MDD ₹1.56L · PF 1.16 · adv ₹41,356 vs ck −₹3,295, slip −₹56,602 · FIT |
| Vega-Shift | drop | 0 | #42 · ₹22,832 / −₹48,008 · MDD ₹2.51L · PF 1.02 · adv ₹32,786 vs ck ₹8,062 · FIT |
| CF Strangle | drop | 0 | #48 · −₹10,497 / ₹90,715 · MDD ₹1.85L · PF 0.97 · adv −₹7,085 vs ck −₹7,079 · FIT |
| Prudent | drop | 0 | #16 · ₹96,934 / −₹11,430 · MDD ₹43,205 · PF 1.69 · adv −₹1,25,837 vs ck −₹10,466 · NO fit |
| Damper | drop (parked) | 0 | #7 · ₹2.92L / −₹27,696 · MDD ₹74,301 · PF 1.30 · adv ₹38,249 vs ck ₹9,032, missed −₹39,699 · FIT, but intraday so the copier lot is naked all day |
| Convex | drop (parked) | 0 | #21 · ₹2.68L / ₹1.07L · MDD ₹1.54L · PF 1.27 · adv ₹17,615 vs ck −₹14,736, missed −₹57,983 · FIT |
| Savdhaan | drop (parked) | 0 | #15 · ₹2.00L / −₹62,632 · MDD ₹86,560 · PF 1.49 · no fills · NO |
| Sookshma-Nazar | drop; out of COPY_IDS | 0 | #3 · ₹2.42L / ₹4,505 · MDD ₹52,376 · PF 2.06 · adv −₹70,018 vs ck −₹14,073 · NO fit |
| Burst RR | drop; out of COPY_IDS | 0 | #30 · ₹44,300 / −₹57,964 · MDD ₹1.30L · PF 1.04 · adv −₹1,01,039 vs ck −₹21,482 · NO fit |
| SkewHunter (+TSL) | drop | 0 | #51 · −₹24,293 / −₹83,169 · MDD ₹1.85L · PF 0.98 · adv −₹88,517 vs ck −₹8,151 (TSL #32: PF 1.04, adv −₹1,30,852) · NO fit |

**Delta-Rotation:** 17 matched days closed near advised prices; the loss was sizing. No exact-copy trips prove the overnight close, so it stays out of COPY_IDS and runs Auto.

## Adds (FIT, all gates, not in book)

| Algo | Verdict | Evidence |
|---|---|---|
| Gamma-Fluxer | **add**, 1 (+1) | #14 · ₹2.53L / ₹60,560 · MDD ₹1.08L · PF 1.28 · 139 trades · adv ₹40,534 vs ck ₹19,491 · corr 0.15 with IVI |
| Delta-Ripple | not added (runner-up) | #18 · ₹2.27L / ₹75,806 · MDD ₹1.10L · PF 1.26 · adv ₹49,290 vs ck −₹33,070, missed −₹1,12,889 · no room under ₹75k |
| Ratio-Return | not added | #25 · ₹1.49L / ₹57,951 · MDD ₹1.31L · PF 1.26 · Calmar 1.14, 83 trades |

Burst/Vacuum GRID (#1, #2): naked buys, NO fit, and the public series contradicts the deep tier (12M −30.6%).

## Sizing (combined per-day curve, parquet, 12M to 2026-11-02)

| Book (effective lots) | 12M net | Combined MDD | Sum of MDDs | Calmar |
|---|---|---|---|---|
| IVI 2, Curvature 2, Delta-Rotation 2, Gamma-Fluxer 2, Ratio-Fluxer 2, Index Scalper 1 | **₹8,61,397** | **₹74,082** | ₹2,76,491 | **11.63** |

Individual MDDs: IVI ₹56,288, Delta-Rotation ₹59,052, Gamma-Fluxer ₹55,572, Index Scalper ₹43,432, Curvature ₹38,222, Ratio-Fluxer ₹23,926. 3M ₹2,41,209; worst day −₹48,895. Clears ₹75k by ~₹900, all picks ≥1 lot.

> Caveats: picked in-sample; May–Jun made ₹4.5L of the ₹8.6L (Nov–Apr only ₹1.63L). The copier lot is naked until the 14:50 wing, so real risk exceeds this spread backtest, and `TOPUP_MARGIN_CHECK` is dead code.

## Copier settings

- `COPY_IDS`: empty (drop Burst RR, Sookshma-Nazar; IVI is a no-op on Auto; Delta-Rotation stays out). No `COPY_LOTS_*`.
- `TOPUP_LOTS_DEFAULT` 3→**1**, `TOPUP_MAX_LOTS` 4→**1**, `TOPUP_KILL_CAP_RUPEES` 1,00,000→**40,000**.

## Stratzy toggles (ck, by hand)

1. Auto, 1 lot: IV-Imbalance (5→1), Curvature (enable), Delta-Rotation (Manual→Auto), Gamma-Fluxer (enable), Ratio-Fluxer, Index Scalper (8→1).
2. Disable Zen, Theta-Harvest, Prudent, Vega-Shift, Ratio-Weave (Manual+enabled now), CF Strangle.
3. Keep disabled: Damper, Convex, Savdhaan, Sookshma-Nazar, Burst RR, SkewHunter, SkewHunter TSL. Any FIT algo left on gets topped up; the copier can't tell algos apart.

## Execution lessons

Run as advised, the matched contracts made ₹3,23,424; ck netted ₹55,866 after ₹42,261 charges, and −₹1,848 overall once unmatched manual trades (−₹57,713) count. The −₹2,56,320 slippage was hand execution, led by Zen (−₹1,03,943, four days of ₹17–25k worse exits) then Ratio-Weave, Ratio-Fluxer, IVI and Curvature. Missed hedges cost −₹81,507 net, mostly one-legged Delta-Ripple (−₹1.13L) and Convex (−₹57,983). Sizing added +₹1,12,529 only because ck was 0.13–0.17x on losing naked buys; under-sizing winners cost IVI −₹98,579 and Zen −₹47,645.
