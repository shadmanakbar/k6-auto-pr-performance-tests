#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

class MCPClient:
    def __init__(self, command):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.msg_id = 1

    def send(self, method, params):
        request = {
            "jsonrpc": "2.0",
            "id": self.msg_id,
            "method": method,
            "params": params
        }
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        self.msg_id += 1
        
        # Read until we get a non-error line (or timeout)
        while True:
            line = self.process.stdout.readline()
            if not line:
                return None
            try:
                resp = json.loads(line)
                if "id" in resp:
                    return resp
            except:
                continue

    def call_tool(self, name, args):
        return self.send("tools/call", {
            "name": name,
            "arguments": args
        })

    def close(self):
        self.process.terminate()

def log(msg):
    print(f"[mcp-orchestrator] {msg}", file=sys.stderr, flush=True)

def main():
    log("Starting K6 MCP Orchestrator...")
    
    server_cmd = ["node", "mcp-server/dist/index.js"]
    client = MCPClient(server_cmd)

    # 1. Initialize
    log("Initializing MCP Server...")
    client.send("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "k6-orc", "version": "1.0"}
    })

    # Get env vars
    pr_title = os.environ.get("PR_TITLE", "Test PR")
    pr_body = os.environ.get("PR_BODY", "")
    stack = os.environ.get("DETECTED_STACK", "java-maven")
    prompt = f"Title: {pr_title}\nBody: {pr_body}"

    # 2. Generate Script
    log(f"Generating script for {stack}...")
    gen_resp = client.call_tool("generate_k6_script", {
        "prompt": prompt,
        "techStack": stack
    })
    
    if not gen_resp or "result" not in gen_resp:
        log(f"❌ Generation failed: {gen_resp}")
        sys.exit(1)
        
    script_content = gen_resp["result"]["content"][0]["text"]
    log("✅ Script generated.")

    # 3. Run Test
    log("Running k6 test via MCP...")
    run_resp = client.call_tool("run_k6_test", {
        "scriptContent": script_content
    })
    
    if not run_resp or "result" not in run_resp:
        log(f"❌ Execution failed: {run_resp}")
        sys.exit(1)
        
    exec_data = json.loads(run_resp["result"]["content"][0]["text"])
    log(f"✅ k6 finished with exit code {exec_data['exitCode']}")

    # 4. Format Results
    log("Formatting results for PR...")
    format_resp = client.call_tool("format_results", {
        "resultsJson": exec_data["summaryData"],
        "exitCode": exec_data["exitCode"],
        "stack": stack
    })
    
    if not format_resp or "result" not in format_resp:
        log("❌ Formatting failed.")
        sys.exit(1)
        
    comment_body = format_resp["result"]["content"][0]["text"]
    
    # 5. Post Comment to GitHub
    log("Posting results to GitHub...")
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("REPO")
    pr_num = os.environ.get("PR_NUMBER")

    if token and repo and pr_num:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_num}/comments"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        data = json.dumps({"body": comment_body}).encode("utf-8")
        req = subprocess.run([
            "curl", "-s", "-X", "POST",
            "-H", f"Authorization: token {token}",
            "-H", "Accept: application/vnd.github.v3+json",
            "-d", json.dumps({"body": comment_body}),
            url
        ], capture_output=True)
        log("✅ Comment posted.")
    else:
        log("⚠️ Skipping comment posting (missing env vars).")
        print(comment_body)
    
    client.close()
    
    # Final exit code based on k6 run
    sys.exit(exec_data["exitCode"])

if __name__ == "__main__":
    main()
