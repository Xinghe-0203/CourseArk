import { describe, expect, it } from "vitest";
import {
  canResume,
  dismissedResumeTasks,
  isResumeDismissed,
  latestUnfinished,
  missionState,
  missionTotals,
  nextDismissedResumeTasks,
  resumableTasks,
  unfinishedTotal,
  unfinishedUnits,
  visibleLatestUnfinished,
  visibleResumableTasks,
  visibleUnfinishedTotal,
} from "./mission";
import type { Course, Settings, Task } from "./types";

function course(partial: Partial<Course>): Course {
  return {
    course_id: "c1",
    class_id: "k1",
    cpi: "1",
    name: "测试课程",
    author: "老师",
    if_open: true,
    mission_fn: 0,
    mission_all: 0,
    ...partial,
  };
}
function task(partial: Partial<Task>): Task {
  return {
    course_id: "c1",
    class_id: "k1",
    id: "t1",
    account_id: "a1",
    account_label: "账号 01",
    course_name: "测试课程",
    feature: "course_all",
    feature_label: "课程任务点",
    status: "interrupted",
    stage: "",
    error: "",
    created_at: 100,
    started_at: 100,
    finished_at: 0,
    stats: {},
    params: {},
    progress: {
      percent: null,
      completed: 0,
      total: 0,
      failed: 0,
      blocked: 0,
      sealed: false,
      active: [],
    },
    ...partial,
  } as Task;
}

describe("missionState", () => {
  it("显示已完成 x / y 并在有待完成时高亮", () => {
    const state = missionState(course({ mission_fn: 109, mission_all: 125 }));
    expect(state.text).toBe("已完成 109 / 125，待完成 16");
    expect(state.tone).toBe("pending");
    expect(state.pending).toBe(16);
    expect(state.percent).toBe(87);
  });
  it("全部完成不显示待完成", () => {
    const state = missionState(course({ mission_fn: 27, mission_all: 27 }));
    expect(state.text).toBe("已完成 27 / 27");
    expect(state.tone).toBe("ok");
    expect(state.percent).toBe(100);
  });
  it("mission_all 为 0 且已同步时提示任务点未同步", () => {
    expect(
      missionState(course({ mission_fn: 0, mission_all: 0, synced_at: 1700000000 }))
        .text,
    ).toBe("任务点未同步");
    expect(missionState(course({ mission_fn: 0, mission_all: 0 })).text).toBe(
      "等待同步",
    );
  });
  it("同步中优先显示同步状态", () => {
    expect(missionState(course({ mission_fn: 1, mission_all: 5 }), true).text).toBe(
      "同步中…",
    );
  });
});

describe("missionTotals", () => {
  it("汇总账号下所有课程的任务点", () => {
    const totals = missionTotals([
      course({ mission_fn: 109, mission_all: 125 }),
      course({ mission_fn: 27, mission_all: 27, synced_at: 1 }),
    ]);
    expect(totals).toEqual({ fn: 136, all: 152, synced: true });
  });
});

describe("续跑判定", () => {
  it("优先使用后端 unfinished_units，其次回退 stats.work.units", () => {
    expect(unfinishedUnits(task({ unfinished_units: 16 }))).toBe(16);
    expect(
      unfinishedUnits(
        task({
          stats: {
            work: {
              units: {
                "1": { status: "succeeded" },
                "2": { status: "blocked" },
                "3": { status: "running" },
                "4": { status: "failed" },
                "5": {},
              },
            },
          },
        }),
      ),
    ).toBe(3);
    expect(unfinishedUnits(task({}))).toBe(0);
  });
  it("只有中断/停止/失败且仍有未完成项时提示继续执行", () => {
    expect(canResume(task({ status: "interrupted" }))).toBe(true);
    expect(canResume(task({ status: "running" }))).toBe(false);
    const tasks = [
      task({ id: "a", status: "interrupted", unfinished_units: 3, created_at: 10 }),
      task({ id: "b", status: "stopped", unfinished_units: 0, created_at: 20 }),
      task({ id: "c", status: "failed", unfinished_units: 2, created_at: 30 }),
    ];
    expect(resumableTasks(tasks).map((t) => t.id)).toEqual(["a", "c"]);
    expect(unfinishedTotal(tasks)).toBe(5);
    expect(latestUnfinished(tasks)?.id).toBe("c");
  });
});

describe("不再提醒（settings.ui.dismissed_resume_tasks）", () => {
  const tasks = [
    task({ id: "a", status: "interrupted", unfinished_units: 3, created_at: 10 }),
    task({ id: "b", status: "stopped", unfinished_units: 2, created_at: 20 }),
  ];
  const settings = (ids: string[]) =>
    ({ ui: { dismissed_resume_tasks: ids } }) as unknown as Settings;

  it("只隐藏列表内的 id，其余中断任务照常提醒", () => {
    expect(visibleResumableTasks(tasks, settings([])).map((t) => t.id)).toEqual([
      "a",
      "b",
    ]);
    expect(visibleResumableTasks(tasks, settings(["a"])).map((t) => t.id)).toEqual([
      "b",
    ]);
    expect(visibleUnfinishedTotal(tasks, settings(["a"]))).toBe(2);
    expect(visibleLatestUnfinished(tasks, settings(["a"]))?.id).toBe("b");
  });

  it("新任务不在列表内时仍然提醒（不发全局开关）", () => {
    const fresh = task({
      id: "new",
      status: "failed",
      unfinished_units: 4,
      created_at: 99,
    });
    const visible = visibleResumableTasks([...tasks, fresh], settings(["a", "b"]));
    expect(visible.map((t) => t.id)).toEqual(["new"]);
    expect(visibleLatestUnfinished([...tasks, fresh], settings(["a", "b"]))?.id).toBe(
      "new",
    );
  });

  it("损坏的设置值按空列表处理，不会误隐藏", () => {
    expect(dismissedResumeTasks(null)).toEqual([]);
    expect(dismissedResumeTasks({ ui: { dismissed_resume_tasks: "a" } } as never)).toEqual(
      [],
    );
    expect(isResumeDismissed(tasks[0]!, settings([]))).toBe(false);
    expect(isResumeDismissed(tasks[0]!, settings(["a"]))).toBe(true);
  });

  it("重复点击去重且只保留最近 100 条", () => {
    expect(nextDismissedResumeTasks(settings(["a", "b"]), "a")).toEqual(["b", "a"]);
    const many = Array.from({ length: 100 }, (_, i) => `t${i}`);
    const next = nextDismissedResumeTasks(settings(many), "latest");
    expect(next.length).toBe(100);
    expect(next.at(-1)).toBe("latest");
    expect(next).not.toContain("t0");
  });
});
