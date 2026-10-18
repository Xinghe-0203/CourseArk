<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RefreshCw, Radio, LoaderCircle } from "lucide-vue-next";
import type { AnswerItem, Task, TaskEvent } from "../types";
import { request } from "../api";
import { categories, statuses, date, active, terminal } from "../format";
import {
  answerSourceLabel,
  answerStatusLabel,
  groupAnswers,
  summarizeAnswers,
} from "../answers";
import { elapsedSeconds, formatDuration, formatEta } from "../live";
import { state } from "../store";
import ModalShell from "./ModalShell.vue";
const props = defineProps<{ task: Task }>();
defineEmits<{ close: [] }>();
const detail = ref(props.task),
  events = ref<TaskEvent[]>([]),
  category = ref(""),
  level = ref(""),
  error = ref(""),
  follow = ref(false),
  loading = ref(false),
  refreshedAt = ref(0),
  chosen = ref(false),
  log = ref<HTMLElement>(),
  expanded = ref<Set<string>>(new Set());
const live = computed(
  () => active(detail.value) || detail.value.status === "paused",
);
const tab = ref(live.value ? "answers" : "activity");
const answerItems = computed<AnswerItem[]>(() => detail.value.answers || []);
const groups = computed(() => groupAnswers(answerItems.value));
const summary = computed(() =>
  summarizeAnswers(answerItems.value, detail.value.answers_summary),
);
const liveLine = computed(() => {
  const value = detail.value.live;
  if (!live.value || !value) return "";
  const elapsed = formatDuration(elapsedSeconds(detail.value));
  const eta = value.eta_seconds ? formatEta(value.eta_seconds) : "计算中";
  return `${value.activity || "任务运行中"} · 已用时 ${elapsed} · 预计剩余 ${eta}`;
});
const filtered = computed(() =>
  (tab.value === "activity"
    ? detail.value.activity_events || events.value
    : events.value
  ).filter(
    (e) =>
      (!category.value ||
        (e.presentation?.category || e.stage) === category.value) &&
      (!level.value || e.level === level.value) &&
      (tab.value === "logs" ||
        (e.presentation
          ? e.presentation.visible
          : e.event !== "log" && e.event !== "task_progress")),
  ),
);
let timer: ReturnType<typeof setTimeout> | undefined,
  sseTimer: ReturnType<typeof setTimeout> | undefined,
  closed = false;
