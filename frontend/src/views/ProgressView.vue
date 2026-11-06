<script setup lang="ts">
import { computed, ref } from "vue";
import { ChartColumn, ChevronRight, Search } from "lucide-vue-next";
import { state } from "../store";
import { courseKey, courseRows, type CourseRow } from "../course";
import { missionState, missionTotals } from "../mission";
import { active, date, features, statuses } from "../format";
import type { Course, Task } from "../types";

const emit = defineEmits<{ select: [task: Task] }>();
const query = ref("");
const scope = ref("all");


const scopes = [
  { key: "all", text: "全部课程" },
  { key: "running", text: "执行中" },
  { key: "open", text: "有未完成" },
  { key: "done", text: "已完成" },
];

const rows = computed(() => courseRows(state.workspaces));
const missionOf = (row: CourseRow) => missionState(row.course, row.account.syncing);

// 任务点只用数字 + 「待完成」，避免和右侧状态徽标里的「已完成」撞词。
function numbersOf(course: Course) {
  const all = Math.max(0, Number(course.mission_all) || 0);
  const fn = Math.max(0, Number(course.mission_fn) || 0);
  return { all, fn, pending: Math.max(0, all - fn), percent: all ? Math.min(100, Math.round((fn / all) * 100)) : 0 };
}

const filtered = computed(() =>
  rows.value.filter((row) => {
    if (!`${row.account.label} ${row.account.username} ${row.course.name}`.includes(query.value))
      return false;
    const m = missionOf(row);
    if (scope.value === "running")
      return Boolean(row.task && (active(row.task) || row.task.status === "paused"));
    if (scope.value === "open") return m.pending > 0;
    if (scope.value === "done") return Number(row.course.mission_all) > 0 && m.pending === 0;
    return true;
  }),
);

const totals = computed(() => {
  const base = missionTotals(rows.value.map((row) => row.course));
  return { ...base, pending: rows.value.reduce((n, row) => n + missionOf(row).pending, 0) };
});

const overall = computed(() => {
  const { fn, all } = totals.value;
  return all ? Math.min(100, Math.round((fn / all) * 100)) : null;
});

const runningCount = computed(
  () => rows.value.filter((row) => row.task && active(row.task)).length,
);
const pendingCount = computed(
  () => rows.value.filter((row) => missionOf(row).pending > 0).length,
);
const accountCount = computed(() => new Set(rows.value.map((row) => row.account.id)).size);

interface MissionNumbers {
  all: number;
  fn: number;
  pending: number;
  percent: number;
}

