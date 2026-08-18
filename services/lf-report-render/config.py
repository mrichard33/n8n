"""Service configuration. Report-level knobs (goal, thresholds, alpha …)
arrive IN each payload's ConfigBlock — the orchestrator reads lf_report_config
from Supabase and fills them, so a frozen payload replays identically even if
the config table has since changed. Only service-process concerns live here.
"""
from __future__ import annotations

import os

RENDER_TOKEN = (os.environ.get("RENDER_TOKEN") or "").strip()

# Fail-open when unset (the LP-MCP house convention): enforcement turns on by
# setting the variable, no code change. Railway always sets it.
AUTH_ENFORCED = bool(RENDER_TOKEN)
