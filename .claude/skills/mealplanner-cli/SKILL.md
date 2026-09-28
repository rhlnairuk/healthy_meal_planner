---
name: mealplanner-cli
description: Use main.py's command line (plan generation, ad-hoc items, recipe management) to actually perform meal-planner actions the user asks for in natural language - generating a plan, checking/adding groceries, or adding/updating/listing recipes - instead of hand-editing JSON or re-deriving logic that already exists in the CLI.
---

# Operating the meal planner via its CLI

`main.py` is the supported interface for every mutation in this repo
(recipes, ad-hoc items, pantry state, plan generation). When the user asks
for something this CLI already does, **run it via Bash** rather than editing
`recipes/*.json` / `adhoc_items.json` / `pantry_state.json` by hand — the
CLI validates input and writes atomically; hand-edits skip both.

## Command reference

### Plan generation (default command, no subcommand)

```bash
python3 main.py                          # current week, 2 adults + 1 child
python3 main.py --adults 2 --children 2  # different household size
python3 main.py --week 32                # a specific ISO week
python3 main.py --reset-pantry           # clear tracked pantry surplus
```

Prints: household summary, 7-day meal plan, cooking steps, weekly grocery
list (perishables), and the biweekly list (pantry staples) if due that week.

### Ad-hoc items (one-offs not tied to a recipe, e.g. "add paper towels")

```bash
python3 main.py adhoc list [--week N]
python3 main.py adhoc add "<name>" <quantity> <g|ml|unit> [--week N]
python3 main.py adhoc remove <index> [--week N]
```

`--week` defaults to the current ISO week on all three. Quantity is literal
(not scaled by household size). Get the index for `remove` from `adhoc list`
first if the user didn't give one.

### Recipes

```bash
python3 main.py recipe list [slot]                          # slot: breakfasts|lunches|dinners|snacks
python3 main.py recipe show <slot> <name-or-index>
python3 main.py recipe add <slot> "<name>" --ingredient "NAME:QTY:UNIT" [...] [--step "..." [...]]
python3 main.py recipe update <slot> <name-or-index> [--name ...] [--ingredient ...] [--step ...]
python3 main.py recipe remove <slot> <name-or-index>
```

- `--ingredient` is `NAME:QUANTITY:UNIT` (quantity per one adult portion,
  unit `g`/`ml`/`unit`), repeatable — one flag per ingredient.
- `update` only touches fields you pass. Passing `--ingredient` or `--step`
  replaces that *entire* list (no per-item patch) — if the user wants to
  tweak one ingredient in an existing recipe, run `recipe show` first to get
  the full current list, then pass the whole edited list back.
- `show`, `update`, and `remove` all take either the exact recipe name or
  its list index from `recipe list`.
- `remove` refuses to empty a slot to zero (each meal slot needs at least
  one recipe) — to fully replace a slot's recipes, `add` the new ones first,
  then `remove` the old ones by name; never rely on index numbers staying
  put across a `remove`, since later indices shift down.

## Recipe workflows

### Add a new recipe

1. Pick the right slot (`breakfasts`/`lunches`/`dinners`/`snacks`) from what
   the request describes — a dish eaten as a main evening meal is `dinners`,
   not `lunches`, even if it could technically work for either.
2. Check `long_life_ingredients.json` (read the file, there's no CLI for it)
   for each ingredient name. If an ingredient you're about to use already
   exists there, **reuse its exact name and unit** — this is what makes it
   land on the biweekly pantry list at the right pack size instead of
   silently defaulting to the weekly perishable list. A near-miss name
   (`"brown rice"` vs `"Brown rice"`) is treated as a different ingredient.
3. Quantities in `--ingredient` are **per one adult portion** — household
   scaling happens later in `grocery.py`, don't pre-multiply for the
   household size yourself.
4. If the household includes a young child (check `main.py`'s default
   `--children`/DESIGN.md's stated goals), avoid listing whole nuts/hard
   choking-hazard items as an ingredient on their own — use a prepared form
   in the name, e.g. `"Roasted peanuts, crushed"`, `"Almond butter"`, the
   same way the existing recipes do.
5. Run `recipe add <slot> "<name>" --ingredient "N:Q:U" [...] --step "..." [...]`.
   `--step` is optional but should never mention a quantity (steps are
   shared across household sizes).
6. If it errors, the message names the exact bad field (bad unit, malformed
   `NAME:QTY:UNIT`, non-numeric quantity) — fix that one thing and re-run;
   the file was never touched on failure, so there's nothing to undo.
7. Confirm with `recipe show <slot> "<name>"`.

### Update an existing recipe

1. Resolve the recipe first with `recipe show <slot> <name-or-index>` if you
   don't already have its exact name/index — don't guess.
2. Decide what's actually changing:
   - Renaming only → `--name`.
   - Changing any ingredient → pass **every** ingredient via `--ingredient`,
     not just the changed one; `update` replaces the whole list, it doesn't
     patch a single entry. Start from the output of `recipe show` and edit
     that.
   - Changing steps → same rule, pass the full new steps list.
3. Run `recipe update <slot> <name-or-index> [--name ...] [--ingredient ...] [--step ...]`.
4. Confirm with `recipe show` again.

### Delete a recipe

1. Resolve it with `recipe list <slot>` or `recipe show` first if the user
   gave a name that might not match exactly.
2. Run `recipe remove <slot> <name-or-index>`.
3. It fails if the recipe is the last one left in that slot (every slot
   needs at least one) — if the goal is to replace it rather than have zero
   recipes in that slot, add the replacement first (step 4 below).
4. **To replace some or all recipes in a slot** (e.g. "swap out the dinner
   recipes for X"): `add` every replacement recipe first, *then* `remove`
   every recipe you're retiring, referencing each by its exact name (not
   index — indices shift down after every `remove`, so a name is the only
   reference that stays valid across the whole batch). This keeps the slot
   non-empty at every intermediate step and makes each removal independently
   safe to re-run if one fails partway through.

## Working from a natural-language request

1. Map the request to the narrowest matching command above rather than the
   broadest one — e.g. "what's for dinner this week" is `python3 main.py`
   (or `--week N`), not a `recipe list`.
2. If a request needs an index (`adhoc remove`, `recipe show`/`update` by
   position) and the user only gave a name or description, run the
   corresponding `list`/`show` first to resolve it — don't guess an index.
3. Surface the command's own error text verbatim (it already names the
   exact field/value at fault, e.g. `error: ... has unit 'kg', must be 'g',
   'ml', or 'unit'.`) rather than re-explaining or retrying blindly.
4. Recipe/ad-hoc writes land in git-tracked files (`recipes/*.json`,
   `adhoc_items.json`) — after a batch of changes, mention what changed
   (`git diff --stat`) so the user can see it before committing. Don't
   commit on their behalf unless asked.
5. `--reset-pantry` discards tracked surplus state — treat it like any other
   state-clearing action and confirm with the user first if it wasn't the
   explicit ask.
