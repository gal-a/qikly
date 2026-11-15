from pricing import apply_discount, label


def test_discount():
    assert apply_discount(100, 10) == 90  # 10% off a price of 100


def test_label():
    assert label("vip") == "gold"  # the VIP code gets the gold label
