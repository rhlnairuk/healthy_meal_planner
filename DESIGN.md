# Design

Architecture notes for anyone extending this codebase. For how to run the
tool, see [README.md](README.md).

## Goals and non-goals

- Deterministically generate a varying weekly meal plan, without needing a
  database, network call, or ML model - it's a fixed pool of hand-picked
  recipes rotated by week number.
- Turn that plan into grocery shopping sized for a specific household, split
  by how often you'd actually buy each ingredient: weekly for perishables,
  biweekly for pantry staples bought in bulk.
- Non-goal: this is not a nutrition optimizer. Recipes are hand-picked for
  balance (protein/veg/carbs/dairy, no whole-nut choking hazards for a young
  child); nothing here computes calories or macros.
- Non-goal: this doesn't place any order or touch a retailer. Output is
  plans and lists for you to shop from - deliberately scoped that way after
  finding that automating a real grocery retailer's site (login behind
  reCAPTCHA, cross-domain SSO, unstable markup) fights you at every step
  and offers no official API to sidestep it. See the "History" note at the
  bottom if you're curious why this isn't in scope.

## Module map

```
household.py                 Builds a household from --adults/--children (portion scaling)
recipes/                      Recipe data, one JSON file per meal slot - not Python
long_life_ingredients.json    Which ingredients are pantry staples, and their real pack sizes
meal_plan.py                  Loads + validates recipes/*.json, weekly rotation, printing
grocery.py                    Loads long_life_ingredients.json; splits recipes into weekly/biweekly lists (pure, no I/O)
pantry.py                     Persists purchase/surplus state across runs; wraps grocery.py's biweekly calc
pantry_state.json             Generated state for pantry.py - not hand-edited, safe to delete
main.py                       CLI glue: argparse, orchestration, output formatting
```

Dependency direction is strictly top-to-bottom in that list - `main.py` is
the only module that imports from all of the others. `pantry.py` imports
from `grocery.py` (its pure helpers) and `meal_plan.py` (types only); it
does not import `household.py` - like `grocery.py`, it just takes a plain
`portion_factor` float.

## Data flow

```
household.build_household(adults, children) ──> total_portion_factor() ─┐
                                                                          ▼
meal_plan.generate_week_plan(week_number) ──> list[DayPlan] ──┬──> print_week_plan()
                                                                ├──> print_recipe_steps()
                                                                ▼
                                  grocery.build_weekly_grocery_list(week_plan, portion_factor)
                                                                ▼
                                                       print_grocery_list()

  (on biweekly-shopping weeks only)
  generate_week_plan(week_number) + generate_week_plan(week_number + 1)
                                                                ▼
              pantry.plan_biweekly_purchase(..., portion_factor, shopping_cycle_id)
                     │ reads/writes pantry_state.json via grocery.raw_totals()
                     │ + grocery.round_up_to_pack() internally
                                                                ▼
                                                       print_grocery_list()
```

`main.py` runs this pipeline top to bottom and prints after each stage.
`portion_factor` is computed once from the CLI-supplied household and passed
into the grocery/pantry functions as a plain float - neither `grocery.py`
nor `pantry.py` has any import of or dependency on `household.py` itself,
they just know how to scale by a number.

## Core data model (`meal_plan.py`)

- `Ingredient(name, quantity, unit)` - `quantity` is always **per one adult
  portion**. `unit` is `"g"`, `"ml"`, or `"unit"` (whole items: eggs,
  bread slices, bananas...).
- `Recipe(name, ingredients, steps)` - `steps` is an ordered tuple of plain
  strings, printed as a numbered list. Recipes never encode quantities in
  the steps text (no "add 40g oats") because the actual amount depends on
  who's eating - see portion scaling below.
- `DayPlan(day, breakfast, lunch, dinner, snack)` - one calendar day's four
  meal slots.

All three are frozen dataclasses: a `Recipe` is a value, not something
mutated in place.

## Recipe data lives outside the code (`recipes/*.json`)

Recipes used to be Python constants in `meal_plan.py`. They now live under
`recipes/` - one JSON file per meal slot (`breakfasts.json`, `lunches.json`,
`dinners.json`, `snacks.json`), each a plain array of recipes in the same
shape as `Recipe`/`Ingredient` above. The goal: adding a recipe should be a
data edit, not a code change - no Python syntax, dataclass constructors, or
tuple trailing-comma gotchas to get right. One file per slot (rather than
one combined file with a section per slot) means a diff or a `git blame` on
"the dinners" only ever touches `dinners.json`, and there's no risk of an
edit to one slot's recipes accidentally colliding with another's in the
same file.

