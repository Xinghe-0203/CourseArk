import { describe, it, expect } from "vitest";
import { executionProfiles } from "./overview";
import type { AccountWorkspace } from "./types";
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
