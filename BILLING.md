# Building Brain billing pilot

Disabled by default. The current backend is a single-admin, single-workspace deployment, not a tenant-isolated SaaS. Do not enable public registration or sell shared hosted access yet.

Use the Reboot Syndicate Stripe account only if the legal entity and account configuration permit it. Create dedicated Building Brain products and recurring USD prices in Stripe test mode first:

| Plan | Monthly | Annual |
|---|---:|---:|
| Starter | $99 | $990 |
| Professional | $299 | $2990 |
| Enterprise | $799 | $7990 |

These pilot prices supersede the illustrative README pricing for this branch only. No feature or seat limits are enforced yet. Create a separate portal configuration restricted to Building Brain prices. Configure the variables in .env.example locally; never commit credentials. Use a restricted API key where possible. Set BILLING_PUBLIC_URL to the deployed HTTPS origin. After signing in, open /billing. Enable BILLING_PILOT_ENABLED only in a private test deployment.

Status is retrieved from Stripe directly, not inferred from the checkout redirect. Signed test-mode webhooks are accepted at /api/billing/webhook, filtered by workspace customer, and deduplicated by event ID. They record receipt only; status is still read directly from Stripe. Live keys are rejected by the pilot. No trial, entitlement enforcement, or public signup is implemented yet. Before live use: implement tenant isolation, authenticated organization membership, webhook-driven subscription reconciliation, durable checkout reconciliation, entitlement enforcement, CSRF protection review, billing lifecycle tests, and deployment/security review. Test successful and failed checkout, duplicate requests, portal switching and cancellation. No Stripe products have been provisioned by this code.
