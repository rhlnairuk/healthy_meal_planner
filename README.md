# Healthy Meal Planner

Generates a healthy weekly meal plan for your household - a menu that
changes automatically from week to week - along with cooking steps for each
meal and the grocery shopping needed to make it, sized for however many
adults and children you're planning for:

- A **weekly list** of perishables (fresh produce, meat, fish, fresh dairy,
  bread) sized for that week alone.
- A **biweekly list** of pantry staples (dried goods, tins, oils, sauces,
  long-life items) sized to cover two weeks at once, appearing only on the
  weeks that bulk shop is due - and reduced by however much is estimated to
  still be left over from previous shops (see "Pantry tracking" below).

For how the code is put together, see [DESIGN.md](DESIGN.md).

## Setup

No dependencies beyond the Python standard library - just run it.

```bash
cd healthy_meal_planner
python3 main.py
```

## Usage

```bash
python main.py                        # default household (2 adults, 1 child), current week
python main.py --adults 2 --children 2  # size shopping for a different household
python main.py --week 32              # generate a specific ISO week instead of the current one
python main.py --reset-pantry         # forget tracked pantry surplus and start over
```

`--adults` (default 2) and `--children` (default 1) control how much gets
bought - a child counts as half an adult portion. There's no `--adults 0`;
the household needs at least one adult.

A run of `main.py` prints, in order:

0. **Household summary** - who you're planning for (e.g. "2 adults + 1 child").
1. **Weekly meal plan** - breakfast/lunch/dinner/snack for each of the 7 days.
2. **Recipes** - numbered cooking steps for each distinct meal used that week.
3. **Weekly grocery list** - perishable ingredients needed for that week only.
4. **Biweekly grocery list** - pantry staples, sized to cover this week and
   next. Only printed on the weeks it's due (even ISO week numbers); on
   off-weeks it prints a note that the pantry shop already covers you.

### Ad-hoc items (one-offs not tied to any recipe)

The web UI's "Extra Items" screen has a CLI equivalent for scripting or
headless use:

```bash
python main.py adhoc list                          # this week's ad-hoc items
python main.py adhoc add "Paper towels" 6 unit      # literal quantity, not scaled by household size
python main.py adhoc remove 0                       # remove by the index shown in 'list'
python main.py adhoc list --week 32                 # any of the three accept --week
```

These are stored in `adhoc_items.json`, keyed by ISO week, same as the web
UI - either interface sees the other's edits.

### Getting the same menu every week (or a fresh one on demand)

The menu is derived from the ISO week number, so:

- Run it any day this week and you get the same plan (useful if you re-run
  the script mid-week).
- Next calendar week, it automatically rotates to different recipes.
- `--week N` lets you preview or regenerate a specific week's menu, e.g. to
  plan ahead or re-print a shopping list you lost.

## Web UI

A local browser UI is also available, for viewing this week's and next
week's menu, and for editing recipes, pantry-staple classification, and
one-off "extra" shopping items without hand-editing JSON:

```bash
python3 webapp.py
```

This starts a local server at `http://localhost:8765` and opens it in your
default browser. Stdlib only, same as the CLI - no extra install step.
Screens:

- **This Week / Next Week** - the same day-by-day menu, recipes, and
  grocery lists `main.py` prints, browsable without re-running a command.
- **Recipes** - add, edit, or delete recipes per meal slot. Writes go
  straight to `recipes/*.json`, validated the same way `main.py` validates
  them on startup - an invalid edit is rejected with the exact error and
  the file on disk is left untouched.
- **Pantry Staples** - add, edit, or delete entries in
  `long_life_ingredients.json` (see "Marking an ingredient as long-life"
  below).
- **Extra Items** - one-off items to buy for a given week that aren't tied
  to any recipe (e.g. paper towels). These are literal quantities, not
  scaled by household size, and always shown separately from the
  weekly/biweekly totals.

Stop the server with Ctrl+C. `python3 main.py` continues to work exactly as
before and doesn't require the server to be running.

### Running the web UI in Docker

```bash
docker build -t healthy-meal-planner .
docker run --rm -p 8765:8765 -v "$(pwd):/app" healthy-meal-planner
```

Or, with Compose:

```bash
docker compose up --build
```

Either way, open `http://localhost:8765` in your browser - same UI as
running `python3 webapp.py` directly.

`-v "$(pwd):/app"` (or the equivalent `volumes:` entry in
`docker-compose.yml`) bind-mounts the whole project directory into the
container, rather than baking `recipes/*.json`, `long_life_ingredients.json`,
`pantry_state.json`, and `adhoc_items.json` into the image. That means:

- Every JSON file stays a real file on your Mac - open it in any text
  editor, `git`-track it, back it up - exactly as if you weren't using
  Docker at all.
- Edits made through the UI while running in Docker land on your host
  filesystem immediately, and survive `docker compose down` / removing the
  container.
- Edits made by hand on the host (not through the UI) are picked up the
  next time the **This Week / Next Week** view loads - no container
  restart needed.

Without the volume mount (a plain `docker run -p 8765:8765
healthy-meal-planner`), the app still runs, but against whatever
`recipes/*.json` etc. looked like at `docker build` time, and any edits
made through the UI live only inside that container's writable layer -
gone on `docker rm`. The mount is what makes the data "live on the
machine," not just the container running at all.

The same image can run the CLI instead of the web UI, by overriding the
container command - useful if you'd rather script `main.py` than open a
browser, without installing Python locally:

```bash
docker run --rm -v "$(pwd):/app" healthy-meal-planner python3 main.py --week 32
```

## Adding a new recipe

