// T14：桌面端能力探测与迷你监控子窗调用。
// 浏览器端无 window.coursearkDesktop（preload 只在 Electron 里注入），
// 所有调用点据此静默降级，页面逻辑不需要区分运行环境。
// 类型定义只有一份，放在 types.ts 里（桌面壳与前端共用同一套字段）。
import type {
  CoursearkDesktop,
  DesktopVerifyCaptured,
  DesktopVerifyPayload,
  DesktopWindowPreset,
} from "./types";

export type {
  CoursearkDesktop,
  DesktopVerifyCaptured,
  DesktopVerifyPayload,
  DesktopWindowPreset,
};

export function isDesktop(): boolean {
  return typeof window !== "undefined" && !!window.coursearkDesktop;
}

export function desktopBridge(): CoursearkDesktop | null {
  if (!isDesktop()) return null;
  return window.coursearkDesktop ?? null;
}

/** 打开迷你监控子窗；非桌面环境返回 false（调用方无需特判 UI）。 */
export function openDesktopMini(): Promise<boolean> {
  return desktopBridge()?.openMini() ?? Promise.resolve(false);
}

/** 关闭迷你监控子窗；非桌面环境无操作。 */
export function closeDesktopMini(): Promise<boolean> {
  return desktopBridge()?.closeMini() ?? Promise.resolve(false);
}

/** T15：打开通用桌面小窗（route 为前端 hash 片段）；非桌面环境返回 false。 */
export function openDesktopWindow(route: string, preset?: DesktopWindowPreset): Promise<boolean> {
  return desktopBridge()?.openWindow(route, preset) ?? Promise.resolve(false);
}

/** T15：按 route 关闭通用桌面小窗；非桌面环境无操作。 */
export function closeDesktopWindow(route: string): Promise<boolean> {
  return desktopBridge()?.closeWindow(route) ?? Promise.resolve(false);
}

/** T16：打开应用内安全验证窗；非桌面环境返回 false（调用方走系统浏览器兜底）。 */
export function openDesktopVerify(payload: DesktopVerifyPayload): Promise<boolean> {
  return desktopBridge()?.openVerify(payload) ?? Promise.resolve(false);
}

/** T16：订阅验证窗捕获的答题页地址；非桌面环境不会收到回调。 */
export function onDesktopVerifyCaptured(
  handler: (data: DesktopVerifyCaptured) => void,
): void {
  desktopBridge()?.onVerifyCaptured(handler);
}
