// T14：桌面端 preload 桥。contextIsolation+sandbox:true 下，渲染进程唯一的
// 特权入口是 contextBridge.exposeInMainWorld——只暴露极小的命令面（开/关迷你窗），
// 不传任何 Node 能力。功能探测靠 window.coursearkDesktop 是否存在。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("coursearkDesktop", {
  /** 打开迷你监控子窗（紧凑进度条）；桌面端可用，浏览器端无此全局。 */
  openMini: () => ipcRenderer.invoke("mini:open"),
  /** 关闭迷你监控子窗。 */
  closeMini: () => ipcRenderer.invoke("mini:close"),
});
