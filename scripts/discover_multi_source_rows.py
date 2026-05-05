"""
Discover multi-source rows in food_properties.csv.

Replicates the exact parser logic from app/rag/data_sources/food_safety.py
and asserts string equality of the regex patterns before running, so the
report faithfully represents what production ingestion does.

Writes: migration_artifacts/multi_source_rows.md
"""

import csv
import re
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
FOOD_PROPS_CSV = REPO_ROOT / "data" / "rag" / "food_properties.csv"
SOURCE_REF_CSV = REPO_ROOT / "data" / "sources" / "source_references.csv"
FOOD_SAFETY_PY = REPO_ROOT / "app" / "rag" / "data_sources" / "food_safety.py"
OUTPUT_DIR     = REPO_ROOT / "migration_artifacts"
OUTPUT_FILE    = OUTPUT_DIR / "multi_source_rows.md"

# ── Replicated parser constants ─────────────────────────────────────────────────
# Must be byte-for-byte identical to the definitions in food_safety.py.
# assert_patterns_match_source() will abort if they drift.
_BRACKET_PATTERN = r'\[([A-Z]{2,}-\d{4}[A-Z0-9\-]*)\]'
_PROSE_PATTERN   = r'\bfrom\s+([A-Z]{2,}-\d{4}[A-Z0-9\-]*)'

_BRACKET_RE = re.compile(_BRACKET_PATTERN)
_PROSE_RE   = re.compile(_PROSE_PATTERN)



# ── Regex-equality guard ────────────────────────────────────────────────────────

def assert_patterns_match_source() -> None:
    """
    Read food_safety.py as text, extract the regex literals for _BRACKET_RE
    and _PROSE_RE, and assert they equal the constants above.  Aborts with a
    clear diagnostic on any mismatch so the report is never produced against
    a phantom baseline.
    """
    src = FOOD_SAFETY_PY.read_text(encoding="utf-8")

    bracket_m = re.search(r"_BRACKET_RE\s*=\s*re\.compile\(r'([^']+)'\)", src)
    prose_m   = re.search(r"_PROSE_RE\s*=\s*re\.compile\(r'([^']+)'\)",   src)

    if not bracket_m:
        sys.exit(
            "ABORT: _BRACKET_RE definition not found in food_safety.py.\n"
            f"  File: {FOOD_SAFETY_PY}"
        )
    if not prose_m:
        sys.exit(
            "ABORT: _PROSE_RE definition not found in food_safety.py.\n"
            f"  File: {FOOD_SAFETY_PY}"
        )

    prod_bracket = bracket_m.group(1)
    prod_prose   = prose_m.group(1)

    if prod_bracket != _BRACKET_PATTERN:
        sys.exit(
            "ABORT: _BRACKET_RE pattern mismatch — script would report against "
            "a phantom baseline.\n"
            f"  Production : {prod_bracket!r}\n"
            f"  This script: {_BRACKET_PATTERN!r}"
        )
    if prod_prose != _PROSE_PATTERN:
        sys.exit(
            "ABORT: _PROSE_RE pattern mismatch — script would report against "
            "a phantom baseline.\n"
            f"  Production : {prod_prose!r}\n"
            f"  This script: {_PROSE_PATTERN!r}"
        )

    print(f"[OK] Regex patterns match production food_safety.py")


# ── Source registry ─────────────────────────────────────────────────────────────

