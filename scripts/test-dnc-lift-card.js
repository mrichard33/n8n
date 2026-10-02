#!/usr/bin/env node
// node --test scripts/test-dnc-lift-card.js
//
// Runs the two Code nodes of OPS.DNC-LIFT Slack Approval straight out of the
// workflow JSON (what n8n will run), with $input / $env / $() stubbed, and
// pins the 2026-10-02 card changes:
//   - the full phone on the first line (last 4 only from an older LP MCP);
//   - consent history when LP MCP sends rows, otherwise the pre-consent Five9
//     block lines (legacy_block), otherwise "none recorded yet";
//   - the LP manual-clear warning ABOVE the buttons, and the matching line in
//     the approve thread reply.
// A payload from today's LP MCP (none of the new fields) must render as before.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WF = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'workflows', 'OPS.DNC-LIFT-slack-approval.json'), 'utf8'));
const code = (name) => WF.nodes.find((n) => n.name === name).parameters.jsCode;
const SECRET = 'test-secret';

function runNode(name, { input, nodes = {}, env = {} }) {
  const $input = { first: () => ({ json: input }) };
  const $ = (n) => ({ first: () => ({ json: nodes[n] }) });
  // eslint-disable-next-line no-new-func
  const fn = new Function('$input', '$env', '$', `return (function () {${code(name)}\n})();`);
  return fn($input, { DNC_LIFT_WEBHOOK_SECRET: SECRET, ...env }, $);
}

const BASE = {
  request_id: 'dnc-lift-1', ghl_contact_id: 'C1', contact_name: 'Jesus Lobo',
  phone_last4: '0498', source: 'Internet', trigger: 'reentry', reentered_at: '2026-10-02T14:00:00Z',
  blocking_tags: ['Five9 DNC list'], last_consent_events: [], ghl_contact_url: 'https://example.com/c/C1',
};
const card = (body) => runNode('Build Card', { input: { headers: { 'x-dnc-lift-secret': SECRET }, body } })[0].json;
const mainText = (c) => c.blocks[1].text.text;

test('refuses a request without the shared secret', () => {
  assert.deepEqual(runNode('Build Card', { input: { headers: {}, body: BASE } }), []);
});

test('an old payload (no new fields) renders exactly as before', () => {
  const c = card(BASE);
  assert.match(mainText(c), /^\*Jesus Lobo\* · phone ending \*0498\*/);
  assert.match(mainText(c), /\*Recent consent history:\*\n• none recorded yet/);
  assert.equal(c.blocks.filter((b) => b.type === 'section').length, 1, 'no LP warning without the flag');
});

test('full phone on the first line and in the fallback text', () => {
  const c = card({ ...BASE, phone_full: '(561) 598-0498' });
  assert.match(mainText(c), /^\*Jesus Lobo\* · \*\(561\) 598-0498\*/);
  assert.match(c.text, /\(561\) 598-0498/);
});

test('consent rows present → they are shown, legacy lines are not', () => {
  const c = card({ ...BASE, last_consent_events: [{ created_at: '2026-09-29T10:00:00Z', channel: 'phone', change: 'revoked', source: 'ghl_tag', actor: 'system' }],
    legacy_block: { note: 'x', five9_last_dnc_dispo: { name: 'DNC' } } });
  assert.match(mainText(c), /• 2026-09-29 phone revoked — ghl_tag \(system\)/);
  assert.doesNotMatch(mainText(c), /Five9 DNC result/);
});

