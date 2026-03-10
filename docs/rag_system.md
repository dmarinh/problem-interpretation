# RAG System: Technical Documentation

## Overview

The Retrieval-Augmented Generation (RAG) system provides the scientific knowledge foundation for the Problem Translation Module. It stores, indexes, and retrieves food safety information including food properties (pH, water activity) and pathogen-food associations.

**Core Principle:** Provide accurate, citable scientific information to ground predictions in evidence rather than assumptions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        RAG System                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  Ingestion  │───▶│ Vector Store │───▶│  Retrieval  │         │
│  │  Pipeline   │    │  (ChromaDB)  │    │   Service   │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│        │                   │                   │                │
│        ▼                   ▼                   ▼                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  Document   │    │  Embedding  │    │  Reranker   │         │
│  │   Loaders   │    │   Model     │    │   Model     │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Vector Store | ChromaDB (PersistentClient) | Persistent storage of document embeddings |
| Embedding Model | all-MiniLM-L6-v2 (SentenceTransformer) | Convert text to 384-dim normalized vectors |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 | Re-score candidates for relevance |
| Ingestion Pipeline | Custom with multiple loaders | Process and chunk documents |
| Retrieval Service | Custom | Query interface with confidence scoring |
| Evaluation | ranx library | Standard IR metrics (MRR, nDCG, Recall, Precision) |

---

## Document Types

The system uses a **single ChromaDB collection** (`knowledge_base`) with metadata filtering for different knowledge types:

### Food Properties (`food_properties`)

Contains information about food characteristics relevant to microbial growth.

**Content Examples:**
```
"Raw chicken breast has a pH between 5.9 and 6.2. Water activity is typically 0.99. Store below 4°C."
"Cooked rice has pH 6.0-6.6 and water activity 0.96-0.98. Risk of Bacillus cereus."
"Hard cheese like cheddar has pH 5.0-5.5 and water activity 0.85-0.95."
```

**Expected Fields:**
- pH (single value or range)
- Water activity (aw)
- Storage recommendations
- Food category/type

### Pathogen Hazards (`pathogen_hazards`)

Contains information about pathogen-food associations and growth characteristics.

**Content Examples:**
```
"Salmonella is commonly found in raw poultry, eggs, and unpasteurized milk. Growth range 5-47°C."
"Listeria monocytogenes can grow at refrigeration temperatures (0-4°C). Found in deli meats, soft cheeses."
"E. coli O157:H7 associated with undercooked ground beef. Minimum growth temperature 7°C."
```

**Expected Fields:**
- Pathogen name
- Associated foods
- Growth temperature range
- Risk factors

### Conservative Values (`conservative_values`)

Contains worst-case default values for safety-first predictions.

---

## Vector Store (ChromaDB)

### Configuration

```python
VectorStore(
    persist_directory=Path("data/vector_store"),  # From settings.vector_store_path
    embedding=None,  # Creates default if not provided
)
```

### Collection Structure

```
ChromaDB Collection: "knowledge_base" (single collection)
├── Documents: Raw text content
├── Embeddings: 384-dimensional normalized vectors
├── Metadata: type, source, food, pathogen, etc.
└── IDs: Unique document identifiers (auto-generated or provided)
```

### Document Type Constants

```python
class VectorStore:
    COLLECTION_NAME = "knowledge_base"
    
    TYPE_FOOD_PROPERTIES = "food_properties"
    TYPE_PATHOGEN_HAZARDS = "pathogen_hazards"
    TYPE_CONSERVATIVE_VALUES = "conservative_values"
    
    ALL_TYPES = [TYPE_FOOD_PROPERTIES, TYPE_PATHOGEN_HAZARDS, TYPE_CONSERVATIVE_VALUES]
    
    DISTANCE_METRIC = "cosine"
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `initialize()` | Create ChromaDB client and collection (required before use) |
| `add_documents(documents, doc_type, metadatas, ids)` | Insert new documents |
| `query(query_text, n_results, doc_type, where)` | Retrieve similar documents |
| `get_count(doc_type)` | Count documents (optionally by type) |
| `clear(doc_type)` | Remove documents (optionally by type) |

### Initialization Pattern

```python
store = VectorStore()
store.initialize()  # MUST be called before any operations

