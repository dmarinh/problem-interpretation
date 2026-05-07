"""
Validate that every demand food (from the consolidated test-journal +
sensitivity-analysis list) appears in food_taxonomy.csv.

Run after build_food_taxonomy.py. Exits non-zero if any demand food
fails to resolve. Prints a per-food report regardless.

Match policy: a demand food X is considered resolved if some row's
food_name contains X (case-insensitive substring match) OR if the
foodex2_label contains X. The first match wins; the matching row is
reported so curation gaps are visible.

This is intentionally permissive — the goal is "do we cover this food
at all" not "is the canonical food_name exactly this". Tighter matching
will follow when we wire the bridge into PTM grounding.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Consolidated demand list. Each entry: (demand_food_keywords, source_query_ids)
# Composites that the alignment DEFERRED are not in this list (chicken soup,
# Caesar salad, chili, mixed dairy/deli display).
DEMAND_FOODS = [
    # Test journal Q01–Q17 + B1, B2, C1
    (["chicken"],                "Q02 Q04 Q08 Q11 Q14 Q17 B1 C2 C9"),
    (["bread"],                  "Q03 Q05 Q07 Q12"),
    (["rice"],                   "Q06 A7"),
    (["milk"],                   "Q09 B4"),
    (["camembert"],              "Q10"),
    # Cat A
    (["turkey"],                 "A1 B7 C1 C6"),
    (["beef"],                   "A2 A3"),
    (["lettuce"],                "A4 C7"),
    (["oyster"],                 "A5"),
    (["soft-ripened"],           "A6"),
    (["sausage"],                "A8"),
    (["custard"],                "A9 C10"),
    (["peanut butter"],          "A10"),
    # Cat B
    (["smoked salmon"],          "B5"),
    (["salmon"],                 "B5 B8 B10"),
    (["egg"],                    "B9"),
    (["tuna"],                   "B10"),
    # Cat C
    (["ham"],                    "C3"),
    (["yoghurt"],                "C5"),
    (["tomato"],                 "C8"),
]


def load_taxonomy(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def find_matches(keywords: list[str], rows: list[dict]) -> list[dict]:
    """Find taxonomy rows whose food_name OR foodex2_label contains all keywords.

    Word-boundary matching (with simple plural tolerance) to avoid false hits
    like 'salmon' matching 'salmonberries' or 'ham' matching 'Graham flour',
    while still resolving 'lettuce' against 'Lettuces' and 'oyster' against
    'Oysters'. Returns matches sorted with the most plausible canonical match
    first.
    """
    import re
    kws = [k.lower() for k in keywords]
    # Each pattern: keyword OR keyword+s (simple plural tolerance)
    word_patterns = [re.compile(r"\b" + re.escape(k) + r"s?\b") for k in kws]

    matches = []
    for r in rows:
        haystack = (r["food_name"] + " " + r["foodex2_label"]).lower()
        if all(p.search(haystack) for p in word_patterns):
            matches.append(r)

    # Rank: exact food_name match → starts-with → shortest food_name first
    primary_kw = kws[0]
    def sort_key(r):
        fn = r["food_name"].lower()
        return (
            0 if fn == primary_kw else
            1 if fn == primary_kw + "s" else
            2 if fn.startswith(primary_kw + " ") else
            3 if primary_kw in fn else
            4,
            len(fn),
        )
    matches.sort(key=sort_key)
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--taxonomy", type=Path, required=True,
                        help="Path to food_taxonomy.csv produced by build_food_taxonomy.py")
    args = parser.parse_args(argv)

    rows = load_taxonomy(args.taxonomy)
    print(f"Loaded {len(rows)} rows from {args.taxonomy}\n")
    print(f"{'Demand food':<22} {'Status':<8} {'Top match (foodex2_label → ptm_category)'}")
    print("-" * 100)

    failures = 0
    for keywords, queries in DEMAND_FOODS:
        matches = find_matches(keywords, rows)
        food_label = " ".join(keywords)
        if matches:
            top = matches[0]
            n_extra = len(matches) - 1
            extra = f" (+{n_extra} more)" if n_extra > 0 else ""
            print(f"{food_label:<22} ✓ {len(matches):<5}  "
                  f"{top['foodex2_label'][:55]} → {top['ptm_category']}{extra}")
        else:
            failures += 1
            print(f"{food_label:<22} ✗ MISS   (queries: {queries})")

    print()
    if failures:
        print(f"VALIDATION FAILED: {failures} demand foods unresolved", file=sys.stderr)
        return 1
    print(f"VALIDATION PASSED: all {len(DEMAND_FOODS)} demand foods resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
