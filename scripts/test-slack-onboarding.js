#!/usr/bin/env node
// node --test scripts/test-slack-onboarding.js
//
// Covers the two pure functions the Slack onboarding workflows depend on, and
// guards that the workflow JSON files embed those exact functions — the n8n
// Code nodes cannot require() a file, so the source is copied into the node.
// If this test fails on "embeds", re-copy the lib file into the Code node.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { normalize, slugify, MARKETS, ROLES } = require('./lib/slack-onboarding-normalize');
const { resolveChannels, repChannelName } = require('./lib/slack-onboarding-resolve');

const ROOT = path.join(__dirname, '..');
const WF = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'workflows', f), 'utf8'));

// The seed rows from sql/slack_onboarding_schema.sql, so the resolve tests
// exercise the real patterns rather than invented ones.
const ROLE_PATTERNS = {
  sales_rep: ['announcements', 'general', 'dispatch', 'sales-<market>'],
  canvasser: ['announcements', 'general', 'canvass-<market>'],
  sales_manager: ['announcements', 'general', 'dispatch', 'sales-<market>', 'service-<market>'],
  canvass_manager: ['announcements', 'general', 'canvass-<market>'],
  service_lead: ['announcements', 'general', 'service-<market>'],
  dispatch: ['announcements', 'general', 'dispatch', 'contact-center'],
  contact_center: ['announcements', 'general', 'contact-center'],
  leadership: ['announcements', 'general', 'leadership']
};

function form(overrides = {}) {
  return {
    'First name': 'Jane',
    'Last name': 'Smith',
    'Company email': 'Jane.Smith@ReeceWindows.com',
    'Mobile phone': '(239) 555-0100',
    'Market': 'Fort Myers',
    'Role': 'Sales Rep',
    submittedAt: '2026-09-08T12:00:00.000Z',
    formMode: 'production',
    ...overrides
  };
}

test('normalize: market labels map to codes', () => {
  assert.equal(normalize(form({ Market: 'Fort Lauderdale' })).market_code, 'FTLAU');
  assert.equal(normalize(form({ Market: 'St. Petersburg' })).market_code, 'STPET');
  assert.equal(normalize(form({ Market: 'St Petersburg' })).market_code, 'STPET');
  assert.equal(normalize(form({ Market: 'Fort Myers' })).market_code, 'FTMYR');
  assert.equal(normalize(form({ Market: 'Company-wide' })).market_code, null);
});

test('normalize: unknown market or role throws', () => {
  assert.throws(() => normalize(form({ Market: 'Tampa' })), /Unknown market: Tampa/);
  assert.throws(() => normalize(form({ Role: 'CEO' })), /Unknown role: CEO/);
});

test('normalize: every form dropdown option is a known key', () => {
  const marketOptions = ['Jacksonville', 'St. Petersburg', 'Sarasota', 'Lakeland', 'Fort Lauderdale', 'Orlando', 'Fort Myers', 'Company-wide'];
  const roleOptions = ['Sales Rep', 'Canvasser', 'Sales Manager', 'Canvass Manager', 'Service Lead', 'Dispatch', 'Contact Center Agent', 'Leadership'];
  for (const m of marketOptions) assert.ok(m.toLowerCase() in MARKETS, m);
  for (const r of roleOptions) assert.ok(r.toLowerCase() in ROLES, r);
  // ...and the workflow's dropdowns match these lists exactly.
  const wf = WF('OPS.SLK-A-team-onboarding-intake.json');
  const trigger = wf.nodes.find((n) => n.type === 'n8n-nodes-base.formTrigger');
  const field = (label) => trigger.parameters.formFields.values.find((f) => f.fieldLabel === label);
  assert.deepEqual(field('Market').fieldOptions.values.map((v) => v.option), marketOptions);
  assert.deepEqual(field('Role').fieldOptions.values.map((v) => v.option), roleOptions);
});

test('normalize: email lowercased, phone digits only, roles mapped', () => {
  const out = normalize(form());
  assert.equal(out.email, 'jane.smith@reecewindows.com');
  assert.equal(out.phone, '2395550100');
  assert.equal(out.role, 'sales_rep');
  assert.equal(normalize(form({ Role: 'Contact Center Agent' })).role, 'contact_center');
  assert.equal(normalize(form({ Role: 'canvass manager' })).role, 'canvass_manager');
});

test('normalize: slug strips accents and punctuation', () => {
  const out = normalize(form({ 'First name': 'José', 'Last name': "O'Brien" }));
  assert.equal(out.slug, 'jose-o-brien');
  assert.equal(slugify('  Mary-Ann   van der Berg '), 'mary-ann-van-der-berg');
  assert.equal(slugify('Zoë'), 'zoe');
});

test('normalize: trims names, rejects blanks and bad email', () => {
  const out = normalize(form({ 'First name': '  Jane ', 'Last name': ' Smith  ' }));
  assert.equal(out.first_name, 'Jane');
  assert.equal(out.last_name, 'Smith');
  assert.throws(() => normalize(form({ 'First name': '  ' })), /required/);
  assert.throws(() => normalize(form({ 'Company email': 'not-an-email' })), /Invalid company email/);
});

test('resolve: sales_rep + fortmyers', () => {
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_rep, 'fortmyers'),
    ['announcements', 'general', 'dispatch', 'sales-fortmyers']);
});

