# Prepaid billing design

Each tenant has one lazily created billing account, an append-only transaction
ledger, and pending/completed provider payment attempts. Migration 015 seeds
existing tenants with $5 welcome grants; lazy creation uses the configured grant.

Balances and ledger amounts are integer cents. Fractional usage accumulates in
Numeric(18,6). Monthly cost is users / 1000 times the user price, plus fractional
GiB above the included storage allowance times the storage price. Bots are users.
Metering samples current usage across the tenant's applications, prorates elapsed
time over 720 hours, caps catch-up at 31 days, and charges only whole accrued
cents. The first meter call establishes the timestamp.

A Redis lock coordinates the periodic worker. Accounts are handled in separate
transactions so one failure does not abort the pass. Row locks serialize balance
changes and metering. After accrual: attempt eligible saved-card reload, pause a
negative balance, then send a low-balance warning if active. Reload failures are
suppressed for 24 hours. Empty tenants have no charge. Billing-disabled mode
bypasses the metering and enforcement state machine.

All credits go through one helper. A globally unique provider reference on the
ledger, a precheck, and an IntegrityError savepoint guard make duplicate delivery
a no-op. A top-up clears warning and reload failure markers and unpauses once
the balance reaches zero. Charges are negative ledger amounts; superadmin
adjustments use the same balance mutation paths.

Stripe Checkout produces pending attempts and verified webhooks credit by
PaymentIntent ID. Saved cards can be charged off-session; the direct result and
webhook use the same ledger idempotency key. PayPal orders are captured on the
dashboard return and verified webhook captures converge on the capture ID.
Crypto creates a confirmations.info payment; callbacks and status polls always
re-fetch its authenticated status, then credit by provider payment ID. The
creation response's native amount and expiry remain stored because status
responses do not repeat every creation field. Pending crypto attempts older
than 48 hours expire locally.

Application resolution blocks paused tenants with 402. JWKS remains public;
billing has a dedicated secret-key resolver without enforcement. Dashboard
authorization and CSRF checks remain in force, and every payment lookup is
tenant-scoped before external completion. Webhooks use provider verification
instead of browser authentication.

Email is best effort: low-balance/reload-failure notices respect preferences;
pause notices and top-up receipts are always attempted. Operators configure
provider credentials and webhook URLs as documented in DEPLOYMENT.md.
