def apply_discount(price, discount_rate):
    if discount_rate < 0 or discount_rate > 100:
        raise ValueError("discount_rate out of range")
    return round(price * (1 - discount_rate / 100), 2)


def label(code):
    if code.strip().lower() == "vip":
        return "gold"
    return "standard"
