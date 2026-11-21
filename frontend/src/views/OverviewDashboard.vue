<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Layers,
  ArrowUpRight,
  Pause,
  Play,
  Square,
  ChevronRight,
  History,
  CheckCircle2,
  TriangleAlert,
} from "lucide-vue-next";
import { state, act, navigate, resumeTask, dismissResumeTask } from "../store";
import { request } from "../api";
import ProgressBar from "../components/ProgressBar.vue";
import { features, statuses, date, terminal } from "../format";
import { executionProfiles, queueReason, summarizeWork } from "../overview";
import {
  visibleLatestUnfinished,
  visibleResumableTasks,
  visibleUnfinishedTotal,
} from "../mission";
import ConfirmDialog from "../components/ConfirmDialog.vue";
import type { Overview, Task } from "../types";
const emit = defineEmits<{ select: [task: Task] }>();
const profiles = computed(() => executionProfiles(state.workspaces));
const tasks = computed(() => profiles.value.flatMap((p) => p.tasks));
/** /api/overview 聚合真值：指标卡与调度队列同源，缺席时回退本地任务口径。 */
const overview = computed(() => state.overview);
/** 调度队列：后端已排好 active+paused+pending 前 60 条。 */
const queue = computed(() => overview.value?.queue ?? []);
const queueTotal = computed(() => {
  const t = overview.value?.tasks;
  return (t?.active ?? 0) + (t?.paused ?? 0) + (t?.pending ?? 0);
});
const ACTIVE_STATUSES = ["running", "starting", "logging_in", "loading_courses", "pausing", "stopping"];
const activeAccounts = computed(() => {
  if (overview.value) {
    const ids = new Set(
      queue.value.filter((q) => ACTIVE_STATUSES.includes(q.status)).map((q) => q.account_id),
    );
    return ids.size;
  }
  return profiles.value.length;
});
const activeCourses = computed(() => {
  if (overview.value) {
    const keys = new Set(
      queue.value
        .filter((q) => ACTIVE_STATUSES.includes(q.status))
        .map((q) => q.account_id + ":" + q.course_name),
    );
    return keys.size;
  }
  return profiles.value.reduce((n, p) => n + p.courses.length, 0);
});
/** 队列行点「详情」：完整任务在本地列表里就开抽屉，否则去任务页。 */
function openQueue(item: Overview["queue"][number]) {
  const task = state.tasks.find((t) => t.id === item.id);
  if (task) emit("select", task);
  else navigate("tasks");
}
/** 空状态里的「去创建任务」直接打开向导弹窗，而不是只跳到学习任务页。 */
function openNewTask() {
  state.newTaskAccount = "";
  state.newTaskFeature = "course_all";
  state.newTask = true;
}
/** 最近结束的任务：与「已完成」页共用同一批数据，这里只做摘要。 */
const recent = computed(() => state.tasks.filter(terminal).slice(0, 6));
const totals = computed(() =>
  tasks.value.reduce(
    (s, t) => ({
      completed: s.completed + t.progress.completed,
      total: s.total + t.progress.total,
      issues: s.issues + t.progress.failed + t.progress.blocked,
    }),
    { completed: 0, total: 0, issues: 0 },
  ),
);
const known = computed(
  () =>
    tasks.value.length > 0 &&
    tasks.value.every((t) => t.progress.sealed && t.progress.total > 0),
);
const progress = computed(() =>
  known.value
    ? Math.min(
        100,
        Math.round((totals.value.completed / totals.value.total) * 100),
      )
    : null,
);
const phase = computed(() => [
  {
    name: "准备与读取",
    count: tasks.value.filter((t) =>
      ["starting", "logging_in", "loading_courses"].includes(t.status),
    ).length,
    color: "amber",
  },
  {
    name: "执行学习",
    count: tasks.value.filter((t) => t.status === "running").length,
    color: "green",
  },
  {
    name: "处理控制指令",
    count: tasks.value.filter((t) => ["pausing", "stopping"].includes(t.status))
      .length,
    color: "blue",
  },
]);
/** 今日统计（/api/overview.today）：任务点、答题、缓存与提交的真实数字。
 *  这些字段后端一直返回，但界面此前一处未用——用户只能去任务详情逐条数。 */