if not store.is_initialized:
    raise RuntimeError("Store not ready")
```

---

## Embedding Model

### Model Selection

**Model:** `sentence-transformers/all-MiniLM-L6-v2`

| Property | Value |
|----------|-------|
| Dimensions | 384 |
| Max Sequence Length | 256 tokens |
| Model Size | ~80MB |
| Speed | Fast (CPU-friendly) |
| Normalization | L2 normalized by default |

**Why this model?**
- Balance of speed and quality
- Small enough for CPU inference
- Well-tested for semantic search
- Handles food/science terminology adequately

### Embedding Abstraction

```python
class BaseEmbedding(ABC):
    """Abstract base for embedding models."""
    
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple documents."""
        pass
    
    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimension."""
        pass
    
    @staticmethod
    def normalize(vectors: np.ndarray) -> np.ndarray:
        """L2 normalize vectors to unit length."""
        pass
```

### ChromaDB Adapter

ChromaDB requires a specific interface. The `ChromaEmbeddingAdapter` wraps our embedding classes:

```python
class ChromaEmbeddingAdapter:
    """Adapter for ChromaDB compatibility."""
    
    def __init__(self, embedding: BaseEmbedding):
        self._embedding = embedding
    
    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB calls this for embeddings."""
        return self._embedding.embed_documents(input)
    
    def name(self) -> str:
        """Model identifier for logging."""
        return self._embedding.model_name
```

### Factory Function

```python
def create_embedding(
    model_name: str = "all-MiniLM-L6-v2",
    normalize: bool = True,
) -> BaseEmbedding:
    """Create embedding model instance."""
    return SentenceTransformerEmbedding(
        model_name=model_name,
        normalize=normalize,
    )
```

---

## Document Loaders

The system supports multiple file formats through specialized loaders:

### Supported Formats

| Extension | Loader | Notes |
|-----------|--------|-------|
| `.txt` | TextLoader | Plain text with chunking |
| `.md` | MarkdownLoader | Splits by headers, preserves structure |
| `.csv` | CSVLoader | One document per row |
| `.docx` | DocxLoader | Extracts paragraphs and tables |
| `.pdf` | PDFLoader | Uses PyMuPDF (fitz) |

### Base Loader Interface

```python
class BaseLoader(ABC):
    @abstractmethod
    def load(self, file_path: Path) -> list[Document]:
        """Load documents from a file."""
        pass
    
    def chunk_text(
        self,
        text: str,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> list[str]:
        """Split text into chunks at sentence boundaries."""
        pass
```

### Document Model

```python
class Document(BaseModel):
    content: str           # Document text content
    metadata: dict = {}    # Additional metadata
    source: str | None     # Source file path
    chunk_index: int | None  # Chunk index if split
```

### Chunking Strategy

**Default Parameters:**
- `chunk_size`: 512 characters (from `settings.chunk_size`)
- `chunk_overlap`: 50 characters (from `settings.chunk_overlap`)

**Boundary Detection Priority:**
1. Sentence boundary (`. `)
2. Sentence with newline (`.\n`)
3. Double newline (`\n\n`)
4. Single newline (`\n`)
5. Space (` `)

```python
# Chunking algorithm
for sep in ['. ', '.\n', '\n\n', '\n', ' ']:
    last_sep = text[start:end].rfind(sep)
    if last_sep > chunk_size // 2:
        end = start + last_sep + len(sep)
        break
```

### Loader-Specific Features

**CSVLoader:**
```python
CSVLoader(
    content_columns=["description", "notes"],  # Columns for content
    metadata_columns=["food", "source"],       # Columns for metadata
    delimiter=",",
)
```

**MarkdownLoader:**
- Splits by header lines (`#`, `##`, etc.)
- Preserves section structure in metadata

**PDFLoader:**
- `load()`: Chunks across pages
- `load_by_page()`: One document per page

---

## Ingestion Pipeline

### Purpose

Process raw documents into chunked, embedded, and indexed format.

### Usage

```python
pipeline = IngestionPipeline()

# Single file
stats = pipeline.ingest_file(
    file_path=Path("data/food_properties.csv"),
    doc_type="food_properties",
    extra_metadata={"source": "FDA"},
)

# Directory
stats = pipeline.ingest_directory(
    directory=Path("data/sources"),
    doc_type="food_properties",
    recursive=True,
)

# Raw text
stats = pipeline.ingest_text(
    text="Raw chicken has pH 5.9-6.2...",
    doc_type="food_properties",
    metadata={"food": "chicken"},
    source="manual_entry",
)
```

### Return Format

```python
# File ingestion result
{
    "file": "data/food_properties.csv",
    "chunks": 15,
    "success": True,
}

# Directory ingestion result
{
    "total_files": 5,
    "successful_files": 4,
    "total_chunks": 47,
    "results": [...]  # Per-file results
}
```

### Automatic Loader Selection

```python
LOADER_MAP = {
    ".txt": TextLoader,
    ".md": MarkdownLoader,
    ".csv": CSVLoader,
    ".docx": DocxLoader,
    ".pdf": PDFLoader,
}
```

---

## Retrieval Service

### Purpose

Query the vector store and return ranked, confidence-scored results.

### Configuration

```python
RetrievalService(
    vector_store=None,        # Uses global if not provided
    reranker=None,            # Optional cross-encoder reranker
    global_threshold=None,    # From settings.global_min_confidence
)
```

### Query Methods

```python
# General query
response = service.query(
    query_text="raw chicken pH",
    doc_type="food_properties",  # Optional filter
    n_results=5,
    threshold=0.6,               # Optional override
    where={"state": "raw"},      # Optional metadata filter
    use_reranker=True,
)

# Specialized queries (use appropriate thresholds)
response = service.query_food_properties("raw chicken")
response = service.query_pathogen_hazards("ground beef")
response = service.query_conservative_values("pH", context="poultry")
```

### Query Enhancement

Queries are automatically enhanced with relevant terms:

```python
def query_food_properties(self, food_description: str):
    return self.query(
        query_text=f"{food_description} pH water activity properties",
        doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        threshold=settings.food_properties_confidence,
    )

def query_pathogen_hazards(self, food_description: str):
    return self.query(
        query_text=f"{food_description} pathogen bacteria hazard contamination",
        doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        threshold=settings.pathogen_hazards_confidence,
    )
```

---

## Reranker

### Model Selection

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`

| Property | Value |
|----------|-------|
| Type | Cross-encoder |
| Training Data | MS MARCO passage ranking |
| Input | Query + Document pair |
| Output | Relevance score |

### Reranker Types

```python
class NoOpReranker(BaseReranker):
    """Pass-through that preserves original order."""
    pass

class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranking for improved relevance."""
    pass
