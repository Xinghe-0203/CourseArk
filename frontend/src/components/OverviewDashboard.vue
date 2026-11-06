<script setup lang="ts">
import { computed } from "vue";
import {
  Layers,
  ArrowUpRight,
  Pause,
  Square,
  ChevronRight,
  History,
  CheckCircle2,
} from "lucide-vue-next";
import { state, act, navigate, resumeTask, dismissResumeTask } from "../store";
import { request } from "../api";
import { features, statuses, date, terminal } from "../format";
import { executionProfiles, queueReason, summarizeWork } from "../overview";
import {
  visibleLatestUnfinished,
  visibleResumableTasks,
  visibleUnfinishedTotal,
} from "../mission";
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
        <div
          class="progress-track"
          :class="{ indeterminate: progress === null }"
        >
          <i :style="{ width: (progress || 0) + '%' }" />
        </div>
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
      <button
        v-for="item in queue"
        :key="item.id"
        class="queue-row"
        @click="openQueue(item)"
      >
        <span class="queue-main">
          <b>{{ item.course_name }}</b>
          <small>{{ item.account_label }} · {{ item.feature_label }}</small>
        </span>
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
        </span>
        <span class="queue-when num">{{ date(item.created_at) }}</span>
      </button>
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
                <div
                  class="progress-track"
                  :class="{ indeterminate: t.progress.percent === null }"
                >
                  <i :style="{ width: (t.progress.percent || 0) + '%' }" />
                </div>
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
            @click="control(p.account.id, 'stop')"
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
      <button @click="navigate('tasks')">去创建任务</button>
    </div>
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
  border: 1px solid #e6d3ac;
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
  background: #fff;
  color: var(--warn);
}

.resume-copy {
  min-width: 0;
}

.resume-copy b {
  font-size: 12.5px;
  color: #6b4606;
}

.resume-copy p {
  font-size: 11.5px;
  color: #7c5a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-actions {
  display: flex;
  align-items: center;
  gap: 10px;
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
  font-size: 26px;
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
  border-color: #e5c1bc;
  background: var(--danger-soft);
  color: #7c2a22;
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
    minmax(0, 1.5fr) 78px minmax(0, 1.4fr) 62px 78px;
  gap: 12px;
  align-items: center;
  padding: 0 12px;
}

.queue-head {
  height: 28px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.queue-row {
  width: 100%;
  height: auto;
  min-height: 40px;
  padding: 7px 12px;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: var(--surface);
  text-align: left;
}

.queue-row:last-child {
  border-bottom: 0;
}

.queue-row:hover:not(:disabled) {
  background: var(--surface2);
  border-color: var(--line);
}

.queue-main {
  display: grid;
  gap: 1px;
  min-width: 0;
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
  gap: 12px;
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
  gap: 9px;
  padding: 9px 12px;
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
  gap: 10px;
  max-height: 300px;
  padding: 11px 12px;
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
  gap: 6px;
  padding: 8px 10px;
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
  gap: 3px;
}

.media-live li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  font-size: 11px;
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
  color: #8a3529;
}

.account-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
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
  min-height: 36px;
  padding: 7px 12px;
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
  gap: 1px;
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
  .resume-banner {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .resume-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }

  .queue-head,
  .queue-row,
  .recent-row {
    grid-template-columns: minmax(0, 1fr) 78px;
  }

  .queue-head > span:nth-child(4),
  .queue-row > .queue-meta,
  .recent-row > .recent-meta {
    display: none;
  }

  .execution-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>