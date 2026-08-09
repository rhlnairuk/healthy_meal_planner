"""Household composition used to scale recipe portions.

The household is built from an adult count and a child count rather than a
fixed list, so the app can be pointed at a different family size via CLI
parameters (see main.py --adults / --children) without editing this file.
Children are assumed to eat roughly half an adult portion; that's a
simplification (a 12-year-old eats more than a toddler) but a reasonable
default absent per-person ages.
"""

from dataclasses import dataclass

ADULT_PORTION = 1.0
CHILD_PORTION = 0.5


@dataclass(frozen=True)
class Person:
    name: str
    portion_factor: float  # relative to one adult portion


def build_household(adults: int, children: int) -> list[Person]:
    if adults < 1:
        raise ValueError(f"Need at least 1 adult in the household, got {adults}.")
    if children < 0:
        raise ValueError(f"children can't be negative, got {children}.")

    household = [Person(f"Adult {i + 1}", ADULT_PORTION) for i in range(adults)]
    household += [Person(f"Child {i + 1}", CHILD_PORTION) for i in range(children)]
    return household


def total_portion_factor(household: list[Person]) -> float:
    return sum(p.portion_factor for p in household)


def describe(household: list[Person]) -> str:
    adults = sum(1 for p in household if p.portion_factor == ADULT_PORTION)
    children = len(household) - adults
    parts = [f"{adults} adult{'s' if adults != 1 else ''}"]
    if children:
        parts.append(f"{children} child{'ren' if children != 1 else ''}")
    return " + ".join(parts)
