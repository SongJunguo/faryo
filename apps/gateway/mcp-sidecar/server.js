import { randomUUID, timingSafeEqual } from "node:crypto";
import fs from "node:fs";
import express from "express";
import cors from "cors";
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";

const PORT = Number(process.env.FARYO_MCP_PORT || 8781);
const BACKEND_MCP = process.env.FARYO_GATEWAY_MCP_URL || "http://127.0.0.1:8780/mcp";
const OWNER_URL = process.env.FARYO_TXY_OWNER_URL || "http://127.0.0.1:8765";
const OWNER_ENV = process.env.FARYO_TXY_OWNER_ENV || "/home/summer/.faryo/owner/config/faryo.env";
const GATEWAY_ENV = process.env.FARYO_GATEWAY_ENV || "/home/summer/.faryo/gateway/config/faryo.env";
const ACCESS_TOKEN = process.env.FARYO_MCP_ACCESS_TOKEN || "";
const transports = new Map();

function readEnvValue(path, key) {
  const body = fs.readFileSync(path, "utf8");
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const index = line.indexOf("=");
    if (index < 0 || line.slice(0, index) !== key) continue;
    let value = line.slice(index + 1).trim();
    if ((value.startsWith("'") && value.endsWith("'")) || (value.startsWith('"') && value.endsWith('"'))) {
      value = value.slice(1, -1);
    }
    return value;
  }
  throw new Error(`${key} not found in ${path}`);
}

const OWNER_TOKEN = readEnvValue(OWNER_ENV, "FARYO_OWNER_TOKEN");
const GATEWAY_TOKEN = readEnvValue(GATEWAY_ENV, "FARYO_MCP_TOKEN");

function tokenMatches(received) {
  if (!ACCESS_TOKEN || typeof received !== "string") return false;
  const expected = Buffer.from(ACCESS_TOKEN);
  const actual = Buffer.from(received);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

function requireAccess(req, res, next) {
  if (tokenMatches(req.query.access_token)) return next();
  res.status(401).json({
    jsonrpc: "2.0",
    id: null,
    error: { code: -32001, message: "Unauthorized" }
  });
}

function asToolResult(result) {
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    structuredContent: result,
    isError: result?.ok === false
  };
}

