import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from ezauth.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.skipif(True, reason="Requires Redis connection")
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
