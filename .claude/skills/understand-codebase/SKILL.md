---
name: understand-codebase
description: Explain how the healthy meal planner codebase works, orient a new contributor, or answer "how does X work" / "where does Y live" questions about this project. Use before non-trivial changes and whenever the user asks to understand, explore, or get oriented in this repo.
---

# Understanding the healthy meal planner codebase

This repo has already written down its own architecture rationale in detail.
The job of this skill is to **answer from those docs and the real source**,
not to re-derive design intent from scratch by re-reading code in isolation.

## Order of operations

1. **Read `DESIGN.md` first, in full**, before answering any "why" or "how"
   question. It documents the reasoning behind every module boundary,
   including things that aren't obvious from code alone (e.g. why `pantry.py`
   is a separate module from `grocery.py`, why recipes live in JSON not
   Python, why there's no retailer integration).
2. **Read `README.md`** for user-facing behavior: CLI flags, output shape,
   the JSON schema for `recipes/*.json` and `long_life_ingredients.json`.
3. **Only then read source files**, and only the ones relevant to the
   question — use `DESIGN.md`'s module map to go straight to the right file
   instead of scanning everything.

## Module map (top-to-bottom = dependency direction)

```
household.py                 Builds a household from --adults/--children (portion scaling)
recipes/*.json                Recipe data, one JSON file per meal slot - not Python
long_life_ingredients.json    Which ingredients are pantry staples, and their real pack sizes
meal_plan.py                  Loads + validates recipes/*.json, weekly rotation, printing
grocery.py                    Pure: splits recipes into weekly/biweekly lists, no I/O
pantry.py                     Persists purchase/surplus state; wraps grocery.py's biweekly calc
pantry_state.json             Generated state for pantry.py - not hand-edited
main.py                       CLI glue: argparse, orchestration, output formatting
webapp.py / web/              Web UI on top of the same core modules
```

`main.py` is the only module that imports from all of the others. `grocery.py`
and `pantry.py` are deliberately decoupled from `household.py` — they take a
plain `portion_factor: float` and know nothing about `Person` objects.

## Mechanisms worth citing precisely, not paraphrasing

When asked about these, quote the actual mechanism (with file:line) rather
than a generic description — each one has a specific reason behind its shape
that's easy to get subtly wrong if reconstructed from memory:

- **Weekly rotation** — `meal_plan.generate_week_plan`: deterministic
  `offset = week_number * 7 + day_index; POOL[offset % len(POOL)]`, not
  `random.choice()`. Known limitation if a pool length shares a factor with 7.
- **Weekly vs biweekly split** — `grocery.py`: membership in
  `LONG_LIFE_INGREDIENTS` (from `long_life_ingredients.json`) decides the
  cadence, not anything in the recipe data itself.
- **Pantry surplus** — `pantry.py`: rounding up to pack sizes overbuys, so
  leftover is persisted in `pantry_state.json` keyed by
  `shopping_cycle_id` (`"{iso_year}-W{week:02d}"`) for idempotent replay.
- **Data-not-code** — `recipes/*.json` and `long_life_ingredients.json` are
  hand-edited data validated at load time with errors naming the exact
  file/index/field at fault. Adding a recipe or reclassifying an ingredient
  is a data edit, never a code change.

## When answering

- Cite `path:line` for anything you point to in source.
- If a question is about *why* something is shaped a certain way, check
  `DESIGN.md` before speculating — it very likely already has the answer,
  including known limitations and rejected alternatives (e.g. the Playwright
  retailer-integration history at the bottom of `DESIGN.md`).
- If the user is about to make a change, flag which module boundary or
  invariant (from "Mechanisms" above) the change would touch, using
  `DESIGN.md`'s "Extension points" section as a starting guide.
- Don't restate all of `DESIGN.md` back to the user — pull out only what's
  relevant to their actual question.
