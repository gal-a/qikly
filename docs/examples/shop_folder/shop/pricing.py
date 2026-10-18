from .rules import MAX_RATE


def apply_discount(price, rate):
    if rate < 0 or rate > MAX_RATE:
        raise ValueError('rate out of range')
    return round(price * (1 - rate / 100), 2)
