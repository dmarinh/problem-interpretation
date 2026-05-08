"""
Taxonomy Bridge — Tier 3 deterministic food-category lookup.

Resolves a food description to a FoodEx2 ptm_category via fuzzy matching
against food_taxonomy.csv, then supplies the matching food_properties.csv rows
for that category.  Used by GroundingService when both Tier 1 (primary RAG
query) and Tier 2 (per-field fallback) fail to ground a property.

Resolution pipeline inside TaxonomyBridge.resolve()
----------------------------------------------------
1. Normalise: lowercase, strip punctuation, collapse whitespace.
2. Composite-blocklist guard — if any blocklist keyword is present, return None
   immediately, BEFORE fuzzy matching runs.  This is a semantic decision:
   composite foods ("chicken soup") would otherwise score 100 against their
   primary ingredient token ("chicken") via token_set_ratio, producing a
   confident but wrong category assignment.  The guard must short-circuit
   before _fuzzy_match_food_name is called; test_composite_blocklist_short_circuits
   verifies this ordering via monkeypatch.
3. Apply alias map (e.g. "beef" → "bovine") to the normalised input.
   Aliases rewrite user vocabulary to FoodEx2 vocabulary before matching.
   The rewrite must happen BEFORE fuzzy match — "beef" scores ~36 against
   "bovine" in token_set_ratio, below any sensible threshold.
4. _fuzzy_match_food_name: compute rapidfuzz.fuzz.token_set_ratio against
   every food_name in the taxonomy.  Top score ≥ threshold → TaxonomyResolution.

Threshold selection (default 80)
---------------------------------
Parametrised unit tests over thresholds 70/75/80/85 confirm:
- All positive cases (turkey, turkey portions, turkeys, tukey, raw chicken,
  lettuce) score ≥ 80 at every threshold.
- All negative cases (tornado, xyzqwerty) score ≤ 57 at every threshold.
The gap between min true-positive (90.9 for 'tukey') and max true-negative
(57.1 for 'tornado') is 33.8 points.  Threshold 80 sits in this gap with a
23-point margin above the nearest true-negative and an 11-point margin below
the nearest true-positive.  70 would also work on the current test set, but
80 provides a larger safety margin against vocabulary drift in future taxonomy
updates.

Note: the tiebreaker (fuzz.ratio secondary score) does not affect the primary
threshold comparison — threshold is checked only against token_set_ratio.

property_rows dict shape
------------------------
Each dict in TaxonomyResolution.property_rows has these keys (all str, empty
string when absent, never None):
  food_name       — food_properties.food_name
  food_category   — food_properties.food_category
  ph_min          — pH lower bound (empty if no pH data for this row)
  ph_max          — pH upper bound (empty if no pH data for this row)
  ph_source_id    — registered source ID for pH (e.g. 'IFT-2003-T33')
  aw_min          — water activity lower bound (empty if no aw data)
  aw_max          — water activity upper bound (empty if no aw data)
  aw_source_id    — registered source ID for aw (e.g. 'IFT-2003-T31')

State-aware curated lookup
--------------------------
TaxonomyResolution.matched_state carries the raw 'state' column value of the
winning taxonomy row ("fresh", "cured", "unspecified", etc.).  GroundingService
normalises this via _apply_state_default ("unspecified"/"" → "fresh") and then
calls lookup_category_level_row(category, state, field) which consults the
five explicitly curated rows in data/rag/category_level_rows.csv.  The bridge
inherits ONLY from those rows — never from individual-food rows in
food_properties.csv.
"""

import csv
import logging
import re
import string
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Paths resolved relative to this file so the bridge works regardless of the
# working directory.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_TAXONOMY_CSV = _REPO_ROOT / "data" / "rag" / "food_taxonomy.csv"
_FOOD_PROPERTIES_CSV = _REPO_ROOT / "data" / "rag" / "food_properties.csv"
_ALIASES_CSV = _REPO_ROOT / "data" / "food_taxonomy_aliases.csv"
_CATEGORY_LEVEL_ROWS_CSV = _REPO_ROOT / "data" / "rag" / "category_level_rows.csv"

# Composite-food keywords whose presence signals a multi-ingredient dish.
# These are semantic descriptors, not ingredients.  "chicken soup" has
# "chicken" but the DISH is composite; the bridge must not resolve it.
# The guard fires on the normalised input (post-lowercase, post-punctuation-strip).
_COMPOSITE_KEYWORDS: frozenset[str] = frozenset({
    "soup", "salad", "stew", "pie", "sandwich", "roll", "wrap",
    "casserole", "curry", "mixed", "platter", "dish",
})


