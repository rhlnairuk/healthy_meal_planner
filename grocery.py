"""Turns weeks of meals into grocery lists sized for the household.

Ingredients are split into two shopping cadences:

- Weekly: perishables (fresh produce, meat, fish, fresh dairy, bread) that
  only keep for a few days, so they're bought fresh for the week they're
  used in. Rounded up to a flat pack size (PACK_SIZE_G / PACK_SIZE_ML)
  since fresh items aren't bought in one fixed size the way tins and bags
  of pantry staples are.
- Biweekly: pantry staples (dried goods, tins, oils, sauces, long-life
  freezer items) that keep for weeks or months, so they're bought every
  other week in a single bulk shop sized to cover both weeks. Rounded up to
  each ingredient's own real-world pack size, defined in
  long_life_ingredients.json.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from meal_plan import DayPlan, Recipe

# Round perishable purchase quantities up to these flat pack sizes so the
# list reads like something you'd actually buy, rather than raw recipe math.
PACK_SIZE_G = 25
PACK_SIZE_ML = 50

LONG_LIFE_PATH = Path(__file__).with_name("long_life_ingredients.json")


@dataclass(frozen=True)
class LongLifeIngredient:
    name: str
    unit: str
    pack_size: float


def load_long_life_ingredients(path: Path = LONG_LIFE_PATH) -> dict[str, LongLifeIngredient]:
    """Load and validate long_life_ingredients.json into a name -> entry map.

    Each entry records the unit and real-world pack size (e.g. a 500g bag,
    a 400g tin) that pantry staple is rounded up to when building the
    biweekly list. Ingredients not listed here default to the weekly,
    flat-rounded perishable list.
    """
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise FileNotFoundError(f"Long-life ingredient file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None

    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array of ingredient entries.")

    entries = {}
    for i, item in enumerate(raw):
        where = f"{path.name}[{i}]"
        missing = [k for k in ("name", "unit", "pack_size") if k not in item]
        if missing:
            raise ValueError(f"{where} is missing {missing}.")
        if item["unit"] not in ("g", "ml", "unit"):
            raise ValueError(f"{where} ('{item['name']}') has unit '{item['unit']}', must be 'g', 'ml', or 'unit'.")
        if not isinstance(item["pack_size"], (int, float)) or item["pack_size"] <= 0:
            raise ValueError(f"{where} ('{item['name']}') has an invalid pack_size: {item['pack_size']!r}.")
        if item["name"] in entries:
            raise ValueError(f"{where}: '{item['name']}' is listed more than once.")
        entries[item["name"]] = LongLifeIngredient(item["name"], item["unit"], item["pack_size"])

    return entries


LONG_LIFE_INGREDIENTS = load_long_life_ingredients()


@dataclass
class GroceryItem:
    name: str
    quantity: float
    unit: str

    def display(self) -> str:
        if self.unit == "unit":
            return f"{math.ceil(self.quantity)} x {self.name}"
        return f"{self.quantity:g}{self.unit} {self.name}"


def _all_recipes(week_plans: list[list[DayPlan]]) -> list[Recipe]:
    recipes = []
    for week_plan in week_plans:
        for day in week_plan:
            recipes.extend([day.breakfast, day.lunch, day.dinner, day.snack])
    return recipes


def raw_totals(
    week_plans: list[list[DayPlan]], portion_factor: float, *, long_life: bool
) -> dict[tuple[str, str], float]:
    """Unrounded ingredient totals (name, unit) -> quantity, before pack-size
    rounding. Exposed (not just an internal step of _build_grocery_list) so
    pantry.py can subtract carried-over surplus before rounding.
    """
    totals: dict[tuple[str, str], float] = {}
    for recipe in _all_recipes(week_plans):
        for ing in recipe.ingredients:
            if (ing.name in LONG_LIFE_INGREDIENTS) != long_life:
                continue
            key = (ing.name, ing.unit)
            totals[key] = totals.get(key, 0.0) + ing.quantity * portion_factor
    return totals


def round_up_to_pack(name: str, unit: str, qty: float, *, long_life: bool) -> float:
    if long_life:
        entry = LONG_LIFE_INGREDIENTS[name]
        if entry.unit != unit:
            raise ValueError(
                f"'{name}' is used as '{unit}' in a recipe but long_life_ingredients.json "
                f"declares it as '{entry.unit}' - fix the mismatch in one of the two files."
            )
        return math.ceil(qty / entry.pack_size) * entry.pack_size
    if unit == "g":
        return math.ceil(qty / PACK_SIZE_G) * PACK_SIZE_G
    if unit == "ml":
        return math.ceil(qty / PACK_SIZE_ML) * PACK_SIZE_ML
    return math.ceil(qty)


def build_weekly_grocery_list(week_plan: list[DayPlan], portion_factor: float) -> list[GroceryItem]:
    """Perishables needed for this one week's plan."""
    totals = raw_totals([week_plan], portion_factor, long_life=False)
    return [
        GroceryItem(name, round_up_to_pack(name, unit, qty, long_life=False), unit)
        for (name, unit), qty in sorted(totals.items())
    ]


def build_biweekly_grocery_list(
    week_plan: list[DayPlan], next_week_plan: list[DayPlan], portion_factor: float
) -> list[GroceryItem]:
    """Pantry staples needed to cover this week and next week's plans, with
    no allowance for surplus already sitting in the pantry from a previous
    shop - see pantry.py for the carryover-aware version main.py actually
    uses. Kept here as the plain, stateless computation for testing/reuse.
    """
    totals = raw_totals([week_plan, next_week_plan], portion_factor, long_life=True)
    return [
        GroceryItem(name, round_up_to_pack(name, unit, qty, long_life=True), unit)
        for (name, unit), qty in sorted(totals.items())
    ]


def is_biweekly_shopping_week(week_number: int) -> bool:
    """Pantry staples are bought every other week - even ISO week numbers."""
    return week_number % 2 == 0


def print_grocery_list(title: str, items: list[GroceryItem], empty_message: str = "(nothing needed)") -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)
    if not items:
        print(f"  {empty_message}")
    for item in items:
        print(f"  - {item.display()}")
