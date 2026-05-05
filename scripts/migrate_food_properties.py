"""
Migrate data/rag/food_properties.csv to per-field source attribution.

Old schema: food_name, food_category, ph_min, ph_max, aw_min, aw_max, notes, source_id
New schema: food_name, food_category, ph_min, ph_max, ph_source_id, aw_min, aw_max, aw_source_id, notes

All validation must pass before the CSV is written. Any failure aborts with a
diagnostic and leaves the original file untouched.

Writes:
  data/rag/food_properties.csv         (in place, overwriting old schema)
  migration_artifacts/csv_migration_diff.md
"""

import csv
import re
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT      = Path(__file__).parent.parent
INPUT_CSV      = REPO_ROOT / "data" / "rag" / "food_properties.csv"
SOURCE_REF_CSV = REPO_ROOT / "data" / "sources" / "source_references.csv"
OUTPUT_DIR     = REPO_ROOT / "migration_artifacts"
DIFF_FILE      = OUTPUT_DIR / "csv_migration_diff.md"

NEW_HEADER = [
    "food_name", "food_category",
    "ph_min", "ph_max", "ph_source_id",
    "aw_min",  "aw_max",  "aw_source_id",
    "notes",
]

# ── Multi-source rows (reviewed migration_artifacts/multi_source_rows.md) ─────
# Keys are 0-indexed row_index (header excluded, blank/comment rows not counted).
MULTI_SOURCE: dict[int, dict[str, str]] = {
    14:  {"ph": "FDA-PH-2007", "aw": "IFT-2003-T31"},
    211: {"ph": "FDA-PH-2007", "aw": "IFT-2003-T31"},
    233: {"ph": "FDA-PH-2007", "aw": "IFT-2003-T31"},
    234: {"ph": "FDA-PH-2007", "aw": "IFT-2003-T31"},
}

# Notes cleanup: strip attribution fragments now encoded in ph/aw_source_id columns.
# Applied only to the 4 known multi-source rows; all other notes are left verbatim.
CLEANED_NOTES: dict[int, str] = {
    14:  "Hard aged cheese",
    211: "White bread",
    233: "Raw honey",
    234: "Pure maple syrup",
}

# Row-order anchors: food_properties_N = row_index N (test-journal doc-ID mapping).
# Validation #8 asserts all seven match after migration.
ROW_ORDER_ANCHORS: dict[int, str] = {
    4:   "milk acidophilus",
    14:  "cheese parmesan",
    25:  "fresh meat",
    184: "pimiento canned acidified",
    211: "bread white",
    220: "rice white cooked",
    229: "uncooked rice",
}


# ── Source registry ─────────────────────────────────────────────────────────────

