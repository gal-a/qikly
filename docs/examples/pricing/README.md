# Pricing

Pricing helpers for a shop's checkout.

## `apply_discount(price, rate)`

Applies a percentage discount to a price and returns the new price, rounded
to whole cents.

`rate` is a percentage. A rate of 0 leaves the price as it is. A full 100%
discount is never given at checkout, because a free order goes through a
separate approval, so a rate of 100 or more is rejected with `ValueError`, and
so is a negative rate.

## `label(code)`

Labels a customer code for the receipt. The VIP code is labelled `gold`,
whatever its letter case and with any spaces around it ignored; every other
code is `standard`.