`meal_plan.load_recipe_pools(directory)` reads and validates all four files
at import time (`RECIPES_DIR = Path(__file__).with_name("recipes")`),
raising `ValueError`/`FileNotFoundError` with a message that names the
exact file, index, and field at fault (e.g. `"breakfasts.json[3]
('Overnight oats'), ingredient [1] is missing ['unit']."`) rather than
letting a typo surface later as a confusing `KeyError` deep in
`grocery.py`. Validation checks: each file is a non-empty JSON array, every
recipe has a non-empty `name` and at least one ingredient, every ingredient
has `name`/`quantity`/`unit` with `unit` restricted to `"g"`/`"ml"`/`"unit"`
and `quantity` numeric. `steps` is optional (defaults to empty) since not
every snack needs a method.

The four module-level lists (`BREAKFASTS`, `LUNCHES`, `DINNERS`, `SNACKS`)
are populated once from this load and consumed exactly as before by
`generate_week_plan()` - nothing downstream (grocery aggregation, printing)
knows or cares that the data came from JSON rather than Python literals.

## Weekly rotation algorithm

`generate_week_plan(week_number)` in `meal_plan.py` is the one piece of
"cleverness" in the codebase, so it's worth spelling out:

```python
offset = week_number * len(DAYS) + day_index   # len(DAYS) == 7
recipe = POOL[offset % len(POOL)]
```

Why this shape, instead of `random.choice()` seeded by week number:

- **Determinism without a seed dependency.** Same `week_number` always
  produces the same plan, with no reliance on `random`'s algorithm being
  stable across Python versions.
- **No repeats within a pool cycle.** Because `offset` strictly increases
  across both days and weeks, you don't get the same recipe twice until
  you've cycled through the whole pool - unlike picking independently at
  random per slot, which can repeat a recipe two days running.
- **Default argument ties it to real time.** `week_number` defaults to
  `date.today().isocalendar()[1]`, so calling `generate_week_plan()` with no
  arguments naturally changes as real weeks pass - "the menu changes every
  week" falls out of the calendar rather than needing a cron job or stored
  state.

Known limitation: if a pool's length shares a common factor with 7 (e.g. a
future pool of exactly 7 or 14 recipes), the same day-of-week will always
land on the same recipe across different weeks, even though the week's
*set* of recipes still varies. This doesn't visibly matter at the current
pool sizes (8/8/10/8) but is worth knowing if you resize a pool.

## Portion scaling (`household.py`)

`Person.portion_factor` is a multiplier relative to one adult portion
(`ADULT_PORTION = 1.0`, `CHILD_PORTION = 0.5`). `build_household(adults,
children)` - driven by `main.py`'s `--adults`/`--children` CLI flags -
generates a flat list of `Person`s from those two counts rather than a
household being a fixed constant, so the same codebase serves any family
size without editing a file. `total_portion_factor(household)` sums it down
to a single float, and that's the one number `grocery.py` multiplies every
ingredient quantity by (see Data flow above) - `grocery.py` takes a plain
`portion_factor: float` parameter and has no knowledge of `Person` or
`household.py` at all, which keeps the shopping-cadence logic reusable if
the household model ever gets richer (e.g. per-child ages) without
`grocery.py` needing to change.

This does mean every child is currently assumed to eat the same fraction of
an adult portion regardless of age - a reasonable default, not a modeled
fact. If that stops being good enough, the natural extension is a
`--child-ages` style flag that maps ages to portion factors before calling
`build_household`, rather than changing `grocery.py` at all.

`describe(household)` produces the human-readable summary printed at the
top of a run (e.g. `"2 adults + 1 child"`); it assumes every person's
factor is exactly `ADULT_PORTION` or `CHILD_PORTION` since those are the
only two `build_household` produces - a hand-built household with other
factors would describe oddly, but nothing in the app currently constructs
one that way.

## Weekly vs. biweekly grocery split (`grocery.py`)

Every ingredient is classified once, by name, into one of two shopping
cadences:

- **Weekly (default):** anything *not* in `LONG_LIFE_INGREDIENTS` - fresh
  produce, meat, fish, fresh dairy, bread. Bought fresh for the week it's
  used in, rounded to a flat pack size (`PACK_SIZE_G` 25g / `PACK_SIZE_ML`
  50ml) since fresh items don't have one fixed real-world pack size the way
  tins and bags do.
