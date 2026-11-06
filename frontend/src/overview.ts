import { active, statuses } from "./format";
import type { AccountWorkspace, Overview, Task } from "./types";

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

/** 汇总单个任务的 work 单元计数。
 *  v2.4.0 起 /api/overview 只回传 stats.work 的 units 与 sealed（不再带
 *  completed/total/failed/blocked 汇总），所以这里以单元状态现算，旧字段存在时优先。 */
export function summarizeWork(task: Pick<Task, "stats">) {
  const work = (task.stats?.work ?? {}) as {
    completed?: number;
    total?: number;
    failed?: number;
    blocked?: number;
    units?: Record<string, { status?: string } | undefined>;
  };
  const units = work.units && typeof work.units === "object" ? Object.values(work.units) : [];
  const counted = (status: string) => units.filter((unit) => unit?.status === status).length;
  const derived = {
    completed: counted("succeeded"),
    total: units.length,
    failed: counted("failed"),
    blocked: counted("blocked"),
  };
  return {
    completed: Number(work.completed) || derived.completed,
    total: Number(work.total) || derived.total,
    failed: Number(work.failed) || derived.failed,
    blocked: Number(work.blocked) || derived.blocked,
  };
}

/** 调度队列一行的等待原因：执行中报活动，其余报状态与未完成单元。 */
export function queueReason(item: Overview["queue"][number]) {
  if (item.status === "pending") return "等待空闲执行槽";
  const work = summarizeWork(item);
  if (item.status === "paused") {
    const left = work.total > work.completed ? work.total - work.completed : 0;
    return left > 0 ? `已暂停 · 剩 ${left} 项待继续` : "已暂停";
  }
  const activity = (item.stats?.activity ?? {}) as { name?: string };
  return activity.name ? `正在${activity.name}` : statuses[item.status] || item.status;
}

/** /api/overview 的账号与课程数（种子真值 6/18 就来自这里）。 */
export function overviewCounts(overview: Overview | null, fallbackWorkspaces: AccountWorkspace[]) {
  if (overview)
    return {
      accounts: overview.accounts?.total ?? fallbackWorkspaces.length,
      courses: fallbackWorkspaces.reduce((sum, p) => sum + p.courses.length, 0),
    };
  return {
    accounts: fallbackWorkspaces.length,
    courses: fallbackWorkspaces.reduce((sum, p) => sum + p.courses.length, 0),
  };
}

/** 顶栏与侧栏心跳共用的运行口径，overview 缺席时回退本地任务列表。 */
export function engineTotals(overview: Overview | null, tasks: Task[]) {
  if (overview)
    return {
      running: overview.tasks?.active ?? 0,
      paused: overview.tasks?.paused ?? 0,
      pending: overview.tasks?.pending ?? 0,
    };
  const running = tasks.filter(active).length;
  const paused = tasks.filter((t) => t.status === "paused").length;
  const pending = tasks.filter((t) => t.status === "pending").length;
  return { running, paused, pending };
}
