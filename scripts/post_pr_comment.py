#!/usr/bin/env python3
"""
post_pr_comment.py
──────────────────
Parses k6 results and posts a formatted markdown comment to the GitHub PR.

Environment variables required:
  GITHUB_TOKEN        – GitHub token (automatic in Actions)
  PR_NUMBER           – Pull request number
  REPO                – Repository in "owner/repo" format
  K6_EXIT_CODE        – Exit code from the k6 run step
  SCRIPT_WAS_GENERATED – "true" if Groq generated the script, "false" if reused
  DETECTED_STACK      – Tech stack string (e.g. "node", "python")
"""

import json
import os
import sys
import urllib.request
import urllib.error

# ─── File paths ───────────────────────────────────────────────────────────────
SUMMARY_FILE = "k6-results/summary.json"
OUTPUT_FILE  = "k6-results/output.txt"
OUTPUT_LINES = 40  # how many tail lines to include in the <details> block

# ─── Threshold definitions (mirrored from the k6 script) ─────────────────────
THRESHOLDS = {
    "http_req_duration_p95": {"label": "P95 Response Time", "limit": 500,  "unit": "ms",  "lower_is_better": True},
    "http_req_failed_rate":  {"label": "Error Rate",        "limit": 1.0,  "unit": "%",   "lower_is_better": True},
}


def log(msg: str) -> None:
    print(f"[post_pr_comment] {msg}", flush=True)


def fmt_ms(value: float) -> str:
    return f"{value:.2f} ms"


def fmt_percent(value: float) -> str:
    return f"{value:.4f}%"


def status_icon(passed: bool) -> str:
    return "✅" if passed else "❌"


