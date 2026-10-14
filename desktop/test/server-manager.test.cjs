const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const { test } = require("node:test");

const { selectLoopbackPort, startBackend, stopBackend } = require("../src/server-manager.cjs");

function fakeChildProcess() {
  const child = new EventEmitter();
  child.pid = 4321;
  child.exitCode = null;
  child.signalCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => {
    child.signalCode = "SIGTERM";
    child.emit("exit", null, "SIGTERM");
    return true;
  };
  return child;
}

const options = (overrides = {}) => ({
  pythonPath: "python.exe",
  appRoot: "C:/app",
  dataDir: "C:/user-data",
  port: 18848,
  shutdownToken: "test-token",
  timeoutMs: 100,
  ...overrides,
});

test("selectLoopbackPort reserves an ephemeral loopback port", async () => {
  const port = await selectLoopbackPort();
  assert.equal(Number.isInteger(port), true);
  assert.ok(port > 0 && port <= 65535);
});

test("startBackend launches Python and waits for matching health", async () => {
  const child = fakeChildProcess();
  let launch;
  const result = await startBackend(options({
    spawnImpl: (executable, args, spawnOptions) => {
      launch = { executable, args, spawnOptions };
      return child;
    },
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({ ok: true, data_dir: "C:/user-data" }),
    }),
  }));

  assert.equal(launch.executable, "python.exe");
  assert.equal(launch.args[0], path.join("C:/app", "run.py"));
  assert.deepEqual(launch.args.slice(1), ["--host", "127.0.0.1", "--port", "18848"]);
  assert.equal(launch.spawnOptions.cwd, "C:/app");
  assert.equal(launch.spawnOptions.env.AUTOCXWEBUI_DATA_DIR, "C:/user-data");
  assert.equal(launch.spawnOptions.env.AUTOCXWEBUI_SHUTDOWN_TOKEN, "test-token");
  assert.equal(result.baseUrl, "http://127.0.0.1:18848");
  assert.equal(result.child, child);
  assert.equal(typeof result.getOutput, "function");
});

test("startBackend rejects a different service on the selected port", async () => {
  const child = fakeChildProcess();
  await assert.rejects(startBackend(options({
    timeoutMs: 20,
    spawnImpl: () => child,
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({ ok: true, data_dir: "C:/other-app" }),
    }),
  })), /health|data directory|timed out/i);
  assert.equal(child.signalCode, "SIGTERM");
});

test("startBackend rejects if Python exits before health is ready", async () => {
  const child = fakeChildProcess();
  setImmediate(() => {
    child.exitCode = 2;
    child.emit("exit", 2, null);
  });
  await assert.rejects(startBackend(options({
    spawnImpl: () => child,
    fetchImpl: async () => { throw new Error("not listening"); },
  })), /exited|exit code/i);
});

test("stopBackend sends the random token and waits for graceful exit", async () => {
  const child = fakeChildProcess();
  let request;
  await stopBackend({
    child,
    baseUrl: "http://127.0.0.1:18848",
    shutdownToken: "test-token",
    graceMs: 20,
    fetchImpl: async (url, init) => {
      request = { url, init };
      child.exitCode = 0;
      child.emit("exit", 0, null);
      return { ok: true };
    },
    taskkillImpl: async () => assert.fail("taskkill should not be needed"),
  });

  assert.equal(request.url, "http://127.0.0.1:18848/api/internal/shutdown");
  assert.equal(request.init.method, "POST");
  assert.equal(request.init.headers["X-AutoCx-Shutdown-Token"], "test-token");
});

test("stopBackend falls back to terminating the process tree", async () => {
  const child = fakeChildProcess();
  let killedPid;
  await stopBackend({
    child,
    baseUrl: "http://127.0.0.1:18848",
    shutdownToken: "test-token",
    graceMs: 1,
    fetchImpl: async () => { throw new Error("server is unresponsive"); },
    taskkillImpl: async (pid) => {
      killedPid = pid;
      child.exitCode = 1;
      child.emit("exit", 1, null);
    },
  });

  assert.equal(killedPid, child.pid);
});
