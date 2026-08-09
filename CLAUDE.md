# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python3 main.py                         # generate current week's plan (default: 2 adults, 1 child)
python3 main.py --adults 2 --children 2 # size shopping for a different household
python3 main.py --week 32               # generate a specific ISO week instead of the current one
python3 main.py --reset-pantry          # clear tracked pantry surplus and start over
```

No dependencies beyond the Python standard library, no build step, no test suite. The `.venv/`
contains leftover Playwright packages from an abandoned retailer-integration attempt (see
DESIGN.md's "History" section) - not used by any current code.

## Architecture

Read [DESIGN.md](DESIGN.md) before making non-trivial changes - it documents the reasoning behind
every module boundary in detail. Short version:

```
household.py                 Builds a household from --adults/--children (portion scaling)
recipes/*.json                Recipe data, one JSON file per meal slot - not Python
long_life_ingredients.json    Which ingredients are pantry staples, and their real pack sizes
meal_plan.py                  Loads + validates recipes/*.json, weekly rotation, printing
grocery.py                    Loads long_life_ingredients.json; splits recipes into weekly/biweekly lists (pure, no I/O)
pantry.py                     Persists purchase/surplus state across runs; wraps grocery.py's biweekly calc
pantry_state.json             Generated state for pantry.py - not hand-edited, safe to delete
main.py                       CLI glue: argparse, orchestration, output formatting
```

Dependency direction is strictly top-to-bottom in that list: `main.py` is the only module that
imports from all of the others. `grocery.py` and `pantry.py` take a plain `portion_factor: float`
and know nothing about `household.py` or `Person` - keeps shopping-cadence logic reusable
independent of how a household is modeled. `pantry.py` uses `grocery.py`'s pure
`raw_totals()`/`round_up_to_pack()` rather than making `grocery.py` itself stateful.

Key mechanisms worth knowing before touching them:

- **Weekly rotation** (`meal_plan.generate_week_plan`): `offset = week_number * 7 + day_index`,
  `recipe = POOL[offset % len(POOL)]`. Deterministic per week number (no `random` seed
  dependency), and no repeats within a pool cycle. If a pool's length shares a common factor with
  7, the same day-of-week lands on the same recipe across different weeks - noted as a known
  limitation in DESIGN.md.
- **Weekly vs. biweekly split** (`grocery.py`): an ingredient is biweekly (pantry staple) iff its
  name is in `LONG_LIFE_INGREDIENTS` (loaded from `long_life_ingredients.json`); everything else
  is weekly (perishable). Biweekly items round to *that ingredient's* real pack size; weekly items
  round to the flat `PACK_SIZE_G`/`PACK_SIZE_ML` constants. `is_biweekly_shopping_week()` (even
  ISO week numbers) is the only place that decides *when* the biweekly list is shown.
- **Pantry surplus tracking** (`pantry.py`): rounding up to a pack size overbuys, so leftover
  quantity is persisted in `pantry_state.json` and subtracted from the next cycle's raw need
  before rounding again. Keyed by `shopping_cycle_id` (`"{iso_year}-W{week:02d}"`) for
  idempotency - replaying the same cycle returns the same numbers instead of double-subtracting.
  This is an estimate (no spoilage/snacking/manual-restock modeling); `--reset-pantry` is the
  escape hatch.
- **Data-not-code**: recipes (`recipes/*.json`) and long-life classification
  (`long_life_ingredients.json`) are hand-edited JSON, not Python literals, so adding a recipe or
  reclassifying an ingredient's shopping cadence never requires a code change. Both are validated
  at load time with errors naming the exact file/index/field at fault - see README.md for the
  required shapes and validation rules before editing either file.

## Core data model (`meal_plan.py`)

All frozen dataclasses (values, not mutated in place):

- `Ingredient(name, quantity, unit)` - `quantity` is always **per one adult portion**; `unit` is
  `"g"`, `"ml"`, or `"unit"`.
- `Recipe(name, ingredients, steps)` - `steps` never encode quantities (those vary by household
  size).
- `DayPlan(day, breakfast, lunch, dinner, snack)`.
