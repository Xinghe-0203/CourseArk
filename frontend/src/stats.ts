import { active } from "./format";
import type { AccountWorkspace, Task } from "./types";

/**
 * 全局工作空间口径：总览、学习任务、顶栏统计共用同一套数字，
 * 避免同一批账号在不同页面显示不同的课程数。
 */
export function workspaceStats(workspaces: AccountWorkspace[], tasks: Task[]) {
  const enabled = workspaces.filter((item) => item.account.enabled);
  return {
    // 已添加的账号总数（含停用账号）。
    accounts: workspaces.length,
    // 已启用、会参与执行的账号数。
    enabled: enabled.length,
    // 已同步课程总数：与学习任务页列出的课程条数一致。
    courses: workspaces.reduce((sum, item) => sum + item.courses.length, 0),
    // 当前可创建任务的课程数（平台标记为开放）。
    learnable: enabled.reduce(
      (sum, item) => sum + item.courses.filter((course) => course.if_open).length,
      0,
    ),
    // 正在执行（含准备、登录、读取课程、暂停/停止中）的任务数。
    running: tasks.filter(active).length,
    // 已暂停但未结束的任务数。
    paused: tasks.filter((task) => task.status === "paused").length,
    // 终态里需要人工核对的任务数。
    issues: tasks.filter(
      (task) => task.status === "failed" || task.status === "interrupted",
    ).length,
  };
}
