from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BeforeValidator


DEFAULT_CURRENCY = "VND"


def normalize_vnd_currency(value: object) -> str:
    """Normalize an allowed VND value and reject every other currency."""

    currency = str(value or DEFAULT_CURRENCY).strip().upper()
    if currency != DEFAULT_CURRENCY:
        raise ValueError("only VND is supported")
    return DEFAULT_CURRENCY


VndCurrency = Annotated[
    Literal["VND"],
    BeforeValidator(normalize_vnd_currency),
]
