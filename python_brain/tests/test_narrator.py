import os
import sys
import pytest
import time
import json
from dataclasses import dataclass

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.rag.corpus import get_mock_corpus, Document
from aegis.rag.retriever import RegulatoryRetriever, ScoredDocument, RetrievalResult
from aegis.narrator.narrator import AlertNarrator, Citation, OperatorAlert
from aegis.risk.bayesian_net import RiskAssessment

def test_retriever_successful_match():
    """1. Retriever: query 'hot work near flammable gas' returns OISD-STD-116 Section 5.3 with score > 0.75."""
    corpus = get_mock_corpus()
    retriever = RegulatoryRetriever(corpus, similarity_threshold=0.75)
    
    result = retriever.retrieve("hot work near flammable gas", top_k=3)
    
    assert len(result.matched_docs) > 0
    # The top document should be OISD-STD-116 Section 5.3
    top_doc = result.matched_docs[0].document
    assert top_doc.source == "OISD-STD-116"
    assert "Section 5.3" in top_doc.section
    assert result.matched_docs[0].similarity_score > 0.75
    assert not result.abstained

def test_retriever_abstention():
    """2. Retriever: query 'underwater basket weaving' returns empty list with abstained=True."""
    corpus = get_mock_corpus()
    retriever = RegulatoryRetriever(corpus, similarity_threshold=0.75)
    
    result = retriever.retrieve("underwater basket weaving", top_k=3)
    
    assert len(result.matched_docs) == 0
    assert result.abstained
    assert "No regulatory text found above similarity threshold" in result.abstention_reason
    assert result.max_similarity < 0.75

# Mock OpenAI client response structure
class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockCompletion:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

class MockCompletions:
    def __init__(self, response_content):
        self.response_content = response_content

    def create(self, *args, **kwargs):
        return MockCompletion(self.response_content)

class MockChat:
    def __init__(self, response_content):
        self.completions = MockCompletions(response_content)

class MockLLMClient:
    def __init__(self, response_content):
        self.chat = MockChat(response_content)

def test_narrator_post_validation_hallucination():
    """3. Narrator: with mock LLM response, post-validation catches and removes a hallucinated citation."""
    corpus = get_mock_corpus()
    retriever = RegulatoryRetriever(corpus, similarity_threshold=0.75)
    
    # Mock LLM response containing one valid citation and one hallucinated citation
    mock_response = {
        "situation": "Flammable gas and hot work are co-located in Zone 2, creating an ignition hazard.",
        "actions": [
            "Suspend hot work immediately.",
            "Verify gas concentration."
        ],
        "regulatory_basis": [
            {
                "citation": "[OISD-STD-116 - Section 5.3 - Gas Monitoring and LEL Limits during Hot Work]",
                "relevance": "This is a valid retrieved citation."
            },
            {
                "citation": "[OSHA 29 CFR 1910.999 - Section 9.9 - Fabricated Pressure Standard]",
                "relevance": "This citation was hallucinated by the LLM."
            }
        ],
        "urgency": "Immediate threat of fire.",
        "abstention_notes": []
    }
    
    mock_client = MockLLMClient(json.dumps(mock_response))
    narrator = AlertNarrator(retriever, llm_client=mock_client)
    
    # Retrieve docs for a hot work scenario (will retrieve OISD-STD-116 Section 5.3)
    retrieved = retriever.retrieve("hot work near flammable gas", top_k=2)
    assert any(doc.document.source == "OISD-STD-116" for doc in retrieved.matched_docs)
    
    # Compute mock risk assessment
    ra = RiskAssessment(
        zone_id=2,
        timestamp=time.time(),
        incident_probability={"critical": 0.8},
        max_probability_state="critical",
        max_probability_value=0.8,
        consequence_severity={"major": 0.9},
        risk_score=85.0,
        contributing_factors=["GasLevel: critical", "HotWorkActive: yes"],
        tti_seconds=12.0,
        plume_radius_m=None,
        affected_workers=3,
        recommendation_urgency="IMMEDIATE_ACTION"
    )
    
    alert = narrator.generate_alert(ra, retrieved)
    
    # Post-validation checks:
    # 1. Valid citation must be preserved
    assert len(alert.regulatory_citations) == 1
    assert alert.regulatory_citations[0].source == "OISD-STD-116"
    assert "Section 5.3" in alert.regulatory_citations[0].section

    # 2. Hallucinated citation must be removed from regulatory_citations
    assert not any(c.source == "OSHA 29 CFR 1910.999" for c in alert.regulatory_citations)
    
    # 3. Hallucination message must be added to abstention_notes
    assert any("Hallucinated citation removed" in note for note in alert.abstention_notes)
    assert any("1910.999" in note for note in alert.abstention_notes)