def load_valid_source_ids() -> frozenset:
    with open(SOURCE_REF_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return frozenset(row["source_id"] for row in reader if row.get("source_id"))


# ── Transform ──────────────────────────────────────────────────────────────────

def transform() -> tuple[list[dict], list[dict]]:
    """
    Read INPUT_CSV and return (old_rows, new_rows).

    Each element is a dict with 'row_index' added.  Blank rows and comment rows
    (food_name starts with '#') are skipped and do not increment row_index, matching
    the ChromaDB doc-ID assignment logic in app/rag/vector_store.py.
    """
    old_rows: list[dict] = []
    new_rows: list[dict] = []
    row_index = -1

    with open(INPUT_CSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            food_name = row.get("food_name", "")
            if not food_name or food_name.startswith("#"):
                continue
            row_index += 1

            old_source = row.get("source_id", "")
            ph_min = row.get("ph_min", "")
            ph_max = row.get("ph_max", "")
            aw_min = row.get("aw_min", "")
            aw_max = row.get("aw_max", "")
            has_ph = bool(ph_min or ph_max)
            has_aw = bool(aw_min or aw_max)

            if row_index in MULTI_SOURCE:
                ph_src = MULTI_SOURCE[row_index]["ph"] if has_ph else ""
                aw_src = MULTI_SOURCE[row_index]["aw"] if has_aw else ""
                notes  = CLEANED_NOTES[row_index]
            else:
                ph_src = old_source if has_ph else ""
                aw_src = old_source if has_aw else ""
                notes  = row.get("notes", "")

            old_rows.append({
                "row_index":     row_index,
                "food_name":     food_name,
                "food_category": row.get("food_category", ""),
                "ph_min":        ph_min,
                "ph_max":        ph_max,
                "aw_min":        aw_min,
                "aw_max":        aw_max,
                "notes":         row.get("notes", ""),
                "source_id":     old_source,
            })
            new_rows.append({
                "row_index":     row_index,
                "food_name":     food_name,
                "food_category": row.get("food_category", ""),
                "ph_min":        ph_min,
                "ph_max":        ph_max,
                "ph_source_id":  ph_src,
                "aw_min":        aw_min,
                "aw_max":        aw_max,
                "aw_source_id":  aw_src,
                "notes":         notes,
            })

    return old_rows, new_rows


# ── Validate ───────────────────────────────────────────────────────────────────

def validate(
    old_rows: list[dict],
    new_rows: list[dict],
    valid_ids: frozenset,
) -> None:
    """
    Run all 8 validation checks against the in-memory transformed data.
    Calls sys.exit(1) on any failure — CSV is never written if this raises.
    """
    errors: list[str] = []
    bracket_re = re.compile(r'\[[A-Z]{2,}-[A-Z0-9\-]+\]')
    idx_to_new = {r["row_index"]: r for r in new_rows}

    # 1. Row count
    if len(new_rows) != 252:
        errors.append(f"Row count: expected 252, got {len(new_rows)}")

    for r in new_rows:
        idx  = r["row_index"]
        name = r["food_name"]

        # 2. Non-empty pH range → non-empty ph_source_id
        if (r["ph_min"] or r["ph_max"]) and not r["ph_source_id"]:
            errors.append(f"row {idx} ({name}): has pH range but ph_source_id is empty")

        # 3. Non-empty aw range → non-empty aw_source_id
        if (r["aw_min"] or r["aw_max"]) and not r["aw_source_id"]:
            errors.append(f"row {idx} ({name}): has aw range but aw_source_id is empty")

        # 4. Every non-empty source ID value appears in source_references.csv
        for field, val in [("ph_source_id", r["ph_source_id"]), ("aw_source_id", r["aw_source_id"])]:
            if val and val not in valid_ids:
                errors.append(f"row {idx} ({name}): {field}={val!r} not in source_references.csv")

        # 6. No residual source-ID attribution fragments in notes (silent-mention guard).
        #    Checks both literal source IDs and bracket-pattern [SOURCE-ID] syntax.
        notes = r["notes"]
        for sid in valid_ids:
            if sid in notes:
                errors.append(f"row {idx} ({name}): notes still contains source ID {sid!r}")
        if bracket_re.search(notes):
            errors.append(f"row {idx} ({name}): notes contains a bracket-style source citation")

    # 5. Multi-source attributions match the reviewed report
    for ridx, expected in MULTI_SOURCE.items():
        r = idx_to_new.get(ridx)
        if r is None:
            errors.append(f"Multi-source row {ridx} not found in migrated data")
            continue
        if (r["ph_min"] or r["ph_max"]) and r["ph_source_id"] != expected["ph"]:
            errors.append(
                f"row {ridx}: ph_source_id={r['ph_source_id']!r}, expected {expected['ph']!r}"
            )
        if (r["aw_min"] or r["aw_max"]) and r["aw_source_id"] != expected["aw"]:
            errors.append(
                f"row {ridx}: aw_source_id={r['aw_source_id']!r}, expected {expected['aw']!r}"
            )

    # 7. Column header (enforced by write_csv using NEW_HEADER directly;
    #    verify here that every new_row has the expected keys and no old source_id key)
    for r in new_rows:
        for col in ["ph_source_id", "aw_source_id"]:
            if col not in r:
                errors.append(f"row {r['row_index']}: missing expected column {col!r}")
        if "source_id" in r:
            errors.append(f"row {r['row_index']}: old source_id key still present in row dict")

    # 8. Row-order preservation: 7 known food_name→row_index anchors
    for ridx, expected_name in ROW_ORDER_ANCHORS.items():
        r = idx_to_new.get(ridx)
        if r is None:
            errors.append(f"Row-order anchor: row_index {ridx} not found in migrated data")
        elif r["food_name"] != expected_name:
            errors.append(
                f"Row-order anchor: row_index {ridx} expected {expected_name!r}, "
                f"got {r['food_name']!r}"
            )

    if errors:
        print("VALIDATION FAILED — CSV not written.")
        for e in errors:
            print(f"  FAIL: {e}")
        sys.exit(1)

    print("[OK] All 8 validation checks passed")


# ── Write CSV ───────────────────────────────────────────────────────────────────

def write_csv(new_rows: list[dict]) -> None:
    with open(INPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_HEADER, extrasaction="ignore")
        writer.writeheader()
        for r in new_rows:
            writer.writerow({k: r[k] for k in NEW_HEADER})
    print(f"[OK] Migrated CSV written to {INPUT_CSV.relative_to(REPO_ROOT)}")


# ── Diff report ─────────────────────────────────────────────────────────────────

def cell(s: str) -> str:
    return s.replace("|", "\\|")


def row_table(r: dict, is_old: bool) -> list[str]:
    """Return markdown table rows for a before or after view of a row."""
    if is_old:
        fields = [
            ("food_name",     r["food_name"]),
            ("food_category", r["food_category"]),
            ("ph_min",        r["ph_min"]),
            ("ph_max",        r["ph_max"]),
            ("aw_min",        r["aw_min"]),
            ("aw_max",        r["aw_max"]),
            ("notes",         r["notes"]),
            ("source_id",     r["source_id"]),
        ]
    else:
        fields = [
            ("food_name",     r["food_name"]),
            ("food_category", r["food_category"]),
            ("ph_min",        r["ph_min"]),
            ("ph_max",        r["ph_max"]),
            ("ph_source_id",  r["ph_source_id"]),
            ("aw_min",        r["aw_min"]),
            ("aw_max",        r["aw_max"]),
            ("aw_source_id",  r["aw_source_id"]),
            ("notes",         r["notes"]),
        ]
    lines = ["| column | value |\n", "|---|---|\n"]
    for col, val in fields:
        lines.append(f"| `{col}` | {cell(val or '*(empty)*')} |\n")
    return lines


def write_diff(old_rows: list[dict], new_rows: list[dict]) -> None:
    idx_to_old = {r["row_index"]: r for r in old_rows}
    idx_to_new = {r["row_index"]: r for r in new_rows}

    multi_indices = set(MULTI_SOURCE.keys())

    # 5 representative single-source rows: 2 pH-only, 2 aw-only, 1 pH-only with different source
    def is_ph_only(r: dict) -> bool:
        return bool(r["ph_min"] or r["ph_max"]) and not (r["aw_min"] or r["aw_max"])

    def is_aw_only(r: dict) -> bool:
        return not (r["ph_min"] or r["ph_max"]) and bool(r["aw_min"] or r["aw_max"])

    single_old = [r for r in old_rows if r["row_index"] not in multi_indices]
    ph_only = [r for r in single_old if is_ph_only(r)]
    aw_only = [r for r in single_old if is_aw_only(r)]

    # Vary the source IDs represented in the sample
    sample_ph = []
    seen_src: set[str] = set()
    for r in ph_only:
        if len(sample_ph) >= 3:
            break
        if r["source_id"] not in seen_src or len(sample_ph) < 2:
            sample_ph.append(r)
            seen_src.add(r["source_id"])

    sample_aw = aw_only[:2]
    samples = (sample_ph + sample_aw)[:5]

    OUTPUT_DIR.mkdir(exist_ok=True)
    lines: list[str] = []

    # Header
    lines += [
        "# CSV Migration Diff — food_properties.csv\n",
        "\n",
        "**Migration date:** 2026-05-04  \n",
        "**From schema:** `food_name, food_category, ph_min, ph_max, aw_min, aw_max, notes, source_id`  \n",
        "**To schema:** `food_name, food_category, ph_min, ph_max, ph_source_id, aw_min, aw_max, aw_source_id, notes`  \n",
        "\n",
        "---\n",
        "\n",
    ]

    # Section 1 — Summary
    lines += [
        "## 1. Summary\n",
        "\n",
        "| Change | Value |\n",
        "|---|---|\n",
        "| Total rows | 252 |\n",
        f"| Single-source rows (ph_source_id = aw_source_id = old source_id) | {252 - len(multi_indices)} |\n",
        f"| Multi-source rows (per-field attribution from reviewed report) | {len(multi_indices)} |\n",
        f"| Notes fields cleaned (attribution fragments stripped) | {len(multi_indices)} |\n",
        "| Columns added | 2 (`ph_source_id`, `aw_source_id`) |\n",
        "| Columns removed | 1 (`source_id`) |\n",
        "| Registry-rejected deferred rows | 0 |\n",
        "\n",
        "**Information loss note:** The four multi-source rows' notes previously carried\n",
        "table-level citation references (e.g., `IFT-2003-T31 Table 3-1`). The new schema\n",
        "attributes at source_id level only; table-level granularity is not preserved. If\n",
        "finer-grained citation is needed in future, that requires a separate schema extension\n",
        "(e.g., a `ph_source_table` column).\n",
        "\n",
    ]

    # Section 2 — Sample single-source rows
    lines += [
        "## 2. Sample single-source rows (before / after)\n",
        "\n",
        "Five representative rows showing the column rename from `source_id` to\n",
        "per-field `ph_source_id` / `aw_source_id`. Notes are unchanged for all\n",
        "single-source rows.\n",
        "\n",
    ]
    for old in samples:
        ridx = old["row_index"]
        new  = idx_to_new[ridx]
        lines += [f"### row_index {ridx} — {old['food_name']}\n", "\n"]
        lines += ["**Before:**\n", "\n"]
        lines += row_table(old, is_old=True)
        lines += ["\n", "**After:**\n", "\n"]
        lines += row_table(new, is_old=False)
        lines.append("\n")

    # Section 3 — Multi-source rows
    lines += [
        "## 3. Multi-source rows (before / after)\n",
        "\n",
        "All four rows identified in `migration_artifacts/multi_source_rows.md`.\n",
        "Per-field source attribution comes from the reviewed `proposed ph_source_id`\n",
        "and `proposed aw_source_id` columns. Notes attribution fragments are stripped.\n",
        "\n",
    ]
    for ridx in sorted(MULTI_SOURCE.keys()):
        old = idx_to_old[ridx]
        new = idx_to_new[ridx]
        lines += [f"### row_index {ridx} — {old['food_name']}\n", "\n"]
        lines += ["**Before:**\n", "\n"]
        lines += row_table(old, is_old=True)
        lines += ["\n", "**After:**\n", "\n"]
        lines += row_table(new, is_old=False)
        lines.append("\n")

    # Section 4 — Deferred
    lines += [
        "## 4. Deferred for separate registry/data work\n",
        "\n",
        "None. The discovery report (`migration_artifacts/multi_source_rows.md`)\n",
        "found zero registry-rejected candidates in Section 3a. No rows required deferral.\n",
        "\n",
    ]

    DIFF_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"[OK] Diff report written to {DIFF_FILE.relative_to(REPO_ROOT)}")


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    valid_ids = load_valid_source_ids()
    print(f"[OK] Loaded {len(valid_ids)} valid source IDs from source_references.csv")

    old_rows, new_rows = transform()
    print(f"[OK] Transformed {len(new_rows)} rows")

    validate(old_rows, new_rows, valid_ids)

    # All checks passed — safe to write.
    write_csv(new_rows)
    write_diff(old_rows, new_rows)

    print(f"\n[OK] Migration complete.")


if __name__ == "__main__":
    main()
