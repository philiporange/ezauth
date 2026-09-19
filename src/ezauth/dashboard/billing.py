"""Tenant credit controls stay available when application traffic is paused.

Read access follows tenant visibility; spending, saved-card changes and payment
completion require tenant administration. Provider IDs are always scoped locally
before a callback-like dashboard action can ask a provider to complete payment.
"""

import uuid
from decimal import Decimal, DecimalException

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth, templates
from ezauth.dashboard.scope import get_administered_tenant, get_owned_tenant, scope_tenants
from ezauth.dependencies import get_db
from ezauth.models.billing import BillingPayment, BillingTransaction
from ezauth.models.tenant import Tenant
from ezauth.services import billing
from ezauth.services.payments import PaymentError, crypto, paypal, stripe

router = APIRouter()


def money(cents) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def _cents(value, *, signed=False, topup=False) -> int:
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError
        if abs(amount) > 2**63 - 1 or (not signed and amount < 0):
            raise ValueError
        cents = int(amount)
    except (DecimalException, ValueError):
        raise HTTPException(400, "Enter a valid amount with at most two decimal places") from None
    if topup and not settings.billing_min_topup_cents <= cents <= settings.billing_max_topup_cents:
        raise HTTPException(400, "Amount is outside the allowed top-up range")
    return cents


def _url(tenant_id, status=None):
    url = f"/dashboard/billing/{tenant_id}"
    return f"{url}?status={status}" if status else url