- **Biweekly:** anything in `LONG_LIFE_INGREDIENTS` - dried goods (oats,
  pasta, rice, lentils), tins (beans, chickpeas, chopped tomatoes, tuna,
  sweetcorn), oils, sauces, and other long-life items. Bought in bulk every
  other week, rounded to *that specific ingredient's* real pack size.

### Long-life ingredient data (`long_life_ingredients.json`)

The classification and its pack sizes both live in one JSON file rather
than Python, for the same reason recipes do: it's a data edit, not a code
change, and it keeps the "is this long-life" question answered in exactly
one place rather than tagged per-`Ingredient` at the recipe level (the same
ingredient name, e.g. "Brown rice", appears across many recipes and must
always shop the same way).

Each entry is `{"name", "unit", "pack_size"}` - `pack_size` is the
real-world minimum you'd buy (a 500g bag, a 400g tin, a 12-pack), not a
rounding increment like the weekly `PACK_SIZE_G`. `load_long_life_ingredients()`
validates the file at import time (same pattern as `meal_plan.py`'s recipe
loader: missing fields, an invalid `unit`, a non-positive `pack_size`, or a
duplicate `name` all fail immediately with a message naming the offending
entry) and builds `LONG_LIFE_INGREDIENTS: dict[name, LongLifeIngredient]` -
membership in this dict is what routes an ingredient to the weekly or
biweekly pool.

`round_up_to_pack()` cross-checks that a long-life ingredient's `unit` in
`long_life_ingredients.json` matches the `unit` actually used for it in
`recipes/*.json`, raising `ValueError` on a mismatch rather than silently
rounding, say, a gram quantity to a millilitre pack size. This is the one
place unit consistency between the two hand-edited data files is enforced,
so a typo in either file surfaces immediately instead of producing a
quietly wrong grocery quantity.

`raw_totals(week_plans, portion_factor, *, long_life)` and
`round_up_to_pack(name, unit, qty, *, long_life)` are deliberately separate,
public functions rather than one combined step, so `pantry.py` (below) can
sit *between* them - subtracting carried-over surplus from the raw total
before it gets rounded. `build_weekly_grocery_list` and
`build_biweekly_grocery_list` are the plain compositions of the two
(aggregate, then round, no surplus involved):

- `build_weekly_grocery_list(week_plan, portion_factor)` aggregates just
  the perishables from **one** week's recipes.
- `build_biweekly_grocery_list(week_plan, next_week_plan, portion_factor)`
  aggregates just the long-life items from **two consecutive weeks'**
  recipes, since a biweekly shop has to last until the next one. This is
  the stateless version - kept for testability and reuse, but `main.py`
  actually calls `pantry.plan_biweekly_purchase()` instead, which wraps
  the same `raw_totals`/`round_up_to_pack` but factors in surplus.

`is_biweekly_shopping_week(week_number)` decides *when* to actually show the
biweekly list: even ISO week numbers. This is an arbitrary but deterministic
and stateless choice - it doesn't require remembering when you last did a
pantry shop, it just falls out of the calendar the same way the menu
rotation does. `main.py` calls it once per run to decide whether to print
the real biweekly list (covering this week + next) or a "not due" note.

`GroceryItem.display()` is the single place formatting is decided (`"300g
Blueberries"` vs `"3 x Apple"`).

## Pantry surplus tracking (`pantry.py`)

Rounding up to a pack size means a biweekly shop routinely buys more than
that cycle needs (need 750g rice, buy a 500g-multiple pack → 1000g, 250g
left over). That leftover is real stock still sitting in the pantry for the
*next* cycle, so treating every biweekly cycle as an independent
from-zero calculation - which is all `grocery.build_biweekly_grocery_list`
does - overstates what you actually need to buy over time. `pantry.py`
closes that loop by remembering the surplus and subtracting it from the
next cycle's raw requirement before rounding again.

**Why this is a separate module rather than folded into `grocery.py`:**
`grocery.py` is pure - no I/O, no state, same inputs always produce the
same outputs, which is what makes it trivial to reason about and test.
Purchase tracking is inherently stateful (it has to persist something
between runs), so it lives in its own module that *uses* `grocery.py`'s
pure `raw_totals`/`round_up_to_pack` rather than making `grocery.py` itself
stateful. This mirrors how `household.py` and `grocery.py` are decoupled
(`grocery.py` takes a plain `portion_factor` float, not a `Person` list) -
each module owns exactly one concern.

**State shape** (`pantry_state.json`, auto-created, not hand-edited):

```json
{
  "last_shopped": "2026-W04",
  "surplus": { "Brown rice": 250.0, "Honey": 0.0, ... },
  "last_purchase": { "Brown rice": 500, "Honey": 340, ... }
}
```

