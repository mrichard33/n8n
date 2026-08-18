"""§3 date-window tests: the reference assertion, the four DST fixtures, the
year boundary, and the non-Monday guard. US DST 2026: begins Sun 8 Mar, ends
Sun 1 Nov."""
from datetime import date, timedelta

import pytest

from windows import ET, Windows, approval_token, compute_windows, et_abbrev, period_utc_bounds


def test_reference_assertion_2026_08_17():
    """Handoff §3: run this first. Deviation means the date math is wrong."""
    w = compute_windows(date(2026, 8, 17))
    assert w.period_start == date(2026, 8, 9)
    assert w.period_end == date(2026, 8, 15)
    assert w.cohort_set_start == date(2026, 7, 6)
    assert w.cohort_set_end == date(2026, 8, 15)
    assert w.cohort_appt_cutoff == date(2026, 8, 16)
    assert (w.iso_year, w.iso_week) == (2026, 33)
    assert w.prior_period_start == date(2026, 8, 2)
    assert w.prior_period_end == date(2026, 8, 8)


def test_worked_example_2026_08_24():
    """§1 worked example: run Monday 24 Aug -> week Sun 16 .. Sat 22 Aug."""
    w = compute_windows(date(2026, 8, 24))
    assert w.period_start == date(2026, 8, 16)
    assert w.period_end == date(2026, 8, 22)


DST_FIXTURES = [
    # (run date, expected week start, expected week end, note)
    (date(2026, 3, 9), date(2026, 3, 1), date(2026, 3, 7), "last full EST week"),
    (date(2026, 3, 16), date(2026, 3, 8), date(2026, 3, 14), "spring-forward week; Sunday is 23h"),
    (date(2026, 11, 2), date(2026, 10, 25), date(2026, 10, 31), "last full EDT week"),
    (date(2026, 11, 9), date(2026, 11, 1), date(2026, 11, 7), "fall-back week; Sunday is 25h"),
]


@pytest.mark.parametrize("run,start,end,note", DST_FIXTURES)
def test_dst_weeks_are_exactly_seven_calendar_days(run, start, end, note):
    w = compute_windows(run)
    assert w.period_start == start, note
    assert w.period_end == end, note
    assert w.period_start.weekday() == 6 and w.period_end.weekday() == 5
    assert (w.period_end - w.period_start).days == 6  # 7 calendar days inclusive


def test_spring_forward_sunday_is_23_hours_fall_back_is_25():
    """Prove the elapsed-hours trap is real, and that bounds still cover the
    full ET day: the UTC span of the spring-forward Sunday is 23h, fall-back 25h."""
    lo, hi = period_utc_bounds(date(2026, 3, 8), date(2026, 3, 8))
    assert round((hi - lo).total_seconds() / 3600) == 23
    lo, hi = period_utc_bounds(date(2026, 11, 1), date(2026, 11, 1))
    assert round((hi - lo).total_seconds() / 3600) == 25


def test_year_boundary_files_under_period_end_year():
    """Run 2027-01-04 -> week 2026-12-27 .. 2027-01-02. iso_year/iso_week come
    from period_end (2027-01-02 is ISO 2026-W53); deriving from run_date would
    collide the January runs."""
    w = compute_windows(date(2027, 1, 4))
    assert w.period_start == date(2026, 12, 27)
    assert w.period_end == date(2027, 1, 2)
    assert (w.iso_year, w.iso_week) == (2026, 53)
    # The following Monday's run must land in a DIFFERENT (year, week) bucket.
    w2 = compute_windows(date(2027, 1, 11))
    assert (w2.iso_year, w2.iso_week) == (2027, 1)
    assert (w.iso_year, w.iso_week) != (w2.iso_year, w2.iso_week)


def test_month_boundary():
    w = compute_windows(date(2026, 9, 7))
    assert w.period_start == date(2026, 8, 30)
    assert w.period_end == date(2026, 9, 5)


def test_non_monday_raises():
    with pytest.raises(ValueError):
        compute_windows(date(2026, 8, 18))  # a Tuesday
    with pytest.raises(ValueError):
        compute_windows(date(2026, 8, 16))  # a Sunday


def test_et_abbrev_never_hardcoded():
    assert et_abbrev(date(2026, 1, 15)) == "EST"
    assert et_abbrev(date(2026, 7, 15)) == "EDT"
    assert et_abbrev(date(2026, 3, 8)) == "EDT"   # noon on spring-forward day
    assert et_abbrev(date(2026, 11, 1)) == "EST"  # noon on fall-back day


def test_cohort_is_41_inclusive_days_monday_to_saturday():
    """The handoff §3 comment says the cohort starts on a Sunday; the 40-day
    formula, the §3 reference assertion (07-06), and the canonical PDF's own
    subtitle ("set 6 July – 15 August") all say Monday. The formula wins."""
    w = compute_windows(date(2026, 8, 17))
    assert (w.cohort_set_end - w.cohort_set_start).days == 40
    assert w.cohort_set_start.weekday() == 0  # Monday
    assert w.cohort_set_start == date(2026, 7, 6)


def test_approval_token_format():
    assert approval_token(2026, 34, 1) == "LR-2026-W34-V1"
    assert approval_token(2026, 5, 3) == "LR-2026-W5-V3"
