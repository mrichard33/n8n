"""Approval-reply parsing (§14) — implemented exactly in the specified order.

THE TRAP: "not approved" contains "approved". Any implementation that tests
approve before deny, or uses a bare substring check, sends an unapproved
report to a vendor. Steps 5 and 6 run before step 7, always. Requiring the
command at the START of the cleaned text is what defeats a quoted older
"APPROVED" further down the thread.

This lives in the render service (not in n8n JSON) so the dangerous logic is
unit-tested in one place; Workflow 02 calls POST /classify-reply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

APPROVED = "APPROVED"
DENY = "DENY"
EDIT = "EDIT"
UNKNOWN = "UNKNOWN"

DATA_CORRECTION = "DATA_CORRECTION"
NARRATIVE_EDIT = "NARRATIVE_EDIT"

# §14 step 1: quoted-history markers. Everything from the first match down is
# dropped, as is every line beginning with '>'.
_QUOTE_START = re.compile(r"^\s*(On .+ wrote:|-----Original Message-----|_{5,}|From:\s)", re.M)
# §14 step 2: signature delimiter.
_SIG_START = re.compile(r"^--\s*$", re.M)

# §14 step 5 — DENY FIRST, ALWAYS.
_DENY = re.compile(r"^(deny|denied|reject|hold|do not send|don'?t send)\b")
_NOT_APPROVED = re.compile(r"^not\s+approved?\b")
# §14 step 6.
_EDIT = re.compile(r"^edit\s*:")
# §14 step 7 — only after DENY and EDIT have both failed to match.
_APPROVE = re.compile(r"^(approved?|approve it|ok to send|send it)\b")


@dataclass(frozen=True)
class ReplyClassification:
    classification: str            # APPROVED | DENY | EDIT | UNKNOWN
    reason: str | None = None      # DENY: remainder after the keyword
    instruction: str | None = None # EDIT: remainder after 'edit:'
    revision_kind: str | None = None  # EDIT only
    cleaned: str = ""              # what was actually classified (audit trail)

    def as_record(self) -> dict:
        return {"classification": self.classification, "reason": self.reason,
                "instruction": self.instruction, "revision_kind": self.revision_kind,
                "cleaned_reply": self.cleaned}


def clean_reply(raw: str) -> str:
    """§14 steps 1–3: strip quoted history, strip signature, normalise
    whitespace, lowercase, trim, first 300 chars."""
    text = raw or ""
    m = _QUOTE_START.search(text)
    if m:
        text = text[: m.start()]
    text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(">"))
    m = _SIG_START.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:300]


def classify_reply(raw: str) -> ReplyClassification:
    """§14 steps 4–8. The command MUST appear at the start of the cleaned
    reply; anything else is UNKNOWN — do NOT guess, send clarification, stay
    pending."""
    cleaned = clean_reply(raw)

    # Step 5 — DENY first, always. Both patterns, before anything else.
    m = _DENY.match(cleaned)
    if m:
        reason = cleaned[m.end():].lstrip(" ,:;—–-").strip() or None
        return ReplyClassification(DENY, reason=reason, cleaned=cleaned)
    m = _NOT_APPROVED.match(cleaned)
    if m:
        reason = cleaned[m.end():].lstrip(" ,:;—–-").strip() or None
        return ReplyClassification(DENY, reason=reason, cleaned=cleaned)

    # Step 6 — EDIT.
    m = _EDIT.match(cleaned)
    if m:
        instruction = cleaned[m.end():].strip()
        return ReplyClassification(EDIT, instruction=instruction,
                                   revision_kind=classify_revision_kind(instruction),
                                   cleaned=cleaned)

    # Step 7 — APPROVE, only now.
    if _APPROVE.match(cleaned):
        return ReplyClassification(APPROVED, cleaned=cleaned)

    # Step 8 — anything else is UNKNOWN. Never guess.
    return ReplyClassification(UNKNOWN, cleaned=cleaned)


# ---------------------------------------------------------------------------
# Revision-kind classification (§14): DATA_CORRECTION when the instruction
# contains a numeric assertion about a metric or a correction verb applied to
# a figure; NARRATIVE_EDIT otherwise. Ambiguous -> NARRATIVE_EDIT, and the
# reply to the approver says so, so a human can escalate. Never guess a number.
# ---------------------------------------------------------------------------

# The correction phrasing must be APPLIED TO a figure — proximity, not mere
# co-occurrence ("do not name the agents in section 3" carries a digit and a
# 'not' yet corrects nothing). Ambiguous stays NARRATIVE_EDIT: never guess a
# number (§14).
_DIGIT_CORRECTIONS = [
    re.compile(r"\$?\d[\d,.$%]*(?:\s+\w+){0,3}\s*,?\s*not\s+\$?\d"),   # "47 appointments, not 49"
    re.compile(r"\b(should be|correct to|actually|off by)\s+\$?\d"),   # "should be 3"
    re.compile(r"\$?\d[\d,.$%]*[^.\n]{0,40}\b(wrong|incorrect)\b"),    # "the 38% figure is wrong"
    re.compile(r"\b(wrong|incorrect)\b[^.\n]{0,40}\$?\d"),             # "wrong — it is 31%"
]


def classify_revision_kind(instruction: str) -> str:
    text = (instruction or "").lower()
    if any(p.search(text) for p in _DIGIT_CORRECTIONS):
        return DATA_CORRECTION
    return NARRATIVE_EDIT
