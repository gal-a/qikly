from shop.pricing import apply_discount
from shop.rules import label


def test_discount():
    assert apply_discount(100, 10) == 90  # 10% off a price of 100


def test_label():
    assert label('vip') == 'gold'  # the VIP code gets the gold label
