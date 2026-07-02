# Stripe Webhook Testing

How to verify `/api/v1/stripe/webhook` locally and on the production VPS.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/stripe/webhook` | Stripe webhook handler (live signature validation) |
| `POST` | `/api/v1/stripe/simulate-webhook` | Admin/KJ-only simulated event for local testing |

Webhook path resolution: nginx `location /api/` strips the prefix, so `/api/v1/stripe/webhook` reaches the FastAPI app at `/v1/stripe/webhook`. The `payments` router is mounted under `/v1/venues/{venue_id}/payments` **and** exposes `/webhook` at the root of that router, but the current production setup relies on the route being reachable. Verify the exact registered route in `/docs` when `DEBUG=true`.

## Required secrets

Set these in the host `.env` for docker-compose:

```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_BASIC=price_...
STRIPE_PRICE_ID_ENTERPRISE=price_...
```

For local dev you can use `STRIPE_TEST_SECRET_KEY` instead of `STRIPE_SECRET_KEY`. `_get_stripe()` prefers `STRIPE_SECRET_KEY` and falls back to `STRIPE_TEST_SECRET_KEY`, then `sk_test_` placeholder.

## Option 1: Local test with Stripe CLI (recommended)

1. [Install Stripe CLI](https://docs.stripe.com/stripe-cli)
2. Login and start a local forwarder:

```bash
stripe login
stripe listen --forward-to http://localhost:8000/api/v1/stripe/webhook
```

`stripe listen` prints a webhook signing secret. Copy it into `.env`:

```bash
STRIPE_WEBHOOK_SECRET=whsec_...
```

3. Trigger a test event:

```bash
stripe trigger payment_intent.succeeded
```

The CLI signs the payload with the local `whsec_` and POSTs it to your FastAPI app.

## Option 2: Local manual test (no Stripe account)

```bash
curl -X POST http://localhost:8000/api/v1/stripe/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "payment_intent.succeeded",
    "data": {
      "object": {
        "id": "pi_test_123",
        "metadata": {"payment_id": "00000000-0000-0000-0000-000000000000"}
      }
    }
  }'
```

Without `STRIPE_WEBHOOK_SECRET` or `Stripe-Signature`, the handler parses raw JSON and updates the matching `Payment` row if found.

## Option 3: Production webhook registration

1. In the Stripe Dashboard add an endpoint:
   - **Endpoint URL:** `https://dancingdragonservices.com/api/v1/stripe/webhook`
   - **Listen to:** `payment_intent.succeeded`, `payment_intent.payment_failed`
2. Copy the endpoint signing secret into the VPS `.env` as `STRIPE_WEBHOOK_SECRET`.
3. Recreate the API container:

```bash
ssh scales@dancingdragonservices.com
cd ~/ScalesInfrastructure
docker compose up -d --no-deps api
```

4. Send a test event from the Stripe Dashboard and check the response:

```bash
# on VPS
docker logs --tail 100 scales-api | grep -i stripe
```

## Verifying signature validation

With `STRIPE_WEBHOOK_SECRET` set, any request missing a valid `Stripe-Signature` returns:

```json
{"detail":"Webhook validation failed: ..."}
```

With HTTP 400.

When the secret is not set, the handler falls back to raw JSON parsing (dev/test only).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| 404 on `/api/v1/stripe/webhook` | Router not mounted under expected path | Check `app/api/router.py` includes `payments.router` and path prefix |
| `Webhook validation failed` | `STRIPE_WEBHOOK_SECRET` mismatch | Compare Stripe dashboard secret with `.env` and rebuild container |
| Payment not updated | `payment_id` missing from metadata or row not found | Verify `Payment` row exists with the UUID in the event metadata |
| `no payment_id in metadata` | Stripe event lacks metadata | Confirm `metadata.payment_id` is sent on every `PaymentIntent.create` |
| Container doesn't see new env | Docker image uses baked env from `.env` at build time | Use `docker compose up -d --no-deps api` (not `docker restart`) |

## Security notes

- Never commit real secrets; keep them in `.env` on the VPS only.
- The simulated webhook endpoint requires an authenticated admin/KJ JWT.
- Always validate `Stripe-Signature` in production; raw JSON fallback is disabled when `STRIPE_WEBHOOK_SECRET` is present.
- Restrict Stripe webhook IPs at the firewall if desired: see Stripe's [webhook IP list](https://docs.stripe.com/ips).
