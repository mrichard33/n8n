// Shared with the `Normalize` Code node in workflows/OPS.SLK-A-team-onboarding-intake.json.
// scripts/test-slack-onboarding.js asserts the workflow embeds this file verbatim
// (everything above the module.exports line), so edit HERE and re-embed — never
// edit the copy inside the workflow JSON on its own.
//
// Input: the raw n8n Form Trigger item — keys are the form field LABELS.
// Output: the team_members row shape plus `slug`, the person's channel-name slug.

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

// Lower-case, strip accents, collapse every run of non-alphanumerics to one
// hyphen, trim hyphens. "José O'Brien" -> "jose-o-brien". Slack channel names
// only allow a-z 0-9 - _ so this is also the channel-safe form.
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
  const last = String(f['Last name'] || '').trim();
  const email = String(f['Company email'] || '').trim().toLowerCase();
  const mk = String(f['Market'] || '').trim().toLowerCase();
  const rl = String(f['Role'] || '').trim().toLowerCase();
  if (!first || !last) throw new Error('First and last name are required');
  if (!email.includes('@')) throw new Error('Invalid company email: ' + f['Company email']);
  if (!(mk in MARKETS)) throw new Error('Unknown market: ' + f['Market']);
  if (!(rl in ROLES)) throw new Error('Unknown role: ' + f['Role']);
  return {
    first_name: first,
    last_name: last,
    email,
    phone: String(f['Mobile phone'] || '').replace(/\D/g, ''),
    market_code: MARKETS[mk],
    role: ROLES[rl],
    slug: `${slugify(first)}-${slugify(last)}`
  };
}

module.exports = { normalize, slugify, MARKETS, ROLES };