const today = computed(() => overview.value?.today || {});
const todayFacts = computed(() => {
  const t = today.value as Record<string, number>;
  const n = (key: string) => Math.max(0, Number(t[key]) || 0);
  return [
    { key: "success", label: "完成任务点", value: n("success"), tone: "ok" },
    { key: "questions", label: "答题", value: n("questions"), tone: "" },
    { key: "cache", label: "缓存命中", value: n("cache_hits"), tone: "" },
    { key: "llm", label: "AI 调用", value: n("llm_calls"), tone: "" },
    { key: "submit", label: "提交成功", value: n("submit_ok"), tone: "ok" },
    {
      key: "failed",
      label: "待处理",
      value: n("failed") + n("submit_fail"),
      tone: "warn",
    },
  ];
});
/** 今日全为 0 时不占版面，避免新装用户先看到一排零。 */
const todayVisible = computed(() => todayFacts.value.some((item) => item.value > 0));
/** 最近异常：/api/overview.recent_events 里 level 为 warning/error 的事件。
 *  同一句话可能连续出现多次（例如同一账号反复登录失败），按内容归并后
 *  只展示一行 + 次数，否则异常条会被重复文案占满。 */
const problems = computed(() => {
  const rows = (overview.value?.recent_events || []).filter(
    (e) => e.level === "warning" || e.level === "error",
  );
  const merged = new Map<
    string,
    { title: string; count: number; time: string; level: string }
>();
  for (const event of rows) {
    const title = event.narrative?.title || event.message || "任务异常";
    const time = (event.timestamp || "").slice(5, 16);
    const existing = merged.get(title);
    if (existing) {
      existing.count += 1;
      if (time) existing.time = time;
      if (event.level === "error") existing.level = "error";
    } else {
      merged.set(title, { title, count: 1, time, level: event.level });
    }
  }
  return [...merged.values()].slice(0, 4);
});
const problemTotal = computed(() =>
  problems.value.reduce((n, item) => n + item.count, 0),
);
/** 题库命中率：只有真正查询过才有意义，避免「0%」被误读成缓存没用。 */
const bankRate = computed(() => {
  const bank = overview.value?.question_bank;
  if (!bank?.lookups) return null;
  return Math.round((bank.hit_rate || 0) * 100);
});