const groups = computed(() => {
  const out: {
    id: string;
    label: string;
    username: string;
    enabled: boolean;
    count: number;
    fn: number;
    all: number;
    percent: number | null;
    status: string;
    statusText: string;
    rows: { key: string; row: CourseRow; n: MissionNumbers }[];
  }[] = [];
  for (const row of filtered.value) {
    let group = out.find((item) => item.id === row.account.id);
    if (!group) {
      const status = row.workspace.counts.active
        ? "running"
        : row.workspace.counts.paused
          ? "paused"
          : "pending";
      group = {
        id: row.account.id,
        label: row.account.label || row.account.username,
        username: row.account.username,
        enabled: row.account.enabled,
        count: 0,
        fn: 0,
        all: 0,
        percent: null,
        status,
        statusText: row.account.syncing
          ? "正在同步"
          : !row.account.enabled
            ? "已停用"
            : status === "running"
              ? "正在执行"
              : status === "paused"
                ? "已暂停"
                : "就绪",
        rows: [],
      };
      out.push(group);
    }
    group.count += 1;
    group.rows.push({ key: courseKey(row.account.id, row.course), row, n: numbersOf(row.course) });
  }
  for (const group of out) {
    const base = missionTotals(group.rows.map((item) => item.row.course));
    group.fn = base.fn;
    group.all = base.all;
    group.percent = base.all ? Math.min(100, Math.round((base.fn / base.all) * 100)) : null;
  }
  return out;
});
</script>
<template>
  <div class="progress-view">
    <section class="progress-summary">
      <div class="summary-lead">
        <span class="eyebrow">平台任务点进度</span>
        <strong class="num">{{ totals.fn }}<small> / {{ totals.all || "—" }}</small></strong>
        <p class="muted">
          {{ accountCount }} 个账号 · {{ rows.length }} 门课程 · {{ totals.pending }} 个任务点待完成 ·
          {{ runningCount }} 门正在执行
        </p>
      </div>
      <div class="summary-bar">
        <div class="progress-track" :class="{ indeterminate: overall === null }">
          <i :style="{ width: (overall || 0) + '%' }" />
        </div>
        <div class="progress-pair">
          <span>{{ overall === null ? "任务点尚未同步" : "整体完成度" }}</span>
          <b v-if="overall !== null">{{ overall }}%</b>
        </div>
      </div>
      <div class="summary-facts">
        <div><strong class="num">{{ runningCount }}</strong><span>正在执行</span></div>
        <div><strong class="num">{{ pendingCount }}</strong><span>有未完成</span></div>
        <div><strong class="num">{{ totals.synced ? totals.all - totals.fn : "—" }}</strong
        ><span>剩余任务点</span></div>
      </div>
    </section>

    <div class="filterbar">
      <label class="search"
        ><Search :size="15" /><input
          v-model="query"
          placeholder="搜索账号或课程"
          aria-label="搜索课程进度"
      /></label>
      <select v-model="scope" aria-label="进度范围">
        <option v-for="item in scopes" :key="item.key" :value="item.key">{{ item.text }}</option>
      </select>
      <span class="faint">{{ filtered.length }} 门课程</span>
    </div>

    <div class="progress-groups" v-if="groups.length">
      <section v-for="group in groups" :key="group.id" class="progress-account">
        <header class="progress-account-head">
          <span class="avatar">{{ group.label.slice(0, 1) }}</span>
          <div class="account-name">
            <b>{{ group.label }}</b>
            <small>{{ group.username }} · {{ group.count }} 门课程</small>
          </div>
          <span :class="['status', group.status]"><i />{{ group.statusText }}</span>
          <div class="account-total">
            <b class="num">{{ group.fn }}<small> / {{ group.all || "—" }}</small></b>
            <span v-if="group.percent !== null" class="num">{{ group.percent }}%</span>
            <span v-else class="faint">未同步</span>
          </div>
        </header>
        <div class="progress-course-head">
          <span>课程</span><span>平台任务点</span><span>本轮任务</span><span>完成度</span>
        </div>
        <article v-for="item in group.rows" :key="item.key" class="progress-course">
          <div class="course-name">
            <b>{{ item.row.course.name }}</b>
            <small>
              {{ item.row.course.author || "课程" }}
              <template v-if="item.row.course.synced_at"> · 缓存 {{ date(item.row.course.synced_at) }}</template>
            </small>
          </div>
          <div class="course-mission">
            <span class="mission-count">
              <b class="num">{{ item.n.fn }}</b>
              <small class="num"> / {{ item.n.all || "—" }}</small>
            </span>
            <small class="mission-note faint">{{
              item.n.all ? (item.n.pending ? "待完成 " + item.n.pending : "已全部完成") : "任务点未同步"
            }}</small>
          </div>
          <div class="course-task">
            <template v-if="item.row.task">
              <span :class="['status', item.row.task.status]"
                ><i />{{ statuses[item.row.task.status] }}</span
              >
              <small class="muted">{{
                features[item.row.task.feature] || item.row.task.feature_label
              }}</small>
              <small v-if="item.row.task.progress.total" class="num"
                >{{ item.row.task.progress.completed }} /
                {{ item.row.task.progress.total }} 项</small
              >
              <button class="text-link" @click="emit('select', item.row.task)">
                详情<ChevronRight :size="12" />
              </button>
            </template>
            <span v-else class="faint">{{ item.row.course.if_open ? "还没有执行过" : "课程已关闭" }}</span>
          </div>
          <div class="course-progress">
            <div class="progress-track small">
              <i :style="{ width: item.n.percent + '%' }" />
            </div>
            <b class="num">{{ item.n.percent }}%</b>
          </div>
        </article>
      </section>
    </div>

    <div v-else class="empty">
      <ChartColumn :size="26" />
      <h3>没有符合条件的课程</h3>
      <p>换个关键词或范围看看；账号与课程可以在「账号与课程」页同步。</p>
    </div>
  </div>
