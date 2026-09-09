# Slack team onboarding — OPS.SLK-A / B / C

Zero-click Slack provisioning for new hires. Slack's API cannot create user
accounts on our plan, so the flow keys off the moment the person joins:

```
OPS.SLK-A  n8n Form ──► team_members row (invited) ──► invite email ──► #ops-alerts 🟢
                                                            │
                                            person clicks the invite, signs up
                                                            ▼
OPS.SLK-B  Slack team_join ──► verify signature ──► match email ──► resolve channels
           ──► [live] invite to role channels · create private rep channel (sales_rep only)
           ──► row active · welcome DM ──► #ops-alerts ✅   ([shadow] = evaluate + post only)

OPS.SLK-C  POST /webhook/team-departure {email} ──► [live] kick from those channels
           · archive rep channel (never delete) ──► row departed ──► #ops-alerts 🟠
```

**Employees are never GHL contacts.** That is why intake is an n8n Form and not
a GHL form, and why nothing here touches lp_leads or GHL.

**Channel/role rules are data, not code.** `slack_role_channels` says which
channel patterns each role gets; `slack_market_slugs` fills in `<market>`. To
change who gets what, change rows. Canvassers are never in `#dispatch` because
no such row exists.

| File | n8n ID | What it is |
|---|---|---|
| `workflows/OPS.SLK-A-team-onboarding-intake.json` | `7PbuOsFtCSrJJmSH` | Form → normalize → upsert `team_members` → invite email (Gmail `updates@reecewindowsmail.com`) → #ops-alerts |
| `workflows/OPS.SLK-B-slack-join-provisioner.json` | `UAJTAHUd6FiYgit6` | Slack `team_join` → HMAC verify → match → resolve → invite / rep channel / activate / DM → #ops-alerts |
| `workflows/OPS.SLK-C-team-departure.json` | `ygqlp5Fea6zc8K5S` | Departure webhook → kick + archive → row departed → #ops-alerts + manual-deactivation reminder |
| `sql/slack_onboarding_schema.sql` | — | `team_members`, `slack_channels`, `slack_role_channels`, `slack_market_slugs` + seed, 3 executions |
| `scripts/lib/slack-onboarding-normalize.js` | — | Form → row normalizer (embedded verbatim in A's `Normalize` node) |
| `scripts/lib/slack-onboarding-resolve.js` | — | `<market>` pattern resolver + rep channel name (embedded verbatim in B's and C's `Resolve Channels`) |
| `scripts/test-slack-onboarding.js` | — | `node --test` — the pure functions, plus guards that the workflow JSON embeds them and ships inactive |

All three workflows **ship inactive** and stay in **shadow mode** until Mark
flips `SLACK_ONBOARDING_MODE=live`. They were created in n8n on 2026-09-09 (ids
above) after the merge of PR #60; later pushes that change these files update
them in place by name via `.github/workflows/deploy-to-n8n.yml`.

## Env vars (Railway → project `n8n` → service `n8n main instance`)

| Var | Value | Used by |
|---|---|---|
| `SLACK_BOT_TOKEN` | Reece Bot `xoxb-…` token | A, B, C (every Slack call is a plain HTTP node with `Authorization: Bearer`; no n8n credential object, so the token stays in env) |
| `SLACK_SIGNING_SECRET` | Slack app → Basic Information → Signing Secret | B (HMAC check; **unset = every event rejected with 401**) |
| `SLACK_INVITE_URL` | shareable, no-expiry invite link | A (invite email) |
| `SLACK_OPS_ALERTS_CHANNEL_ID` | `C…` id of `#ops-alerts` (Reece Bot must be in the channel) | A, B, C |
| `SLACK_ONBOARDING_MODE` | `shadow` (default when unset) or `live` | B, C |
| `SLACK_DEPARTURE_TOKEN` | any long random string | C — required header `x-departure-token`; **unset = every departure call rejected with 401** (added because the webhook is public and kicking people is destructive) |
| `LP_SUPABASE_URL`, `LP_SUPABASE_KEY` | already set on the service | A, B, C — PostgREST reads/writes. The new tables have RLS on with no policies, so **the key must be the service_role key**; with the anon key every Supabase node returns an empty result / 401. |

The n8n worker service carries the same variables; set them on both if a
production execution ever lands on the worker (queue mode).

Verified 2026-09-08 on the live instance with a throwaway workflow: `$env` is
readable in Code nodes and expressions (`N8N_BLOCK_ENV_ACCESS_IN_NODE` is
false), `require('crypto')` is **disallowed** in the Code node, and the Crypto
node's HMAC action matches a locally computed Slack signature byte for byte.
That is why the signature check is a Crypto node and not a Code node.

## Preflight (Mark, before any workflow is activated — the workflows fail gracefully until done)

1. Slack app **Reece Bot** at api.slack.com/apps → OAuth & Permissions → Bot Token Scopes:
   `chat:write`, `chat:write.customize`, `channels:manage`, `groups:write`,
   `channels:read`, `groups:read`, `channels:join`, `users:read`,
   `users:read.email`, `im:write` → Install to workspace → copy the `xoxb-` token.
   Add Reece Bot to `#ops-alerts` (`/invite @Reece Bot`).
2. Slack → Settings & administration → Invitations → shareable invite link, no expiry.
3. Set the env vars above on the n8n Railway service. Leave `SLACK_ONBOARDING_MODE=shadow`.
4. Run `sql/slack_onboarding_schema.sql` in the Supabase dashboard (LP MCP
   instance, project `rcjcgjlqzepicbwhnnjl`) as **3 separate executions** in
   order: tables (+RLS) → seed → index. Execution 3 is `CREATE INDEX
   CONCURRENTLY` and cannot share a run with anything.
5. Load `slack_channels` with the 6 company + 21 market channels once they exist
   (Slack → channel → About → Channel ID). Template at the bottom of the SQL
   file. `SELECT count(*) FROM slack_channels;` → 27.
6. Import / deploy the three workflows. Activate **A** and **B** (B first if you
   are doing step 7 right away). Leave **C** inactive until A + B are live.
7. Slack app → Event Subscriptions → Enable → Request URL
   `https://n8n-main-instance-production-981e.up.railway.app/webhook/slack-events`
   → Subscribe to bot events: `team_join` → Save. Slack sends a `url_verification`
   challenge immediately; **B must already be active** to echo it (the challenge
   is signed, so `SLACK_SIGNING_SECRET` must already be set too).

## Verification (shadow first, then live)

0. `SELECT count(*) FROM slack_channels;` → 27.
1. Submit the form (`/form/team-onboarding`) as Sales Rep / Fort Myers with a
   test email → `SELECT status FROM team_members WHERE email='…'` → `invited`;
   invite email received; `#ops-alerts` shows `🟢 ONBOARDING …`.
2. Join Slack with that email (shadow) → `#ops-alerts` shows
   `[SHADOW] ✅ ONBOARDED · … · sales_rep · FTMYR · 4 channels · would invite:
   #announcements, #general, #dispatch, #sales-fortmyers · would create private
   #sales-fortmyers-<first>-<last> · row left as-is (shadow)`.
3. Repeat as Canvasser → `3 channels`, no `#dispatch`, no rep channel line.
4. Join with an email that has no form row → `🔴 UNKNOWN JOIN · …`.
5. Flip `SLACK_ONBOARDING_MODE=live` (Mark's call), repeat step 2 with a fresh
   test account → rep channel exists, private, topic + purpose set, user is in
   all 4 + the rep channel, welcome DM received, row `active` with
   `slack_user_id` and `rep_channel_id`, `slack_channels` has the `rep` row.
6. Submit the same email twice → `SELECT count(*) FROM team_members WHERE email='…'` → 1.
7. `node --test scripts/test-slack-onboarding.js` → all pass.
8. Departure (after A + B are live and C is activated with `SLACK_DEPARTURE_TOKEN` set):
   ```
   curl -X POST https://n8n-main-instance-production-981e.up.railway.app/webhook/team-departure \
     -H 'Content-Type: application/json' -H 'x-departure-token: <SLACK_DEPARTURE_TOKEN>' \
     -d '{"email":"<test email>"}'
   ```
   → `#ops-alerts` shows `🟠 DEPARTURE · … · removed from N channels · rep
   channel archived · DEACTIVATE SLACK ACCOUNT MANUALLY (Enterprise-only API)`;
   row `departed`. In shadow mode the same call posts a `[SHADOW]` line and
   changes nothing.

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
names the cause (`not_authed` → token, `channel_not_found` → channel id or bot
not in #ops-alerts, `missing_scope` → reinstall the app with the scope).

## How it works, node by node

**A · intake.** Form Trigger (`/form/team-onboarding`, six required fields) →
`Normalize` (label → code maps, lower-cased email, digits-only phone, slug) →
PostgREST `POST team_members?on_conflict=email` with
`Prefer: resolution=merge-duplicates` (so a re-submit updates, never
duplicates, and never touches `slack_user_id` / `rep_channel_id`) → Gmail send
→ `chat.postMessage` → `Check Slack Response`.

**B · provisioner.** Webhook (`/webhook/slack-events`, **Raw Body on**,
responds via node) → `Prepare Signature Input` (raw bytes → `v0:<ts>:<body>`,
5-minute window) → Crypto HMAC-SHA256 with the signing secret →
`Verify & Route` (constant-time compare; builds the challenge reply or a 401)
→ **Respond to Slack** (before any other work — Slack retries after 3 s) →
`team_join` only → lookups (`team_members` by email, `slack_role_channels` by
role, `slack_market_slugs` by market, `slack_channels` by the resolved names)
→ `Plan Provisioning` (ids, missing-channel alerts, DM text, shadow line) →
**Live Mode?** → shadow: post the line and stop. Live: fan out
`conversations.invite` per channel (`already_in_channel` = success) →
`sales_rep`: reuse the `slack_channels` rep row, else `conversations.create`
(private); on `name_taken` scan `conversations.list` (paginated) → setTopic,
setPurpose, invite the rep, upsert the `rep` row → PATCH `team_members`
(`active`, `slack_user_id`, `rep_channel_id`) → welcome DM → summary →
`Check Slack Response`.

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
  constraint on `team_members`, `ROLES` (normalize lib) + the form dropdown.
- `workflows/*.json` on `main` is auto-deployed by `.github/workflows/deploy-to-n8n.yml`
  (changed files only, created inactive, activation never changed). Never
  commit to `main` directly — PR, Mark reviews and merges.
- Slack deactivation is manual on this plan. The 🟠 DEPARTURE line is the reminder.
