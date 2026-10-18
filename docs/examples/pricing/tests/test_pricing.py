from pricing import apply_discount, label


def test_discount():
    assert apply_discount(100, 10) == 90


def test_label():
    assert label("vip") == "gold"
