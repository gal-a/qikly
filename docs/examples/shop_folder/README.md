# Shop

A shop's checkout rules, as a package of two modules.

## `shop.pricing.apply_discount(price, rate)`

Applies a percentage discount to a price and returns the new price, rounded
to whole cents.

`rate` is a percentage, capped by `shop.rules.MAX_RATE`, which is 100. A rate
of 0 leaves the price as it is. A full discount, a rate of `MAX_RATE` or more,
is never given at checkout, because a free order goes through a separate
approval, so it is rejected with `ValueError`, and so is a negative rate.

## `shop.rules.label(code)`

Labels a customer code for the receipt. The VIP code is labelled `gold`,
whatever its letter case and with any spaces around it ignored; every other
code is `standard`.
