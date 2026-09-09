#!/usr/bin/env node
// node --test scripts/test-slack-onboarding.js
//
// Covers the two pure functions the Slack onboarding workflows depend on, and
// guards that the workflow JSON files embed those exact functions — the n8n
// Code nodes cannot require() a file, so the source is copied into the node.
// If this test fails on "embeds", re-copy the lib file into the Code node.
//
// It also pins the live wiring (2026-09-09): Slack calls authenticate with the
// n8n credential "Reece Bot" (slackApi), Supabase calls with "LP Supabase"
// (supabaseApi), and B is triggered by the Slack Trigger node on team_join.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { normalize, slugify, MARKETS, ROLES, LEADS, WATCH_ALL } = require('./lib/slack-onboarding-normalize');
const { resolveChannels, repChannelName } = require('./lib/slack-onboarding-resolve');

const ROOT = path.join(__dirname, '..');
const WF = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'workflows', f), 'utf8'));
const FILES = {
  A: 'OPS.SLK-A-team-onboarding-intake.json',
  B: 'OPS.SLK-B-slack-join-provisioner.json',
  C: 'OPS.SLK-C-team-departure.json'
};

// The n8n credentials the live workflows use. Ids are what the n8n instance
// assigned; the names are what you see in the credential picker.
const SLACK_CRED = { id: '1OT2X5rtLCxwNgFI', name: 'Reece Bot' };
const SUPABASE_CRED = { id: '9QVXUFOAdIAIg4WH', name: 'LP Supabase' };
const SUPABASE_REST = 'https://rcjcgjlqzepicbwhnnjl.supabase.co/rest/v1/';

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
    'Email': 'Jane.Smith@ReeceWindows.com',
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
  const wf = WF(FILES.A);
  const trigger = wf.nodes.find((n) => n.type === 'n8n-nodes-base.formTrigger');
  const field = (label) => trigger.parameters.formFields.values.find((f) => f.fieldLabel === label);
  assert.deepEqual(field('Market').fieldOptions.values.map((v) => v.option), marketOptions);
  assert.deepEqual(field('Role').fieldOptions.values.map((v) => v.option), roleOptions);
  // The form labels normalize() reads must exist on the form.
  for (const label of ['First name', 'Last name', 'Email', 'Mobile phone', 'Market', 'Role']) {
    assert.ok(field(label), `form is missing the "${label}" field`);
    assert.equal(field(label).requiredField, true, `"${label}" must be required`);
  }
});

test('normalize: email lowercased, phone digits only, roles mapped', () => {
  const out = normalize(form());
  assert.equal(out.email, 'jane.smith@reecewindows.com');
  assert.equal(out.phone, '2395550100');
  assert.equal(out.role, 'sales_rep');
  assert.equal(normalize(form({ Role: 'Contact Center Agent' })).role, 'contact_center');
  assert.equal(normalize(form({ Role: 'canvass manager' })).role, 'canvass_manager');
});

