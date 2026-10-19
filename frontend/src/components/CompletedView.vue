<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import {
  ChevronRight,
  ExternalLink,
  FileText,
  Inbox,
  Layers,
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

async function load() {
  const current = ++generation;
  loading.value = true;
  loadError.value = "";
  try {
    const data = await request<{ total: number; items: CompletedTask[] }>(
      `/completed?feature=${encodeURIComponent(feature.value)}` +
        `&account_id=${encodeURIComponent(account.value)}` +
        `&q=${encodeURIComponent(query.value)}` +
        `&limit=${pageSize.value}&offset=${offset.value}`,
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

/** 状态筛选在本地进行：后端 /api/completed 固定只返回四种终态，没有 status 参数。 */
const filtered = computed(() =>
  status.value
    ? items.value.filter((task) => task.status === status.value)
    : items.value,
);

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
</script>
<template>
  <div class="filterbar completed-filterbar">
    <label class="search"
      ><Search :size="17" /><input
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
      <option v-for="[value, name] in statusOptions" :key="value" :value="value">
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
  <div v-if="loadError" class="alert error completed-load-error" role="alert">
    <span>读取已完成任务失败：{{ loadError }}</span
    ><button type="button" @click="load">重新读取</button>
  </div>
  <div v-if="loading" class="empty completed-loading">正在读取已完成任务…</div>
  <div v-else class="completed-list">
    <article v-for="task in filtered" :key="task.id" class="completed-row">
      <div class="completed-head">
        <span :class="['status', task.status]"
          ><i />{{ statuses[task.status] || task.status }}</span
        >
        <button class="completed-title" @click="openDetail(task)">
          <span class="course-icon"><Layers :size="18" /></span
          ><span
            ><b>{{ task.course_name || "未命名课程" }}</b
            ><small
              >{{ task.feature_label || features[task.feature] || task.feature }} ·
              {{ task.account_label || "未命名账号" }}</small
            ></span
          >
        </button>
        <div class="completed-when">
          <span>开始 {{ date(task.started_at) }}</span>
          <span>结束 {{ date(task.finished_at) }}</span>
          <span class="completed-duration"
            ><Timer :size="13" />耗时 {{ durationText(task) }}</span
          >
        </div>
      </div>
      <div class="completed-body">
        <p v-if="rowNote(task)" class="alert completed-note" role="status">
          {{ rowNote(task) }}
        </p>
        <p v-if="task.exam" class="completed-exam">
          <FileText :size="14" /><span
            ><b>{{ task.exam.title || "考试" }}</b
            ><small v-if="task.exam.exam_id"
              >编号 {{ task.exam.exam_id }}</small
            ><em v-if="task.exam.already_done">已交卷</em> · {{ EXAM_NOTE }}</span
          ><a
            v-if="task.exam.url"
            :href="task.exam.url"
            target="_blank"
            rel="noreferrer"
            >打开考试地址<ExternalLink :size="12" /></a
          >
        </p>
        <div class="completed-answers">
          <span class="completed-answers-label">逐题概要</span>
          <span class="completed-answers-text">{{ answersText(task) }}</span>
        </div>
        <button
          class="text-link completed-more"
          aria-label="查看任务详情"
          @click="openDetail(task)"
        >
          查看详情<ChevronRight :size="14" />
        </button>
      </div>
    </article>
    <div v-if="!filtered.length" class="empty completed-empty">
      <Inbox :size="30" />
      <h3>
        {{
          items.length
            ? "当前筛选条件下没有已完成的任务"
            : "还没有已完成的任务"
        }}
      </h3>
      <p v-if="items.length">
        换一个关键词或清空筛选，可以看到全部已结束的任务。
      </p>
      <p v-else>
        跑完第一个学习任务后，这里会汇总课程、耗时、逐题明细与失败原因。
      </p>
      <button class="primary" @click="navigate('tasks')">
        <Plus :size="16" />去新建学习任务
      </button>
    </div>
  </div>
  <div v-if="total > pageSize" class="pagination">
    <button
      type="button"
      :disabled="offset === 0"
      @click="offset = Math.max(0, offset - pageSize)"
    >
      上一页
    </button>
    <span>{{ offset + 1 }}—{{ Math.min(offset + pageSize, total) }} / {{ total }}</span>
    <button
      type="button"
      :disabled="offset + pageSize >= total"
      @click="offset += pageSize"
    >
      下一页
    </button>
  </div>
</template>
<style scoped>
.completed-filterbar {
  align-items: center;
}
.completed-size {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--fg-muted);
  font-size: 11.5px;
}
.completed-size select {
  height: 40px;
}
.completed-load-error {
  justify-content: space-between;
}
.completed-loading {
  margin-bottom: 20px;
}
.completed-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.completed-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  padding: 18px 22px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.completed-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
}
.completed-title {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 12px;
  min-width: 200px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
}
.completed-title:hover {
  background: transparent;
}
.completed-title b {
  display: block;
  overflow: hidden;
  color: var(--fg);
  font-size: 13.5px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.completed-title small {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  color: var(--fg-subtle);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.completed-when {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  color: var(--fg-muted);
  font-size: 11px;
}
.completed-duration {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--fg);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.completed-body {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.completed-note {
  margin: 0;
}
.completed-exam {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--bg-subtle);
  color: var(--fg-muted);
  font-size: 11.5px;
  line-height: 1.6;
}
.completed-exam b {
  color: var(--fg);
  font-weight: 600;
}
.completed-exam small {
  margin-left: 6px;
  color: var(--fg-subtle);
  font-size: 10.5px;
}
.completed-exam em {
  margin-left: 6px;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: var(--r-pill);
  color: var(--ok);
  font-size: 10px;
  font-style: normal;
}
.completed-exam a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  color: var(--info);
  font-size: 11px;
  text-decoration: none;
}
.completed-answers {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  color: var(--fg-muted);
  font-size: 11.5px;
  line-height: 1.6;
}
.completed-answers-label {
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-pill);
  background: var(--bg-subtle);
  color: var(--fg-subtle);
  font-size: 10px;
}
.completed-answers-text {
  overflow-wrap: anywhere;
}
.completed-more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-self: start;
  color: var(--fg);
  font-size: 11.5px;
  font-weight: 600;
}
.completed-empty {
  margin-top: 8px;
}
@media (max-width: 720px) {
  .completed-row {
    padding: 14px 16px;
  }
  .completed-when {
    gap: 8px;
  }
}
</style>
