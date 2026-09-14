# Slack team onboarding — OPS.SLK-A / B / C / D

Zero-click Slack provisioning for new hires. Slack's API cannot create user
accounts on our plan, so the flow keys off the moment the person joins:

```
OPS.SLK-A  n8n Form ──► team_members row (invited) ──► invite email ──► #ops-alerts 🟢
                                                            │
                                            person clicks the invite, signs up
                                                            ▼
OPS.SLK-B  Slack Trigger ──► match email ──► approval gate ──► resolve channels
           ──► [live] invite to role channels ──► row active · welcome DM ──► #ops-alerts ✅
           (a Slack deactivation on the same trigger fires OPS.SLK-C automatically)

OPS.SLK-C  POST /webhook/team-departure {email} ──► [live] kick from those channels
           ──► row departed ──► #ops-alerts 🟠

OPS.SLK-D  hourly ──► link anyone already in Slack when their row was created
           ──► same channel provisioning ──► #ops-alerts (only when something changed)
```

**Status (2026-09-14): all four workflows are ACTIVE and in LIVE mode**
(`SLACK_ONBOARDING_MODE=live` on both n8n Railway services). The JSON files in
this folder are exports of what is running, credentials included by name, with
`pinData` and editor-only `settings` keys stripped.

> Live and this folder drift the moment anyone edits in the n8n UI, and a push
> to `main` deploys these files over the live version. Export first, edit the
> export, then commit — never edit the file here from memory.

**Employees are never GHL contacts.** That is why intake is an n8n Form and not
a GHL form, and why nothing here touches lp_leads or GHL.

**No per-rep private channels (removed 2026-09-14).** A sales rep lands in
their market's `#sales-<market>` channel and nothing else is created for them.
`team_members.rep_channel_id` and `channel_type = 'rep'` survive in the schema,
unused, because dropping a live column is irreversible and they cost nothing.

**Channel/role rules are data, not code.** `slack_role_channels` says which
channel patterns each role gets; `slack_market_slugs` fills in `<market>`. To
change who gets what, change rows. Canvassers are never in `#dispatch` because
no such row exists.

| File | n8n ID | What it is |
|---|---|---|
| `workflows/OPS.SLK-A-team-onboarding-intake.json` | `7PbuOsFtCSrJJmSH` | Form → normalize → upsert `team_members` → invite email (Gmail `updates@reecewindowsmail.com`) → #ops-alerts |
| `workflows/OPS.SLK-B-slack-join-provisioner.json` | `UAJTAHUd6FiYgit6` | Slack Trigger → match → approval gate → resolve → invite / activate / DM → #ops-alerts. A deactivation calls C. |
| `workflows/OPS.SLK-C-team-departure.json` | `ygqlp5Fea6zc8K5S` | Departure webhook → kick from every channel → row departed → #ops-alerts |
| `workflows/OPS.SLK-D-backfill-slack-ids.json` | `RI0A1VCI2QiWA4DK` | Hourly: link people who were already in Slack, then provision them and fan watchers out |
| `sql/slack_onboarding_schema.sql` | — | `team_members` (+ `watch_scope`, `pro_id`), `slack_channels`, `slack_role_channels`, `slack_market_slugs` + seed, 3 executions — **applied** |
| `scripts/lib/slack-onboarding-normalize.js` | — | Form → row normalizer incl. `pro_id`, `watch_scope`, `needs_approval` (embedded verbatim in A's `Normalize` node) |
| `scripts/lib/slack-onboarding-resolve.js` | — | `<market>` pattern resolver (embedded verbatim in B's and C's `Resolve Channels`) |
| `scripts/test-slack-onboarding.js` | — | `node --test` — the pure functions, the Pro ID rules, the embed guards, and the live wiring (credentials, Slack Trigger, fail-closed departure, no per-rep channels) |

## Auth: n8n credentials, not env vars

Every Slack call is a plain HTTP Request node authenticated with the n8n
credential **Reece Bot** (type `slackApi`, id `1OT2X5rtLCxwNgFI`). Every
Supabase call is a plain HTTP Request node authenticated with **LP Supabase**
(type `supabaseApi`, id `9QVXUFOAdIAIg4WH`, service_role key). B's Slack
Trigger node uses the same Reece Bot credential, which also holds the app's
signing secret, so Slack event signatures are verified by n8n itself.

The bot token and signing secret therefore live only inside those two n8n
credentials. `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` and `LP_SUPABASE_KEY`
are **not** read by these workflows any more (the test suite fails if one of
them creeps back in). To rotate the Slack token: edit the Reece Bot credential
in n8n. Nothing else changes.

## Env vars (Railway → project `n8n` → services `n8n main instance` AND `n8n worker`)

Both services carry the same values (queue mode — an execution may land on the
worker). All of these are set as of 2026-09-09.

| Var | Value | Used by |
|---|---|---|
| `SLACK_INVITE_URL` | shareable, no-expiry invite link | A (invite email) |
| `SLACK_OPS_ALERTS_CHANNEL_ID` | `C…` id of `#ops-alerts` (Reece Bot must be in the channel) | A, B, C |
| `SLACK_ONBOARDING_MODE` | `live` (anything else = shadow: evaluate + post only, no Slack/DB writes) | B, C |
| `SLACK_DEPARTURE_TOKEN` | long random string | C — required header `x-departure-token`; **unset = every departure call rejected with 401** (the webhook is public and kicking people is destructive) |

The Supabase REST URL (`https://rcjcgjlqzepicbwhnnjl.supabase.co/rest/v1/…`)
is written into the nodes; `LP_SUPABASE_URL` is not used.

## Slack app side (done once, by a Slack admin)

1. Slack app **Reece Bot** at api.slack.com/apps → OAuth & Permissions → Bot Token Scopes:
   `chat:write`, `chat:write.customize`, `channels:manage`, `groups:write`,
   `channels:read`, `groups:read`, `channels:join`, `users:read`,
   `users:read.email`, `im:write` → Install to workspace. Paste the `xoxb-`
   token and the Signing Secret into the n8n credential **Reece Bot**.
   Add Reece Bot to `#ops-alerts` (`/invite @Reece Bot`).
2. Slack → Settings & administration → Invitations → shareable invite link, no
   expiry → `SLACK_INVITE_URL`.
3. Slack app → Event Subscriptions → Enable → Request URL = the **Slack
   Trigger node's webhook URL** (open the node in workflow B and copy the
   production URL) → Subscribe to bot events: `team_join` → Save. B must be
   active for Slack to accept the URL.
