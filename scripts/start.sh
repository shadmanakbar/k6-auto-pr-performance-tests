#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/start.sh — Application Startup Script
# ══════════════════════════════════════════════════════════════════════════════
#
# PURPOSE
#   This script is run by the k6 GitHub Actions workflow to start your
#   application before running performance tests.
#
# REQUIREMENTS  (read carefully — the workflow depends on these)
#   1. Your app MUST listen on port 8080.
#   2. Your app MUST respond with a 2xx HTTP status to at least ONE of:
#        GET http://localhost:8080/actuator/health   (Spring Boot default)
#        GET http://localhost:8080/health            (common convention)
#        GET http://localhost:8080/                  (root path)
#   3. Start your app in the BACKGROUND (append &) so this script can return.
#   4. Logs should go to logs/app.log so the workflow can show them when the
#      health check times out.
#
# HOW TO USE
#   1. Uncomment the ONE block that matches your tech stack below.
#   2. Adjust the command to point to your actual entry point / jar / binary.
#   3. Commit this file. The workflow will handle the rest automatically.
#
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

mkdir -p logs

# ─── Uncomment the block that matches your stack ────────────────────────────

# ── Node.js (direct) ──────────────────────────────────────────────────────────
# Adjust "server.js" to your actual entry file (e.g. src/index.js, app.js)
# node server.js > logs/app.log 2>&1 &

# ── Node.js (npm start) ───────────────────────────────────────────────────────
# Uses the "start" script defined in package.json
# npm start > logs/app.log 2>&1 &

# ── Python · FastAPI with Uvicorn ─────────────────────────────────────────────
# Replace "main:app" with your module:variable (e.g. "src.main:app")
# uvicorn main:app --host 0.0.0.0 --port 8080 > logs/app.log 2>&1 &

# ── Python · Flask ────────────────────────────────────────────────────────────
# Set FLASK_APP to your module if it differs from "app"
# FLASK_APP=app flask run --host=0.0.0.0 --port=8080 > logs/app.log 2>&1 &

# ── Python · Gunicorn ─────────────────────────────────────────────────────────
# gunicorn main:app --bind 0.0.0.0:8080 --workers 2 > logs/app.log 2>&1 &

# ── Java · Spring Boot fat JAR ────────────────────────────────────────────────
if ls target/*.jar >/dev/null 2>&1; then
  echo "☕ Starting Java (Maven) JAR..."
  java -jar target/*.jar --server.port=8080 > logs/app.log 2>&1 &
elif ls build/libs/*.jar >/dev/null 2>&1; then
  echo "☕ Starting Java (Gradle) JAR..."
  java -jar build/libs/*.jar --server.port=8080 > logs/app.log 2>&1 &
elif [ -f "package.json" ]; then
  echo "🟢 Starting Node.js app..."
  npm start > logs/app.log 2>&1 &
fi

# ─────────────────────────────────────────────────────────────────────────────

echo "🚀 App starting process initiated on port 8080"
echo "   Checking logs/app.log if the health check times out"
