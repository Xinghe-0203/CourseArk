import { active } from "./format";
import type { AccountWorkspace, Course, Task } from "./types";

/** 课程选择的稳定键：同账号下同名课程靠 class/cpi 区分。 */
export function courseKey(accountId: string, course: Course) {
  return [accountId, course.course_id, course.class_id, course.cpi].join(":");
}

/** 课程对应的本轮任务：优先执行中，其次任意一轮，最后取最近结果。 */
export function taskForCourse(p: AccountWorkspace, c: Course): Task | undefined {
  const same = (t: Task) => t.course_id === c.course_id && t.class_id === c.class_id;
  return (
    p.tasks.find((t) => active(t) && same(t)) ||
    p.tasks.find(same) ||
    p.recent.find(same)
  );
}

export interface CourseRow {
  workspace: AccountWorkspace;
  account: AccountWorkspace["account"];
  course: Course;
  task?: Task;
}

/** 进度页与账号工作台共用同一份「账号 × 课程 × 本轮任务」展平结果。 */
export function courseRows(workspaces: AccountWorkspace[]): CourseRow[] {
  return workspaces.flatMap((p) =>
    p.courses.map((course) => ({
      workspace: p,
      account: p.account,
      course,
      task: taskForCourse(p, course),
    })),
  );
}