4. `slack_channels` holds one row per real channel (10 company + 21 market
   channels). Template at the bottom of the SQL file.

## Verification

0. `SELECT count(*) FROM slack_channels;` → 31.
1. Submit the form (`/form/team-onboarding`) as Sales Rep / Fort Myers with a
   test email and Pro ID `4213` → `SELECT status, pro_id, watch_scope FROM
   team_members WHERE email='…'` → `invited`, `4213`, `NULL`; invite email
   received; `#ops-alerts` shows `🟢 ONBOARDING …`.
2. Submit as Sales Rep with the Pro ID left blank → the run fails with
   `Pro ID is required for sales_rep`. Submit as Setter with it blank → it
   succeeds and `pro_id` is `NULL`. Submit with `421` → fails on the length.
3. Join Slack with the test email → the person is in their four role channels
   and **no private channel is created**; welcome DM received; row `active`
   with `slack_user_id`; `#ops-alerts` shows `✅ ONBOARDED · … · sales_rep · FTMYR`.
   If nothing happens on join, check workflow B's executions: no execution at
   all means the Slack Event Subscription is not pointed at the Slack Trigger URL.
4. Repeat as Canvasser → `3 channels`, no `#dispatch`.
5. Join with an email that has no form row → `🔴 UNKNOWN JOIN · …`.
6. Submit the same email twice → `SELECT count(*) FROM team_members WHERE email='…'` → 1.
7. Submit as Sales Manager → row has `watch_scope = 'rep_channels'` and
   `needs_approval` drives the 🟠 APPROVAL NEEDED card in `#ops-alerts`.
8. Once a few canvassers are onboarded, cross-check the Pro ID against the
   roster Lead Perfection already has:
   `SELECT t.email, t.pro_id, c.name FROM team_members t JOIN ci_canvassers c
    ON c.pro_id::text = t.pro_id WHERE t.role = 'canvasser';`
9. `node --test scripts/test-slack-onboarding.js` → all pass.
10. Departure:
    ```
    curl -X POST https://n8n-main-instance-production-981e.up.railway.app/webhook/team-departure \
      -H 'Content-Type: application/json' -H 'x-departure-token: <SLACK_DEPARTURE_TOKEN>' \
      -d '{"email":"<test email>"}'
    ```
    → `#ops-alerts` shows `🟠 DEPARTURE · … · removed from N channels ·
    #announcements, #general left in place … · cleanup complete`; row
    `departed`. Without the header (or with a wrong one) the call gets 401 and
    nothing runs. Deactivating the Slack account itself is still manual —
    Slack has no API for it on this plan.

## What #ops-alerts will show

| Prefix | Meaning | Action |
|---|---|---|
| `🟢 ONBOARDING` | form submitted, invite emailed | none |
| `✅ ONBOARDED` / `[SHADOW] ✅ ONBOARDED` | join processed (or would have been) | none unless 🟠 lines follow |
| `🔴 UNKNOWN JOIN` | someone joined Slack with an email that has no form row | submit the form for them, have them leave and re-join (or add them by hand) |
| `🔴 DEPARTED REJOIN` | a departed person joined again; nothing was provisioned | re-submit the form if intended |
| `🟠 MISSING CHANNEL · name` | `slack_channels` has no row for that name | add the row; re-join or invite by hand |
| `🟠 NO ROLE MAPPING` / `🟠 UNKNOWN MARKET` | data gap in `slack_role_channels` / `slack_market_slugs` | add rows |
| `🟠 INVITE FAILED` / `🟠 KICK FAILED` / `🟠 DM FAILED` | Slack error for one call, the rest went through | error text names the cause (usually a missing scope or the bot not in the channel) |
| `🟠 DEPARTURE` | departure processed | **deactivate the Slack account by hand** (Slack has no API for it on this plan) |
| `🟠 APPROVAL NEEDED` | a manager-level role joined and has not been approved | approve or deny on the card in `#ops-alerts` |
| `🔴 DEACTIVATED` | a Slack account was deactivated; the departure workflow was fired automatically | none, unless 🟠 lines follow |

