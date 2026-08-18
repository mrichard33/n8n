"""Date-window computation for the Lightfire weekly report.

Every boundary in this system is a CALENDAR DATE in America/New_York (D9).
Compute calendar dates in ET first; derive UTC instants only at the edge where
a query needs timestamps (period_utc_bounds). Never subtract hours to move
between days — on the spring-forward Sunday a day is 23 hours long and on the
fall-back Sunday it is 25, so elapsed-hours arithmetic silently shifts the
window twice a year. Calendar-date arithmetic does not.

Reference assertion (Handoff V2 §3 — run before building anything else):
    compute_windows(date(2026, 8, 17)) ->
        period       2026-08-09 .. 2026-08-15
        cohort_set   2026-07-06 .. 2026-08-15
        appt_cutoff  2026-08-16
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_MONDAY, _SATURDAY, _SUNDAY = 0, 5, 6  # date.weekday() numbering

# Matured cohort: period_end - 40, i.e. 41 calendar days inclusive ending on
# the reporting Saturday. NOTE: the handoff's §3 comment calls the start "a
# Sunday"; it is a MONDAY (reference week: Mon 6 July -> Sat 15 Aug). The
# 40-day subtraction is the authoritative definition — it is what the §3
# reference assertion demands, what the canonical PDF's subtitle states
# ("set 6 July – 15 August 2026"), and what reproduced the golden cohort
# exactly against live lp_leads. Do not "fix" this to a Sunday.
_COHORT_SPAN_DAYS = 40


@dataclass(frozen=True)
class Windows:
    run_date: date            # the Monday the workflow runs, ET
    period_start: date        # prior Sunday      (reporting week start)
    period_end: date          # prior Saturday    (reporting week end)
    prior_period_start: date  # the Sunday before that
    prior_period_end: date    # the Saturday before that
    cohort_set_start: date    # Monday, period_end - 40 (see _COHORT_SPAN_DAYS note)
    cohort_set_end: date      # == period_end
    cohort_appt_cutoff: date  # run_date - 1 (the Sunday between period_end and run_date)
    iso_year: int             # derived from period_end, NOT run_date (year boundary)
    iso_week: int


def compute_windows(run_date: date) -> Windows:
    """Windows for a Monday run. Raises ValueError on a non-Monday run_date —
    a schedule misfire must fail loudly, not report a skewed week."""
    if run_date.weekday() != _MONDAY:
        raise ValueError(f"run_date must be a Monday in ET, got {run_date} ({run_date:%A})")

    period_end = run_date - timedelta(days=2)
    period_start = run_date - timedelta(days=8)
    cohort_set_end = period_end
    cohort_set_start = period_end - timedelta(days=_COHORT_SPAN_DAYS)
    cohort_appt_cutoff = run_date - timedelta(days=1)

    # iso_year/iso_week from period_end: a January run reporting the last week
    # of December must file under the OLD year's week or two runs collide.
    iso_year, iso_week, _ = period_end.isocalendar()

    w = Windows(
        run_date=run_date,
        period_start=period_start,
        period_end=period_end,
        prior_period_start=period_start - timedelta(days=7),
        prior_period_end=period_end - timedelta(days=7),
        cohort_set_start=cohort_set_start,
        cohort_set_end=cohort_set_end,
        cohort_appt_cutoff=cohort_appt_cutoff,
        iso_year=iso_year,
        iso_week=iso_week,
    )

    # Structural invariants (validation gate #1 asserts these again server-side).
    assert w.period_start.weekday() == _SUNDAY
    assert w.period_end.weekday() == _SATURDAY
    assert (w.period_end - w.period_start).days == 6  # Sunday..Saturday inclusive = 7 calendar days
    assert w.cohort_set_start.weekday() == _MONDAY  # see _COHORT_SPAN_DAYS note
    assert w.cohort_appt_cutoff.weekday() == _SUNDAY
    return w


def et_abbrev(d: date) -> str:
    """'EST' or 'EDT' for a calendar date, derived from the zone — never
    hardcoded (D9). Sampled at noon so the DST-transition days themselves
    report the abbreviation in force for business hours."""
    return datetime.combine(d, time(12, 0), tzinfo=ET).tzname()


def period_utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """UTC instants for [start 00:00:00 ET, end 23:59:59.999999 ET].
    Only for queries that must compare timestamps; date-typed comparisons
    should convert the column instead: (col AT TIME ZONE 'America/New_York')::date."""
    lo = datetime.combine(start, time.min, tzinfo=ET).astimezone(timezone.utc)
    hi = datetime.combine(end, time.max, tzinfo=ET).astimezone(timezone.utc)
    return lo, hi


def approval_token(iso_year: int, iso_week: int, version_no: int) -> str:
    """e.g. LR-2026-W34-V1 — stable id carried in the approval email subject."""
    return f"LR-{iso_year}-W{iso_week}-V{version_no}"
