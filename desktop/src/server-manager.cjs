const { execFile, spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");

const OUTPUT_LIMIT = 16 * 1024;
const HEALTH_POLL_MS = 250;

function selectLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function normalizePath(value) {
  return path.resolve(String(value)).replace(/[\\/]+/g, "\\").toLowerCase();
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isProcessExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function waitForExit(child, timeoutMs) {
  if (isProcessExited(child)) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (exited) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.removeListener("exit", onExit);
      child.removeListener("error", onError);
      resolve(exited);
    };
    const onExit = () => finish(true);
    const onError = () => finish(true);
    const timer = setTimeout(() => finish(isProcessExited(child)), Math.max(0, timeoutMs));
    child.once("exit", onExit);
    child.once("error", onError);
    if (isProcessExited(child)) finish(true);
  });
}

function appendOutput(current, chunk) {
  const next = current + chunk.toString("utf8");
  return next.length > OUTPUT_LIMIT ? next.slice(-OUTPUT_LIMIT) : next;
}

async function startBackend({
  pythonPath,
  appRoot,
  dataDir,
  port,
  shutdownToken,
  spawnImpl = spawn,
  fetchImpl = globalThis.fetch,
  timeoutMs = 30_000,
}) {
  const baseUrl = `http://127.0.0.1:${port}`;
  let output = "";
  let exit = null;
  let resolveExit;
  const exited = new Promise((resolve) => { resolveExit = resolve; });
  const child = spawnImpl(pythonPath, [
    path.join(appRoot, "run.py"), "--host", "127.0.0.1", "--port", String(port),
  ], {
    cwd: appRoot,
    env: {
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
      AUTOCXWEBUI_DATA_DIR: dataDir,
      AUTOCXWEBUI_SHUTDOWN_TOKEN: shutdownToken,
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  for (const stream of [child.stdout, child.stderr]) {
    if (stream) stream.on("data", (chunk) => { output = appendOutput(output, chunk); });
  }
  child.once("error", (error) => {
    exit = { error };
    resolveExit(exit);
  });
  child.once("exit", (code, signal) => {
    exit = { code, signal };
    resolveExit(exit);
  });

  const deadline = Date.now() + timeoutMs;
  let lastError = "health check did not return the expected application data directory";
  try {
    while (Date.now() < deadline) {
      if (exit) {
        const cause = exit.error ? exit.error.message : `exit code ${exit.code ?? exit.signal}`;
        throw new Error(`Backend exited before becoming ready (${cause})`);
      }
      try {
        const response = await fetchImpl(`${baseUrl}/api/health`, {
          signal: AbortSignal.timeout(1000),
        });
        if (response.ok) {
          const health = await response.json();
          if (health.ok === true && normalizePath(health.data_dir) === normalizePath(dataDir)) {
            return { child, baseUrl, getOutput: () => output };
          }
          lastError = "health check reached a different service or data directory";
        } else {
          lastError = `health check returned HTTP ${response.status}`;
        }
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
      await Promise.race([delay(Math.min(HEALTH_POLL_MS, deadline - Date.now())), exited]);
    }
    throw new Error(`Backend startup timed out: ${lastError}`);
  } catch (error) {
    try {
      child.kill();
    } catch {
      // Startup errors remain primary; the Electron main process has a final tree cleanup.
    }
    const tail = output.trim();
    throw new Error(tail ? `${error.message}\n\n${tail}` : error.message, { cause: error });
  }
}

function runTaskkill(pid) {
  return new Promise((resolve, reject) => {
    execFile("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
    }, (error) => error ? reject(error) : resolve());
  });
}

async function stopBackend({
  child,
  baseUrl,
  shutdownToken,
  fetchImpl = globalThis.fetch,
  graceMs = 15_000,
  taskkillImpl = runTaskkill,
}) {
  if (!child || isProcessExited(child)) return;

  try {
    const controller = new AbortController();
    let requestTimeout;
    await Promise.race([
      fetchImpl(`${baseUrl}/api/internal/shutdown`, {
        method: "POST",
        headers: { "X-AutoCx-Shutdown-Token": shutdownToken },
        signal: controller.signal,
      }).catch(() => {}),
      new Promise((resolve) => {
        requestTimeout = setTimeout(() => {
          controller.abort();
          resolve();
        }, Math.min(1000, graceMs));
      }),
    ]);
    clearTimeout(requestTimeout);
  } catch {
    // The process may already be shutting down; wait for it before forcing termination.
  }
  if (await waitForExit(child, graceMs)) return;

  try {
    await taskkillImpl(child.pid);
  } catch {
    try {
      child.kill();
    } catch {
      // The parent process is already exiting; nothing else can be done here.
    }
  }
  await waitForExit(child, 2000);
}

module.exports = { selectLoopbackPort, startBackend, stopBackend };
