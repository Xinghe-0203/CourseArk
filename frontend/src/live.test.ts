import { describe, expect, it } from "vitest";
import type { Task, TaskLive } from "./types";
import {
  activityOf,
  elapsedSeconds,
  focusTask,
  formatDuration,
  formatEta,
  runningSummary,
  unitPercent,
  unitText,
} from "./live";

const task = (patch: Partial<Task> = {}): Task =>
  ({
    id: "t1",
    account_id: "a1",
    account_label: "账号 01",
    course_name: "大学英语",
    feature: "independent_homework",
    feature_label: "独立作业",
    status: "running",
    stage: "exam",
    error: "",
    created_at: 0,
    started_at: 0,
    finished_at: 0,
    stats: {},
    params: {},
    progress: { percent: null, completed: 0, total: 0, failed: 0, blocked: 0, sealed: false, active: [] },
    ...patch,
  }) as Task;

const live = (patch: Partial<TaskLive> = {}): TaskLive => ({
  activity: "正在学习 · 第二章 · 240 / 480",
  elapsed_seconds: 120,
  eta_seconds: 90,
  unit: { label: "第二章", current: 240, total: 480 },
  eta_source: "unit",
  ...patch,
});

describe("live 进度格式化", () => {
  it("把秒数格式化为 hh:mm:ss", () => {
    expect(formatDuration(0)).toBe("00:00:00");
    expect(formatDuration(754)).toBe("00:12:34");
    expect(formatDuration(3725)).toBe("01:02:05");
    expect(formatDuration(undefined)).toBe("--:--:--");
    expect(formatEta(null)).toBe("计算中");
    expect(formatEta(90)).toBe("00:01:30");
  });

  it("当前项进度显示百分比与文字", () => {
    expect(unitPercent({ label: "第二讲", current: 120, total: 600 })).toBe(20);
    expect(unitPercent({ label: "", current: 0, total: 0 })).toBeNull();
    expect(unitPercent(null)).toBeNull();
    expect(unitText({ label: "第二讲", current: 120, total: 600 })).toBe(
      "第二讲 · 120 / 600",
    );
  });

  it("已用时优先 live，其次 started_at 兜底", () => {
    expect(elapsedSeconds(task({ live: live() }), 1000)).toBe(120);
    expect(elapsedSeconds(task({ started_at: 100 }), 400)).toBe(300);
    expect(elapsedSeconds(task({ started_at: 0 }), 10)).toBeNull();
    expect(
      elapsedSeconds(task({ started_at: 100, finished_at: 260 }), 999),
    ).toBe(160);
  });

  it("动作与行摘要缺失 live 时优雅降级", () => {
    expect(activityOf(task({ live: live() }))).toContain("正在学习");
    expect(
      activityOf(
        task({
          progress: {
            percent: null,
            completed: 0,
            total: 0,
            failed: 0,
            blocked: 0,
            sealed: false,
            active: [{ id: "u1", name: "第二章", kind: "video" }],
          },
        }),
      ),
    ).toBe("正在处理「第二章」");
    expect(activityOf(task({ status: "logging_in" }))).toBe("正在登录学习通");
    expect(activityOf(task({}))).toBe("正在准备任务");
    expect(runningSummary(task({ live: live() }))).toEqual({
      activity: "正在学习 · 第二章 · 240 / 480",
      eta: "00:01:30",
    });
    expect(runningSummary(task({ status: "succeeded" }))).toBeNull();
    expect(runningSummary(task({}))?.eta).toBe("计算中");
  });

  it("小窗优先选择真正运行中的任务", () => {
    const paused = task({ id: "paused", status: "paused" });
    const running = task({ id: "running" });
    expect(focusTask([paused, running])?.id).toBe("running");
    expect(focusTask([paused])?.id).toBe("paused");
    expect(focusTask([task({ status: "succeeded" })])).toBeUndefined();
  });
});
