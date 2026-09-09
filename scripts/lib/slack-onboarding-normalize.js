// Shared with the `Normalize` Code node in workflows/OPS.SLK-A-team-onboarding-intake.json.
// scripts/test-slack-onboarding.js asserts the workflow embeds this file verbatim
// (everything above the module.exports line), so edit HERE and re-embed — never
// edit the copy inside the workflow JSON on its own.
//
// Input: the raw n8n Form Trigger item — keys are the form field LABELS.
// Output: the team_members row shape plus `slug`, the person's channel-name slug,
// and `watch_scope`: 'all' for the people in WATCH_ALL, 'rep_channels' for the
// lead roles in LEADS (they get visibility into the per-rep channels), else null.

const MARKETS = {
  'jacksonville': 'JAX',
  'st. petersburg': 'STPET',
  'st petersburg': 'STPET',
  'sarasota': 'SAR',
  'lakeland': 'LAKE',
  'fort lauderdale': 'FTLAU',
  'orlando': 'ORL',
  'fort myers': 'FTMYR',
  'company-wide': null
};

const ROLES = {
  'sales rep': 'sales_rep',
  'canvasser': 'canvasser',
  'sales manager': 'sales_manager',
  'canvass manager': 'canvass_manager',
  'service lead': 'service_lead',
  'dispatch': 'dispatch',
  'contact center agent': 'contact_center',
  'leadership': 'leadership'
};

const LEADS = ['leadership', 'sales_manager', 'canvass_manager', 'service_lead'];
const WATCH_ALL = ['m.richard@reecewindows.com'];

function slugify(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function normalize(f) {
  const first = String(f['First name'] || '').trim();
  const last  = String(f['Last name'] || '').trim();
  const email = String(f['Email'] || '').trim().toLowerCase();
  const mk    = String(f['Market'] || '').trim().toLowerCase();
  const rl    = String(f['Role'] || '').trim().toLowerCase();

  if (!first || !last) throw new Error('First and last name are required');
  if (!email.includes('@')) throw new Error('Invalid email: ' + f['Email']);
  if (!(mk in MARKETS)) throw new Error('Unknown market: ' + f['Market']);
  if (!(rl in ROLES)) throw new Error('Unknown role: ' + f['Role']);

  const role = ROLES[rl];
  const watch_scope =
    WATCH_ALL.includes(email) ? 'all' :
    LEADS.includes(role) ? 'rep_channels' : null;

  return {
    first_name: first,
    last_name: last,
    email,
    phone: String(f['Mobile phone'] || '').replace(/\D/g, ''),
    market_code: MARKETS[mk],
    role,
    slug: `${slugify(first)}-${slugify(last)}`,
    watch_scope
  };
}

module.exports = { normalize, slugify, MARKETS, ROLES, LEADS, WATCH_ALL };
