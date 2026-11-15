from .rules import MAX_DISCOUNT_RATE


def apply_discount(price, discount_rate):
    if discount_rate < 0 or discount_rate > MAX_DISCOUNT_RATE:
        raise ValueError('discount_rate out of range')
    return round(price * (1 - discount_rate / 100), 2)
