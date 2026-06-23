import networkx as nx

class EquipmentGraph:
    def __init__(self):
        self.g = nx.DiGraph()
        self._build_mock_graph()

    def _build_mock_graph(self):
        # 1. Add 8 zones
        zones_info = [
            (0, "Zone A - Tank Farm", (100, 100)),
            (1, "Zone B - Compressor Hall", (250, 100)),
            (2, "Zone C - Reactor Area", (400, 100)),
            (3, "Zone D - Pipe Rack", (100, 250)),
            (4, "Zone E - Control Room", (250, 250)),
            (5, "Zone F - Loading Bay", (400, 250)),
            (6, "Zone G - Utilities", (100, 400)),
            (7, "Zone H - Flare Stack", (400, 400)),
        ]
        
        for z_id, name, coords in zones_info:
            self.g.add_node(f"ZONE_{z_id}", type="ZONE", zone_id=z_id, name=name, coords=coords)

        # Connect adjacent zones
        adj_zones = [(0, 1), (1, 2), (0, 3), (1, 4), (2, 5), (3, 4), (4, 5), (3, 6), (5, 7), (6, 7)]
        for z1, z2 in adj_zones:
            self.g.add_edge(f"ZONE_{z1}", f"ZONE_{z2}", relation="adjacent_to")
            self.g.add_edge(f"ZONE_{z2}", f"ZONE_{z1}", relation="adjacent_to")

        # 2. Add ~40 equipment pieces (~5 per zone)
        equip_types = ["Compressor", "Valve", "Reactor", "Tank", "Pipe", "Flare", "Pump", "HeatExchanger"]
        for z_id in range(8):
            for idx in range(5):
                eq_id = z_id * 5 + idx
                eq_type = equip_types[eq_id % len(equip_types)]
                eq_node = f"EQ_{eq_id}"
                self.g.add_node(
                    eq_node,
                    type="EQUIPMENT",
                    equip_id=eq_id,
                    equip_type=eq_type,
                    zone_id=z_id,
                    status="OPERATIONAL"
                )
                self.g.add_edge(f"ZONE_{z_id}", eq_node, relation="contains")

                # Connect some adjacent equipment for domino propagation within the same zone or across zones
                if idx > 0:
                    prev_eq = f"EQ_{z_id * 5 + idx - 1}"
                    self.g.add_edge(prev_eq, eq_node, relation="adjacent_to")
                    self.g.add_edge(eq_node, prev_eq, relation="adjacent_to")

        # 3. Add 200 sensors (linked from SCADA Step 2)
        # Cycle through types matching SCADA simulator:
        # 0: GasConcentration, 1: Temperature, 2: Pressure, 3: FlowRate, 4: Vibration, 5: PH, 6: Level, 7: Humidity
        sensor_types = ["GasConcentration", "Temperature", "Pressure", "FlowRate", "Vibration", "PH", "Level", "Humidity"]
        for s_id in range(200):
            z_id = s_id % 8
            s_type = sensor_types[s_id % 8]
            s_node = f"SENSOR_{s_id}"
            
            # Map sensor to one of the equipment in the zone
            linked_eq_id = z_id * 5 + (s_id % 5)
            linked_eq_node = f"EQ_{linked_eq_id}"
            
            self.g.add_node(
                s_node,
                type="SENSOR",
                sensor_id=s_id,
                sensor_type=s_type,
                zone_id=z_id,
                linked_equipment=linked_eq_node
            )
            self.g.add_edge(linked_eq_node, s_node, relation="monitored_by")

    def get_zone_context(self, zone_id: int) -> dict:
        """Returns all equipment, sensors, and active permits for a zone."""
        eqs = []
        sensors = []
        permits = []
        
        # Get contained equipment
        for n, attrs in self.g.nodes(data=True):
            if attrs.get("zone_id") == zone_id:
                n_type = attrs.get("type")
                if n_type == "EQUIPMENT":
                    eqs.append({
                        "equip_id": attrs["equip_id"],
                        "equip_type": attrs["equip_type"],
                        "status": attrs["status"]
                    })
                elif n_type == "SENSOR":
                    sensors.append({
                        "sensor_id": attrs["sensor_id"],
                        "sensor_type": attrs["sensor_type"]
                    })
                elif n_type == "PERMIT" and attrs.get("status") == "ACTIVE":
                    permits.append({
                        "permit_id": attrs["permit_id"],
                        "permit_type": attrs["permit_type"],
                        "workers_on_permit": attrs["workers_on_permit"]
                    })
                    
        return {
            "zone_id": zone_id,
            "zone_name": self.g.nodes[f"ZONE_{zone_id}"]["name"],
            "equipment": eqs,
            "sensors": sensors,
            "permits": permits
        }

    def get_affected_by_plume(self, affected_zones: list[int]) -> dict:
        """Returns all equipment and workers at risk given affected zones."""
        workers = 0
        eqs = []
        for z_id in affected_zones:
            ctx = self.get_zone_context(z_id)
            for p in ctx["permits"]:
                workers += p["workers_on_permit"]
            for eq in ctx["equipment"]:
                eqs.append({**eq, "zone_id": z_id})
                
        return {
            "affected_zones": affected_zones,
            "total_workers_at_risk": workers,
            "equipment_at_risk": eqs
        }

    def activate_permit(self, permit_id: str, zone_id: int, permit_type: str, duration_hours: float, worker_count: int):
        p_node = f"PERMIT_{permit_id}"
        import time
        expiry_time = time.time() + duration_hours * 3600.0
        self.g.add_node(
            p_node,
            type="PERMIT",
            permit_id=permit_id,
            permit_type=permit_type,
            zone_id=zone_id,
            status="ACTIVE",
            expiry_time=expiry_time,
            workers_on_permit=worker_count
        )
        self.g.add_edge(p_node, f"ZONE_{zone_id}", relation="applies_to")

    def expire_permit(self, permit_id: str):
        p_node = f"PERMIT_{permit_id}"
        if self.g.has_node(p_node):
            self.g.nodes[p_node]["status"] = "EXPIRED"

    def get_domino_candidates(self, zone_id: int) -> list:
        """Finds equipment in adjacent zones that could cascade."""
        zone_node = f"ZONE_{zone_id}"
        adj_zone_nodes = [
            nbr for nbr, edge_attrs in self.g[zone_node].items()
            if edge_attrs.get("relation") == "adjacent_to"
        ]
        
        candidates = []
        for z_node in adj_zone_nodes:
            z_id = self.g.nodes[z_node]["zone_id"]
            # Find equipment contained in this adjacent zone
            for eq_node, edge_attrs in self.g[z_node].items():
                if edge_attrs.get("relation") == "contains":
                    attrs = self.g.nodes[eq_node]
                    candidates.append({
                        "equip_id": attrs["equip_id"],
                        "equip_type": attrs["equip_type"],
                        "zone_id": z_id
                    })
        return candidates
