"""Prepaid metering keeps fractional usage while serializing balance changes.

Account row locks protect the ledger against simultaneous callbacks and hourly
usage. Provider references plus savepoints make retries safe without rolling
back the caller's transaction. Payment rails and mail failures are isolated so
an unavailable provider cannot stop other tenants from being metered.
"""

import asyncio
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.db.engine import async_session_factory
from ezauth.db.redis import get_redis
from ezauth.models.application import Application
from ezauth.models.billing import BillingAccount, BillingTransaction
from ezauth.models.storage_object import StorageObject
from ezauth.models.tenant import Tenant
from ezauth.models.user import User
from ezauth.services.mail import MailService


@dataclass
class Usage:
    users: int
    storage_bytes: int
    estimated_monthly_cost_cents: Decimal


def monthly_cost_cents(users: int, storage_bytes: int) -> Decimal:
    return Decimal(users) * settings.billing_price_per_1000_users_cents / 1000 + Decimal(
        max(0, storage_bytes - settings.billing_included_storage_bytes)
    ) * settings.billing_price_per_gb_storage_cents / (2**30)


async def usage_snapshot(db: AsyncSession, tenant_id: uuid.UUID) -> Usage:
    users = await db.scalar(
        select(func.count(User.id))
        .join(Application, Application.id == User.app_id)
        .where(Application.tenant_id == tenant_id)
    )
    storage = await db.scalar(
        select(func.coalesce(func.sum(StorageObject.size_bytes), 0))
        .join(Application, Application.id == StorageObject.app_id)
        .where(Application.tenant_id == tenant_id)
    )
    return Usage(users or 0, storage or 0, monthly_cost_cents(users or 0, storage or 0))


async def owner_emails_for_tenant(db: AsyncSession, tenant: Tenant) -> list[str]:
    if tenant.owner_email:
        return [tenant.owner_email]
    return list(
        (
            await db.scalars(
                select(Application.owner_email)
                .where(
                    Application.tenant_id == tenant.id,
                    Application.owner_email.is_not(None),
                    Application.owner_email != "",
                )
                .distinct()
            )
        ).all()
    )


async def send_billing_email(db, account, template, *, amount_cents=0):
    """Billing alerts use tenant ownership, and delivery never aborts billing."""
    if template in {"billing_low_balance", "billing_reload_failed"} and not account.email_warnings:
        return
    tenant = await db.get(Tenant, account.tenant_id)
    if tenant is None:
        return
    subjects = {
        "billing_low_balance": "Your ezAuth credit is running low",
        "billing_paused": "Your ezAuth service is paused",
        "billing_reload_failed": "Your ezAuth auto-reload failed",
        "billing_topup_received": "Your ezAuth top-up was received",
    }
    data = {
        "tenant_name": tenant.name,
        "balance": f"${Decimal(account.balance_cents) / 100:.2f}",
        "threshold": f"${Decimal(account.low_balance_threshold_cents) / 100:.2f}",
        "amount": f"${Decimal(amount_cents) / 100:.2f}",
        "billing_url": f"{settings.public_base_url}/dashboard/billing/{tenant.id}",
    }
    for email in await owner_emails_for_tenant(db, tenant):
        try:
            await MailService().send_template(template, email, subjects[template], data)
        except Exception:
            # SES may also raise transport errors rather than MailError.
            logger.exception("Could not send billing email {template}", template=template)


