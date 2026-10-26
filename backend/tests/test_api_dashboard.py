"""API tests for the dashboard endpoints.

These are safe against the working database:
  - /metrics is read-only,
  - the /upload cases here are rejected by guard rails *before* any write.

Run:  python -m pytest -q tests/test_api_dashboard.py
"""
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def _auth_headers(username: str = "admin", password: str = "admin123"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_rejects_wrong_password_with_expected_message():
    r = client.post("/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json().get("detail") == "Incorrect Password"


def test_login_accepts_correct_credentials():
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("token")
    assert body.get("user", {}).get("username") == "admin"


def test_metrics_endpoint_shape():
    r = client.get("/metrics", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    for key in ("totals", "by_category", "top_suppliers", "monthly_trend", "fragmentation", "top_items", "by_bu"):
        assert key in data
    assert "total_spend" in data["totals"]


def test_metrics_accepts_date_range():
    r = client.get(
        "/metrics",
        params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("range") == {"start_date": "2025-01-01", "end_date": "2025-12-31"}
    assert "total_spend" in data["totals"]


def test_metrics_rejects_bad_date():
    r = client.get("/metrics", params={"start_date": "01-01-2025"}, headers=_auth_headers())
    assert r.status_code == 400


def test_upload_history_shape_admin_only():
    r = client.get("/upload-history", headers=_auth_headers())
    assert r.status_code == 200
    assert isinstance(r.json().get("history"), list)
    # workers cannot see the upload ledger
    r2 = client.get("/upload-history", headers=_auth_headers("worker", "worker123"))
    assert r2.status_code == 403


def test_upload_rejects_unsupported_extension():
    r = client.post(
        "/upload",
        files={"file": ("malware.exe", b"hello", "application/octet-stream")},
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_upload_rejects_empty_file():
    r = client.post(
        "/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
        data={"mode": "replace"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_upload_rejects_bad_mode():
    r = client.post(
        "/upload",
        files={"file": ("x.csv", b"Vendor,Amount\nDell,100\n", "text/csv")},
        data={"mode": "sideways"},
        headers=_auth_headers(),
    )
    assert r.status_code == 400