async function callOwner(path, payload) {
  const response = await fetch(`${OWNER_URL}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "accept": "application/json",
      "x-owner-token": OWNER_TOKEN
    },
    body: JSON.stringify(payload)
  });
  const text = await response.text();
  let result;
  try {
    result = JSON.parse(text);
  } catch {
    throw new Error(`Owner returned invalid JSON (${response.status}): ${text}`);
  }
  return asToolResult(result);
}

const TASKS = new Set(["faryo_run_tests", "faryo_run_build", "faryo_run_lint"]);

async function callBackendTool(name, args) {
  if (args?.target === "txy") {
    const payload = { ...args };
    delete payload.target;
    if (TASKS.has(name)) {
      payload.action = name.replace(/^faryo_/, "");
      return callOwner("/api/task", payload);
    }
    payload.action = name.replace(/^faryo_/, "");
    return callOwner("/api/devfs", payload);
  }

  const response = await fetch(BACKEND_MCP, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "accept": "application/json, text/event-stream",
      "authorization": `Bearer ${GATEWAY_TOKEN}`
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: randomUUID(),
      method: "tools/call",
      params: { name, arguments: args }
    })
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`Gateway HTTP ${response.status}: ${text}`);
  const payload = JSON.parse(text);
  if (payload.error) throw new Error(payload.error.message || JSON.stringify(payload.error));
  return payload.result;
}

function createServer() {
  const server = new McpServer(
    { name: "faryo-devfs", version: "1.1.0" },
    {
      instructions: "Use the dedicated Faryo tools for directory listing, file reading, text search, file writing, exact text replacement, directory creation, moving, deletion, Git inspection, tests, builds, and lint checks."
    }
  );

  const target = z.enum(["gcp", "hp", "txy"]).describe(
    "Faryo target host: gcp, hp, or txy."
  );
  const pathSchema = z.string().min(1).describe(
    "Absolute path or target-local path accepted by the selected Faryo target."
  );
  const encodingSchema = z.string().min(1).optional().describe(
    "Text encoding name. Omit to use the target default, normally UTF-8."
  );
  const outputSchema = z.object({
    ok: z.boolean(),
    action: z.string().optional()
  }).passthrough();
  const registerTool = (name, config, handler) => server.registerTool(
    name,
    { ...config, outputSchema },
    handler
  );

  registerTool("faryo_list_dir", {
    title: "List Faryo directory",
    description: "List the immediate entries of a directory on the selected Faryo target without modifying it.",
    inputSchema: {
      target,
      path: pathSchema.describe("Directory path to list on the selected target.")
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_list_dir", args));

  registerTool("faryo_read_file", {
    title: "Read Faryo text file",
    description: "Read and return the contents of a text file on the selected Faryo target without modifying it.",
    inputSchema: {
      target,
      path: pathSchema.describe("Text file path to read on the selected target."),
      encoding: encodingSchema
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_read_file", args));

  registerTool("faryo_search_text", {
    title: "Search text on Faryo target",
    description: "Recursively search files for an exact, case-sensitive text string on the selected Faryo target without modifying files.",
    inputSchema: {
      target,
      path: pathSchema.describe("File or directory path to search on the selected target."),
      query: z.string().min(1).describe("Exact, case-sensitive text to find."),
      glob: z.string().min(1).optional().describe(
        "Optional file glob such as *.py or **/*.js."
      ),
      max_results: z.number().int().min(1).max(1000).optional().describe(
        "Maximum number of matching lines to return. Defaults to 100."
      ),
      encoding: encodingSchema
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_search_text", args));

  registerTool("faryo_write_file", {
    title: "Write Faryo text file",
    description: "Create a text file or replace the complete contents of an existing text file on the selected Faryo target.",
    inputSchema: {
      target,
      path: pathSchema.describe("Destination text file path on the selected target."),
      content: z.string().describe("Complete text content to write to the file."),
      encoding: encodingSchema
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_write_file", args));

  registerTool("faryo_replace_text", {
    title: "Replace exact text in Faryo file",
    description: "Replace exact matching text inside an existing text file on the selected Faryo target.",
    inputSchema: {
      target,
      path: pathSchema.describe("Existing text file path to edit on the selected target."),
      old_text: z.string().describe("Exact text to find in the file."),
      new_text: z.string().describe("Replacement text to insert for each matched occurrence."),
      expected_count: z.number().int().optional().describe(
        "Required number of matches. Omit when no exact match count is required."
      ),
      encoding: encodingSchema
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_replace_text", args));

  registerTool("faryo_mkdir", {
    title: "Create Faryo directory",
    description: "Create a directory on the selected Faryo target.",
    inputSchema: {
      target,
      path: pathSchema.describe("Directory path to create on the selected target."),
      exist_ok: z.boolean().optional().describe(
        "When true, succeed if the directory already exists."
      )
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_mkdir", args));

  registerTool("faryo_move_path", {
    title: "Move Faryo path",
    description: "Move or rename a file or directory on the selected Faryo target.",
    inputSchema: {
      target,
      source: pathSchema.describe("Existing source path on the selected target."),
      destination: pathSchema.describe("Destination path on the selected target.")
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_move_path", args));

  registerTool("faryo_delete_path", {
    title: "Delete Faryo path",
    description: "Delete a file or directory on the selected Faryo target.",
    inputSchema: {
      target,
      path: pathSchema.describe("File or directory path to delete on the selected target."),
      recursive: z.boolean().optional().describe(
        "When true, recursively delete a non-empty directory."
      )
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_delete_path", args));

  registerTool("faryo_git_status", {
    title: "Show Faryo Git status",
    description: "Read the concise Git working tree and branch status for a repository on the selected Faryo target.",
    inputSchema: {
      target,
      cwd: pathSchema.describe("Repository directory on the selected target.")
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_git_status", args));

  registerTool("faryo_git_diff", {
    title: "Show Faryo Git diff",
    description: "Read unstaged or staged Git changes for a repository on the selected Faryo target.",
    inputSchema: {
      target,
      cwd: pathSchema.describe("Repository directory on the selected target."),
      staged: z.boolean().optional().describe("When true, return staged changes instead of unstaged changes.")
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, async (args) => callBackendTool("faryo_git_diff", args));

  for (const [name, title, description] of [
    ["faryo_run_tests", "Run Faryo tests", "Run the repository's predefined test task on the selected Faryo target."],
    ["faryo_run_build", "Run Faryo build", "Run the repository's predefined build task on the selected Faryo target."],
    ["faryo_run_lint", "Run Faryo lint", "Run the repository's predefined lint task on the selected Faryo target."]
  ]) {
    registerTool(name, {
      title,
      description,
      inputSchema: {
        target,
        cwd: pathSchema.describe("Project directory on the selected target."),
        timeout_seconds: z.number().int().min(1).max(900).optional().describe("Task timeout in seconds.")
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false
      }
    }, async (args) => callBackendTool(name, args));
  }

  return server;
}

const app = express();
app.use(cors({ exposedHeaders: ["Mcp-Session-Id"] }));

app.get("/healthz", (_req, res) => {
  res.json({ ok: true, name: "faryo-gateway-mcp-adapter", auth: "query-token" });
});

app.use("/mcp", requireAccess);

app.post("/mcp", express.json({ limit: "20mb" }), async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"];
    let transport;

    if (sessionId && transports.has(sessionId)) {
      transport = transports.get(sessionId);
    } else if (!sessionId && isInitializeRequest(req.body)) {
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (newSessionId) => transports.set(newSessionId, transport)
      });
      transport.onclose = () => {
        if (transport.sessionId) transports.delete(transport.sessionId);
      };
      const server = createServer();
      await server.connect(transport);
    } else {
      res.status(400).json({
        jsonrpc: "2.0",
        id: null,
        error: { code: -32000, message: "Missing or invalid MCP session" }
      });
      return;
    }

    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error(error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        id: null,
        error: { code: -32603, message: error instanceof Error ? error.message : String(error) }
      });
    }
  }
});

async function handleSessionRequest(req, res) {
  const sessionId = req.headers["mcp-session-id"];
  const transport = sessionId ? transports.get(sessionId) : undefined;
  if (!transport) {
    res.status(400).send("Invalid or missing MCP session id");
    return;
  }
  await transport.handleRequest(req, res);
}

app.get("/mcp", handleSessionRequest);
app.delete("/mcp", handleSessionRequest);

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Faryo MCP adapter listening on http://127.0.0.1:${PORT}/mcp`);
});
