#!/usr/bin/env python3
"""
GitOps deploy script — pushes CHANGED /workflows/*.json to n8n.

Reads N8N_API_KEY and N8N_BASE_URL from environment (set via GitHub Secrets).

WHY THIS IS SCOPED TO CHANGED FILES
-----------------------------------
This script has never successfully deployed. Every run since it was added
(2026-06-22, 27 runs) failed with `401 Unauthorized` because the N8N_API_KEY
secret is empty — it dies in get_existing_workflows() before writing anything.

The consequence is that /workflows has drifted from the live instance for two
months and is NOT a trustworthy mirror of production. Verified 2026-08-11:
live I.LPRA has no CSV branch and a subject-scoped Gmail trigger, while the
repo copy has a CSV branch and a broad trigger. Other files are likely stale
too, in ways nobody has audited.

So the moment someone sets a working API key, the OLD behaviour of this script
— iterate every workflows/*.json, match by name, PUT the whole definition —
would overwrite ~78 live workflows with stale definitions in one merge. It also
forced `active = False` on every one of them, which would have taken the entire
automation estate offline.

Two rules follow, and both are load-bearing:

  1. Deploy only the files the triggering commit actually changed. A commit that
     touches one workflow must never rewrite the other 77.
  2. Never change activation state on UPDATE. Activation is live state that this
     repo does not model; a stale `active` field must not be able to switch a
     running workflow off. New workflows are still created inactive, which was
     the original safety intent.

Deploying everything is still possible, but it is now an explicit, deliberate
opt-in (DEPLOY_ALL=1) rather than the default. Do not use it until /workflows
has been reconciled against live per-workflow.
"""

import os
import json
import sys
import subprocess
import requests
from pathlib import Path

N8N_BASE_URL = os.environ.get(
    "N8N_BASE_URL",
    "https://n8n-main-instance-production-981e.up.railway.app"
).rstrip("/")

N8N_API_KEY = os.environ.get("N8N_API_KEY", "").strip()

DRY_RUN = os.environ.get("DEPLOY_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
DEPLOY_ALL = os.environ.get("DEPLOY_ALL", "").strip().lower() in ("1", "true", "yes")

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json",
}

# The only fields the n8n public API accepts on create/update. Sending anything
# else (id, active, tags, versionId, meta, ...) risks a 400 and, in the case of
# `active`, risks silently deactivating a running workflow.
WRITABLE_FIELDS = ("name", "nodes", "connections", "settings", "staticData")

WORKFLOWS_DIR = Path("workflows")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def changed_workflow_files() -> list[Path]:
    """
    The workflow files this deploy is allowed to touch.

    DEPLOY_FILES (newline- or space-separated) wins when set — the Action
    computes it from the push range. Otherwise fall back to diffing against the
    previous commit, which covers a local run. DEPLOY_ALL=1 opts in to the whole
    directory and is deliberately awkward to reach.
    """
    if DEPLOY_ALL:
        files = sorted(WORKFLOWS_DIR.glob("*.json"))
        print(f"DEPLOY_ALL=1 — deploying all {len(files)} workflow file(s).")
        print("  This overwrites live definitions with repo state. /workflows has")
        print("  NOT been reconciled against live; expect drift. See module docstring.")
        return files

    declared = os.environ.get("DEPLOY_FILES")

    # Unset and empty are different. The Action always sets DEPLOY_FILES, so an
    # empty value is a positive statement that this push changed no workflow
    # files — it must deploy nothing. Only a genuinely absent variable (a local
    # run) may fall back to guessing from git history.
    if declared is not None:
        raw = declared.replace("\n", " ").split()
        if not raw:
            print("DEPLOY_FILES is set but empty — no workflow files changed.")
            return []
    else:
        raw = []
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD", "--", "workflows/"],
                capture_output=True, text=True, check=True,
            ).stdout
            raw = out.split()
            print("DEPLOY_FILES unset — diffed HEAD~1..HEAD instead.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            fail(
                f"could not determine changed files ({e}). Set DEPLOY_FILES to a "
                "list of workflow paths, or DEPLOY_ALL=1 to deploy everything."
            )

    files = []
    for name in raw:
        path = Path(name)
        if path.suffix != ".json" or path.parent != WORKFLOWS_DIR:
            continue
        if not path.exists():
            # Deleted in this commit. This script never deletes from n8n —
            # removing a workflow is a manual, deliberate act.
            print(f"  SKIP {path.name} — deleted in this commit; not removing from n8n")
            continue
        files.append(path)

    return sorted(set(files))


