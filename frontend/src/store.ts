import { reactive } from "vue";
import { request } from "./api";
import { active } from "./format";
import { nextDismissedResumeTasks } from "./mission";
import type {
  Account,
  Task,
  Problem,
  Settings,
  TaskLive,
  View,
  AccountWorkspace,
} from "./types";
export const state = reactive({
  accounts: [] as Account[],
  tasks: [] as Task[],
  totalTasks: 0,
  problems: [] as Problem[],
  unreadProblems: 0,
  workspaces: [] as AccountWorkspace[],
  selectedCourses: [] as string[],
  selectedAccounts: [] as string[],
  settings: {} as Settings,
  view: (location.hash.slice(1) || "overview") as View,
  online: false,
  loading: false,
  error: "",
  toast: "",
  busy: new Set<string>(),
  newTask: false,
  newTaskFeature: "course_all",
  newTaskAccount: "",
  // SSE 事件计数：任务详情等局部视图据此按需刷新。
  eventRevision: 0,
  // 运行中快照缓存（进度小窗 / 任务列表行摘要共享），键为任务 id。
  liveById: {} as Record<string, TaskLive | null>,
});
/** 写入运行中快照，同时同步任务列表中的行摘要。 */
export function setTaskLive(id: string, live?: TaskLive | null) {
  state.liveById[id] = live ?? null;
  const task = state.tasks.find((item) => item.id === id);
  if (task) task.live = live ?? null;
}
// 列表接口不含 live：按任务节流补齐运行中快照（小窗与任务行摘要共用）。
const liveFetchedAt: Record<string, number> = {};
async function refreshLives() {
  const now = Date.now();
  const running = state.tasks.filter(
    (task) => active(task) || task.status === "paused",
  );
  await Promise.all(
    running.map(async (task) => {
      if (now - (liveFetchedAt[task.id] || 0) < 2500) return;
      liveFetchedAt[task.id] = now;
      try {
        const detail = await request<Task>(`/tasks/${task.id}`);
        setTaskLive(task.id, detail.live);
      } catch {
        liveFetchedAt[task.id] = 0;
      }
    }),
  );
}
export async function act(
  key: string,
  action: () => Promise<unknown>,
  success: string | ((result: unknown) => string) = "操作已完成",
) {
  if (state.busy.has(key)) return;
  state.error = "";
  state.busy.add(key);
  try {
    const result = await action();
    state.toast = typeof success === "function" ? success(result) : success;
    await refresh();
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error);
    await refresh();
  } finally {
    state.busy.delete(key);
  }
}
/** 续跑中断/停止/失败的任务：后端复用原参数快照新建 pending 任务。 */
export async function resumeTask(task: Task) {
  await act(
    "resume-" + task.id,
    () => request(`/tasks/${task.id}/resume`, "POST"),
    "已创建续跑任务",
  );
}
/**
 * 对单条续跑提示点「不再提醒」：把任务 id 追加进 settings.ui.dismissed_resume_tasks
 * （去重、上限 100）并 PATCH 持久化；只隐藏该 id，新的中断任务照常提醒。
 */
export async function dismissResumeTask(task: Task) {
  const next = nextDismissedResumeTasks(state.settings, task.id);
  await act(
    "dismiss-resume-" + task.id,
    async () => {
      await request("/settings", "PATCH", {
        ui: { dismissed_resume_tasks: next },
      });
      state.settings.ui = {
        ...(state.settings.ui || {}),
        dismissed_resume_tasks: next,
      };
    },
    "已不再提醒这条未完成任务",
  );
}
let generation = 0;
export async function refresh() {
  const current = ++generation;
  try {
    const values = await Promise.all([
      request<{ items: Account[] }>("/accounts"),
      request<{ items: Task[]; total: number }>("/tasks?limit=100"),
      request<{ items: Problem[]; unread: number }>(
        "/notifications?include_read=false",
      ),
      request<{ items: AccountWorkspace[] }>("/workspace/accounts"),
    ]);
    if (current !== generation) return;
    state.accounts = values[0].items;
    // 列表接口不带 live，用最近一次小窗轮询的快照补齐，避免行摘要闪回。
    state.tasks = values[1].items.map((task) =>
      state.liveById[task.id] ? { ...task, live: state.liveById[task.id] } : task,
    );
    state.totalTasks = values[1].total;
    state.problems = values[2].items;
    state.unreadProblems = values[2].unread;
    state.workspaces = values[3].items;
    const validAccounts = new Set(state.workspaces.map((p) => p.account.id));
    const validCourses = new Set(
      state.workspaces
        .filter((p) => p.account.enabled)
        .flatMap((p) =>
          p.courses
            .filter((c) => c.if_open)
            .map((c) =>
              [p.account.id, c.course_id, c.class_id, c.cpi].join(":"),
            ),
        ),
    );
    state.selectedAccounts = state.selectedAccounts.filter((id) =>
      validAccounts.has(id),
    );
    state.selectedCourses = state.selectedCourses.filter((key) =>
      validCourses.has(key),
    );
    state.online = true;
    void refreshLives();
  } catch (error) {
    state.online = false;
    if (!state.accounts.length)
      state.error = error instanceof Error ? error.message : String(error);
  }
}
export function navigate(view: View) {
  state.view = view;
  location.hash = view;
}
export async function initialize() {
  state.loading = true;
  await Promise.all([
    refresh(),
    request<Settings>("/settings")
      .then((data) => (state.settings = data))
      .catch((error) => (state.error = error.message)),
  ]);
  state.loading = false;
}
