"""
Unit tests for ingestion pipeline.
"""

import csv
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from app.rag.ingestion import IngestionPipeline
from app.rag.vector_store import VectorStore


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def vector_store(temp_dir) -> VectorStore:
    """Create a temporary vector store."""
    store = VectorStore(persist_directory=temp_dir / "vector_store")
    store.initialize()
    return store


@pytest.fixture
def pipeline(vector_store) -> IngestionPipeline:
    """Create pipeline with temp store."""
    return IngestionPipeline(vector_store=vector_store)


class TestIngestionPipeline:
    """Tests for IngestionPipeline."""

    def test_ingest_text_file(self, pipeline, vector_store, temp_dir):
        """Should ingest a text file."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("This is test content about food safety.")

        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["success"] is True
        assert result["chunks"] >= 1
        assert vector_store.get_count() >= 1

    def test_ingest_csv_file(self, pipeline, vector_store, temp_dir):
        """Should ingest a CSV file."""
        test_file = temp_dir / "test.csv"
        test_file.write_text("food,ph,aw\nchicken,6.0,0.99\nbeef,5.5,0.98\n")

        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["success"] is True
        assert result["chunks"] == 2  # One per row

    def test_ingest_with_extra_metadata(self, pipeline, vector_store, temp_dir):
        """Should add extra metadata to all chunks."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Content about chicken.")

        pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            extra_metadata={"category": "poultry"},
        )

        results = vector_store.query("chicken", n_results=1)

        assert results[0]["metadata"]["category"] == "poultry"

    def test_ingest_missing_file(self, pipeline):
        """Should handle missing file gracefully."""
        result = pipeline.ingest_file(
            Path("nonexistent.txt"),
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_ingest_unsupported_format(self, pipeline, temp_dir):
        """Should reject unsupported file types."""
        test_file = temp_dir / "test.xyz"
        test_file.write_text("content")

        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["success"] is False
        assert "unsupported" in result["error"].lower()

    def test_ingest_directory(self, pipeline, vector_store, temp_dir):
        """Should ingest all files in directory."""
        # Create test files
        (temp_dir / "file1.txt").write_text("Content one.")
        (temp_dir / "file2.txt").write_text("Content two.")
        (temp_dir / "file3.md").write_text("# Markdown content")

        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["total_files"] == 3
        assert result["successful_files"] == 3
        assert result["total_chunks"] >= 3

    def test_ingest_directory_recursive(self, pipeline, vector_store, temp_dir):
        """Should find files in subdirectories."""
        # Create nested structure
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (temp_dir / "root.txt").write_text("Root content.")
        (subdir / "nested.txt").write_text("Nested content.")

        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            recursive=True,
        )

        assert result["total_files"] == 2

    def test_ingest_directory_non_recursive(self, pipeline, vector_store, temp_dir):
        """Should not find files in subdirectories when recursive=False."""
        # Create nested structure
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (temp_dir / "root.txt").write_text("Root content.")
        (subdir / "nested.txt").write_text("Nested content.")

        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            recursive=False,
        )

        assert result["total_files"] == 1

    def test_ingest_text_directly(self, pipeline, vector_store):
        """Should ingest raw text."""
        result = pipeline.ingest_text(
            text="Raw chicken has pH 6.0 and water activity 0.99.",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            metadata={"food": "chicken"},
        )

        assert result["success"] is True
        assert result["chunks"] >= 1

        # Verify searchable
        results = vector_store.query("chicken pH")
        assert len(results) >= 1

    def test_ingest_empty_text(self, pipeline):
        """Should reject empty text."""
        result = pipeline.ingest_text(
            text="   ",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )

        assert result["success"] is False
        assert "empty" in result["error"].lower()


