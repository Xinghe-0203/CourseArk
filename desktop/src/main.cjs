const path = require("node:path");
const fs = require("node:fs");
const { randomBytes } = require("node:crypto");
const { app, BrowserWindow, dialog, shell } = require("electron");

const { isInternalNavigation, externalHttpUrl } = require("./navigation-policy.cjs");
const { selectLoopbackPort, startBackend, stopBackend } = require("./server-manager.cjs");

// Keep the legacy app name so existing user data remains in %APPDATA%\AutoCxWebUI.
app.setName("AutoCxWebUI");

let mainWindow = null;
let backend = null;
let quitting = false;
let exitDialogOpen = false;
const smokeMode = process.env.AUTOCXWEBUI_ELECTRON_SMOKE === "1";

function runtimePaths() {
  if (app.isPackaged) {
    return {
      appRoot: path.join(process.resourcesPath, "app-runtime"),
      pythonPath: path.join(process.resourcesPath, "python", "python.exe"),
    };
  }
  return {
    appRoot: path.resolve(__dirname, "..", ".."),
    pythonPath: process.env.AUTOCXWEBUI_PYTHON || "python.exe",
  };
}

function configureNavigation(window, baseUrl) {
  const backendOrigin = new URL(baseUrl).origin;
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (!isInternalNavigation(url, backendOrigin)) {
      const target = externalHttpUrl(url);
      if (target) shell.openExternal(target).catch(() => {});
    }
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (isInternalNavigation(url, backendOrigin)) return;
    event.preventDefault();
    const target = externalHttpUrl(url);
    if (target) shell.openExternal(target).catch(() => {});
  });
}

function createOrReuseWindow(baseUrl) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    mainWindow = new BrowserWindow({
      width: 1280,
      height: 850,
      minWidth: 920,
      minHeight: 640,
      show: false,
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    mainWindow.once("ready-to-show", () => {
      if (!smokeMode && mainWindow) mainWindow.show();
    });
    mainWindow.on("closed", () => { mainWindow = null; });
  }
  configureNavigation(mainWindow, baseUrl);
  return mainWindow.loadURL(baseUrl);
}

async function startDesktop() {
  const port = await selectLoopbackPort();
  const paths = runtimePaths();
  const shutdownToken = randomBytes(32).toString("hex");
  const current = await startBackend({
    ...paths,
    dataDir: process.env.AUTOCXWEBUI_DATA_DIR || app.getPath("userData"),
    port,
    shutdownToken,
  });
  backend = { ...current, shutdownToken };
  backend.child.once("exit", (code, signal) => {
    if (quitting || backend?.child !== current.child) return;
    backend = null;
    void handleBackendExit(code, signal, current.getOutput());
  });
  await createOrReuseWindow(current.baseUrl);
  if (smokeMode) {
    const marker = process.env.AUTOCXWEBUI_ELECTRON_SMOKE_READY_FILE;
    if (marker) fs.writeFileSync(marker, `READY ${current.baseUrl}\n`, "utf8");
    setTimeout(() => app.quit(), 150);
  }
}

async function handleBackendExit(code, signal, output) {
  if (exitDialogOpen || quitting) return;
  exitDialogOpen = true;
  const detail = [
    `后端进程已退出（code=${code ?? "-"}, signal=${signal ?? "-"}）。`,
    output,
  ].filter(Boolean).join("\n\n");
  try {
    const result = await dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "CourseArk 服务已停止",
      message: "本机服务意外退出。",
      detail,
      buttons: ["重新启动", "退出应用"],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    });
    if (result.response === 0) {
      await startDesktop();
    } else {
      app.quit();
    }
  } catch (error) {
    dialog.showErrorBox("CourseArk 无法重新启动", error.message);
    app.quit();
  } finally {
    exitDialogOpen = false;
  }
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(startDesktop).catch((error) => {
    if (smokeMode) {
      const marker = process.env.AUTOCXWEBUI_ELECTRON_SMOKE_READY_FILE;
      if (marker) fs.writeFileSync(marker, `ERROR ${error.stack || error.message}\n`, "utf8");
      process.exitCode = 1;
    } else {
      dialog.showErrorBox("CourseArk 启动失败", error.message);
    }
    app.quit();
  });

  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    const current = backend;
    backend = null;
    Promise.resolve(current ? stopBackend({
      child: current.child,
      baseUrl: current.baseUrl,
      shutdownToken: current.shutdownToken,
    }) : undefined).catch(() => {}).finally(() => app.quit());
  });
}
