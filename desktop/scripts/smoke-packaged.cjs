const assert = require("node:assert/strict");
const { execFileSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { version } = require("../package.json");

function terminateTree(pid) {
  try {
    execFileSync("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } catch {}
}

async function runSmoke(executable, cwd, tempRoot, label) {
  const dataDir = path.join(tempRoot, `${label}-user-data`);
  const readyFile = path.join(tempRoot, `${label}-ready.txt`);
  const output = [];
  let child;
  try {
    child = spawn(executable, [], {
      cwd,
      env: {
        ...process.env,
        AUTOCXWEBUI_ELECTRON_SMOKE: "1",
        AUTOCXWEBUI_ELECTRON_SMOKE_READY_FILE: readyFile,
        AUTOCXWEBUI_DATA_DIR: dataDir,
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: false,
    });
    for (const stream of [child.stdout, child.stderr]) {
      if (stream) stream.on("data", (chunk) => output.push(chunk.toString("utf8")));
    }

    const exit = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        terminateTree(child.pid);
        reject(new Error(`${label} Electron app did not exit within 120 seconds`));
      }, 120_000);
      child.once("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.once("exit", (code, signal) => {
        clearTimeout(timer);
        resolve({ code, signal });
      });
    });

    const details = fs.existsSync(readyFile) ? fs.readFileSync(readyFile, "utf8") : "";
    assert.equal(exit.code, 0, `${label}: ${details}\n${output.join("")}`);
    assert.match(details, /^READY http:\/\/127\.0\.0\.1:\d+\s*$/);
    assert.equal(fs.existsSync(path.join(dataDir, "webui.db")), true);
  } finally {
    if (child && child.exitCode === null) terminateTree(child.pid);
  }
}

async function main() {
  if (process.platform !== "win32") {
    throw new Error("Packaged Electron smoke test is supported on Windows only.");
  }
  const desktopRoot = path.resolve(__dirname, "..");
  const appOut = path.join(desktopRoot, "dist", "win-unpacked");
  const executable = path.join(appOut, "CourseArk.exe");
  const installer = path.join(desktopRoot, "dist", `CourseArk-${version}-Setup.exe`);
  const portable = path.join(desktopRoot, "dist", `CourseArk-${version}-Portable.exe`);
  const resources = path.join(appOut, "resources");
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "autocx-electron-smoke-"));

  try {
    assert.equal(fs.existsSync(executable), true, "unpacked Electron executable is missing");
    assert.equal(fs.existsSync(installer), true, "NSIS installer is missing");
    assert.equal(fs.existsSync(portable), true, "portable Electron executable is missing");
    assert.equal(fs.existsSync(path.join(resources, "python", "python.exe")), true);
    assert.equal(fs.existsSync(path.join(resources, "LICENSE")), true);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "app", "paths.py")), true);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "webui_static", "vue", "index.html")), true);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "cli_copy", "config.yml")), false);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "cli_copy", ".pytest_cache")), false);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "data", "accounts.json")), false);
    assert.equal(fs.existsSync(path.join(resources, "app-runtime", "data", "webui.db")), false);
    assert.match(
      fs.readFileSync(path.join(resources, "app-runtime", "webui_static", "vue", "index.html"), "utf8"),
      /CourseArk/,
      "packaged static page must be the CourseArk build",
    );

    await runSmoke(executable, appOut, tempRoot, "unpacked");
    await runSmoke(portable, path.dirname(portable), tempRoot, "portable");
    console.log("Unpacked and portable Electron apps loaded Vue and stopped their Python backends.");
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
