// T14：桌面端 preload 桥。contextIsolation+sandbox:true 下，渲染进程唯一的
// 特权入口是 contextBridge.exposeInMainWorld——只暴露极小的命令面（开/关迷你窗），
// 不传任何 Node 能力。功能探测靠 window.coursearkDesktop 是否存在。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("coursearkDesktop", {
  /** 打开迷你监控子窗（紧凑进度条）；桌面端可用，浏览器端无此全局。 */
  openMini: () => ipcRenderer.invoke("mini:open"),
  /** 关闭迷你监控子窗。 */
  closeMini: () => ipcRenderer.invoke("mini:close"),
  /** T15：通用小窗——route 为前端 hash 片段（如 "mini"），preset 可选覆盖形态。 */
  openWindow: (route, preset) => ipcRenderer.invoke("windows:open", route, preset),
  /** T15：按 route 关闭（隐藏）通用小窗。 */
  closeWindow: (route) => ipcRenderer.invoke("windows:close", route),
  /** T16：打开应用内安全验证窗（注入登录态 → 用户手动验证 → 捕获答题页地址）。 */
  openVerify: (payload) => ipcRenderer.invoke("verify:open", payload),
  /** T16：订阅验证窗捕获的答题页地址（含窗口 Cookie，渲染端负责回写）。 */
  onVerifyCaptured: (handler) => {
    ipcRenderer.on("verify:captured", (_event, data) => handler(data));
  },
});
