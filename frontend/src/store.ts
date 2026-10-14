import { reactive } from "vue";
import { request } from "./api";
import type {
  Account,
  Task,
  Problem,
  Settings,
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
});
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
let generation = 0;
export async function refresh() {
  const current = ++generation;
  try {
    const values = await Promise.all([
      request<{ items: Account[] }>("/accounts"),
      request<{ items: Task[]; total: number }>(
        "/tasks?limit=100&feature=course_all,independent_homework",
      ),
      request<{ items: Problem[]; unread: number }>(
        "/notifications?include_read=false",
      ),
      request<{ items: AccountWorkspace[] }>("/workspace/accounts"),
    ]);
    if (current !== generation) return;
    state.accounts = values[0].items;
    state.tasks = values[1].items;
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
