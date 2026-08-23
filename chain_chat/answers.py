"""chain-chat — shared answer types and number formatters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_MONEY_RE = re.compile(r"^\d+(\.\d+)?$")


@dataclass
class Answer:
    question: str
    text: str
    sql: str | None
    columns: list[str] = field(default_factory=list)
    rows: list = field(default_factory=list)
    truncated: bool = False
    source: str = "llm"          # "llm" | "canned" | "fallback"
    model: str | None = None
    error: str | None = None     # "offline-fallback" | "guardrail" | ...


def format_usd(value: float) -> str:
    """$1_234_567 -> '$1.2M' · 987_654 -> '$987.7K' · 1234 -> '$1,234.00'."""
    value = float(value)
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.2f}"


def format_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:,.1f}K"
    return f"{value:,.0f}"