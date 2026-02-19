#!/usr/bin/env python3
"""
generate_k6_script.py
─────────────────────
Calls a locally running Ollama instance (llama3) to generate a k6
performance test script based on the PR title, body, and detected stack.

Environment variables:
  OLLAMA_HOST     – Ollama base URL (default: http://localhost:11434)
  PR_TITLE        – GitHub PR title
  PR_BODY         – GitHub PR body / description
  DETECTED_STACK  – Tech stack detected by the workflow (e.g. "node", "python")

Output:
  tests/k6/performance-test.js

No external dependencies — stdlib only.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error

# ─── Configuration ────────────────────────────────────────────────────────────
OLLAMA_MODEL   = "llama3"
OUTPUT_FILE    = "tests/k6/performance-test.js"

# ─── Fallback script (used when Ollama fails or output is invalid) ────────────
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
    text = text.strip()
    # Remove ```javascript ... ``` or ```js ... ``` or ``` ... ```
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def validate_k6_script(script: str) -> bool:
    """Check that the generated script contains the required k6 constructs."""
    required = ["import http", "export default", "options"]
    missing = [r for r in required if r not in script]
    if missing:
        log(f"⚠️  Validation failed — missing constructs: {missing}")
        return False
    log("✅ Validation passed")
    return True


def call_ollama_chat(host: str, pr_title: str, pr_body: str, stack: str) -> str:
    """
    Call Ollama's OpenAI-compatible /v1/chat/completions endpoint.
    Returns the assistant's message content string.
    """
    url = f"{host.rstrip('/')}/v1/chat/completions"

    user_message = (
        f"Tech stack detected: {stack}\n\n"
        f"PR Title: {pr_title}\n\n"
        f"PR Description:\n{pr_body or '(No description provided)'}\n\n"
        "Based on the above PR information and tech stack, generate a k6 performance test script "
        "that tests the most likely REST API endpoints this PR touches or introduces. "
        "If the PR description does not mention specific endpoints, generate a general health-check "
        "test for GET / and GET /health."
    )

    payload = {
        "model":       OLLAMA_MODEL,
        "temperature": 0.2,
        "stream":      False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    log(f"📡 Calling Ollama ({url}, model: {OLLAMA_MODEL}) ...")
    try:
        # Ollama inference can be slow on CPU — allow up to 10 minutes
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        log(f"❌ Ollama HTTP error {e.code}: {error_body}")
        raise
    except urllib.error.URLError as e:
        log(f"❌ Network error calling Ollama: {e.reason}")
        raise

    data = json.loads(raw)

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        log(f"❌ Unexpected Ollama response structure: {json.dumps(data, indent=2)[:500]}")
        raise ValueError(f"Cannot parse Ollama response: {e}") from e

    usage = data.get("usage", {})
    log(f"✅ Ollama responded — tokens: {usage}")
    return content


def call_ollama_generate(host: str, pr_title: str, pr_body: str, stack: str) -> str:
    """
    Fallback: use Ollama's native /api/generate endpoint if /v1 is not available.
    Returns the generated text string.
    """
    url = f"{host.rstrip('/')}/api/generate"

    prompt = (
        f"<s>[INST] <<SYS>>\n{SYSTEM_PROMPT}\n<</SYS>>\n\n"
        f"Tech stack: {stack}\n"
        f"PR Title: {pr_title}\n"
        f"PR Description: {pr_body or '(none)'}\n"
        "Generate the k6 script now: [/INST]"
    )

    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    log(f"📡 Calling Ollama /api/generate ({url}) ...")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        log(f"❌ Ollama /api/generate also failed: {e}")
        raise

    data = json.loads(raw)
    content = data.get("response", "")
    if not content:
        raise ValueError("Ollama /api/generate returned empty response")

    log(f"✅ Ollama /api/generate responded — eval_count: {data.get('eval_count', '?')}")
    return content


def save_script(script: str, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    log(f"💾 Script saved to {path}")


def main() -> None:
    log("─" * 60)
    log("k6 Script Generator — Ollama llama3 (local)")
    log("─" * 60)

    # ── Read environment variables ──────────────────────────────────
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()
    pr_title    = os.environ.get("PR_TITLE",    "").strip()
    pr_body     = os.environ.get("PR_BODY",     "").strip()
    stack       = os.environ.get("DETECTED_STACK", "unknown").strip()

    log(f"Ollama host   : {ollama_host}")
    log(f"Model         : {OLLAMA_MODEL}")
    log(f"PR Title      : {pr_title or '(empty)'}")
    log(f"Detected Stack: {stack}")
    log(f"PR Body       : {(pr_body[:120] + '...') if len(pr_body) > 120 else pr_body or '(empty)'}")

    # ── Verify Ollama is reachable ──────────────────────────────────
    tags_url = f"{ollama_host.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=10) as r:
            available_models = json.loads(r.read())
            model_names = [m.get("name", "") for m in available_models.get("models", [])]
            log(f"✅ Ollama reachable — available models: {model_names}")
    except Exception as e:
        log(f"⚠️  Cannot reach Ollama at {ollama_host}: {e}")
        log("⚠️  Writing fallback script")
        save_script(FALLBACK_SCRIPT, OUTPUT_FILE)
        return

    # ── Call Ollama — try /v1/chat/completions first, fall back to /api/generate
    generated_script = None
    raw_content = None

    try:
        raw_content = call_ollama_chat(ollama_host, pr_title, pr_body, stack)
    except Exception as exc:
        log(f"⚠️  /v1/chat/completions failed ({exc}) — retrying with /api/generate ...")
        try:
            raw_content = call_ollama_generate(ollama_host, pr_title, pr_body, stack)
        except Exception as exc2:
            log(f"❌ Both Ollama endpoints failed: {exc2}")
            log("⚠️  Writing fallback script")
            save_script(FALLBACK_SCRIPT, OUTPUT_FILE)
            return

    # ── Strip markdown fences ───────────────────────────────────────
    log("🔍 Stripping markdown fences (if any) ...")
    cleaned = strip_markdown_fences(raw_content)
    log(f"Script preview (first 300 chars):\n{cleaned[:300]}\n...")

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
