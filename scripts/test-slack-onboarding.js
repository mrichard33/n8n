#!/usr/bin/env node
// node --test scripts/test-slack-onboarding.js
//
// Covers the pure functions the Slack onboarding workflows depend on, and
// guards that the workflow JSON files embed those exact functions — the n8n
// Code nodes cannot require() a file, so the source is copied into the node.
// If this test fails on "embeds", re-copy the lib file into the Code node.
//
// It also pins the live wiring: Slack calls authenticate with the n8n
// credential "Reece Bot" (slackApi) and Supabase calls with "LP Supabase"
// (supabaseApi); B is driven by the Slack Trigger; C is fail-closed; and
// nothing anywhere still builds a per-rep private channel (removed 2026-09-14).

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  normalize, normalizeProId, normalizeLabel, MARKETS, ROLES, NEEDS_APPROVAL, WATCH_ALL, PRO_ID_ROLES,
} = require('./lib/slack-onboarding-normalize');
const { resolveChannels } = require('./lib/slack-onboarding-resolve');

const ROOT = path.join(__dirname, '..');
const WF = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'workflows', f), 'utf8'));
const FILES = {
  A: 'OPS.SLK-A-team-onboarding-intake.json',
  B: 'OPS.SLK-B-slack-join-provisioner.json',
  C: 'OPS.SLK-C-team-departure.json',
  D: 'OPS.SLK-D-backfill-slack-ids.json',
};

// The n8n credentials the live workflows use. Ids are what the n8n instance
// assigned; the names are what you see in the credential picker.
const SLACK_CRED = { id: '1OT2X5rtLCxwNgFI', name: 'Reece Bot' };
const SUPABASE_CRED = { id: '9QVXUFOAdIAIg4WH', name: 'LP Supabase' };
const SUPABASE_REST = 'https://rcjcgjlqzepicbwhnnjl.supabase.co/rest/v1/';

// A sample of the live slack_role_channels rows (as of 2026-10-02), so the
// resolve tests exercise real patterns rather than invented ones.
const ROLE_PATTERNS = {
  sales_rep: ['announcements', 'dispatch', 'general', 'sales-<market>'],
  canvasser: ['announcements', 'canvass-<market>', 'general'],
  canvass_team_lead: ['announcements', 'canvass-<market>', 'canvass-all', 'canvass-leadership', 'general'],
  rehash: ['announcements', 'contact-center', 'contact-rehash', 'general'],
  sales_manager: ['announcements', 'dispatch', 'general', 'sales-<market>', 'sales-all', 'service-<market>'],
  canvass_manager: ['announcements', 'canvass-<market>', 'canvass-all', 'general'],
  service_lead: ['announcements', 'general', 'service-<market>'],
  dispatch: ['announcements', 'contact-center', 'dispatch', 'general', 'lead-intelligence'],
  setter: ['announcements', 'contact-center', 'general'],
  leadership: ['announcements', 'general', 'lead-intelligence', 'leadership'],
};

function form(overrides = {}) {
  return {
    'First name': 'Jane',
    'Last name': 'Smith',
    'Email': 'Jane.Smith@ReeceWindows.com',
    'Mobile phone': '(239) 555-0100',
    'Pro ID': '4213',
    'Market': 'Fort Myers',
    'Role': 'Sales Rep',
    submittedAt: '2026-09-08T12:00:00.000Z',
    formMode: 'production',
    ...overrides
  };
}

// --- normalize -----------------------------------------------------------

test('normalize: market labels map to codes', () => {
  assert.equal(normalize(form({ Market: 'Fort Lauderdale' })).market_code, 'FTLAU');
  assert.equal(normalize(form({ Market: 'St. Petersburg' })).market_code, 'STPET');
  assert.equal(normalize(form({ Market: 'St Petersburg' })).market_code, 'STPET');
  assert.equal(normalize(form({ Market: 'Fort Myers' })).market_code, 'FTMYR');
  assert.equal(normalize(form({ Market: 'Company-wide' })).market_code, null);
});

