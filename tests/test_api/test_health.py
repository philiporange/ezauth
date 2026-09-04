"""Tests for the liveness and readiness endpoints."""


async def test_live_is_a_cheap_liveness_probe(client):
    resp = await client.get("/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_health_reports_each_dependency(client):
    """Readiness must name each dependency so a probe failure is diagnosable."""
    resp = await client.get("/health")
    assert resp.status_code in (200, 503)

    body = resp.json()
    assert set(body["checks"]) == {"database", "redis"}
    assert body["checks"]["database"] is True

    healthy = all(body["checks"].values())
    assert (resp.status_code == 200) is healthy
