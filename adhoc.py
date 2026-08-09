"""Ad-hoc grocery items - one-off things to buy that aren't tied to any
recipe (e.g. paper towels, a birthday candle), added through the web UI.

Persisted in adhoc_items.json, keyed by ISO week id ("2026-W32" - a single
week, not to be confused with pantry.py's biweekly shopping_cycle_id even
though the string format matches).

Unlike a recipe Ingredient's quantity (always "per one adult portion",
scaled by household size in grocery.py), an ad-hoc item's quantity is the
literal, absolute amount the user typed - it is never multiplied by a
portion factor. Ad-hoc items are also never classified as long-life or
perishable and never folded into the weekly/biweekly totals; they're always
shown in their own section.
"""

import json
from dataclasses import dataclass
from pathlib import Path

STATE_PATH = Path(__file__).with_name("adhoc_items.json")


@dataclass
class AdhocItem:
    name: str
    quantity: float
    unit: str

    def display(self) -> str:
        if self.unit == "unit":
            return f"{int(self.quantity)} x {self.name}" if self.quantity == int(self.quantity) else f"{self.quantity:g} x {self.name}"
        return f"{self.quantity:g}{self.unit} {self.name}"


def _load_all(path: Path = STATE_PATH) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_all(all_items: dict[str, list[dict]], path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(all_items, indent=2) + "\n")


def load_items(week_key: str, path: Path = STATE_PATH) -> list[AdhocItem]:
    raw = _load_all(path).get(week_key, [])
    return [AdhocItem(item["name"], item["quantity"], item["unit"]) for item in raw]


def add_item(week_key: str, name: str, quantity: float, unit: str, path: Path = STATE_PATH) -> list[AdhocItem]:
    if unit not in ("g", "ml", "unit"):
        raise ValueError(f"unit must be 'g', 'ml', or 'unit', got {unit!r}.")
    if not name.strip():
        raise ValueError("name must not be empty.")
    if not isinstance(quantity, (int, float)) or quantity <= 0:
        raise ValueError(f"quantity must be a positive number, got {quantity!r}.")

    all_items = _load_all(path)
    week_items = all_items.setdefault(week_key, [])
    week_items.append({"name": name, "quantity": quantity, "unit": unit})
    _save_all(all_items, path)
    return load_items(week_key, path)


def remove_item(week_key: str, index: int, path: Path = STATE_PATH) -> list[AdhocItem]:
    all_items = _load_all(path)
    week_items = all_items.get(week_key, [])
    if index < 0 or index >= len(week_items):
        raise IndexError(f"No ad-hoc item at index {index} for week {week_key}.")
    week_items.pop(index)
    _save_all(all_items, path)
    return load_items(week_key, path)