test('normalize: Lakeland lands in Orlando (markets merged 2026-09-28)', () => {
  assert.equal(normalize(form({ Market: 'Lakeland' })).market_code, 'ORL');
  assert.ok(!Object.values(MARKETS).includes('LAKE'), 'no market may still map to LAKE');
});

test('normalizeLabel: case, outer space, spaces around "/" and repeated spaces do not matter', () => {
  assert.equal(normalizeLabel('  Dispatch / Confirmer '), 'dispatch/confirmer');
  assert.equal(normalizeLabel('Dispatch/Confirmer'), 'dispatch/confirmer');
  assert.equal(normalizeLabel('Dispatch  /Confirmer'), 'dispatch/confirmer');
  assert.equal(normalizeLabel('Canvass   Team  Lead'), 'canvass team lead');
  assert.equal(normalizeLabel(undefined), '');
  // A map key that is not already in normalized form can never be matched.
  for (const k of [...Object.keys(ROLES), ...Object.keys(MARKETS)]) {
    assert.equal(normalizeLabel(k), k, `map key "${k}" is unreachable`);
  }
});

// The labels Mark put on the live form on 2026-10-02. Every one threw
// "Unknown role" until the ROLES map learned them.
test('normalize: the relabelled form roles map', () => {
  const cases = {
    'Canvass Team Lead': 'canvass_team_lead',
    'Canvas Team Lead': 'canvass_team_lead',
    'Canvass Lead': 'canvass_team_lead',
    'Canvas Lead': 'canvass_team_lead',
    'Canvas Manager': 'canvass_manager',
    'Service Team': 'service_lead',
    'Rehash': 'rehash',
    'Dispatch/Confirmer': 'dispatch',
    'Dispatch / Confirmer': 'dispatch',
  };
  for (const [label, role] of Object.entries(cases)) {
    assert.equal(normalize(form({ Role: label })).role, role, label);
  }
});

test('normalize: the new roles keep the existing approval and watch rules', () => {
  const ctl = normalize(form({ Role: 'Canvass Team Lead', Market: 'Orlando' }));
  assert.equal(ctl.market_code, 'ORL');
  assert.equal(ctl.needs_approval, false);
  assert.equal(ctl.watch_scope, null);
  const rehash = normalize(form({ Role: 'Rehash', 'Pro ID': '' }));
  assert.equal(rehash.pro_id, null);
  assert.equal(rehash.needs_approval, false);
  assert.equal(rehash.watch_scope, null);
  assert.equal(normalize(form({ Role: 'Dispatch/Confirmer', 'Pro ID': '' })).watch_scope, 'rep_channels');
});

test('normalize: unknown market or role throws', () => {
  assert.throws(() => normalize(form({ Market: 'Tampa' })), /Unknown market: Tampa/);
  assert.throws(() => normalize(form({ Role: 'CEO' })), /Unknown role: CEO/);
});

test('normalize: every form field the normalizer reads exists on the form', () => {
  const marketOptions = ['Jacksonville', 'St. Petersburg', 'Sarasota', 'Lakeland', 'Fort Lauderdale', 'Orlando', 'Fort Myers', 'Company-wide'];
  const roleOptions = ['Sales Rep', 'Canvasser', 'Sales Manager', 'Canvass Manager', 'Service Lead', 'Dispatch / Confirmer', 'Setter', 'Call Center Manager', 'Executive Leadership'];
  for (const m of marketOptions) assert.ok(normalizeLabel(m) in MARKETS, m);
  for (const r of roleOptions) assert.ok(normalizeLabel(r) in ROLES, r);

  const trigger = WF(FILES.A).nodes.find((n) => n.type === 'n8n-nodes-base.formTrigger');
  const field = (label) => trigger.parameters.formFields.values.find((f) => f.fieldLabel === label);
  assert.deepEqual(field('Market').fieldOptions.values.map((v) => v.option), marketOptions);
  assert.deepEqual(field('Role').fieldOptions.values.map((v) => v.option), roleOptions);

  for (const label of ['First name', 'Last name', 'Email', 'Mobile phone', 'Market', 'Role']) {
    assert.ok(field(label), `form is missing the "${label}" field`);
    assert.equal(field(label).requiredField, true, `"${label}" must be required`);
  }
  // Pro ID is deliberately NOT required on the form — the trigger has no
  // conditional requirement and several roles have no Pro ID. normalize()
  // enforces it per role instead.
  assert.ok(field('Pro ID'), 'form is missing the "Pro ID" field');
  assert.notEqual(field('Pro ID').requiredField, true, 'Pro ID must stay optional on the form');
});