test('normalize: watch_scope is all for WATCH_ALL, rep_channels for lead roles, else null', () => {
  assert.ok(WATCH_ALL.length > 0);
  assert.equal(normalize(form({ Email: WATCH_ALL[0].toUpperCase() })).watch_scope, 'all');
  assert.equal(normalize(form({ Role: 'Sales Manager' })).watch_scope, 'rep_channels');
  assert.equal(normalize(form({ Role: 'Leadership', Market: 'Company-wide' })).watch_scope, 'rep_channels');
  assert.equal(normalize(form({ Role: 'Sales Rep' })).watch_scope, null);
  assert.equal(normalize(form({ Role: 'Canvasser' })).watch_scope, null);
  for (const r of LEADS) assert.ok(Object.values(ROLES).includes(r), `LEADS entry ${r} is not a role`);
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
  assert.throws(() => normalize(form({ Email: 'not-an-email' })), /Invalid email/);
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

test('workflow A embeds the normalize lib verbatim and writes watch_scope', () => {
  const wf = WF(FILES.A);
  assert.ok(codeNode(wf, 'Normalize').includes(libBody('slack-onboarding-normalize.js')));
  const upsert = wf.nodes.find((n) => n.name === 'Upsert team_members');
  assert.ok(upsert.parameters.jsonBody.includes('watch_scope: $json.watch_scope'), 'upsert must persist watch_scope');
  assert.ok(upsert.parameters.queryParameters.parameters.some((q) => q.name === 'on_conflict' && q.value === 'email'));
});

test('workflows B and C embed the resolve lib verbatim', () => {
  const body = libBody('slack-onboarding-resolve.js');
  assert.ok(codeNode(WF(FILES.B), 'Resolve Channels').includes(body));
  assert.ok(codeNode(WF(FILES.C), 'Resolve Channels').includes(body));
});

// --- Live wiring guards ------------------------------------------------------

test('every Slack and Supabase HTTP call uses the shared n8n credentials, nothing inline', () => {
  for (const f of Object.values(FILES)) {
    const wf = WF(f);
    const http = wf.nodes.filter((n) => n.type === 'n8n-nodes-base.httpRequest');
    const slackCalls = http.filter((n) => String(n.parameters.url).includes('slack.com/api/'));
    const supabaseCalls = http.filter((n) => String(n.parameters.url).includes('supabase.co/rest/v1/'));
    assert.ok(slackCalls.length > 0, `${f} has Slack calls`);
    assert.ok(supabaseCalls.length > 0, `${f} has Supabase calls`);
    assert.equal(slackCalls.length + supabaseCalls.length, http.length, `${f}: every HTTP node is a Slack or Supabase call`);
    for (const n of slackCalls) {
      assert.equal(n.parameters.authentication, 'predefinedCredentialType', `${f} / ${n.name}`);
      assert.equal(n.parameters.nodeCredentialType, 'slackApi', `${f} / ${n.name}`);
      assert.deepEqual(n.credentials.slackApi, SLACK_CRED, `${f} / ${n.name}: must use the Reece Bot credential`);
    }
    for (const n of supabaseCalls) {
      assert.equal(n.parameters.authentication, 'predefinedCredentialType', `${f} / ${n.name}`);
      assert.equal(n.parameters.nodeCredentialType, 'supabaseApi', `${f} / ${n.name}`);
      assert.deepEqual(n.credentials.supabaseApi, SUPABASE_CRED, `${f} / ${n.name}: must use the LP Supabase credential`);
      // n8n expression prefix is a single "=" — "==https://" is a real bug we hit once.
      assert.ok(n.parameters.url === `=${SUPABASE_REST}${n.parameters.url.split('/rest/v1/')[1]}`, `${f} / ${n.name}: url must be =${SUPABASE_REST}<table>`);
    }
    // No hand-built auth headers and no bot token in the JSON anywhere.
    for (const n of http) {
      const headers = (n.parameters.headerParameters || { parameters: [] }).parameters.map((h) => h.name.toLowerCase());
      for (const h of ['authorization', 'apikey']) assert.ok(!headers.includes(h), `${f} / ${n.name}: ${h} header must come from the credential`);
    }
    const raw = JSON.stringify(wf);
    assert.ok(!/xoxb-/.test(raw), `${f} contains a Slack token`);
    assert.ok(!/\$env\.(SLACK_BOT_TOKEN|SLACK_SIGNING_SECRET|LP_SUPABASE_KEY)/.test(raw), `${f} still reads a retired env var`);
    // Every node name referenced by a connection exists.
    const names = new Set(wf.nodes.map((n) => n.name));
    for (const [from, outs] of Object.entries(wf.connections)) {
      assert.ok(names.has(from), `${f}: connection from unknown node ${from}`);
      for (const branch of outs.main) for (const c of branch || []) assert.ok(names.has(c.node), `${f}: connection to unknown node ${c.node}`);
    }
  }
});

test('workflows are checked in as they run live (active, no pinned data)', () => {
  for (const f of Object.values(FILES)) {
    const wf = WF(f);
    assert.equal(wf.active, true, `${f} mirrors the live, active workflow`);
    assert.deepEqual(wf.pinData, {}, `${f}: never commit pinned test data (it carries real names/phones)`);
    // The public API rejects the whole update on any settings key it does not
    // know (400 "settings must NOT have additional properties"). `binaryMode`
    // is written by the editor and broke deploy run 41; keep exports clean.
    const allowed = ['executionOrder', 'timezone', 'availableInMCP', 'saveExecutionProgress', 'saveManualExecutions',
      'saveDataErrorExecution', 'saveDataSuccessExecution', 'executionTimeout', 'errorWorkflow', 'callerPolicy'];
    for (const k of Object.keys(wf.settings)) assert.ok(allowed.includes(k), `${f}: settings.${k} is not accepted by the n8n public API — remove it from the export`);
  }
});

test('workflow B is driven by the Slack Trigger on team_join; the old HMAC webhook is disabled', () => {
  const wf = WF(FILES.B);
  const trigger = wf.nodes.find((n) => n.type === 'n8n-nodes-base.slackTrigger');
  assert.ok(trigger, 'B needs a Slack Trigger node');
  assert.equal(trigger.disabled, undefined);
  assert.deepEqual(trigger.parameters.trigger, ['team_join']);
  assert.deepEqual(trigger.credentials.slackApi, SLACK_CRED);
  assert.deepEqual(wf.connections[trigger.name].main[0].map((c) => c.node), ['Route']);
  // Route only proceeds for a real (non-bot) team_join with a user id.
  const route = codeNode(wf, 'Route');
  assert.ok(route.includes("j.type === 'team_join'") && route.includes('!u.is_bot') && route.includes('!!u.id'));
  // The legacy webhook must stay disabled and disconnected so it cannot double-fire.
  for (const hook of wf.nodes.filter((n) => n.type === 'n8n-nodes-base.webhook')) {
    assert.equal(hook.disabled, true, `${hook.name} must stay disabled`);
    const outs = (wf.connections[hook.name] || { main: [] }).main.flat().filter(Boolean);
    assert.equal(outs.length, 0, `${hook.name} must not be wired to anything`);
  }
});

test('workflow C answers the caller before doing any Slack or Supabase work, and is fail-closed', () => {
  const wf = WF(FILES.C);
  const hook = wf.nodes.find((n) => n.type === 'n8n-nodes-base.webhook');
  assert.equal(hook.parameters.path, 'team-departure');
  assert.equal(hook.parameters.responseMode, 'responseNode');
  const auth = codeNode(wf, 'Authorize & Parse');
  assert.ok(auth.includes('$env.SLACK_DEPARTURE_TOKEN') && auth.includes("headers['x-departure-token']"));
  assert.ok(auth.includes('expected.length > 0'), 'an unset token must reject every call');
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
      if (node.type === 'n8n-nodes-base.httpRequest') assert.ok(responded, `${name} runs before the caller was answered`);
      for (const branch of (wf.connections[name] || { main: [] }).main) for (const c of branch || []) next.push(c.node);
    }
    frontier = next;
  }
  assert.ok(responded);
});
