# Connect booking data from Supabase

SoloAI reads booking details through one restricted Edge Function. It does not need your Supabase service-role key or access to every table.

## Set up the function

The repository includes a small test implementation:

- `integrations/supabase/001_synthetic_bookings.sql` creates fictional bookings with RLS enabled.
- `integrations/supabase/functions/soloai-booking/index.ts` exposes a read-only lookup.
- `integrations/supabase/config.toml` selects the function's dedicated-token authentication.

Use these in a test project first. For a real project, adapt the lookup to your booking schema and ownership rules. The function uses the service-role credential inside Supabase; that credential must never be entered into SoloAI.

Generate a separate random bearer token for this connection. Store its SHA-256 hex digest as the function secret `SOLOAI_BOOKING_TOKEN_SHA256`. The function checks that token itself, so the supplied configuration disables the legacy JWT check. Do not deploy it without the verifier secret.

## Connect in SoloAI

Set `SOLOAI_CONNECTOR_KEY_FILE` to a private Fernet key file on the server. The existing Gmail encryption key is used as a fallback if this setting is absent.

Open **Integrations → Supabase**. Enter the function URL and its dedicated token. The supported URL format is:

```text
https://YOUR_PROJECT_REF.supabase.co/functions/v1/soloai-booking
```

SoloAI encrypts the token before storing it. The model cannot choose a different endpoint or supply the customer identity.

## Verify the customer

A booking reference alone is not proof of ownership. Open the email in Support Inbox and choose **Verify customer for booking lookup**. Confirm the customer's identity through your own process, then enter the customer ID. The confirmation lasts up to an hour for that case.

The function receives both the booking reference and the verified customer ID. A wrong customer must get no booking data. Disconnecting the integration clears these confirmations and prevents an in-flight lookup from being accepted after disconnect.

## What has been checked

The synthetic Supabase project was tested with a matching customer, a different customer and an invalid token. The matching lookup succeeded; the other requests returned no booking or were rejected. This does not validate a customer's production schema or identity-verification process.

Older versions of SoloAI only saved a setup request. Those records do not authorize access. Connect the restricted function explicitly to use the new lookup.