test('normalize: email lowercased, phone digits only, roles mapped', () => {
  const out = normalize(form());
  assert.equal(out.email, 'jane.smith@reecewindows.com');
  assert.equal(out.phone, '2395550100');
  assert.equal(out.role, 'sales_rep');
  assert.equal(normalize(form({ Role: 'Setter', 'Pro ID': '' })).role, 'setter');
  assert.equal(normalize(form({ Role: 'Dispatch / Confirmer', 'Pro ID': '' })).role, 'dispatch');
  assert.equal(normalize(form({ Role: 'Executive Leadership', 'Pro ID': '' })).role, 'leadership');
  assert.equal(normalize(form({ Role: 'canvass manager' })).role, 'canvass_manager');
});

test('normalize: watch_scope is all for WATCH_ALL and the call centre, rep_channels for dispatch and sales managers', () => {
  assert.ok(WATCH_ALL.length > 0);
  assert.equal(normalize(form({ Email: WATCH_ALL[0].toUpperCase() })).watch_scope, 'all');
  assert.equal(normalize(form({ Role: 'Call Center Manager', 'Pro ID': '' })).watch_scope, 'all');
  assert.equal(normalize(form({ Role: 'Sales Manager' })).watch_scope, 'rep_channels');
  assert.equal(normalize(form({ Role: 'Dispatch / Confirmer', 'Pro ID': '' })).watch_scope, 'rep_channels');
  assert.equal(normalize(form({ Role: 'Sales Rep' })).watch_scope, null);
  assert.equal(normalize(form({ Role: 'Canvasser' })).watch_scope, null);
  assert.equal(normalize(form({ Role: 'Executive Leadership', 'Pro ID': '' })).watch_scope, null);
});

test('normalize: needs_approval covers the manager roles only', () => {
  for (const r of NEEDS_APPROVAL) assert.ok(Object.values(ROLES).includes(r), `${r} is not a role`);
  assert.equal(normalize(form({ Role: 'Sales Manager' })).needs_approval, true);
  assert.equal(normalize(form({ Role: 'Call Center Manager', 'Pro ID': '' })).needs_approval, true);
  assert.equal(normalize(form({ Role: 'Sales Rep' })).needs_approval, false);
  assert.equal(normalize(form({ Role: 'Canvasser' })).needs_approval, false);
});

test('pro_id: required for reps, canvassers and their managers', () => {
  assert.deepEqual(PRO_ID_ROLES, ['sales_rep', 'canvasser', 'canvass_team_lead', 'sales_manager', 'canvass_manager']);
  for (const r of PRO_ID_ROLES) assert.ok(Object.values(ROLES).includes(r), `${r} is not a role`);
  for (const label of ['Sales Rep', 'Canvasser', 'Canvass Team Lead', 'Sales Manager', 'Canvass Manager']) {
    assert.equal(normalize(form({ Role: label, 'Pro ID': '4213' })).pro_id, '4213', label);
    assert.throws(() => normalize(form({ Role: label, 'Pro ID': '' })), /Pro ID is required/, label);
  }
});

test('pro_id: null for roles that do not carry one, and blank is fine there', () => {
  for (const label of ['Service Lead', 'Service Team', 'Dispatch / Confirmer', 'Dispatch/Confirmer', 'Rehash', 'Setter', 'Call Center Manager', 'Executive Leadership']) {
    assert.equal(normalize(form({ Role: label, 'Pro ID': '' })).pro_id, null, label);
    assert.equal(normalize(form({ Role: label })).pro_id, '4213', `${label} still stores a Pro ID when one is typed`);
  }
});

