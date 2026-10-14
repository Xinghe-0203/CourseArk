import { describe, it, expect } from "vitest";
import { groupTasks, percent, chapters } from "./format";
import type { Task } from "./types";
describe("账号分组与真实进度", () => {
  it("不同账号的同名课程分开，同账号的课程聚在一起", () => {
    const tasks = [
      { id: "1", account_id: "a", account_label: "甲" },
      { id: "2", account_id: "b", account_label: "乙" },
      { id: "3", account_id: "a", account_label: "甲" },
    ] as Task[];
    const groups = groupTasks(tasks);
    expect(groups.map((g) => g.tasks.map((t) => t.id))).toEqual([
      ["1", "3"],
      ["2"],
    ]);
  });
  it("未知进度保留未知，零值不会变成阶段估计", () => {
    expect(
      percent({
        status: "running",
        stats: {},
        progress: { percent: null },
      } as Task),
    ).toBeNull();
    expect(percent({ progress: { percent: 0 } } as Task)).toBe(0);
    expect(percent({ progress: { percent: 42.5 } } as Task)).toBe(42.5);
  });
  it("章节编号支持中文分隔并去重", () =>
    expect(chapters("123，456;123 789、789")).toEqual(["123", "456", "789"]));
});
