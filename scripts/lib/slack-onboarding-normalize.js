// Shared with the `Normalize` Code node in workflows/OPS.SLK-A-team-onboarding-intake.json.
// scripts/test-slack-onboarding.js asserts the workflow embeds this file verbatim
// (everything above the module.exports line), so edit HERE and re-embed — never
// edit the copy inside the workflow JSON on its own.
//
// Input: the raw n8n Form Trigger item — keys are the form field LABELS.
// Output: the team_members row shape, plus `watch_scope`, `needs_approval` and
// `pro_id`.

const MARKETS = {
  'jacksonville': 'JAX',
  'st. petersburg': 'STPET',
  'st petersburg': 'STPET',
  'sarasota': 'SAR',
  // Lakeland merged into Orlando on 2026-09-28 (LP-MCP sql/135). The key stays
  // so a submission from an old form link still lands, in Orlando.
  'lakeland': 'ORL',
  'fort lauderdale': 'FTLAU',
  'orlando': 'ORL',
  'fort myers': 'FTMYR',
  'company-wide': null
};

// Keys are compared after normalizeLabel(), so "Dispatch/Confirmer" and
// "Dispatch / Confirmer" are the same key. Mark relabelled the live form on
// 2026-10-02 and every new label threw "Unknown role" until these were added;
// the old labels stay so a cached form still works.
const ROLES = {
  'sales rep': 'sales_rep',
  'canvasser': 'canvasser',
  'canvass team lead': 'canvass_team_lead',
  'canvas team lead': 'canvass_team_lead',
  'canvass lead': 'canvass_team_lead',
  'canvas lead': 'canvass_team_lead',
  'sales manager': 'sales_manager',
  'canvass manager': 'canvass_manager',
  'canvas manager': 'canvass_manager',
  'service lead': 'service_lead',
  'service team': 'service_lead',
  'dispatch/confirmer': 'dispatch',
  'dispatch': 'dispatch',
  'confirmer': 'dispatch',
  'rehash': 'rehash',
  'setter': 'setter',
  'call center manager': 'call_center_manager',
  'executive leadership': 'leadership',
  'leadership': 'leadership'
};

// Roles that must be approved before Workflow B will provision them.
const NEEDS_APPROVAL = ['sales_manager','canvass_manager','call_center_manager','leadership'];
const WATCH_ALL = ['m.richard@reecewindows.com'];

// Pro ID is required for EVERY role (Mark, 2026-10-07). It is the person's
// OWN 4-digit Lead Perfection PRO number, saved on team_members and later used
// to match people across systems.

// Lowercase, trim, no spaces around "/", single spaces — so a label typed with
// or without spaces around the slash, or with a double space, still matches.
function normalizeLabel(raw) {
  return String(raw || '').trim().toLowerCase().replace(/\s*\/\s*/g, '/').replace(/\s+/g, ' ');
}

function normalizeProId(raw) {
  const digits = String(raw || '').replace(/\D/g, '');
  if (!digits) throw new Error('Pro ID is required — enter the 4-digit Lead Perfection PRO number');
  if (digits.length !== 4) {
    throw new Error('Pro ID must be exactly 4 digits, got "' + raw + '" (' + digits.length + ' digits)');
  }
  return digits;
}

function normalize(f) {
  const first = String(f['First name'] || '').trim();
  const last  = String(f['Last name'] || '').trim();
  const email = String(f['Email'] || '').trim().toLowerCase();
  const mk    = normalizeLabel(f['Market']);
  const rl    = normalizeLabel(f['Role']);

  if (!first || !last) throw new Error('First and last name are required');
  if (!email.includes('@')) throw new Error('Invalid email: ' + f['Email']);
  if (!(mk in MARKETS)) throw new Error('Unknown market: ' + f['Market']);
  if (!(rl in ROLES)) throw new Error('Unknown role: ' + f['Role']);

  const role = ROLES[rl];
  // watch_scope drives automatic channel membership beyond the role map:
  //   'all'          -> every channel in slack_channels, including future ones
  //   'rep_channels' -> every market sales channel (#sales-<market>)
  // Per-rep private channels were removed on 2026-09-14; reps live in their
  // market's sales channel, so that is what a watcher now watches. 'all' is
  // only for the people on WATCH_ALL: it includes #ops-alerts, the system
  // channel. Call center managers watch the market sales channels instead
  // (Mark, 2026-10-07: managers do not belong in #ops-alerts). Dispatch talks
  // to reps, and a sales manager covers more than their own market.
  const REP_CHANNEL_WATCHERS = ['dispatch', 'sales_manager', 'call_center_manager'];
  const watch_scope =
    WATCH_ALL.includes(email) ? 'all' :
    REP_CHANNEL_WATCHERS.includes(role) ? 'rep_channels' : null;

  return {
    first_name: first,
    last_name: last,
    email,
    phone: String(f['Mobile phone'] || '').replace(/\D/g, ''),
    market_code: MARKETS[mk],
    role,
    pro_id: normalizeProId(f['Pro ID']),
    watch_scope,
    needs_approval: NEEDS_APPROVAL.includes(role)
  };
}

module.exports = { normalize, normalizeProId, normalizeLabel, MARKETS, ROLES, NEEDS_APPROVAL, WATCH_ALL };
