# Slack team onboarding — OPS.SLK-A / B / C

Zero-click Slack provisioning for new hires. Slack's API cannot create user
accounts on our plan, so the flow keys off the moment the person joins:

```
OPS.SLK-A  n8n Form ──► team_members row (invited) ──► invite email ──► #ops-alerts 🟢
                                                            │
                                            person clicks the invite, signs up
                                                            ▼
OPS.SLK-B  Slack Trigger (team_join) ──► match email ──► resolve channels
           ──► [live] invite to role channels · create private rep channel (sales_rep only)
           ──► row active · welcome DM ──► #ops-alerts ✅   ([shadow] = evaluate + post only)

OPS.SLK-C  POST /webhook/team-departure {email} ──► [live] kick from those channels
           · archive rep channel (never delete) ──► row departed ──► #ops-alerts 🟠
```

**Status (2026-09-09): all three workflows are ACTIVE and in LIVE mode**
(`SLACK_ONBOARDING_MODE=live` on both n8n Railway services). The JSON files in
this folder mirror what is running in n8n, credentials included by name, so the
auto-deploy on the next `main` push is a no-op until someone changes them.

**Employees are never GHL contacts.** That is why intake is an n8n Form and not
a GHL form, and why nothing here touches lp_leads or GHL.

**Channel/role rules are data, not code.** `slack_role_channels` says which
channel patterns each role gets; `slack_market_slugs` fills in `<market>`. To
change who gets what, change rows. Canvassers are never in `#dispatch` because
no such row exists.

