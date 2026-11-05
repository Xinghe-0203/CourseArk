<script setup lang="ts">
import { computed } from "vue";
import {
  Users,
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
  <div v-if="unfinished.total" class="resume-banner" role="status">
    <span class="resume-icon"><History :size="20" /></span>
    <div class="resume-copy">
      <b>上次任务未完成，共 {{ unfinished.total }} 项</b>
      <p v-if="unfinished.latest">
        {{ unfinished.latest.course_name }} ·
        {{ date(unfinished.latest.created_at) }} 中断，可从中断处继续，无需重新开始。
      </p>
      <p v-else>可以从中断处继续，无需重新开始。</p>
    </div>
    <button
      class="primary"
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
  <div class="metrics overview-metrics">
    <div>
      <span>执行中的账号</span
      ><strong>{{ activeAccounts }}<small>个账号</small></strong>
      <p>{{ tasks.length }} 项任务正在执行</p>
      <Users :size="21" />
    </div>
    <div>
      <span>执行中的课程</span
      ><strong>{{ activeCourses }}<small>门课程</small></strong>
      <p>课程任务点与独立作业</p>
      <Layers :size="21" />
    </div>
    <div>
      <span>本轮已确认</span
      ><strong
        >{{ totals.completed
        }}<small>/ {{ totals.total || "—" }} 项</small></strong
      >
      <p>
        {{
          known
            ? "平台确认的实际完成量"
            : tasks.length
              ? "正在读取完整任务范围"
              : "当前没有执行中的任务"
        }}
      </p>
    </div>
    <div>
      <span>待处理内容</span
      ><strong>{{ totals.issues }}<small>项</small></strong>
      <p>{{
        totals.issues
          ? "有内容需要打开任务详情核对"
          : "当前没有需要处理的内容"
      }}</p>
    </div>
  </div>
  <div v-if="tasks.length" class="execution-dashboard">
    <div class="execution-gauge">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="42" class="gauge-track" />
        <circle
          cx="50"
          cy="50"
          r="42"
          class="gauge-value"
          :stroke-dasharray="`${(progress || 0) * 2.639} 263.9`"
        />
      </svg>
      <div>
        <strong>{{ progress === null ? "读取中" : progress + "%" }}</strong
        ><small>{{
          progress === null ? "任务范围尚未完整" : "已确认任务点占比"
        }}</small>
      </div>
    </div>
    <div class="execution-phases">
      <h3>任务运行状态</h3>
      <div v-for="item in phase" :key="item.name">
        <span :class="['dot', item.color]" /><span>{{ item.name }}</span
        ><b>{{ item.count }} 项</b>
        <div class="phase-track">
          <i :style="{ width: (item.count / tasks.length) * 100 + '%' }" />
        </div>
      </div>
    </div>
    <div class="execution-summary">
      <h3>当前执行结果</h3>
      <strong>{{ totals.completed }}<small> 项已确认完成</small></strong>
      <p v-if="totals.issues" class="issue-text">
        {{ totals.issues }} 项内容需要处理，请打开课程详情核对。
      </p>
      <p v-else>各账号独立执行，视频进度、答题来源与提交结果持续更新。</p>
    </div>
  </div>
  <div v-if="queueTotal" class="section-heading queue-heading">
    <div>
      <h2>调度队列</h2>
      <p>正在执行、已暂停与排队等待的任务，共 {{ queueTotal }} 项</p>
    </div>
    <button class="text-link" @click="navigate('tasks')">
      全部任务 <ArrowUpRight :size="16" />
    </button>
  </div>
  <div v-if="queue.length" class="overview-queue">
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
      <span :class="['status', item.status]">{{ statuses[item.status] }}</span>
      <span class="queue-reason">{{ queueReason(item) }}</span>
      <span class="queue-meta">
        <b>{{ summarizeWork(item).completed }}/{{ summarizeWork(item).total }}</b>
        <small>{{ date(item.created_at) }}</small>
      </span>
    </button>
  </div>
  <div class="section-heading">
    <div>
      <h2>正在执行的账号</h2>
      <p>仅显示正在执行的课程 · 点击「详情」查看逐题与日志</p>
    </div>
    <button class="text-link" @click="navigate('tasks')">
      学习任务 <ArrowUpRight :size="16" />
    </button>
  </div>
  <div class="execution-grid">
    <section
      v-for="p in profiles"
      :key="p.account.id"
      class="execution-account"
    >
      <header class="workspace-account-head">
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
        <span class="status running">执行中</span>
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
              }}</span
              ><span :class="['status', t.status]">{{
                statuses[t.status]
              }}</span
              ><button class="text-link" @click="emit('select', t)">
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
              <small
                >{{ t.progress.completed }}/{{ t.progress.total || "—" }}
                项已确认
                <b v-if="t.progress.percent !== null"
                  >{{ t.progress.percent }}%</b
                ></small
              >
            </div>
            <div class="live-details">
              <span
                >开始 {{ date(t.started_at)
                }}<template v-if="t.stats.activity">
                  · {{ (t.stats.activity as { name?: string }).name }}</template
                ></span
              >
              <span
                >答题 {{ t.stats.questions || 0 }} · 缓存命中
                {{ t.stats.cache_hits || 0 }} · AI
                {{ t.stats.llm_calls || 0 }}</span
              ><span
                >提交接受 {{ t.stats.submit_ok || 0 }} · 随机答案
                {{ t.stats.random_answers || 0 }}</span
              >
            </div>
            <p v-if="t.progress.failed + t.progress.blocked" class="issue-text">
              {{ t.progress.failed + t.progress.blocked }}
              项内容待处理，打开详情查看原因。
            </p>
            <ul v-if="t.progress.active.length" class="media-live">
              <li v-for="m in t.progress.active" :key="m.id">
                <span>{{
                  m.kind === "video"
                    ? "视频"
                    : m.kind === "audio"
                      ? "音频"
                      : m.kind === "work"
                        ? "测验"
                        : "任务点"
                }}</span
                ><b :title="m.name">{{ m.name }}</b
                ><small>{{
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
          </div>
        </article>
      </div>
      <footer class="account-controls">
        <button
          :disabled="state.busy.has('overview-' + p.account.id + 'pause')"
          @click="control(p.account.id, 'pause')"
        >
          <Pause :size="14" />暂停账号</button
        ><button
          :disabled="state.busy.has('overview-' + p.account.id + 'stop')"
          @click="control(p.account.id, 'stop')"
        >
          <Square :size="14" />停止账号</button
        ><small>实时任务数据</small>
      </footer>
    </section>
  </div>
  <div v-if="!profiles.length" class="empty">
    <Layers :size="32" />
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
      全部已完成 <ArrowUpRight :size="16" />
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
        <small>{{ t.account_label }} · {{ features[t.feature] || t.feature_label }}</small>
      </span>
      <span :class="['status', t.status]">{{ statuses[t.status] }}</span>
      <span class="recent-meta">
        <b>{{ t.progress.completed }}/{{ t.progress.total || "—" }}</b>
        <small>{{ date(t.finished_at || t.created_at) }}</small>
      </span>
    </button>
  </div>
  <div v-else class="empty overview-recent-empty">
    <CheckCircle2 :size="28" />
    <h3>还没有完成的任务</h3>
    <p>任务跑完后会在这里显示课程、进度与结束时间，完整明细在「已完成」页。</p>
    <button @click="navigate('tasks')">去创建任务</button>
  </div>
</template>
<style scoped>
.queue-heading {
  margin-top: 18px;
}
.overview-queue {
  display: grid;
  gap: 8px;
}
.queue-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1.2fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 14px;
  border: 1px solid var(--line, #e8e8ea);
  border-radius: var(--r-md, 14px);
  background: var(--surface, #f7f7f8);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease;
}
.queue-row:hover {
  border-color: #b9b9c0;
}
.queue-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.queue-main b {
  font-size: 13px;
  color: var(--fg, #0a0a0a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-main small {
  color: var(--fg-muted, #6b6b74);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-reason {
  min-width: 0;
  font-size: 12px;
  color: var(--fg-muted, #6b6b74);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-meta {
  display: grid;
  gap: 2px;
  justify-items: end;
}
.queue-meta b {
  font-size: 12px;
  color: var(--fg, #0a0a0a);
}
.queue-meta small {
  font-size: 11px;
  color: var(--fg-subtle, #a1a1aa);
}
@media (max-width: 850px) {
  .queue-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .queue-reason,
  .queue-meta {
    display: none;
  }
}
</style>
