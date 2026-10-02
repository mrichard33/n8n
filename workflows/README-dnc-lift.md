# OPS.DNC-LIFT · Slack Approval

n8n workflow `Gdqd1GZJDag0qCUu`, file `OPS.DNC-LIFT-slack-approval.json`. Part of Consent Model v1
(LP-MCP, 2026-09-28). **Active since 2026-09-28** (Mark activated it and put the review webhook
behind the "DNC Lift Webhook Secret" header-auth credential).

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

## ActiveProspect re-entries (2026-09-28)

A card is asked for three ways: the `dnc-lift:request` tag, E.0's `reentry` event (first-party
consent only), and **ActiveProspect**. I.AP (`YOozjkCkeNEe4s3a`, `I.AP-activeprospect-intake.json`)
matches each lead to GHL by phone. When the phone matches an existing contact, the node
*Report DNC Re-entry (LP-MCP)* posts `{contactId, vendor, lead_id}` to LP MCP
`/webhook/ap/dnc-reentry` (header `X-DNC-Lift-Secret`). LP MCP checks its own records and queues a
review only when the contact is blocked; the card then reads *"Came back through ActiveProspect
(vendor)"*. The call runs beside *Add Intake Note*, never errors, and cannot delay the reply to
ActiveProspect. It only asks — nothing is lifted without an Approve click.

ActiveProspect runs its own DNC gate before delivery, so a number on its suppression list never
reaches I.AP and no card can appear for it.

## What the card shows (2026-10-02)

- **Full phone** (`phone_full`) on the first line. An older LP MCP sends only `phone_last4`, and the
  card falls back to "phone ending ####".
- **History.** The consent record when it has rows. Otherwise, for a block older than the consent
  system (Five9 DNC list), LP MCP sends `legacy_block`: the last Five9 DNC result, the last Five9
  call and the LP disposition. Each line appears only when known. LP MCP then seeds one
  `five9_legacy` consent row, so the next card for that contact has real history.
- **LP warning.** LP's DNC clear does not work yet, so LP MCP sends `lp_manual_clear_required`
  (until its `LP_DNC_CLEAR_WORKING=true`). The card then says *"Lead Perfection is NOT updated
  automatically … Prospect #…"* above the buttons, and the approve thread reply adds *"LP still
  shows DNC — clear it manually"*.

`node --test scripts/test-dnc-lift-card.js` runs both Code nodes from this file.

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
