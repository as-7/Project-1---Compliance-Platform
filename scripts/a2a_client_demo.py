"""Minimal A2A client.

Discovers the Extraction Agent via its agent card, submits a tiny regulatory
text snippet, and polls the task until it completes.

Run inside the running stack with:

    docker compose exec backend python /app/scripts/a2a_client_demo.py

or from the host (after `docker compose up`):

    python scripts/a2a_client_demo.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

DEFAULT_BASE = "http://localhost:8080"
SAMPLE_TEXT = """
Section 4.2 — Data Retention.
The processor shall retain personal data only for as long as necessary to
fulfill the purposes for which it was collected and shall delete or anonymize
such data upon expiry of the retention period. Retention periods must be
documented and reviewed annually.

Section 4.3 — Access Logging.
All access to systems containing personal data shall be logged. Access logs
shall be retained for a minimum of 12 months and reviewed at least quarterly
by the security team.
"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--name", default="A2A demo doc")
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1. Discover.
        card_resp = await client.get(f"{args.base_url}/.well-known/agent.json")
        card_resp.raise_for_status()
        card = card_resp.json()
        print("== Agent card ==")
        print(json.dumps(card, indent=2))
        tasks_url = card["endpoints"]["tasks"]

        # 2. Submit task.
        submit = await client.post(
            tasks_url, json={"document_name": args.name, "text": SAMPLE_TEXT}
        )
        submit.raise_for_status()
        body = submit.json()
        task_id = body["task_id"]
        print(f"\n== Submitted task {task_id} ==")

        # 3. Poll.
        status_url = card["endpoints"]["task_status"].format(task_id=task_id)
        deadline = time.monotonic() + 300
        while True:
            poll = await client.get(status_url)
            poll.raise_for_status()
            state = poll.json()
            print(f"  state={state['state']}", end="\r")
            if state["state"] in {"completed", "failed"}:
                print()
                print(json.dumps(state, indent=2))
                return 0 if state["state"] == "completed" else 1
            if time.monotonic() > deadline:
                print("\nTimed out waiting for completion.")
                return 2
            await asyncio.sleep(2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
