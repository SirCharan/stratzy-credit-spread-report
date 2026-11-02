import charges as c

def test_sell_gt_buy():
    assert c.leg_cost("SELL", 100, 100) > c.leg_cost("BUY", 100, 100)

def test_gst_base():
    t = 100 * 1000
    ex, sebi = t * c.EXCHANGE_TXN, t * c.SEBI_PER_CRORE / 1e7
    base = c.BROKERAGE_PER_ORDER + ex + sebi
    buy = c.leg_cost("BUY", 100, 1000)
    assert abs(buy - (base * (1 + c.GST) + t * c.STAMP_BUY)) < 1e-9
    sell = c.leg_cost("SELL", 100, 1000)
    assert abs(sell - (base * (1 + c.GST) + t * c.STT_SELL)) < 1e-9

def test_ratio():
    assert 1.05 <= c.calibrate()["ratio"] <= 1.15

if __name__ == "__main__":
    test_sell_gt_buy(); test_gst_base(); test_ratio(); print("all tests passed")
