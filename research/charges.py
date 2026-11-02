"""NSE NIFTY options charges on Dhan (stdlib only)."""
import csv
import sys

BROKERAGE_PER_ORDER = 20.0
STT_SELL = 0.001          # 0.1% of premium, SELL only
EXCHANGE_TXN = 0.000353   # 0.0353% of premium, both sides
SEBI_PER_CRORE = 10.0     # Rs per crore of premium, both sides
STAMP_BUY = 0.00003       # 0.003% of premium, BUY only
GST = 0.18                # on brokerage + exchange + SEBI

CALIBRATION = 1.083  # footer_total over modelled_total, Jul 1-Nov 2
CSV_PATH = "/Users/ck/.claude/jobs/b5f4e1ec/tmp/dhan_trades.csv"
FOOTER_TOTAL = 55972.46
FOOTER_BROKERAGE = 28820.0
FOOTER_ORDERS = 1441


def leg_cost(side: str, premium: float, qty: int, orders: int = 1) -> float:
    """Total charges (Rs) for one leg. premium = option price per unit."""
    turnover = premium * qty
    side = side.upper()
    brokerage = BROKERAGE_PER_ORDER * orders
    exchange = turnover * EXCHANGE_TXN
    sebi = turnover * SEBI_PER_CRORE / 1e7
    stt = turnover * STT_SELL if side == "SELL" else 0.0
    stamp = turnover * STAMP_BUY if side == "BUY" else 0.0
    gst = GST * (brokerage + exchange + sebi)
    return brokerage + exchange + sebi + stt + stamp + gst


def leg_cost_calibrated(side: str, premium: float, qty: int, orders: int = 1) -> float:
    return leg_cost(side, premium, qty, orders) * CALIBRATION


def calibrate(path: str = CSV_PATH) -> dict:
    """Model all option rows in the CSV; compare to Dhan's footer."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            cs = r["customSymbol"]
            if r["productType"] in ("MARGIN", "INTRADAY") and ("CALL" in cs or "PUT" in cs):
                rows.append(r)
    order_ids = {r["orderId"] for r in rows}
    # brokerage is per distinct order: charge it once per orderId, on its first row
    seen = set()
    total = 0.0
    for r in rows:
        first = r["orderId"] not in seen
        seen.add(r["orderId"])
        total += leg_cost(r["side"], float(r["price"]), int(float(r["qty"])), 1 if first else 0)
    brokerage = BROKERAGE_PER_ORDER * len(order_ids)
    return {
        "rows": len(rows),
        "orders": len(order_ids),
        "modelled_brokerage": brokerage,
        "modelled_total": total,
        "footer_total": FOOTER_TOTAL,
        "ratio": FOOTER_TOTAL / total,
    }


if __name__ == "__main__":
    res = calibrate(sys.argv[1] if len(sys.argv) > 1 else CSV_PATH)
    for k, v in res.items():
        print(f"{k}: {v:,.4f}" if isinstance(v, float) else f"{k}: {v}")
    print(f"CALIBRATION (3dp): {res['ratio']:.3f}")