A **red execution** in n8n (not an alert) means the alert itself could not be
posted: the last node throws when Slack answers `ok:false`, and its message
names the cause (`not_authed` / `invalid_auth` → the Reece Bot credential,
`channel_not_found` → channel id or bot not in #ops-alerts, `missing_scope` →
reinstall the app with the scope).

## How it works, node by node

**A · intake.** Form Trigger (`/form/team-onboarding`: First name, Last name,
Email, Mobile phone, Market and Role required, Pro ID optional on the form) →
`Normalize` (label → code maps, lower-cased email, digits-only phone,
`pro_id`, `watch_scope`, `needs_approval`) → PostgREST
`POST team_members?on_conflict=email` with `Prefer: resolution=merge-duplicates`
(so a re-submit updates, never duplicates, and never touches `slack_user_id`
or `approved_by`) → Gmail send → `chat.postMessage` → `Check Slack Response`.

**Pro ID** is the person's own 4-digit Lead Perfection PRO number, not the
promoter id credited on a lead. It cannot be required on the form itself —
the trigger has no conditional requirement and several roles do not have one —
so `Normalize` enforces it per role and throws a readable error naming the
role. Required for sales reps, canvassers and their managers; `NULL` otherwise.

**B · provisioner.** Slack Trigger (`team_join`, Reece Bot credential; n8n
verifies the signature and answers Slack) → `Route` (real, non-bot user with an
id) → lookups (`team_members` by email, `slack_role_channels` by role,
`slack_market_slugs` by market, `slack_channels` by the resolved names) →
`Plan Provisioning` (ids, missing-channel alerts, DM text, shadow line) →
**Live Mode?** → shadow: post the line and stop. Live: fan out
`conversations.invite` per channel (`already_in_channel` = success) → PATCH
`team_members` (`active`, `slack_user_id`) → welcome DM → summary →
`Check Slack Response`. A manager-level role with no `approved_by` stops at
the approval gate and posts a 🟠 APPROVAL NEEDED card instead. The same trigger
also catches a Slack deactivation and calls OPS.SLK-C for that person. The
original `Slack Events` webhook node (manual HMAC check) is still in the file
but **disabled and disconnected**; the tests keep it that way.

**C · departure.** Webhook (`/webhook/team-departure`) → `Authorize & Parse`
(`x-departure-token` must equal `SLACK_DEPARTURE_TOKEN`; fail-closed) →
Respond → lookups (same as B) → `Plan Departure` → **Live Mode?** → shadow:
post and stop. Live: `conversations.kick` per channel (`not_in_channel` = done;
`#announcements` and `#general` are skipped because Slack refuses to remove
anyone from a default channel) → PATCH `departed` → summary. A row with no
`slack_user_id` (never joined) is still marked `departed` so B refuses a later
stray join.

**D · backfill.** Hourly and on demand. Finds non-departed people who have no
`slack_user_id` (or who are watchers), looks each up by email, writes the id,
then runs the same channel provisioning plus the watcher fan-out:
`watch_scope = 'all'` means every channel in the registry, `'rep_channels'`
means every `#sales-<market>`. Shadow mode still links the id but sends no
invites. It posts to `#ops-alerts` only when something actually changed, and
repeats identical text at most once a day.

## Editing rules

- The `Normalize` and `Resolve Channels` Code nodes are verbatim copies of the
  two files under `scripts/lib/`. Edit the lib file, paste the body (everything
  above `module.exports`) back into the node, run the tests — they fail if the
  copies drift.
- Add a market: one row in `slack_market_slugs`, the three market channels in
  `slack_channels`, and the label in `MARKETS` (normalize lib) + the form
  dropdown. Add a role: rows in `slack_role_channels`, the `role` CHECK
  constraint on `team_members`, `ROLES` (normalize lib) + the form dropdown.
  Decide at the same time whether it belongs in `PRO_ID_ROLES`, `NEEDS_APPROVAL`
  or the watcher lists in the normalize lib.
- Editing live in the n8n UI is fine, but export the workflow afterwards and
  commit it here (strip `pinData`), otherwise the next `main` push that touches
  the file deploys the old version over your edit.
- `workflows/*.json` on `main` is auto-deployed by `.github/workflows/deploy-to-n8n.yml`
  (changed files only, updates by name, activation never changed). Never
  commit to `main` directly — PR, Mark reviews and merges.
- Never commit `pinData`: pinned form submissions carry real names and phones.
- Slack deactivation is manual on this plan. The 🟠 DEPARTURE line is the reminder.