```

### Factory Function

```python
def create_reranker(
    model_name: str | None = None,
    enabled: bool = True,
) -> BaseReranker:
    if not enabled or model_name == "noop":
        return NoOpReranker()
    return CrossEncoderReranker(
        model_name=model_name or "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
```

### Reranking Process

When reranking is enabled:
1. Fetch `n_results * 3` candidates from vector search
2. Apply cross-encoder to all candidates
3. Sort by reranker score
4. Return top `n_results`

```python
def _apply_reranker(self, query, raw_results, top_k):
    documents = [r["document"] for r in raw_results]
    reranked = self._reranker.rerank(query, documents, top_k=top_k)
    
    reordered = []
    for rr in reranked:
        result = raw_results[rr.index].copy()
        result["rerank_score"] = rr.score
        reordered.append(result)
    return reordered
```

---

## Confidence Scoring

### Distance to Confidence Conversion

ChromaDB returns cosine **distance** (not similarity). Conversion:

```python
def _cosine_distance_to_confidence(self, distance: float) -> float:
    """
    ChromaDB cosine distance = 1 - cosine_similarity
    So: confidence = cosine_similarity = 1 - distance
    
    For normalized vectors:
    - distance 0 = identical (confidence 1.0)
    - distance 1 = orthogonal (confidence 0.0)
    - distance 2 = opposite (confidence -1.0, clamped to 0)
    """
    confidence = 1.0 - distance
    return max(0.0, min(1.0, confidence))
```

### Confidence Levels

```python
class RetrievalConfidenceLevel(str, Enum):
    HIGH = "high"       # Score ≥ 0.85
    MEDIUM = "medium"   # Score ≥ threshold (default 0.6)
    LOW = "low"         # Score > 0.0 but below threshold
    FAILED = "failed"   # Score = 0.0 or no results
```

### Classification Logic

```python
def _classify_confidence(self, confidence: float, threshold: float) -> RetrievalConfidenceLevel:
    if confidence >= 0.85:
        return RetrievalConfidenceLevel.HIGH
    elif confidence >= threshold:
        return RetrievalConfidenceLevel.MEDIUM
    elif confidence > 0.0:
        return RetrievalConfidenceLevel.LOW
    else:
        return RetrievalConfidenceLevel.FAILED
```

---

## Response Models

### RetrievalResult

```python
class RetrievalResult(BaseModel):
    content: str                           # Document text
    confidence: float                      # 0.0 - 1.0
    confidence_level: RetrievalConfidenceLevel
    source: str | None                     # Source attribution
    metadata: dict                         # Additional metadata
    doc_id: str | None                     # Document ID
    
    # Raw scores for debugging
    distance: float | None                 # Raw vector distance
    rerank_score: float | None             # Cross-encoder score if used
```

### RetrievalResponse

```python
class RetrievalResponse(BaseModel):
    query: str                             # Original query
    results: list[RetrievalResult]         # Ranked results
    top_result: RetrievalResult | None     # Best result if above threshold
    has_confident_result: bool             # Any result meets threshold
    reranker_used: str | None              # Reranker model name if used
```

---

## Evaluation System

### RAGEvaluator

The system includes a full evaluation framework using the `ranx` library:

```python
evaluator = RAGEvaluator()

# Add ground truth
evaluator.add_ground_truth("q1", "doc1", relevance=1)
evaluator.add_ground_truth("q1", "doc2", relevance=2)  # Highly relevant

# Add predictions
evaluator.add_prediction("q1", "doc1", score=0.95)
evaluator.add_prediction("q1", "doc3", score=0.80)

# Evaluate
result = evaluator.evaluate()
```

### Supported Metrics

| Metric | Description |
|--------|-------------|
| MRR | Mean Reciprocal Rank |
| nDCG@5 | Normalized DCG at 5 |
| nDCG@10 | Normalized DCG at 10 |
| Recall@5 | Recall at 5 |
| Recall@10 | Recall at 10 |
| Precision@5 | Precision at 5 |
| Precision@10 | Precision at 10 |

### EvaluationResult

```python
class EvaluationResult(BaseModel):
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    precision_at_10: float
    num_queries: int
    config: dict  # Experiment configuration
```

---

## Experiment Runner

### Purpose

Run and compare RAG experiments with different configurations.

### Configuration

```python
@dataclass
class ExperimentConfig:
    name: str
    embedding_model: str = "all-MiniLM-L6-v2"
    reranker_model: str | None = None
    reranker_enabled: bool = False
    chunk_size: int = 512
    chunk_overlap: int = 50
    n_results: int = 10
```

### Usage

```python
runner = ExperimentRunner(
    log_dir=Path("data/experiments"),
    primary_metric="mrr",
)

# Run baseline
baseline = runner.run(ExperimentConfig(name="baseline"))

# Run with reranker
with_reranker = runner.run(ExperimentConfig(
    name="with_reranker",
    reranker_enabled=True,
    reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
))

# Compare
print(runner.compare_runs())
# Name                 MRR      nDCG@5   R@5      P@5
# baseline             0.7500   0.6832   0.6000   0.2400
# with_reranker        0.8333   0.7654   0.7200   0.2880

# Get best
best = runner.get_best_run()
```

### Synthetic Evaluation Dataset

Built-in test dataset with 16 documents (8 food properties, 8 pathogen hazards) and 12 queries:

```python
documents, queries = get_synthetic_evaluation_dataset()

# Documents have: id, content, type, metadata
# Queries have: id, text, relevant_docs
```

---

## Query Flow Example

### Query: "What is the pH of raw chicken?"

```
Step 1: Query Enhancement
─────────────────────────
Input: "raw chicken"
Enhanced: "raw chicken pH water activity properties"
Doc type: "food_properties"

Step 2: Vector Search
─────────────────────
Embed query → [0.023, -0.156, ...] (384d, normalized)
Search ChromaDB for top-15 similar (3x if reranking)
Filter by metadata: type = "food_properties"

Results (by cosine distance):
1. "Raw chicken breast has a pH..." (distance: 0.15)
2. "Cooked chicken has pH..." (distance: 0.22)
3. "Poultry products typically..." (distance: 0.28)
...

Step 3: Distance to Confidence
──────────────────────────────
distance 0.15 → confidence = 1 - 0.15 = 0.85
distance 0.22 → confidence = 1 - 0.22 = 0.78
distance 0.28 → confidence = 1 - 0.28 = 0.72

Step 4: Reranking (if enabled)
──────────────────────────────
Cross-encoder scores each candidate:
1. "Raw chicken breast..." → 0.92
2. "Cooked chicken..." → 0.67
3. "Poultry products..." → 0.61

Reorder by reranker score.

Step 5: Confidence Classification
─────────────────────────────────
0.85 → HIGH (≥ 0.85)
0.78 → MEDIUM (≥ threshold)
0.72 → MEDIUM (≥ threshold)

Step 6: Response Construction
─────────────────────────────
RetrievalResponse(
    query="raw chicken pH water activity properties",
    results=[...],
    top_result=results[0],
    has_confident_result=True,
    reranker_used="cross-encoder/ms-marco-MiniLM-L-6-v2",
)
```

---

## Singleton Pattern

All major components use singleton pattern with reset for testing:

```python
# Vector Store
_store: VectorStore | None = None

def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

def reset_vector_store() -> None:
    global _store
    _store = None

# Same pattern for:
# - get_retrieval_service() / reset_retrieval_service()
# - get_ingestion_pipeline() / reset_ingestion_pipeline()
```

---

## Configuration Reference

### Settings (from app.config)

| Setting | Purpose |
|---------|---------|
| `vector_store_path` | ChromaDB persistence directory |
| `embedding_model` | Default embedding model name |
| `chunk_size` | Default chunk size for loaders |
| `chunk_overlap` | Default chunk overlap |
| `global_min_confidence` | Default confidence threshold |
| `food_properties_confidence` | Threshold for food queries |
| `pathogen_hazards_confidence` | Threshold for pathogen queries |

### Confidence Thresholds

| Level | Score Range | Interpretation |
|-------|-------------|----------------|
| HIGH | ≥ 0.85 | Strong match, use directly |
| MEDIUM | ≥ threshold | Reasonable match |
| LOW | > 0.0 | Weak match, use with caution |
| FAILED | = 0.0 | No reliable match |

---

## Error Handling

### Uninitialized Store

```python
def _ensure_initialized(self) -> None:
    if not self.is_initialized:
        raise RuntimeError("VectorStore not initialized. Call initialize() first.")
```

### File Not Found

```python
def ingest_file(self, file_path, doc_type, extra_metadata):
    if not file_path.exists():
        return {
            "file": str(file_path),
            "chunks": 0,
            "success": False,
            "error": "File not found",
        }
```

### Unsupported File Type

```python
def _get_loader(self, file_path):
    suffix = file_path.suffix.lower()
    loader_class = LOADER_MAP.get(suffix)
    if loader_class is None:
        raise ValueError(f"Unsupported file type: {suffix}")
```

---

## Testing Strategy

### Unit Tests

- Embedding normalization
- Distance to confidence conversion
- Confidence level classification
- Loader chunking logic

### Integration Tests

- Full retrieval pipeline
- Reranking improvement
- Document type filtering
- Experiment runner

### Evaluation Tests

```python
# Run synthetic evaluation
runner = ExperimentRunner()
result = runner.run(ExperimentConfig(name="test"))

assert result.result.mrr > 0.5
assert result.result.recall_at_5 > 0.4
```

---

## Future Enhancements

1. **Hybrid Search:** Combine vector similarity with BM25 keyword matching
2. **Query Expansion:** Use LLM to generate query variants
3. **Feedback Loop:** Learn from user corrections
4. **Multi-Vector Representations:** ColBERT-style token-level embeddings
5. **Hierarchical Retrieval:** Category → Subcategory → Document
6. **Source Freshness:** Weight recent sources higher
7. **Cross-Lingual:** Support queries in multiple languages
8. **Streaming Results:** Return results as they're found
9. **Caching:** Cache frequent queries
10. **Monitoring:** Track retrieval quality over time