def test_narrator_no_hallucinations_enforced():
    """4. Narrator: alert contains no citation not present in the retrieved_docs."""
    corpus = get_mock_corpus()
    retriever = RegulatoryRetriever(corpus, similarity_threshold=0.75)
    
    # Mock LLM response that only contains hallucinated citations
    mock_response = {
        "situation": "A general hazard exists in Zone 2.",
        "actions": ["Check area safety."],
        "regulatory_basis": [
            {
                "citation": "[OSHA 29 CFR 1910.999 - Section 9.9 - Fabricated Pressure Standard]",
                "relevance": "This is hallucinated."
            }
        ],
        "urgency": "Caution.",
        "abstention_notes": []
    }
    
    mock_client = MockLLMClient(json.dumps(mock_response))
    narrator = AlertNarrator(retriever, llm_client=mock_client)
    
    # Retrieve nothing (empty query)
    retrieved = retriever.retrieve("underwater basket weaving", top_k=2)
    assert len(retrieved.matched_docs) == 0
    
    ra = RiskAssessment(
        zone_id=2,
        timestamp=time.time(),
        incident_probability={"low": 0.9},
        max_probability_state="low",
        max_probability_value=0.9,
        consequence_severity={"minor": 0.9},
        risk_score=15.0,
        contributing_factors=[],
        tti_seconds=None,
        plume_radius_m=None,
        affected_workers=0,
        recommendation_urgency="MONITOR"
    )
    
    alert = narrator.generate_alert(ra, retrieved)
    
    # Since no docs were retrieved, regulatory_citations list must be completely empty!
    assert len(alert.regulatory_citations) == 0
    assert any("Hallucinated citation removed" in note for note in alert.abstention_notes)

def test_end_to_end_alert_flow():
    """5. End-to-end: RiskAssessment -> retrieval -> LLM -> OperatorAlert in < 5 seconds."""
    corpus = get_mock_corpus()
    retriever = RegulatoryRetriever(corpus, similarity_threshold=0.75)
    
    # Use the mock fallback mode (llm_client = None) which represents local deployment
    narrator = AlertNarrator(retriever, llm_client=None)
    
    ra = RiskAssessment(
        zone_id=2,
        timestamp=time.time(),
        incident_probability={"critical": 0.82},
        max_probability_state="critical",
        max_probability_value=0.82,
        consequence_severity={"catastrophic": 0.9},
        risk_score=82.5,
        contributing_factors=["GasLevel: critical", "HotWorkActive: yes"],
        tti_seconds=15.0,
        plume_radius_m=25.0,
        affected_workers=3,
        recommendation_urgency="IMMEDIATE_ACTION"
    )
    
    t0 = time.time()
    
    # Step 1: Retrieval
    query = "gas leak LEL monitoring hot work permit in Zone C - Reactor Area"
    retrieved = retriever.retrieve(query, top_k=2)
    
    # Step 2: Narration
    alert = narrator.generate_alert(ra, retrieved)
    
    dt = time.time() - t0
    print(f"\n[E2E Alert Duration] {dt*1000:.2f} ms")
    
    # Assert duration < 5 seconds
    assert dt < 5.0, f"Expected alert flow to execute in < 5 seconds, took {dt:.2f} s"
    
    # Check alert structure and mock output
    assert alert.alert_id.startswith("AL-02-")
    assert alert.risk_score == 82.5
    assert len(alert.situation) > 0
    assert len(alert.actions) >= 2
    assert len(alert.urgency) > 0
    
    # Verify the fallback successfully mapped the mock gas + hotwork citation
    assert len(alert.regulatory_citations) == 1
    assert alert.regulatory_citations[0].source == "OISD-STD-116"
    assert "Section 5.3" in alert.regulatory_citations[0].section
