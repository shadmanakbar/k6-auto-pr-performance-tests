#!/usr/bin/env python3
"""
generate_k6_script.py
─────────────────────
Calls the Groq API (llama3-70b-8192) to generate a k6 performance test
script based on the PR title, body, and detected tech stack.

Environment variables required:
  GROQ_API_KEY    – Groq API key (from repository secret)
  PR_TITLE        – GitHub PR title
  PR_BODY         – GitHub PR body / description
  DETECTED_STACK  – Tech stack detected by the workflow (e.g. "node", "python")

Output:
  tests/k6/performance-test.js
"""

import json
import os
import sys
import urllib.request
import urllib.error
import re

# ─── Configuration ────────────────────────────────────────────────────────────
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama3-70b-8192"
OUTPUT_FILE   = "tests/k6/performance-test.js"

# ─── Fallback script (used when Groq fails or output is invalid) ─────────────
FALLBACK_SCRIPT = """\
import http from 'k6/http';
import { check, group, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '10s', target: 10 },  // ramp-up
    { duration: '20s', target: 10 },  // hold
    { duration: '5s',  target: 0  },  // ramp-down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500'],
    'http_req_failed':   ['rate<0.01'],
  },
};

const BASE_URL = 'http://localhost:8080';
const TOKEN    = __ENV.API_TOKEN || 'test-token';

const PARAMS = {
  headers: {
    'Authorization': `Bearer ${TOKEN}`,
    'Content-Type':  'application/json',
  },
};

export default function () {
  group('Health check', () => {
    const res = http.get(`${BASE_URL}/`, PARAMS);
    check(res, {
      'status is 2xx': (r) => r.status >= 200 && r.status < 300,
      'response time < 500ms': (r) => r.timings.duration < 500,
    });
  });

  group('Health endpoint', () => {
    const res = http.get(`${BASE_URL}/health`, PARAMS);
    check(res, {
      'status is 2xx': (r) => r.status >= 200 && r.status < 300,
      'response time < 500ms': (r) => r.timings.duration < 500,
    });
  });

  sleep(1);
}
"""

SYSTEM_PROMPT = """\
You are an expert k6 performance test engineer. Generate a production-quality k6 test script.

STRICT RULES — follow every rule exactly:
1. Output ONLY raw JavaScript. No markdown code fences, no triple backticks, no explanation text.
2. Target base URL: http://localhost:8080
3. Use these exact stages:
     stages: [
       { duration: '10s', target: 10 },
       { duration: '20s', target: 10 },
       { duration: '5s',  target: 0  },
     ]
4. Use these exact thresholds:
     thresholds: {
       'http_req_duration': ['p(95)<500'],
       'http_req_failed':   ['rate<0.01'],
     }
5. Import http from 'k6/http'
6. Import { check, group, sleep } from 'k6'
7. Use: const TOKEN = __ENV.API_TOKEN || 'test-token';
8. Set Authorization: Bearer ${TOKEN} header on all requests.
9. Wrap each endpoint in a group() call.
10. Add check() for status code (2xx) and response time (< 500ms) in every group.
11. Call sleep(1) at the end of the default function.
12. Use realistic fake data for POST/PUT request bodies inferred from endpoint names.
13. If no specific endpoints can be inferred from the PR info, test GET / and GET /health.
14. Export named options object and default function.
"""


def log(msg: str) -> None:
    print(f"[generate_k6_script] {msg}", flush=True)


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences that the model may add despite instructions."""
    # Remove ```javascript ... ``` or ```js ... ``` or ``` ... ```
    text = re.sub(r"^```[a-zA-Z]*\n", "", text.strip())
    text = re.sub(r"\n```\s*$", "", text)
    text = text.strip()
    return text


def validate_k6_script(script: str) -> bool:
    """Check that the generated script contains the required k6 constructs."""
    required = ["import http", "export default", "options"]
    missing = [r for r in required if r not in script]
    if missing:
        log(f"⚠️  Validation failed — missing constructs: {missing}")
        return False
    log("✅ Validation passed")
    return True


def call_groq_api(api_key: str, pr_title: str, pr_body: str, stack: str) -> str:
    """Call Groq API and return the raw response text."""
    user_message = f"""
Tech stack detected: {stack}

PR Title: {pr_title}

PR Description:
{pr_body or '(No description provided)'}

Based on the above PR information and tech stack, generate a k6 performance test script
that tests the most likely REST API endpoints this PR touches or introduces.
If the PR description does not mention specific endpoints, generate a general health-check
test for GET / and GET /health.
""".strip()

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.2,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROQ_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    log(f"📡 Calling Groq API (model: {GROQ_MODEL}) ...")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        log(f"❌ Groq API HTTP error {e.code}: {error_body}")
        raise
    except urllib.error.URLError as e:
        log(f"❌ Network error calling Groq API: {e.reason}")
        raise

    data = json.loads(raw)

    # Parse the assistant message content
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        log(f"❌ Unexpected Groq API response structure: {data}")
        raise ValueError(f"Cannot parse Groq response: {e}") from e

    usage = data.get("usage", {})
    log(f"✅ Groq API responded — tokens used: {usage}")

    return content


def save_script(script: str, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    log(f"💾 Script saved to {path}")


def main() -> None:
    log("─" * 60)
    log("k6 Script Generator — Groq Llama3")
    log("─" * 60)

    # ── Read environment variables ──────────────────────────────────
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    pr_title = os.environ.get("PR_TITLE", "").strip()
    pr_body  = os.environ.get("PR_BODY",  "").strip()
    stack    = os.environ.get("DETECTED_STACK", "unknown").strip()

    log(f"PR Title      : {pr_title or '(empty)'}")
    log(f"Detected Stack: {stack}")
    log(f"PR Body       : {(pr_body[:120] + '...') if len(pr_body) > 120 else pr_body or '(empty)'}")

    if not api_key:
        log("⚠️  GROQ_API_KEY is not set — writing fallback script")
        save_script(FALLBACK_SCRIPT, OUTPUT_FILE)
        log("✅ Done (fallback)")
        return

    # ── Call Groq API ───────────────────────────────────────────────
    generated_script = None
    try:
        raw_content = call_groq_api(api_key, pr_title, pr_body, stack)
        log("🔍 Stripping markdown fences (if any) ...")
        cleaned = strip_markdown_fences(raw_content)
        log(f"Script preview (first 300 chars):\n{cleaned[:300]}\n...")
    except Exception as exc:
        log(f"❌ Groq API call failed: {exc}")
        log("⚠️  Falling back to default health-check script")
        save_script(FALLBACK_SCRIPT, OUTPUT_FILE)
        return

    # ── Validate ────────────────────────────────────────────────────
    if validate_k6_script(cleaned):
        generated_script = cleaned
    else:
        log("⚠️  Generated script failed validation — using fallback")
        generated_script = FALLBACK_SCRIPT

    # ── Save ────────────────────────────────────────────────────────
    save_script(generated_script, OUTPUT_FILE)
    log("✅ Done")


if __name__ == "__main__":
    main()
