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
```

- `--ingredient` is `NAME:QUANTITY:UNIT` (quantity per one adult portion,
  unit `g`/`ml`/`unit`), repeatable — one flag per ingredient.
- `update` only touches fields you pass. Passing `--ingredient` or `--step`
  replaces that *entire* list (no per-item patch) — if the user wants to
  tweak one ingredient in an existing recipe, run `recipe show` first to get
  the full current list, then pass the whole edited list back.
- Both `show` and `update` take either the exact recipe name or its list
  index from `recipe list`.
- There is no `recipe remove` — deleting a recipe isn't supported by this
  CLI (only the web UI, `webapp.py`, can delete one). Say so if asked rather
  than hand-editing the JSON.

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
