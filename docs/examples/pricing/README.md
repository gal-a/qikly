# Pricing.py module

Pricing helpers for a shop's checkout.

## Function: `apply_discount(price, discount_rate)`

Applies a percentage discount to a price and returns the new price, rounded
to whole cents.

- `price`: the price before the discount.
- `discount_rate`: the discount, as a percentage. A discount rate of 0 leaves
  the price as it is. A full 100% discount is never given at checkout, because
  a free order goes through a separate approval, so a discount rate of 100 or
  more is rejected with `ValueError`, and so is a negative discount rate.

## Function: `label(code)`

Labels a customer code for the receipt.

- `code`: the customer code. The VIP code is labelled `gold`, whatever its
  letter case and with any spaces around it ignored; every other code is
  `standard`.