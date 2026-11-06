<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ChevronDown, LoaderCircle, PictureInPicture2, X } from "lucide-vue-next";
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
import { isDesktop, openDesktopMini } from "../desktop";
import type { Task } from "../types";
defineEmits<{ select: [task: Task] }>();
const POLL_MS = 2000;
const closed = ref(false);
// 默认最小化：只留一条标题栏贴在右下角，避免长期压住页面卡片。
const minimized = ref(true);
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
      // 这一轮任务结束后，下一轮运行重新显示小窗（默认仍是最小化的贴边状态）。
      closed.value = false;
      minimized.value = true;
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
        v-if="isDesktop()"
        class="icon-button"
        aria-label="浮出迷你监控"
        title="浮出独立迷你监控小窗"
        @click="openDesktopMini()"
      >
        <PictureInPicture2 :size="13" />
      </button>
      <button
        class="icon-button"
        :aria-label="minimized ? '展开进度小窗' : '最小化进度小窗'"
        :title="minimized ? '展开进度小窗' : '最小化进度小窗'"
        @click="minimized = !minimized"
      >
        <ChevronDown :size="13" :class="{ up: minimized }" />
      </button>
      <button
        class="icon-button"
        aria-label="关闭进度小窗"
        title="关闭进度小窗"
        @click="closed = true"
      >
        <X :size="13" />
      </button>
    </header>
    <div v-if="!minimized" class="progress-window-body">
      <p class="progress-window-activity">
        <LoaderCircle class="spin" :size="12" /><span>{{
          activityOf(task)
        }}</span>
      </p>
      <div v-if="percent !== null" class="progress-window-unit">
        <div class="progress-pair">
          <span>{{ unitLabel || "任务进度" }}</span
          ><b class="num">{{ percent }}%</b>
        </div>
        <div class="progress-track small">
          <i :style="{ width: percent + '%' }" />
        </div>
      </div>
      <dl class="progress-window-meta">
        <div>
          <dt>已用时</dt>
          <dd class="num">{{ formatDuration(elapsed) }}</dd>
        </div>
        <div>
          <dt>预计剩余</dt>
          <dd class="num">{{ eta }}</dd>
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

<style scoped>
.progress-window {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 40;
  width: 300px;
  border: 1px solid var(--line2);
  border-radius: var(--r3);
  background: var(--surface);
  box-shadow: 0 6px 20px rgba(21, 25, 31, 0.14);
  overflow: hidden;
}

.progress-window-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.progress-window.minimized .progress-window-head {
  border-bottom: 0;
}

.progress-window-title {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.progress-window-title strong {
  font-size: 12.5px;
  line-height: 1.35;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-window-title small {
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-window-head .icon-button {
  width: 24px;
  height: 24px;
}

.progress-window-head .icon-button.up :deep(svg) {
  transform: rotate(180deg);
}

.progress-window-head .icon-button svg.up {
  transform: rotate(180deg);
}

.progress-window-body {
  display: grid;
  gap: 12px;
  padding: 12px;
}

.progress-window-activity {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 11.5px;
  color: var(--ink2);
  line-height: 1.55;
}

.progress-window-activity span {
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.progress-window-unit {
  display: grid;
  gap: 6px;
}

.progress-window-unit .progress-pair {
  font-size: 11px;
  color: var(--mute);
}

.progress-window-unit .progress-pair b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.progress-window-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 3px;
  margin: 0;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--line);
  overflow: hidden;
}

.progress-window-meta > div {
  display: grid;
  gap: 2px;
  padding: 7px 9px;
  background: var(--surface);
}

.progress-window-meta dt {
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--faint);
}

.progress-window-meta dd {
  margin: 0;
  font-size: 13px;
  line-height: 1.3;
  color: var(--ink);
}

.progress-window-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10.5px;
  color: var(--faint);
}

.progress-window-foot .text-link {
  font-size: 11px;
}

@media (max-width: 760px) {
  .progress-window {
    right: 8px;
    bottom: 8px;
    width: calc(100vw - 16px);
  }
}
</style>