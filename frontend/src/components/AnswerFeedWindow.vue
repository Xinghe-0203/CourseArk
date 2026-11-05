<script setup lang="ts">
// T9.4 逐题作答小窗（页面内浮层；T14 桌面桥就绪后升级真子窗）。
import { computed } from "vue";
import { X } from "lucide-vue-next";
import { answerFeed, openAnswerTask } from "../windows/answers";
import {
  closeWindow,
  focusWindow,
  toggleMinimized,
  windows,
} from "../windows/manager";
import { date } from "../format";
import type { Task } from "../types";
const emit = defineEmits<{ select: [task: Task] }>();
const win = computed(() => windows.map.answers);
const items = answerFeed();
const statusLabel: Record<string, string> = {
  answered: "已作答",
  skipped: "已跳过",
  unreadable: "未识别",
};
function rowClass(status: string) {
  return status === "answered"
    ? "is-ok"
    : status === "skipped"
      ? "is-warn"
      : "is-err";
}
function pick(item: (typeof items.value)[number]) {
  const task = openAnswerTask(item);
  if (task) emit("select", task);
}
</script>
<template>
  <aside
    v-if="win?.open"
    class="float-window answer-feed-window"
    :class="{ minimized: win.minimized }"
    role="status"
    aria-label="逐题作答小窗"
    @mousedown="focusWindow('answers')"
  >
    <header class="float-window-head">
      <span class="live-dot"></span>
      <strong>逐题作答</strong>
      <button
        class="icon-button"
        :aria-label="win.minimized ? '展开逐题小窗' : '最小化逐题小窗'"
        @click="toggleMinimized('answers')"
      >
        {{ win.minimized ? "展开" : "最小化" }}
      </button>
      <button class="icon-button" aria-label="关闭逐题小窗" @click="closeWindow('answers')">
        <X :size="16" />
      </button>
    </header>
    <div v-if="!win.minimized" class="float-window-body">
      <p v-if="!items.length" class="empty">暂无逐题动态。运行中的答题任务会在这里实时滚动。</p>
      <ul v-else class="answer-feed-list">
        <li v-for="item in items" :key="item.key">
          <button class="recent-row" @click="pick(item)">
            <b>{{ item.courseName }}</b>
            <small>{{ item.question || "（无题干）" }}</small>
            <span :class="['pill', rowClass(item.status)]">{{
              statusLabel[item.status] || item.status
            }}</span>
            <small class="feed-answer">{{ item.answer }}</small>
            <time>{{ date(item.ts) }}</time>
          </button>
        </li>
      </ul>
    </div>
  </aside>
</template>
