<script setup lang="ts">
// T13：学习任务页（tabs + 按账号展开/任务历史）从 App.vue 拆出，
// 供 RouterView 挂载；select 事件继续上抛给 App 的任务抽屉。
import { ref } from "vue";
import { state } from "../store";
import type { Task } from "../types";
import AccountWorkspace from "../components/AccountWorkspace.vue";
import TaskList from "../components/TaskList.vue";
const emit = defineEmits<{ select: [task: Task] }>();
const taskTab = ref("accounts");
</script>
<template>
  <div>
    <div class="tabs">
      <button
        :class="{ selected: taskTab === 'accounts' }"
        @click="taskTab = 'accounts'"
      >
        按账号展开</button
      ><button
        :class="{ selected: taskTab === 'history' }"
        @click="taskTab = 'history'"
      >
        任务记录与历史
      </button>
    </div>
    <AccountWorkspace
      v-if="taskTab === 'accounts'"
      @select="emit('select', $event)"
    /><TaskList
      v-else
      :tasks="state.tasks"
      filters
      @select="emit('select', $event)"
    />
  </div>
</template>