test('resolve: canvasser + fortmyers never includes dispatch', () => {
  const out = resolveChannels(ROLE_PATTERNS.canvasser, 'fortmyers');
  assert.deepEqual(out, ['announcements', 'general', 'canvass-fortmyers']);
  assert.ok(!out.includes('dispatch'));
  assert.ok(!resolveChannels(ROLE_PATTERNS.canvass_manager, 'orlando').includes('dispatch'));
});

test('resolve: leadership + null market skips market patterns without throwing', () => {
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.leadership, null),
    ['announcements', 'general', 'leadership']);
  // A market-scoped role with no market gets only the company channels.
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_rep, ''),
    ['announcements', 'general', 'dispatch']);
});

test('resolve: dedupes, ignores blank patterns, sales_manager gets both market channels', () => {
  assert.deepEqual(resolveChannels(['general', 'general', '', null], 'orlando'), ['general']);
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_manager, 'orlando'),
    ['announcements', 'general', 'dispatch', 'sales-orlando', 'service-orlando']);
});

test('repChannelName', () => {
  assert.equal(repChannelName('fortmyers', 'jane-smith'), 'sales-fortmyers-jane-smith');
  assert.ok(repChannelName('fortlauderdale', 'a'.repeat(120)).length <= 80);
});

// --- Embedding guards --------------------------------------------------------

function libBody(file) {
  const src = fs.readFileSync(path.join(__dirname, 'lib', file), 'utf8');
  // From the first top-level statement to the module.exports LINE (the header
  // comment also mentions module.exports, so anchor on line start, not indexOf).
  const cut = src.search(/^module\.exports/m);
  const start = src.search(/^(const|function) /m);
  assert.ok(cut > 0 && start >= 0 && start < cut, `${file}: cannot locate the body to embed`);
  const body = src.slice(start, cut).trim();
  // Guard against a vacuous pass: an empty body is "included" in anything.
  assert.ok(body.length > 500 && /^function |^const /m.test(body), `${file}: extracted body is too small to be real`);
  return body;
}

function codeNode(wf, name) {
  const node = wf.nodes.find((n) => n.name === name && n.type === 'n8n-nodes-base.code');
  assert.ok(node, `${wf.name} has no Code node named "${name}"`);
  return node.parameters.jsCode;
}

test('workflow A embeds the normalize lib verbatim', () => {
  const wf = WF('OPS.SLK-A-team-onboarding-intake.json');
  assert.ok(codeNode(wf, 'Normalize').includes(libBody('slack-onboarding-normalize.js')));
});

test('workflows B and C embed the resolve lib verbatim', () => {
  const body = libBody('slack-onboarding-resolve.js');
  assert.ok(codeNode(WF('OPS.SLK-B-slack-join-provisioner.json'), 'Resolve Channels').includes(body));
  assert.ok(codeNode(WF('OPS.SLK-C-team-departure.json'), 'Resolve Channels').includes(body));
});

test('workflows ship inactive, Slack auth comes from env, no credential objects on Slack calls', () => {
  for (const f of ['OPS.SLK-A-team-onboarding-intake.json', 'OPS.SLK-B-slack-join-provisioner.json', 'OPS.SLK-C-team-departure.json']) {
    const wf = WF(f);
    assert.equal(wf.active, false, `${f} must ship inactive`);
    const slackCalls = wf.nodes.filter((n) => n.type === 'n8n-nodes-base.httpRequest' && String(n.parameters.url).includes('slack.com/api/'));
    assert.ok(slackCalls.length > 0, `${f} has Slack calls`);
    for (const n of slackCalls) {
      assert.equal(n.credentials, undefined, `${n.name}: Slack token must come from $env, not a credential`);
      const auth = n.parameters.headerParameters.parameters.find((h) => h.name === 'Authorization');
      assert.ok(auth && auth.value.includes('$env.SLACK_BOT_TOKEN'), `${n.name}: Authorization header must use SLACK_BOT_TOKEN`);
    }
    // Every node name referenced by a connection exists.
    const names = new Set(wf.nodes.map((n) => n.name));
    for (const [from, outs] of Object.entries(wf.connections)) {
      assert.ok(names.has(from), `${f}: connection from unknown node ${from}`);
      for (const branch of outs.main) for (const c of branch || []) assert.ok(names.has(c.node), `${f}: connection to unknown node ${c.node}`);
    }
  }
});

test('workflow B responds to Slack before doing any Slack or Supabase work', () => {
  const wf = WF('OPS.SLK-B-slack-join-provisioner.json');
  const hook = wf.nodes.find((n) => n.type === 'n8n-nodes-base.webhook');
  assert.equal(hook.parameters.responseMode, 'responseNode');
  assert.equal(hook.parameters.options.rawBody, true, 'raw body is required for the HMAC');
  // Walk from the webhook; the Respond node must be reached before any HTTP node.
  const seen = new Set();
  let frontier = [hook.name];
  let responded = false;
  while (frontier.length) {
    const next = [];
    for (const name of frontier) {
      if (seen.has(name)) continue;
      seen.add(name);
      const node = wf.nodes.find((n) => n.name === name);
      if (node.type === 'n8n-nodes-base.respondToWebhook') responded = true;
      if (node.type === 'n8n-nodes-base.httpRequest') assert.ok(responded, `${name} runs before Slack was answered`);
      for (const branch of (wf.connections[name] || { main: [] }).main) for (const c of branch || []) next.push(c.node);
    }
    frontier = next;
  }
  assert.ok(responded);
});
