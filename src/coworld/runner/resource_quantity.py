"""Resource quantity conversion shared by the local and hosted runners."""

import re
from decimal import Decimal

_SUFFIX = re.compile(r"([numkKMGTPE])(i?)\Z")
_EXPONENTS = {"n": -3, "u": -2, "m": -1, "k": 1, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}


def parse_resource_quantity(value: str) -> Decimal:
    """Convert CPU/memory quantities without importing the Kubernetes client.

    Preserve the Python client's decimal and binary scales, including scientific
    notation in the numeric portion. Callers apply resource-specific bounds.
    """
    suffix = _SUFFIX.search(value)
    if suffix is None:
        return Decimal(value)

    prefix, binary = suffix.groups()
    if prefix == "k" and binary:
        raise ValueError(f"Invalid resource quantity suffix: {value!r}; use Ki")
    scale = Decimal(1024 if binary else 1000) ** _EXPONENTS[prefix]
    return Decimal(value[: suffix.start()]) * scale
