"""
RAG Evaluation

Metrics for evaluating retrieval quality.
Uses ranx for standard IR metrics.
"""

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field
from ranx import Qrels, Run, evaluate


@dataclass
class RelevanceJudgment:
    """A single relevance judgment for evaluation."""
    query_id: str
    doc_id: str
    relevance: int  # 0 = not relevant, 1 = relevant, 2+ = highly relevant


@dataclass
class RetrievalPrediction:
    """A single retrieval prediction."""
    query_id: str
    doc_id: str
    score: float


class EvaluationResult(BaseModel):
    """Result of an evaluation run."""
    mrr: float = Field(description="Mean Reciprocal Rank")
    ndcg_at_5: float = Field(description="nDCG@5")
    ndcg_at_10: float = Field(description="nDCG@10")
    recall_at_5: float = Field(description="Recall@5")
    recall_at_10: float = Field(description="Recall@10")
    precision_at_5: float = Field(description="Precision@5")
    precision_at_10: float = Field(description="Precision@10")
    
    # Metadata
    num_queries: int = Field(description="Number of queries evaluated")
    config: dict = Field(default_factory=dict, description="Experiment configuration")


class RAGEvaluator:
    """
    Evaluator for RAG retrieval quality.
    
    Usage:
        evaluator = RAGEvaluator()
        evaluator.add_ground_truth("q1", "doc1", relevance=1)
        evaluator.add_prediction("q1", "doc1", score=0.95)
        result = evaluator.evaluate()
    """
    
    # Supported metrics
    METRICS = [
        "mrr",
        "ndcg@5",
        "ndcg@10", 
        "recall@5",
        "recall@10",
        "precision@5",
        "precision@10",
    ]
    
    def __init__(self):
        self._judgments: list[RelevanceJudgment] = []
        self._predictions: list[RetrievalPrediction] = []
    
    def add_ground_truth(
        self,
        query_id: str,
        doc_id: str,
        relevance: int = 1,
    ) -> None:
        """Add a ground truth relevance judgment."""
        self._judgments.append(RelevanceJudgment(
            query_id=query_id,
            doc_id=doc_id,
            relevance=relevance,
        ))
    
    def add_prediction(
        self,
        query_id: str,
        doc_id: str,
        score: float,
    ) -> None:
        """Add a retrieval prediction."""
        self._predictions.append(RetrievalPrediction(
            query_id=query_id,
            doc_id=doc_id,
            score=score,
        ))
    
    def clear(self) -> None:
        """Clear all judgments and predictions."""
        self._judgments = []
        self._predictions = []
    
    def evaluate(self, config: dict | None = None) -> EvaluationResult:
        """
        Compute evaluation metrics.
        
        Args:
            config: Optional experiment configuration to include in result
            
        Returns:
            EvaluationResult with all metrics
        """
        if not self._judgments or not self._predictions:
            raise ValueError("Need both ground truth and predictions to evaluate")
        
        # Build qrels (ground truth)
        qrels_dict = {}
        for j in self._judgments:
            if j.query_id not in qrels_dict:
                qrels_dict[j.query_id] = {}
            qrels_dict[j.query_id][j.doc_id] = j.relevance
        
        # Build run (predictions)
        run_dict = {}
        for p in self._predictions:
            if p.query_id not in run_dict:
                run_dict[p.query_id] = {}
            run_dict[p.query_id][p.doc_id] = p.score
        
        qrels = Qrels(qrels_dict)
        run = Run(run_dict)
        
        # Evaluate
        results = evaluate(run, qrels, self.METRICS)
        
        return EvaluationResult(
            mrr=results.get("mrr", 0.0),
            ndcg_at_5=results.get("ndcg@5", 0.0),
            ndcg_at_10=results.get("ndcg@10", 0.0),
            recall_at_5=results.get("recall@5", 0.0),
            recall_at_10=results.get("recall@10", 0.0),
            precision_at_5=results.get("precision@5", 0.0),
            precision_at_10=results.get("precision@10", 0.0),
            num_queries=len(qrels_dict),
            config=config or {},
        )


# =============================================================================
# SYNTHETIC EVALUATION DATASET
# =============================================================================