The web UI's "Recipes" screen has a CLI equivalent for scripting or headless
use - it validates the same way `main.py` does at startup, so an invalid
edit is rejected with the exact error and the file on disk is left
untouched:

```bash
python main.py recipe list                     # every slot, name + ingredient count
python main.py recipe list dinners              # one slot only
python main.py recipe show dinners "Beans on toast"   # or by index: recipe show dinners 3
python main.py recipe add dinners "Beans on toast" \
    --ingredient "Baked beans:120:g" --ingredient "Wholemeal bread:1:unit" \
    --step "Warm the beans in a small pan." --step "Toast the bread and spoon the beans over."
python main.py recipe update dinners "Beans on toast" --step "New step 1." --step "New step 2."
python main.py recipe remove dinners "Beans on toast"
```

Notes:

- `--ingredient` takes `NAME:QUANTITY:UNIT` (quantity is per one adult
  portion, unit is `g`/`ml`/`unit`) and is repeatable - pass it once per
  ingredient.
- `recipe update` only changes the fields you pass; `--ingredient` or
  `--step`, if given at all, replaces that whole list rather than merging
  with the old one (there's no way to tweak a single ingredient in place
  without re-listing all of them).
- `show`, `update`, and `remove` all accept either the recipe's exact name
  or its index from `recipe list`.
- `recipe remove` refuses to remove the last recipe in a slot - each meal
  slot needs at least one. To fully replace a slot's recipes, `add` the
  replacements first, then `remove` the old ones by name.

Recipes live under [recipes/](recipes) - one JSON file per meal slot, if you
prefer to hand-edit the JSON directly instead:

```
recipes/
  breakfasts.json
  lunches.json
  dinners.json
  snacks.json
```

Each file is a plain JSON array of recipes. To add one, open the file for
the right meal slot and append an entry in the same shape as its neighbors:

```json
{
  "name": "Beans on toast",
  "ingredients": [
    { "name": "Baked beans", "quantity": 120, "unit": "g" },
    { "name": "Wholemeal bread", "quantity": 1, "unit": "unit" }
  ],
  "steps": [
    "Warm the beans in a small pan.",
    "Toast the bread and spoon the beans over."
  ]
}
```

Rules:

- `quantity` is always **per one adult portion** - `household.py` scales it
  for the rest of the household automatically.
- `unit` must be `"g"`, `"ml"`, or `"unit"` (for whole items like eggs or
  bread slices).
- `steps` don't mention quantities (those vary by household size) - just the
  method.
- If the recipe uses an ingredient name that's a pantry staple (tins, dried
  goods, oils) rather than something fresh, add it to
  [long_life_ingredients.json](long_life_ingredients.json) so it lands on
  the biweekly list instead of the weekly one - see the next section.

Save the file and run the app - the new recipe joins the rotation on its
next turn automatically, no code changes needed. If the JSON is malformed or
a recipe is missing a required field, `main.py` will fail immediately with a
message naming the exact recipe and field at fault, rather than silently
skipping it.

## Marking an ingredient as long-life (biweekly)

[long_life_ingredients.json](long_life_ingredients.json) is a JSON array
that decides two things per pantry-staple ingredient: that it belongs on
the biweekly list at all, and the real pack size it gets rounded up to
(rather than the flat weekly rounding):

```json
{ "name": "Brown rice", "unit": "g", "pack_size": 500 }
```

- `name` must match the ingredient's `name` exactly as used in `recipes/*.json`.
- `unit` must match how that ingredient is used in recipes (`"g"`, `"ml"`,
  or `"unit"`) - a mismatch fails loudly at startup rather than silently
  producing a wrong quantity.
- `pack_size` is the smallest real unit you'd buy it in - a 500g bag, a
  400g tin, a 12-pack of rice cakes. The biweekly list rounds each
  ingredient's total up to a multiple of this, so "830g Baked beans" reads
  as "2 tins" rather than an arbitrary number.

An ingredient *not* listed here defaults to the weekly, perishable list,
rounded to a flat `PACK_SIZE_G` (25g) / `PACK_SIZE_ML` (50ml) instead -
those constants live in `grocery.py` if you want to change the weekly
rounding granularity.

## Pantry tracking (surplus from previous shops)

Rounding up to a pack size almost always buys a bit more than a cycle
needs - a 500g bag of rice for a 250g need leaves 250g still in the pantry.
The app remembers that in `pantry_state.json` (created automatically on
first run) and subtracts it from the *next* biweekly cycle's requirement
before rounding again, so quantities trend down over time instead of every
cycle rounding up in isolation - an ingredient with enough surplus is
dropped from the list entirely for a cycle.

This is an estimate, not a real stocktake: it assumes every gram bought
gets used exactly per the meal plan, with no spoilage, no eating more or
less than a recipe calls for, and no untracked snacking or manual top-up
shops. If reality has drifted from that assumption - you did a big manual
pantry restock, or skipped several biweekly cycles without buying what was
recommended - run `python main.py --reset-pantry` to clear the tracked
surplus and start over from zero.

Re-running the same shopping week's plan replays what was already
recorded rather than recomputing (so checking your list twice in the same
week doesn't double-subtract surplus). `pantry_state.json` is generated
state, not something to hand-edit - delete it any time to reset tracking,
same as `--reset-pantry`.

## Customizing

- **Household size:** use `--adults` / `--children` (see Usage above) - no
  file editing needed.
- **Child portion size:** edit `CHILD_PORTION` in `household.py` if 0.5x an
  adult portion doesn't fit your kids' ages (all children currently share
  one factor).

See [DESIGN.md](DESIGN.md) for the reasoning behind these modules and how
they fit together.
