import random
import time
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class OperatorProfile:
    operator_id: str
    name: str
    shift_start: datetime
    shift_duration_hours: float  # typically 8 or 12
    role: str  # "Field Operator", "Control Room", "Maintenance"
    current_zone: int

@dataclass
class FatigueAssessment:
    operator_id: str
    fatigue_score: float  # 0-100
    hrv_rmssd: float      # mock HRV in ms
    hours_on_shift: float
    is_night_shift: bool
    risk_level: str       # "normal" / "moderate" / "high"
    recommendation: str   # safety action recommendation

@dataclass
class ZoneFatigueState:
    zone_id: int
    max_fatigue_score: float
    avg_fatigue_score: float
    most_fatigued_operator: str
    worker_count: int
    fatigue_level: str    # "normal" / "moderate" / "high" — maps to Bayesian node state

class FatigueMonitor:
    def __init__(self, start_time: datetime = None):
        # We allow passing a start_time for deterministic testing
        # Default to 2:00 AM to simulate a night shift environment by default
        if start_time is None:
            now = datetime.now()
            self.current_time = datetime(now.year, now.month, now.day, 2, 0, 0)
        else:
            self.current_time = start_time
            
        self.last_tick_real_time = time.time()
        self.operators: dict[str, OperatorProfile] = {}
        self._init_mock_operators()

    def _init_mock_operators(self):
        """Prepopulate mock operators across different zones with varied shift start times."""
        # Zone layout reminder:
        # Zone 0: Tank Farm, Zone 1: Compressor, Zone 2: Reactor, Zone 3: Pipe Rack,
        # Zone 4: Control Room, Zone 5: Loading Bay, Zone 6: Utilities, Zone 7: Flare Stack
        
        # OP_001: Alex Mercer (Reactor Area, Zone 2) - Fatigued (11 hours into 12h night shift)
        # Shift started at 15:00 the previous day (since current time is 2:00 AM)
        alex_start = self.current_time - timedelta(hours=11)
        self.operators["OP_001"] = OperatorProfile(
            operator_id="OP_001",
            name="Alex Mercer",
            shift_start=alex_start,
            shift_duration_hours=12.0,
            role="Field Operator",
            current_zone=2
        )

        # OP_002: Elena Rostova (Control Room, Zone 4) - Day shift transition / fresh (1 hour in)
        elena_start = self.current_time - timedelta(hours=1)
        self.operators["OP_002"] = OperatorProfile(
            operator_id="OP_002",
            name="Elena Rostova",
            shift_start=elena_start,
            shift_duration_hours=8.0,
            role="Control Room",
            current_zone=4
        )

        # OP_003: Rajesh Kumar (Loading Bay, Zone 5) - Moderate fatigue (6 hours in)
        rajesh_start = self.current_time - timedelta(hours=6)
        self.operators["OP_003"] = OperatorProfile(
            operator_id="OP_003",
            name="Rajesh Kumar",
            shift_start=rajesh_start,
            shift_duration_hours=8.0,
            role="Maintenance",
            current_zone=5
        )

        # OP_004: Marcus Aurelius (Pipe Rack, Zone 3) - Normal fatigue (3 hours in)
        marcus_start = self.current_time - timedelta(hours=3)
        self.operators["OP_004"] = OperatorProfile(
            operator_id="OP_004",
            name="Marcus Aurelius",
            shift_start=marcus_start,
            shift_duration_hours=12.0,
            role="Field Operator",
            current_zone=3
        )

        # OP_005: Sarah Connor (Control Room, Zone 4) - Approaching end of shift (8 hours in)
        sarah_start = self.current_time - timedelta(hours=8)
        self.operators["OP_005"] = OperatorProfile(
            operator_id="OP_005",
            name="Sarah Connor",
            shift_start=sarah_start,
            shift_duration_hours=8.0,
            role="Control Room",
            current_zone=4
        )

        # OP_006: John Doe (Tank Farm, Zone 0) - Fatigued night shift (10 hours in)
        john_start = self.current_time - timedelta(hours=10)
        self.operators["OP_006"] = OperatorProfile(
            operator_id="OP_006",
            name="John Doe",
            shift_start=john_start,
            shift_duration_hours=12.0,
            role="Maintenance",
            current_zone=0
        )

    def get_fatigue_score(self, operator_id: str) -> FatigueAssessment:
        """
        Compute fatigue score (0-100) based on:
        - Hours on shift (linear ramp to 60 at hour 10, 80 at hour 12, then up to 100)
        - Time of day (night shifts 22:00-06:00 get +15 penalty)
        - Simulated HRV (physiologically mapped: lower HRV -> higher fatigue)
        - Sedentary role penalty (+5 for Control Room)
        - Random micro-variation for realism
        """
        profile = self.operators.get(operator_id)
        if not profile:
            raise ValueError(f"Operator {operator_id} not found.")

        # 1. Calculate hours on shift
        time_diff = self.current_time - profile.shift_start
        hours_on_shift = max(0.0, time_diff.total_seconds() / 3600.0)

        # Hours into shift ramp:
        # linear ramp from 0 at start to 60 at hour 10, 80 at hour 12
        if hours_on_shift <= 10.0:
            shift_ramp = hours_on_shift * 6.0
        else:
            shift_ramp = 60.0 + (hours_on_shift - 10.0) * 10.0

        # 2. Time of day: +15 if night shift (22:00-06:00)
        hour = self.current_time.hour
        is_night = (hour >= 22 or hour < 6)
        night_penalty = 15.0 if is_night else 0.0

        # 3. Simulate HRV RMSSD:
        # Normally ~50ms RMSSD, drops to ~20ms under fatigue
        base_hrv = 52.0
        if profile.role == "Field Operator":
            base_hrv += 3.0
        elif profile.role == "Control Room":
            base_hrv -= 2.0

        # HRV decreases as shift progresses and is lower during night hours
        hrv_rmssd = base_hrv - (2.7 * hours_on_shift)
        if is_night:
            hrv_rmssd -= 4.0

        # Add repeatable deterministic fluctuation + small random noise
        # Using hash-based pseudo-random noise to make it stable but realistic
        h = hash(operator_id) ^ hash(int(self.current_time.timestamp()))
        random.seed(h)
        noise = random.normalvariate(0.0, 1.2)
        hrv_rmssd += noise

        # Clamp HRV to realistic physical limits (15ms to 70ms)
        hrv_rmssd = max(15.0, min(70.0, hrv_rmssd))

        # 4. Map HRV to fatigue contribution (lower HRV -> higher fatigue)
        # If HRV is 50ms, hrv_impact = 0. If it drops to 20ms, hrv_impact = 30 * 0.8 = 24.
        hrv_impact = max(0.0, (50.0 - hrv_rmssd) * 0.8)

        # 5. Activity/Role proxy: Sedentary roles get +5 baseline fatigue penalty due to sleepiness
        role_penalty = 5.0 if profile.role == "Control Room" else 0.0

        # Sum total fatigue score and clamp to [0, 100]
        fatigue_score = shift_ramp + night_penalty + hrv_impact + role_penalty
        fatigue_score = max(0.0, min(100.0, fatigue_score))

        # Classify risk level and recommendation
        if fatigue_score >= 70.0:
            risk_level = "high"
            recommendation = (
                f"Operator {profile.name} ({profile.role}) fatigue is CRITICAL ({fatigue_score:.1f}%). "
                f"HRV dropped to {hrv_rmssd:.1f}ms after {hours_on_shift:.1f}h on shift. Request immediate relief."
            )
        elif fatigue_score >= 40.0:
            risk_level = "moderate"
            recommendation = (
                f"Operator {profile.name} ({profile.role}) fatigue is MODERATE ({fatigue_score:.1f}%). "
                f"HRV is {hrv_rmssd:.1f}ms after {hours_on_shift:.1f}h on shift. Schedule a rest break."
            )
        else:
            risk_level = "normal"
            recommendation = f"Operator {profile.name} fatigue is normal ({fatigue_score:.1f}%)."

        return FatigueAssessment(
            operator_id=operator_id,
            fatigue_score=fatigue_score,
            hrv_rmssd=hrv_rmssd,
            hours_on_shift=hours_on_shift,
            is_night_shift=is_night,
            risk_level=risk_level,
            recommendation=recommendation
        )

    def get_zone_fatigue(self, zone_id: int) -> ZoneFatigueState:
        """Aggregate fatigue for all operators currently assigned to the given zone."""
        zone_operators = [op for op in self.operators.values() if op.current_zone == zone_id]
        
        if not zone_operators:
            return ZoneFatigueState(
                zone_id=zone_id,
                max_fatigue_score=0.0,
                avg_fatigue_score=0.0,
                most_fatigued_operator="",
                worker_count=0,
                fatigue_level="normal"
            )

        assessments = [self.get_fatigue_score(op.operator_id) for op in zone_operators]
        
        max_assessment = max(assessments, key=lambda a: a.fatigue_score)
        avg_score = sum(a.fatigue_score for a in assessments) / len(assessments)
        
        # Determine aggregated fatigue level for Bayesian network input
        max_score = max_assessment.fatigue_score
        if max_score >= 70.0:
            level = "high"
        elif max_score >= 40.0:
            level = "moderate"
        else:
            level = "normal"

        return ZoneFatigueState(
            zone_id=zone_id,
            max_fatigue_score=max_score,
            avg_fatigue_score=avg_score,
            most_fatigued_operator=max_assessment.operator_id,
            worker_count=len(zone_operators),
            fatigue_level=level
        )

    def tick(self):
        """Advance mock time based on actual elapsed wall time."""
        now_real = time.time()
        elapsed_seconds = now_real - self.last_tick_real_time
        self.last_tick_real_time = now_real
        
        # Advance mock clock by the actual elapsed seconds
        self.current_time += timedelta(seconds=elapsed_seconds)
