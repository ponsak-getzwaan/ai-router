"""End-to-end test of the test console: seed history then classify a follow-up.

Usage:
    uv run python scripts/e2e_test_console.py
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time

import httpx

CF_BASE = "https://d3b8sahdoudt7a.cloudfront.net"
POOL_ID = "ap-southeast-1_ZuJthaSmR"
CLIENT_ID = "4f2pc9a6tfruil1rqsouk7q9gd"
USERNAME = "test-ci@ai-router.internal"
PASSWORD = "TmpTestPass123!"
REGION = "ap-southeast-1"


def _get_token() -> str:
    result = subprocess.run(
        [
            "aws", "cognito-idp", "initiate-auth",
            "--auth-flow", "USER_PASSWORD_AUTH",
            "--client-id", CLIENT_ID,
            "--auth-parameters", f"USERNAME={USERNAME},PASSWORD={PASSWORD}",
            "--region", REGION,
            "--query", "AuthenticationResult.AccessToken",
            "--output", "text",
        ],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


async def call_console(
    token: str,
    session_id: str,
    message: str,
) -> dict | None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "user_sub": "test-ci",
        "session_id": session_id,
        "message": message,
    }
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=70.0, verify=False) as client:
        resp = await client.post(f"{CF_BASE}/admin/api/test-console", headers=headers, json=body)
    elapsed = time.monotonic() - t0

    print(f"\n--- '{message}' [{elapsed:.1f}s] HTTP {resp.status_code} ---")
    if resp.status_code != 200:
        print(resp.text[:400])
        return None

    data = resp.json()
    for layer in data.get("layers", []):
        print(f"  {layer['layer']:12s}  {json.dumps(layer['outcome'])}")
    print(f"  total={data['total_latency_ms']}ms  vendor={data['final_vendor']}")
    return data


async def main() -> None:
    session_id = f"e2e-test-{int(time.time())}"
    print(f"session_id={session_id}")

    token = _get_token()
    print("Token obtained.")

    # Step 1 — seed history
    r1 = await call_console(token, session_id, "what is BMW e30?")
    if not r1:
        print("ABORT: call 1 failed")
        return

    clf1 = next((l for l in r1["layers"] if l["layer"] == "classifier"), None)
    if not clf1:
        print("ABORT: no classifier layer in call 1")
        return
    print(f"\nCall 1 intent={clf1['outcome']['intent']}. Waiting 5s before follow-up...\n")
    await asyncio.sleep(5)

    # Step 2 — follow-up: must classify as general_qa without escalation
    r2 = await call_console(token, session_id, "what makes it different from e93?")
    if not r2:
        print("FAIL: call 2 returned error")
        return

    clf = next((l for l in r2["layers"] if l["layer"] == "classifier"), None)
    if not clf:
        print("FAIL: no classifier layer in response")
        return

    o = clf["outcome"]
    passed = o["intent"] == "general_qa" and not o["escalate"]
    print(f"\n{'PASS' if passed else 'FAIL'}")
    print(f"  intent={o['intent']}  confidence={o['confidence']}  escalate={o['escalate']}")


if __name__ == "__main__":
    asyncio.run(main())
