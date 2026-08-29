"""Generate a week's healthy meal plan, its cooking steps, and the grocery
lists needed to shop for it: a weekly list of perishables, plus a biweekly
list of pantry staples on the weeks that bulk shop is due. Sized for the
household you specify. The biweekly list accounts for surplus estimated to
be left over from previous shops (see pantry.py).

Usage:
    python main.py                       # default household (2 adults, 1 child), current week
    python main.py --adults 2 --children 2
    python main.py --week 32             # generate a specific ISO week instead of the current one
    python main.py --reset-pantry        # forget tracked pantry surplus and start over
    python main.py adhoc list [--week 32]
    python main.py adhoc add "Paper towels" 6 unit [--week 32]
    python main.py adhoc remove 0 [--week 32]
    python main.py recipe list [slot]
    python main.py recipe show dinners "Beans on toast"
    python main.py recipe add dinners "Beans on toast" --ingredient "Baked beans:120:g" --ingredient "Wholemeal bread:1:unit" --step "Warm the beans." --step "Toast the bread."
    python main.py recipe update dinners "Beans on toast" --step "Warm the beans in a small pan." --step "Toast the bread and spoon the beans over."
"""

import argparse
import json
from datetime import date
from pathlib import Path

import adhoc
import meal_plan
from grocery import build_weekly_grocery_list, is_biweekly_shopping_week, print_grocery_list
from household import build_household, describe, total_portion_factor
from meal_plan import generate_week_plan, print_recipe_steps, print_week_plan
from pantry import plan_biweekly_purchase, reset_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, default=None, help="ISO week number to generate the menu for (default: current week).")
    parser.add_argument("--adults", type=int, default=2, help="Number of adults to plan and shop for (default: 2).")
    parser.add_argument("--children", type=int, default=1, help="Number of children to plan and shop for (default: 1).")
    parser.add_argument("--reset-pantry", action="store_true", help="Forget tracked pantry surplus before planning this run.")

    subparsers = parser.add_subparsers(dest="command")
    adhoc_parser = subparsers.add_parser("adhoc", help="Manage one-off grocery items that aren't tied to any recipe.")
    adhoc_subparsers = adhoc_parser.add_subparsers(dest="adhoc_command", required=True)

    list_parser = adhoc_subparsers.add_parser("list", help="List ad-hoc items for a week.")
    list_parser.add_argument("--week", type=int, default=None, help="ISO week (default: current week).")

    add_parser = adhoc_subparsers.add_parser("add", help="Add an ad-hoc item for a week.")
    add_parser.add_argument("name", help="Item name, e.g. 'Paper towels'.")
    add_parser.add_argument("quantity", type=float, help="Literal quantity - not scaled by household size.")
    add_parser.add_argument("unit", choices=["g", "ml", "unit"])
    add_parser.add_argument("--week", type=int, default=None, help="ISO week (default: current week).")

    remove_parser = adhoc_subparsers.add_parser("remove", help="Remove an ad-hoc item by its list index.")
    remove_parser.add_argument("index", type=int, help="Index shown by 'adhoc list'.")
    remove_parser.add_argument("--week", type=int, default=None, help="ISO week (default: current week).")

    recipe_parser = subparsers.add_parser("recipe", help="Manage recipes (recipes/*.json).")
    recipe_subparsers = recipe_parser.add_subparsers(dest="recipe_command", required=True)

    recipe_list_parser = recipe_subparsers.add_parser("list", help="List recipes, optionally for one meal slot.")
    recipe_list_parser.add_argument("slot", nargs="?", choices=meal_plan.MEAL_SLOTS, help="Meal slot (default: all slots).")

    recipe_show_parser = recipe_subparsers.add_parser("show", help="Show one recipe's ingredients and steps.")
    recipe_show_parser.add_argument("slot", choices=meal_plan.MEAL_SLOTS)
    recipe_show_parser.add_argument("recipe", help="Recipe name or its index from 'recipe list'.")

    recipe_add_parser = recipe_subparsers.add_parser("add", help="Add a new recipe to a meal slot.")
    recipe_add_parser.add_argument("slot", choices=meal_plan.MEAL_SLOTS)
    recipe_add_parser.add_argument("name")
    recipe_add_parser.add_argument(
        "--ingredient", action="append", required=True, metavar="NAME:QUANTITY:UNIT",
        help="Repeatable, at least one required. Quantity is per one adult portion; unit is g, ml, or unit.",
    )
    recipe_add_parser.add_argument("--step", action="append", default=[], metavar="STEP", help="Repeatable cooking step, in order. Optional.")

    recipe_update_parser = recipe_subparsers.add_parser("update", help="Update an existing recipe - only the fields you pass change.")
    recipe_update_parser.add_argument("slot", choices=meal_plan.MEAL_SLOTS)
    recipe_update_parser.add_argument("recipe", help="Recipe name or its index from 'recipe list'.")
    recipe_update_parser.add_argument("--name", help="New name.")
    recipe_update_parser.add_argument(
        "--ingredient", action="append", metavar="NAME:QUANTITY:UNIT",
        help="Repeatable. If given at all, replaces the entire ingredients list (not merged with the old one).",
    )
    recipe_update_parser.add_argument(
        "--step", action="append", metavar="STEP",
        help="Repeatable. If given at all, replaces the entire steps list (not merged with the old one).",
    )

    return parser.parse_args()