const unfinished = computed(() => ({
  total: visibleUnfinishedTotal(state.tasks, state.settings),
  items: visibleResumableTasks(state.tasks, state.settings),
  latest: visibleLatestUnfinished(state.tasks, state.settings),
}));
function resumeLatest() {
  const task = unfinished.value.latest;
  if (task) resumeTask(task);
}
/** 「不再提醒」：只对提示条当前指向的这条任务生效，新的中断任务照常提醒。 */
function dismissLatest() {
  const task = unfinished.value.latest;
  if (task) dismissResumeTask(task);
}
/** 停止不可撤销，先确认；暂停可逆，直接执行。 */
const stopping = ref<{ id: string; label: string } | null>(null);
/** 队列行上的单任务停止：与「停止账号」分开，粒度更细。 */
const stoppingTask = ref<{ id: string; name: string } | null>(null);
function askStop(p: { account: { id: string; label?: string; username: string } }) {
  stopping.value = {
    id: p.account.id,
    label: p.account.label || p.account.username,
  };
}
function confirmStop() {
  const target = stopping.value;
  stopping.value = null;
  if (target) void control(target.id, "stop");
}
/** 队列行的单任务指令：走 /tasks/{id}/{op}，与学习任务页同一套接口。 */
function taskCommand(id: string, op: "pause" | "resume" | "stop") {
  if (op === "stop") {
    const item = queue.value.find((row) => row.id === id);
    stoppingTask.value = { id, name: item?.course_name || "该任务" };
    return;
  }
  act(
    "queue-" + id + op,
    () => request(`/tasks/${id}/${op}`, "POST"),
    op === "pause" ? "已发送暂停指令" : "已发送继续指令",
  );
}
function confirmTaskStop() {
  const target = stoppingTask.value;
  stoppingTask.value = null;
  if (target)
    act(
      "queue-" + target.id + "stop",
      () => request(`/tasks/${target.id}/stop`, "POST"),
      "已发送停止指令",
    );
}
/** 队列行可执行的操作：与 app/task_model.py 的状态迁移表对齐。 */
function queueOps(status: string) {
  const pauseable = ["starting", "logging_in", "loading_courses", "running"];
  return {
    pause: pauseable.includes(status),
    resume: status === "paused",
    stop: !["succeeded", "failed", "stopped", "interrupted"].includes(status),
  };
}
async function control(id: string, op: string) {
  await act(
    "overview-" + id + op,
    async () => {
      const result = await request<{ accepted: number }>(
        `/accounts/${id}/tasks/${op}`,
        "POST",
      );
      return result.accepted;
    },
    (n) => `已接受 ${n} 项${op === "pause" ? "暂停" : "停止"}操作`,
  );
}
</script>
<template>
  <div class="overview">
    <div v-if="unfinished.total" class="resume-banner" role="status">
      <span class="resume-icon"><History :size="18" /></span>
      <div class="resume-copy">
        <b>上次任务未完成，共 {{ unfinished.total }} 项</b>
        <p v-if="unfinished.latest">
          {{ unfinished.latest.course_name }} ·
          {{ date(unfinished.latest.created_at) }} 中断，可从中断处继续，无需重新开始。
        </p>
        <p v-else>可以从中断处继续，无需重新开始。</p>
      </div>
      <div class="resume-actions">
        <button
          class="primary resume-action"
          :disabled="state.busy.has('resume-' + unfinished.latest?.id)"
          @click="resumeLatest"
        >
          继续执行
        </button>
        <button
          class="text-link resume-dismiss"
          :disabled="state.busy.has('dismiss-resume-' + unfinished.latest?.id)"
          @click="dismissLatest"
        >
          不再提醒
        </button>
        <button class="text-link" @click="navigate('tasks')">查看任务</button>
      </div>
    </div>

    <section class="execution-dashboard">
      <div class="dash-lead">
        <span class="eyebrow">本轮执行</span>
        <strong class="num"
          >{{ totals.completed }}<small>/{{ totals.total || "—" }}</small></strong
        >
        <p>
          {{
            tasks.length
              ? `项已确认 · ${tasks.length} 项任务在 ${activeAccounts} 个账号、${activeCourses} 门课程中执行`
              : "当前没有执行中的任务"
          }}
        </p>
      </div>
      <div class="dash-progress">
        <ProgressBar :value="progress ?? undefined" label="本轮执行总体进度" />
        <div class="progress-pair">
          <span>{{ known ? "平台确认的实际完成量" : tasks.length ? "正在读取完整任务范围" : "空闲" }}</span>
          <b>{{ progress === null ? "读取中" : progress + "%" }}</b>
        </div>
      </div>
      <div class="dash-phases">
        <span v-for="item in phase" :key="item.name" class="phase-chip">
          <span :class="['dot', item.color]" />{{ item.name }}
          <b class="num">{{ item.count }}</b>
        </span>
        <span v-if="totals.issues" class="phase-chip issue">
          <span class="dot red" />待处理 <b class="num">{{ totals.issues }}</b>
        </span>
      </div>
    </section>

    <section v-if="todayVisible" class="today-strip" aria-label="今日统计">
      <span class="eyebrow">今日</span>
      <div
        v-for="item in todayFacts"
        :key="item.key"
        :class="['today-fact', item.tone]"
      >
        <strong class="num">{{ item.value }}</strong>
        <span>{{ item.label }}</span>
      </div>
      <div class="today-fact extra">
        <strong class="num">{{ overview?.workers?.limit ?? "—" }}</strong>
        <span>并发上限</span>
      </div>
      <div v-if="bankRate !== null" class="today-fact extra">
        <strong class="num">{{ bankRate }}%</strong>
        <span>缓存命中率</span>
      </div>
    </section>

    <section v-if="problems.length" class="problem-strip" aria-label="最近异常">
      <span class="problem-icon"><TriangleAlert :size="15" /></span>
      <div class="problem-copy">
        <b>最近有 {{ problemTotal }} 条异常</b>
        <ul>
          <li
            v-for="item in problems"
            :key="item.title"
            :class="['problem-row', item.level]"
          >
            <span class="num">{{ item.time }}</span>
            <span v-if="item.count > 1" class="problem-count num"
              >×{{ item.count }}</span
            >
            <span class="problem-text">{{ item.title }}</span>
          </li>
        </ul>
      </div>
      <button
        class="text-link"
        aria-label="查看任务记录并处理异常"
        @click="navigate('tasks')"
      >
        处理异常 <ArrowUpRight :size="13" />
      </button>
    </section>

    <div class="section-heading queue-heading">
      <div>
        <h2>调度队列</h2>
        <p>正在执行、已暂停与排队等待的任务，共 {{ queueTotal }} 项</p>
      </div>
      <button class="text-link" @click="navigate('tasks')">
        全部任务 <ArrowUpRight :size="14" />
      </button>
    </div>
    <div v-if="queue.length" class="overview-queue">
      <div class="queue-head" aria-hidden="true">
        <span>课程与任务</span><span>状态</span><span>说明</span><span>进度</span
        ><span>创建</span>
      </div>
      <div v-for="item in queue" :key="item.id" class="queue-row">
        <button class="queue-main" @click="openQueue(item)">
          <b>{{ item.course_name }}</b>
          <small>{{ item.account_label }} · {{ item.feature_label }}</small>
        </button>
        <span :class="['status', item.status]"
          ><i />{{ statuses[item.status] }}</span
        >
        <span class="queue-reason">{{ queueReason(item) }}</span>
        <span class="queue-meta">
          <b class="num"
            >{{ summarizeWork(item).completed }}/{{
              summarizeWork(item).total || "—"
            }}</b
          >
          <small class="num">{{ date(item.created_at) }}</small>
        </span>
        <span class="queue-actions">
          <button
            v-if="queueOps(item.status).pause"
            class="icon-button"
            aria-label="暂停这项任务"
            title="暂停这项任务"
            :disabled="state.busy.has('queue-' + item.id + 'pause')"
            @click="taskCommand(item.id, 'pause')"
          >
            <Pause :size="13" />
          </button>
          <button
            v-if="queueOps(item.status).resume"
            class="icon-button"
            aria-label="继续这项任务"
            title="继续这项任务"
            :disabled="state.busy.has('queue-' + item.id + 'resume')"
            @click="taskCommand(item.id, 'resume')"
          >
            <Play :size="13" />
          </button>
          <button
            v-if="queueOps(item.status).stop"
            class="icon-button stop-ink"
            aria-label="停止这项任务"
            title="停止这项任务"
            :disabled="state.busy.has('queue-' + item.id + 'stop')"
            @click="taskCommand(item.id, 'stop')"
          >
            <Square :size="12" />
          </button>
          <button
            class="icon-button"
            aria-label="查看任务详情"
            title="查看任务详情"
            @click="openQueue(item)"
          >
            <ChevronRight :size="14" />
          </button>
        </span>
      </div>
    </div>
    <div v-else-if="!queueTotal" class="empty">
      <Layers :size="26" />
      <h3>队列是空的</h3>
      <p>还没有排队或正在执行的任务。新建学习任务后，这里按调度顺序列出每一项。</p>
      <button class="primary" @click="navigate('tasks')">查看学习任务</button>
    </div>

    <div class="section-heading">
      <div>
        <h2>正在执行的账号</h2>
        <p>只列执行中的课程 · 点「详情」查看逐题与日志</p>
      </div>
      <button class="text-link" @click="navigate('tasks')">
        学习任务 <ArrowUpRight :size="14" />
      </button>
    </div>
    <div v-if="profiles.length" class="execution-grid">
      <section
        v-for="p in profiles"
        :key="p.account.id"
        class="execution-account"
      >
        <header class="execution-account-head">
          <span class="avatar">{{
            (p.account.label || p.account.username).slice(0, 1)
          }}</span>
          <div>
            <h2>{{ p.account.label || p.account.username }}</h2>
            <small
              >{{ p.account.username }} · {{ p.courses.length }} 门课程 /
              {{ p.tasks.length }} 项任务</small
            >
          </div>
          <span class="status running"><i />执行中</span>
        </header>
        <div
          class="execution-scroll"
          tabindex="0"
          :aria-label="(p.account.label || p.account.username) + ' 的任务数据'"
        >
          <article v-for="(c, i) in p.courses" :key="i" class="execution-course">
            <h3>{{ c.name }}</h3>
            <small v-if="c.cached" class="muted"
              >平台任务点缓存 {{ c.cached.mission_fn }} /
              {{ c.cached.mission_all }}</small
            >
            <div v-for="t in c.tasks" :key="t.id" class="execution-task">
              <div class="execution-task-heading">
                <span class="module-tag">{{
                  features[t.feature] || t.feature_label
                }}</span>
                <span :class="['status', t.status]"
                  ><i />{{ statuses[t.status] }}</span
                >
                <button class="text-link" @click="emit('select', t)">
                  详情 <ChevronRight :size="13" />
                </button>
              </div>
              <div class="live-progress">
                <ProgressBar
                  :value="t.progress.percent ?? undefined"
                  :label="(t.course_name || '任务') + '进度'"
                />
                <div class="progress-pair">
                  <span
                    >{{ t.progress.completed }}/{{ t.progress.total || "—" }}
                    项已确认</span
                  >
                  <b v-if="t.progress.percent !== null"
                    >{{ t.progress.percent }}%</b
                  >
                </div>
              </div>
              <ul v-if="t.progress.active.length" class="media-live">
                <li v-for="m in t.progress.active" :key="m.id">
                  <span class="media-kind">{{
                    m.kind === "video"
                      ? "视频"
                      : m.kind === "audio"
                        ? "音频"
                        : m.kind === "work"
                          ? "测验"
                          : "任务点"
                  }}</span>
                  <b :title="m.name">{{ m.name }}</b>
                  <small class="num">{{
                    m.total
                      ? `${m.current || 0} / ${m.total}${["video", "audio"].includes(m.kind) ? " 秒" : ""}`
                      : "处理中"
                  }}</small>
                </li>
              </ul>
              <p v-else class="muted execution-stage">
                {{
                  t.stage === "login"
                    ? "正在验证账号登录"
                    : t.stage === "course"
                      ? "正在读取课程任务"
                      : "正在处理课程内容"
                }}
              </p>
              <p v-if="t.progress.failed + t.progress.blocked" class="issue-text">
                {{ t.progress.failed + t.progress.blocked }}
                项内容待处理，打开详情查看原因。
              </p>
            </div>
          </article>
        </div>
        <footer class="account-controls">
          <button
            :disabled="state.busy.has('overview-' + p.account.id + 'pause')"
            @click="control(p.account.id, 'pause')"
          >
            <Pause :size="13" />暂停账号</button
          ><button
            :disabled="state.busy.has('overview-' + p.account.id + 'stop')"
            @click="askStop(p)"
          >
            <Square :size="13" />停止账号</button
          ><small class="faint">实时任务数据</small>
        </footer>
      </section>
    </div>
    <div v-else class="empty">
      <Layers :size="26" />
      <h3>当前没有正在执行的任务</h3>
      <p>创建学习任务后，执行中的账号与课程会显示在这里。</p>
      <button @click="navigate('tasks')">查看学习任务</button>
    </div>

    <div class="section-heading recent-heading">
      <div>
        <h2>最近完成</h2>
        <p>最近结束的任务摘要 · 逐题明细与结果说明在「已完成」页</p>
      </div>
      <button class="text-link" @click="navigate('completed')">
        全部已完成 <ArrowUpRight :size="14" />
      </button>
    </div>
    <div v-if="recent.length" class="overview-recent">
      <button
        v-for="t in recent"
        :key="t.id"
        class="recent-row"
        @click="emit('select', t)"
      >
        <span class="recent-main">
          <b>{{ t.course_name }}</b>
          <small
            >{{ t.account_label }} ·
            {{ features[t.feature] || t.feature_label }}</small
          >
        </span>
        <span :class="['status', t.status]"
          ><i />{{ statuses[t.status] }}</span
        >
        <span class="recent-meta num"
          >{{ t.progress.completed }}/{{ t.progress.total || "—" }}</span
        >
        <span class="recent-when num">{{
          date(t.finished_at || t.created_at)
        }}</span>
      </button>
    </div>
    <div v-else class="empty overview-recent-empty">
      <CheckCircle2 :size="24" />
      <h3>还没有完成的任务</h3>
      <p>任务跑完后会在这里显示课程、进度与结束时间，完整明细在「已完成」页。</p>
      <button class="primary" @click="openNewTask">去创建任务</button>
    </div>

    <ConfirmDialog
      v-if="stoppingTask"
      title="停止这项任务"
      :message="'将停止「' + stoppingTask.name + '」正在执行的任务。'"
      hint="已完成的进度会保留，之后可以在任务记录里继续执行。"
      confirm-text="停止任务"
      :busy="state.busy.has('queue-' + stoppingTask.id + 'stop')"
      @confirm="confirmTaskStop"
      @cancel="stoppingTask = null"
    />
    <ConfirmDialog
      v-if="stopping"
      title="停止账号"
      :message="`将停止「${stopping.label}」下正在执行与排队的任务。`"
      hint="已完成的进度会保留，之后可以在任务记录里继续执行。"
      confirm-text="停止账号"
      :busy="state.busy.has('overview-' + stopping.id + 'stop')"
      @confirm="confirmStop"
      @cancel="stopping = null"
    />
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ---------- 续跑提示 ---------- */
.resume-banner {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
  border: 1px solid var(--warn-line);
  border-left: 3px solid var(--warn);
  border-radius: var(--r3);
  background: var(--warn-soft);
}