async def _lock_account(db, account):
    await db.flush()
    return (
        await db.scalars(
            select(BillingAccount)
            .where(BillingAccount.id == account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).one()


async def get_or_create_account(db: AsyncSession, tenant_id: uuid.UUID) -> BillingAccount:
    account = await db.scalar(select(BillingAccount).where(BillingAccount.tenant_id == tenant_id))
    if account is not None:
        return account
    # Lock the parent even before the account exists, serializing lazy creation.
    await db.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    account = await db.scalar(select(BillingAccount).where(BillingAccount.tenant_id == tenant_id))
    if account is not None:
        return account
    account = BillingAccount(tenant_id=tenant_id)
    db.add(account)
    await db.flush()
    await credit(
        db,
        account,
        settings.billing_welcome_credit_cents,
        kind="grant",
        description="Welcome credit",
        provider="system",
        provider_ref=None,
    )
    return account


async def credit(
    db, account, amount_cents, *, kind, description, provider, provider_ref, details=None
):
    """Apply one positive ledger entry; a repeated provider reference is a no-op."""
    if amount_cents < 0:
        raise ValueError("Credit must not be negative")
    account = await _lock_account(db, account)
    if provider_ref and await db.scalar(
        select(BillingTransaction.id).where(BillingTransaction.provider_ref == provider_ref)
    ):
        return None
    try:
        async with db.begin_nested():
            account.balance_cents += amount_cents
            account.low_balance_warned_at = None
            account.auto_reload_failed_at = None
            if account.paused and account.balance_cents >= 0:
                account.paused = False
                account.paused_at = None
            entry = BillingTransaction(
                tenant_id=account.tenant_id,
                kind=kind,
                amount_cents=amount_cents,
                balance_after_cents=account.balance_cents,
                description=description,
                provider=provider,
                provider_ref=provider_ref,
                details=details,
            )
            db.add(entry)
            await db.flush()
    except IntegrityError:
        await db.refresh(account)
        if provider_ref and await db.scalar(
            select(BillingTransaction.id).where(BillingTransaction.provider_ref == provider_ref)
        ):
            return None
        raise
    if kind == "topup":
        await send_billing_email(db, account, "billing_topup_received", amount_cents=amount_cents)
    return entry


async def charge(
    db, account, amount_cents, *, description, details, kind="charge", provider="system"
):
    if amount_cents < 0:
        raise ValueError("Charge must not be negative")
    account = await _lock_account(db, account)
    account.balance_cents -= amount_cents
    entry = BillingTransaction(
        tenant_id=account.tenant_id,
        kind=kind,
        amount_cents=-amount_cents,
        balance_after_cents=account.balance_cents,
        description=description,
        provider=provider,
        details=details,
    )
    db.add(entry)
    await db.flush()
    return entry


async def meter_account(db, account, now):
    if not settings.billing_enabled:
        return
    account = await _lock_account(db, account)
    if account.last_metered_at is None:
        account.last_metered_at = now
        await db.flush()
        return
    elapsed = now - account.last_metered_at
    seconds = (
        Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(elapsed.microseconds) / 1000000
    )
    hours = max(Decimal(0), min(seconds / 3600, Decimal(24 * 31)))
    usage = await usage_snapshot(db, account.tenant_id)
    account.accrued_cents += usage.estimated_monthly_cost_cents * hours / 720
    whole = int(account.accrued_cents)
    if whole >= 1:
        account.accrued_cents -= whole
        await charge(
            db,
            account,
            whole,
            description="Metered usage",
            details={
                "users": usage.users,
                "storage_bytes": usage.storage_bytes,
                "hours": str(hours),
            },
        )
    account.last_metered_at = max(now, account.last_metered_at)
    if (
        account.auto_reload_enabled
        and account.balance_cents < account.auto_reload_threshold_cents
        and account.stripe_payment_method_id
        and (
            account.auto_reload_failed_at is None
            or account.auto_reload_failed_at <= now - timedelta(hours=24)
        )
    ):
        from ezauth.services.payments import stripe

        try:
            intent = await stripe.charge_saved_card(account, account.auto_reload_amount_cents)
        except Exception:
            account.auto_reload_failed_at = now
            await send_billing_email(db, account, "billing_reload_failed")
        else:
            await credit(
                db,
                account,
                account.auto_reload_amount_cents,
                kind="topup",
                description="Automatic card reload",
                provider="stripe",
                provider_ref=intent,
            )
    if account.balance_cents < 0 and not account.paused:
        account.paused = True
        account.paused_at = now
        await send_billing_email(db, account, "billing_paused")
    if (
        not account.paused
        and account.balance_cents < account.low_balance_threshold_cents
        and account.low_balance_warned_at is None
        and account.email_warnings
    ):
        await send_billing_email(db, account, "billing_low_balance")
        account.low_balance_warned_at = now
    await db.flush()


async def is_paused(db: AsyncSession, app: Application) -> bool:
    if not settings.billing_enabled:
        return False
    return bool(
        await db.scalar(
            select(BillingAccount.paused).where(BillingAccount.tenant_id == app.tenant_id)
        )
    )


async def run_metering_pass():
    if not settings.billing_enabled:
        return
    try:
        locked = await get_redis().set(
            "billing:lock",
            secrets.token_hex(8),
            nx=True,
            ex=max(1, settings.billing_metering_interval_seconds - 1),
        )
    except Exception:
        logger.warning("Could not reach Redis for billing lock; skipping pass")
        return
    if not locked:
        return
    async with async_session_factory() as db:
        tenant_ids = list((await db.scalars(select(Tenant.id))).all())
    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as db:
                account = await get_or_create_account(db, tenant_id)
                await meter_account(db, account, datetime.now(timezone.utc))
                await db.commit()
        except Exception:
            logger.exception("Metering failed for tenant {tenant_id}", tenant_id=tenant_id)
    from ezauth.services.payments import crypto

    if crypto.configured():
        async with async_session_factory() as db:
            await crypto.poll_pending(db)
            await db.commit()


async def metering_loop():
    while True:
        await asyncio.sleep(settings.billing_metering_interval_seconds)
        try:
            await run_metering_pass()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Billing metering pass failed")
