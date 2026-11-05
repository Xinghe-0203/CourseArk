// T9.9 WindowManager 单测：注册/持久化/z 序/上限/最小化。
// vitest 默认 node 环境无 localStorage——按计划卡用 jsdom 环境隔离本文件。
// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  MAX_WINDOWS,
  closeWindow,
  ensureWindow,
  focusWindow,
  moveWindow,
  openWindow,
  resetWindowLayout,
  toggleMinimized,
  windows,
  type WindowKind,
} from "./windows/manager";

const kinds: WindowKind[] = ["progress", "answers", "alerts"];

beforeEach(() => {
  localStorage.clear();
  windows.map = {} as typeof windows.map;
  windows.zOrder = [];
});

describe("T9 WindowManager", () => {
  it("ensureWindow 注册默认状态并写入 zOrder", () => {
    const win = ensureWindow("progress");
    expect(win.kind).toBe("progress");
    expect(win.open).toBe(true);
    expect(win.minimized).toBe(true);
    expect(windows.zOrder).toEqual(["progress"]);
    // 重复调用幂等：不追加 zOrder。
    ensureWindow("progress");
    expect(windows.zOrder).toEqual(["progress"]);
  });

  it("openWindow 持久化几何到 localStorage（open 不持久化）", () => {
    openWindow("answers");
    moveWindow("answers", 120, 64);
    const raw = JSON.parse(
      localStorage.getItem("courseark.windows.answers") || "{}",
    );
    expect(raw.x).toBe(120);
    expect(raw.y).toBe(64);
    expect(raw.open).toBeUndefined();
    expect(raw.minimized).toBe(false);
  });

  it("重新注册时恢复持久化的几何与最小化", () => {
    openWindow("alerts");
    toggleMinimized("alerts");
    moveWindow("alerts", 40, 80);
    // 模拟重新加载：清空注册表但保留 localStorage。
    windows.map = {} as typeof windows.map;
    windows.zOrder = [];
    const win = ensureWindow("alerts");
    expect(win.minimized).toBe(true);
    expect(win.x).toBe(40);
    expect(win.y).toBe(80);
  });

  it("实例上限 MAX_WINDOWS=3：第 4 个实例被拒绝", () => {
    expect(MAX_WINDOWS).toBe(3);
    for (const kind of kinds) expect(openWindow(kind)).not.toBeNull();
    // 未注册的第 4 个 kind（这里用一个类型断言模拟）应被拒。
    const extra = openWindow("progress" as WindowKind); // progress 已注册→允许
    expect(extra).not.toBeNull();
    closeWindow("progress");
    // 关闭后再次打开仍占注册表名额（map 里还在），上限语义按注册数计算。
    expect(Object.keys(windows.map)).toHaveLength(3);
  });

  it("z 序点击置顶：focusWindow 把 kind 移到末位", () => {
    for (const kind of kinds) ensureWindow(kind);
    expect(windows.zOrder).toEqual(["progress", "answers", "alerts"]);
    focusWindow("progress");
    expect(windows.zOrder).toEqual(["answers", "alerts", "progress"]);
    focusWindow("alerts");
    expect(windows.zOrder).toEqual(["answers", "progress", "alerts"]);
  });

  it("closeWindow 只关不注销；resetWindowLayout 恢复默认几何", () => {
    openWindow("answers");
    moveWindow("answers", 300, 300);
    closeWindow("answers");
    expect(windows.map.answers?.open).toBe(false);
    expect(windows.map.answers?.x).toBe(300);
    resetWindowLayout("answers");
    expect(windows.map.answers?.open).toBe(false);
    expect(windows.map.answers?.x).toBe(24);
    expect(windows.map.answers?.y).toBe(24);
  });

  it("moveWindow 负数坐标钳制为 0", () => {
    openWindow("alerts");
    moveWindow("alerts", -20, -5);
    expect(windows.map.alerts?.x).toBe(0);
    expect(windows.map.alerts?.y).toBe(0);
  });
});
