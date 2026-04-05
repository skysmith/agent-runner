from __future__ import annotations

from agent_runner.page_context import normalize_page_context


def test_normalize_inventory_context_adds_inventory_aliases() -> None:
    payload = normalize_page_context(
        {
            "route": "/finance/inventory",
            "entities": {"sku": "SKU-123", "warehouse": "west"},
            "filters": {"sell_through_window": "28d"},
            "metrics": ["on_hand", "sell_through"],
        }
    )
    assert payload["adapter"] == "inventory"
    assert payload["sku"] == "SKU-123"
    assert payload["warehouse"] == "west"
    assert payload["sell_through_window"] == "28d"


def test_normalize_cashflow_context_adds_cashflow_aliases() -> None:
    payload = normalize_page_context(
        {
            "route": "/finance/cash-flow",
            "entities": {"account_id": "acct_42"},
            "filters": {"category": "operations"},
            "date_window": {"start": "2026-03-01", "end": "2026-03-31"},
        }
    )
    assert payload["adapter"] == "cashflow"
    assert payload["account_id"] == "acct_42"
    assert payload["category"] == "operations"
    assert payload["cashflow_date_window"] == {"start": "2026-03-01", "end": "2026-03-31"}


def test_normalize_unknown_route_falls_back_to_generic() -> None:
    payload = normalize_page_context({"route": "/finance/custom"})
    assert payload == {"route": "/finance/custom", "adapter": "generic"}