async def _account(db, auth, tenant_id, *, write=False):
    getter = get_administered_tenant if write else get_owned_tenant
    tenant = await getter(db, auth, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Not found")
    return tenant, await billing.get_or_create_account(db, tenant.id)


async def _payment(db, tenant_id, **where):
    payment = await db.scalar(select(BillingPayment).filter_by(tenant_id=tenant_id, **where))
    if payment is None:
        raise HTTPException(404, "Not found")
    return payment


@router.get("", response_class=HTMLResponse)
async def list_accounts(
    request: Request, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenants = (await db.scalars(scope_tenants(select(Tenant).order_by(Tenant.name), auth))).all()
    if len(tenants) == 1:
        return RedirectResponse(_url(tenants[0].id), status_code=302)
    rows = []
    for tenant in tenants:
        rows.append((tenant, await billing.get_or_create_account(db, tenant.id),
                     await billing.usage_snapshot(db, tenant.id)))
    return templates.TemplateResponse(request=request, name="billing/list.html", context={
        "request": request, "auth": auth, "rows": rows, "money": money,
    })


@router.get("/{tenant_id}", response_class=HTMLResponse)
async def detail(
    tenant_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenant, account = await _account(db, auth, tenant_id)
    usage = await billing.usage_snapshot(db, tenant_id)
    pending = (await db.scalars(select(BillingPayment).where(
        BillingPayment.tenant_id == tenant_id, BillingPayment.provider == "crypto",
        BillingPayment.status == "pending",
    ).order_by(BillingPayment.created_at.desc()))).all()
    history = (await db.scalars(select(BillingTransaction).where(
        BillingTransaction.tenant_id == tenant_id,
    ).order_by(BillingTransaction.created_at.desc()).limit(50))).all()
    status = request.query_params.get("status")
    flash = {"paid": "Payment received", "cancelled": "Payment cancelled",
             "saved": "Settings saved", "checked": "Payment status updated",
             "adjusted": "Balance adjusted", "card_removed": "Card removed"}.get(status)
    if status == "success":
        completed = await db.scalar(select(BillingPayment.id).where(
            BillingPayment.tenant_id == tenant_id, BillingPayment.provider == "stripe",
            BillingPayment.provider_ref == request.query_params.get("session_id", ""),
            BillingPayment.status == "completed",
        ))
        flash = "Payment received" if completed else "Payment is processing, refresh in a moment"
    days = None
    if usage.estimated_monthly_cost_cents > 0:
        days = max(0, int(Decimal(account.balance_cents) * 30 / usage.estimated_monthly_cost_cents))
    return templates.TemplateResponse(request=request, name="billing/detail.html", context={
        "request": request, "auth": auth, "tenant": tenant, "account": account,
        "usage": usage, "pending": pending, "history": history, "money": money,
        "settings": settings, "days": days, "flash": flash,
        "can_manage": bool(await get_administered_tenant(db, auth, tenant_id)),
        "providers": [name for name, module in (("stripe", stripe), ("paypal", paypal),
                      ("crypto", crypto)) if module.configured()],
    })


@router.post("/{tenant_id}/topup")
async def topup(
    tenant_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    _, account = await _account(db, auth, tenant_id, write=True)
    form = await request.form()
    amount = _cents(form.get("amount_usd", ""), topup=True)
    method = form.get("method")
    provider = {"stripe": stripe, "paypal": paypal, "crypto": crypto}.get(method)
    if provider is None or not provider.configured():
        raise HTTPException(400, "Payment method is not configured")
    base = settings.public_base_url.rstrip("/") + _url(tenant_id)
    try:
        if method == "stripe":
            payment = await stripe.create_topup(
                db, account, amount, save_card=form.get("save_card") == "on",
                success_url=base + "?status=success&session_id={CHECKOUT_SESSION_ID}",
                cancel_url=base + "?status=cancelled",
            )
            url = payment.details["url"]
        elif method == "paypal":
            payment = await paypal.create_topup(db, account, amount,
                return_url=base + "/paypal/return", cancel_url=base + "/paypal/cancel")
            url = payment.details["approve_url"]
        else:
            await crypto.create_topup(db, account, amount, chain=str(form.get("chain", "")))
            url = _url(tenant_id)
    except (PaymentError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(url, status_code=303)


@router.post("/{tenant_id}/settings")
async def update_settings(
    tenant_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    _, account = await _account(db, auth, tenant_id, write=True)
    form = await request.form()
    low = _cents(form.get("low_balance_threshold", ""))
    threshold = _cents(form.get("auto_reload_threshold", ""))
    amount = _cents(form.get("auto_reload_amount", ""), topup=True)
    if max(low, threshold) > 2**31 - 1:
        raise HTTPException(400, "Threshold is too large")
    account.email_warnings = form.get("email_warnings") == "on"
    account.low_balance_threshold_cents = low
    account.auto_reload_enabled = form.get("auto_reload_enabled") == "on"
    account.auto_reload_threshold_cents = threshold
    account.auto_reload_amount_cents = amount
    await db.flush()
    return RedirectResponse(_url(tenant_id, "saved"), status_code=303)


@router.post("/{tenant_id}/card/remove")
async def remove_card(
    tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    _, account = await _account(db, auth, tenant_id, write=True)
    try:
        await stripe.detach_card(account)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.flush()
    return RedirectResponse(_url(tenant_id, "card_removed"), status_code=303)


@router.post("/{tenant_id}/payments/{payment_id}/check")
async def check_payment(
    tenant_id: uuid.UUID, payment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    await _account(db, auth, tenant_id, write=True)
    payment = await _payment(db, tenant_id, id=payment_id, provider="crypto")
    try:
        await crypto.confirm(db, payment.provider_ref)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(_url(tenant_id, "checked"), status_code=303)


@router.post("/{tenant_id}/adjust")
async def adjust(
    tenant_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    if not auth.is_super:
        raise HTTPException(403, "Superadmin access required")
    _, account = await _account(db, auth, tenant_id, write=True)
    form = await request.form()
    amount = _cents(form.get("amount_usd", ""), signed=True)
    description = str(form.get("description", "")).strip()
    if not description or len(description) > 255 or amount == 0:
        raise HTTPException(
            400, "Provide a nonzero amount and a description (at most 255 characters)"
        )
    if amount > 0:
        await billing.credit(db, account, amount, kind="adjustment", description=description,
                             provider="system", provider_ref=None)
    else:
        await billing.charge(db, account, -amount, kind="adjustment", description=description,
                             provider="system", details=None)
    return RedirectResponse(_url(tenant_id, "adjusted"), status_code=303)


@router.get("/{tenant_id}/paypal/return")
async def paypal_return(
    tenant_id: uuid.UUID, token: str, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    await _account(db, auth, tenant_id, write=True)
    await _payment(db, tenant_id, provider="paypal", provider_ref=token)
    try:
        payment = await paypal.capture(db, token)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    status = "paid" if payment.status == "completed" else None
    return RedirectResponse(_url(tenant_id, status), status_code=303)


@router.get("/{tenant_id}/paypal/cancel")
async def paypal_cancel(
    tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    await _account(db, auth, tenant_id)
    return RedirectResponse(_url(tenant_id, "cancelled"), status_code=303)
