# I.CN — Contact Normalizer v2.2: guest-visitor placeholder guard

**Applied live via n8n API: 2026-07-04** (workflow `aZaSxWpdGuC7Zcul`, published — active version `a61e0922-0921-4106-b6f4-bb058478d99f`).
**Incident:** Victor Lopez, GHL contact `XdAUR9qR42UdBre6Byrw`. The live-chat widget created the contact as
"Guest Visitor bljpx"; I.CN v2.1 normalized the placeholder and downstream stamped `name-normalized`,
certifying a garbage name as clean.

## Change (in the "Normalize Name" code node driver loop)

Before `normalizeContact()` runs, each contact is checked against the live-chat placeholder pattern:

```js
const GUEST_PLACEHOLDER_RE = /^guest\s+visitor\b/i;
// matched against the full "first last" name AND the raw firstName
```

When it matches:

- **Normalization is skipped entirely** — no name write, no opp rename, so nothing downstream can
  stamp `name-normalized` off a `write` action.
- Tag **`name-placeholder`** is applied instead (via the existing tag-POST path, `action: 'placeholder'`),
  so these contacts stay visible and queryable.
- If `name-placeholder` is already present, the contact is skipped silently.

## Interplay with LP MCP identity promotion (same incident, v1.1)

LP MCP's `promoteIdentityToGHL` (src/services/identity-extraction.js) writes the real name extracted
from the conversation to the standard fields and **removes `name-placeholder`**. I.CN then normalizes
normally on its next pass.

## Note for Mark

If any GHL workflow stamps `name-normalized` unconditionally after calling the I.CN webhook, it should
be conditioned on the webhook response's `action === 'write'` (the v2.2 response returns
`action: 'placeholder'` for these contacts). GHL workflow changes are out of scope for the agentic
handoff — flagging only.
