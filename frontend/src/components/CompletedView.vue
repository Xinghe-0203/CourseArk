<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import {
  ChevronRight,
  ExternalLink,
  FileText,
  Inbox,
  Plus,
  Search,
  Timer,
} from "lucide-vue-next";
import { act, navigate, state } from "../store";
import { request } from "../api";
import { date, features, statuses } from "../format";
import type { CompletedTask, Task } from "../types";

const emit = defineEmits<{ select: [task: Task] }>();

/** 考试任务在考后拿不到逐题回顾，列表与详情都要把这件事说清楚。 */
const EXAM_NOTE = "已交卷，平台不提供考后逐题回顾";

const items = ref<CompletedTask[]>([]);
const total = ref(0);
const offset = ref(0);
const query = ref("");
const account = ref("");
const feature = ref("");
const status = ref("");
const loading = ref(false);
const loadError = ref("");
/** /tasks/{id} 返回的 answers_note：列表 outcome.reason 之外的第二来源。 */
const notes = ref<Record<string, string>>({});
let generation = 0;
let debounce: ReturnType<typeof setTimeout> | undefined;

/** 每页条数读 settings.ui.completed_page_size（后端已 clamp 到 10..100）。 */
const pageSize = computed(() => {
  const value = Number(state.settings?.ui?.completed_page_size);
  return Number.isFinite(value) && value > 0 ? Math.min(100, Math.round(value)) : 30;
});
const sizeOptions = [10, 20, 30, 50, 100];
const statusOptions: [string, string][] = [
  ["succeeded", "成功完成"],
  ["failed", "失败需处理"],
  ["stopped", "已停止"],
  ["interrupted", "已中断"],
];

/**
 * 状态筛选改打 /api/history 服务端过滤（T7.5）：history 支持 status 参数且
 * 上限 200，不再本地截断 100 条；无状态筛选时仍走 /api/completed（带逐题
 * 汇总、耗时、结果说明的完整视图，分页语义也只在无状态时成立）。
 */
const requestLimit = computed(() => (status.value ? 200 : pageSize.value));
const requestOffset = computed(() => (status.value ? 0 : offset.value));
const filtered = computed(() =>
  status.value
    ? items.value.filter((task) => task.status === status.value)
    : items.value,
);
/** 状态筛选时按接口上限取最新一批，分页语义不再成立，因此隐藏分页。 */
const paginable = computed(() => !status.value && total.value > pageSize.value);
/** 状态筛选但结果被 200 条上限截断时给出说明，避免误以为「只有这些」。 */
const statusCapped = computed(
  () => Boolean(status.value) && total.value > 200,
);

/** 是否有筛选条件：决定空状态是「筛选无结果」还是「确实还没有数据」。 */
const hasFilters = computed(() =>
  Boolean(query.value || account.value || feature.value || status.value),
);

function clearFilters() {
  query.value = "";
  account.value = "";
  feature.value = "";
  status.value = "";
}

async function load() {
  const current = ++generation;
  loading.value = true;
  loadError.value = "";
  try {
    /** 状态筛选走 /api/history（status 服务端过滤）；否则 /api/completed 完整视图。 */
    const path = status.value ? "/history" : "/completed";
    const statusParam = status.value
      ? `&status=${encodeURIComponent(status.value)}`
      : "";
    const data = await request<{ total: number; items: CompletedTask[] }>(
      `${path}?feature=${encodeURIComponent(feature.value)}` +
        `&account_id=${encodeURIComponent(account.value)}` +
        `&q=${encodeURIComponent(query.value)}${statusParam}` +
        `&limit=${requestLimit.value}&offset=${requestOffset.value}`,
    );
    if (current !== generation) return;
    items.value = data.items || [];
    total.value = data.total || 0;
  } catch (error) {
    if (current !== generation) return;
    items.value = [];
    total.value = 0;
    loadError.value = error instanceof Error ? error.message : String(error);
  } finally {
    if (current === generation) loading.value = false;
  }
}

