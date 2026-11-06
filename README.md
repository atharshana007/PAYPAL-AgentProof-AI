# AgentProof AI

Agents will soon spend money for us, but nobody can prove who authorized what. AgentProof is the receipt for agent decisions.

## How it works

1. **Mandate:** A user creates and signs a spending mandate with a maximum total, permitted categories and merchants, and an expiry.
2. **Policy gate:** The shopping agent proposes a purchase; the policy gate verifies the mandate signature and checks the purchase before any order is created.
3. **Hash-chained log:** Requests, mandate terms, reasoning, policy decisions, and payment events are recorded in SQLite and linked by hashes so edits can be detected.
4. **Dispute report:** A report gathers the recorded facts for a purchase, reports the chain status, and provides a plain-English summary.

```text
 User
   |
   v
 Mandate --signed--> Shopping Agent
                         |
                    purchase tool
                         v
                   Policy Gate
                    /       \
              BLOCK or      ALLOW
             approval        |
                 |           v
                 |     PayPal Sandbox
                 |           |
                 +-----+-----+
                       v
                Hash-Chained Log
                       |
              Dispute Report + UI
```

## Setup (Windows PowerShell)

Run these commands from the project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set a private `MANDATE_SECRET` before seeding. To use the AI
agent or PayPal Sandbox, also add your own `ANTHROPIC_API_KEY`,
`PAYPAL_CLIENT_ID`, and `PAYPAL_SECRET`. Keep `.env` private; never commit it.

Seed the demo database. The script displays the database path and requires you
to type `RESET` before deleting or recreating it:

```powershell
python seed_demo.py
```

Start the app:

```powershell
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API documentation is available at
<http://127.0.0.1:8000/docs>. By default, SQLite is stored in `agentproof.db`;
set `DB_PATH` in `.env` to select another database file.

## Five-step demo walkthrough

1. **Create the mandate:** Run `python seed_demo.py`, confirm the reset, and
   check the signed $50 accessories mandate in the Mandate panel.
2. **Try the policy gate:** Run the agent with an allowed accessories purchase;
   use Rogue Agent to request an over-budget purchase from a disallowed category.
   The policy gate blocks unauthorized requests before any payment order is made.
3. **Inspect the evidence:** Review the Audit Log panel and select **Verify**.
   Use **Tamper Log** to change an old event and see the chain report the broken
   entry.
4. **Review the dispute report:** Select **Dispute report** on a purchase's log
   event to open its request, mandate, reasoning, decision, payment details, and
   chain status in a printable one-page view.
5. **Complete a sandbox payment:** For an allowed purchase, open its PayPal
   approval link and approve it using a PayPal Sandbox buyer account. Then use
   `POST /paypal/capture/{order_id}` from `/docs` to capture the approved order.
   The capture is recorded only after PayPal returns a successful response.

## PayPal APIs

The app uses the PayPal **Sandbox** at `https://api-m.sandbox.paypal.com`.
It obtains an OAuth access token, creates an order with the Orders API v2
(`POST /v2/checkout/orders`, intent `CAPTURE`), and captures an approved order
with `POST /v2/checkout/orders/{order_id}/capture`. The buyer must approve the
order through its returned approval link before capture can succeed.

## Limitations

- **Sandbox only:** This project targets PayPal Sandbox; it is not configured
  for live payments.
- **Demo-grade HMAC signing:** HMAC-SHA256 protects mandate integrity, but this
  is a hackathon demo, not a production key-management or signing service.
- **Single user:** The local SQLite store has one current mandate and no
  multi-user authentication or isolation.
- **Hardcoded agent:** The shopping agent uses a single tool and simple fixed
  prompts; it is not a production autonomous purchasing system.
Verifies an AI agent's final PayPal checkout against your original request before payment, warns on mismatches, and records an intent receipt linking request, decision, and transaction.


## Run it locally

uvicorn main:app --reload

Open the app:
- Default: http://127.0.0.1:8000
- If port 8000 is already used by another project, run
  `uvicorn main:app --reload --port 8001` and open http://127.0.0.1:8001

API docs: http://127.0.0.1:8000/docs (or :8001/docs on the alternate port)