def _parse_ingredient_arg(raw: str) -> dict:
    parts = raw.split(":")
    if len(parts) != 3:
        raise SystemExit(f"error: --ingredient must be 'NAME:QUANTITY:UNIT', got {raw!r}.")
    name, quantity_str, unit = parts
    try:
        quantity = float(quantity_str)
    except ValueError:
        raise SystemExit(f"error: --ingredient quantity must be numeric, got {quantity_str!r} in {raw!r}.")
    return {"name": name, "quantity": quantity, "unit": unit}


def _format_ingredient(ing: dict) -> str:
    if ing["unit"] == "unit":
        return f"{ing['quantity']:g} x {ing['name']}"
    return f"{ing['quantity']:g}{ing['unit']} {ing['name']} (per adult)"


def _slot_path(slot: str) -> Path:
    return meal_plan.RECIPES_DIR / f"{slot}.json"


def _load_raw_slot(slot: str) -> list[dict]:
    return json.loads(_slot_path(slot).read_text())


def _resolve_recipe_index(raw: list[dict], ref: str) -> int:
    if ref.isdigit():
        index = int(ref)
        if 0 <= index < len(raw):
            return index
        raise SystemExit(f"error: No recipe at index {index} ({len(raw)} recipes).")
    matches = [i for i, r in enumerate(raw) if r.get("name") == ref]
    if not matches:
        raise SystemExit(f"error: No recipe named {ref!r}.")
    if len(matches) > 1:
        raise SystemExit(f"error: Multiple recipes named {ref!r}; use its index instead.")
    return matches[0]


def _write_slot_validated(slot: str, raw: list[dict]) -> None:
    """Validate with the same loader main.py uses at startup before writing
    anything, then replace the file atomically - an invalid edit never
    touches disk, and the real file is never left half-written.
    """
    try:
        for i, r in enumerate(raw):
            meal_plan._parse_recipe(f"{slot}.json", i, r)
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(f"error: {error}")

    path = _slot_path(slot)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n")
    tmp.replace(path)


def _print_recipe_summary(index: int, raw: dict) -> None:
    count = len(raw.get("ingredients", []))
    print(f"  [{index}] {raw.get('name', '?')} ({count} ingredient{'s' if count != 1 else ''})")