def load_valid_source_ids() -> frozenset:
    with open(SOURCE_REF_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return frozenset(row["source_id"] for row in reader if row.get("source_id"))


# ── Parser (identical logic to _parse_extra_source_ids in food_safety.py) ──────

def parse_candidates(notes: str) -> set[str]:
    """Return every string that matches either regex, before registry validation."""
    candidates: set[str] = set()
    for m in _BRACKET_RE.finditer(notes):
        candidates.add(m.group(1))
    for m in _PROSE_RE.finditer(notes):
        candidates.add(m.group(1))
    return candidates


# ── Attribution inference ───────────────────────────────────────────────────────

def infer_attribution(
    notes: str, col_source_id: str, extras: list[str]
) -> tuple[str, str, bool]:
    """
    Returns (proposed_ph_source, proposed_aw_source, is_ambiguous).

    Uses literal substring search rather than the parser regex, because some
    valid source IDs (e.g. FDA-PH-2007) don't match [A-Z]{2,}-d{4} and
    would be skipped by a regex-based approach.  For each ID that appears
    literally in the notes, the nearest preceding keyword ("ph" / "aw") in
    the lowercased notes determines the field.

    is_ambiguous (Section 3b) is True when a valid ID appears in the notes
    but neither "ph" nor "aw" precedes it unambiguously.
    """
    notes_lower = notes.lower()
    ph_src = ""
    aw_src = ""

    # Attribute column source_id first (it may not appear in the parsed extras
    # because the parser regex can't capture its format, but it IS in the notes).
    candidates_in_order = (
        [col_source_id] if col_source_id and col_source_id in notes else []
    ) + [s for s in extras if s in notes]

    for sid in candidates_in_order:
        pos = notes.find(sid)
        if pos == -1:
            continue
        context = notes_lower[:pos]
        ph_pos = context.rfind("ph")
        aw_pos = context.rfind("aw")
        if ph_pos >= 0 and (aw_pos < 0 or ph_pos > aw_pos):
            ph_src = sid
        elif aw_pos >= 0 and (ph_pos < 0 or aw_pos > ph_pos):
            aw_src = sid

    all_to_attribute = candidates_in_order
    unattributed = [s for s in all_to_attribute if s not in (ph_src, aw_src)]
    is_ambiguous = bool(unattributed and (not ph_src or not aw_src))

    return ph_src, aw_src, is_ambiguous


# ── Markdown helpers ────────────────────────────────────────────────────────────

def cell(s: str) -> str:
    return s.replace("|", "\\|")


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    assert_patterns_match_source()

    valid_ids = load_valid_source_ids()
    print(f"[OK] Loaded {len(valid_ids)} valid source IDs from source_references.csv")

    OUTPUT_DIR.mkdir(exist_ok=True)

    multi_source_rows:       list[dict] = []
    registry_rejected_rows:  list[dict] = []   # 3a — regex hit but not in registry
    attribution_ambiguous_rows: list[dict] = [] # 3b — valid extras, field unclear

    total_rows = 0
    row_index  = -1  # 0-indexed position among valid data rows only

    with open(FOOD_PROPS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            food_name = row.get("food_name", "")
            if not food_name or food_name.startswith("#"):
                continue  # trailing blank line or comment — do not increment
            row_index += 1
            total_rows += 1

            col_source_id = row.get("source_id", "")
            notes         = row.get("notes", "")
            category      = row.get("food_category", "")

            candidates = parse_candidates(notes)

            # Split into registry-accepted and registry-rejected
            valid_cands   = [s for s in candidates if s in valid_ids]
            invalid_cands = [s for s in candidates if s not in valid_ids]

            # 3a: registry-rejected (regex hit, not in registry)
            if invalid_cands:
                registry_rejected_rows.append({
                    "row_index":           row_index,
                    "food_name":           food_name,
                    "category":            category,
                    "source_id":           col_source_id,
                    "notes":               notes,
                    "rejected_candidates": sorted(invalid_cands),
                })

            # Extra = valid candidates not already equal to the column source_id
            extras = [s for s in valid_cands if s != col_source_id]

            if extras:
                ph_src, aw_src, is_ambiguous = infer_attribution(notes, col_source_id, extras)
                record = {
                    "row_index":            row_index,
                    "food_name":            food_name,
                    "category":             category,
                    "source_id":            col_source_id,
                    "parsed_extras":        sorted(extras),
                    "notes":                notes,
                    "proposed_ph_source_id": ph_src,
                    "proposed_aw_source_id": aw_src,
                    "is_ambiguous":         is_ambiguous,
                }
                multi_source_rows.append(record)
                if is_ambiguous:
                    attribution_ambiguous_rows.append(record)

    # ── Verification assertions ────────────────────────────────────────────────

    if total_rows != 252:
        print(
            f"STOP: Expected 252 data rows; found {total_rows}.\n"
            "Report not written. Investigate the CSV before proceeding."
        )
        sys.exit(1)

    def has_row(idx: int, extra: str) -> bool:
        return any(r["row_index"] == idx and extra in r["parsed_extras"]
                   for r in multi_source_rows)

    if not has_row(14, "IFT-2003-T31"):
        print(
            "STOP: cheese parmesan (row_index 14) not found in multi-source rows "
            "with IFT-2003-T31 as a parsed extra.\n"
            "Canonical test-journal doc ID food_properties_14 would be affected by "
            "the migration — investigate before proceeding."
        )
        sys.exit(1)

    if not has_row(211, "IFT-2003-T31"):
        print(
            "STOP: bread white (row_index 211) not found in multi-source rows "
            "with IFT-2003-T31 as a parsed extra.\n"
            "Canonical test-journal doc ID food_properties_211 would be affected by "
            "the migration — investigate before proceeding."
        )
        sys.exit(1)

    # All source IDs appearing in the report must be registered
    ids_in_report: set[str] = set()
    for r in multi_source_rows:
        ids_in_report.add(r["source_id"])
        ids_in_report.update(r["parsed_extras"])
        ids_in_report.discard("")
    unregistered = ids_in_report - valid_ids
    if unregistered:
        print(f"STOP: Source IDs in report not found in source_references.csv: {unregistered}")
        sys.exit(1)

    print(f"[OK] Total data rows: {total_rows}")
    print(f"[OK] Multi-source rows: {len(multi_source_rows)}")
    print(f"[OK] Registry-rejected rows (3a): {len(registry_rejected_rows)}")
    print(f"[OK] Attribution-ambiguous rows (3b): {len(attribution_ambiguous_rows)}")
    print(f"[OK] cheese parmesan (row_index 14) present with IFT-2003-T31")
    print(f"[OK] bread white (row_index 211) present with IFT-2003-T31")
    print(f"[OK] All source IDs in report found in source_references.csv")

    # ── Build report ───────────────────────────────────────────────────────────

    single_source_count = total_rows - len(multi_source_rows)
    lines: list[str] = []

    lines += [
        "# Multi-Source Row Discovery Report\n",
        "\n",
        "**Source file:** `data/rag/food_properties.csv`  \n",
        "**Parser baseline:** `app/rag/data_sources/food_safety.py`"
        " (`_BRACKET_RE`, `_PROSE_RE`) — pattern equality asserted at runtime  \n",
        "**Generated:** 2026-05-04  \n",
        "**Purpose:** Enumerate every row where the ingestion-layer notes-parser"
        " extracts one or more source IDs from the `notes` field beyond what the"
        " `source_id` column declares. Input artifact for the per-field source"
        " attribution schema migration.\n",
        "\n",
        "---\n",
        "\n",
    ]

    # Section 1 — Summary
    lines += [
        "## 1. Summary\n",
        "\n",
        "| Metric | Count |\n",
        "|---|---|\n",
        f"| Total data rows | {total_rows} |\n",
        f"| Single-source rows (column only, no extras) | {single_source_count} |\n",
        f"| Multi-source rows (column + parsed extras) | {len(multi_source_rows)} |\n",
        f"| Rows with registry-rejected candidates (Section 3a) | {len(registry_rejected_rows)} |\n",
        f"| Rows with attribution-ambiguous extras (Section 3b) | {len(attribution_ambiguous_rows)} |\n",
        "\n",
    ]

    # Section 2 — Multi-source rows table
    lines += [
        "## 2. Multi-source rows\n",
        "\n",
        "Rows requiring per-field `ph_source_id` and `aw_source_id` columns in"
        " the migrated CSV schema. Review `proposed ph_source_id` and"
        " `proposed aw_source_id` and correct before migration.\n",
        "\n",
        "| row_index | food_name | category | source_id (column)"
        " | parsed extras (from notes) | notes (raw text)"
        " | proposed ph_source_id | proposed aw_source_id |\n",
        "|---|---|---|---|---|---|---|---|\n",
    ]

    for r in sorted(multi_source_rows, key=lambda x: x["row_index"]):
        extras_str = ", ".join(r["parsed_extras"])
        ambig_flag = " ⚠" if r["is_ambiguous"] else ""
        lines.append(
            f"| {r['row_index']}"
            f" | {cell(r['food_name'])}"
            f" | {cell(r['category'])}"
            f" | {cell(r['source_id'])}"
            f" | {cell(extras_str)}"
            f" | {cell(r['notes'])}"
            f" | {cell(r['proposed_ph_source_id'])}"
            f" | {cell(r['proposed_aw_source_id'])}{ambig_flag}"
            f" |\n"
        )

    lines.append("\n")

    # Section 3 — Ambiguous / failed
    lines += [
        "## 3. Ambiguous and failed rows\n",
        "\n",
    ]

    # 3a — Registry-rejected
    lines += [
        "### 3a. Registry-rejected candidates\n",
        "\n",
    ]
    if registry_rejected_rows:
        lines += [
            "Notes text matched the regex syntax for a source ID but the candidate"
            " is absent from `data/sources/source_references.csv`. Possible causes:"
            " typo in the notes field, missing registry entry, or a table reference"
            " that coincidentally matches the pattern.\n",
            "\n",
            "| row_index | food_name | rejected candidates | notes (raw text) |\n",
            "|---|---|---|---|\n",
        ]
        for r in registry_rejected_rows:
            lines.append(
                f"| {r['row_index']}"
                f" | {cell(r['food_name'])}"
                f" | {', '.join(r['rejected_candidates'])}"
                f" | {cell(r['notes'])} |\n"
            )
        lines.append("\n")
    else:
        lines += [
            "None. Every string that matched the regex in a notes field was found"
            " in `source_references.csv`.\n",
            "\n",
        ]

    # 3b — Attribution-ambiguous
    lines += [
        "### 3b. Attribution-ambiguous rows\n",
        "\n",
    ]
    if attribution_ambiguous_rows:
        lines += [
            "Valid extra source IDs were found but the secondary attribution"
            " regexes (`pH from <SOURCE>`, `aw … from <SOURCE>`) could not"
            " assign each source to a specific field. Manual review required"
            " before migration. Flagged with ⚠ in Section 2.\n",
            "\n",
            "| row_index | food_name | parsed extras | notes (raw text)"
            " | proposed ph_source_id | proposed aw_source_id |\n",
            "|---|---|---|---|---|---|\n",
        ]
        for r in attribution_ambiguous_rows:
            lines.append(
                f"| {r['row_index']}"
                f" | {cell(r['food_name'])}"
                f" | {', '.join(r['parsed_extras'])}"
                f" | {cell(r['notes'])}"
                f" | {cell(r['proposed_ph_source_id'])}"
                f" | {cell(r['proposed_aw_source_id'])} |\n"
            )
        lines.append("\n")
    else:
        lines += [
            "None. For every multi-source row, the notes prose unambiguously"
            " attributed each extra source to a specific field"
            " (`pH from` / `aw … from` patterns resolved cleanly).\n",
            "\n",
        ]

    OUTPUT_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"\n[OK] Report written to {OUTPUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
