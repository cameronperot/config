# Example test module

The shape SKILL.md asks for: a shared fixture, Arrange-Act-Assert with blank lines, a parametrized case table with `ids=`, an error path, and exact `Decimal` comparisons for an amount (see `domain-checks.md` for why exact values are not compared with default `pytest.approx`).

```python
from decimal import Decimal

import pytest

from billing.parser import parse_line_item


@pytest.fixture
def raw_item():
    return {"sku": "A-100", "description": "Widget", "amount": "0.5"}


def test_parse_line_item_valid_input_returns_item(raw_item):
    item = parse_line_item(raw_item)

    assert item.sku == "A-100"
    assert item.amount == Decimal("0.5")


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("1", Decimal("1")), ("0.001", Decimal("0.001")), ("1e-8", Decimal("1e-8"))],
    ids=["integer", "decimal", "scientific"],
)
def test_parse_line_item_amount_formats_parse_exactly(raw_item, amount, expected):
    raw_item["amount"] = amount

    item = parse_line_item(raw_item)

    assert item.amount == expected


def test_parse_line_item_empty_sku_raises_value_error(raw_item):
    raw_item["sku"] = ""

    with pytest.raises(ValueError, match="sku"):
        parse_line_item(raw_item)
```