def get_existing_workflows() -> dict:
    """Map of { workflow_name: workflow_id } for everything currently in n8n."""
    url = f"{N8N_BASE_URL}/api/v1/workflows?limit=250"
    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code == 401:
        fail(
            "401 Unauthorized from the n8n API — the N8N_API_KEY secret is missing, "
            "empty, or expired. Every run of this workflow since 2026-06-22 has failed "
            "here. Set a valid key in GitHub repo secrets before re-running."
        )

    response.raise_for_status()
    workflows = response.json().get("data", [])
    result = {wf["name"]: wf["id"] for wf in workflows}
    print(f"Found {len(result)} existing workflows in n8n")
    return result


def deploy_workflow(file_path: Path, existing: dict):
    """
    Create or update one workflow.

    On update, activation state is left exactly as it is live — `active` is not
    sent at all. On create, the workflow is created inactive and a human turns
    it on.
    """
    with open(file_path, encoding="utf-8") as f:
        workflow = json.load(f)

    name = workflow.get("name")
    if not name:
        print(f"  SKIP {file_path.name} — no 'name' field in JSON")
        return None

    payload = {k: workflow[k] for k in WRITABLE_FIELDS if k in workflow}

    if name in existing:
        wf_id = existing[name]
        url = f"{N8N_BASE_URL}/api/v1/workflows/{wf_id}"
        action = "updated"
        verb = requests.put
    else:
        wf_id = None
        url = f"{N8N_BASE_URL}/api/v1/workflows"
        action = "created"
        verb = requests.post
        # Safety lock, on new workflows only — activation is always manual.
        payload["active"] = False

    if DRY_RUN:
        print(f"  [dry-run] would {action[:-1]}: {name}"
              + (f" (id: {wf_id})" if wf_id else " (new)"))
        return {"name": name, "id": wf_id, "action": f"{action} (dry-run)"}

    response = verb(url, headers=HEADERS, json=payload, timeout=30)

    if response.status_code in (200, 201):
        result = response.json()
        wf_id = result.get("id", wf_id or "unknown")
        print(f"  ✓ {action}: {name} (id: {wf_id})")
        return {"name": name, "id": wf_id, "action": action}

    print(f"  ✗ FAILED {name}: HTTP {response.status_code} — {response.text[:200]}")
    return None


def main():
    if not WORKFLOWS_DIR.exists():
        fail("/workflows directory not found. Are you running from the repo root?")

    if not N8N_API_KEY and not DRY_RUN:
        fail(
            "N8N_API_KEY is unset or empty. Set it in GitHub repo secrets, or run "
            "with DEPLOY_DRY_RUN=1 to plan without credentials."
        )

    files = changed_workflow_files()
    if not files:
        print("No changed workflow files to deploy — nothing to do.")
        sys.exit(0)

    mode = "DRY RUN — no writes" if DRY_RUN else "LIVE"
    print(f"Deploying {len(files)} workflow file(s) to n8n [{mode}]...\n")
    for f in files:
        print(f"  · {f.name}")
    print()

    existing = {} if (DRY_RUN and not N8N_API_KEY) else get_existing_workflows()
    print()

    results, errors = [], []
    for file_path in files:
        try:
            result = deploy_workflow(file_path, existing)
            if result:
                results.append(result)
            else:
                errors.append(file_path.name)
        except Exception as e:
            print(f"  ✗ ERROR on {file_path.name}: {e}")
            errors.append(file_path.name)

    print(f"\n{'='*50}")
    print(f"Deployed:  {len(results)}/{len(files)}")
    if errors:
        print(f"Errors:    {len(errors)} — {errors}")
        sys.exit(1)
    print("All workflows deployed successfully."
          if not DRY_RUN else "Dry run complete — no changes were written.")


if __name__ == "__main__":
    main()
