import numpy as np
from dataclasses import dataclass, field
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination

@dataclass
class RiskAssessment:
    zone_id: int
    timestamp: float
    incident_probability: dict[str, float]
    max_probability_state: str
    max_probability_value: float
    consequence_severity: dict[str, float]
    risk_score: float
    contributing_factors: list[str]
    tti_seconds: float | None
    plume_radius_m: float | None
    affected_workers: int
    recommendation_urgency: str
    raw_evidence: dict = field(default_factory=dict)

# Explicit definition of string state names for all nodes in the Bayesian network.
# Used for programmatic CPD construction and evidence translation.
STATE_NAMES = {
    "GasLevel": ["low", "medium", "high", "critical"],
    "Temperature": ["normal", "elevated", "high", "critical"],
    "Pressure": ["normal", "elevated", "high", "critical"],
    "TTI_Urgency": ["normal", "watch", "warning", "critical"],
    "EquipAge": ["new", "mid", "old"],
    "HotWorkActive": ["no", "yes"],
    "ConfinedSpace": ["no", "yes"],
    "WorkerCount": ["none", "few", "many"],
    "FatigueScore": ["normal", "moderate", "high"],
    "EquipmentRisk": ["low", "medium", "high", "critical"],
    "PermitRisk": ["low", "medium", "high"],
    "IncidentProbability": ["negligible", "low", "moderate", "high", "critical"],
    "ConsequenceSeverity": ["minor", "moderate", "major", "catastrophic"]
}

def make_softmax_cpd(node_name, parent_names, parent_cards, states_card, weights, decay=0.8, safety_parents=None):
    """
    Programmatically builds a valid TabularCPD by computing a weighted score of parent states
    and distributing probabilities using a Gaussian-like decay centered around the target state index.
    Includes a non-linear safety factor that prevents safety-critical anomalies from being averaged down
    by other normal parameters.
    """
    import itertools
    import math

    # Calculate total columns in CPT
    num_cols = int(np.prod(parent_cards))
    cpt = np.zeros((states_card, num_cols))

    # Get parent state options
    parent_states_iter = itertools.product(*[range(card) for card in parent_cards])

    # Max possible weighted score
    max_score = sum(w * (card - 1) for w, card in zip(weights, parent_cards))
    if max_score == 0:
        max_score = 1.0

    for col_idx, parent_states in enumerate(parent_states_iter):
        # Compute weighted score
        score = sum(w * state for w, state in zip(weights, parent_states))
        
        if safety_parents:
            # Non-linear safety risk propagation: identify max hazard ratio of safety-critical inputs
            safety_ratios = [
                state / (card - 1)
                for name, state, card in zip(parent_names, parent_states, parent_cards)
                if name in safety_parents and card > 1
            ]
            max_safety_ratio = max(safety_ratios) if safety_ratios else 0.0
            
            # Hybrid scoring: 30% weighted average + 70% worst safety factor
            normalized_score = 0.3 * (score / max_score) + 0.7 * max_safety_ratio
        else:
            # Standard weighted normalized score
            normalized_score = score / max_score
            
        # Target state index in the child node
        target_idx = normalized_score * (states_card - 1)

        # Distribute probabilities using Gaussian decay
        col_probs = []
        for i in range(states_card):
            dist = float(i) - target_idx
            prob = math.exp(-(dist * dist) / decay)
            col_probs.append(prob)

        # Normalize column
        sum_probs = sum(col_probs)
        if sum_probs > 0:
            col_probs = [p / sum_probs for p in col_probs]
        else:
            col_probs = [1.0 / states_card] * states_card

        for row_idx, p in enumerate(col_probs):
            cpt[row_idx, col_idx] = p

    # Map parent cards and names to the pgmpy format
    evidence_names = parent_names
    evidence_cards = parent_cards

    # Construct state names mapping for both child and all parent nodes
    state_names = {name: STATE_NAMES[name] for name in [node_name] + parent_names}

    return TabularCPD(
        variable=node_name,
        variable_card=states_card,
        values=cpt,
        evidence=evidence_names,
        evidence_card=evidence_cards,
        state_names=state_names
    )

