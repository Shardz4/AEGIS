import os
import sys
import pytest
import numpy as np
import time

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.graph.equipment_graph import EquipmentGraph

def test_dynamic_site_map_loading():
    """Verify that a custom site map is dynamically loaded and replaces the mock graph."""
    graph = EquipmentGraph()
    
    config = {
        "zones": [
            {"zone_id": 0, "name": "Zone A", "coords": [0, 0], "is_safe_haven": False},
            {"zone_id": 1, "name": "Zone B", "coords": [10, 0], "is_safe_haven": False},
            {"zone_id": 2, "name": "Zone C", "coords": [20, 0], "is_safe_haven": True}
        ],
        "adjacencies": [
            [0, 1], [1, 2]
        ]
    }
    
    graph.load_site_map(config)
    
    # Assert nodes exist
    assert "ZONE_0" in graph.g.nodes
    assert "ZONE_1" in graph.g.nodes
    assert "ZONE_2" in graph.g.nodes
    
    # Check attributes
    assert graph.g.nodes["ZONE_0"]["name"] == "Zone A"
    assert graph.g.nodes["ZONE_2"]["coords"] == (20, 0)
    assert graph.g.nodes["ZONE_2"]["is_safe_haven"] is True
    
    # Check adjacencies (bi-directional)
    assert graph.g.has_edge("ZONE_0", "ZONE_1")
    assert graph.g.has_edge("ZONE_1", "ZONE_0")
    assert graph.g.has_edge("ZONE_1", "ZONE_2")
    assert graph.g.has_edge("ZONE_2", "ZONE_1")

def test_evacuation_routing_clean_path():
    """Verify shortest path selection when no hazards are present."""
    graph = EquipmentGraph()
    config = {
        "zones": [
            {"zone_id": 0, "name": "Start", "coords": [0, 0]},
            {"zone_id": 1, "name": "Bridge", "coords": [10, 0]},
            {"zone_id": 2, "name": "Dest", "coords": [20, 0]}
        ],
        "adjacencies": [
            [0, 1], [1, 2]
        ]
    }
    graph.load_site_map(config)
    
    # Find path with 0 risk and no plume
    path = graph.find_safe_evacuation_path(
        start_zone_id=0,
        target_zone_id=2,
        zone_risk_metrics={},
        plume_zones=[]
    )
    
    assert path == [0, 1, 2]

def test_evacuation_routing_risk_slashing():
    """Verify that route is penalized ('slashed') and shifts to a clean longer path."""
    graph = EquipmentGraph()
    # Path A: 0 -> 1 -> 2 (Base distance: 10 + 10 = 20)
    # Path B: 0 -> 3 -> 2 (Base distance: 30 + 30 = 60)
    config = {
        "zones": [
            {"zone_id": 0, "name": "Start", "coords": [0, 0]},
            {"zone_id": 1, "name": "Bridge Short", "coords": [10, 0]},
            {"zone_id": 2, "name": "Dest", "coords": [20, 0]},
            {"zone_id": 3, "name": "Bridge Long", "coords": [10, 30]}
        ],
        "adjacencies": [
            [0, 1], [1, 2],
            [0, 3], [3, 2]
        ]
    }
    graph.load_site_map(config)
    
    # Case A: When Zone 1 is clean, we take 0 -> 1 -> 2
    path_clean = graph.find_safe_evacuation_path(0, 2, {}, [])
    assert path_clean == [0, 1, 2]
    
    # Case B: When Zone 1 has high-risk (e.g. 50.0), its edge cost becomes much larger than Path B
    # cost for 0 -> 1 -> 2 = 20 * (1 + 50 * 100) = ~100000
    # cost for 0 -> 3 -> 2 = 60 * (1 + 0) = 60
    # Pathfinder should choose 0 -> 3 -> 2
    path_slashed = graph.find_safe_evacuation_path(
        start_zone_id=0,
        target_zone_id=2,
        zone_risk_metrics={1: 50.0},
        plume_zones=[]
    )
    assert path_slashed == [0, 3, 2]

def test_evacuation_routing_hard_block():
    """Verify that plume-affected or critical zones are treated as completely blocked."""
    graph = EquipmentGraph()
    config = {
        "zones": [
            {"zone_id": 0, "name": "Start", "coords": [0, 0]},
            {"zone_id": 1, "name": "Bridge Short", "coords": [10, 0]},
            {"zone_id": 2, "name": "Dest", "coords": [20, 0]},
            {"zone_id": 3, "name": "Bridge Long", "coords": [10, 30]}
        ],
        "adjacencies": [
            [0, 1], [1, 2],
            [0, 3], [3, 2]
        ]
    }
    graph.load_site_map(config)
    
    # Set Zone 1 as active plume zone
    path = graph.find_safe_evacuation_path(
        start_zone_id=0,
        target_zone_id=2,
        zone_risk_metrics={},
        plume_zones=[1]
    )
    
    # Should definitely avoid Zone 1 and take Zone 3
    assert path == [0, 3, 2]
