<script setup lang="ts">
// T9.5 告警小窗：任务异常/中断事件，支持直接继续执行（复用 store.resumeTask）。
import { computed } from "vue";
import { X } from "lucide-vue-next";
import { alertFeed, dismissAlert } from "../windows/alerts";
import {
  closeWindow,
  focusWindow,
  toggleMinimized,
  windows,
} from "../windows/manager";
import { resumeTask, state } from "../store";
import { date } from "../format";
const win = computed(() => windows.map.alerts);
const items = alertFeed();
const resuming = computed(() => new Set([...state.busy]));
</script>
<template>
  <aside
    v-if="win?.open"
    class="float-window alert-window"
    :class="{ minimized: win.minimized }"
    role="alert"
    aria-label="任务告警小窗"
    @mousedown="focusWindow('alerts')"
  >
    <header class="float-window-head">
      <span class="live-dot"></span>
      <strong>任务告警</strong>
      <button
        class="icon-button"
        :aria-label="win.minimized ? '展开告警小窗' : '最小化告警小窗'"
        @click="toggleMinimized('alerts')"
      >
        {{ win.minimized ? "展开" : "最小化" }}
      </button>
      <button class="icon-button" aria-label="关闭告警小窗" @click="closeWindow('alerts')">
        <X :size="16" />
      </button>
    </header>
    <div v-if="!win.minimized" class="float-window-body">
      <p v-if="!items.length" class="empty">暂无告警。任务失败或中断时会出现在这里。</p>
      <ul v-else class="alert-list">
        <li v-for="item in items" :key="item.key">
          <b>{{ item.title }}</b>
          <p>{{ item.message }}</p>
          <div class="alert-actions">
            <time>{{ date(item.ts) }}</time>
            <button
              class="button small"
              :disabled="resuming.has(`resume-${item.taskId}`)"
              @click="resumeTask({ id: item.taskId } as never)"
            >
              继续执行
            </button>
            <button class="text-link" @click="dismissAlert(item.key)">忽略</button>
          </div>
        </li>
      </ul>
    </div>
  </aside>
</template>
