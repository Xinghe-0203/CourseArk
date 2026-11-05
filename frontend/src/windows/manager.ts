// T9 WindowManager：页面内浮层小窗的注册表（实例状态 + z 序 + 持久化）。
// 网页端浮层形态先行；T14 桌面桥就绪后浮层组件双端共用，升级为真子窗。
import { reactive } from "vue";

export type WindowKind = "progress" | "answers" | "alerts";

export interface WindowState {
  kind: WindowKind;
  open: boolean;
  minimized: boolean;
  // 浮层几何（页面内浮层即像素偏移；桌面端映射为窗口 x/y/w/h）。
  x: number;
  y: number;
  w: number;
  h: number;
}

export const MAX_WINDOWS = 3;

const STORAGE_PREFIX = "courseark.windows.";
const DEFAULTS: Record<WindowKind, Omit<WindowState, "kind" | "open">> = {
  progress: { minimized: true, x: 0, y: 0, w: 320, h: 0 },
  answers: { minimized: false, x: 24, y: 24, w: 360, h: 420 },
  alerts: { minimized: false, x: 24, y: 96, w: 360, h: 320 },
};

function loadPersisted(kind: WindowKind): Partial<WindowState> {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + kind);
    return raw ? (JSON.parse(raw) as Partial<WindowState>) : {};
  } catch {
    return {};
  }
}

function persist(win: WindowState) {
  try {
    const { kind, open: _open, ...rest } = win;
    localStorage.setItem(STORAGE_PREFIX + kind, JSON.stringify(rest));
  } catch {
    /* 隐私模式等 localStorage 不可用时静默降级为会话内状态 */
  }
}

/** 浮层注册表：kind → 状态；zOrder[末位] 为最顶层。 */
export const windows = reactive({
  map: {} as Record<WindowKind, WindowState | undefined>,
  zOrder: [] as WindowKind[],
});

/** 默认开启的小窗（进度小窗维持既有行为：候选存在即显示）。 */
export function ensureWindow(kind: WindowKind): WindowState {
  let win = windows.map[kind];
  if (!win) {
    win = reactive({
      kind,
      open: true,
      ...DEFAULTS[kind],
      ...loadPersisted(kind),
    });
    windows.map[kind] = win;
    windows.zOrder.push(kind);
  }
  return win;
}

/** 打开小窗（注册 + 置顶）；超过上限时拒绝并返回 null。 */
export function openWindow(kind: WindowKind): WindowState | null {
  const known = Object.keys(windows.map) as WindowKind[];
  if (!windows.map[kind] && known.length >= MAX_WINDOWS) return null;
  const win = ensureWindow(kind);
  win.open = true;
  focusWindow(kind);
  persist(win);
  return win;
}

export function closeWindow(kind: WindowKind) {
  const win = windows.map[kind];
  if (!win) return;
  win.open = false;
  persist(win);
}

export function focusWindow(kind: WindowKind) {
  const index = windows.zOrder.indexOf(kind);
  if (index >= 0) windows.zOrder.splice(index, 1);
  windows.zOrder.push(kind);
}

export function toggleMinimized(kind: WindowKind) {
  const win = windows.map[kind];
  if (!win) return;
  win.minimized = !win.minimized;
  persist(win);
}

export function moveWindow(kind: WindowKind, x: number, y: number) {
  const win = windows.map[kind];
  if (!win) return;
  win.x = Math.max(0, Math.round(x));
  win.y = Math.max(0, Math.round(y));
  persist(win);
}

/** 恢复默认几何（不重置开合与最小化）。 */
export function resetWindowLayout(kind: WindowKind) {
  const win = windows.map[kind];
  if (!win) return;
  Object.assign(win, DEFAULTS[kind]);
  persist(win);
}
