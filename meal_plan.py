"""Generates a healthy weekly meal plan that changes from week to week.

Recipes live under recipes/ (one JSON file per meal slot: breakfasts.json,
lunches.json, dinners.json, snacks.json), not in this file - see README.md
for how to add a new one. Each recipe lists ingredients "per adult portion"
plus simple cooking steps. Totals are scaled per meal using
household.total_portion_factor() so the 5-year-old counts as half a
portion.

generate_week_plan() rotates through each meal slot's recipe pool based on
the ISO week number so consecutive weeks get different menus, while
re-running the script within the same week reproduces the same plan.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

RECIPES_DIR = Path(__file__).with_name("recipes")

MEAL_SLOTS = ("breakfasts", "lunches", "dinners", "snacks")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class Ingredient:
    name: str
    quantity: float  # per adult portion
    unit: str  # "g", "ml", or "unit" (whole items like eggs/avocados)


@dataclass(frozen=True)
class Recipe:
    name: str
    ingredients: tuple[Ingredient, ...]
    steps: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class DayPlan:
    day: str
    breakfast: Recipe
    lunch: Recipe
    dinner: Recipe
    snack: Recipe


def _parse_recipe(filename: str, index: int, raw: dict) -> Recipe:
    where = f"{filename}[{index}]"

    if "name" not in raw or not isinstance(raw["name"], str) or not raw["name"].strip():
        raise ValueError(f"{where} is missing a non-empty 'name'.")
    name = raw["name"]

    if "ingredients" not in raw or not isinstance(raw["ingredients"], list) or not raw["ingredients"]:
        raise ValueError(f"{where} ('{name}') needs a non-empty 'ingredients' list.")

    ingredients = []
    for i, raw_ing in enumerate(raw["ingredients"]):
        ing_where = f"{where} ('{name}'), ingredient [{i}]"
        missing = [k for k in ("name", "quantity", "unit") if k not in raw_ing]
        if missing:
            raise ValueError(f"{ing_where} is missing {missing}.")
        if raw_ing["unit"] not in ("g", "ml", "unit"):
            raise ValueError(f"{ing_where} has unit '{raw_ing['unit']}', must be 'g', 'ml', or 'unit'.")
        if not isinstance(raw_ing["quantity"], (int, float)):
            raise ValueError(f"{ing_where} has a non-numeric quantity: {raw_ing['quantity']!r}.")
        ingredients.append(Ingredient(raw_ing["name"], raw_ing["quantity"], raw_ing["unit"]))

    steps = tuple(raw.get("steps", []))

    return Recipe(name, tuple(ingredients), steps)


def load_slot_file(directory: Path, slot: str) -> list[Recipe]:
    path = directory / f"{slot}.json"
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise FileNotFoundError(f"Recipe file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None

    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} must contain a non-empty JSON array of recipes.")

    return [_parse_recipe(path.name, i, r) for i, r in enumerate(raw)]


def load_recipe_pools(directory: Path = RECIPES_DIR) -> dict[str, list[Recipe]]:
    """Load and validate recipes/*.json into Recipe objects, one list per meal slot."""
    return {slot: load_slot_file(directory, slot) for slot in MEAL_SLOTS}


_POOLS = load_recipe_pools()
BREAKFASTS = _POOLS["breakfasts"]
LUNCHES = _POOLS["lunches"]
DINNERS = _POOLS["dinners"]
SNACKS = _POOLS["snacks"]


def generate_week_plan(week_number: int | None = None) -> list[DayPlan]:
    """Build a 7-day plan. Same week_number always yields the same plan;
    different week numbers rotate through the recipe pools so the menu
    changes week to week. Defaults to the current ISO week number, so a
    plain call to this function naturally varies as real weeks pass.
    """
    if week_number is None:
        week_number = date.today().isocalendar()[1]

    plan = []
    for day_index, day_name in enumerate(DAYS):
        offset = week_number * len(DAYS) + day_index
        plan.append(
            DayPlan(
                day_name,
                BREAKFASTS[offset % len(BREAKFASTS)],
                LUNCHES[offset % len(LUNCHES)],
                DINNERS[offset % len(DINNERS)],
                SNACKS[offset % len(SNACKS)],
            )
        )
    return plan


def print_week_plan(week_plan: list[DayPlan]) -> None:
    print("=" * 60)
    print("WEEKLY HEALTHY MEAL PLAN")
    print("=" * 60)
    for day in week_plan:
        print(f"\n{day.day}")
        print(f"  Breakfast: {day.breakfast.name}")
        print(f"  Lunch:     {day.lunch.name}")
        print(f"  Dinner:    {day.dinner.name}")
        print(f"  Snack:     {day.snack.name}")


def _unique_recipes(week_plan: list[DayPlan]) -> list[Recipe]:
    seen: dict[str, Recipe] = {}
    for day in week_plan:
        for recipe in (day.breakfast, day.lunch, day.dinner, day.snack):
            seen.setdefault(recipe.name, recipe)
    return list(seen.values())


def print_recipe_steps(week_plan: list[DayPlan]) -> None:
    print("=" * 60)
    print("HOW TO MAKE THIS WEEK'S MEALS")
    print("=" * 60)
    for recipe in _unique_recipes(week_plan):
        print(f"\n{recipe.name}")
        for step_number, step in enumerate(recipe.steps, start=1):
            print(f"  {step_number}. {step}")