function key(item: AnswerItem) {
  return item.key || `${item.media || ""}#${item.index}`;
}
function isLong(item: AnswerItem) {
  return (item.question || "").length > 72 || (item.options?.length || 0) > 3;
}
function isExpanded(item: AnswerItem) {
  return expanded.value.has(key(item));
}
function toggle(item: AnswerItem) {
  const next = new Set(expanded.value);
  if (next.has(key(item))) next.delete(key(item));
  else next.add(key(item));
  expanded.value = next;
}
function pick(name: string) {
  tab.value = name;
  chosen.value = true;
}
// 独立考试的作答事件 category 同为 exam，但文案不能显示成章节测验。
function categoryLabel(name: string) {
  if (detail.value.feature === "exam" && name === "exam") return "独立考试";
  return categories[name] || "任务运行";
}
function groupPercent(group: { answered: number; total: number }) {
  return group.total ? Math.round((group.answered / group.total) * 100) : 0;
}
function schedule() {
  clearTimeout(timer);
  if (closed) return;
  if (terminal(detail.value)) return;
  // 运行中/暂停时 1.5s 拉一次逐题明细，其余非终态 3s 兜底。
  timer = setTimeout(load, live.value ? 1500 : 3000);
}
async function load() {
  if (closed) return;
  const id = props.task.id;
  loading.value = true;
  try {
    const value = await request<Task>(`/tasks/${id}`);
    if (closed || id !== props.task.id) return;
    detail.value = value;
    events.value = value.events || [];
    refreshedAt.value = Date.now();
    error.value = "";
    if (!chosen.value && (value.answers?.length || live.value))
      tab.value = "answers";
    if (follow.value)
      setTimeout(() => log.value?.scrollTo({ top: log.value.scrollHeight }), 0);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
    schedule();
  }
}
onMounted(load);
onUnmounted(() => {
  closed = true;
  clearTimeout(timer);
  clearTimeout(sseTimer);
});
// 在抽屉内切换到另一个任务时重置本地状态并立即拉取详情。
watch(
  () => props.task.id,
  () => {
    detail.value = props.task;
    events.value = [];
    expanded.value = new Set();
    chosen.value = false;
    tab.value = live.value ? "answers" : "activity";
    load();
  },
);
// SSE 事件到达后尽快同步逐题明细（沿用 store 的 500ms 刷新节奏）。
watch(
  () => state.eventRevision,
  () => {
    if (closed) return;
    clearTimeout(sseTimer);
    sseTimer = setTimeout(load, 300);
  },
);
</script>
<template>
  <ModalShell :title="task.course_name" wide @close="$emit('close')"
    ><div class="detail-summary">
      <span :class="['status', detail.status]">{{
        statuses[detail.status]
      }}</span
      ><span>{{ detail.account_label }} · {{ detail.feature_label }}</span
      ><span class="muted">{{ date(detail.started_at) }}</span
      ><span v-if="live" class="live-badge"
        ><i /><Radio :size="12" />实时更新中</span
      >
    </div>
    <p v-if="liveLine" class="detail-live-line">
      <LoaderCircle class="spin" :size="13" />{{ liveLine }}
    </p>
    <p v-if="detail.error || error" class="alert error">
      {{ detail.error || error }}
    </p>
    <div class="detail-metrics">
      <div>
        <strong
          >{{ detail.progress?.completed || 0 }} /
          {{ detail.progress?.total || "—" }}</strong
        ><small>已确认完成</small>
      </div>
      <div>
        <strong>{{ summary.answered || detail.stats.questions || 0 }}</strong
        ><small>已作答题目</small>
      </div>
      <div>
        <strong>{{ summary.submit_ok || detail.stats.submit_ok || 0 }}</strong
        ><small>已接受提交</small>
      </div>
      <div>
        <strong>{{
          (detail.progress?.failed || 0) + (detail.progress?.blocked || 0) ||
          detail.stats.failed ||
          0
        }}</strong
        ><small>未完成事项</small>
      </div>
    </div>
    <div class="tabs">
      <button :class="{ selected: tab === 'answers' }" @click="pick('answers')">
        AI 做题<span v-if="answerItems.length" class="tab-badge">{{
          answerItems.length
        }}</span></button
      ><button
        :class="{ selected: tab === 'activity' }"
        @click="pick('activity')"
      >
        学习动态</button
      ><button :class="{ selected: tab === 'logs' }" @click="pick('logs')">
        诊断日志</button
      ><button :class="{ selected: tab === 'params' }" @click="pick('params')">
        任务参数
      </button>
    </div>
    <template v-if="tab === 'answers'">
      <div v-if="groups.length" class="answer-summary">
        <span class="answer-chip strong"
          >作答 {{ summary.answered }}/{{ summary.total || "—" }}</span
        ><span v-if="summary.ai" class="answer-chip ai"
          >AI {{ summary.ai }}</span
        ><span v-if="summary.cache" class="answer-chip cache"
          >缓存 {{ summary.cache }}</span
        ><span v-if="summary.random" class="answer-chip random"
          >随机 {{ summary.random }}</span
        ><span v-if="summary.skipped" class="answer-chip failed"
          >待处理 {{ summary.skipped }}</span
        ><span v-if="summary.submit_ok" class="answer-chip submit-ok"
          >提交成功 {{ summary.submit_ok }}</span
        ><span v-if="summary.submit_fail" class="answer-chip submit-fail"
          >提交失败 {{ summary.submit_fail }}</span
        ><button
          class="text-link answer-refresh"
          :disabled="loading"
          @click="load"
        >
          <RefreshCw :size="13" :class="{ spin: loading }" />{{
            loading ? "同步中" : refreshedAt ? "刷新" : "同步"
          }}
        </button>
      </div>
      <p v-if="groups.length && live" class="muted answer-live">
        <i class="live-dot" />每题作答后立即追加，运行中每 1.5 秒自动同步。
      </p>
      <div v-if="groups.length" class="answer-groups">
        <section v-for="group in groups" :key="group.media" class="answer-group">
          <header class="answer-group-head">
            <div>
              <h3>{{ group.media }}</h3>
              <small
                >{{ group.answered }}/{{ group.total }} 题已作答<template
                  v-if="group.skipped"
                >
                  · {{ group.skipped }} 题待处理</template
                ></small
              >
            </div>
            <div class="answer-group-progress">
              <div
                class="progress-track"
                role="progressbar"
                :aria-valuenow="groupPercent(group)"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-label="group.media + '作答进度'"
              >
                <i :style="{ width: groupPercent(group) + '%' }" />
              </div>
              <b>{{ groupPercent(group) }}%</b>
            </div>
          </header>
          <article
            v-for="item in group.items"
            :key="key(item)"
            :class="['answer-card', { expanded: isExpanded(item) }]"
          >
            <div class="answer-head">
              <span class="answer-index">#{{ item.index }}</span
              ><span class="tag">{{ item.question_type || "未知题型" }}</span
              ><span :class="['source-badge', item.source]">{{
                answerSourceLabel(item.source)
              }}</span
              ><span :class="['answer-status', item.status]">{{
                answerStatusLabel(item.status)
              }}</span
              ><time>{{ date(item.ts) }}</time>
            </div>
            <p class="answer-question" @click="isLong(item) && toggle(item)">
              {{ item.question || "（题干未识别）" }}
            </p>
            <button
              v-if="isLong(item)"
              class="text-link answer-expand"
              @click="toggle(item)"
            >
              {{ isExpanded(item) ? "收起" : "展开题干与全部选项" }}
            </button>
            <ol v-if="item.options?.length" class="answer-options">
              <li v-for="(option, i) in item.options" :key="i">{{ option }}</li>
            </ol>
            <div class="answer-foot">
              <span class="answer-label">答案</span
              ><b v-if="item.answer">{{ item.answer }}</b
              ><span v-else class="muted">无答案</span
              ><span v-if="item.note" class="answer-note">{{ item.note }}</span>
            </div>
          </article>
        </section>
      </div>
      <div v-else class="empty answer-empty">
        <svg
          class="empty-illustration"
          viewBox="0 0 96 96"
          fill="none"
          aria-hidden="true"
        >
          <rect
            x="20"
            y="14"
            width="56"
            height="68"
            rx="8"
            fill="#eef4ff"
            stroke="#cfdcf4"
            stroke-width="2"
          />
          <path
            d="M33 34h30M33 46h30M33 58h18"
            stroke="#a9bde0"
            stroke-width="3"
            stroke-linecap="round"
          />
          <circle cx="68" cy="66" r="14" fill="#e5f4ec" stroke="#a9d3be" stroke-width="2" />
          <path
            d="M61 66.5l4.6 4.4L75 62"
            stroke="#62a887"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <h3>还没有逐题作答记录</h3>
        <p v-if="live">
          AI 正在识别题目，答完一题会立刻显示在这里；也可以稍后手动刷新。
        </p>
        <p v-else>
          旧版本任务或未产生 AI 作答时不会保存明细。任务开始 AI 作答后，这里会实时出现每题题干、答案与来源。
        </p>
        <button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spin: loading }" />重新读取
        </button>
      </div>
    </template>
    <template v-else-if="tab !== 'params'"
      ><div class="filterbar compact">
        <select v-model="category" aria-label="日志分类">
          <option value="">所有分类</option>
          <option v-for="key in Object.keys(categories)" :key="key" :value="key">
            {{ categoryLabel(key) }}
          </option></select
        ><select v-model="level" aria-label="日志级别">
          <option value="">所有级别</option>
          <option value="error">错误</option>
          <option value="warning">需关注</option>
          <option value="info">进度</option>
          <option value="debug">诊断</option></select
        ><label class="check"
          ><input v-model="follow" type="checkbox" />跟随最新</label
        ><a :href="`/api/tasks/${task.id}/logs`" download class="text-link"
          >下载完整日志</a
        >
      </div>
      <p class="muted" v-if="tab === 'logs'">
        显示最近 50 条。分类便于定位问题，完整记录可下载。
      </p>
      <div ref="log" :class="['event-list', { raw: tab === 'logs' }]">
        <article v-for="e in filtered" :key="e.id" :class="['event', e.level]">
          <time>{{ date(e.ts) }}</time>
          <div>
            <span class="event-category">{{
              categoryLabel(e.presentation?.category || e.stage)
            }}</span
            ><b>{{
              tab === "logs"
                ? e.message
                : e.presentation?.title || e.narrative.title
            }}</b>
            <p v-if="tab !== 'logs'">
              {{ e.presentation?.detail || e.narrative.detail }}
            </p>
            <p
              v-if="e.presentation?.action && tab !== 'logs'"
              class="action-hint"
            >
              {{ e.presentation.action }}
            </p>
          </div>
        </article>
        <div v-if="!filtered.length" class="empty">暂无此类记录</div>
      </div></template
    >
    <pre v-else class="params-preview">{{
      JSON.stringify(detail.params, null, 2)
    }}</pre>
  </ModalShell>
</template>
