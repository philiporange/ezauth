"""Tests for dashboard ownership scoping: owners only see their own resources."""

import pytest
from sqlalchemy import select

from ezauth.dashboard.auth import DashboardAuth
from ezauth.dashboard.scope import (
    get_administered_tenant,
    get_owned_app,
    get_owned_tenant,
    scope_applications,
    scope_tenants,
)
from ezauth.models.application import Application, Environment
from ezauth.models.tenant import Tenant
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key


def _make_app(tenant, owner_email=None, name="App"):
    private_pem, kid, _ = generate_jwk_pair()
    return Application(
        tenant_id=tenant.id,
        name=name,
        environment=Environment.dev,
        publishable_key=generate_publishable_key("dev"),
        secret_key=generate_secret_key("dev"),
        owner_email=owner_email,
        jwk_private_pem=private_pem,
        jwk_kid=kid,
    )


@pytest.fixture
async def two_owners(db):
    t_alice = Tenant(name="Alice Co", owner_email="alice@x.com")
    t_bob = Tenant(name="Bob Co", owner_email="bob@x.com")
    db.add_all([t_alice, t_bob])
    await db.flush()
    a_alice = _make_app(t_alice, name="Alice App")
    a_bob = _make_app(t_bob, name="Bob App")
    db.add_all([a_alice, a_bob])
    await db.flush()
    return t_alice, t_bob, a_alice, a_bob


async def test_owner_sees_only_own_tenants(db, two_owners):
    t_alice, t_bob, _, _ = two_owners
    auth = DashboardAuth(email="alice@x.com", is_super=False)
    result = await db.execute(scope_tenants(select(Tenant), auth))
    ids = {t.id for t in result.scalars().all()}
    assert t_alice.id in ids
    assert t_bob.id not in ids


async def test_superadmin_sees_all_tenants(db, two_owners):
    t_alice, t_bob, _, _ = two_owners
    auth = DashboardAuth(email="root@x.com", is_super=True)
    result = await db.execute(scope_tenants(select(Tenant), auth))
    ids = {t.id for t in result.scalars().all()}
    assert {t_alice.id, t_bob.id} <= ids


async def test_owner_cannot_fetch_other_tenant(db, two_owners):
    _, t_bob, _, _ = two_owners
    auth = DashboardAuth(email="alice@x.com", is_super=False)
    assert await get_owned_tenant(db, auth, t_bob.id) is None


async def test_owner_sees_only_own_apps(db, two_owners):
    _, _, a_alice, a_bob = two_owners
    auth = DashboardAuth(email="alice@x.com", is_super=False)
    result = await db.execute(scope_applications(select(Application), auth))
    ids = {a.id for a in result.scalars().all()}
    assert a_alice.id in ids
    assert a_bob.id not in ids


async def test_owner_cannot_fetch_other_app(db, two_owners):
    _, _, _, a_bob = two_owners
    auth = DashboardAuth(email="alice@x.com", is_super=False)
    assert await get_owned_app(db, auth, a_bob.id) is None


async def test_direct_app_owner_without_tenant_ownership(db, two_owners):
    """An app whose owner_email matches is visible even if its tenant isn't owned."""
    _, t_bob, _, _ = two_owners
    legacy = _make_app(t_bob, owner_email="carol@x.com", name="Carol App")
    db.add(legacy)
    await db.flush()

    auth = DashboardAuth(email="carol@x.com", is_super=False)
    assert (await get_owned_app(db, auth, legacy.id)) is not None
    # And the containing tenant becomes visible (but Bob's other app doesn't).
    assert (await get_owned_tenant(db, auth, t_bob.id)) is not None


async def test_tenant_owner_may_administer_own_tenant(db, two_owners):
    t_alice, _, _, _ = two_owners
    auth = DashboardAuth(email="alice@x.com", is_super=False)
    assert (await get_administered_tenant(db, auth, t_alice.id)) is not None


async def test_app_owner_may_not_administer_the_tenant(db, two_owners):
    """Owning an app inside a tenant grants a read, never a rename or a delete."""
    _, t_bob, _, _ = two_owners
    guest = _make_app(t_bob, owner_email="carol@x.com", name="Carol App")
    db.add(guest)
    await db.flush()

    auth = DashboardAuth(email="carol@x.com", is_super=False)
    assert (await get_owned_tenant(db, auth, t_bob.id)) is not None
    assert (await get_administered_tenant(db, auth, t_bob.id)) is None


async def test_superadmin_may_administer_any_tenant(db, two_owners):
    _, t_bob, _, _ = two_owners
    auth = DashboardAuth(email="root@x.com", is_super=True)
    assert (await get_administered_tenant(db, auth, t_bob.id)) is not None
