# 🚀 Automated k6 Performance Testing (Official MCP)

This repository provides a **fully automated performance testing solution** for GitHub Pull Requests, powered by the **Official [Grafana mcp-k6 server](https://github.com/grafana/mcp-k6)**. 

### 🧠 How it works
1. **Detects** your stack (Node, Java, Python, Go, Ruby).
2. **Starts** your app in the background.
3. **Generates** or reuses k6 scripts using local Ollama (llama3).
4. **Validates & Executes** tests via the `mcp-k6` server's tools (`validate_script`, `run_script`).
5. **Report** metrics (P95, RPS, Error Rate) back to the PR comment.

### 🌟 Key Features
- **Official Tools**: Uses the same logic as Grafana's internal performance testing experiments.
- **Zero Config**: Drop the files into your repo and everything just works.
- **AI-Native**: Built to work with modern AI agents and MCP-enabled environments.


---

## How It Works

```
PR opened / pushed
       │
       ▼
┌─────────────────────┐
│ Detect tech stack   │  pom.xml → java-maven
│ (file-based)        │  build.gradle → java-gradle
└─────────┬───────────┘  package.json → node
          │              requirements.txt / pyproject.toml → python
          ▼              go.mod → go   │   Gemfile → ruby
┌─────────────────────┐
│ Set up runtime +    │
│ build the project   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  scripts/start.sh   │  ← YOU configure this once
│  (starts your app)  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Health check poll  │  /actuator/health → /health → /
│  every 2s, 90s max  │  First 2xx wins
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐    exists?
│ tests/k6/           │───────────────────┐
│ performance-test.js │                   │ YES → reuse
└─────────┬───────────┘                   │
          │ NO                            │
          ▼                              │
┌─────────────────────┐                  │
│ Groq Llama3 AI      │                  │
│ generates k6 script │                  │
│ committed to PR     │                  │
└─────────┬───────────┘                  │
          └──────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │  k6 run                │
          │  10 VUs · 30s · ramp   │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │  Post PR comment with  │
          │  metrics table         │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │  Upload k6-results/    │
          │  artifact (30 days)    │
          └────────────┬───────────┘
                       │
                       ▼
          Pass ✅ or Fail ❌ CI check
```

---

## Quick Setup

### Step 1 — Get a free Groq API key

1. Go to **[console.groq.com](https://console.groq.com)** and sign up (free tier available).
2. Navigate to **API Keys** → **Create API Key**.
3. Copy the key — you will not see it again.

> The Groq API is used to auto-generate a k6 script from the PR description when no script exists yet. If `tests/k6/performance-test.js` already exists in your repo, Groq is never called.

---

### Step 2 — Add the secret to GitHub

1. Open your repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret**.
4. Name: `GROQ_API_KEY`  
   Value: the key you copied above.
5. Click **Add secret**.

> **`GITHUB_TOKEN`** is provided automatically by GitHub Actions — no setup required.

---

### Step 3 — Copy the files into your repo

Copy these four files at the exact paths shown:

```
your-repo/
├── .github/
│   └── workflows/
│       └── k6-performance-test.yml   ← GitHub Actions workflow
├── scripts/
│   ├── generate_k6_script.py         ← AI script generator (stdlib only)
│   ├── post_pr_comment.py            ← PR comment poster (stdlib only)
│   └── start.sh                      ← YOU edit this
└── README.md
```

---

### Step 4 — Edit `scripts/start.sh`

Open `scripts/start.sh` and **uncomment the one block** that matches your tech stack. Point it to your actual entry file / jar / binary.

**Port is always 8080.** Your app must listen on `0.0.0.0:8080`.

Examples are pre-written for every supported stack — see the file for details.

---

### Step 5 — Make sure your app has a health endpoint

The workflow polls these paths in order and passes on the first `2xx`:

| Priority | Path | Stack |
|----------|------|-------|
| 1st | `GET /actuator/health` | Spring Boot |
| 2nd | `GET /health` | Most frameworks |
| 3rd | `GET /` | Fallback (any app) |

If your app has none of these, add a simple route that returns `200 OK`.

---

### Step 6 — Commit and push

```bash
chmod +x scripts/start.sh
git add .github/workflows/k6-performance-test.yml \
        scripts/generate_k6_script.py \
        scripts/post_pr_comment.py \
        scripts/start.sh \
        README.md
git commit -m "ci: add k6 auto performance testing"
git push
```

---

### Step 7 — Open a pull request

That's it. The workflow triggers automatically on every PR open or push.

---

## Stack Detection Reference

The workflow detects your stack by looking for these files **in the repo root**:

| File found | Stack label | Runtime set up | Build command |
|------------|-------------|----------------|---------------|
| `pom.xml` | `java-maven` | Java 17 (Temurin) | `mvn -B package -DskipTests` |
| `build.gradle` or `build.gradle.kts` | `java-gradle` | Java 17 (Temurin) | `./gradlew build -x test` or `gradle build -x test` |
| `package.json` | `node` | Node.js 20 | `npm install` (+ `npm run build` if defined) |
| `requirements.txt` or `pyproject.toml` | `python` | Python 3.11 | `pip install -r requirements.txt` or `pip install .` |
| `go.mod` | `go` | Go 1.22 | `go build ./...` |
| `Gemfile` | `ruby` | Ruby 3.3 | `bundle install` |
| *(none of the above)* | `unknown` | — | *(build step skipped)* |

Detection is **first-match** in the order shown above.

---

## Sample PR Comment

This is what the workflow posts to every PR:

---

## ✅ k6 Performance Test Results

> 🤖 **AI-generated k6 script** — created by Groq Llama3 for the `node` stack and committed back to this PR branch. It will be reused on future pushes.

### 📊 Metrics

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| P95 Response Time | 142.30 ms | < 500 ms | ✅ |
| P99 Response Time | 198.54 ms | — | ℹ️ |
| Avg Response Time | 98.12 ms | — | ℹ️ |
| Min Response Time | 12.44 ms | — | ℹ️ |
| Max Response Time | 312.09 ms | — | ℹ️ |
| Error Rate | 0.0000% | < 1% | ✅ |
| Throughput (RPS) | 9.87 req/s | — | ℹ️ |
| Total Requests | 296 | — | ℹ️ |
| Max VUs | 10 | — | ℹ️ |

### 🏁 Verdict

**✅ All performance thresholds passed.** This PR meets the required performance standards and is safe to merge.

<details>
<summary>📋 k6 Output (last 40 lines)</summary>

```
          /\      |‾‾| /‾‾/   /‾‾/
     /\  /  \     |  |/  /   /  /
    /  \/    \    |     (   /   ‾‾\
   /          \   |  |\  \ |  (‾)  |
  / __________ \  |__| \__\ \_____/ .io

  execution: local
     script: tests/k6/performance-test.js
     output: json=k6-results/raw.json

  scenarios: (100.00%) 1 scenario, 10 max VUs, 1m5s max duration ...
  ✓ status is 2xx
  ✓ response time < 500ms

  checks.........................: 100.00% ✓ 592 ✗ 0
  data_received..................: 186 kB 5.6 kB/s
  data_sent......................: 48 kB 1.4 kB/s
  http_req_duration..............: avg=98.12ms min=12.44ms med=87.23ms max=312.09ms p(90)=135.44ms p(95)=142.30ms
  http_req_failed................: 0.00% ✓ 0 ✗ 296
  http_reqs......................: 296 9.87/s
  vus............................: 10 min=10 max=10
```

</details>

---
*Powered by [k6](https://k6.io) + [Groq Llama3](https://console.groq.com) · Stack detected: `node`*

---

## Thresholds

| Threshold | Limit | What happens on breach |
|-----------|-------|------------------------|
| P95 response time | < 500 ms | CI job fails ❌ |
| Error rate | < 1% | CI job fails ❌ |

To change these thresholds, edit both:
1. `scripts/generate_k6_script.py` → `SYSTEM_PROMPT` section (for newly generated scripts)
2. `tests/k6/performance-test.js` → `options.thresholds` (for existing scripts)

---

## Troubleshooting

### App won't start / health check times out

**Symptom:** Workflow fails at "Wait for application health check" after 90s.

**Checks:**
- Is `scripts/start.sh` committing and using `&` to background the process?
- Does your app actually bind to `0.0.0.0:8080` (not `127.0.0.1` or a different port)?
- Check `logs/app.log` — the workflow prints its tail when the health check times out.
- Does your app need environment variables (DB connection, etc.)? Add them as GitHub secrets and inject them in `start.sh`.

```bash
# Example: inject a database URL in start.sh
export DATABASE_URL="${DATABASE_URL:-jdbc:h2:mem:testdb}"
java -jar target/*.jar > logs/app.log 2>&1 &
```

---

### Wrong port

**Symptom:** Health check times out even though you can see the app started in logs.

**Fix:** The workflow always uses port 8080. Change your app's port in `start.sh`:

```bash
# Force port via environment variable (most frameworks support this)
PORT=8080 node server.js > logs/app.log 2>&1 &
```

---

### Groq API errors

**Symptom:** The "Generate k6 script via Groq AI" step fails.

**Checks:**
- Is the `GROQ_API_KEY` secret set correctly? (Settings → Secrets → Actions)
- Has your Groq free tier quota been exceeded? Check [console.groq.com](https://console.groq.com).
- Is the secret name exactly `GROQ_API_KEY` (case-sensitive)?

**Fallback:** If Groq fails, the script automatically writes a safe fallback that tests `GET /` and `GET /health`. The workflow continues — you won't get a blank failure, just a basic test.

---

### Generated k6 script is wrong / testing wrong endpoints

**Symptom:** The AI-generated script tests endpoints that don't exist in your app.

**Fix options:**
1. **Delete** `tests/k6/performance-test.js` and reopen the PR with a more descriptive PR description mentioning specific endpoint paths.
2. **Edit** `tests/k6/performance-test.js` directly and commit — the workflow reuses it on all future pushes.

The AI uses your **PR title** and **PR body** to infer which endpoints to test. A PR description like:

> "Adds `POST /api/users` and `GET /api/users/{id}` endpoints for user management"

will produce a much more accurate test than an empty description.

---

### Thresholds keep failing

**Symptom:** CI fails with "k6 performance thresholds FAILED".

**Steps:**
1. Download the `k6-results` artifact from the workflow run.
2. Open `summary.json` to see exact metric values.
3. Open `output.txt` for the full k6 run log.

**Options:**
- Fix the performance issue in your code (recommended).
- Adjust thresholds in `tests/k6/performance-test.js` if the defaults are too strict for your use case.

```javascript
// In tests/k6/performance-test.js, relax thresholds:
export const options = {
  thresholds: {
    'http_req_duration': ['p(95)<1000'],  // loosen to 1s
    'http_req_failed':   ['rate<0.05'],   // loosen to 5%
  },
  // ...
};
```

---

### Health check is slow (app takes > 90s to start)

**Symptom:** Health check times out for apps with long startup (e.g. large Spring Boot apps).

**Fix:** Increase the timeout in the workflow file:

```yaml
# In .github/workflows/k6-performance-test.yml
# Find the "Wait for application health check" step and change:
TIMEOUT=90
# to:
TIMEOUT=180
```

---

### k6 script not committed back to PR

**Symptom:** Script is generated but not appearing in the branch.

**Check:** Does your repository have **branch protection rules** that prevent direct pushes from Actions? You may need to:
- Allow GitHub Actions to bypass branch protection, or
- Manually commit a `tests/k6/performance-test.js` file to your branch before opening the PR.

---

## File Structure

```
.
├── .github/
│   └── workflows/
│       └── k6-performance-test.yml   # Workflow — do not rename
├── scripts/
│   ├── generate_k6_script.py         # Groq AI script generator
│   ├── post_pr_comment.py            # PR comment poster
│   └── start.sh                      # ← EDIT THIS
└── tests/
    └── k6/
        └── performance-test.js       # Auto-generated or manually written
```

> `tests/k6/performance-test.js` is created automatically on the first PR run if it does not already exist. It is committed back to your branch and reused on all subsequent runs.
