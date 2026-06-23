import os
import time
import json
from dataclasses import dataclass
from jinja2 import Environment, FileSystemLoader
from aegis.risk.bayesian_net import RiskAssessment
from aegis.rag.retriever import RegulatoryRetriever, RetrievalResult
from aegis.rag.corpus import Document

@dataclass
class Citation:
    source: str          # e.g., "OISD-STD-116"
    section: str         # e.g., "Section 5.3"
    text_excerpt: str    # first 200 chars of matched text
    similarity_score: float
    relevance: str       # LLM relevance description

@dataclass
class OperatorAlert:
    alert_id: str
    timestamp: float
    zone_id: int
    risk_score: float
    situation: str
    actions: list[str]
    regulatory_citations: list[Citation]
    urgency: str
    abstention_notes: list[str]
    llm_call_duration_ms: float
    retrieval_duration_ms: float
    total_duration_ms: float

class AlertNarrator:
    def __init__(self, retriever: RegulatoryRetriever, llm_client=None):
        self.retriever = retriever
        self.llm_client = llm_client
        self._next_id = 1
        
        # Load Jinja2 environment from local templates folder
        template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

        # Initialize OpenAI client if not provided but API key is in environment
        if self.llm_client is None and os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self.llm_client = OpenAI()
                print("Initialized OpenAI client wrapper for AlertNarrator.")
            except ImportError:
                print("openai package not installed. Running in Mock LLM Mode.")

    def generate_alert(self, risk_assessment: RiskAssessment, retrieved_docs: RetrievalResult) -> OperatorAlert:
        t_start = time.time()
        
        # Get zone name mapping
        zones_info = {
            0: "Zone A - Tank Farm",
            1: "Zone B - Compressor Hall",
            2: "Zone C - Reactor Area",
            3: "Zone D - Pipe Rack",
            4: "Zone E - Control Room",
            5: "Zone F - Loading Bay",
            6: "Zone G - Utilities",
            7: "Zone H - Flare Stack",
        }
        zone_name = zones_info.get(risk_assessment.zone_id, f"Zone {risk_assessment.zone_id}")

        # Formulate TTI Display string
        if risk_assessment.tti_seconds is not None:
            tti_val = risk_assessment.tti_seconds
            if tti_val == 0.0:
                tti_display = "IMMEDIATE BREACH (0s)"
            elif tti_val < 60.0:
                tti_display = f"{tti_val:.1f} seconds"
            else:
                tti_display = f"{tti_val/60.0:.1f} minutes"
        else:
            tti_display = "N/A (No trending breach)"

        # Prepare citations list for the prompt
        citations_data = []
        for doc in retrieved_docs.matched_docs:
            citations_data.append({
                "source": doc.document.source,
                "section": doc.document.section,
                "score": doc.similarity_score,
                "text": doc.document.text
            })

        # Load and render template
        template = self.jinja_env.get_template("alert_prompt.jinja2")
        prompt = template.render(
            zone_name=zone_name,
            zone_id=risk_assessment.zone_id,
            risk_score=risk_assessment.risk_score,
            recommendation_urgency=risk_assessment.recommendation_urgency,
            max_probability_state=risk_assessment.max_probability_state,
            max_probability_value=risk_assessment.max_probability_value,
            tti_display=tti_display,
            contributing_factors=risk_assessment.contributing_factors,
            affected_workers=risk_assessment.affected_workers,
            plume_radius_m=risk_assessment.plume_radius_m,
            citations=citations_data,
            threshold=self.retriever.similarity_threshold,
            abstained=retrieved_docs.abstained,
            abstention_reasons=retrieved_docs.abstention_reason
        )

        t_retrieved = time.time()
        retrieval_duration_ms = (t_retrieved - t_start) * 1000.0

        # Call the LLM (or mock)
        llm_response_text = ""
        llm_call_start = time.time()
        
        if self.llm_client is not None:
            try:
                # Call OpenAI-compatible client
                model_name = os.environ.get("AEGIS_LLM_MODEL", "gpt-4o-mini")
                response = self.llm_client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                llm_response_text = response.choices[0].message.content
            except Exception as e:
                print(f"Error calling LLM client: {e}. Falling back to Mock LLM Generator.")
                llm_response_text = self._mock_llm_call(risk_assessment, retrieved_docs)
        else:
            # Fallback to local mock response generator
            llm_response_text = self._mock_llm_call(risk_assessment, retrieved_docs)

        llm_call_duration_ms = (time.time() - llm_call_start) * 1000.0

        # Parse JSON output from LLM (handling code fences if any)
        parsed_json = {}
        cleaned_text = llm_response_text.strip()
        if cleaned_text.startswith("```"):
            # Strip markdown fences (e.g. ```json ... ```)
            lines = cleaned_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_text = "\n".join(lines).strip()

        try:
            parsed_json = json.loads(cleaned_text)
        except Exception as e:
            print(f"Error parsing LLM response as JSON: {e}. Raw content: {llm_response_text}")
            # Generate a structured emergency fallback
            parsed_json = {
                "situation": f"Emergency conditions detected in {zone_name}. Primary risk factors include: {', '.join(risk_assessment.contributing_factors)}.",
                "actions": ["Activate manual emergency procedures.", "Contact the plant safety supervisor immediately.", "Evacuate the local unit area."],
                "regulatory_basis": [{"citation": "No specific regulatory reference available for this condition.", "relevance": "JSON parsing error on LLM output"}],
                "urgency": f"Critical risk score {risk_assessment.risk_score:.1f}% with TTI {tti_display}.",
                "abstention_notes": ["Response JSON parsing failed."]
            }

        # 4. Programmatic Post-Validation of Citations to Prevent Hallucinations
        valid_citations = []
        hallucination_notes = []

        provided_citations = [scored.document for scored in retrieved_docs.matched_docs]
        raw_basis = parsed_json.get("regulatory_basis", [])

        for item in raw_basis:
            citation_str = item.get("citation", "")
            # Check if this citation is the standard fallback
            if "no specific regulatory reference" in citation_str.lower() or "no regulatory reference" in citation_str.lower():
                # Legitimate fallback citation
                continue

            # Validate citation by checking if its source and section match any provided document
            matched_doc = None
            for doc in provided_citations:
                source_upper = doc.source.strip().upper()
                # Parse section ID (e.g., Section 5.3) for loose but robust matching
                section_upper = doc.section.split("-")[0].strip().upper()
                
                if source_upper in citation_str.upper() and section_upper in citation_str.upper():
                    matched_doc = doc
                    break

            if matched_doc:
                # Find the matched scored document to preserve similarity score
                similarity = 1.0
                for scored in retrieved_docs.matched_docs:
                    if scored.document.doc_id == matched_doc.doc_id:
                        similarity = scored.similarity_score
                        break
                
                valid_citations.append(
                    Citation(
                        source=matched_doc.source,
                        section=matched_doc.section,
                        text_excerpt=matched_doc.text[:200],
                        similarity_score=similarity,
                        relevance=item.get("relevance", "")
                    )
                )
            else:
                # Hallucination detected! Strip the citation
                hallucination_notes.append(f"Hallucinated citation removed: {citation_str}")

        # Combine LLM's abstention notes with our hallucination warnings
        final_abstentions = parsed_json.get("abstention_notes", [])
        final_abstentions.extend(hallucination_notes)
        if retrieved_docs.abstained:
            final_abstentions.append(retrieved_docs.abstention_reason)

        alert_id = f"AL-{risk_assessment.zone_id:02d}-{self._next_id:04d}"
        self._next_id += 1

        total_duration_ms = (time.time() - t_start) * 1000.0

        return OperatorAlert(
            alert_id=alert_id,
            timestamp=t_start,
            zone_id=risk_assessment.zone_id,
            risk_score=risk_assessment.risk_score,
            situation=parsed_json.get("situation", ""),
            actions=parsed_json.get("actions", []),
            regulatory_citations=valid_citations,
            urgency=parsed_json.get("urgency", ""),
            abstention_notes=final_abstentions,
            llm_call_duration_ms=llm_call_duration_ms,
            retrieval_duration_ms=retrieval_duration_ms,
            total_duration_ms=total_duration_ms
        )

    def _mock_llm_call(self, risk_assessment: RiskAssessment, retrieved_docs: RetrievalResult) -> str:
        """Deterministic fallback mockup response generator mapping safety states to realistic JSON."""
        # Check contributing factors
        factors_str = " ".join(risk_assessment.contributing_factors).lower()
        
        has_gas = "gas" in factors_str
        has_pressure = "pressure" in factors_str
        has_hotwork = "hotwork" in factors_str or "hot work" in factors_str
        has_confined = "confined" in factors_str

        # Match OISD-STD-116 Section 5.3
        if has_gas and has_hotwork:
            return json.dumps({
                "situation": f"A critical gas concentration anomaly has been detected in Zone {risk_assessment.zone_id} reactor/tank farm area. Active hot work is currently authorized in this zone, presenting an immediate ignition threat.",
                "actions": [
                    "Order immediate stop to all hot work operations in Zone 2 reactor area.",
                    "Isolate all ignition sources and establish local fire-barriers.",
                    "Verify the fire water deluge system status and prepare pressurized fire hose."
                ],
                "regulatory_basis": [
                    {
                        "citation": "[OISD-STD-116 - Section 5.3 - Gas Monitoring and LEL Limits during Hot Work]",
                        "relevance": "Prior to and during hot work, continuous gas monitoring is mandatory, and concentrations must not exceed 10% LEL. Operations must immediately be suspended if limits are breached."
                    }
                ],
                "urgency": "Emergency: Fire risk is high. Hot work must be suspended immediately. Gas LEL limits breached.",
                "abstention_notes": []
            })
            
        # Match mechanical integrity / pressure
        elif has_pressure:
            return json.dumps({
                "situation": f"An abnormal pressure spike is trending in Zone {risk_assessment.zone_id} reactor systems, with an expected threshold breach in seconds. This poses a high risk of pressure vessel failure.",
                "actions": [
                    "Initiate reactor depressurization sequence to route hydrocarbons to the flare stack.",
                    "Monitor valve positioning on separator outlets to confirm positive containment.",
                    "Establish a field exclusion zone and evacuate non-essential operators."
                ],
                "regulatory_basis": [
                    {
                        "citation": "[OSHA 29 CFR 1910.119 - 1910.119(j) - Mechanical Integrity of Critical Equipment]",
                        "relevance": "Mechanical integrity procedures require pressure vessels and sensors to operate within safety limits. Critical pressure deviations require immediate emergency venting."
                    }
                ],
                "urgency": "Critical: Reactor pressure is approaching limits. TTI less than 1 minute. Evacuate local area immediately.",
                "abstention_notes": []
            })
            
        elif has_confined and has_gas:
            return json.dumps({
                "situation": f"Toxic gas concentrations are detected in Zone {risk_assessment.zone_id} while a confined space entry permit is active. This creates an immediate risk of operator asphyxiation inside the vessel.",
                "actions": [
                    "Order immediate evacuation of all personnel inside the confined space.",
                    "Instruct standby hole watch to deploy emergency rescue winch and tripod.",
                    "Equip emergency responders with Self-Contained Breathing Apparatus (SCBA) before rescue attempt."
                ],
                "regulatory_basis": [
                    {
                        "citation": "[OISD-STD-144 - Section 4.3 - Gas Testing for Confined Space Entry]",
                        "relevance": "Atmospheric checks are required. Toxic gas limits (H2S < 5 ppm) must not be exceeded; vessel entry must immediately stop upon detection of toxic contaminants."
                    }
                ],
                "urgency": "Immediate rescue alert: Toxic gas detected in active confined space. Evacuate vessel immediately.",
                "abstention_notes": []
            })

        # Fallback/Abstention mock
        return json.dumps({
            "situation": f"An elevated risk score of {risk_assessment.risk_score:.1f}/100 was computed for Zone {risk_assessment.zone_id}. Telemetry shows minor anomalies coupled with active work permits.",
            "actions": [
                "Deploy field operator to verify local gas and pressure sensors.",
                "Ensure standby personnel are present at all active permit job-sites.",
                "Review P&IDs for potential process isolation points."
            ],
            "regulatory_basis": [
                {
                    "citation": "No specific regulatory reference available for this condition.",
                    "relevance": "No specific regulatory reference was found above the similarity threshold of 0.75."
                }
            ],
            "urgency": "Watch: Monitor zone safety signals. Ensure all permit conditions are logged.",
            "abstention_notes": ["No regulatory match found for current combination of active cold permits and sensor readings."]
        })