def get_synthetic_evaluation_dataset() -> tuple[list[dict], list[dict]]:
    """
    Get synthetic evaluation dataset for testing.
    
    Returns:
        Tuple of (documents, queries_with_relevance)
        
    Documents have 'id', 'content', 'type', 'metadata'
    Queries have 'id', 'text', 'relevant_docs' (list of doc_ids)
    """
    documents = [
        # Food properties
        {
            "id": "food_001",
            "content": "Raw chicken breast has a pH between 5.9 and 6.2. Water activity is typically 0.99. Store below 4°C.",
            "type": "food_properties",
            "metadata": {"food": "chicken", "state": "raw"},
        },
        {
            "id": "food_002", 
            "content": "Cooked chicken has pH around 6.0-6.3. Water activity remains high at 0.98-0.99.",
            "type": "food_properties",
            "metadata": {"food": "chicken", "state": "cooked"},
        },
        {
            "id": "food_003",
            "content": "Raw ground beef has pH 5.4-5.8 and water activity 0.98. Highly perishable.",
            "type": "food_properties",
            "metadata": {"food": "beef", "state": "raw"},
        },
        {
            "id": "food_004",
            "content": "Fresh salmon has pH 6.1-6.5 and water activity 0.98-0.99.",
            "type": "food_properties",
            "metadata": {"food": "salmon", "state": "raw"},
        },
        {
            "id": "food_005",
            "content": "Pasteurized milk has pH 6.5-6.7 and water activity 0.99.",
            "type": "food_properties",
            "metadata": {"food": "milk", "state": "pasteurized"},
        },
        {
            "id": "food_006",
            "content": "Hard cheese like cheddar has pH 5.0-5.5 and water activity 0.85-0.95.",
            "type": "food_properties",
            "metadata": {"food": "cheese", "state": "aged"},
        },
        {
            "id": "food_007",
            "content": "Fresh eggs have pH 7.6-8.0 for albumen and 6.0 for yolk. Water activity 0.97.",
            "type": "food_properties",
            "metadata": {"food": "eggs", "state": "raw"},
        },
        {
            "id": "food_008",
            "content": "Cooked rice has pH 6.0-6.6 and water activity 0.96-0.98. Risk of Bacillus cereus.",
            "type": "food_properties",
            "metadata": {"food": "rice", "state": "cooked"},
        },
        # Pathogen hazards
        {
            "id": "path_001",
            "content": "Salmonella is commonly found in raw poultry, eggs, and unpasteurized milk. Growth range 5-47°C.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "salmonella"},
        },
        {
            "id": "path_002",
            "content": "Listeria monocytogenes can grow at refrigeration temperatures (0-4°C). Found in deli meats, soft cheeses.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "listeria"},
        },
        {
            "id": "path_003",
            "content": "E. coli O157:H7 associated with undercooked ground beef. Minimum growth temperature 7°C.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "ecoli"},
        },
        {
            "id": "path_004",
            "content": "Campylobacter is the leading cause of bacterial gastroenteritis. Found in raw poultry.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "campylobacter"},
        },
        {
            "id": "path_005",
            "content": "Bacillus cereus produces toxins in cooked rice and pasta left at room temperature.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "bacillus"},
        },
        {
            "id": "path_006",
            "content": "Clostridium perfringens grows rapidly in cooked meat and poultry held at improper temperatures.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "clostridium"},
        },
        {
            "id": "path_007",
            "content": "Vibrio species associated with raw shellfish and seafood. Requires salt for growth.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "vibrio"},
        },
        {
            "id": "path_008",
            "content": "Staphylococcus aureus produces heat-stable toxins. Found in foods handled by humans.",
            "type": "pathogen_hazards",
            "metadata": {"pathogen": "staphylococcus"},
        },
    ]
    
    queries = [
        {
            "id": "q01",
            "text": "What is the pH of raw chicken?",
            "relevant_docs": ["food_001"],
        },
        {
            "id": "q02",
            "text": "chicken water activity properties",
            "relevant_docs": ["food_001", "food_002"],
        },
        {
            "id": "q03",
            "text": "pH and aw of ground beef",
            "relevant_docs": ["food_003"],
        },
        {
            "id": "q04",
            "text": "What pathogens are associated with raw poultry?",
            "relevant_docs": ["path_001", "path_004", "path_006"],
        },
        {
            "id": "q05",
            "text": "bacteria that grow at refrigeration temperature",
            "relevant_docs": ["path_002"],
        },
        {
            "id": "q06",
            "text": "E. coli hamburger contamination",
            "relevant_docs": ["path_003"],
        },
        {
            "id": "q07",
            "text": "milk pH water activity",
            "relevant_docs": ["food_005"],
        },
        {
            "id": "q08",
            "text": "cooked rice food safety hazards",
            "relevant_docs": ["food_008", "path_005"],
        },
        {
            "id": "q09",
            "text": "Listeria deli meat cheese",
            "relevant_docs": ["path_002"],
        },
        {
            "id": "q10",
            "text": "salmon fish pH properties",
            "relevant_docs": ["food_004"],
        },
        {
            "id": "q11",
            "text": "What is the water activity of cheese?",
            "relevant_docs": ["food_006"],
        },
        {
            "id": "q12",
            "text": "shellfish vibrio contamination",
            "relevant_docs": ["path_007"],
        },
    ]
    
    return documents, queries