.resume-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r2);
  background: var(--surface);
  color: var(--warn);
}

.resume-copy {
  min-width: 0;
}

.resume-copy b {
  font-size: 12.5px;
  color: var(--warn-ink);
}

.resume-copy p {
  font-size: 11.5px;
  color: var(--warn-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ---------- 今日统计 ---------- */
.today-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 0;
  padding: 0 4px;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.today-strip > .eyebrow {
  padding: 0 12px 0 10px;
  font-size: 10px;
  line-height: 46px;
  color: var(--faint);
}

.today-fact {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 9px 14px;
  border-left: 1px solid var(--line);
}

.today-fact strong {
  font-size: 15px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--ink);
}

.today-fact span {
  font-size: 11px;
  color: var(--mute);
  white-space: nowrap;
}

.today-fact.ok strong {
  color: var(--ok);
}

.today-fact.warn strong {
  color: var(--warn);
}

.today-fact.extra strong {
  color: var(--ink2);
}

/* ---------- 最近异常 ---------- */
.problem-strip {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--danger-line);
  border-left: 3px solid var(--danger);
  border-radius: var(--r3);
  background: var(--danger-soft);
}

.problem-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  border-radius: var(--r2);
  background: var(--surface);
  color: var(--danger);
}

.problem-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.problem-copy b {
  font-size: 12.5px;
  color: var(--danger-ink);
}

