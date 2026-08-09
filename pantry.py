"""Tracks estimated long-life pantry stock across biweekly shops.

Rounding a biweekly need up to a pack size (grocery.py) almost always buys
a bit more than that cycle needs - e.g. needing 750g of rice, in 500g bags,
means buying 1000g and having 250g left over. That leftover is still in the
pantry for the *next* biweekly cycle. This module remembers it in
pantry_state.json and subtracts it from the next cycle's raw requirement
before rounding again, so recommended quantities trend down over time
instead of every cycle rounding up in isolation.

This is an estimate, not a real stocktake: it assumes every gram bought
gets consumed exactly per the meal plan - no spoilage, no eating more or
less than a recipe calls for, no untracked use, no manual top-up shops.
Delete pantry_state.json any time to reset tracking back to zero surplus
(e.g. after a big manual pantry restock the tool doesn't know about).

State only advances when a biweekly list is generated for a *new* shopping
cycle (identified by ISO year+week, e.g. "2026-W04"). Re-running the same
cycle replays the previously recorded purchase instead of recomputing and
double-counting the surplus adjustment.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from grocery import LONG_LIFE_INGREDIENTS, GroceryItem, raw_totals, round_up_to_pack
from meal_plan import DayPlan

STATE_PATH = Path(__file__).with_name("pantry_state.json")


@dataclass
class PantryState:
    last_shopped: str | None = None  # e.g. "2026-W04" - the cycle last committed
    surplus: dict[str, float] = field(default_factory=dict)  # estimated stock remaining, by ingredient name
    last_purchase: dict[str, float] = field(default_factory=dict)  # what was bought during last_shopped


def load_state(path: Path = STATE_PATH) -> PantryState:
    if not path.exists():
        return PantryState()
    raw = json.loads(path.read_text())
    return PantryState(
        last_shopped=raw.get("last_shopped"),
        surplus=raw.get("surplus", {}),
        last_purchase=raw.get("last_purchase", {}),
    )


def save_state(state: PantryState, path: Path = STATE_PATH) -> None:
    path.write_text(
        json.dumps(
            {"last_shopped": state.last_shopped, "surplus": state.surplus, "last_purchase": state.last_purchase},
            indent=2,
        )
        + "\n"
    )


def reset_state(path: Path = STATE_PATH) -> None:
    if path.exists():
        path.unlink()


def plan_biweekly_purchase(
    week_plan: list[DayPlan],
    next_week_plan: list[DayPlan],
    portion_factor: float,
    shopping_cycle_id: str,
    path: Path = STATE_PATH,
) -> list[GroceryItem]:
    """Long-life items to actually buy this cycle, after subtracting
    estimated surplus carried over from previous cycles. Persists the
    updated surplus for next time, unless shopping_cycle_id matches what's
    already recorded (a safe replay, not a recompute).
    """
    state = load_state(path)

    if state.last_shopped == shopping_cycle_id:
        return [
            GroceryItem(name, qty, LONG_LIFE_INGREDIENTS[name].unit) for name, qty in sorted(state.last_purchase.items())
        ]

    needed = raw_totals([week_plan, next_week_plan], portion_factor, long_life=True)

    new_surplus = dict(state.surplus)
    new_purchase: dict[str, float] = {}
    items = []
    for (name, unit), needed_qty in sorted(needed.items()):
        carried = state.surplus.get(name, 0.0)
        remaining_need = max(0.0, needed_qty - carried)
        purchase_qty = round_up_to_pack(name, unit, remaining_need, long_life=True) if remaining_need > 0 else 0.0

        new_surplus[name] = carried + purchase_qty - needed_qty
        if purchase_qty > 0:
            new_purchase[name] = purchase_qty
            items.append(GroceryItem(name, purchase_qty, unit))

    save_state(PantryState(last_shopped=shopping_cycle_id, surplus=new_surplus, last_purchase=new_purchase), path)
    return items
