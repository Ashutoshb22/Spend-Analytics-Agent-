"""Tests for the savings realisation tracker.

These run against the working database. The CRUD test creates and then deletes its
own opportunity, so it leaves no residue.

Run:  python -m pytest -q tests/test_savings.py
"""
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def _auth_headers(username: str = "admin", password: str = "admin123"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_savings_list_shape():
    r = client.get("/savings", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "opportunities" in data and isinstance(data["opportunities"], list)
    assert "rollup" in data
    for key in ("identified", "negotiating", "contracted", "realised", "pipeline", "count"):
        assert key in data["rollup"]


def test_savings_suggestions_shape():
    r = client.get("/savings/opportunities", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    for s in data["suggestions"]:
        assert {"kind", "title", "target_annual", "rationale"} <= set(s)
        assert s["target_annual"] >= 0


def test_savings_crud_lifecycle():
    headers = _auth_headers()
    # create (with a category so the opportunity has a measurable slice)
    r = client.post("/savings", json={"title": "Pytest opportunity", "target_annual": 12345, "category": "IT Hardware"}, headers=headers)
    assert r.status_code == 200
    opp = r.json()
    oid = opp["id"]
    assert opp["status"] == "identified"
    assert opp["realised"] == 0

    try:
        # it shows up in the list with the measured fields
        body = client.get("/savings", headers=headers).json()
        found = next((o for o in body["opportunities"] if o["id"] == oid), None)
        assert found is not None
        assert "realised" in found and "pct_to_target" in found

        # advancing to contracted captures a baseline (slice is measurable)
        r = client.patch(f"/savings/{oid}", json={"status": "contracted"}, headers=headers)
        assert r.status_code == 200
        upd = r.json()
        assert upd["status"] == "contracted"
        assert upd["baseline_date"] is not None
        assert upd["baseline_annual"] is not None
    finally:
        # delete cleans up
        assert client.delete(f"/savings/{oid}", headers=headers).status_code == 200

    # a second delete is a 404
    assert client.delete(f"/savings/{oid}", headers=headers).status_code == 404


def test_savings_create_requires_title():
    r = client.post("/savings", json={"title": "   "}, headers=_auth_headers())
    assert r.status_code == 422


def test_savings_update_rejects_bad_status():
    headers = _auth_headers()
    r = client.post("/savings", json={"title": "Bad status probe", "target_annual": 1}, headers=headers)
    oid = r.json()["id"]
    try:
        r = client.patch(f"/savings/{oid}", json={"status": "sideways"}, headers=headers)
        assert r.status_code == 422
    finally:
        client.delete(f"/savings/{oid}", headers=headers)


def test_savings_update_404_for_missing():
    r = client.patch("/savings/999999", json={"status": "negotiating"}, headers=_auth_headers())
    assert r.status_code == 404
