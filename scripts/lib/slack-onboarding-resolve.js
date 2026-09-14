// Shared with the `Resolve Channels` Code node in OPS.SLK-B and OPS.SLK-C, and
// with the equivalent inline logic in OPS.SLK-D.
// scripts/test-slack-onboarding.js asserts both workflows embed this file
// verbatim (everything above the module.exports line), so edit HERE and
// re-embed — never edit the copy inside the workflow JSON on its own.
//
// `<market>` in a slack_role_channels pattern is replaced with the person's
// market slug. A market-scoped pattern is skipped entirely for someone with no
// market (company-wide people), rather than producing a broken channel name.
//
// 2026-09-14: repChannelName() and slugify() were removed with the per-rep
// private channels. Reps now live in their market's #sales-<market> channel,
// which falls straight out of the role patterns below.

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

module.exports = { resolveChannels };
