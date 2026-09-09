from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_current_patient() -> None:
    assert client.get("/health").status_code == 200
    response = client.get("/api/v1/patients/patient-001/current")
    assert response.status_code == 200
    assert response.json()["patient_id"] == "patient-001"


def test_login_and_task_flow() -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "doctor.unit.test@example.invalid", "password": "unit-test-password-not-secret"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "doctor"

    task = client.post(
        "/api/v1/patients/patient-001/tasks",
        json={
            "type": "check_in",
            "priority": "normal",
            "title": "Test mock",
            "payload": {"questions": []},
        },
    )
    assert task.status_code == 200
    assert task.json()["status"] == "created"


def test_resolve_alert_requires_note() -> None:
    response = client.patch("/api/v1/alerts/alert-001/resolve", json={})
    assert response.status_code == 422


def test_alert_acknowledge_and_resolve_are_visible_in_patient_alerts() -> None:
    alerts = client.get("/api/v1/patients/patient-004/alerts")
    assert alerts.status_code == 200
    alert_id = alerts.json()["items"][0]["alert_id"]

    acknowledge = client.patch(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        json={"user_id": "doctor-test"},
    )
    assert acknowledge.status_code == 200

    acknowledged_alerts = client.get("/api/v1/patients/patient-004/alerts")
    acknowledged = acknowledged_alerts.json()["items"][0]
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "doctor-test"

    resolve = client.patch(
        f"/api/v1/alerts/{alert_id}/resolve",
        json={"user_id": "doctor-test", "note": "Controllo completato."},
    )
    assert resolve.status_code == 200

    resolved_alerts = client.get("/api/v1/patients/patient-004/alerts")
    resolved = resolved_alerts.json()["items"][0]
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "doctor-test"
    assert resolved["resolution_note"] == "Controllo completato."


def test_absence_scenario_exposes_alert_for_dashboard(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_SCENARIO", "absence")
    response = client.get("/api/v1/patients/patient-001/current")
    assert response.status_code == 200
    body = response.json()
    assert body["signal_type"] == "absence"
    assert body["anomaly_score"] == 22.0

    alerts = client.get("/api/v1/patients/patient-001/alerts")
    assert alerts.status_code == 200
    items = alerts.json()["items"]
    absence = next((item for item in items if item["category"] == "no_movement"), None)
    assert absence is not None
    assert absence["title"] == "Assenza di movimento da verificare"
    assert absence["level"] == "orange"
    payload = absence["payload"]
    assert payload["last_room"] == "living_room"
    assert payload["duration_minutes"] == 297.0
    assert payload["ble_quality"] == "ok"
    assert payload["last_transition_at"]


def test_day_profile_endpoint_returns_overlay_data() -> None:
    response = client.get("/api/v1/patients/patient-001/day-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["bands"] == ["00-06", "06-10", "10-14", "14-18", "18-22", "22-24"]
    assert len(body["today"]) == 6
    assert len(body["yesterday"]) == 6
    assert len(body["baseline_day"]) == 6
    assert body["baseline_available"] is True
    today = {row["band"]: row for row in body["today"]}
    with_data = next((row for row in today.values() if row.get("heart_rate_mean") is not None), None)
    assert with_data is not None
    assert "dominant_room" in with_data


def test_system_status_exposes_trend_and_drift() -> None:
    response = client.get("/api/v1/patients/patient-001/system-status")
    assert response.status_code == 200
    ai = response.json()["ai"]
    assert "trend" in ai
    assert "best" in ai["trend"]
    assert "windows" in ai["trend"]
    assert ai["trend"]["best"]["direction"] in {"in_aumento", "in_diminuzione", "stabile", "unknown"}
    assert ai["drift"]["status"] == "stable"


def test_decisions_include_trend() -> None:
    response = client.get("/api/v1/patients/patient-001/decisions")
    assert response.status_code == 200
    trend = response.json()["items"][-1].get("trend")
    assert trend is not None
    assert "best" in trend
    assert "window_days" in trend["best"]


def test_drift_and_retraining_endpoints() -> None:
    drift_resp = client.get("/api/v1/patients/patient-001/ai/drift")
    assert drift_resp.status_code == 200
    assert drift_resp.json()["drift"]["status"] == "stable"

    approve_resp = client.post("/api/v1/patients/patient-001/ai/retraining/approve", json={"note": "Test"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "retrained"
    assert approve_resp.json()["drift"]["retrained_at"] is not None

    reject_resp = client.post("/api/v1/patients/patient-001/ai/retraining/reject", json={})
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "stable"


def test_model_metrics_includes_drift() -> None:
    resp = client.get("/api/v1/patients/patient-001/ai/model-metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "drift" in body

def test_weekly_reports_endpoint_returns_emilio_fields() -> None:
    resp = client.get("/api/v1/patients/patient-001/reports/weekly?limit=4")
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == "patient-001"
    assert isinstance(body["items"], list) and body["items"]
    assert body["items"] == body["reports"]
    report = body["items"][0]
    assert report["report_id"]
    assert report["title"]
    assert report["week_start"] and report["week_end"]
    assert report["mean_score"] is not None
    assert report["max_score"] is not None
    assert "attention_days" in report
    assert report["tasks"]["completed"] >= 0
    assert report["sleep"]["mean_minutes"] is not None
    assert report["summary"]
    assert len(body["items"]) <= 4


def test_weekly_report_manual_generation_endpoint() -> None:
    resp = client.post("/api/v1/patients/patient-001/reports/generate", json={"force": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated"] is True
    assert body["report"]["report_id"]

def test_morning_brief_endpoint_returns_emilio_fields() -> None:
    resp = client.get("/api/v1/patients/patient-001/morning-brief")
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == "patient-001"
    assert body["summary"]
    assert "sleep_minutes" in body
    assert "night_room_changes" in body
    assert "heart_rate_mean" in body or "night_heart_rate_mean" in body
    assert "max_score" in body or "ai_score" in body
    assert body["confidence"] in {"alta", "media", "bassa"}
    assert "baseline" in body
    assert "disclaimer" in body