test('no consent rows + legacy_block → the pre-consent lines, each only when known', () => {
  const c = card({ ...BASE, legacy_block: {
    note: 'Blocked on Five9 DNC before the consent system (pre-2026-09-28)',
    five9_last_dnc_dispo: { name: 'Do Not Call', date: '2026-08-12T15:01:00Z', agent: 'Craig Deer - LF', campaign: 'Data - Warm Leads less than 30' },
    five9_last_call: { name: 'Hung Up', date: '2026-10-02T14:00:05Z', agent: 'Carla Wright - LF', campaign: 'DIAL ASAP' },
    lp_disposition: { label: 'DNC', date: '2026-09-01T20:33:37.877Z' },
  } });
  const t = mainText(c);
  assert.match(t, /• Blocked on Five9 DNC before the consent system \(pre-2026-09-28\)/);
  assert.match(t, /• Five9 DNC result: Do Not Call on Aug 12, 2026 by Craig Deer - LF \(Data - Warm Leads less than 30\)/);
  assert.match(t, /• Last Five9 call: Hung Up on Oct 2, 2026 \(DIAL ASAP\)/);
  assert.match(t, /• LP disposition: DNC \(Sep 1, 2026\)/);
  assert.doesNotMatch(t, /none recorded yet/);

  const partial = mainText(card({ ...BASE, legacy_block: { note: 'n', five9_last_dnc_dispo: null, five9_last_call: { name: 'Hung Up', date: '2026-10-02T14:00:05Z', campaign: null }, lp_disposition: null } }));
  assert.match(partial, /• Last Five9 call: Hung Up on Oct 2, 2026$/m);
  assert.doesNotMatch(partial, /Five9 DNC result|LP disposition/);
});

test('legacy_block with nothing found → one honest line', () => {
  const t = mainText(card({ ...BASE, legacy_block: { note: 'n', five9_last_dnc_dispo: null, five9_last_call: null, lp_disposition: null } }));
  assert.match(t, /• On Five9 DNC before the consent system — no call record found/);
});

test('LP warning sits above the buttons, with the prospect # or the phone', () => {
  const c = card({ ...BASE, phone_full: '(561) 598-0498', lp_manual_clear_required: true, lp_prospect_id: '456171' });
  const i = c.blocks.findIndex((b) => b.type === 'section' && /Lead Perfection is NOT updated automatically/.test(b.text.text));
  const a = c.blocks.findIndex((b) => b.type === 'actions');
  assert.ok(i > 0 && i < a, 'warning before the actions block');
  assert.match(c.blocks[i].text.text, /clear DNC manually in LP — Prospect #456171\./);

  const noId = card({ ...BASE, phone_full: '(561) 598-0498', lp_manual_clear_required: true, lp_prospect_id: null });
  assert.ok(noId.blocks.some((b) => b.type === 'section' && /find the prospect by phone \(561\) 598-0498\./.test(b.text.text)));
});

const click = { decision: 'approve', slack_user_id: 'U1', response_url: 'https://hooks.slack.com/x', channel: 'C9', slack_ts: '1.2', card_blocks: [] };
const compose = (body, c = click) => runNode('Compose Result', { input: { statusCode: 200, body }, nodes: { 'Parse Click': c } })[0].json;
const OK = { ok: true, decision: 'approve', systems: { lp: { status: 'done', errors: [] } } };

test('approve reply carries the LP manual-clear line; keep-blocked and a working clear do not', () => {
  assert.match(compose({ ...OK, lp_manual_clear_required: true, lp_prospect_id: '456171' }).thread_text,
    /:warning: LP still shows DNC — clear it manually in Lead Perfection \(Prospect #456171\)\./);
  assert.match(compose({ ...OK, lp_manual_clear_required: true, lp_prospect_id: null }).thread_text, /find the prospect by the phone on the card above/);
  assert.doesNotMatch(compose({ ...OK, lp_manual_clear_required: false }).thread_text, /LP still shows DNC/);
  assert.doesNotMatch(compose({ ...OK }).thread_text, /LP still shows DNC/, 'an older LP MCP sends no flag');
  assert.doesNotMatch(compose({ ok: true, decision: 'keep_blocked', systems: {}, lp_manual_clear_required: true }, { ...click, decision: 'keep_blocked' }).thread_text, /LP still shows DNC/);
});
