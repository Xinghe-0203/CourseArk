<script setup lang="ts">
// T14 迷你监控子窗（Electron 无框小窗 loadURL(#/mini)）的紧凑视图。
// 网页端直接访问 #/mini 时也可用：同源取数，展示当前任务与进度摘要。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { state, refresh } from "../store";
import { activityOf, elapsedSeconds, formatDuration, unitPercent, unitText } from "../live";
import { closeDesktopMini } from "../desktop";

const now = ref(Date.now());
let timer: ReturnType<typeof setInterval>;
const running = computed(() =>
  state.tasks.filter((task) => task.status === "running" || task.status === "paused"),
);
const current = computed(() => running.value[0]);
const liveUnit = computed(() => current.value?.live?.unit || null);
const percent = computed(() => unitPercent(liveUnit.value));
const elapsed = computed(() =>
  current.value
    ? formatDuration(elapsedSeconds(current.value, now.value / 1000))
    : "—",
);

onMounted(() => {
  refresh();
  timer = setInterval(() => {
    now.value = Date.now();
    refresh();
  }, 2500);
});
onUnmounted(() => clearInterval(timer));
</script>
<template>
  <div class="mini-view">
    <header class="mini-drag">
      <span class="mini-dot" />
      <span class="mini-title">课舟监控</span>
      <button
        class="mini-close"
        aria-label="关闭迷你监控"
        title="关闭迷你监控"
        @click="closeDesktopMini()"
      >
        ×
      </button>
    </header>
    <div class="mini-body">
      <template v-if="current">
        <p class="mini-course">{{ current.course_name }}</p>
        <p class="mini-activity">{{ activityOf(current) || "准备中" }}</p>
        <div v-if="percent !== null" class="mini-bar">
          <div class="progress-track small">
            <i :style="{ width: percent + '%' }" />
          </div>
        </div>
        <p class="mini-progress">
          <span v-if="unitText(liveUnit)" class="num">{{ unitText(liveUnit) }}</span>
          <span v-if="percent !== null" class="num">{{ percent }}%</span>
          <span class="num">已用时 {{ elapsed }}</span>
        </p>
      </template>
      <p v-else class="mini-idle">暂无运行中的任务</p>
    </div>
    <p class="mini-meta">
      {{ running.length ? `${running.length} 项进行中` : "课舟监控" }}
    </p>
  </div>
</template>

<style scoped>
.mini-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--surface);
  border: 1px solid var(--line2);
  border-radius: var(--r3);
  overflow: hidden;
  font-family: var(--font-body);
}

.mini-drag {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  -webkit-app-region: drag;
  user-select: none;
}

.mini-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok);
  animation: pulse 2s ease-in-out infinite;
}

.mini-title {
  flex: 1;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--mute);
}

.mini-close {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: var(--r1);
  background: transparent;
  font-size: 13px;
  line-height: 1;
  color: var(--faint);
  -webkit-app-region: no-drag;
}

.mini-close:hover:not(:disabled) {
  background: var(--surface3);
  color: var(--danger);
  border-color: transparent;
}

.mini-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex: 1;
  padding: 8px 10px;
}

.mini-course {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-activity {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.45;
  color: var(--mute);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.mini-bar {
  margin-top: 1px;
}

.mini-progress {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  font-size: 10px;
  color: var(--faint);
}

.mini-idle {
  margin: 0;
  padding: 10px 0;
  font-size: 11px;
  color: var(--faint);
}

.mini-meta {
  margin: 0;
  padding: 4px 10px;
  border-top: 1px solid var(--line);
  background: var(--surface2);
  font-size: 9.5px;
  color: var(--faint);
}
</style>