test('pro_id: exactly four digits, punctuation stripped, stored as a string', () => {
  assert.equal(normalize(form({ 'Pro ID': '(4213)' })).pro_id, '4213');
  assert.equal(normalize(form({ 'Pro ID': ' 4213 ' })).pro_id, '4213');
  assert.equal(typeof normalize(form({ 'Pro ID': '0421' })).pro_id, 'string');
  assert.equal(normalize(form({ 'Pro ID': '0421' })).pro_id, '0421', 'a leading zero must survive');
  assert.throws(() => normalize(form({ 'Pro ID': '421' })), /exactly 4 digits/);
  assert.throws(() => normalize(form({ 'Pro ID': '42130' })), /exactly 4 digits/);
  // A typo on an optional field is still a typo — do not store it silently.
  assert.throws(() => normalizeProId('42', 'setter'), /exactly 4 digits/);
  assert.equal(normalizeProId('', 'setter'), null);
});

test('normalize: trims names, rejects blanks and bad email', () => {
  const out = normalize(form({ 'First name': '  Jane ', 'Last name': ' Smith  ' }));
  assert.equal(out.first_name, 'Jane');
  assert.equal(out.last_name, 'Smith');
  assert.throws(() => normalize(form({ 'First name': '  ' })), /required/);
  assert.throws(() => normalize(form({ Email: 'not-an-email' })), /Invalid email/);
});

// --- resolve -------------------------------------------------------------

test('resolve: sales_rep + fortmyers', () => {
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_rep, 'fortmyers'),
    ['announcements', 'dispatch', 'general', 'sales-fortmyers']);
});

test('resolve: canvasser never includes dispatch', () => {
  const out = resolveChannels(ROLE_PATTERNS.canvasser, 'fortmyers');
  assert.deepEqual(out, ['announcements', 'canvass-fortmyers', 'general']);
  assert.ok(!out.includes('dispatch'));
  assert.ok(!resolveChannels(ROLE_PATTERNS.canvass_manager, 'orlando').includes('dispatch'));
});

test('resolve: canvass team lead gets their market canvass channel and #canvass-leadership, never #dispatch', () => {
  const out = resolveChannels(ROLE_PATTERNS.canvass_team_lead, 'orlando');
  assert.deepEqual(out, ['announcements', 'canvass-orlando', 'canvass-all', 'canvass-leadership', 'general']);
  assert.ok(!out.includes('dispatch'));
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.rehash, null),
    ['announcements', 'contact-center', 'contact-rehash', 'general']);
});

test('resolve: a company-wide person skips market patterns without throwing', () => {
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.leadership, null),
    ['announcements', 'general', 'lead-intelligence', 'leadership']);
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_rep, ''),
    ['announcements', 'dispatch', 'general']);
});

test('resolve: dedupes, ignores blank patterns, sales_manager gets both market channels', () => {
  assert.deepEqual(resolveChannels(['general', 'general', '', null], 'orlando'), ['general']);
  assert.deepEqual(resolveChannels(ROLE_PATTERNS.sales_manager, 'orlando'),
    ['announcements', 'dispatch', 'general', 'sales-orlando', 'sales-all', 'service-orlando']);
});

// --- embedding guards ----------------------------------------------------

function libBody(file) {
  const src = fs.readFileSync(path.join(__dirname, 'lib', file), 'utf8');
  // From the first top-level statement to the module.exports LINE (the header
  // comment also mentions module.exports, so anchor on line start, not indexOf).
  const cut = src.search(/^module\.exports/m);
  const start = src.search(/^(const|function) /m);
  assert.ok(cut > 0 && start >= 0 && start < cut, `${file}: cannot locate the body to embed`);
  const body = src.slice(start, cut).trim();
  // Guard against a vacuous pass: an empty body is "included" in anything.
  // The resolve lib is ~380 chars since repChannelName was removed, so the
  // floor sits below that while still catching a truncated or empty extract.
  assert.ok(body.length > 250 && /^function |^const /m.test(body), `${file}: extracted body is too small to be real`);
  return body;
}

function codeNode(wf, name) {
  const node = wf.nodes.find((n) => n.name === name && n.type === 'n8n-nodes-base.code');
  assert.ok(node, `${wf.name} has no Code node named "${name}"`);
  return node.parameters.jsCode;
}