watch([query, account, feature, status], () => {
  offset.value = 0;
  clearTimeout(debounce);
  debounce = setTimeout(load, 250);
});
watch([offset, pageSize], load, { immediate: true });
onUnmounted(() => {
  generation++;
  clearTimeout(debounce);
});

function durationText(task: CompletedTask) {
  const raw = task.duration_seconds;
  if (raw === null || raw === undefined) return "—";
  const seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  const minutes = Math.floor(seconds / 60);
  let rest = Math.round(seconds - minutes * 60);
  if (rest === 60) return `${minutes + 1} 分 0 秒`;
  return `${minutes} 分 ${rest} 秒`;
}

/** 逐题概要：AI / 缓存 / 随机 / 未作答 与提交确认，全部来自后端汇总。 */
function answersText(task: CompletedTask) {
  const summary = task.answers_summary || {};
  const answered = Number(summary.answered || 0);
  const questions = Number(summary.total || 0);
  const parts: string[] = [];
  if (task.answers_count) parts.push(`逐题明细 ${task.answers_count} 条`);
  if (answered || questions)
    parts.push(`作答 ${answered}${questions ? `/${questions}` : ""} 题`);
  const ai = Number(summary.ai || 0);
  const cache = Number(summary.cache || 0);
  const random = Number(summary.random || 0);
  const failed = Number(summary.failed || 0);
  if (ai) parts.push(`AI 作答 ${ai}`);
  if (cache) parts.push(`缓存命中 ${cache}`);
  if (random) parts.push(`随机选择 ${random}`);
  if (failed) parts.push(`未作答 ${failed}`);
  const submitOk = Number(summary.submit_ok || 0);
  const submitFail = Number(summary.submit_fail || 0);
  if (submitOk) parts.push(`提交成功 ${submitOk}`);
  if (submitFail) parts.push(`提交失败 ${submitFail}`);
  return parts.join(" · ") || "本次没有逐题作答记录";
}

function rowNote(task: CompletedTask) {
  return notes.value[task.id] || task.outcome?.reason || "";
}

function openDetail(task: CompletedTask) {
  emit("select", task);
  void enrichNote(task);
}

/** 详情接口会补 answers_note：列表里的结果说明为空时用它兜底。 */
async function enrichNote(task: CompletedTask) {
  try {
    const detail = await request<Task>(`/tasks/${task.id}`);
    if (detail.answers_note)
      notes.value = { ...notes.value, [task.id]: detail.answers_note };
  } catch {
    // 详情读取失败不影响列表：结果说明仍用列表返回的 outcome.reason。
  }
}

function changeSize(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value) || 30;
  offset.value = 0;
  act(
    "completed-page-size",
    async () => {
      await request("/settings", "PATCH", {
        ui: { completed_page_size: value },
      });
      state.settings.ui = {
        ...(state.settings.ui || {}),
        completed_page_size: value,
      };
    },
    `「已完成」每页显示 ${value} 条`,
  );
}

