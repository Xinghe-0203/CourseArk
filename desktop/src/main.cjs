const path = require("node:path");
const fs = require("node:fs");
const { randomBytes } = require("node:crypto");
const { app, BrowserWindow, dialog, shell, session } = require("electron");

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

// ============================================================
// 应用内安全验证窗（T16）
// ============================================================
// 学习通对进入考试/作业做了平台侧校验（滑块、考试码、人脸）。程序不绕过
// 这些校验；本窗口用已保存的登录态打开平台页面，让用户手动完成验证，
// 同时被动监听答题页地址（302 / 请求 URL 里带 enc= 的 reVersionTestStartNew
// / doHomeWorkNew 等），捕获后连同窗口 Cookie 一起回传主窗。
// 窗口内不注入任何自动化脚本、不做程序化 DOM 操作——那是平台风控红线。

const CHAOXING_HOST_RE = /^https:\/\/([^/]*\.)?chaoxing\.(com|cn|org\.cn)\//;
const ANSWER_URL_RE =
  /reVersionTestStartNew|doHomeWorkNew|selectWorkQuestion|exam-ans\/exam\/(?:test|phone)\/start/;
const CAPTURE_URL_FILTER = [
  "*://*.chaoxing.com/*",
  "*://*.chaoxing.cn/*",
  "*://*.chaoxing.org.cn/*",
];

// 与 Python Worker 一致的桌面 Chrome UA：减少双端指纹差异（验证码与 enc 校验
// 都跟请求头相关，UA 漂移是同类项目踩过的坑）。
const CHAOXING_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/124.0.0.0 Safari/537.36";

function chaoxingCookieToElectron(cookie) {
  const domain = String(cookie.domain || ".chaoxing.com");
  const host = domain.replace(/^\./, "");
  const item = {
    url: `https://${host}${cookie.path || "/"}`,
    name: String(cookie.name),
    value: String(cookie.value ?? ""),
    domain,
    path: String(cookie.path || "/"),
  };
  const expires = Number(cookie.expires);
  if (Number.isFinite(expires) && expires > 0) item.expirationDate = expires;
  if (cookie.secure !== undefined) item.secure = Boolean(cookie.secure);
  if (cookie.httpOnly !== undefined) item.httpOnly = Boolean(cookie.httpOnly);
  return item;
}

async function injectChaoxingCookies(ses, cookies) {
  let injected = 0;
  for (const cookie of Array.isArray(cookies) ? cookies : []) {
    if (!cookie || !cookie.name) continue;
    try {
      await ses.setCookie(chaoxingCookieToElectron(cookie));
      injected += 1;
    } catch {
      // 单条 Cookie 失效（域/过期格式）不阻塞窗口打开，登录态主力字段一般在前几条
    }
  }
  return injected;
}

async function captureChaoxingCookies(ses) {
  try {
    const items = await ses.cookies.get({ domain: "chaoxing.com" });
    return items.map((item) => ({
      name: item.name,
      value: item.value,
      domain: item.domain,
      path: item.path,
      expires: item.expirationDate,
      secure: item.secure,
      httpOnly: item.httpOnly,
    }));
  } catch {
    return [];
  }
}

// 捕获到答题页地址：把地址与窗口 Cookie 一起发给主窗渲染进程
//（渲染端负责 Cookie 回写接口调用与「粘贴地址」字段预填）。
function reportCaptured(accountId, url, win) {
  win.setTitle("已捕获答题页地址，可回到课舟继续操作");
  if (!mainWindow || mainWindow.isDestroyed()) return;
  void captureChaoxingCookies(win.webContents.session).then((cookies) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("verify:captured", { accountId, url, cookies });
    }
  });
}

function attachAnswerCapture(win, accountId) {
  const filter = { urls: CAPTURE_URL_FILTER };
  let captured = "";
  const hit = (url) => {
    if (!url || !ANSWER_URL_RE.test(url) || !url.includes("enc=")) return;
    if (url === captured) return;
    captured = url;
    reportCaptured(accountId, url, win);
  };
  try {
    win.webContents.session.webRequest.onBeforeRedirect(filter, (details) => {
      // 302 的 Location 里带 enc=：验证通过后平台跳向答题页的第一落点
      hit(details.redirectURL || "");
    });
    win.webContents.session.webRequest.onCompleted(filter, (details) => {
      hit(details.url || "");
    });
  } catch {
    // webRequest 注册失败不影响「手动复制地址」的兜底路径
  }
}

async function openVerifyWindow(payload) {
  const accountId = typeof payload?.accountId === "string" ? payload.accountId : "";
  const url = typeof payload?.url === "string" ? payload.url : "";
  // accountId 直接拼进持久分区名，只放行安全字符
  if (!accountId || !/^[A-Za-z0-9_-]{1,64}$/.test(accountId)) return false;

  const key = `verify:${accountId}`;
  const existing = childWindows.get(key);
  if (existing && !existing.isDestroyed()) {
    if (!existing.isVisible()) existing.show();
    existing.focus();
    return true;
  }

  const ses = session.fromPartition(`persist:cx-${accountId}`);
  ses.setUserAgent(CHAOXING_UA);
  const injected = await injectChaoxingCookies(ses, payload?.cookies);

  const win = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 720,
    minHeight: 520,
    show: false,
    title: injected
      ? "学习通安全验证（已带入登录态，完成后自动返回）"
      : "学习通安全验证（请在页面内登录）",
    autoHideMenuBar: true,
    backgroundColor: "#ffffff",
    icon: windowIconPath(),
    webPreferences: {
      // 只读窗口：不挂 preload、不开任何 Node 能力，验证操作全部由用户手动完成
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      session: ses,
    },
  });
  // 导航策略：学习通域名留在窗内（平台会多次跳转），其它链接交给系统浏览器
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (CHAOXING_HOST_RE.test(target)) {
      setTimeout(() => win.loadURL(target).catch(() => {}), 0);
    } else {
      const external = externalHttpUrl(target);
      if (external) shell.openExternal(external).catch(() => {});
    }
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, target) => {
    if (CHAOXING_HOST_RE.test(target)) return;
    event.preventDefault();
    const external = externalHttpUrl(target);
    if (external) shell.openExternal(external).catch(() => {});
  });
  win.on("closed", () => {
    if (childWindows.get(key) === win) childWindows.delete(key);
  });

  attachAnswerCapture(win, accountId);
  const start = CHAOXING_HOST_RE.test(url)
    ? url
    : "https://i.chaoxing.com/";
  await win.loadURL(start);
  if (mainWindow && !mainWindow.isDestroyed() && mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  win.show();
  win.focus();
  childWindows.set(key, win);
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
  // T16：应用内安全验证窗（考试/作业人机验证 + 答题页地址被动捕获）。
  ipcMain.handle("verify:open", (_event, payload) => openVerifyWindow(payload));
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
