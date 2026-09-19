"""Exercise prepaid accounting, fractional metering and alert state transitions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from ezauth.config import settings
from ezauth.models.billing import BillingTransaction
from ezauth.services import billing


@pytest.mark.parametrize(
    ("users", "storage", "expected"),
    [
        (0, 0, "0"),
        (1500, 0, "150"),
        (0, 3 * 2**30, "200"),
    ],
)
def test_monthly_cost(users, storage, expected):
    assert billing.monthly_cost_cents(users, storage) == Decimal(expected)


async def test_welcome_credit_once(db, tenant):
    account = await billing.get_or_create_account(db, tenant.id)
    assert account.balance_cents == settings.billing_welcome_credit_cents
    assert await billing.get_or_create_account(db, tenant.id) is account
    rows = list((await db.scalars(select(BillingTransaction))).all())
    assert len(rows) == 1
    assert rows[0].kind == "grant"
    assert rows[0].description == "Welcome credit"


async def _topup(db, account, ref="payment_1", amount=500):
    return await billing.credit(
        db, account, amount, kind="topup", description="Top-up", provider="stripe", provider_ref=ref
    )


async def test_credit_idempotent_unpauses_and_rearms(db, tenant):
    account = await billing.get_or_create_account(db, tenant.id)
    account.balance_cents = -100
    account.paused = True
    account.paused_at = datetime.now(timezone.utc)
    account.low_balance_warned_at = account.paused_at
    account.auto_reload_failed_at = account.paused_at
    assert await _topup(db, account) is not None
    assert await _topup(db, account) is None
    assert account.balance_cents == 400
    assert not account.paused
    assert account.paused_at is None
    assert account.low_balance_warned_at is None
    assert account.auto_reload_failed_at is None


async def test_fractional_metering(db, tenant, monkeypatch):
    account = await billing.get_or_create_account(db, tenant.id)

    async def snapshot(*args):
        return billing.Usage(1000, 0, Decimal(100))

    monkeypatch.setattr(billing, "usage_snapshot", snapshot)
    now = datetime.now(timezone.utc)
    await billing.meter_account(db, account, now)
    assert account.last_metered_at == now
    assert account.balance_cents == 500
    await billing.meter_account(db, account, now + timedelta(hours=1))
    assert abs(account.accrued_cents - Decimal(100) / 720) < Decimal("0.000001")
    assert account.balance_cents == 500
    await billing.meter_account(db, account, now + timedelta(hours=9))
    assert account.balance_cents == 499
    assert abs(account.accrued_cents - Decimal("0.25")) < Decimal("0.000002")


async def test_pause_and_low_balance_rearm(db, tenant, monkeypatch, sent_mail):
    tenant.owner_email = "owner@example.com"
    account = await billing.get_or_create_account(db, tenant.id)
    now = datetime.now(timezone.utc)
    account.last_metered_at = now
    account.balance_cents = 10

    async def snapshot(*args):
        return billing.Usage(1000, 0, Decimal(100))

    monkeypatch.setattr(billing, "usage_snapshot", snapshot)
    await billing.meter_account(db, account, now + timedelta(hours=1))
    await billing.meter_account(db, account, now + timedelta(hours=2))
    assert [m["template"] for m in sent_mail] == ["billing_low_balance"]
    await _topup(db, account, amount=1)
    await billing.meter_account(db, account, now + timedelta(hours=3))
    assert [m["template"] for m in sent_mail].count("billing_low_balance") == 2
    await billing.meter_account(db, account, now + timedelta(hours=103))
    assert account.balance_cents < 0
    assert account.paused
    assert sent_mail[-1]["template"] == "billing_paused"


async def test_auto_reload_and_failure_cooldown(db, tenant, monkeypatch, sent_mail):
    from ezauth.services.payments import stripe

    tenant.owner_email = "owner@example.com"
    account = await billing.get_or_create_account(db, tenant.id)
    account.balance_cents = 0
    account.auto_reload_enabled = True
    account.stripe_payment_method_id = "pm_test"
    now = datetime.now(timezone.utc)
    account.last_metered_at = now
    calls = []

    async def success(account, amount):
        calls.append(amount)
        return "pi_reload"

    monkeypatch.setattr(stripe, "charge_saved_card", success)
    await billing.meter_account(db, account, now + timedelta(hours=1))
    assert account.balance_cents == 2000
    assert calls == [2000]
    account.balance_cents = 0

    async def failure(account, amount):
        calls.append(amount)
        raise RuntimeError("declined")

    monkeypatch.setattr(stripe, "charge_saved_card", failure)
    await billing.meter_account(db, account, now + timedelta(hours=2))
    assert account.auto_reload_failed_at == now + timedelta(hours=2)
    await billing.meter_account(db, account, now + timedelta(hours=3))
    assert calls == [2000, 2000]
    assert [m["template"] for m in sent_mail].count("billing_reload_failed") == 1


async def test_idle_usage_never_charges(db, tenant):
    account = await billing.get_or_create_account(db, tenant.id)
    account.balance_cents = 0
    now = datetime.now(timezone.utc)
    account.last_metered_at = now - timedelta(days=100)
    await billing.meter_account(db, account, now)
    assert account.balance_cents == 0
    assert account.accrued_cents == 0
    assert not account.paused
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BillingTransaction)
            .where(BillingTransaction.kind == "charge")
        )
        == 0
    )


async def test_disabled_billing_does_not_meter(db, tenant, monkeypatch):
    account = await billing.get_or_create_account(db, tenant.id)
    monkeypatch.setattr(settings, "billing_enabled", False)
    await billing.meter_account(db, account, datetime.now(timezone.utc))
    assert account.last_metered_at is None


async def test_usage_counts_bots_and_users(db, app, user):
    from ezauth.models.user import User

    db.add(User(app_id=app.id, email="bot@example.com", is_bot=True))
    await db.flush()
    usage = await billing.usage_snapshot(db, app.tenant_id)
    assert usage.users == 2
    assert usage.storage_bytes == 0
    assert usage.estimated_monthly_cost_cents == Decimal("0.2")


async def test_metering_caps_gap_at_31_days(db, tenant, monkeypatch):
    account = await billing.get_or_create_account(db, tenant.id)
    now = datetime.now(timezone.utc)
    account.last_metered_at = now - timedelta(days=100)

    async def snapshot(*args):
        return billing.Usage(1000, 0, Decimal(100))

    monkeypatch.setattr(billing, "usage_snapshot", snapshot)
    await billing.meter_account(db, account, now)
    assert account.balance_cents == 397
    assert abs(account.accrued_cents - Decimal(1) / 3) < Decimal("0.000001")


async def test_alert_opt_out_keeps_pause_and_receipt(db, tenant, sent_mail):
    tenant.owner_email = "owner@example.com"
    account = await billing.get_or_create_account(db, tenant.id)
    account.email_warnings = False
    await billing.send_billing_email(db, account, "billing_low_balance")
    await billing.send_billing_email(db, account, "billing_reload_failed")
    await billing.send_billing_email(db, account, "billing_paused")
    await _topup(db, account)
    assert [mail["template"] for mail in sent_mail] == [
        "billing_paused",
        "billing_topup_received",
    ]


async def test_mail_failure_does_not_undo_credit(db, tenant, monkeypatch):
    from ezauth.services.mail import MailError, MailService

    tenant.owner_email = "owner@example.com"
    account = await billing.get_or_create_account(db, tenant.id)

    async def fail(*args, **kwargs):
        raise MailError("unavailable")

    monkeypatch.setattr(MailService, "send_template", fail)
    await _topup(db, account)
    assert account.balance_cents == 1000
