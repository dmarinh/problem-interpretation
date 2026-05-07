"""
Build food_taxonomy.csv from the EFSA FoodEx2 MTX catalogue and the PTM
category alignment file.

Inputs:
  --mtx        path to MTX_FULL_X_X.xml (the FoodEx2 catalogue, ~85MB)
  --alignment  path to category_alignment_vN.csv
  --output     path to write food_taxonomy.csv (default: ./food_taxonomy.csv)
  --report     optional path to write a coverage report (text)

Output schema (food_taxonomy.csv):
  food_name             normalized lookup key (lowercase, state and stop-phrases stripped)
  foodex2_code          5-char FoodEx2 term code (e.g. A01SQ)
  foodex2_label         FoodEx2 term name verbatim
  foodex2_parent_code   parent term code in the report hierarchy
  foodex2_parent_label  parent term name verbatim
  ptm_category          one of the in-house PTM categories (poultry, meat, dairy, ...)
  state                 fresh/raw/cooked/smoked/cured/.../unspecified
  scope_note            FoodEx2 scope note (definition) verbatim
  source_id             EFSA-FoodEx2-MTX-12.0

Design notes (Daniel preferences: simple over DRY, readable, no premature abstractions):
- Single module, plain functions, no classes.
- Parsing uses iterparse to keep memory bounded on the 85MB XML.
- Walk is restricted to the 'report' hierarchy. Terms that do not appear
  in 'report' are silently skipped — the report hierarchy is the supported
  general-purpose tree per EFSA documentation.
- A term may legitimately appear under more than one anchor; one row is
  emitted per (anchor, term) pair (option d.i from the design discussion).
- Species-keyword override applies only to descendants walked from the
  A0BXT anchor (processed meat) — see POULTRY_KEYWORDS.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — small curated vocabularies. Kept here for visibility.
# ---------------------------------------------------------------------------

SOURCE_ID = "EFSA-FoodEx2-MTX-12.0"
HIERARCHY = "report"  # the EFSA general-purpose hierarchy

# State extraction. First match wins; MVP keyword set per design discussion.
STATE_KEYWORDS = [
    "fresh", "raw", "cooked", "smoked", "cured", "fermented",
    "dried", "frozen", "canned", "processed", "marinated", "pickled",
]

# Phrases removed from the FoodEx2 label when computing food_name.
# Order matters — longer phrases first to avoid partial overlaps.
STOP_PHRASES = [
    "and primary derivatives thereof",
    "and products thereof",
    "and similar",
    "and products",
    "primary derivatives",
    "meat products",
    "edible offal",
]

# Lone token strip (after stop-phrases). Removed only as whole words.
LONE_STOP_TOKENS = ["meat", "thereof"]

# Species-override keywords for the A0BXT (processed meat) sub-tree.
# A processed-meat term whose name contains any of these is reclassified
# from the default 'meat' to 'poultry'.
POULTRY_KEYWORDS = [
    "chicken", "turkey", "duck", "goose", "quail", "pheasant",
    "partridge", "pigeon", "guinea-fowl", "ratite", "poultry",
]
SPECIES_OVERRIDE_ANCHOR = "A0BXT"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Term:
    code: str
    name: str
    scope_note: str
    parents: dict[str, str]  # hierarchy_code -> parent_code

@dataclass
class AnchorSpec:
    code: str
    ptm_category: str
    apply_species_override: bool  # True only for A0BXT


# ---------------------------------------------------------------------------
# Step 1: parse MTX XML
# ---------------------------------------------------------------------------

def parse_mtx(xml_path: Path) -> dict[str, Term]:
    """Stream-parse the MTX XML into a flat dict of code -> Term."""
    terms: dict[str, Term] = {}
    context = ET.iterparse(str(xml_path), events=("end",))
    for _, elem in context:
        if elem.tag != "term":
            continue
        code = elem.findtext(".//termCode") or ""
        if not code:
            elem.clear()
            continue
        name = elem.findtext(".//termExtendedName") or ""
        scope = elem.findtext(".//termScopeNote") or ""
        parents: dict[str, str] = {}
        for ha in elem.findall(".//hierarchyAssignment"):
            hc = ha.findtext("hierarchyCode")
            pc = ha.findtext("parentCode")
            if hc:
                parents[hc] = pc or ""
        terms[code] = Term(code=code, name=name, scope_note=scope, parents=parents)
        elem.clear()
    return terms


# ---------------------------------------------------------------------------
# Step 2: load alignment, resolve anchor list
# ---------------------------------------------------------------------------

def load_alignment(csv_path: Path) -> list[AnchorSpec]:
    """
    Read the category alignment CSV and return the flat list of anchors
    (DIRECT rows + DESCEND sub-anchors). OUT_OF_SCOPE and DEFER rows
    contribute nothing.
    """
    anchors: list[AnchorSpec] = []
    seen_codes: set[str] = set()
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            treatment = row["treatment"].strip()
            if treatment == "DIRECT":
                code = row["foodex2_code"].strip()
                cat = row["ptm_category"].strip()
                if not cat:
                    raise ValueError(f"DIRECT row {code} has no ptm_category")
                _add_anchor(anchors, seen_codes, code, cat)
            elif treatment == "DESCEND":
                # sub_anchors format: "A0EYF→meat;A0EYG→poultry;A0BXT→meat"
                for chunk in row["sub_anchors"].split(";"):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    sub_code, sub_cat = [p.strip() for p in chunk.split("→")]
                    _add_anchor(anchors, seen_codes, sub_code, sub_cat)
            elif treatment in ("OUT_OF_SCOPE", "DEFER"):
                continue
            else:
                raise ValueError(f"Unknown treatment {treatment!r} for {row['foodex2_code']}")
    return anchors


def _add_anchor(out: list[AnchorSpec], seen: set[str], code: str, cat: str) -> None:
    if code in seen:
        # Two alignment rows targeting the same anchor — surface as error.
        raise ValueError(f"Anchor {code} listed twice in alignment")
    seen.add(code)
    apply_override = (code == SPECIES_OVERRIDE_ANCHOR)
    out.append(AnchorSpec(code=code, ptm_category=cat, apply_species_override=apply_override))


# ---------------------------------------------------------------------------
# Step 3: walk descendants of each anchor in the report hierarchy
# ---------------------------------------------------------------------------

def descendants_of(anchor_code: str, terms: dict[str, Term],
                   hierarchy: str = HIERARCHY) -> list[str]:
    """
    Return all descendant codes (including the anchor itself) of anchor_code
    in the named hierarchy. Order: BFS, deterministic within a single MTX
    snapshot (children iteration follows insertion order of terms dict).
    """
    # Build a children-of map for the hierarchy once. Cheap given ~30k terms.
    children_of: dict[str, list[str]] = defaultdict(list)
    for code, t in terms.items():
        parent = t.parents.get(hierarchy)
        if parent:
            children_of[parent].append(code)

    out: list[str] = []
    seen: set[str] = set()
    queue = [anchor_code]
    while queue:
        code = queue.pop(0)
        if code in seen or code not in terms:
            continue
        seen.add(code)
        out.append(code)
        for child in children_of.get(code, []):
            if child not in seen:
                queue.append(child)
    return out


# ---------------------------------------------------------------------------
# Step 4: normalize FoodEx2 label into food_name + state
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[,.;:\-–—]")
_WS_RE = re.compile(r"\s+")

def normalize_label(label: str) -> tuple[str, str]:
    """
    Return (food_name, state). MVP rules:

    1. Lowercase.
    2. Strip parenthesised content (often scientific or facet annotations).
    3. Find first STATE_KEYWORDS hit, record as state, remove from string.
       Default state = 'unspecified'.
    4. Strip STOP_PHRASES (longest first, already ordered).
    5. Strip LONE_STOP_TOKENS as whole words.
    6. Normalise punctuation and whitespace.

    Examples:
        'Turkey fresh meat'       -> ('turkey', 'fresh')
        'Smoked salmon'           -> ('salmon', 'smoked')
        'Cooked pork ham'         -> ('pork ham', 'cooked')
        'White bread'             -> ('white bread', 'unspecified')
        'Cheese, camembert'       -> ('cheese camembert', 'unspecified')
        'Bovine fresh meat'       -> ('bovine', 'fresh')
    """
    s = label.lower()
    s = _PAREN_RE.sub(" ", s)

    # Extract first state keyword
    state = "unspecified"
    for kw in STATE_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, s):
            state = kw
            s = re.sub(pattern, " ", s, count=1)
            break

    # Strip stop phrases
    for phrase in STOP_PHRASES:
        s = s.replace(phrase, " ")

    # Strip lone stop tokens
    for tok in LONE_STOP_TOKENS:
        s = re.sub(r"\b" + re.escape(tok) + r"\b", " ", s)

    # Punctuation -> space, collapse whitespace
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()

    return s, state


# ---------------------------------------------------------------------------
# Step 5: species-keyword override for A0BXT sub-tree
# ---------------------------------------------------------------------------

def apply_species_override(label: str, default_category: str) -> str:
    """If label contains a poultry species keyword, return 'poultry'.

    Called only for descendants walked from anchor A0BXT — the species-
    agnostic 'Processed or preserved meat' tree where mammal-vs-bird
    products are mixed. See POULTRY_KEYWORDS for the override list.
    """
    label_lower = label.lower()
    for kw in POULTRY_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", label_lower):
            return "poultry"
    return default_category


# ---------------------------------------------------------------------------
# Step 6: build a row per (anchor, descendant) pair
# ---------------------------------------------------------------------------

def build_row(term: Term, anchor: AnchorSpec, terms: dict[str, Term]) -> dict:
    """Build one CSV row for a single (anchor, descendant) pair."""
    food_name, state = normalize_label(term.name)
    parent_code = term.parents.get(HIERARCHY, "")
    parent_label = terms[parent_code].name if parent_code in terms else ""

    if anchor.apply_species_override:
        ptm_category = apply_species_override(term.name, anchor.ptm_category)
    else:
        ptm_category = anchor.ptm_category

    return {
        "food_name": food_name,
        "foodex2_code": term.code,
        "foodex2_label": term.name,
        "foodex2_parent_code": parent_code,
        "foodex2_parent_label": parent_label,
        "ptm_category": ptm_category,
        "state": state,
        "scope_note": term.scope_note,
        "source_id": SOURCE_ID,
    }


# ---------------------------------------------------------------------------
# Step 7: orchestrate
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "food_name", "foodex2_code", "foodex2_label",
    "foodex2_parent_code", "foodex2_parent_label",
    "ptm_category", "state", "scope_note", "source_id",
]

def build_taxonomy(mtx_path: Path, alignment_path: Path) -> list[dict]:
    """End-to-end pipeline. Returns the rows; caller writes the CSV."""
    terms = parse_mtx(mtx_path)
    anchors = load_alignment(alignment_path)

    rows: list[dict] = []
    for anchor in anchors:
        if anchor.code not in terms:
            print(f"  WARNING: anchor {anchor.code} not found in MTX; skipping",
                  file=sys.stderr)
            continue
        for desc_code in descendants_of(anchor.code, terms):
            rows.append(build_row(terms[desc_code], anchor, terms))
    return rows


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: list[dict], report_path: Path) -> None:
    """Coverage stats: row count by anchor, by ptm_category, by state."""
    by_cat = defaultdict(int)
    by_state = defaultdict(int)
    by_anchor_term = defaultdict(set)
    for r in rows:
        by_cat[r["ptm_category"]] += 1
        by_state[r["state"]] += 1
    lines = [
        f"Total rows: {len(rows)}",
        "",
        "By PTM category:",
    ]
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat:<12} {n}")
    lines += ["", "By state:"]
    for st, n in sorted(by_state.items(), key=lambda x: -x[1]):
        lines.append(f"  {st:<14} {n}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mtx", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("food_taxonomy.csv"))
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    print(f"Parsing MTX from {args.mtx} ...", file=sys.stderr)
    rows = build_taxonomy(args.mtx, args.alignment)
    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}", file=sys.stderr)

    if args.report:
        write_report(rows, args.report)
        print(f"Wrote coverage report to {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
