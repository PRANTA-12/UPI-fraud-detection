import pytest


def test_root_and_health_keep_original_contract(client, monkeypatch):
    r = client.get("/").json()
    assert r["message"] == "UPI Fraud Detection API is running" and r["websocket"] == "/ws/live" and "live_feed" in r
    assert r["name"] == "UPI SENTINEL" and "not native UPI" in r["dataset_notice"]
    h = client.get("/health").json()
    assert h["status"] == "healthy" and h["model"] == "XGBoost" and h["database"] == "PostgreSQL" and h["database_connection"] == "ok"
    import api.routers.legacy as legacy
    monkeypatch.setattr(legacy.db, "ping", lambda: False)
    down = client.get("/health"); assert down.status_code == 503 and down.json()["detail"] == "Database connection unavailable"


def test_security_headers_and_request_id(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and r.headers["x-request-id"]


class TestPredictContract:
    """The original /predict behaviour must be preserved."""

    def test_fraud_like(self, client):
        r = client.post("/predict", json={"transaction_id": 900}); b = r.json()
        assert r.status_code == 200
        assert {"prediction_id", "transaction_id", "prediction", "result", "fraud_probability", "risk_level", "threshold", "model"} <= b.keys()
        assert b["prediction"] == 1 and b["result"] == "Fraud" and b["risk_level"] == "High" and b["model"] == "XGBoost"

    def test_prediction_is_stored_with_metadata(self, client):
        from core import db
        client.post("/predict", json={"transaction_id": 5})
        row = db.query_one("SELECT * FROM fraud_predictions WHERE transaction_id = 5")
        assert row["source"] == "api" and row["model_version"] and row["status"] == "completed" and row["latency_ms"] is not None

    @pytest.mark.parametrize("bad", [-1, 0, "abc", None])
    def test_invalid_id_is_422(self, client, bad):
        assert client.post("/predict", json={"transaction_id": bad}).status_code == 422

    def test_missing_transaction_is_404_with_original_message(self, client):
        r = client.post("/predict", json={"transaction_id": 999999999})
        assert r.status_code == 404 and r.json()["detail"] == "Transaction ID 999999999 not found" and r.json()["request_id"]

    def test_stream_status_original_keys(self, client):
        b = client.get("/stream/status").json()
        assert {"stream", "pending_length", "consumer_groups"} <= b.keys() and {"length", "groups", "dlq_length"} <= b.keys()


class TestAuth:
    def test_protected_routes_require_token(self, client):
        for path in ["/dashboard/kpis", "/transactions", "/analytics/summary", "/model/info", "/system/health", "/settings"]:
            assert client.get(path).status_code == 401, path

    def test_bad_token_rejected(self, client):
        assert client.get("/settings", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_login_wrong_password_and_unknown_user(self, client):
        assert client.post("/auth/login", json={"username": "admin", "password": "x"}).status_code == 401
        assert client.post("/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401

    def test_login_rate_limited(self, client):
        codes = [client.post("/auth/login", json={"username": "admin", "password": "bad"}).status_code for _ in range(12)]
        assert 429 in codes and codes[0] == 401

    def test_rbac_viewer_cannot_write_settings_or_read_audit(self, client, viewer):
        assert client.get("/settings", headers=viewer).json()["can_edit"] is False
        assert client.put("/settings", headers=viewer, json={}).status_code == 403
        assert client.get("/admin/audit", headers=viewer).status_code == 403

    def test_admin_updates_settings_and_it_is_audited(self, client, admin):
        body = {"risk_low_max": 0.2, "risk_high_min": 0.8, "refresh_seconds": 10, "alerts_enabled": False, "alert_min_risk": "Medium",
                "alert_sound": False, "default_risk_filter": "High", "default_page_size": 50}
        assert client.put("/settings", headers=admin, json=body).status_code == 200
        assert client.get("/settings", headers=admin).json()["settings"]["risk_high_min"] == 0.8
        actions = [a["action"] for a in client.get("/admin/audit", headers=admin).json()["items"]]
        assert "settings_updated" in actions and "login_success" in actions
        client.put("/settings", headers=admin, json={**body, "risk_low_max": 0.3, "risk_high_min": 0.7})   # restore

    def test_invalid_settings_rejected(self, client, admin):
        assert client.put("/settings", headers=admin, json={"risk_low_max": 0.9, "risk_high_min": 0.5}).status_code == 422


class TestDashboardData:
    @pytest.fixture()
    def seeded(self, client):
        for i in (1, 2, 900):
            client.post("/predict", json={"transaction_id": i})

    def test_kpis_come_from_db_and_separate_truth_from_prediction(self, client, admin, seeded):
        k = client.get("/dashboard/kpis", headers=admin).json()
        assert k["predicted"]["processed"] == 3 and k["predicted"]["flagged"] >= 1
        assert k["ground_truth"]["actual_fraud_processed"] >= 1 and "detection_rate" in k["ground_truth"]
        ho = k["ground_truth"]["held_out"]
        assert ho["available"] and ho["train_time_max"] > 0 and ho["processed"] == 0      # synthetic test rows are all in the training period
        assert client.get("/dashboard/kpis?model_version=nope", headers=admin).json()["predicted"]["processed"] == 0

    def test_transactions_pagination_filter_sort(self, client, admin, seeded):
        p = client.get("/transactions?page_size=2&sort=fraud_probability&order=desc", headers=admin).json()
        assert p["total"] == 3 and len(p["items"]) == 2 and p["total_pages"] == 2
        probs = [i["fraud_probability"] for i in p["items"]]; assert probs == sorted(probs, reverse=True)
        assert client.get("/transactions?risk=High", headers=admin).json()["total"] >= 1
        assert client.get("/transactions?q=900", headers=admin).json()["items"][0]["transaction_id"] == 900

    @pytest.mark.parametrize("qs", ["sort=amount;DROP TABLE transactions", "order=sideways", "page_size=1000", "risk=Extreme", "page=0"])
    def test_bad_query_params_rejected(self, client, admin, qs):
        assert client.get(f"/transactions?{qs}", headers=admin).status_code == 422

    def test_investigation_explain_compare(self, client, admin, seeded):
        d = client.get("/transactions/900", headers=admin).json()
        assert d["transaction"]["actual_label"] == "Fraud" and len(d["features"]) == 28 and len(d["history"]) == 1
        ex = client.get("/transactions/900/explain?top=5", headers=admin).json()
        assert len(ex["contributions"]) == 5 and ex["unit"].startswith("log-odds")
        cmp = client.get("/transactions/900/compare", headers=admin).json()
        by = {v["model_version"]: v for v in cmp["versions"]}
        assert {"legacy", "v1"} <= by.keys() and by["v1"]["stored_prediction"] is not None
        assert 0 <= by["legacy"]["rescored_probability"] <= 1 and by["legacy"]["threshold"] == 0.5
        assert client.get("/model/metrics?version=legacy", headers=admin).status_code == 404      # no fabricated metrics for legacy
        assert client.get("/transactions/123456/explain", headers=admin).status_code == 404

    def test_analytics_and_model_endpoints(self, client, admin, seeded):
        s = client.get("/analytics/summary", headers=admin).json(); cm = s["confusion_matrix"]
        assert sum(cm.values()) == 3
        assert len(client.get("/analytics/hourly", headers=admin).json()["points"]) == 24
        assert len(client.get("/analytics/probability-distribution", headers=admin).json()["bins"]) == 20
        assert client.get("/analytics/high-risk-patterns", headers=admin).status_code == 200
        m = client.get("/model/metrics", headers=admin).json(); assert 0 < m["test"]["pr_auc"] <= 1 and m["roc_curve"] and m["pr_curve"]
        assert client.get("/model/importance?top=3", headers=admin).json()["features"][0]["mean_abs_shap"] > 0
        assert client.get("/model/drift", headers=admin).json()["status"] == "insufficient_data"
        assert client.get("/model/info?version=v999", headers=admin).status_code == 404
        assert client.get("/model/history", headers=admin).json()["active"]

    def test_date_filter_validation(self, client, admin):
        assert client.get("/analytics/summary?date_from=2030-01-02&date_to=2030-01-01", headers=admin).status_code == 422

    def test_risk_bands_follow_settings(self, client, admin, seeded):
        base = {"refresh_seconds": 5, "alerts_enabled": True, "alert_min_risk": "High", "alert_sound": False, "default_risk_filter": "All", "default_page_size": 25}
        client.put("/settings", headers=admin, json={**base, "risk_low_max": 0.0001, "risk_high_min": 0.0002})
        try:
            assert client.get("/dashboard/risk-distribution", headers=admin).json()["distribution"][2]["count"] == 3
        finally:
            client.put("/settings", headers=admin, json={**base, "risk_low_max": 0.3, "risk_high_min": 0.7})

    def test_system_health(self, client, admin):
        h = client.get("/system/health", headers=admin).json()
        assert h["components"]["postgresql"]["status"] == "operational" and h["components"]["redis"]["status"] == "operational"
        assert h["components"]["consumers"]["status"] == "down" and h["overall"] == "down"      # no consumer running in this test
        assert "CPU" in h["disclaimer"]


def test_unhandled_errors_do_not_leak_details(client, admin, monkeypatch):
    import api.routers.dashboard as d
    monkeypatch.setattr(d, "_kpis", lambda *a, **k: 1 / 0)
    from starlette.testclient import TestClient
    c = TestClient(client.app, raise_server_exceptions=False)
    r = c.get("/dashboard/kpis", headers=admin)
    assert r.status_code == 500 and r.json()["detail"] == "Internal server error" and "division" not in r.text
