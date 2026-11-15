"""Tests for the Marswalk Navigators FastAPI service."""
import pytest
from fastapi.testclient import TestClient
from marswalk.api import app
from marswalk.planner import PROFILES

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "marswalk-api"
    assert data["status"] == "online"
    assert "endpoints" in data
    assert data["endpoints"]["health"] == "/health"
    assert data["endpoints"]["bounds"] == "/bounds"
    assert data["endpoints"]["layers"] == "/layers"
    assert data["endpoints"]["budget"] == "/budget"
    assert data["endpoints"]["briefing"] == "/briefing"


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "marswalk-api"
    assert data["site"] == "gale-boxwork"
    assert data["grid_loaded"] is True
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


def test_cors_headers():
    response = client.get("/health", headers={"Origin": "http://localhost:8080"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


def test_bounds_endpoint():
    response = client.get("/bounds")
    assert response.status_code == 200
    data = response.json()
    assert data["site"] == "gale-boxwork"
    assert "bounds_meters" in data
    assert "bounds_latlon" in data
    assert "center" in data

    bm = data["bounds_meters"]
    assert bm["left"] == 8141200.0
    assert bm["bottom"] == -287500.0
    assert bm["right"] == 8145200.0
    assert bm["top"] == -281500.0

    bdeg = data["bounds_latlon"]
    assert -4.9 < bdeg["min_lat"] < -4.7
    assert 137.3 < bdeg["min_lon"] < 137.5
    assert bdeg["min_lat"] < bdeg["max_lat"]
    assert bdeg["min_lon"] < bdeg["max_lon"]


def test_layers_endpoint():
    response = client.get("/layers")
    assert response.status_code == 200
    data = response.json()
    assert data["site"] == "gale-boxwork"
    assert data["count"] >= 6
    layer_ids = [layer["id"] for layer in data["layers"]]
    expected_layers = ["photo", "terrain", "slope", "hazard", "thermal", "radiation", "traverse"]
    for expected in expected_layers:
        assert expected in layer_ids


def test_site_endpoint():
    response = client.get("/site")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "gale-boxwork"
    assert "grid" in data
    assert data["grid"]["width"] == 200
    assert data["grid"]["height"] == 300
    assert data["grid"]["cell_size_m"] == 20.0
    assert "limits" in data
    assert data["limits"]["slope_caution_deg"] == PROFILES["astronaut"].comfort_slope_deg
    assert data["limits"]["slope_nogo_deg"] == PROFILES["astronaut"].max_slope_deg


def test_limits_endpoint():
    response = client.get("/limits")
    assert response.status_code == 200
    data = response.json()
    assert "profiles" in data
    profiles = data["profiles"]
    assert "astronaut" in profiles
    assert "rover" in profiles

    for agent_key, p in PROFILES.items():
        assert profiles[agent_key]["max_slope_deg"] == p.max_slope_deg
        assert profiles[agent_key]["max_roughness_m"] == p.max_roughness_m
        assert profiles[agent_key]["caution_slope_deg"] == p.comfort_slope_deg
        assert profiles[agent_key]["caution_roughness_m"] == p.caution_roughness_m


def test_route_endpoint_valid():
    start_lat = -4.79383
    start_lon = 137.38965
    end_lat = -4.79630
    end_lon = 137.38799

    response = client.get(
        f"/route?start_lat={start_lat}&start_lon={start_lon}&end_lat={end_lat}&end_lon={end_lon}&agent=astronaut"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["agent"] == "astronaut"
    assert "direct_distance_m" in data
    assert data["direct_distance_m"] > 0
    assert "route_distance_m" in data
    assert data["route_distance_m"] >= data["direct_distance_m"]
    assert "path" in data
    assert len(data["path"]) > 0
    assert "coordinates" in data
    first_coord = data["coordinates"][0]
    assert first_coord[0] == start_lon
    assert first_coord[1] == start_lat
    # Verify budgets attached
    assert "budget" in data
    assert "walk" in data["budget"]
    assert "drive" in data["budget"]
    assert "wheel_load_cases" in data["budget"]


def test_get_budget_endpoint():
    start_lat = -4.79383
    start_lon = 137.38965
    end_lat = -4.79630
    end_lon = 137.38799

    response = client.get(
        f"/budget?start_lat={start_lat}&start_lon={start_lon}&end_lat={end_lat}&end_lon={end_lon}&agent=astronaut"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "route_summary" in data
    assert "budget" in data
    assert data["budget"]["walk"]["metabolic_energy_kcal"] > 0.0
    assert data["budget"]["walk"]["oxygen_consumed_liters"] > 0.0
    assert data["budget"]["walk"]["radiation_absorbed_dose_ugy"] > 0.0


def test_post_custom_budget_endpoint():
    payload = {
        "path": [
            [-4.79383, 137.38965],
            [-4.79450, 137.38900],
            [-4.79630, 137.38799],
        ],
        "agent": "rover",
    }
    response = client.post("/budget", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["agent"] == "rover"
    assert "budget" in data
    assert data["budget"]["drive"]["total_energy_wh"] > 0.0


def test_get_briefing_endpoint():
    start_lat = -4.79383
    start_lon = 137.38965
    end_lat = -4.79630
    end_lon = 137.38799

    response = client.get(
        f"/briefing?start_lat={start_lat}&start_lon={start_lon}&end_lat={end_lat}&end_lon={end_lon}&agent=astronaut"
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "briefing_markdown" in data
    assert "# 🔴 MARSWALK MISSION BRIEFING" in data["briefing_markdown"]
    assert "life_support" in data
    assert "hazard_warnings" in data


def test_route_endpoint_impassable_terrain():
    start_lat = -4.80
    start_lon = 137.38
    end_lat = -4.81
    end_lon = 137.39
    response = client.get(
        f"/route?start_lat={start_lat}&start_lon={start_lon}&end_lat={end_lat}&end_lon={end_lon}&agent=astronaut"
    )
    assert response.status_code == 400
    assert "No safe route found" in response.json()["detail"]


def test_route_endpoint_out_of_bounds():
    response = client.get(
        "/route?start_lat=10.0&start_lon=137.38&end_lat=-4.81&end_lon=137.39&agent=astronaut"
    )
    assert response.status_code == 400
    assert "outside Gale Crater boxwork bounds" in response.json()["detail"]


def test_route_endpoint_invalid_agent():
    response = client.get(
        "/route?start_lat=-4.80&start_lon=137.38&end_lat=-4.81&end_lon=137.39&agent=spaceship"
    )
    assert response.status_code == 422
