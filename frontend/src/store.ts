import { reactive, watch } from "vue";
import { request } from "./api";
import { nextDismissedResumeTasks } from "./mission";
import { router } from "./router";
import type {
  Account,
  Task,
  Settings,
  TaskLive,
  View,
  AccountWorkspace,
  Overview,
} from "./types";
export const state = reactive({
  accounts: [] as Account[],
  tasks: [] as Task[],
  workspaces: [] as AccountWorkspace[],
  // /api/overview 聚合真值（顶栏计数、心跳与总览指标卡同源取数）。
  overview: null as Overview | null,
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
  // 最近收到的 SSE 事件 id（T10）：重连时作 ?last_event_id= 增量续传，
  // 避免每次回到前台都全量重放全部历史事件。
  lastEventId: 0,
  // T16：应用内验证窗捕获到的答题页地址（带 enc=）。NewTask 消费后清空，
  // 避免下一次打开向导误用已过期的地址。
  capturedExamUrl: "",
  // 运行中快照缓存（进度小窗 / 任务列表行摘要共享），键为任务 id。
  liveById: {} as Record<string, TaskLive | null>,
});
// T13：路由为单一事实来源——state.view 由 route 同步驱动，消费方零改动。
watch(
  () => router.currentRoute.value.name,
  (name) => {
    if (typeof name === "string" && name !== "mini")
      state.view = name as View;
  },
  { immediate: true },
);
/** 写入运行中快照，同时同步任务列表中的行摘要。 */
export function setTaskLive(id: string, live?: TaskLive | null) {
  state.liveById[id] = live ?? null;
  const task = state.tasks.find((item) => item.id === id);
  if (task) task.live = live ?? null;
}
/**
 * 运行中快照（当前动作 / 已用时 / ETA）由 /api/tasks?include_live=1 随列表一次带回，
 * 不再对每个运行中任务各打一次 /tasks/{id}。此前 8 个任务是 8 次带逐题明细的详情
 * 请求（每次都要查 4 次事件表 + 一次 500 条 answer_result），每 10 秒一轮。
 * liveById 仍然保留：进度小窗自己轮询详情时会把更细的快照写进来，列表刷新沿用最新值。
 */
function adoptLive(items: Task[]) {
  for (const task of items) {
    const live = task.live ?? state.liveById[task.id] ?? null;
    state.liveById[task.id] = live;
    task.live = live;
  }
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
      // include_live=1：列表自带运行中快照，省掉逐任务的详情轮询（见 adoptLive 注释）
      request<{ items: Task[]; total: number }>("/tasks?limit=100&include_live=1"),
      request<{ items: AccountWorkspace[] }>("/workspace/accounts"),
      request<Overview>("/overview").catch(() => null),
    ]);
    if (current !== generation) return;
    state.accounts = values[0].items;
    state.tasks = values[1].items;
    adoptLive(state.tasks);
    state.workspaces = values[2].items;
    state.overview = values[3];
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
  } catch (error) {
    state.online = false;
    if (!state.accounts.length)
      state.error = error instanceof Error ? error.message : String(error);
  }
}
export function navigate(view: View) {
  void router.push({ name: view });
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