def build_bayesian_network() -> DiscreteBayesianNetwork:
    model = DiscreteBayesianNetwork([
        # Equipment Risk Subnetwork
        ("GasLevel", "EquipmentRisk"),
        ("Temperature", "EquipmentRisk"),
        ("Pressure", "EquipmentRisk"),
        ("TTI_Urgency", "EquipmentRisk"),
        ("EquipAge", "EquipmentRisk"),

        # Permit Risk Subnetwork
        ("HotWorkActive", "PermitRisk"),
        ("ConfinedSpace", "PermitRisk"),
        ("WorkerCount", "PermitRisk"),

        # Incident Probability Node
        ("EquipmentRisk", "IncidentProbability"),
        ("PermitRisk", "IncidentProbability"),
        ("FatigueScore", "IncidentProbability"),

        # Consequence Node
        ("IncidentProbability", "ConsequenceSeverity")
    ])

    # Define Priors (discrete state probabilities) with state names
    # GasLevel: [low, medium, high, critical]
    cpd_gas = TabularCPD("GasLevel", 4, [[0.85], [0.10], [0.04], [0.01]], state_names={"GasLevel": STATE_NAMES["GasLevel"]})
    # Temperature: [normal, elevated, high, critical]
    cpd_temp = TabularCPD("Temperature", 4, [[0.90], [0.07], [0.02], [0.01]], state_names={"Temperature": STATE_NAMES["Temperature"]})
    # Pressure: [normal, elevated, high, critical]
    cpd_press = TabularCPD("Pressure", 4, [[0.90], [0.07], [0.02], [0.01]], state_names={"Pressure": STATE_NAMES["Pressure"]})
    # TTI_Urgency: [normal, watch, warning, critical]
    cpd_tti = TabularCPD("TTI_Urgency", 4, [[0.95], [0.03], [0.015], [0.005]], state_names={"TTI_Urgency": STATE_NAMES["TTI_Urgency"]})
    # EquipAge: [new, mid, old]
    cpd_age = TabularCPD("EquipAge", 3, [[0.40], [0.40], [0.20]], state_names={"EquipAge": STATE_NAMES["EquipAge"]})

    # HotWorkActive: [no, yes]
    cpd_hotwork = TabularCPD("HotWorkActive", 2, [[0.80], [0.20]], state_names={"HotWorkActive": STATE_NAMES["HotWorkActive"]})
    # ConfinedSpace: [no, yes]
    cpd_confined = TabularCPD("ConfinedSpace", 2, [[0.90], [0.10]], state_names={"ConfinedSpace": STATE_NAMES["ConfinedSpace"]})
    # WorkerCount: [none, few, many]
    cpd_workers = TabularCPD("WorkerCount", 3, [[0.50], [0.40], [0.10]], state_names={"WorkerCount": STATE_NAMES["WorkerCount"]})

    # FatigueScore: [normal, moderate, high]
    cpd_fatigue = TabularCPD("FatigueScore", 3, [[0.80], [0.15], [0.05]], state_names={"FatigueScore": STATE_NAMES["FatigueScore"]})

    # Build Joint CPDs programmatically using make_softmax_cpd
    
    # EquipmentRisk: [low, medium, high, critical] (4 states)
    # Parents: GasLevel (4), Temperature (4), Pressure (4), TTI_Urgency (4), EquipAge (3)
    # Safety parents: GasLevel, Temperature, Pressure, TTI_Urgency
    cpd_eq_risk = make_softmax_cpd(
        node_name="EquipmentRisk",
        parent_names=["GasLevel", "Temperature", "Pressure", "TTI_Urgency", "EquipAge"],
        parent_cards=[4, 4, 4, 4, 3],
        states_card=4,
        weights=[0.35, 0.15, 0.15, 0.25, 0.10],
        decay=0.4,
        safety_parents=["GasLevel", "Temperature", "Pressure", "TTI_Urgency"]
    )

    # PermitRisk: [low, medium, high] (3 states)
    # Parents: HotWorkActive (2), ConfinedSpace (2), WorkerCount (3)
    # Safety parents: HotWorkActive, ConfinedSpace
    cpd_permit_risk = make_softmax_cpd(
        node_name="PermitRisk",
        parent_names=["HotWorkActive", "ConfinedSpace", "WorkerCount"],
        parent_cards=[2, 2, 3],
        states_card=3,
        weights=[0.40, 0.30, 0.30],
        decay=0.3,
        safety_parents=["HotWorkActive", "ConfinedSpace"]
    )

    # IncidentProbability: [negligible, low, moderate, high, critical] (5 states)
    # Parents: EquipmentRisk (4), PermitRisk (3), FatigueScore (3)
    # Safety parents: EquipmentRisk (only equipment failure represents a direct threat; permit risk is exposure/ignition trigger)
    cpd_incident_prob = make_softmax_cpd(
        node_name="IncidentProbability",
        parent_names=["EquipmentRisk", "PermitRisk", "FatigueScore"],
        parent_cards=[4, 3, 3],
        states_card=5,
        weights=[0.45, 0.25, 0.30],
        decay=0.4,
        safety_parents=["EquipmentRisk"]
    )

    # ConsequenceSeverity: [minor, moderate, major, catastrophic] (4 states)
    # Parents: IncidentProbability (5)
    # Safety parents: IncidentProbability
    cpd_consequence = make_softmax_cpd(
        node_name="ConsequenceSeverity",
        parent_names=["IncidentProbability"],
        parent_cards=[5],
        states_card=4,
        weights=[1.0],
        decay=0.4,
        safety_parents=["IncidentProbability"]
    )

    # Add factors to model
    model.add_cpds(
        cpd_gas, cpd_temp, cpd_press, cpd_tti, cpd_age,
        cpd_hotwork, cpd_confined, cpd_workers, cpd_fatigue,
        cpd_eq_risk, cpd_permit_risk, cpd_incident_prob, cpd_consequence
    )

    # Validate model
    assert model.check_model(), "Bayesian network CPD validation failed!"
    return model

