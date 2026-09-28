# OPS.DNC-LIFT · Slack Approval

n8n workflow `Gdqd1GZJDag0qCUu`, file `OPS.DNC-LIFT-slack-approval.json`. Part of Consent Model v1
(LP-MCP, 2026-09-28). **Created inactive.** Do not activate until the setup below is done and Mark
has run one end-to-end test on a test contact.

## What it does

1. **Review card.** LP MCP (`request_dnc_lift_review`) posts a contact summary to the
   `dnc-lift-review` webhook. The workflow checks the `X-DNC-Lift-Secret` header and posts a card to
   `#dnc-lift-approval`: name, phone last 4, source, why they are blocked, recent consent history,
   and ✅ Approve Lift / ⛔ Keep Blocked. If the lead texted STOP, the card says:
   *"This lead texted STOP. Approving restores calls only. Texts stay off until they text START or
   submit a new form with SMS consent."*
2. **Click.** Slack sends the click to LP MCP (`/webhook/slack/interactions`), which checks Slack's
   signature and relays `dnc_lift_*` clicks **only** to this workflow's `dnc-lift-click` webhook —
   never to OPS.SLK-E, which would read them as team-member approvals. The workflow refuses a click
   without the `X-LPMCP-Forward-Auth` header.
3. It posts the decision to LP MCP `/slack/dnc-lift/decision`, replaces the card (buttons gone,
   "Approved by @user at time" or "Kept blocked by @user"), and replies in the thread with
   GHL / LP / Five9 done or failed. Any failure @-mentions Mark.

OPS.SLK-E is not changed.

## Setup (in this order)

| Where | Setting | Value |
|---|---|---|
| n8n env | `DNC_LIFT_WEBHOOK_SECRET` | long random string — the same value as LP MCP's |
| n8n env | `SLACK_INTERACTIONS_FORWARD_AUTH` | the same value as LP MCP's `SLACK_INTERACTIONS_FORWARD_AUTH` |
| n8n env (optional) | `SLACK_DNC_LIFT_CHANNEL_ID` | the channel id of `#dnc-lift-approval` |
| n8n env (optional) | `DNC_LIFT_ESCALATE_SLACK_ID` | who to @-mention on failure (default Mark, `U0BU7TZPY82`) |
| LP MCP env | `DNC_LIFT_WEBHOOK_SECRET` | same as above |
| LP MCP env | `N8N_DNC_LIFT_REVIEW_WEBHOOK` | this workflow's `dnc-lift-review` production URL |
| LP MCP env | `SLACK_DNC_LIFT_FORWARD_URL` | this workflow's `dnc-lift-click` production URL |
| LP MCP env | `SLACK_INTERACTIONS_FORWARD_AUTH` | must be set (it is the header this workflow checks) |
| Slack | `#dnc-lift-approval` | the workflow tries to create it on the first card (needs the bot's `channels:manage` scope); if that is not allowed, create it by hand and `/invite @Reece Bot` |

## Test

1. Add tag `dnc-lift:request` to a test contact that has `dnc`. A card should appear within a minute.
2. Click Approve on it → the card updates, the thread lists GHL / LP / Five9.
3. Repeat with a test contact carrying `dnc-sms` → the card shows the STOP warning, SMS stays off.
4. Click Keep Blocked on a third → `dnc-lift:reviewed-blocked` tag, nothing lifted.