/** 状态筛选行来自 /api/history，缺 answers_summary/outcome：提示用户开详情补齐。 */
const rowNoteFallback = "状态筛选结果不含逐题汇总，点「查看详情」可查看逐题与日志。";
</script>
<template>
  <div class="completed">
    <div class="filterbar completed-filterbar">
      <label class="search"
        ><Search :size="14" /><input
          v-model="query"
          placeholder="搜索课程或账号"
          aria-label="搜索已完成任务" /></label
      ><select v-model="account" aria-label="已完成账号筛选">
        <option value="">所有账号</option>
        <option v-for="a in state.accounts" :key="a.id" :value="a.id">
          {{ a.label || a.username }}
        </option></select
      ><select v-model="feature" aria-label="已完成功能筛选">
        <option value="">全部功能</option>
        <option v-for="(name, key) in features" :key="key" :value="key">
          {{ name }}
        </option></select
      ><select v-model="status" aria-label="已完成状态筛选">
        <option value="">全部结果</option>
        <option
          v-for="[value, name] in statusOptions"
          :key="value"
          :value="value"
        >
          {{ name }}
        </option></select
      ><label class="completed-size"
        ><span>每页</span
        ><select
          :value="pageSize"
          aria-label="已完成每页条数"
          @change="changeSize"
        >
          <option v-for="n in sizeOptions" :key="n" :value="n">
            {{ n }} 条
          </option>
        </select></label
      >
    </div>
    <div
      v-if="loadError"
      class="alert error completed-load-error"
      role="alert"
    >
      <span>读取已完成任务失败：{{ loadError }}</span
      ><button type="button" @click="load">重新读取</button>
    </div>
    <div v-if="loading" class="empty completed-loading">
      正在读取已完成任务…
    </div>
    <div v-else class="completed-list">
      <div v-if="filtered.length" class="completed-head-row" aria-hidden="true">
        <span>结果</span><span>课程与任务</span><span>逐题概要</span
        ><span>耗时与时间</span><span />
      </div>
      <article v-for="task in filtered" :key="task.id" class="completed-row">
        <span :class="['status', task.status]"
          ><i />{{ statuses[task.status] || task.status }}</span
        >
        <button class="completed-title" @click="openDetail(task)">
          <b>{{ task.course_name || "未命名课程" }}</b>
          <small
            >{{ task.feature_label || features[task.feature] || task.feature }}
            · {{ task.account_label || "未命名账号" }} ·
            {{ date(task.finished_at) }}</small
          >
        </button>
        <p class="completed-answers">
          <span class="completed-answers-text">{{ answersText(task) }}</span>
        </p>
        <div class="completed-when">
          <span class="completed-duration"
            ><Timer :size="12" />{{ durationText(task) }}</span
          >
          <small class="num"
            >{{ date(task.started_at) }} → {{ date(task.finished_at) }}</small
          >
        </div>
        <button
          class="icon-button completed-more"
          aria-label="查看任务详情"
          title="查看任务详情"
          @click="openDetail(task)"
        >
          <ChevronRight :size="14" />
        </button>
        <div v-if="rowNote(task) || task.exam" class="completed-body">
          <p v-if="rowNote(task)" class="completed-note" role="status">
            {{ rowNote(task) }}
          </p>
          <p v-if="task.exam" class="completed-exam">
            <FileText :size="13" /><b>{{ task.exam.title || "考试" }}</b
            ><small v-if="task.exam.exam_id">编号 {{ task.exam.exam_id }}</small
            ><em v-if="task.exam.already_done">已交卷</em>
            <span class="completed-exam-note">{{ EXAM_NOTE }}</span
            ><a
              v-if="task.exam.url"
              :href="task.exam.url"
              target="_blank"
              rel="noreferrer"
              >打开考试地址<ExternalLink :size="11" /></a
            >
          </p>
        </div>
      </article>
      <div v-if="!filtered.length" class="empty completed-empty">
        <Inbox :size="26" />
        <h3>
          {{
            hasFilters ? "当前筛选条件下没有已完成的任务" : "还没有已完成的任务"
          }}
        </h3>
        <p v-if="hasFilters">
          换一个关键词或清空筛选，可以看到全部已结束的任务。
        </p>
        <p v-else>
          跑完第一个学习任务后，这里会汇总课程、耗时、逐题明细与失败原因。
        </p>
        <div class="button-row">
          <button v-if="hasFilters" class="button" @click="clearFilters">
            清空筛选条件
          </button>
          <button v-else class="primary" @click="navigate('tasks')">
            <Plus :size="14" />去新建学习任务
          </button>
        </div>
      </div>
    </div>
    <div v-if="status" class="completed-scope">
      <span
        >正在最近 {{ requestLimit }} 条已结束任务中筛选，命中
        {{ filtered.length }} 条。</span
      >
      <span v-if="statusCapped"
        >更早的任务未参与筛选，可缩小账号或功能范围后再试。</span
      >
      <span>{{ rowNoteFallback }}</span>
    </div>
    <div v-if="paginable" class="pagination">
      <button
        type="button"
        :disabled="offset === 0"
        @click="offset = Math.max(0, offset - pageSize)"
      >
        上一页
      </button>
      <span
        >{{ offset + 1 }}—{{ Math.min(offset + pageSize, total) }} /
        {{ total }}</span
      >
      <button
        type="button"
        :disabled="offset + pageSize >= total"
        @click="offset += pageSize"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<style scoped>
