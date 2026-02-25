import pytest


@pytest.fixture
async def fake_redis():
    import fakeredis.aioredis

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def test_check_and_consume_within_limit(fake_redis):
    from ezauth.ratelimiter import RateLimiter

    rl = RateLimiter(fake_redis, [(60, 5)], user_id="test")
    for _ in range(5):
        assert await rl.check_and_consume() is True


async def test_check_and_consume_exceeds_limit(fake_redis):
    from ezauth.ratelimiter import RateLimiter

    rl = RateLimiter(fake_redis, [(60, 2)], user_id="test2")
    assert await rl.check_and_consume() is True
    assert await rl.check_and_consume() is True
    assert await rl.check_and_consume() is False


async def test_namespace_isolation(fake_redis):
    from ezauth.ratelimiter import RateLimiter

    rl1 = RateLimiter(fake_redis, [(60, 1)], user_id="user", namespace="app1")
    rl2 = RateLimiter(fake_redis, [(60, 1)], user_id="user", namespace="app2")

    assert await rl1.check_and_consume() is True
    assert await rl2.check_and_consume() is True
    # rl1 is now at limit, rl2 should be at limit too (separate namespace)
    assert await rl1.check_and_consume() is False
    assert await rl2.check_and_consume() is False


async def test_get_remaining(fake_redis):
    from ezauth.ratelimiter import RateLimiter

    rl = RateLimiter(fake_redis, [(60, 5)], user_id="remaining_test")
    remaining = await rl.get_remaining()
    assert remaining == [5]

    await rl.check_and_consume()
    remaining = await rl.get_remaining()
    assert remaining == [4]
