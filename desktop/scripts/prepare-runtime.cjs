const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const https = require("node:https");
const path = require("node:path");

const PYTHON_VERSION = "3.13.12";
const EMBED_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const desktopRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(desktopRoot, "..");
const buildRoot = path.join(desktopRoot, "build");
const cacheRoot = path.join(desktopRoot, ".cache");
const runtimeRoot = path.join(buildRoot, "python");
const buildVenv = path.join(buildRoot, "python-build-venv");
const buildVenvPython = path.join(buildVenv, "Scripts", "python.exe");
const archivePath = path.join(cacheRoot, `python-${PYTHON_VERSION}-embed-amd64.zip`);
const requirementsPath = path.join(desktopRoot, "requirements-runtime.txt");
const buildPython = process.env.AUTOCXWEBUI_BUILD_PYTHON || "python";

function run(executable, args) {
  execFileSync(executable, args, { cwd: repoRoot, stdio: "inherit", windowsHide: true });
}

function verifyBuildPython() {
  try {
    run(buildPython, ["-c", [
      "import struct,sys",
      "assert sys.version_info[:2] == (3, 13), 'build Python must be 3.13.x'",
      "assert struct.calcsize('P') == 8, 'build Python must be 64-bit'",
    ].join("; ")]);
  } catch (error) {
    throw new Error(
      "Build staging requires 64-bit CPython 3.13.x. Set AUTOCXWEBUI_BUILD_PYTHON to its python.exe path.",
      { cause: error },
    );
  }
}

function download(url, destination, redirects = 0) {
  if (redirects > 5) return Promise.reject(new Error("Too many redirects downloading CPython"));
  return new Promise((resolve, reject) => {
    const request = https.get(url, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        download(new URL(response.headers.location, url).toString(), destination, redirects + 1)
          .then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`CPython download failed with HTTP ${response.statusCode}`));
        return;
      }
      const output = fs.createWriteStream(destination);
      response.pipe(output);
      output.once("finish", () => output.close(resolve));
      output.once("error", reject);
    });
    request.once("error", reject);
  });
}

async function main() {
  if (process.platform !== "win32") {
    throw new Error("The first desktop runtime build is supported on Windows x64 only.");
  }
  verifyBuildPython();
  fs.mkdirSync(cacheRoot, { recursive: true });
  fs.mkdirSync(buildRoot, { recursive: true });
  if (!fs.existsSync(buildVenvPython)) {
    run(buildPython, ["-m", "venv", buildVenv]);
  }
  if (!fs.existsSync(archivePath)) {
    console.log(`Downloading CPython ${PYTHON_VERSION} embeddable runtime…`);
    await download(EMBED_URL, archivePath);
  }

  fs.rmSync(runtimeRoot, { recursive: true, force: true });
  fs.mkdirSync(runtimeRoot, { recursive: true });
  run(buildVenvPython, ["-c", [
    "import sys,zipfile",
    "zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])",
  ].join("; "), archivePath, runtimeRoot]);

  const sitePackages = path.join(runtimeRoot, "Lib", "site-packages");
  fs.mkdirSync(sitePackages, { recursive: true });
  run(buildVenvPython, [
    "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
    "--target", sitePackages, "-r", requirementsPath,
  ]);

  const pthPath = path.join(runtimeRoot, "python313._pth");
  if (!fs.existsSync(pthPath)) throw new Error(`Missing embedded Python path file: ${pthPath}`);
  const lines = fs.readFileSync(pthPath, "utf8").split(/\r?\n/);
  const active = lines.filter((line) => line.trim() && !line.trim().startsWith("#"));
  if (!active.some((line) => line.trim().replaceAll("/", "\\").toLowerCase() === "lib\\site-packages")) {
    lines.push("Lib\\site-packages");
  }
  if (!active.some((line) => line.trim() === "import site")) lines.push("import site");
  fs.writeFileSync(pthPath, `${lines.filter(Boolean).join("\r\n")}\r\n`, "utf8");

  run(path.join(runtimeRoot, "python.exe"), ["-c", [
    "import fastapi, fontTools, loguru, lxml.etree, multipart, playwright.sync_api,",
    "PIL, pyDes, pydantic, requests, uvicorn, yaml",
  ].join(" ") + "; print('Embedded Python runtime imports OK')"]);
  console.log(`Runtime staged at ${runtimeRoot}`);
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