.problem-copy ul {
  display: grid;
  gap: 2px;
  color: var(--danger-ink);
}

.problem-copy li {
  font-size: 11.5px;
  line-height: 1.5;
}

.problem-copy li .num {
  flex: 0 0 auto;
  font-size: 10.5px;
  opacity: 0.75;
}

.problem-row {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  align-items: baseline;
  justify-content: start;
  gap: 8px;
}

.problem-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.problem-count {
  padding: 0 5px;
  border-radius: var(--r1);
  background: rgba(255, 255, 255, 0.6);
  font-size: 10.5px;
}

.problem-row.error .problem-text {
  font-weight: 600;
}

.problem-strip > .text-link {
  flex: 0 0 auto;
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11.5px;
}

/* ---------- 执行摘要 ---------- */
.execution-dashboard {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.5fr);
  gap: 4px 22px;
  align-items: end;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
}

.dash-lead {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.dash-lead .eyebrow {
  letter-spacing: 0.1em;
}

.dash-lead strong {
  font-family: var(--font-num);
  font-size: var(--fs-display);
  font-weight: 500;
  line-height: 1.15;
  color: var(--ink);
}

.dash-lead strong small {
  font-size: 13px;
  color: var(--faint);
}

.dash-lead p {
  font-size: 11.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dash-progress {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding-bottom: 2px;
}

.dash-phases {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.phase-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r1);
  background: var(--surface2);
  font-size: 11.5px;
  color: var(--ink2);
}

.phase-chip b {
  font-family: var(--font-num);
  font-weight: 500;
  color: var(--ink);
}

.phase-chip.issue {
  border-color: var(--danger-line);
  background: var(--danger-soft);
  color: var(--danger-ink);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--faint);
}