def handle_recipe(args: argparse.Namespace) -> None:
    if args.recipe_command == "list":
        for slot in [args.slot] if args.slot else list(meal_plan.MEAL_SLOTS):
            raw = _load_raw_slot(slot)
            print(f"{slot.upper()} ({len(raw)} recipes)")
            for i, r in enumerate(raw):
                _print_recipe_summary(i, r)
            print()
        return

    if args.recipe_command == "show":
        raw = _load_raw_slot(args.slot)
        index = _resolve_recipe_index(raw, args.recipe)
        recipe = raw[index]
        print(f"[{index}] {recipe['name']}  ({args.slot})")
        print("Ingredients:")
        for ing in recipe.get("ingredients", []):
            print(f"  - {_format_ingredient(ing)}")
        steps = recipe.get("steps", [])
        if steps:
            print("Steps:")
            for step_number, step in enumerate(steps, start=1):
                print(f"  {step_number}. {step}")
        return

    if args.recipe_command == "add":
        raw = _load_raw_slot(args.slot)
        new_recipe = {
            "name": args.name,
            "ingredients": [_parse_ingredient_arg(i) for i in args.ingredient],
            "steps": args.step,
        }
        raw.append(new_recipe)
        _write_slot_validated(args.slot, raw)
        print(f"Added [{len(raw) - 1}] {args.name} to {args.slot}.")
        return

    if args.recipe_command == "update":
        raw = _load_raw_slot(args.slot)
        index = _resolve_recipe_index(raw, args.recipe)
        recipe = dict(raw[index])
        if args.name is not None:
            recipe["name"] = args.name
        if args.ingredient is not None:
            recipe["ingredients"] = [_parse_ingredient_arg(i) for i in args.ingredient]
        if args.step is not None:
            recipe["steps"] = args.step
        raw[index] = recipe
        _write_slot_validated(args.slot, raw)
        print(f"Updated [{index}] {recipe['name']} in {args.slot}.")
        return


def _week_key(week: int | None) -> str:
    iso_year, iso_week, _ = date.today().isocalendar()
    return f"{iso_year}-W{(week if week is not None else iso_week):02d}"


def _print_adhoc_items(week_key: str, items: list[adhoc.AdhocItem]) -> None:
    print(f"AD-HOC ITEMS ({week_key})")
    if not items:
        print("  (none)")
        return
    for index, item in enumerate(items):
        print(f"  [{index}] {item.display()}")


def handle_adhoc(args: argparse.Namespace) -> None:
    week_key = _week_key(args.week)

    if args.adhoc_command == "list":
        _print_adhoc_items(week_key, adhoc.load_items(week_key))
    elif args.adhoc_command == "add":
        try:
            items = adhoc.add_item(week_key, args.name, args.quantity, args.unit)
        except ValueError as error:
            raise SystemExit(f"error: {error}")
        _print_adhoc_items(week_key, items)
    elif args.adhoc_command == "remove":
        try:
            items = adhoc.remove_item(week_key, args.index)
        except IndexError as error:
            raise SystemExit(f"error: {error}")
        _print_adhoc_items(week_key, items)


def main() -> None:
    args = parse_args()
    if args.command == "adhoc":
        handle_adhoc(args)
        return
    if args.command == "recipe":
        handle_recipe(args)
        return

    if args.reset_pantry:
        reset_state()

    iso_year, iso_week, _ = date.today().isocalendar()
    week_number = args.week if args.week is not None else iso_week
    household = build_household(args.adults, args.children)
    portion_factor = total_portion_factor(household)

    print(f"Planning for: {describe(household)}\n")

    week_plan = generate_week_plan(week_number)
    print_week_plan(week_plan)

    print()
    print_recipe_steps(week_plan)

    print()
    weekly_items = build_weekly_grocery_list(week_plan, portion_factor)
    print_grocery_list("WEEKLY GROCERY LIST (perishables)", weekly_items)

    print()
    if is_biweekly_shopping_week(week_number):
        next_week_plan = generate_week_plan(week_number + 1)
        shopping_cycle_id = f"{iso_year}-W{week_number:02d}"
        biweekly_items = plan_biweekly_purchase(week_plan, next_week_plan, portion_factor, shopping_cycle_id)
        print_grocery_list(
            "BIWEEKLY GROCERY LIST (pantry staples - covers this week and next)",
            biweekly_items,
            empty_message="Fully covered by pantry surplus from previous shops - nothing new to buy.",
        )
    else:
        print("=" * 60)
        print("BIWEEKLY GROCERY LIST (pantry staples)")
        print("=" * 60)
        print("  Not due this week - covered by last week's biweekly shop.")


if __name__ == "__main__":
    main()
