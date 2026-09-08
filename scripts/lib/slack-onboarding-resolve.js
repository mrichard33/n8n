// Shared with the `Resolve Channels` Code node in
// workflows/OPS.SLK-B-slack-join-provisioner.json and OPS.SLK-C-team-departure.json.
// scripts/test-slack-onboarding.js asserts both workflows embed this file verbatim
// (everything above the module.exports line), so edit HERE and re-embed.
//
// No role logic lives here. The role -> channel rules are rows in
// slack_role_channels; this only expands the `<market>` placeholder.

// patterns: channel_pattern values for one role, e.g. ['announcements', 'sales-<market>'].
// marketSlug: slack_market_slugs.slug for the person's market, or '' / null when
// the person is company-wide. Market-scoped patterns are skipped (not thrown) when
// there is no market, so leadership / dispatch / contact-center never need one.
function resolveChannels(patterns, marketSlug) {
  const out = [];
  for (const p of patterns) {
    const pattern = String(p || '').trim();
    if (!pattern) continue;
    if (pattern.includes('<market>')) {
      if (!marketSlug) continue;
      out.push(pattern.replace('<market>', marketSlug));
    } else {
      out.push(pattern);
    }
  }
  return [...new Set(out)];
}

// Same algorithm as slugify() in slack-onboarding-normalize.js. It is repeated
// here because team_members stores first/last name, not the slug, so B and C
// re-derive it — and the n8n Code node can only embed one file.
function slugify(s) {
  return String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// Per-rep private channel: sales-<market>-<firstname>-<lastname>.
// Slack caps channel names at 80 characters.
function repChannelName(marketSlug, slug) {
  return `sales-${marketSlug}-${slug}`.slice(0, 80);
}

module.exports = { resolveChannels, repChannelName, slugify };
