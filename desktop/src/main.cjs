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

// T15：通用子窗注册表——route 片段（如 "mini"）→ BrowserWindow。
// 关闭=隐藏（窗口对象保留，可随时复现），主窗销毁才随应用真正退出。
const childWindows = new Map();

// 内置窗口形态预设；迷你监控是第一个预设（T14 形态不变）。
const WINDOW_PRESETS = {
  mini: {
    title: "课舟 · 迷你监控",
    width: 340,
    height: 220,
    minWidth: 280,
    minHeight: 160,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
  },
};

// 未注册 route 的兜底形态：仍可开通用小窗（渲染端可覆盖字段）。
const FALLBACK_PRESET = {
  title: "课舟窗口",
  width: 360,
  height: 420,
  minWidth: 240,
  minHeight: 160,
};

// 渲染进程允许覆盖的字段白名单——其余 BrowserWindow 选项一律不透传。
const PRESET_KEYS = ["title", "width", "height", "minWidth", "minHeight", "frame", "alwaysOnTop", "skipTaskbar"];

function resolvePreset(route, override) {
  const preset = { ...(WINDOW_PRESETS[route] || FALLBACK_PRESET) };
  if (override && typeof override === "object") {
    for (const key of PRESET_KEYS) {
      if (override[key] !== undefined) preset[key] = override[key];
    }
  }
  // 钳制下限，防止渲染端开出 0 尺寸/负尺寸窗口。
  preset.width = Math.max(200, Number(preset.width) || FALLBACK_PRESET.width);
  preset.height = Math.max(140, Number(preset.height) || FALLBACK_PRESET.height);
  preset.minWidth = Math.max(120, Number(preset.minWidth) || FALLBACK_PRESET.minWidth);
  preset.minHeight = Math.max(100, Number(preset.minHeight) || FALLBACK_PRESET.minHeight);
  return preset;
}

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

// T15：通用子窗工厂——按 route 片段建/复用窗口，形态=preset 覆盖项+钳制，
// 加载 `${baseUrl}/#/${route}`。注册表以 route 为键（同 route 单实例）。
function createChildWindow(baseUrl, route, override) {
  if (!route || typeof route !== "string") return null;
  const preset = resolvePreset(route, override);
  const existing = childWindows.get(route);
  if (existing && !existing.isDestroyed()) return existing;
  const win = new BrowserWindow({
    width: preset.width,
    height: preset.height,
    minWidth: preset.minWidth,
    minHeight: preset.minHeight,
    show: false,
    frame: preset.frame !== false,
    title: typeof preset.title === "string" && preset.title ? preset.title : "课舟窗口",
    autoHideMenuBar: preset.skipTaskbar !== true,
    alwaysOnTop: preset.alwaysOnTop === true,
    skipTaskbar: preset.skipTaskbar === true,
    backgroundColor: "#ffffff",
    icon: windowIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  if (preset.alwaysOnTop === true) win.setAlwaysOnTop(true, "screen-saver");
  win.on("closed", () => {
    if (childWindows.get(route) === win) childWindows.delete(route);
  });
  configureNavigation(win, baseUrl);
  win.loadURL(`${baseUrl}/#/${route}`);
  childWindows.set(route, win);
  return win;
}

// 关闭子窗=隐藏（窗口对象保留在注册表，可随时复现）。
function closeChildWindow(route) {
  const win = childWindows.get(route);
  if (!win || win.isDestroyed()) return true;
  win.hide();
  return true;
}

// 打开（或复现）一个子窗；后端未就绪返回 false。
async function openChildWindow(route, override) {
  const current = backend;
  if (!current || !route || typeof route !== "string") return false;
  const win = createChildWindow(current.baseUrl, route, override);
  if (!win) return false;
  if (mainWindow && !mainWindow.isDestroyed() && mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  if (!win.isVisible()) win.show();
  win.focus();
  return true;
}

async function startDesktop() {
  const { ipcMain } = require("electron");
  // T15：通用窗口 IPC。mini:open / mini:close 保留为迷你窗的语义别名，
  // windows:open / windows:close 是带 route 参数的通用入口。
  ipcMain.handle("mini:open", () => openChildWindow("mini"));
  ipcMain.handle("mini:close", () => closeChildWindow("mini"));
  ipcMain.handle("windows:open", (_event, route, preset) => {
    const key = typeof route === "string" ? route : "";
    return openChildWindow(key, preset);
  });
  ipcMain.handle("windows:close", (_event, route) => {
    const key = typeof route === "string" ? route : "";
    return closeChildWindow(key);
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
    // T15：聚焦扩展到注册表内全部子窗（不抢最小化，只前置已可见的）。
    for (const win of childWindows.values()) {
      if (win && !win.isDestroyed() && win.isVisible()) win.focus();
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
    // 主窗随应用退出时连带销毁全部注册表子窗（hide 语义下窗口对象还在）。
    for (const win of childWindows.values()) {
      if (win && !win.isDestroyed()) win.destroy();
    }
    childWindows.clear();
    const current = backend;
    backend = null;
    Promise.resolve(current ? stopBackend({
      child: current.child,
      baseUrl: current.baseUrl,
      shutdownToken: current.shutdownToken,
    }) : undefined).catch(() => {}).finally(() => app.quit());
  });
}
