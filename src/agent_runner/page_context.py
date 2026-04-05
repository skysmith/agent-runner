from __future__ import annotations

from typing import Any


KNOWN_ROUTES = {
    "/finance/inventory": "inventory",
    "/finance/cash-flow": "cashflow",
    "/finance/payouts": "payouts",
}


def normalize_page_context(raw: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    route = _clean_path(raw.get("route"))
    adapter = _infer_adapter(route)
    normalized: dict[str, object] = {}
    if route:
        normalized["route"] = route
    normalized["adapter"] = adapter

    filters = _clean_dict(raw.get("filters"))
    entities = _clean_dict(raw.get("entities"))
    visible_columns = _clean_list(raw.get("visible_columns"))
    metrics = _clean_list(raw.get("metrics"))
    date_window = _clean_dict(raw.get("date_window"))

    if filters:
        normalized["filters"] = filters
    if entities:
        normalized["entities"] = entities
    if visible_columns:
        normalized["visible_columns"] = visible_columns
    if metrics:
        normalized["metrics"] = metrics
    if date_window:
        normalized["date_window"] = date_window

    # Page-specific stable aliases so prompt consumers can rely on shape.
    if adapter == "inventory":
        _add_alias(normalized, entities, "sku", "sku")
        _add_alias(normalized, entities, "warehouse", "warehouse")
        _add_alias(normalized, filters, "sell_through_window", "sell_through_window")
    elif adapter == "cashflow":
        _add_alias(normalized, entities, "account_id", "account_id")
        _add_alias(normalized, filters, "category", "category")
        if date_window:
            normalized["cashflow_date_window"] = date_window
    elif adapter == "payouts":
        _add_alias(normalized, entities, "payout_id", "payout_id")
        _add_alias(normalized, filters, "status", "status")
        _add_alias(normalized, filters, "provider", "provider")

    return normalized


def _infer_adapter(route: str | None) -> str:
    if not route:
        return "generic"
    route_text = route.lower()
    for known_route, adapter in KNOWN_ROUTES.items():
        if route_text.startswith(known_route):
            return adapter
    if "inventory" in route_text:
        return "inventory"
    if "cash" in route_text or "flow" in route_text:
        return "cashflow"
    if "payout" in route_text:
        return "payouts"
    return "generic"


def _clean_path(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not text.startswith("/"):
        text = "/" + text
    return text


def _clean_dict(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, object] = {}
    for key, item in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        if isinstance(item, str):
            item_text = item.strip()
            if item_text:
                cleaned[key_text] = item_text
            continue
        if isinstance(item, (int, float, bool)):
            cleaned[key_text] = item
            continue
        if item is None:
            continue
        cleaned[key_text] = str(item)
    return cleaned


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _add_alias(target: dict[str, object], source: dict[str, object], source_key: str, alias_key: str) -> None:
    value = source.get(source_key)
    if value is None:
        return
    target[alias_key] = value