</template>
<style scoped>
.progress-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.progress-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr) minmax(0, 0.85fr);
  align-items: center;
  gap: 14px 28px;
  padding: 16px 20px;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
}

.summary-lead .eyebrow {
  display: block;
  margin-bottom: 6px;
}

.summary-lead strong {
  display: block;
  font-size: 26px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--ink);
}

.summary-lead strong small {
  font-size: 13px;
  color: var(--faint);
}

.summary-lead p {
  margin-top: 7px;
  font-size: 12px;
  line-height: 1.55;
}

.summary-bar {
  min-width: 0;
}

.summary-bar .progress-pair {
  margin-top: 9px;
}

.summary-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: var(--r2);
  overflow: hidden;
}

.summary-facts > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-right: 1px solid var(--line);
  background: var(--surface2);
}

.summary-facts > div:last-child {
  border-right: 0;
}

.summary-facts strong {
  font-size: 16px;
  font-weight: 500;
  line-height: 1.25;
}

.summary-facts span {
  font-size: 11px;
  line-height: 1.4;
  color: var(--faint);
}

.filterbar {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-groups {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.progress-account {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.progress-account-head {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 6px 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.account-name {
  min-width: 0;
}

.account-name b {
  display: block;
  font-size: 13.5px;
  line-height: 1.4;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-name small {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-total {
  display: flex;
  align-items: baseline;
  gap: 9px;
  padding-left: 14px;
  border-left: 1px solid var(--line);
}

.account-total b {
  font-size: 16px;
  font-weight: 500;
  line-height: 1.25;
}

.account-total b small {
  font-size: 11px;
  color: var(--faint);
}

.account-total > span {
  font-size: 12px;
  color: var(--navy);
}

.progress-course-head,
.progress-course {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1.25fr) minmax(0, 1.15fr) 152px;
  align-items: center;
  gap: 16px;
  padding: 0 14px;
}

.progress-course-head {
  height: 32px;
  border-bottom: 1px solid var(--line);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.progress-course-head span:last-child {
  text-align: right;
}

.progress-course {
  padding-top: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.progress-course:last-child {
  border-bottom: 0;
}

.progress-course:hover {
  background: var(--surface2);
}

.course-name {
  min-width: 0;
}

.course-name b {
  display: block;
  font-size: 13px;
  line-height: 1.45;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-name small {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-mission {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.mission-count {
  display: flex;
  align-items: baseline;
  gap: 1px;
  color: var(--ink2);
}

.mission-count b {
  font-size: 13.5px;
  line-height: 1.3;
  font-weight: 600;
}

.mission-count small {
  font-size: 11.5px;
  line-height: 1.3;
  color: var(--faint);
}

.mission-note {
  font-size: 11px;
  line-height: 1.45;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mission-note:only-child {
  color: var(--faint);
}

.course-task {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 8px;
  min-width: 0;
  font-size: 11.5px;
  line-height: 1.55;
}

.course-task .text-link {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  font-size: 11.5px;
}

.course-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 40px;
  align-items: center;
  gap: 12px;
}

.course-progress b {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink2);
  text-align: right;
}

@media (max-width: 1080px) {
  .progress-summary {
    grid-template-columns: minmax(0, 1fr);
  }

  .progress-course-head {
    display: none;
  }

  .progress-course {
    grid-template-columns: minmax(0, 1fr) 108px;
    gap: 8px 14px;
    padding-top: 14px;
    padding-bottom: 14px;
  }

  .course-name {
    grid-column: 1;
  }

  .course-progress {
    grid-column: 2;
    grid-row: 1;
  }

  .course-mission {
    grid-column: 1;
  }

  .course-task {
    grid-column: 1 / -1;
  }
}
</style>