def read_summary(path: str) -> dict:
    """Read and return k6 summary JSON, or an empty dict on error."""
    if not os.path.exists(path):
        log(f"⚠️  Summary file not found: {path}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log(f"⚠️  Failed to parse summary JSON: {e}")
        return {}


def read_tail(path: str, lines: int) -> str:
    """Return the last `lines` lines of a text file."""
    if not os.path.exists(path):
        return "(k6 output file not found)"
    try:
        with open(path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except OSError as e:
        return f"(error reading output: {e})"


def extract_metrics(summary: dict) -> dict:
    """Pull the relevant metrics out of the k6 summary JSON structure."""
    metrics = {
        "http_req_duration_avg":  None,
        "http_req_duration_min":  None,
        "http_req_duration_max":  None,
        "http_req_duration_p95":  None,
        "http_req_duration_p99":  None,
        "http_req_failed_rate":   None,
        "http_reqs_rate":         None,
        "http_reqs_count":        None,
        "vus_max":                None,
    }

    if not summary:
        return metrics

    # http_req_duration
    dur = summary.get("metrics", {}).get("http_req_duration", {}).get("values", {})
    if dur:
        metrics["http_req_duration_avg"] = dur.get("avg")
        metrics["http_req_duration_min"] = dur.get("min")
        metrics["http_req_duration_max"] = dur.get("max")
        metrics["http_req_duration_p95"] = dur.get("p(95)")
        metrics["http_req_duration_p99"] = dur.get("p(99)")

    # http_req_failed
    failed = summary.get("metrics", {}).get("http_req_failed", {}).get("values", {})
    if failed:
        # k6 reports as a decimal fraction (0.0 – 1.0) — convert to %
        raw_rate = failed.get("rate", 0.0)
        metrics["http_req_failed_rate"] = raw_rate * 100

    # http_reqs
    reqs = summary.get("metrics", {}).get("http_reqs", {}).get("values", {})
    if reqs:
        metrics["http_reqs_rate"]  = reqs.get("rate")
        metrics["http_reqs_count"] = reqs.get("count")

    # vus_max
    vus = summary.get("metrics", {}).get("vus_max", {}).get("values", {})
    if vus:
        metrics["vus_max"] = vus.get("max")

    return metrics


def check_thresholds(metrics: dict) -> dict[str, bool]:
    """Return a dict of threshold_key → passed (bool)."""
    results = {}
    for key, cfg in THRESHOLDS.items():
        value = metrics.get(key)
        if value is None:
            results[key] = False
            continue
        if cfg["lower_is_better"]:
            results[key] = value < cfg["limit"]
        else:
            results[key] = value > cfg["limit"]
    return results


def build_comment(
    metrics: dict,
    threshold_results: dict,
    k6_exit_code: str,
    script_was_generated: bool,
    detected_stack: str,
    k6_output_tail: str,
) -> str:
    """Assemble the full markdown comment."""

    all_passed = all(threshold_results.values()) and k6_exit_code == "0"
    overall_icon = "✅" if all_passed else "❌"
    overall_label = "All thresholds passed" if all_passed else "One or more thresholds FAILED"

    # ── Script origin note ────────────────────────────────────────────
    if script_was_generated:
        script_note = (
            f"> 🤖 **AI-generated k6 script** — created by Groq Llama3 for "
            f"the `{detected_stack}` stack and committed back to this PR branch. "
            f"It will be reused on future pushes."
        )
    else:
        script_note = (
            "> 📄 **Existing k6 script** reused from `tests/k6/performance-test.js`."
        )

    # ── Helpers ────────────────────────────────────────────────────────
    def row(metric, value_str, threshold_str, passed):
        icon = status_icon(passed) if passed is not None else "ℹ️"
        return f"| {metric} | {value_str} | {threshold_str} | {icon} |"

    def na(v, fmt_fn):
        return fmt_fn(v) if v is not None else "N/A"

    # ── Metrics table ─────────────────────────────────────────────────
    p95  = metrics.get("http_req_duration_p95")
    p99  = metrics.get("http_req_duration_p99")
    avg  = metrics.get("http_req_duration_avg")
    mn   = metrics.get("http_req_duration_min")
    mx   = metrics.get("http_req_duration_max")
    err  = metrics.get("http_req_failed_rate")
    rps  = metrics.get("http_reqs_rate")
    tot  = metrics.get("http_reqs_count")
    vus  = metrics.get("vus_max")

    p95_pass = threshold_results.get("http_req_duration_p95")
    err_pass = threshold_results.get("http_req_failed_rate")

    table_rows = [
        row("P95 Response Time",  na(p95, fmt_ms),      "< 500 ms",  p95_pass),
        row("P99 Response Time",  na(p99, fmt_ms),      "—",         None),
        row("Avg Response Time",  na(avg, fmt_ms),      "—",         None),
        row("Min Response Time",  na(mn,  fmt_ms),      "—",         None),
        row("Max Response Time",  na(mx,  fmt_ms),      "—",         None),
        row("Error Rate",         na(err, fmt_percent), "< 1%",      err_pass),
        row("Throughput (RPS)",   f"{rps:.2f} req/s" if rps is not None else "N/A", "—", None),
        row("Total Requests",     str(int(tot)) if tot is not None else "N/A",     "—", None),
        row("Max VUs",            str(int(vus)) if vus is not None else "N/A",     "—", None),
    ]

    table = "\n".join([
        "| Metric | Value | Threshold | Status |",
        "|--------|-------|-----------|--------|",
    ] + table_rows)

    # ── Verdict / merge advice ────────────────────────────────────────
    if all_passed:
        verdict = (
            "**✅ All performance thresholds passed.** "
            "This PR meets the required performance standards and is safe to merge."
        )
    else:
        verdict = (
            "**❌ Performance thresholds FAILED.** "
            "Please investigate the issues above before merging. "
            "Check the k6 output details below and the `k6-results` artifact for the raw data."
        )

    # ── Full comment ──────────────────────────────────────────────────
    comment = f"""\
## {overall_icon} k6 Performance Test Results

{script_note}

### 📊 Metrics

{table}

### 🏁 Verdict

{verdict}

<details>
<summary>📋 k6 Output (last {OUTPUT_LINES} lines)</summary>

```
{k6_output_tail.strip()}
```

</details>

---
*Powered by [k6](https://k6.io) + [Groq Llama3](https://console.groq.com) · Stack detected: `{detected_stack}`*
"""
    return comment.strip()


def post_comment(token: str, repo: str, pr_number: str, body: str) -> None:
    """POST the comment to the GitHub API."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
            "Content-Type":  "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    log(f"📡 POSTing comment to {url} ...")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            log(f"✅ Comment posted (HTTP {status})")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        log(f"❌ GitHub API error {e.code}: {err_body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        log(f"❌ Network error: {e.reason}")
        sys.exit(1)


def main() -> None:
    log("─" * 60)
    log("k6 PR Comment Poster")
    log("─" * 60)

    # ── Read environment variables ──────────────────────────────────
    token       = os.environ.get("GITHUB_TOKEN",        "").strip()
    pr_number   = os.environ.get("PR_NUMBER",           "").strip()
    repo        = os.environ.get("REPO",                "").strip()
    k6_exit_code= os.environ.get("K6_EXIT_CODE",        "1").strip()
    was_gen_raw = os.environ.get("SCRIPT_WAS_GENERATED","false").strip().lower()
    stack       = os.environ.get("DETECTED_STACK",      "unknown").strip()

    script_was_generated = was_gen_raw == "true"

    log(f"Repo        : {repo}")
    log(f"PR Number   : {pr_number}")
    log(f"k6 Exit Code: {k6_exit_code}")
    log(f"Stack       : {stack}")
    log(f"Generated   : {script_was_generated}")

    if not token:
        log("❌ GITHUB_TOKEN is not set — cannot post comment")
        sys.exit(1)
    if not pr_number or not repo:
        log("❌ PR_NUMBER or REPO is not set — cannot post comment")
        sys.exit(1)

    # ── Parse results ───────────────────────────────────────────────
    summary          = read_summary(SUMMARY_FILE)
    metrics          = extract_metrics(summary)
    threshold_results= check_thresholds(metrics)
    k6_output_tail   = read_tail(OUTPUT_FILE, OUTPUT_LINES)

    log(f"Metrics extracted: {metrics}")
    log(f"Threshold results: {threshold_results}")

    # ── Build comment ───────────────────────────────────────────────
    comment_body = build_comment(
        metrics=metrics,
        threshold_results=threshold_results,
        k6_exit_code=k6_exit_code,
        script_was_generated=script_was_generated,
        detected_stack=stack,
        k6_output_tail=k6_output_tail,
    )

    log("Comment preview (first 500 chars):")
    log(comment_body[:500])

    # ── Post to GitHub ──────────────────────────────────────────────
    post_comment(token, repo, pr_number, comment_body)
    log("✅ Done")


if __name__ == "__main__":
    main()
