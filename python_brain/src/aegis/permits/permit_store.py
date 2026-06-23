import time
from dataclasses import dataclass

@dataclass
class Permit:
    permit_id: str
    permit_type: str
    zone_id: int
    duration_hours: float
    worker_count: int
    issued_at: float
    expiry_time: float
    status: str = "ACTIVE"

class PermitStore:
    def __init__(self, equipment_graph=None):
        self.active_permits: dict[str, Permit] = {}
        self.equipment_graph = equipment_graph
        self._next_id = 1
        self._prepopulate_permits()

    def _prepopulate_permits(self):
        # Prepopulate demo scenario permits:
        # 1. HotWork in Zone 2
        self.issue_permit("HotWork", zone_id=2, duration_hours=4.0, worker_count=3)
        # 2. ConfinedSpace in Zone 5
        self.issue_permit("ConfinedSpace", zone_id=5, duration_hours=6.0, worker_count=2)
        # 3. LineBreak in Zone 3
        self.issue_permit("LineBreak", zone_id=3, duration_hours=8.0, worker_count=4)

    def issue_permit(self, permit_type: str, zone_id: int, duration_hours: float, worker_count: int) -> str:
        permit_id = f"PM-{self._next_id:04d}"
        self._next_id += 1
        
        now = time.time()
        expiry_time = now + duration_hours * 3600.0
        
        permit = Permit(
            permit_id=permit_id,
            permit_type=permit_type,
            zone_id=zone_id,
            duration_hours=duration_hours,
            worker_count=worker_count,
            issued_at=now,
            expiry_time=expiry_time
        )
        self.active_permits[permit_id] = permit

        # Sync with equipment graph if linked
        if self.equipment_graph:
            self.equipment_graph.activate_permit(
                permit_id, zone_id, permit_type, duration_hours, worker_count
            )

        return permit_id

    def revoke_permit(self, permit_id: str):
        if permit_id in self.active_permits:
            self.active_permits[permit_id].status = "EXPIRED"
            if self.equipment_graph:
                self.equipment_graph.expire_permit(permit_id)

    def get_active_for_zone(self, zone_id: int) -> list[Permit]:
        return [
            p for p in self.active_permits.values()
            if p.zone_id == zone_id and p.status == "ACTIVE"
        ]

    def get_conflicting(self, zone_id: int, permit_type: str) -> list[Permit]:
        # Simple conflict check: e.g. checking for other active permits in the same zone
        active = self.get_active_for_zone(zone_id)
        return [p for p in active if p.permit_type != permit_type]

    def tick(self):
        """Expires any permits past their duration."""
        now = time.time()
        for permit_id, permit in list(self.active_permits.items()):
            if permit.status == "ACTIVE" and now >= permit.expiry_time:
                permit.status = "EXPIRED"
                if self.equipment_graph:
                    self.equipment_graph.expire_permit(permit_id)
