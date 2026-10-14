import { active } from "./format";
import type { AccountWorkspace } from "./types";

// 以任务身份确定课程范围；同步缓存缺失时仍保留正在执行的课程。
export function executionProfiles(workspaces: AccountWorkspace[]) {
  return workspaces.flatMap((p) => {
    const tasks = p.tasks.filter(active);
    if (!tasks.length) return [];
    const groups = new Map<
      string,
      {
        name: string;
        cached?: AccountWorkspace["courses"][number];
        tasks: typeof tasks;
      }
    >();
    for (const task of tasks) {
      const key = [task.course_id, task.class_id, task.cpi || ""].join(":");
      if (!groups.has(key))
        groups.set(key, {
          name: task.course_name,
          cached: p.courses.find(
            (c) =>
              c.course_id === task.course_id &&
              c.class_id === task.class_id &&
              (!task.cpi || c.cpi === task.cpi),
          ),
          tasks: [],
        });
      groups.get(key)!.tasks.push(task);
    }
    return [{ account: p.account, tasks, courses: [...groups.values()] }];
  });
}