.completed {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.completed-filterbar {
  align-items: center;
}

.completed-size {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  font-size: 11px;
  color: var(--faint);
}

.completed-size select {
  height: 26px;
  width: auto;
  font-size: 11.5px;
}

.completed-load-error {
  justify-content: space-between;
}

.completed-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.completed-head-row,
.completed-row {
  display: grid;
  grid-template-columns:
    74px minmax(0, 1.5fr) minmax(0, 1.7fr) minmax(0, 200px) 30px;
  align-items: center;
  gap: 14px;
  padding: 0 14px;
}

.completed-head-row {
  height: 34px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10px;
  letter-spacing: 0.05em;
  color: var(--faint);
  text-transform: uppercase;
}

.completed-row {
  align-items: start;
  padding-top: 13px;
  padding-bottom: 13px;
  border-bottom: 1px solid var(--line);
}

.completed-row:last-child {
  border-bottom: 0;
}

.completed-row:hover {
  background: var(--surface2);
}

.completed-row .status {
  justify-self: start;
  margin-top: 2px;
}

.completed-title {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
}

.completed-title:hover:not(:disabled) {
  background: transparent;
  border-color: transparent;
}

.completed-title b {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.completed-title small {
  font-size: 11px;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.completed-answers {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--mute);
  overflow-wrap: anywhere;
}

.completed-answers-text {
  color: var(--ink2);
}

.completed-when {
  display: grid;
  gap: 3px;
  font-size: 10.5px;
}

.completed-duration {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-num);
  font-size: 12px;
  color: var(--ink);
}

.completed-when small {
  font-size: 10.5px;
  color: var(--faint);
}

.completed-more {
  width: 26px;
  height: 26px;
  justify-self: end;
}

.completed-body {
  grid-column: 2 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin-top: 7px;
}

.completed-note {
  margin: 0;
  font-size: 11.5px;
  color: var(--warn);
}

.completed-exam {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 11.5px;
  color: var(--mute);
}

.completed-exam b {
  font-weight: 600;
  color: var(--ink2);
}

.completed-exam small {
  font-family: var(--font-num);
  font-size: 10px;
  color: var(--faint);
}

.completed-exam em {
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: var(--r1);
  font-size: 10px;
  font-style: normal;
  color: var(--ok);
  background: var(--ok-soft);
}

.completed-exam-note {
  color: var(--faint);
}

.completed-exam a {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--info);
  font-size: 11px;
  text-decoration: none;
}

.completed-exam a:hover {
  text-decoration: underline;
}

.completed-empty {
  border: 0;
  border-radius: 0;
  padding: 34px 16px;
}

.completed-scope {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 12px;
  font-size: 10.5px;
  color: var(--faint);
}

@media (max-width: 1080px) {
  .completed-head-row {
    display: none;
  }

  .completed-row {
    grid-template-columns: 70px minmax(0, 1fr) 26px;
  }

  .completed-answers,
  .completed-when {
    grid-column: 2;
  }

  .completed-more {
    grid-row: 1;
    grid-column: 3;
  }

  .completed-body {
    grid-column: 2 / -1;
  }
}
</style>