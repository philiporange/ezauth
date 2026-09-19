"""Tenant billing stays accessible while usage is paused so agents can restore service.

Provider callbacks bypass application auth and instead use each rail's verification.
Payment lookups are always tenant-scoped before any external status refresh.
"""

import uuid
from dataclasses import asdict
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import BillingApp, DbSession
from ezauth.models.billing import BillingPayment, BillingTransaction
from ezauth.schemas.billing import (
    BalanceResponse,
    TopupRequest,
    TopupResponse,
    TransactionResponse,
    validate_topup_amount,
)
from ezauth.services import billing
from ezauth.services.payments import PaymentError, crypto, paypal, stripe

router = APIRouter(prefix="/billing")
PROVIDERS = {"stripe": stripe, "paypal": paypal, "crypto": crypto}


@router.get("", response_model=BalanceResponse)
async def balance(db: DbSession, app: BillingApp):
    account = await billing.get_or_create_account(db, app.tenant_id)
    usage = await billing.usage_snapshot(db, app.tenant_id)
    return BalanceResponse(
        balance_cents=account.balance_cents,
        balance_usd=Decimal(account.balance_cents) / 100,
        paused=account.paused if settings.billing_enabled else False,
        usage=asdict(usage),
        payment_methods=[name for name, rail in PROVIDERS.items() if rail.configured()],
        crypto_chains=settings.crypto_chain_list if crypto.configured() else [],
    )


@router.post("/topups", response_model=TopupResponse, response_model_exclude_none=True)
async def topup(body: TopupRequest, db: DbSession, app: BillingApp):
    rail = PROVIDERS[body.method]
    if not rail.configured():
        raise HTTPException(400, "Payment method is not configured")
    try:
        cents = validate_topup_amount(body.amount_usd)
        account = await billing.get_or_create_account(db, app.tenant_id)
        base = f"{settings.public_base_url}/dashboard/billing/{app.tenant_id}"
        if body.method == "crypto":
            payment = await rail.create_topup(db, account, cents, chain=body.chain or "")
        elif body.method == "stripe":
            payment = await rail.create_topup(
                db, account, cents, save_card=False,
                success_url=base + "?status=success&session_id={CHECKOUT_SESSION_ID}",
                cancel_url=base + "?status=cancelled",
            )
        else:
            payment = await rail.create_topup(
                db, account, cents, return_url=base + "/paypal/return",
                cancel_url=base + "/paypal/cancel",
            )
    except (ValueError, PaymentError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return TopupResponse.from_payment(payment)


@router.get("/topups/{payment_id}", response_model=TopupResponse, response_model_exclude_none=True)
async def topup_status(payment_id: uuid.UUID, db: DbSession, app: BillingApp):
    payment = await db.scalar(select(BillingPayment).where(
        BillingPayment.id == payment_id, BillingPayment.tenant_id == app.tenant_id,
    ))
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment.provider == "crypto":
        try:
            payment = await crypto.confirm(db, payment.provider_ref)
        except PaymentError as exc:
            raise HTTPException(400, str(exc)) from exc
    return TopupResponse.from_payment(payment)


@router.get("/transactions", response_model=list[TransactionResponse])
async def transactions(db: DbSession, app: BillingApp, limit: int = Query(50, ge=1, le=200)):
    return (await db.scalars(select(BillingTransaction).where(
        BillingTransaction.tenant_id == app.tenant_id,
    ).order_by(BillingTransaction.created_at.desc()).limit(limit))).all()


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: DbSession):
    try:
        await stripe.handle_webhook(
            db, await request.body(), request.headers.get("Stripe-Signature", ""),
        )
    except (PaymentError, ValueError) as exc:
        raise HTTPException(400, "Payment verification failed") from exc
    return {"ok": True}


@router.post("/webhooks/paypal", include_in_schema=False)
async def paypal_webhook(request: Request, db: DbSession):
    try:
        await paypal.handle_webhook(db, request.headers, await request.json())
    except (PaymentError, ValueError) as exc:
        raise HTTPException(400, "Payment verification failed") from exc
    return {"ok": True}


@router.post("/webhooks/crypto", include_in_schema=False)
async def crypto_webhook(request: Request, db: DbSession):
    try:
        await crypto.handle_callback(db, await request.json())
    except (PaymentError, ValueError) as exc:
        raise HTTPException(400, "Payment verification failed") from exc
    return {"ok": True}
