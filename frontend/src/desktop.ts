// T14：桌面端能力探测与迷你监控子窗调用。
// 浏览器端无 window.coursearkDesktop（preload 只在 Electron 里注入），
// 所有调用点据此静默降级，页面逻辑不需要区分运行环境。
export interface CoursearkDesktopBridge {
  openMini: () => Promise<boolean>;
  closeMini: () => Promise<boolean>;
}

export function isDesktop(): boolean {
  return typeof window !== "undefined" && !!window.coursearkDesktop;
}

export function desktopBridge(): CoursearkDesktopBridge | null {
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
