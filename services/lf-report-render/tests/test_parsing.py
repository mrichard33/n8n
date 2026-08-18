"""§14 reply-parser table tests — every row of acceptance #6, plus the §20
workflow fixtures around quoting and signatures. The DENY-before-APPROVE
ordering is the single most safety-critical behavior in this build."""
import pytest

from parsing import (
    APPROVED, DATA_CORRECTION, DENY, EDIT, NARRATIVE_EDIT, UNKNOWN,
    classify_reply, classify_revision_kind, clean_reply,
)


# ---------------------------------------------------------------------------
# Acceptance #6 — the required table, row by row
# ---------------------------------------------------------------------------


def test_plain_approved():
    assert classify_reply("Approved").classification == APPROVED


def test_not_approved_is_DENY():
    """THE trap: 'not approved' contains 'approved'. Must classify DENY."""
    r = classify_reply("Not approved — hold this")
    assert r.classification == DENY
    assert "hold this" in (r.reason or "")


def test_deny_with_reason():
    r = classify_reply("deny, Deer numbers look off")
    assert r.classification == DENY
    assert r.reason == "deer numbers look off"


def test_edit_data_correction():
    r = classify_reply("EDIT: Craig had 47 not 49")
    assert r.classification == EDIT
    assert r.revision_kind == DATA_CORRECTION


def test_edit_narrative():
    r = classify_reply("EDIT: soften the Craig paragraph")
    assert r.classification == EDIT
    assert r.revision_kind == NARRATIVE_EDIT


def test_looks_good_is_UNKNOWN():
    """'looks good' must NOT approve — clarification email, stay pending."""
    assert classify_reply("looks good").classification == UNKNOWN


def test_approved_above_quoted_thread_containing_deny():
    raw = "Approved\n\nOn Mon, Aug 18, 2026 Mark Richard wrote:\n> deny this until we check Deer\n> EDIT: numbers"
    assert classify_reply(raw).classification == APPROVED


def test_quoted_old_approved_does_not_approve():
    """A quoted older APPROVED further down the thread must not fire — the
    start-anchor plus quote-stripping defeats it."""
    raw = "What changed in v2?\n\nOn Mon, Aug 17, 2026 Brad Codman wrote:\n> APPROVED"
    assert classify_reply(raw).classification == UNKNOWN


# ---------------------------------------------------------------------------
# Ordering guarantees and edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "Denied", "reject", "hold", "do not send", "don't send", "Do Not Send this week",
    "NOT APPROVED", "not approve",
])
def test_deny_family(raw):
    assert classify_reply(raw).classification == DENY


@pytest.mark.parametrize("raw", ["approve it", "ok to send", "send it", "Approved."])
def test_approve_family(raw):
    assert classify_reply(raw).classification == APPROVED


@pytest.mark.parametrize("raw", [
    "please approve",              # not at start
    "I think this is approved",    # not at start
    "",                            # empty
    "thanks!",
])
def test_unknown_family(raw):
    assert classify_reply(raw).classification == UNKNOWN


def test_signature_stripped():
    raw = "Approved\n-- \nMark Richard\nVP, Reece Windows & Doors"
    r = classify_reply(raw)
    assert r.classification == APPROVED
    assert "vp" not in r.cleaned


def test_cleaning_truncates_at_300():
    assert len(clean_reply("x" * 1000)) == 300


def test_deny_wins_even_when_edit_appears_later_in_text():
    r = classify_reply("hold — then EDIT: fix Deer to 47")
    assert r.classification == DENY


# ---------------------------------------------------------------------------
# Revision-kind classification (§14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("instr", [
    "Craig had 47 appointments, not 49",
    "his cancels should be 3",
    "gross for Walker is actually 130,000",
    "the 38% figure is wrong, it is 31%",
])
def test_data_corrections(instr):
    assert classify_revision_kind(instr) == DATA_CORRECTION


@pytest.mark.parametrize("instr", [
    "make the Craig section less strong",
    "mention he was out Wednesday",
    "soften the tone of the staffing paragraph",
    "do not name the agents in section 3",   # contains 'not' but no digit
])
def test_narrative_edits(instr):
    assert classify_revision_kind(instr) == NARRATIVE_EDIT