test('workflow A embeds the normalize lib verbatim and persists what it derives', () => {
  const wf = WF(FILES.A);
  assert.ok(codeNode(wf, 'Normalize').includes(libBody('slack-onboarding-normalize.js')));
  const upsert = wf.nodes.find((n) => n.name === 'Upsert team_members');
  for (const key of ['pro_id: $json.pro_id', 'watch_scope: $json.watch_scope', 'role: $json.role']) {
    assert.ok(upsert.parameters.jsonBody.includes(key), `upsert must persist ${key}`);
  }
  assert.ok(upsert.parameters.queryParameters.parameters.some((q) => q.name === 'on_conflict' && q.value === 'email'));
  // A re-submit must never wipe ids the provisioner wrote.
  for (const key of ['slack_user_id', 'approved_by']) {
    assert.ok(!upsert.parameters.jsonBody.includes(key), `upsert must not overwrite ${key}`);
  }
});

test('workflows B and C embed the resolve lib verbatim', () => {
  const body = libBody('slack-onboarding-resolve.js');
  assert.ok(codeNode(WF(FILES.B), 'Resolve Channels').includes(body));
  assert.ok(codeNode(WF(FILES.C), 'Resolve Channels').includes(body));
});

// --- per-rep channels are gone -------------------------------------------

test('no workflow builds, joins, archives or records a per-rep private channel', () => {
  const banned = [
    'rep_channel_name', 'repChannelName', 'existing_rep_channel_id', 'needs_rep_channel',
    'Rep Channel Id', 'Create Rep Channel', 'Archive Rep Channel', 'Deregister Rep Channel',
    'Invite Rep to Own Channel', 'Record Rep Channel',
    'conversations.create', 'conversations.archive', 'conversations.setTopic', 'conversations.setPurpose',
  ];
  for (const f of Object.values(FILES)) {
    const raw = JSON.stringify(WF(f));
    for (const t of banned) assert.ok(!raw.includes(t), `${f} still references ${t}`);
  }
  // watch_scope 'rep_channels' survives, repointed at the market sales channels.
  assert.ok(JSON.stringify(WF(FILES.D)).includes('salesChannelIds'),
    'the backfill must fan watchers out to the market sales channels');
});

// --- live wiring ---------------------------------------------------------

test('every Slack and Supabase HTTP call uses the shared n8n credentials, nothing inline', () => {
  for (const f of Object.values(FILES)) {
    const wf = WF(f);
    const http = wf.nodes.filter((n) => n.type === 'n8n-nodes-base.httpRequest');
    const slackCalls = http.filter((n) => String(n.parameters.url).includes('slack.com/api/'));
    const supabaseCalls = http.filter((n) => String(n.parameters.url).includes('supabase.co/rest/v1/'));
    assert.ok(slackCalls.length > 0, `${f} has Slack calls`);
    assert.ok(supabaseCalls.length > 0, `${f} has Supabase calls`);
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
      const tail = String(n.parameters.url).split('/rest/v1/')[1];
      assert.equal(n.parameters.url, `=${SUPABASE_REST}${tail}`, `${f} / ${n.name}: url must be =${SUPABASE_REST}<table>`);
    }
    for (const n of http) {
      const headers = (n.parameters.headerParameters || { parameters: [] }).parameters.map((h) => h.name.toLowerCase());
      for (const h of ['authorization', 'apikey']) {
        assert.ok(!headers.includes(h), `${f} / ${n.name}: ${h} must come from the credential`);
      }
    }
    const raw = JSON.stringify(wf);
    assert.ok(!/xoxb-/.test(raw), `${f} contains a Slack token`);
    assert.ok(!/\$env\.(SLACK_BOT_TOKEN|SLACK_SIGNING_SECRET|LP_SUPABASE_KEY)/.test(raw), `${f} still reads a retired env var`);

    // Every node name referenced by a connection exists. This is the safety net
    // for node deletions — a dangling edge fails here.
    const names = new Set(wf.nodes.map((n) => n.name));
    for (const [from, outs] of Object.entries(wf.connections)) {
      assert.ok(names.has(from), `${f}: connection from unknown node ${from}`);
      for (const branch of outs.main) for (const c of branch || []) assert.ok(names.has(c.node), `${f}: connection to unknown node ${c.node}`);
    }
  }
});

