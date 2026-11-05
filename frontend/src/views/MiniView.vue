<script setup lang="ts">
// T14 迷你监控子窗（Electron 无框小窗 loadURL(#/mini)）的紧凑视图。
// 网页端直接访问 #/mini 时也可用：同源取数，展示当前任务与进度摘要。
import { computed, onMounted, onUnmounted, ref } from "vue";
import { state, refresh } from "../store";
import { activityOf, formatDuration, unitPercent, unitText } from "../live";

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
    ? formatDuration(
        Math.floor((now.value - (current.value.started_at || now.value)) / 1000),
      )
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
    <template v-if="current">
      <p class="mini-course">{{ current.course_name }}</p>
      <p class="mini-activity">{{ activityOf(current) || "准备中" }}</p>
      <p class="mini-progress">
        <template v-if="unitText(liveUnit)">{{ unitText(liveUnit) }} · </template
        ><template v-if="percent !== null">{{ percent }}% · </template>已用时
        {{ elapsed }}
      </p>
    </template>
    <p v-else class="mini-idle">暂无运行中的任务</p>
    <p class="mini-meta">
      {{ running.length ? `${running.length} 项进行中` : "课舟监控" }}
    </p>
  </div>
</template>
