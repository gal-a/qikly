# Shop

A shop's checkout rules, as a package of two modules.

## Function: `shop.pricing.apply_discount(price, discount_rate)`

Applies a percentage discount to a price and returns the new price, rounded
to whole cents.

- `price`: the price before the discount.
- `discount_rate`: the discount, as a percentage, capped by
  `shop.rules.MAX_DISCOUNT_RATE`, which is 100. A discount rate of 0 leaves
  the price as it is. A full discount, a discount rate of `MAX_DISCOUNT_RATE`
  or more, is never given at checkout, because a free order goes through a
  separate approval, so it is rejected with `ValueError`, and so is a negative
  discount rate.

## Function: `shop.rules.label(code)`

Labels a customer code for the receipt.

- `code`: the customer code. The VIP code is labelled `gold`, whatever its
  letter case and with any spaces around it ignored; every other code is
  `standard`.