.dot.amber {
  background: var(--warn);
}

.dot.green {
  background: var(--ok);
}

.dot.blue {
  background: var(--info);
}

.dot.red {
  background: var(--danger);
}

/* ---------- 队列 ---------- */
.overview-queue {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.queue-head,
.queue-row {
  display: grid;
  grid-template-columns:
    minmax(0, 1.5fr) 78px minmax(0, 1.4fr) 92px 106px;
  gap: 14px;
  align-items: center;
  padding: 0 14px;
}

.queue-head {
  height: 34px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.queue-head > span:last-child {
  text-align: right;
}

.queue-row {
  min-height: 48px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.queue-row:last-child {
  border-bottom: 0;
}

.queue-row:hover {
  background: var(--surface2);
}

/* 整行可点：把课程名做成一枚无边框按钮，其余列不响应点击，
   避免「点进度条也跳详情」和行内操作按钮互相抢事件。 */
.queue-main {
  display: grid;
  gap: 2px;
  min-width: 0;
  height: auto;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
  justify-content: start;
  justify-items: stretch;
}

.queue-main:hover:not(:disabled) {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}

.queue-main > b,
.queue-main > small {
  max-width: 100%;
  text-align: left;
}

.queue-main:hover b {
  color: var(--navy2);
}

.queue-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
}

.queue-actions .icon-button {
  width: 24px;
  height: 24px;
}

.queue-actions .stop-ink:hover:not(:disabled) {
  background: var(--danger-soft);
  border-color: var(--danger-line);
  color: var(--danger-ink);
}

.queue-meta {
  display: grid;
  gap: 1px;
  justify-items: end;
}

.queue-meta small {
  font-family: var(--font-num);
  font-size: 10.5px;
  color: var(--faint);
}

.queue-main b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-main small {
  font-size: 11px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-row > .status {
  justify-self: start;
}

.queue-reason {
  min-width: 0;
  font-size: 11.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-meta b {
  font-family: var(--font-num);
  font-size: 12px;
  font-weight: 500;
  color: var(--ink2);
}

.queue-when,
.recent-when {
  font-family: var(--font-num);
  font-size: 11px;
  color: var(--faint);
  text-align: right;
}

/* ---------- 执行中的账号 ---------- */
.execution-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 16px;
  align-items: start;
}

.execution-account {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.execution-account-head {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.execution-account-head > div {
  display: grid;
  gap: 0;
  min-width: 0;
  flex: 1;
}

.execution-account-head h2 {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-account-head small {
  font-size: 11px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-scroll {
  display: grid;
  gap: 14px;
  max-height: 320px;
  padding: 14px 14px;
  overflow-y: auto;
}

.execution-course {
  display: grid;
  gap: 5px;
}

.execution-course h3 {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-task {
  display: grid;
  gap: 9px;
  padding: 12px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface2);
}

.execution-task-heading {
  display: flex;
  align-items: center;
  gap: 6px;
}

.module-tag {
  padding: 2px 6px;
  border-radius: var(--r1);
  background: var(--navy-soft);
  color: var(--navy);
  font-size: 10.5px;
}

.execution-task-heading .text-link {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.live-progress {
  display: grid;
  gap: 4px;
}

.media-live {
  display: grid;
  gap: 5px;
}

.media-live li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  font-size: 11.5px;
  line-height: 1.45;
}

.media-kind {
  color: var(--faint);
}

.media-live li b {
  font-weight: 400;
  color: var(--ink2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.media-live li small {
  font-family: var(--font-num);
  color: var(--mute);
}

.execution-stage,
.issue-text {
  font-size: 11px;
}

.issue-text {
  color: var(--danger-ink);
}

.account-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border-top: 1px solid var(--line);
}

.account-controls button {
  height: 24px;
  padding: 0 8px;
  font-size: 11.5px;
}

.account-controls small {
  margin-left: auto;
  font-size: 10.5px;
}

/* ---------- 最近完成 ---------- */
.overview-recent {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.recent-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 78px 62px 78px;
  gap: 12px;
  align-items: center;
  width: 100%;
  height: auto;
  min-height: 42px;
  padding: 10px 14px;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: var(--surface);
  text-align: left;
}

.recent-row:last-child {
  border-bottom: 0;
}

.recent-row:hover:not(:disabled) {
  background: var(--surface2);
  border-color: var(--line);
}

.recent-main {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.recent-main b {
  font-size: 12.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-main small {
  font-size: 11px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-row > .status {
  justify-self: start;
}

.recent-meta {
  font-family: var(--font-num);
  font-size: 12px;
  color: var(--ink2);
  text-align: right;
}

/* ---------- 响应式 ---------- */
@media (max-width: 1080px) {
  .queue-head,
  .queue-row {
    grid-template-columns: minmax(0, 1.4fr) 74px minmax(0, 1fr) 96px;
  }

  .queue-head > span:nth-child(4),
  .queue-row > .queue-meta {
    display: none;
  }
}

@media (max-width: 980px) {
  .execution-dashboard {
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
  }

  .queue-head,
  .queue-row {
    grid-template-columns: minmax(0, 1fr) 78px 62px;
  }

  .queue-head > span:nth-child(3),
  .queue-row > .queue-reason,
  .queue-head > span:nth-child(5),
  .queue-row > .queue-when {
    display: none;
  }
}

@media (max-width: 720px) {
  /* 今日统计在手机上排成两列，不再出现「单独一格挂在第二行」的碎行。 */
  .today-strip {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1px;
    background: var(--line);
  }

  .today-strip > .eyebrow {
    display: none;
  }

  .today-fact {
    display: grid;
    gap: 1px;
    padding: 9px 12px;
    border-left: 0;
    background: var(--surface);
  }

  .today-fact strong {
    font-size: 17px;
  }

  .problem-strip {
    flex-wrap: wrap;
  }

  .problem-strip > .text-link {
    width: 100%;
    justify-content: flex-end;
  }

  .resume-banner {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .resume-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }

  /* 队列行在手机上重排成「主信息 + 状态 | 操作」三格两块，
     而不是让状态和操作各自掉到下一行。 */
  .queue-head {
    display: none;
  }

  .queue-row {
    grid-template-areas:
      "main status"
      "main actions";
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: start;
    gap: 6px 10px;
    padding: 12px 14px;
  }

  .queue-row > .queue-main {
    grid-area: main;
  }

  .queue-row > .status {
    grid-area: status;
    justify-self: end;
  }

  .queue-row > .queue-actions {
    grid-area: actions;
    align-self: end;
  }

  .queue-row > .queue-reason {
    grid-area: main;
    align-self: end;
    display: block;
    white-space: normal;
  }

  .recent-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
  }

  .queue-head > span:nth-child(3),
  .queue-head > span:nth-child(4),
  .queue-row > .queue-reason,
  .queue-row > .queue-meta,
  .recent-row > .recent-meta {
    display: none;
  }

  .execution-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>