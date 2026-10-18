export type View =
  "overview" | "accounts" | "tasks" | "bank" | "problems" | "settings";
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
export interface Problem {
  id: number;
  category: string;
  level: string;
  title: string;
  detail: string;
  count: number;
  read_at?: number;
  last_seen: number;
  context: { task_id?: string; account_label?: string; course_name?: string };
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
export type Settings = Record<string, any>;