`surplus` is the estimated stock remaining *after* `last_shopped`'s two
weeks of consumption - i.e. what's available to offset the *next* cycle.
`last_purchase` exists purely so a re-run of the same cycle can be
answered by lookup instead of recomputation (see idempotency below).

**The core calculation**, per long-life ingredient, in
`plan_biweekly_purchase()`:

```python
carried = state.surplus.get(name, 0.0)
remaining_need = max(0.0, needed_qty - carried)     # 0 if surplus already covers it
purchase_qty = round_up_to_pack(...) if remaining_need > 0 else 0.0
new_surplus = carried + purchase_qty - needed_qty    # what's left after this cycle's consumption
```

An ingredient with enough surplus (`remaining_need == 0`) is dropped from
the list entirely for that cycle rather than showing a zero - the biweekly
list only ever shows things you actually need to go buy.

`new_surplus` starts as a **copy of the previous surplus dict**, not an
empty one, before any of the above overwrites entries present in this
cycle's `needed` totals. This matters for ingredients that aren't used in
the current fortnight's recipes at all (e.g. an ingredient temporarily out
of rotation) - without the copy, their tracked surplus would silently
vanish from state instead of correctly persisting untouched until a cycle
that needs it again.

**Idempotency.** Each cycle is identified by ISO year + week (e.g.
`"2026-W04"`, computed in `main.py` from `date.today().isocalendar()`, or
paired with `--week` when given). If `plan_biweekly_purchase()` is called
with a `shopping_cycle_id` matching `state.last_shopped`, it skips the
calculation entirely and replays `last_purchase` - so checking your list
twice in the same shopping week shows the same numbers instead of applying
the surplus adjustment a second time (which would double-subtract and
under-recommend). Any *different* `shopping_cycle_id` is treated as a new
cycle and recomputes/commits - there's no guard against going "backwards"
(re-running an older week after a newer one has already been committed);
that's an unhandled edge case on the assumption the tool is run forward
through time as you actually shop, not used to replay history.

**What this doesn't model:** spoilage, eating more or less than a recipe
specifies, snacking outside the meal plan, or a manual top-up shop the tool
doesn't know about. All of these push the tracked surplus away from
reality over time with no way for the tool to detect the drift on its own
- `--reset-pantry` (`main.py`) / `pantry.reset_state()` is the escape
hatch: it deletes `pantry_state.json`, so the next biweekly cycle
recomputes from zero surplus, same as a first-ever run.

## History: why there's no retailer integration

An earlier version of this project logged into Ocado via Playwright browser
automation and added the grocery list straight to a basket. That was pulled
back out after live-testing turned up three compounding problems: none of
the major UK grocery retailers (Ocado, Tesco, Sainsbury's, Asda, Morrisons)
expose an official API for basket/checkout, so the only path is scripting
the real website; Ocado's login form sits behind an invisible reCAPTCHA on a
separate SSO domain, which is exactly the kind of thing likely to flag
scripted credential entry; and the product grid markup was virtualized in
ways that made reliable, stable selectors harder to pin down than expected.
None of that is impossible to work around, but it made the retailer
integration the least stable, most maintenance-heavy part of the project by
far, for a feature that was secondary to the actual goal (a healthy,
varied, low-effort meal plan). Scope was narrowed back to planning and
list-building, which needs nothing but the standard library and has no
external failure modes.

## Extension points

- **New recipes:** append to the relevant file under `recipes/` (see
  README.md for the exact shape). Pool order doesn't matter for
  correctness, only for which week lands on which recipe.
- **Household size:** already a CLI concern (`--adults`/`--children`) - no
  code change needed. Different child portion sizing: edit `CHILD_PORTION`
  in `household.py`.
- **Reclassify an ingredient's shopping cadence, or change its pack size:**
  add, remove, or edit its entry in `long_life_ingredients.json` - see
  README.md for the exact shape.
- **Different biweekly cadence/offset:** `is_biweekly_shopping_week()` is
  the only place that decision lives.
- **Different weekly rounding granularity:** `grocery.py`'s `PACK_SIZE_G` /
  `PACK_SIZE_ML` constants are the only place flat (non-long-life) pack-size
  behavior lives.
- **Stop or reset pantry surplus tracking:** `python main.py --reset-pantry`,
  or delete `pantry_state.json` directly - both clear tracked surplus back
  to zero.
- **Model per-child ages or real spoilage/consumption instead of the
  current simplifying assumptions:** see the callouts in "Portion scaling"
  and "Pantry surplus tracking" above for where each assumption lives.
