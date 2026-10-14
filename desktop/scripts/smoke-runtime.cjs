const assert = require("node:assert/strict");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { selectLoopbackPort, startBackend, stopBackend } = require("../src/server-manager.cjs");

async function main() {
  const desktopRoot = path.resolve(__dirname, "..");
  const repoRoot = path.resolve(desktopRoot, "..");
  const pythonPath = path.join(desktopRoot, "build", "python", "python.exe");
  if (!fs.existsSync(pythonPath)) {
    throw new Error(`Packaged Python runtime is missing: ${pythonPath}`);
  }

  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "autocxwebui-electron-smoke-"));
  const shutdownToken = randomBytes(32).toString("hex");
  let backend;
  try {
    backend = await startBackend({
      pythonPath,
      appRoot: repoRoot,
      dataDir,
      port: await selectLoopbackPort(),
      shutdownToken,
      timeoutMs: 30_000,
    });

    const page = await fetch(backend.baseUrl);
    assert.equal(page.ok, true, "FastAPI should serve the Vue entry page");
    assert.match(await page.text(), /id=["']app["']/i);

    const health = await fetch(`${backend.baseUrl}/api/health`).then((response) => response.json());
    assert.equal(health.ok, true);
    assert.equal(path.resolve(health.data_dir), path.resolve(dataDir));

    for (const endpoint of ["/api/overview", "/api/accounts", "/api/settings", "/api/question-bank/stats"]) {
      const response = await fetch(`${backend.baseUrl}${endpoint}`);
      assert.equal(response.ok, true, `${endpoint} should respond successfully`);
      await response.json();
    }
    const createdAccount = await fetch(`${backend.baseUrl}/api/accounts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "13800000000", password: "smoke-only" }),
    });
    assert.equal(createdAccount.status, 201);
    assert.equal((await createdAccount.json()).username, "13800000000");
    console.log("Embedded Python backend and Vue static page are healthy.");
  } finally {
    if (backend) {
      await stopBackend({
        child: backend.child,
        baseUrl: backend.baseUrl,
        shutdownToken,
        graceMs: 15_000,
      });
    }
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
