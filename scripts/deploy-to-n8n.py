#!/usr/bin/env python3
"""
GitOps deploy script — pushes /workflows/*.json to n8n on every merge to main.
Reads N8N_API_KEY and N8N_BASE_URL from environment (set via GitHub Secrets).
All workflows are kept inactive — activation is always manual.
"""

import os
import json
import sys
import requests
from pathlib import Path

N8N_BASE_URL = os.environ.get(
    "N8N_BASE_URL",
    "https://n8n-main-instance-production-981e.up.railway.app"
)
N8N_API_KEY = os.environ["N8N_API_KEY"]

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json"
}


def get_existing_workflows():
    """
    Pull all workflows currently in n8n.
    Returns a dict of { workflow_name: workflow_id }.
    """
    url = f"{N8N_BASE_URL}/api/v1/workflows?limit=250"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    workflows = data.get("data", [])
    result = {wf["name"]: wf["id"] for wf in workflows}
    print(f"Found {len(result)} existing workflows in n8n")
    return result


def deploy_workflow(file_path: Path, existing: dict):
    """
    Deploy a single workflow JSON file to n8n.
    Creates if new, updates if already present.
    Always leaves the workflow inactive.
    """
    with open(file_path, encoding="utf-8") as f:
        workflow = json.load(f)

    # Safety lock — never auto-activate anything
    workflow["active"] = False

    name = workflow.get("name")
    if not name:
        print(f"  SKIP {file_path.name} — no 'name' field in JSON")
        return None

    if name in existing:
        wf_id = existing[name]
        url = f"{N8N_BASE_URL}/api/v1/workflows/{wf_id}"
        response = requests.put(url, headers=HEADERS, json=workflow, timeout=30)
        action = "updated"
    else:
        url = f"{N8N_BASE_URL}/api/v1/workflows"
        response = requests.post(url, headers=HEADERS, json=workflow, timeout=30)
        action = "created"

    if response.status_code in (200, 201):
        result = response.json()
        wf_id = result.get("id", "unknown")
        print(f"  \u2713 {action}: {name} (id: {wf_id})")
        return {"name": name, "id": wf_id, "action": action}
    else:
        print(f"  \u2717 FAILED {name}: HTTP {response.status_code} — {response.text[:200]}")
        return None


def main():
    workflows_dir = Path("workflows")

    if not workflows_dir.exists():
        print("ERROR: /workflows directory not found. Are you running from the repo root?")
        sys.exit(1)

    files = sorted(workflows_dir.glob("*.json"))
    if not files:
        print("No .json files in /workflows — nothing to deploy")
        sys.exit(0)

    print(f"Deploying {len(files)} workflow file(s) to n8n...\n")

    existing = get_existing_workflows()
    print()

    results = []
    errors = []

    for file_path in files:
        try:
            result = deploy_workflow(file_path, existing)
            if result:
                results.append(result)
        except Exception as e:
            print(f"  \u2717 ERROR on {file_path.name}: {e}")
            errors.append(file_path.name)

    print(f"\n{'='*50}")
    print(f"Deployed:  {len(results)}/{len(files)}")
    if errors:
        print(f"Errors:    {len(errors)} — {errors}")
        sys.exit(1)
    else:
        print("All workflows deployed successfully.")


if __name__ == "__main__":
    main()
