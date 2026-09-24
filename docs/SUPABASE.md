# Supabase setup

Open **Integrations → Set up Supabase**. Enter your project URL, booking table, reference column, customer identifier and the fields the agent may read. Explain how bookings belong to your business and how a customer proves they may see a booking.

Choose **Save and request setup**. The request is saved for your workspace; reopen the form to update it. Use column names and descriptions only. Do not enter credentials or customer records.

## What happens next

The current release collects requirements. It does not start Supabase OAuth, contact the project, create database permissions or give the agent access. The request stays pending until an operator implements authorization and a restricted booking endpoint. There is no automatic provisioning or operator notification yet.

The operator must verify the ownership and customer verification rules, configure server-side authorization, map approved fields to a read-only lookup and test access boundaries before enabling agent access. The existing booking MCP connector remains separate; saving this form does not change it.

## Installation update

This release adds `supabase_setups`, containing a workspace ID and configuration JSON. Local installations create it at startup when `SOLOAI_INIT_SCHEMA=true`. For installations with automatic schema setup disabled, run the existing idempotent schema initializer with the deployment's database environment before starting the updated application:

```bash
python -c 'from app.main import init_db; init_db()'
```

Use a deployment identity with schema permissions. The runtime account does not need schema permissions after initialization. The SQL Server adapter stores the configuration as `NVARCHAR(MAX)`. All reads and writes use the authenticated workspace ID; clients cannot submit a different tenant ID. Saving a request adds an audit entry without the form contents.