| File | n8n ID | What it is |
|---|---|---|
| `workflows/OPS.SLK-A-team-onboarding-intake.json` | `7PbuOsFtCSrJJmSH` | Form → normalize → upsert `team_members` → invite email (Gmail `updates@reecewindowsmail.com`) → #ops-alerts |
| `workflows/OPS.SLK-B-slack-join-provisioner.json` | `UAJTAHUd6FiYgit6` | Slack Trigger `team_join` → match → resolve → invite / rep channel / activate / DM → #ops-alerts |
| `workflows/OPS.SLK-C-team-departure.json` | `ygqlp5Fea6zc8K5S` | Departure webhook → kick + archive → row departed → #ops-alerts + manual-deactivation reminder |
| `sql/slack_onboarding_schema.sql` | — | `team_members` (+ `watch_scope`), `slack_channels`, `slack_role_channels`, `slack_market_slugs` + seed, 3 executions — **applied** |
| `scripts/lib/slack-onboarding-normalize.js` | — | Form → row normalizer incl. `watch_scope` (embedded verbatim in A's `Normalize` node) |
| `scripts/lib/slack-onboarding-resolve.js` | — | `<market>` pattern resolver + rep channel name (embedded verbatim in B's and C's `Resolve Channels`) |
| `scripts/test-slack-onboarding.js` | — | `node --test` — the pure functions, the embed guards, and the live wiring (credentials, Slack Trigger, fail-closed departure) |

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
4. `slack_channels` holds one row per real channel (6 company + 21 market
   channels + any `rep` rows B creates). Template at the bottom of the SQL file.

## Verification

0. `SELECT count(*) FROM slack_channels;` → at least 27.
1. Submit the form (`/form/team-onboarding`) as Sales Rep / Fort Myers with a
   test email → `SELECT status, watch_scope FROM team_members WHERE email='…'`
   → `invited`, `NULL`; invite email received; `#ops-alerts` shows `🟢 ONBOARDING …`.
2. Join Slack with that email → rep channel exists, private, topic + purpose
   set, user is in all 4 role channels + the rep channel, welcome DM received,
   row `active` with `slack_user_id` and `rep_channel_id`, `slack_channels`
   has the `rep` row, `#ops-alerts` shows `✅ ONBOARDED · … · sales_rep · FTMYR`.
   If nothing happens on join, check workflow B's executions: no execution at
   all means the Slack Event Subscription is not pointed at the Slack Trigger URL.
3. Repeat as Canvasser → `3 channels`, no `#dispatch`, no rep channel line.
4. Join with an email that has no form row → `🔴 UNKNOWN JOIN · …`.
5. Submit the same email twice → `SELECT count(*) FROM team_members WHERE email='…'` → 1.
6. Submit as Sales Manager → row has `watch_scope = 'rep_channels'`.
7. `node --test scripts/test-slack-onboarding.js` → all pass.
8. Departure:
   ```
   curl -X POST https://n8n-main-instance-production-981e.up.railway.app/webhook/team-departure \
     -H 'Content-Type: application/json' -H 'x-departure-token: <SLACK_DEPARTURE_TOKEN>' \
     -d '{"email":"<test email>"}'
   ```
   → `#ops-alerts` shows `🟠 DEPARTURE · … · removed from N channels · rep
   channel archived · DEACTIVATE SLACK ACCOUNT MANUALLY (Enterprise-only API)`;
   row `departed`. Without the header (or with a wrong one) the call gets 401
   and nothing runs.

## What #ops-alerts will show

| Prefix | Meaning | Action |
|---|---|---|
| `🟢 ONBOARDING` | form submitted, invite emailed | none |
| `✅ ONBOARDED` / `[SHADOW] ✅ ONBOARDED` | join processed (or would have been) | none unless 🟠 lines follow |
| `🔴 UNKNOWN JOIN` | someone joined Slack with an email that has no form row | submit the form for them, have them leave and re-join (or add them by hand) |
| `🔴 DEPARTED REJOIN` | a departed person joined again; nothing was provisioned | re-submit the form if intended |
| `🟠 MISSING CHANNEL · name` | `slack_channels` has no row for that name | add the row; re-join or invite by hand |
| `🟠 NO ROLE MAPPING` / `🟠 UNKNOWN MARKET` | data gap in `slack_role_channels` / `slack_market_slugs` | add rows |
| `🟠 REP CHANNEL …` | create failed, or name_taken and the bot cannot see the existing private channel | add Reece Bot to that channel and re-run, or fix the error named |
| `🟠 INVITE FAILED` / `🟠 KICK FAILED` / `🟠 DM FAILED` | Slack error for one call, the rest went through | error text names the cause (usually a missing scope or the bot not in the channel) |
| `🟠 DEPARTURE` | departure processed | **deactivate the Slack account by hand** (Enterprise-only API) |

A **red execution** in n8n (not an alert) means the alert itself could not be
posted: the last node throws when Slack answers `ok:false`, and its message
names the cause (`not_authed` / `invalid_auth` → the Reece Bot credential,
`channel_not_found` → channel id or bot not in #ops-alerts, `missing_scope` →
reinstall the app with the scope).

## How it works, node by node

**A · intake.** Form Trigger (`/form/team-onboarding`, six required fields:
First name, Last name, Email, Mobile phone, Market, Role) → `Normalize` (label
→ code maps, lower-cased email, digits-only phone, slug, `watch_scope`) →
PostgREST `POST team_members?on_conflict=email` with
`Prefer: resolution=merge-duplicates` (so a re-submit updates, never
duplicates, and never touches `slack_user_id` / `rep_channel_id`) → Gmail send
→ `chat.postMessage` → `Check Slack Response`.

**B · provisioner.** Slack Trigger (`team_join`, Reece Bot credential; n8n
verifies the signature and answers Slack) → `Route` (real, non-bot user with an
id) → lookups (`team_members` by email, `slack_role_channels` by role,
`slack_market_slugs` by market, `slack_channels` by the resolved names) →
`Plan Provisioning` (ids, missing-channel alerts, DM text, shadow line) →
**Live Mode?** → shadow: post the line and stop. Live: fan out
`conversations.invite` per channel (`already_in_channel` = success) →
`sales_rep`: reuse the `slack_channels` rep row, else `conversations.create`
(private); on `name_taken` scan `conversations.list` (paginated) → setTopic,
setPurpose, invite the rep, upsert the `rep` row → PATCH `team_members`
(`active`, `slack_user_id`, `rep_channel_id`) → welcome DM → summary →
`Check Slack Response`. The original `Slack Events` webhook node (manual HMAC
check) is still in the file but **disabled and disconnected**; the tests keep
it that way.

**C · departure.** Webhook (`/webhook/team-departure`) → `Authorize & Parse`
(`x-departure-token` must equal `SLACK_DEPARTURE_TOKEN`; fail-closed) →
Respond → lookups (same as B) → `Plan Departure` (rep channel id from the row,
else the registry) → **Live Mode?** → shadow: post and stop. Live:
`conversations.kick` per channel (`not_in_channel` = done) →
`conversations.archive` the rep channel (`already_archived` = done; **never
delete**) → PATCH `departed` → summary. A row with no `slack_user_id` (never
joined) is still marked `departed` so B refuses a later stray join.

## Editing rules

- The `Normalize` and `Resolve Channels` Code nodes are verbatim copies of the
  two files under `scripts/lib/`. Edit the lib file, paste the body (everything
  above `module.exports`) back into the node, run the tests — they fail if the
  copies drift.
- Add a market: one row in `slack_market_slugs`, the three market channels in
  `slack_channels`, and the label in `MARKETS` (normalize lib) + the form
  dropdown. Add a role: rows in `slack_role_channels`, the `role` CHECK
  constraint on `team_members`, `ROLES` (normalize lib; add it to `LEADS` if
  it should see the rep channels) + the form dropdown.
- Editing live in the n8n UI is fine, but export the workflow afterwards and
  commit it here (strip `pinData`), otherwise the next `main` push that touches
  the file deploys the old version over your edit.
- `workflows/*.json` on `main` is auto-deployed by `.github/workflows/deploy-to-n8n.yml`
  (changed files only, updates by name, activation never changed). Never
  commit to `main` directly — PR, Mark reviews and merges.
- Never commit `pinData`: pinned form submissions carry real names and phones.
- Slack deactivation is manual on this plan. The 🟠 DEPARTURE line is the reminder.