@dataclass
class TaxonomyResolution:
    """Result of a successful taxonomy bridge resolution.

    Carries everything needed to build a CategoryBridgeInfo on the
    ValueProvenance, plus the food_properties rows for the resolved category
    so the grounding service can extract pH and aw without an extra CSV read.

    See module docstring for the exact key set on each property_rows dict.

    matched_state is the raw 'state' column value of the winning taxonomy row
    ("fresh", "cured", "dried", "unspecified", etc.).  The grounding service
    passes it through _apply_state_default() before calling
    lookup_category_level_row().
    """
    ptm_category: str
    taxonomy_code: str
    taxonomy_label: str
    taxonomy_source_id: str
    matched_food_name: str      # the food_name column value that won the match
    match_score: float          # token_set_ratio score 0–100
    matched_state: str = ""     # raw 'state' column value of the winning row
    property_rows: list[dict] = field(default_factory=list)


class TaxonomyBridge:
    """Deterministic food-name → ptm_category resolver using FoodEx2 taxonomy.

    Loads three CSV artefacts at construction time:
      - data/rag/food_taxonomy.csv  (2,917 FoodEx2 MTX entries)
      - data/rag/food_properties.csv (253 food pH/aw reference rows)
      - data/food_taxonomy_aliases.csv (user vocabulary → FoodEx2 vocabulary)

    All lookups are in-memory; no I/O after construction.
    """

    def __init__(
        self,
        threshold: float = 80,
        taxonomy_csv: Path = _TAXONOMY_CSV,
        food_properties_csv: Path = _FOOD_PROPERTIES_CSV,
        aliases_csv: Path = _ALIASES_CSV,
        category_level_rows_csv: Path = _CATEGORY_LEVEL_ROWS_CSV,
    ) -> None:
        """
        Args:
            threshold: Minimum token_set_ratio score (0–100) to accept a match.
                Default 80.  Calibration rationale: min true-positive 'tukey'
                scores 90.9; max true-negative 'tornado' scores 57.1; gap 33.8
                points.  Threshold 80 provides a 23-point margin above the
                nearest true-negative and an 11-point margin below the nearest
                true-positive.  Tests confirm all thresholds 70/75/80/85 pass
                the full positive/negative test set; 80 is chosen for margin.
            taxonomy_csv: Path to food_taxonomy.csv.
            food_properties_csv: Path to food_properties.csv.
            aliases_csv: Path to food_taxonomy_aliases.csv.
            category_level_rows_csv: Path to category_level_rows.csv — the 5
                explicitly curated rows that the bridge may inherit from.
        """
        self.threshold = threshold
        self._taxonomy_rows = self._load_csv(taxonomy_csv)
        self._aliases = self._load_aliases(aliases_csv)
        self._properties_by_category = self._index_properties(food_properties_csv)
        self._category_level_index = self._index_category_level_rows(category_level_rows_csv)

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def resolve(self, food_description: str) -> TaxonomyResolution | None:
        """Resolve a food description to a ptm_category via FoodEx2 taxonomy.

        Returns TaxonomyResolution on success (property_rows may be empty if
        the category has no food_properties data — callers must handle this),
        None when:
        - the description contains a composite-food keyword (blocklist guard), or
        - no taxonomy entry scores ≥ threshold after alias rewrite.

        Pipeline: normalise → blocklist → alias → _fuzzy_match_food_name.
        The blocklist runs BEFORE fuzzy matching; this ordering is load-bearing
        (see module docstring) and is pinned by a structural unit test.
        """
        normalised = self._normalise(food_description)
        if self._is_composite(normalised):
            return None
        aliased = self._apply_alias(normalised)
        return self._fuzzy_match_food_name(aliased)

    # -------------------------------------------------------------------------
    # Pipeline steps (separate methods for testability / monkeypatching)
    # -------------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        """Lowercase, strip punctuation (except hyphen), collapse whitespace."""
        text = text.lower()
        # Remove punctuation except hyphen (stir-fry stays as one token group)
        text = text.translate(str.maketrans("", "", string.punctuation.replace("-", "")))
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_composite(self, normalised: str) -> bool:
        """Return True if any composite-food keyword appears as a whole word."""
        tokens = set(normalised.split())
        # Also check multi-word composites that survive normalisation
        return bool(tokens & _COMPOSITE_KEYWORDS or
                    any(kw in normalised for kw in ("stir-fry", "stir fry")))

    def _apply_alias(self, normalised: str) -> str:
        """Rewrite user-vocabulary terms to FoodEx2 vocabulary.

        Aliases are applied to the normalised input as whole-word replacements
        so that "beef tenderloin" becomes "bovine tenderloin" rather than a
        partial string replacement.  Only the first matching alias is applied.
        """
        for user_term, foodex2_term in self._aliases.items():
            # Whole-word match on token boundaries
            if re.search(rf"\b{re.escape(user_term)}\b", normalised):
                return re.sub(rf"\b{re.escape(user_term)}\b", foodex2_term, normalised, count=1)
        return normalised

    def _fuzzy_match_food_name(self, text: str) -> TaxonomyResolution | None:
        """Score text against every taxonomy food_name via token_set_ratio.

        Returns the best-matching TaxonomyResolution if score ≥ threshold,
        None otherwise.

        Scoring uses a composite (token_set_ratio, fuzz.ratio) tuple.
        token_set_ratio is the primary discriminator (order-invariant, handles
        extra context words).  fuzz.ratio breaks ties by penalising length
        differences — so "turkey" (ratio=100 vs itself) beats "turkey egg"
        (ratio=75 vs "turkey") when both share the same token_set_ratio.
        Without the tiebreaker, short single-word queries match longer
        taxonomy entries first in CSV order, producing wrong categories.
        """
        best_scores: tuple[float, float] = (0.0, 0.0)
        best_row: dict | None = None

        for row in self._taxonomy_rows:
            tsr = fuzz.token_set_ratio(text, row["food_name"])
            secondary = fuzz.ratio(text, row["food_name"])
            scores = (tsr, secondary)
            if scores > best_scores:
                best_scores = scores
                best_row = row

        if best_row is None or best_scores[0] < self.threshold:
            return None

        category = best_row["ptm_category"]
        property_rows = self._properties_by_category.get(category, [])

        return TaxonomyResolution(
            ptm_category=category,
            taxonomy_code=best_row["foodex2_code"],
            taxonomy_label=best_row["foodex2_label"],
            taxonomy_source_id=best_row["source_id"],
            matched_food_name=best_row["food_name"],
            match_score=best_scores[0],
            matched_state=best_row.get("state", "").strip(),
            property_rows=property_rows,
        )

    def lookup_category_level_row(
        self, category: str, state: str, field: str
    ) -> dict | None:
        """Return the single curated row for (category, state, field), or None.

        The curated index is keyed by (ptm_category, state, field) where field
        is 'ph' or 'aw'.  A row qualifies for 'ph' when ph_min is non-empty,
        and for 'aw' when aw_min is non-empty.

        Returns None when no curated row matches — the caller must fall through
        to the conservative default and record a bridge_attempt.
        """
        return self._category_level_index.get((category, state, field))

    # -------------------------------------------------------------------------
    # CSV loaders (called once at construction)
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_csv(path: Path) -> list[dict]:
        with path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @staticmethod
    def _load_aliases(path: Path) -> dict[str, str]:
        """Return {user_term: foodex2_term} mapping (all lowercase)."""
        aliases: dict[str, str] = {}
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                user = row["user_term"].strip().lower()
                target = row["foodex2_term"].strip().lower()
                if user and target:
                    aliases[user] = target
        return aliases

    @staticmethod
    def _index_category_level_rows(path: Path) -> dict[tuple[str, str, str], dict]:
        """Build {(ptm_category, state, field): row} index from category_level_rows.csv.

        Each row is indexed under up to two keys: one for 'ph' (when ph_min is
        non-empty) and one for 'aw' (when aw_min is non-empty).  A row may be
        indexed under both if it carries both pH and aw data, or under neither
        if it carries neither (which should not occur in the curated file).
        """
        index: dict[tuple[str, str, str], dict] = {}
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                cat = row.get("ptm_category", "").strip()
                state = row.get("state", "").strip()
                if not cat or not state:
                    continue
                entry = {k: v.strip() for k, v in row.items()}
                if entry.get("ph_min"):
                    index[(cat, state, "ph")] = entry
                if entry.get("aw_min"):
                    index[(cat, state, "aw")] = entry
        return index

    @staticmethod
    def _index_properties(path: Path) -> dict[str, list[dict]]:
        """Return {food_category: [row, ...]} index of food_properties.csv.

        Each dict carries only the keys relevant to the bridge:
        food_name, food_category, ph_min, ph_max, ph_source_id,
        aw_min, aw_max, aw_source_id.
        """
        index: dict[str, list[dict]] = {}
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                cat = row.get("food_category", "").strip()
                if not cat:
                    continue
                entry = {
                    "food_name": row.get("food_name", "").strip(),
                    "food_category": cat,
                    "ph_min": row.get("ph_min", "").strip(),
                    "ph_max": row.get("ph_max", "").strip(),
                    "ph_source_id": row.get("ph_source_id", "").strip(),
                    "aw_min": row.get("aw_min", "").strip(),
                    "aw_max": row.get("aw_max", "").strip(),
                    "aw_source_id": row.get("aw_source_id", "").strip(),
                }
                index.setdefault(cat, []).append(entry)
        return index
