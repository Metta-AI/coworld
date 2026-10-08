from decimal import Decimal, InvalidOperation

import pytest

from coworld.runner.resource_quantity import parse_resource_quantity


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        ("750m", "0.75"),
        ("250u", "0.000250"),
        ("500n", "0.000000500"),
        ("1.5Gi", "1610612736"),
        ("128Mi", "134217728"),
        ("1Ki", "1024"),
        ("1k", "1000"),
        ("1K", "1000"),
        ("2M", "2000000"),
        ("1E", "1e18"),
        ("1Ei", "1152921504606846976"),
        ("1e3", "1000"),
        ("1E-3", "0.001"),
        ("1e3Ki", "1024000"),
        ("+.5", "0.5"),
        ("-2.5G", "-2500000000"),
    ],
)
def test_resource_quantity_scales(quantity: str, expected: str) -> None:
    assert parse_resource_quantity(quantity) == Decimal(expected)


@pytest.mark.parametrize("quantity", ["", "cpu", "1ki", "1MiB", "1Mi\n", "1e"])
def test_resource_quantity_rejects_malformed_input(quantity: str) -> None:
    with pytest.raises((ValueError, InvalidOperation)):
        parse_resource_quantity(quantity)
