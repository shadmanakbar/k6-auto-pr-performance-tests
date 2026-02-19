import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, } from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "child_process";
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "fs";
import path from "path";
/**
 * K6 MCP Server
 * Exposes tools to generate, run, and analyze k6 performance tests.
 */
const server = new Server({
    name: "k6-mcp-server",
    version: "1.0.0",
}, {
    capabilities: {
        tools: {},
    },
});
const OLLAMA_HOST = process.env.OLLAMA_HOST || "http://localhost:11434";
const OLLAMA_MODEL = "llama3";
/**
 * Helper to call Ollama
 */
async function callOllama(systemPrompt, userPrompt) {
    const url = `${OLLAMA_HOST}/v1/chat/completions`;
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            model: OLLAMA_MODEL,
            messages: [
                { role: "system", content: systemPrompt },
                { role: "user", content: userPrompt },
            ],
            stream: false,
            temperature: 0.2,
        }),
    });
    if (!response.ok) {
        const err = await response.text();
        throw new Error(`Ollama error: ${err}`);
    }
    const data = await response.json();
    return data.choices[0].message.content;
}
/**
 * Define available tools
 */
const TOOLS = [
    {
        name: "generate_k6_script",
        description: "Generates a k6 script from a performance testing prompt and tech stack context.",
        inputSchema: {
            type: "object",
            properties: {
                prompt: { type: "string" },
                techStack: { type: "string" },
                targetUrl: { type: "string", default: "http://localhost:8080" },
            },
            required: ["prompt", "techStack"],
        },
    },
    {
        name: "run_k6_test",
        description: "Runs a provided k6 script and returns the JSON summary results.",
        inputSchema: {
            type: "object",
            properties: {
                scriptContent: { type: "string" },
                outputDir: { type: "string", default: "k6-results" },
            },
            required: ["scriptContent"],
        },
    },
    {
        name: "format_results",
        description: "Formats k6 JSON results into a markdown table for PR comments.",
        inputSchema: {
            type: "object",
            properties: {
                resultsJson: { type: "object" },
                exitCode: { type: "number" },
                stack: { type: "string" },
            },
            required: ["resultsJson", "exitCode", "stack"],
        },
    },
];
server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS,
}));
server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
        if (name === "generate_k6_script") {
            const { prompt, techStack, targetUrl = "http://localhost:8080" } = args;
            const systemPrompt = `You are an expert k6 engineer. Generate a k6 script. Output ONLY raw JS. 
      Target URL: ${targetUrl}. Stages: 10s ramp to 10 VUs, 20s hold, 5s ramp down. 
      Thresholds: p(95)<500, rate<0.01. Use groups and checks.`;
            const userPrompt = `PR Context: ${prompt}\nTech Stack: ${techStack}`;
            const script = await callOllama(systemPrompt, userPrompt);
            // Clean up markdown fences
            const cleanScript = script.replace(/^```[a-z]*\n/i, "").replace(/\n```$/i, "").trim();
            return {
                content: [{ type: "text", text: cleanScript }],
            };
        }
        if (name === "run_k6_test") {
            const { scriptContent, outputDir = "k6-results" } = args;
            const scriptPath = path.join(process.cwd(), "temp-test.js");
            const summaryPath = path.join(process.cwd(), outputDir, "summary.json");
            if (!existsSync(outputDir))
                mkdirSync(outputDir, { recursive: true });
            writeFileSync(scriptPath, scriptContent);
            return new Promise((resolve) => {
                const k6 = spawn("k6", [
                    "run",
                    "--summary-export", summaryPath,
                    scriptPath
                ]);
                let stdout = "";
                let stderr = "";
                k6.stdout.on("data", (data) => stdout += data);
                k6.stderr.on("data", (data) => stderr += data);
                k6.on("close", (code) => {
                    let summary = {};
                    try {
                        if (existsSync(summaryPath)) {
                            summary = JSON.parse(readFileSync(summaryPath, "utf-8"));
                        }
                    }
                    catch (e) { }
                    resolve({
                        content: [{
                                type: "text",
                                text: JSON.stringify({
                                    exitCode: code,
                                    stdout: stdout.slice(-1000), // Keep last 1000 chars
                                    stderr,
                                    summaryData: summary
                                }, null, 2)
                            }],
                    });
                });
            });
        }
        if (name === "format_results") {
            const { resultsJson, exitCode, stack } = args;
            const metrics = resultsJson.metrics || {};
            const httpReqDuration = metrics.http_req_duration?.values || {};
            const httpReqFailed = metrics.http_req_failed?.values || {};
            const p95 = httpReqDuration["p(95)"] || 0;
            const errorRate = (httpReqFailed.rate || 0) * 100;
            const rps = metrics.http_reqs?.values?.rate || 0;
            const p95Status = p95 < 500 ? "✅" : "❌";
            const errorStatus = errorRate < 1 ? "✅" : "❌";
            const overallStatus = (exitCode === 0 && p95 < 500 && errorRate < 1) ? "✅" : "❌";
            const table = `
## ${overallStatus} k6 Performance Test Results

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| P95 Response Time | ${p95.toFixed(2)} ms | < 500 ms | ${p95Status} |
| Error Rate | ${errorRate.toFixed(4)}% | < 1% | ${errorStatus} |
| Throughput | ${rps.toFixed(2)} req/s | — | ℹ️ |

**Verdict:** ${overallStatus === "✅" ? "Performance looks good!" : "Thresholds breached. Please check logs."}
      
---
*Powered by K6 MCP Server · Stack: ${stack}*
`.trim();
            return {
                content: [{ type: "text", text: table }],
            };
        }
        return {
            content: [{ type: "text", text: `Unknown tool: ${name}` }],
            isError: true,
        };
    }
    catch (error) {
        return {
            content: [{ type: "text", text: `Error: ${error.message}` }],
            isError: true,
        };
    }
});
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("K6 MCP Server running on stdio");
}
main().catch((error) => {
    console.error("Fatal error in main():", error);
    process.exit(1);
});
