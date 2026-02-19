#!/usr/bin/env python3
import json
import os
import subprocess
import sys

def call_mcp_tool(tool_name, arguments):
    """Simple wrapper to call a tool on the mcp-k6 server via stdio."""
    # The official mcp-k6 server expects JSON-RPC over stdio
    process = subprocess.Popen(
        ["mcp-k6"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # 1. Initialize
    process.stdin.write(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ci-orchestrator", "version": "1.0"}
        }
    }) + "\n")
    
    # 2. Call Tool
    process.stdin.write(json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }) + "\n")
    
    process.stdin.close()
    
    stdout_output = process.stdout.read()
    process.terminate()

    # Parse the response (the second message is usually the tool result)
    for line in stdout_output.splitlines():
        try:
            resp = json.loads(line)
            if resp.get("id") == 2:
                return resp.get("result")
        except:
            continue
    return None

def main():
    print("🚀 Starting k6 Performance Test (using official Grafana MCP-K6)...")
    
    pr_title = os.environ.get("PR_TITLE", "Test PR")
    pr_body = os.environ.get("PR_BODY", "")
    stack = os.environ.get("DETECTED_STACK", "unknown")
    
    # 1. Generate Script using official mcp-k6 prompt tool
    # Note: mcp-k6 has a 'generate_script' prompt, but for standard tool calls we use its logic
    # As per README, k6-mcp has a tool 'run_script' and 'validate_script'.
    # We will pass the PR context to generate a script.
    
    prompt = f"Stack: {stack}\nPR: {pr_title}\nDescription: {pr_body}\nRule: Target http://localhost:8080. 10 VUs for 30s. P95 < 500ms."
    
    # Since we want it SIMPLE, let's just use the existing generate_k6_script logic if available,
    # or use the MCP server to validate a generated one.
    # Actually, let's just use k6 directly for execution if the script exists!
    
    script_path = "tests/k6/performance-test.js"
    
    if not os.path.exists(script_path):
        print("📝 Generating k6 script via Ollama...")
        # We'll use our existing robust generator for the file creation
        subprocess.run(["python3", "scripts/generate_k6_script.py"], check=True)

    # 2. Validate using official mcp-k6
    print("🔍 Validating script with mcp-k6...")
    with open(script_path, "r") as f:
        script_content = f.read()
    
    val_res = call_mcp_tool("validate_script", {"script": script_content})
    if val_res and not val_res.get("isError"):
        print("✅ Script validation passed.")
    else:
        print(f"⚠️ Validation warning or error: {val_res}")

    # 3. Run Test using official mcp-k6
    print("🏃 Running performance test...")
    run_res = call_mcp_tool("run_script", {
        "script": script_content,
        "vus": 10,
        "duration": "30s"
    })

    if not run_res:
        print("❌ Test failed to return results.")
        sys.exit(1)

    # 4. Extract metrics and post result (using existing post script)
    # The mcp-k6 tool returns stdout/stderr. We'll save them and let the post script handle it.
    os.makedirs("k6-results", exist_ok=True)
    with open("k6-results/output.txt", "w") as f:
        f.write(run_res.get("stdout", ""))
    
    # Run the existing post script to format and post to GitHub
    print("📤 Posting results to GitHub...")
    subprocess.run(["python3", "scripts/post_pr_comment.py"], check=True)

if __name__ == "__main__":
    main()
