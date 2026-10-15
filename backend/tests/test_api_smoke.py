"""Smoke tests for the API test harness itself."""


async def test_health(api):
    r = await api.get("/api/health")
    assert r.status_code == 200


async def test_admin_can_list_connectors(api):
    r = await api.get("/api/connectors")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["data"]}
    assert "network_scan" in names


async def test_unauthenticated_request_is_rejected(api):
    r = await api.get("/api/connectors", headers={"Authorization": ""})
    assert r.status_code == 401