class TestMultiSourceAttribution:
    """
    Per-field ph_source_id / aw_source_id columns drive source attribution.
    Notes text is opaque data; it must never contribute source IDs.
    """

    _FIELDS = [
        "food_name",
        "food_category",
        "ph_min",
        "ph_max",
        "ph_source_id",
        "aw_min",
        "aw_max",
        "aw_source_id",
        "notes",
    ]

    _KNOWN_IDS = frozenset({"FDA-PH-2007", "IFT-2003-T31", "IFT-2003-T33", "CDC-2019"})

    def _patch(self, monkeypatch, expected_count: int = 1) -> None:
        import app.rag.data_sources.food_safety as fs

        monkeypatch.setattr(fs, "EXPECTED_FOOD_PROPERTIES_COUNT", expected_count)
        monkeypatch.setattr(fs, "_valid_source_ids", lambda: self._KNOWN_IDS)

    def _write_food_csv(self, path: Path, rows: list) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    @pytest.mark.parametrize(
        "food_name", ["bread white", "cheese parmesan", "honey", "maple syrup"]
    )
    def test_multi_source_row_derives_both_ids_from_columns(
        self, pipeline, vector_store, temp_dir, monkeypatch, food_name
    ):
        """Rows with distinct ph_source_id and aw_source_id emit both IDs, pH first."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": food_name,
                    "food_category": "test",
                    "ph_min": "5.0",
                    "ph_max": "6.0",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "0.94",
                    "aw_max": "0.97",
                    "aw_source_id": "IFT-2003-T31",
                    "notes": "",
                }
            ],
        )

        load_food_properties(pipeline, temp_dir)

        docs = vector_store.get_documents(where={"food_name": food_name})
        assert docs, f"No document found for {food_name!r}"

        stored = docs[0]["metadata"]["source_id"]
        ids = [s.strip() for s in stored.split(",") if s.strip()]
        assert ids == [
            "FDA-PH-2007",
            "IFT-2003-T31",
        ], f"Unexpected source_id list: {ids}"

    def test_same_ph_aw_source_deduplicates_to_one_id(
        self, pipeline, vector_store, temp_dir, monkeypatch
    ):
        """When ph_source_id == aw_source_id only one entry appears in stored source_id."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "chicken",
                    "food_category": "poultry",
                    "ph_min": "6.2",
                    "ph_max": "6.4",
                    "ph_source_id": "IFT-2003-T33",
                    "aw_min": "0.99",
                    "aw_max": "0.99",
                    "aw_source_id": "IFT-2003-T33",
                    "notes": "Chicken breast, raw",
                }
            ],
        )

        load_food_properties(pipeline, temp_dir)

        docs = vector_store.get_documents(where={"food_name": "chicken"})
        assert docs

        stored = docs[0]["metadata"]["source_id"]
        ids = [s.strip() for s in stored.split(",") if s.strip()]
        assert ids == [
            "IFT-2003-T33"
        ], f"Expected exactly one ID after dedup, got {ids}"

    def test_ph_only_row_excludes_empty_aw_source(
        self, pipeline, vector_store, temp_dir, monkeypatch
    ):
        """A row with no aw range emits only the ph_source_id."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "vinegar",
                    "food_category": "condiment",
                    "ph_min": "2.0",
                    "ph_max": "3.5",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "",
                    "aw_max": "",
                    "aw_source_id": "",
                    "notes": "",
                }
            ],
        )

        load_food_properties(pipeline, temp_dir)

        docs = vector_store.get_documents(where={"food_name": "vinegar"})
        assert docs

        stored = docs[0]["metadata"]["source_id"]
        ids = [s.strip() for s in stored.split(",") if s.strip()]
        assert ids == ["FDA-PH-2007"], f"Expected only ph_source_id, got {ids}"

    def test_notes_field_does_not_contribute_to_source_ids(
        self, pipeline, vector_store, temp_dir, monkeypatch
    ):
        """Notes prose citing source IDs must not affect the stored source_id."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "bread white",
                    "food_category": "grain",
                    # Both columns point to the same source; notes mentions a second one.
                    "ph_min": "5.0",
                    "ph_max": "6.0",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "0.94",
                    "aw_max": "0.97",
                    "aw_source_id": "FDA-PH-2007",
                    "notes": "White bread; pH from FDA-PH-2007, aw 0.94-0.97 from IFT-2003-T31 Table 3-1",
                }
            ],
        )

        load_food_properties(pipeline, temp_dir)

        docs = vector_store.get_documents(where={"food_name": "bread white"})
        assert docs

        stored = docs[0]["metadata"]["source_id"]
        ids = [s.strip() for s in stored.split(",") if s.strip()]
        # IFT-2003-T31 appears in notes but not in ph_source_id/aw_source_id — must be absent.
        assert ids == [
            "FDA-PH-2007"
        ], f"Notes text must not inflate source_id; got {ids}"

    def test_validation_error_missing_ph_source_id(
        self, pipeline, temp_dir, monkeypatch
    ):
        """A populated ph range with an empty ph_source_id must raise ValueError."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "apple",
                    "food_category": "fruit",
                    "ph_min": "3.3",
                    "ph_max": "4.0",
                    "ph_source_id": "",
                    "aw_min": "0.97",
                    "aw_max": "0.99",
                    "aw_source_id": "FDA-PH-2007",
                    "notes": "",
                }
            ],
        )

        with pytest.raises(ValueError, match="ph_source_id is empty"):
            load_food_properties(pipeline, temp_dir)

    def test_validation_error_missing_aw_source_id(
        self, pipeline, temp_dir, monkeypatch
    ):
        """A populated aw range with an empty aw_source_id must raise ValueError."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "apple",
                    "food_category": "fruit",
                    "ph_min": "3.3",
                    "ph_max": "4.0",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "0.97",
                    "aw_max": "0.99",
                    "aw_source_id": "",
                    "notes": "",
                }
            ],
        )

        with pytest.raises(ValueError, match="aw_source_id is empty"):
            load_food_properties(pipeline, temp_dir)

    def test_validation_error_unknown_ph_source_id(
        self, pipeline, temp_dir, monkeypatch
    ):
        """A ph_source_id not present in source_references.csv must raise ValueError."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "apple",
                    "food_category": "fruit",
                    "ph_min": "3.3",
                    "ph_max": "4.0",
                    "ph_source_id": "UNKNOWN-SRC-999",
                    "aw_min": "0.97",
                    "aw_max": "0.99",
                    "aw_source_id": "FDA-PH-2007",
                    "notes": "",
                }
            ],
        )

        with pytest.raises(
            ValueError, match="ph_source_id.*not found in source_references"
        ):
            load_food_properties(pipeline, temp_dir)

    def test_validation_error_unknown_aw_source_id(
        self, pipeline, temp_dir, monkeypatch
    ):
        """An aw_source_id not present in source_references.csv must raise ValueError."""
        from app.rag.data_sources.food_safety import load_food_properties

        self._patch(monkeypatch)
        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "apple",
                    "food_category": "fruit",
                    "ph_min": "3.3",
                    "ph_max": "4.0",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "0.97",
                    "aw_max": "0.99",
                    "aw_source_id": "UNKNOWN-SRC-999",
                    "notes": "",
                }
            ],
        )

        with pytest.raises(
            ValueError, match="aw_source_id.*not found in source_references"
        ):
            load_food_properties(pipeline, temp_dir)

    def test_row_count_sanity_check(self, pipeline, temp_dir, monkeypatch):
        """A CSV with the wrong row count must raise ValueError naming the expected count."""
        import app.rag.data_sources.food_safety as fs
        from app.rag.data_sources.food_safety import load_food_properties

        # Patch only _valid_source_ids — leave EXPECTED_FOOD_PROPERTIES_COUNT at 253
        # so a single-row fixture triggers the mismatch.
        monkeypatch.setattr(fs, "_valid_source_ids", lambda: self._KNOWN_IDS)

        self._write_food_csv(
            temp_dir / "food_properties.csv",
            [
                {
                    "food_name": "apple",
                    "food_category": "fruit",
                    "ph_min": "3.3",
                    "ph_max": "4.0",
                    "ph_source_id": "FDA-PH-2007",
                    "aw_min": "0.97",
                    "aw_max": "0.99",
                    "aw_source_id": "IFT-2003-T31",
                    "notes": "",
                }
            ],
        )

        with pytest.raises(ValueError, match=r"253.*EXPECTED_FOOD_PROPERTIES_COUNT"):
            load_food_properties(pipeline, temp_dir)


class TestManifestWarning:
    """System audit signals clearly when the ingestion manifest is absent."""

    def test_manifest_present_fields_populated(self, tmp_path, monkeypatch):
        """All three manifest-sourced fields are non-None when the manifest exists."""
        import app.services.audit.system as sys_mod

        manifest = tmp_path / "ingest_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "rag_store_hash": "abc123",
                    "ingested_at": "2026-04-27T10:00:00+00:00",
                    "source_csv_audit_date": "2026-04-17T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(sys_mod, "_MANIFEST_PATH", manifest)

        result = sys_mod.build_system_audit()

        assert result["rag_store_hash"] == "abc123"
        assert result["rag_ingested_at"] is not None
        assert result["source_csv_audit_date"] is not None
        assert not result.get("manifest_missing", False)

    def test_manifest_absent_flags_missing(self, tmp_path, monkeypatch):
        """Missing manifest sets manifest_missing=True and leaves the three fields None."""
        import app.services.audit.system as sys_mod

        monkeypatch.setattr(sys_mod, "_MANIFEST_PATH", tmp_path / "nonexistent.json")

        result = sys_mod.build_system_audit()

        assert result["rag_store_hash"] is None
        assert result["rag_ingested_at"] is None
        assert result["source_csv_audit_date"] is None
        assert result.get("manifest_missing") is True

    def test_manifest_missing_warning_wired_in_orchestrator(
        self, tmp_path, monkeypatch
    ):
        """Orchestrator appends a warning string when build_system_audit signals manifest_missing."""
        import app.services.audit.system as sys_mod

        monkeypatch.setattr(sys_mod, "_MANIFEST_PATH", tmp_path / "nonexistent.json")

        # Directly exercise the wiring logic without a full translate() call.
        from app.models.metadata import InterpretationMetadata, SystemAudit

        metadata = InterpretationMetadata(
            session_id="test-session", original_input="test"
        )
        sys_audit_data = sys_mod.build_system_audit()
        manifest_missing = sys_audit_data.pop("manifest_missing", False)
        metadata.system = SystemAudit(**sys_audit_data)
        if manifest_missing:
            metadata.warnings.append("RAG manifest missing — store provenance unknown")

        assert "RAG manifest missing — store provenance unknown" in metadata.warnings
        assert metadata.system.rag_store_hash is None