test('workflows are checked in as they run live (active, no pinned data, API-safe settings)', () => {
  // The public API rejects the whole update on any settings key it does not
  // know (400 "settings must NOT have additional properties"). binaryMode and
  // friends are written by the editor; keep exports clean.
  const allowed = ['executionOrder', 'timezone', 'availableInMCP', 'saveExecutionProgress', 'saveManualExecutions',
    'saveDataErrorExecution', 'saveDataSuccessExecution', 'executionTimeout', 'errorWorkflow'];
  for (const f of Object.values(FILES)) {
    const wf = WF(f);
    assert.equal(wf.active, true, `${f} mirrors the live, active workflow`);
    assert.deepEqual(wf.pinData, {}, `${f}: never commit pinned data (it carries real tokens and phone numbers)`);
    for (const k of Object.keys(wf.settings)) {
      assert.ok(allowed.includes(k), `${f}: settings.${k} is not accepted by the n8n public API — remove it from the export`);
    }
  }
});

test('workflow B is driven by the Slack Trigger; the old HMAC webhook is disabled', () => {
  const wf = WF(FILES.B);
  const trigger = wf.nodes.find((n) => n.type === 'n8n-nodes-base.slackTrigger');
  assert.ok(trigger, 'B needs a Slack Trigger node');
  assert.equal(trigger.disabled, undefined);
  assert.deepEqual(trigger.credentials.slackApi, SLACK_CRED);
  assert.deepEqual(wf.connections[trigger.name].main[0].map((c) => c.node), ['Route']);

  // Route must classify a real join and a real deactivation, and nothing else.
  const route = codeNode(wf, 'Route');
  assert.ok(route.includes("j.type === 'team_join'") && route.includes('!u.is_bot') && route.includes('!!u.id'));
  assert.ok(route.includes("j.type === 'user_change'") && route.includes('u.deleted === true'));

  // The legacy webhook must stay disabled and disconnected so it cannot double-fire.
  for (const hook of wf.nodes.filter((n) => n.type === 'n8n-nodes-base.webhook')) {
    assert.equal(hook.disabled, true, `${hook.name} must stay disabled`);
    const outs = (wf.connections[hook.name] || { main: [] }).main.flat().filter(Boolean);
    assert.equal(outs.length, 0, `${hook.name} must not be wired to anything`);
  }

  // The invite results must flow straight into activation now that the rep
  // channel chain is gone.
  assert.deepEqual(wf.connections['Collect Invite Results'].main[0].map((c) => c.node), ['Activate Member']);
});

test('workflow C answers the caller before any Slack or Supabase work, and is fail-closed', () => {
  const wf = WF(FILES.C);
  const hook = wf.nodes.find((n) => n.type === 'n8n-nodes-base.webhook');
  assert.equal(hook.parameters.path, 'team-departure');
  assert.equal(hook.parameters.responseMode, 'responseNode');
  const auth = codeNode(wf, 'Authorize & Parse');
  assert.ok(auth.includes('$env.SLACK_DEPARTURE_TOKEN') && auth.includes("headers['x-departure-token']"));
  assert.ok(auth.includes('expected.length > 0'), 'an unset token must reject every call');
  assert.deepEqual(wf.connections['Collect Kick Results'].main[0].map((c) => c.node), ['Mark Departed']);

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

test('workflow D backfills on a schedule and honours shadow mode', () => {
  const wf = WF(FILES.D);
  assert.ok(wf.nodes.some((n) => n.type === 'n8n-nodes-base.scheduleTrigger'), 'D needs its hourly trigger');
  assert.ok(wf.nodes.some((n) => n.type === 'n8n-nodes-base.manualTrigger'), 'D keeps the manual run');
  assert.ok(codeNode(wf, 'Plan Backfill').includes("$env.SLACK_ONBOARDING_MODE === 'live'"),
    'D must stay gated on the live-mode switch');
});
