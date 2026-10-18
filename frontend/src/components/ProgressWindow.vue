<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ChevronDown, LoaderCircle, X } from "lucide-vue-next";
import { request } from "../api";
import { active } from "../format";
import {
  activityOf,
  elapsedSeconds,
  formatDuration,
  formatEta,
  focusTask,
  unitPercent,
  unitText,
} from "../live";
import { setTaskLive, state } from "../store";
import type { Task } from "../types";
defineEmits<{ select: [task: Task] }>();
const POLL_MS = 2000;
const closed = ref(false);
const minimized = ref(false);
const taskId = ref("");
const detail = ref<Task | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
const candidates = computed(() =>
  state.tasks.filter((task) => active(task) || task.status === "paused"),
);
const task = computed<Task | undefined>(() => {
  if (taskId.value && detail.value?.id === taskId.value) return detail.value;
  return state.tasks.find((item) => item.id === taskId.value);
});
const visible = computed(() => !closed.value && candidates.value.length > 0);
const percent = computed(() => {
  const live = task.value?.live;
  const unit = unitPercent(live?.unit);
  if (unit !== null) return unit;
  const overall = task.value?.progress?.percent;
  return typeof overall === "number" ? Math.round(overall) : null;
});
const eta = computed(() => {
  if (task.value?.status === "paused") return "已暂停";
  return formatEta(task.value?.live?.eta_seconds);
});
const elapsed = computed(() => elapsedSeconds(task.value || ({} as Task)));
const unitLabel = computed(() => unitText(task.value?.live?.unit));
function schedule() {
  clearTimeout(timer);
  const current = task.value;
  if (current && (active(current) || current.status === "paused"))
    timer = setTimeout(load, POLL_MS);
}
async function load() {
  const id = taskId.value;
  if (!id || closed.value) return;
  try {
    const data = await request<Task>(`/tasks/${id}`);
    if (id !== taskId.value) return;
    detail.value = data;
    setTaskLive(id, data.live);
    schedule();
  } catch {
    schedule();
  }
}
watch(
  () => candidates.value.map((task) => task.id).join(","),
  () => {
    const live = candidates.value.find((task) => task.id === taskId.value);
    const next = live || focusTask(candidates.value);
    if (!next) {
      taskId.value = "";
      detail.value = null;
      clearTimeout(timer);
      // 这一轮任务结束后，下一轮运行重新显示小窗。
      closed.value = false;
      minimized.value = false;
      return;
    }
    if (next.id !== taskId.value) {
      taskId.value = next.id;
      detail.value = state.tasks.find((item) => item.id === next.id) || null;
      setTaskLive(next.id, next.live);
      load();
    }
  },
  { immediate: true },
);
watch(
  () => state.eventRevision,
  () => load(),
);
onMounted(() => load());
onUnmounted(() => clearTimeout(timer));
</script>
<template>
  <aside
    v-if="visible && task"
    :class="['progress-window', { minimized }]"
    role="status"
    aria-label="运行进度小窗"
  >
    <header class="progress-window-head">
      <span class="live-dot"></span>
      <div class="progress-window-title">
        <strong>{{ task.course_name || "学习任务" }}</strong>
        <small>{{ task.account_label }} · {{ task.feature_label }}</small>
      </div>
      <button
        class="icon-button"
        :aria-label="minimized ? '展开进度小窗' : '最小化进度小窗'"
        @click="minimized = !minimized"
      >
        <ChevronDown :size="16" :class="{ up: minimized }" />
      </button>
      <button
        class="icon-button"
        aria-label="关闭进度小窗"
        @click="closed = true"
      >
        <X :size="16" />
      </button>
    </header>
    <div v-if="!minimized" class="progress-window-body">
      <p class="progress-window-activity">
        <LoaderCircle class="spin" :size="14" /><span>{{
          activityOf(task)
        }}</span>
      </p>
      <div v-if="percent !== null" class="progress-window-unit">
        <div class="progress-pair">
          <span>{{ unitLabel || "任务进度" }}</span><b>{{ percent }}%</b>
        </div>
        <div class="progress-track small">
          <i :style="{ width: percent + '%' }" />
        </div>
      </div>
      <dl class="progress-window-meta">
        <div>
          <dt>已用时</dt>
          <dd>{{ formatDuration(elapsed) }}</dd>
        </div>
        <div>
          <dt>预计剩余</dt>
          <dd>{{ eta }}</dd>
        </div>
      </dl>
      <div class="progress-window-foot">
        <span>{{ task.status === "paused" ? "已暂停" : "任务运行中" }}</span>
        <button class="text-link" @click="$emit('select', task)">
          查看详情
        </button>
      </div>
    </div>
  </aside>
</template>
