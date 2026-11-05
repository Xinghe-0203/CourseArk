import { describe, it, expect } from "vitest";
import {
  executionProfiles,
  summarizeWork,
  queueReason,
  overviewCounts,
  engineTotals,
} from "./overview";
import type { AccountWorkspace, Overview, Task } from "./types";

describe("执行总览的范围", () => {
  it("只保留执行账号和课程，同课程不同班级隔离，缓存缺失仍显示任务", () => {
    const profiles = [
      {
        account: { id: "a" },
        courses: [
          { course_id: "c", class_id: "1", cpi: "p", name: "课程" },
          { course_id: "idle", class_id: "2", name: "空闲课程" },
        ],
        tasks: [
          {
            id: "1",
            status: "running",
            course_id: "c",
            class_id: "1",
            cpi: "p",
            course_name: "课程",
          },
          {
            id: "2",
            status: "logging_in",
            course_id: "c",
            class_id: "3",
            cpi: "q",
            course_name: "另一班级",
          },
          {
            id: "3",
            status: "running",
            course_id: "c",
            class_id: "1",
            cpi: "p",
            course_name: "课程",
          },
          { id: "4", status: "paused", course_id: "idle", class_id: "2" },
        ],
      },
      {
        account: { id: "b" },
        courses: [],
        tasks: [
          { status: "succeeded" },
          { status: "pending" },
          { status: "failed" },
        ],
      },
    ] as AccountWorkspace[];
    const result = executionProfiles(profiles);
    expect(result.map((p) => p.account.id)).toEqual(["a"]);
    expect(result[0]!.tasks.map((t) => t.id)).toEqual(["1", "2", "3"]);
    expect(result[0]!.courses.map((c) => c.tasks.length)).toEqual([2, 1]);
    expect(result[0]!.courses[1]!.cached).toBeUndefined();
    expect(result[0]!.courses.map((c) => c.name)).toEqual(["课程", "另一班级"]);
  });
});

describe("summarizeWork", () => {
  it("汇总 stats.work 的四项计数，缺失与脏值按 0 处理", () => {
    expect(
      summarizeWork({ stats: { work: { completed: 3, total: 8, failed: 1 } } }),
    ).toEqual({ completed: 3, total: 8, failed: 1, blocked: 0 });
    expect(summarizeWork({ stats: {} })).toEqual({
      completed: 0,
      total: 0,
      failed: 0,
      blocked: 0,
    });
    expect(summarizeWork({ stats: { work: { completed: "x" } } }).completed).toBe(
      0,
    );
  });
});

describe("queueReason", () => {
  const base = {
    id: "t1",
    account_id: "a",
    account_label: "学员",
    course_name: "课程",
    feature: "course_all",
    feature_label: "课程任务点",
    status: "pending",
    stage: "",
    created_at: 0,
  };
  it("pending 报等待执行槽，paused 报剩余待继续项数", () => {
    expect(
      queueReason({
        ...base,
        status: "pending",
        stats: {},
      }),
    ).toBe("等待空闲执行槽");
    expect(
      queueReason({
        ...base,
        status: "paused",
        stats: { work: { completed: 3, total: 8 } },
      }),
    ).toBe("已暂停 · 剩 5 项待继续");
    expect(queueReason({ ...base, status: "paused", stats: {} })).toBe(
      "已暂停",
    );
  });
  it("执行中优先报活动名，否则回退状态文案", () => {
    expect(
      queueReason({
        ...base,
        status: "running",
        stats: { activity: { name: "播放视频" } },
      }),
    ).toBe("正在播放视频");
    expect(queueReason({ ...base, status: "starting", stats: {} })).toBe(
      "准备中",
    );
  });
});

describe("overviewCounts", () => {
  const workspaces = [
    { account: { id: "a" }, courses: [{ course_id: "1" }, { course_id: "2" }] },
    { account: { id: "b" }, courses: [{ course_id: "3" }] },
  ] as unknown as AccountWorkspace[];
  it("有 overview 时用真值账号数，课程数沿用工作台缓存", () => {
    const overview = { accounts: { total: 6 } } as Overview;
    expect(overviewCounts(overview, workspaces)).toEqual({
      accounts: 6,
      courses: 3,
    });
  });
  it("overview 缺席时回退本地工作台", () => {
    expect(overviewCounts(null, workspaces)).toEqual({
      accounts: 2,
      courses: 3,
    });
  });
});

describe("engineTotals", () => {
  const tasks = [
    { status: "running" },
    { status: "starting" },
    { status: "paused" },
    { status: "pending" },
    { status: "succeeded" },
  ] as Task[];
  it("有 overview 时直接用后端口径", () => {
    const overview = {
      tasks: { active: 2, paused: 1, pending: 1 },
    } as Overview;
    expect(engineTotals(overview, tasks)).toEqual({
      running: 2,
      paused: 1,
      pending: 1,
    });
  });
  it("overview 缺席时回退本地任务统计", () => {
    expect(engineTotals(null, tasks)).toEqual({
      running: 2,
      paused: 1,
      pending: 1,
    });
  });
});
