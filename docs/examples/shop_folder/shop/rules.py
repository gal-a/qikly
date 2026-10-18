MAX_RATE = 100


def label(code):
    if code.strip().lower() == 'vip':
        return 'gold'
    return 'standard'
