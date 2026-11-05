const path = require("node:path");
const fs = require("node:fs");
const { randomBytes } = require("node:crypto");
const { app, BrowserWindow, dialog, shell } = require("electron");

const { isInternalNavigation, externalHttpUrl } = require("./navigation-policy.cjs");
const { selectLoopbackPort, startBackend, stopBackend } = require("./server-manager.cjs");

// Keep the legacy app name so existing user data remains in %APPDATA%\AutoCxWebUI.
app.setName("AutoCxWebUI");

let mainWindow = null;
let miniWindow = null;
let miniHidden = false; // 关闭迷你窗=隐藏（应用还在跑），主窗销毁才真正关。
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

function windowIconPath() {
  const icon = path.join(__dirname, "..", "assets", "icon.ico");
  return fs.existsSync(icon) ? icon : undefined;
}

function createOrReuseWindow(baseUrl) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    mainWindow = new BrowserWindow({
      width: 1280,
      height: 850,
      minWidth: 920,
      minHeight: 640,
      show: false,
      title: "课舟 CourseArk",
      backgroundColor: "#f5f7fb",
      autoHideMenuBar: true,
      icon: windowIconPath(),
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
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

// T14：迷你监控子窗——无边框置顶小条，加载前端的 /#/mini 紧凑视图。
function createMiniWindow(baseUrl) {
  if (miniWindow && !miniWindow.isDestroyed()) return miniWindow;
  miniWindow = new BrowserWindow({
    width: 340,
    height: 220,
    minWidth: 280,
    minHeight: 160,
    show: false,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    title: "课舟 · 迷你监控",
    backgroundColor: "#ffffff",
    icon: windowIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  miniWindow.setAlwaysOnTop(true, "screen-saver");
  miniWindow.on("closed", () => { miniWindow = null; });
  configureNavigation(miniWindow, baseUrl);
  miniWindow.loadURL(`${baseUrl}/#/mini`);
  return miniWindow;
}

async function openMiniWindow() {
  miniHidden = false;
  const current = backend;
  if (!current) return false;
  const win = createMiniWindow(current.baseUrl);
  if (mainWindow && !mainWindow.isDestroyed() && mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  if (!win.isVisible()) win.show();
  win.focus();
  return true;
}

async function startDesktop() {
  const { ipcMain } = require("electron");
  ipcMain.handle("mini:open", () => openMiniWindow());
  ipcMain.handle("mini:close", () => {
    miniHidden = true;
    if (miniWindow && !miniWindow.isDestroyed()) miniWindow.hide();
    return true;
  });
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

  app.on("window-all-closed", () => {
    // T14 语义修正：迷你子窗关闭（隐藏）不算退出信号——应用随主窗生命周期。
    // 主窗销毁后剩余窗口为空时才退出；后台服务由 before-quit 统一收尾。
    const mainAlive = mainWindow && !mainWindow.isDestroyed();
    if (!mainAlive) app.quit();
  });
  app.on("before-quit", (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    // 主窗随应用退出时连带关闭迷你子窗（hide 语义下窗口对象还在）。
    if (miniWindow && !miniWindow.isDestroyed()) miniWindow.destroy();
    const current = backend;
    backend = null;
    Promise.resolve(current ? stopBackend({
      child: current.child,
      baseUrl: current.baseUrl,
      shutdownToken: current.shutdownToken,
    }) : undefined).catch(() => {}).finally(() => app.quit());
  });
}
