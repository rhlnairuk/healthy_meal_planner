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
"""

import argparse
from datetime import date

from grocery import build_weekly_grocery_list, is_biweekly_shopping_week, print_grocery_list
from household import build_household, describe, total_portion_factor
from meal_plan import generate_week_plan, print_recipe_steps, print_week_plan
from pantry import plan_biweekly_purchase, reset_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=None, help="ISO week number to generate the menu for (default: current week).")
    parser.add_argument("--adults", type=int, default=2, help="Number of adults to plan and shop for (default: 2).")
    parser.add_argument("--children", type=int, default=1, help="Number of children to plan and shop for (default: 1).")
    parser.add_argument("--reset-pantry", action="store_true", help="Forget tracked pantry surplus before planning this run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