class RiskEngine:
    def __init__(self):
        self.model = build_bayesian_network()
        self.inference = VariableElimination(self.model)

    def compute_risk(self, zone_id: int, timestamp: float, evidence: dict) -> RiskAssessment:
        """
        Compute safety risk probabilities given evidence.
        evidence: dict of {node_name: state_str}
        E.g. {"GasLevel": "high", "TTI_Urgency": "warning", "HotWorkActive": "yes"}
        """
        # Filter evidence to make sure keys match network nodes and states are valid
        valid_evidence = {}
        for k, v in evidence.items():
            if self.model.has_node(k) and v is not None:
                cpd = self.model.get_cpds(k)
                if cpd and k in cpd.state_names:
                    states_list = cpd.state_names[k]
                    if v in states_list:
                        valid_evidence[k] = v

        # Run variable elimination for IncidentProbability
        res_prob = self.inference.query(variables=["IncidentProbability"], evidence=valid_evidence, show_progress=False)
        incident_states = res_prob.state_names["IncidentProbability"]
        incident_dist = {incident_states[i]: float(res_prob.values[i]) for i in range(len(incident_states))}

        # Run variable elimination for ConsequenceSeverity
        res_conseq = self.inference.query(variables=["ConsequenceSeverity"], evidence=valid_evidence, show_progress=False)
        conseq_states = res_conseq.state_names["ConsequenceSeverity"]
        conseq_dist = {conseq_states[i]: float(res_conseq.values[i]) for i in range(len(conseq_states))}

        # Calculate max probability state
        max_state = max(incident_dist, key=incident_dist.get)
        max_val = incident_dist[max_state]

        # Calculate a weighted risk score (0 to 100) based on IncidentProbability distribution
        # Weights: negligible=0, low=25, moderate=50, high=75, critical=100
        score_weights = {"negligible": 0.0, "low": 25.0, "moderate": 50.0, "high": 75.0, "critical": 100.0}
        risk_score = sum(incident_dist[state] * score_weights[state] for state in incident_states)

        # Urgency classification
        if risk_score >= 70.0:
            urgency = "IMMEDIATE_ACTION"
        elif risk_score >= 40.0:
            urgency = "INVESTIGATE"
        else:
            urgency = "MONITOR"

        # Determine top contributing factors:
        # We can find variables present in evidence that are not in their lowest/baseline state
        contributing_factors = []
        for k, v in evidence.items():
            if v not in ["low", "normal", "no", "none", "new"]:
                contributing_factors.append(f"{k}: {v}")

        # Extract TTI & plume from raw evidence if passed
        tti_seconds = evidence.get("_tti_seconds")
        plume_radius_m = evidence.get("_plume_radius_m")
        affected_workers = evidence.get("_affected_workers", 0)

        return RiskAssessment(
            zone_id=zone_id,
            timestamp=timestamp,
            incident_probability=incident_dist,
            max_probability_state=max_state,
            max_probability_value=max_val,
            consequence_severity=conseq_dist,
            risk_score=risk_score,
            contributing_factors=contributing_factors,
            tti_seconds=tti_seconds,
            plume_radius_m=plume_radius_m,
            affected_workers=affected_workers,
            recommendation_urgency=urgency,
            raw_evidence=evidence
        )

    def compute_risk_delta(self, evidence_before: dict, evidence_after: dict) -> dict:
        """Shows how risk score and incident distribution changed between two states."""
        ra_before = self.compute_risk(0, 0.0, evidence_before)
        ra_after = self.compute_risk(0, 0.0, evidence_after)
        
        return {
            "score_before": ra_before.risk_score,
            "score_after": ra_after.risk_score,
            "score_delta": ra_after.risk_score - ra_before.risk_score,
            "urgency_before": ra_before.recommendation_urgency,
            "urgency_after": ra_after.recommendation_urgency
        }
