<script setup lang="ts">
// 学习任务页：左侧账号工作台 / 右侧任务记录。
// tab 由路由 query 驱动，刷新或从详情返回时不会跳回第一个 tab。
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { state } from "../store";
import type { Task } from "../types";
import AccountWorkspace from "../components/AccountWorkspace.vue";
import TaskList from "../components/TaskList.vue";

const emit = defineEmits<{ select: [task: Task] }>();
const route = useRoute();
const router = useRouter();
const tabs = [
  { key: "accounts", label: "按账号展开" },
  { key: "history", label: "任务记录与历史" },
] as const;
type TabKey = (typeof tabs)[number]["key"];

const taskTab = computed<TabKey>(() =>
  route.query.tab === "history" ? "history" : "accounts",
);

function selectTab(key: TabKey) {
  void router.replace({
    name: "tasks",
    query: key === "accounts" ? {} : { tab: key },
  });
}
</script>

<template>
  <div>
    <div class="tabs" role="tablist" aria-label="学习任务视图">
      <button
        v-for="item in tabs"
        :key="item.key"
        role="tab"
        :aria-selected="taskTab === item.key"
        :class="{ selected: taskTab === item.key }"
        @click="selectTab(item.key)"
      >
        {{ item.label }}
      </button>
    </div>
    <AccountWorkspace
      v-if="taskTab === 'accounts'"
      @select="emit('select', $event)"
    />
    <!-- 历史 tab 默认看全部状态；此前用 TaskList 的默认 "active"，
         切过来只看到当前任务，与「历史」名不符。 -->
    <TaskList
      v-else
      :tasks="state.tasks"
      filters
      initial-filter="all"
      @select="emit('select', $event)"
    />
  </div>
</template>
