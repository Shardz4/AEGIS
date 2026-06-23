import numpy as np
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
from aegis.rag.corpus import Document

@dataclass
class ScoredDocument:
    document: Document
    similarity_score: float

@dataclass
class RetrievalResult:
    matched_docs: list[ScoredDocument]
    query: str
    abstained: bool
    abstention_reason: str
    max_similarity: float

class RegulatoryRetriever:
    def __init__(self, corpus: list[Document], similarity_threshold: float = 0.75):
        self.corpus = corpus
        self.similarity_threshold = similarity_threshold
        
        # Load the sentence-transformer model
        print("Initializing SentenceTransformer model 'all-MiniLM-L6-v2'...")
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        
        # Precompute embeddings for all chunks in the corpus
        print(f"Pre-embedding {len(self.corpus)} regulatory documents...")
        corpus_texts = [f"{doc.source} {doc.section} {doc.text}" for doc in self.corpus]
        
        # Encode and L2-normalize for simple dot-product cosine similarity
        raw_embeddings = self.model.encode(corpus_texts, show_progress_bar=False)
        self.corpus_embeddings = self._normalize(raw_embeddings)

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
        # Avoid division by zero
        norms[norms == 0] = 1e-10
        return vectors / norms

    def retrieve(self, query: str, top_k: int = 5) -> RetrievalResult:
        """
        Embeds the query, computes cosine similarity against the pre-embedded corpus,
        applies a keyword-overlap hybrid boost, and returns the top_k scored documents
        that meet the similarity threshold.
        If no document passes the threshold, triggers calibrated abstention.
        """
        if not query or not query.strip():
            return RetrievalResult(
                matched_docs=[],
                query=query,
                abstained=True,
                abstention_reason="Empty search query",
                max_similarity=0.0
            )

        # 1. Embed and normalize the query
        query_vector = self.model.encode([query], show_progress_bar=False)
        normalized_query = self._normalize(query_vector)[0]

        # 2. Compute cosine similarity (dot product of normalized vectors)
        semantic_scores = np.dot(self.corpus_embeddings, normalized_query)
        
        # 3. Apply keyword-overlap hybrid boost to improve recall on exact matches
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        final_scores = []
        for idx, doc in enumerate(self.corpus):
            sim = float(semantic_scores[idx])
            overlap_count = 0
            
            for kw in doc.keywords:
                kw_lower = kw.lower()
                if kw_lower in query_lower:
                    overlap_count += 1
                else:
                    kw_words = set(kw_lower.split())
                    if kw_words.intersection(query_words):
                        overlap_count += 0.5
            
            boost = min(0.35, overlap_count * 0.15)
            final_score = min(1.0, sim + boost)
            final_scores.append(final_score)
            
        scores = np.array(final_scores)
        max_score = float(np.max(scores)) if len(scores) > 0 else 0.0

        # 4. Filter by similarity threshold
        passed_indices = [i for i, score in enumerate(scores) if score >= self.similarity_threshold]
        
        # Sort passed indices by score descending
        sorted_passed_indices = sorted(passed_indices, key=lambda idx: scores[idx], reverse=True)
        
        # Limit to top_k
        top_indices = sorted_passed_indices[:top_k]

        matched_docs = [
            ScoredDocument(
                document=self.corpus[idx],
                similarity_score=float(scores[idx])
            )
            for idx in top_indices
        ]

        # 5. Check for calibrated abstention
        abstained = len(matched_docs) == 0
        abstention_reason = ""
        if abstained:
            abstention_reason = (
                f"No regulatory text found above similarity threshold {self.similarity_threshold} "
                f"for query: '{query}' (highest score was {max_score:.3f})"
            )

        return RetrievalResult(
            matched_docs=matched_docs,
            query=query,
            abstained=abstained,
            abstention_reason=abstention_reason,
            max_similarity=max_score
        )
