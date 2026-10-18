def apply_discount(price, rate):
    if rate < 0 or rate > 100:
        raise ValueError("rate out of range")
    return round(price * (1 - rate / 100), 2)


def label(code):
    if code.strip().lower() == "vip":
        return "gold"
    return "standard"
