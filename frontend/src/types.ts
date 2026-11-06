export type View =
  | "overview"
  | "progress"
  | "accounts"
  | "tasks"
  | "completed"
  | "bank"
  | "settings";
export interface Account {
  id: string;
  label: string;
  username: string;
  enabled: boolean;
  course_count: number;
  syncing: boolean;
  last_sync_status?: string;
  last_sync_at?: number;
  session?: {
    has_session?: boolean;
    fresh?: boolean;
    fetching?: boolean;
    last_result?: { ok?: boolean; message?: string };
  };
}
export interface Course {
  synced_at?: number;
  course_id: string;
  class_id: string;
  cpi: string;
  name: string;
  author: string;
  if_open: boolean;
  mission_fn: number;
  mission_all: number;
}
export interface Progress {
  percent: number | null;
  completed: number;
  total: number;
  failed: number;
  blocked: number;
  sealed: boolean;
  active: {
    id: string;
    name: string;
    kind: string;
    current?: number;
    total?: number;
  }[];
}
export interface AccountWorkspace {
  account: Account;
  courses: Course[];
  tasks: Task[];
  recent: Task[];
  counts: {
    active: number;
    pending: number;
    paused: number;
    succeeded: number;
    failed: number;
  };
}
export type AnswerSource = "ai" | "cache" | "random" | "failed";
export type AnswerStatus = "answered" | "skipped" | "unreadable";
export interface AnswerItem {
  key: string;
  index: number;
  total: number;
  media: string;
  question_type: string;
  question: string;
  options?: string[];
  answer: string;
  source: AnswerSource | string;
  status: AnswerStatus | string;
  note?: string;
  ts: number;
  time?: string;
}
export interface AnswersSummary {
  answered: number;
  skipped: number;
  total: number;
  ai: number;
  cache: number;
  random: number;
  failed: number;
  submit_ok: number;
  submit_fail: number;
}
export interface CatalogItem {
  id: string;
  title: string;
  status?: string;
  valid?: boolean;
  time_left?: string;
  start_time?: string;
  end_time?: string;
  limit_time?: number | string;
  url?: string;
  relation_id?: string;
  paper_id?: string;
}
export interface CatalogResponse {
  account_id: string;
  course_id: string;
  kind: string;
  items: CatalogItem[];
  fetched_at?: number;
  from_cache?: boolean;
  error?: string;
}
export interface SelectionParams {
  mode: "all" | "selected";
  ids: string[];
}
export interface LiveUnit {
  label: string;
  current: number;
  total: number;
}
export interface TaskLive {
  activity?: string;
  activity_at?: number;
  elapsed_seconds?: number | null;
  unit?: LiveUnit | null;
  eta_seconds?: number | null;
  eta_source?: string | null;
}
export interface Task {
  cpi?: string;
  course_id: string;
  class_id: string;
  id: string;
  /** 所属运行批次（/api/runs 的 id）；重建后端时一并补齐。 */
  run_id?: string;
  account_id: string;
  account_label: string;
  course_name: string;
  feature: string;
  feature_label: string;
  status: string;
  stage: string;
  error: string;
  created_at: number;
  started_at: number;
  finished_at: number;
  stats: Record<string, unknown>;
  params: Record<string, unknown>;
  progress: Progress;
  events?: TaskEvent[];
  activity_events?: TaskEvent[];
  answers?: AnswerItem[];
  answers_summary?: Partial<AnswersSummary>;
  live?: TaskLive | null;
  /** 中断/停止/失败任务仍有待处理的单元数，由后端按 stats.work.units 统计。 */
  unfinished_units?: number;
  /** 逐题明细为空时的可读解释（有明细时为 ""）。仅 /tasks/{id} 详情返回。 */
  answers_note?: string;
  /** 续跑链（T8.6）：本任务由哪个旧任务继续而来（resume 端点回传）。 */
  resumed_from?: string;
  /** 续跑链（T8.6）：resume 新建的任务 id（resume 端点回传）。 */
  new_task_id?: string;
}
/** 已完成任务的结果说明：status 与后端给出的可读原因（保证非空）。 */
export interface CompletedOutcome {
  status: string;
  reason: string;
}
/** 独立考试任务在「已完成」页展示的考试信息。 */
export interface CompletedExam {
  title: string;
  exam_id: string;
  url: string;
  already_done?: boolean;
  detail?: string;
}
/** 「已完成」专页列表项：任务视图 + 逐题汇总 + 耗时 + 结果说明 + 考试信息。 */
export interface CompletedTask extends Task {
  answers_summary?: Partial<AnswersSummary>;
  answers_count?: number;
  duration_seconds?: number | null;
  outcome?: CompletedOutcome;
  exam?: CompletedExam | null;
}
export interface CompletedResponse {
  total: number;
  items: CompletedTask[];
}
/** T14/T15：Electron preload 桥（仅桌面端存在，浏览器端 undefined）。 */
export interface DesktopWindowPreset {
  title?: string;
  width?: number;
  height?: number;
  minWidth?: number;
  minHeight?: number;
  frame?: boolean;
  alwaysOnTop?: boolean;
  skipTaskbar?: boolean;
}
export interface CoursearkDesktop {
  openMini: () => Promise<boolean>;
  closeMini: () => Promise<boolean>;
  openWindow: (route: string, preset?: DesktopWindowPreset) => Promise<boolean>;
  closeWindow: (route: string) => Promise<boolean>;
}
declare global {
  interface Window {
    coursearkDesktop?: CoursearkDesktop;
  }
}
export interface TaskEvent {
  id: number;
  event: string;
  message: string;
  level: string;
  stage: string;
  ts: number;
  payload: Record<string, unknown>;
  presentation?: {
    category: string;
    title: string;
    detail: string;
    action: string;
    visible: boolean;
  };
  narrative: { title: string; detail: string; kind: string };
}
export interface BankItem {
  hash: string;
  question_hash?: string;
  question_text: string;
  question_type: string;
  answer: string;
  options?: string[];
  course_id?: string;
}
/** /api/overview 的调度队列行（active+paused+pending 前 60）。 */
export interface QueueItem {
  id: string;
  account_id: string;
  account_label: string;
  course_name: string;
  feature: string;
  feature_label: string;
  status: string;
  stage: string;
  stats: Record<string, unknown>;
  created_at: number;
}
/** /api/overview 聚合视图（main.py /api/overview 的四节数据）。 */
export interface Overview {
  accounts: {
    total: number;
    enabled: number;
    online: number;
    login_failed: number;
  };
  tasks: { active: number; paused: number; pending: number; today_total: number };
  today: Record<string, number>;
  workers: { running: number; limit: number; busy: number; workers: number };
  question_bank: { total: number; hits: number; hit_rate: number; lookups: number };
  queue: QueueItem[];
  recent_events: TaskEvent[];
}
/** /api/question-bank/stats 响应（题库统计卡）。 */
export interface BankStats {
  total: number;
  hits: number;
  lookups: number;
  hit_rate: number;
  by_type: Record<string, number>;
  by_course: Record<string, number>;
  recent_days: { day: string; hits: number; lookups: number }[];
  recent_count: number;
  latest: BankItem[];
}
export type Settings = Record<string, any>;
