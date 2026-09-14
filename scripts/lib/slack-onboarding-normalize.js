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
  'dispatch / confirmer': 'dispatch',
  'dispatch': 'dispatch',
  'confirmer': 'dispatch',
  'setter': 'setter',
  'call center manager': 'call_center_manager',
  'executive leadership': 'leadership',
  'leadership': 'leadership'
};

// Roles that must be approved before Workflow B will provision them.
const NEEDS_APPROVAL = ['sales_manager','canvass_manager','call_center_manager','leadership'];
const WATCH_ALL = ['m.richard@reecewindows.com'];

// Roles that carry a Lead Perfection PRO number. This is the person's OWN
// 4-digit PRO id — the one they are assigned and log in with — not the
// promoter id credited on a lead. Everyone else (dispatch, setters,
// leadership, service leads) has none, so the field is optional on the form
// and enforced here, where the role is known.
const PRO_ID_ROLES = ['sales_rep', 'canvasser', 'sales_manager', 'canvass_manager'];

function normalizeProId(raw, role) {
  const digits = String(raw || '').replace(/\D/g, '');
  if (!digits) {
    if (PRO_ID_ROLES.includes(role)) {
      throw new Error('Pro ID is required for ' + role + ' — enter the 4-digit Lead Perfection PRO number');
    }
    return null;
  }
  if (digits.length !== 4) {
    throw new Error('Pro ID must be exactly 4 digits, got "' + raw + '" (' + digits.length + ' digits)');
  }
  return digits;
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
  // watch_scope drives automatic channel membership beyond the role map:
  //   'all'          -> every channel in slack_channels, including future ones
  //   'rep_channels' -> every market sales channel (#sales-<market>)
  // Per-rep private channels were removed on 2026-09-14; reps live in their
  // market's sales channel, so that is what a watcher now watches. The call
  // center manager runs the whole floor and needs full visibility. Dispatch
  // talks to reps, and a sales manager covers more than their own market, so
  // both get every market sales channel.
  const FULL_ACCESS_ROLES = ['call_center_manager'];
  const REP_CHANNEL_WATCHERS = ['dispatch', 'sales_manager'];
  const watch_scope =
    (WATCH_ALL.includes(email) || FULL_ACCESS_ROLES.includes(role)) ? 'all' :
    REP_CHANNEL_WATCHERS.includes(role) ? 'rep_channels' : null;

  return {
    first_name: first,
    last_name: last,
    email,
    phone: String(f['Mobile phone'] || '').replace(/\D/g, ''),
    market_code: MARKETS[mk],
    role,
    pro_id: normalizeProId(f['Pro ID'], role),
    watch_scope,
    needs_approval: NEEDS_APPROVAL.includes(role)
  };
}

module.exports = { normalize, normalizeProId, MARKETS, ROLES, NEEDS_APPROVAL, WATCH_ALL, PRO_ID_ROLES };
