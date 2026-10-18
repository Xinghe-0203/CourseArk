<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from "vue";
import {
  Search,
  ChevronRight,
  Pause,
  Play,
  RotateCcw,
  Square,
  Layers,
} from "lucide-vue-next";
import type { Task } from "../types";
import { state, act } from "../store";
import { request } from "../api";
import { runningSummary } from "../live";
import {
  groupTasks,
  statuses,
  features,
  active,
  terminal,
  percent,
  date,
} from "../format";
const props = defineProps<{ tasks: Task[]; filters?: boolean }>();
defineEmits<{ select: [task: Task] }>();
const query = ref(""),
  filter = ref("active"),
  account = ref("");
const fetched = ref<Task[] | null>(null),
  count = ref(0),
  offset = ref(0);
let generation = 0,
  debounce: ReturnType<typeof setTimeout>;
async function load() {
  if (!props.filters) return;
  const current = ++generation;
  const status =
    filter.value === "all"
      ? ""
      : filter.value === "active"
        ? "pending,starting,logging_in,loading_courses,running,pausing,paused,stopping"
        : filter.value;
  try {
    const data = await request<{ items: Task[]; total: number }>(
      `/tasks?q=${encodeURIComponent(query.value)}&status=${status}&account_id=${account.value}&limit=100&offset=${offset.value}`,
    );
    if (current === generation) {
      if (offset.value && offset.value >= data.total) {
        offset.value = Math.max(0, Math.floor((data.total - 1) / 100) * 100);
        return;
      }
      fetched.value = data.items.map((task) =>
        state.liveById[task.id]
          ? { ...task, live: state.liveById[task.id] }
          : task,
      );
      count.value = data.total;
    }
  } catch (e) {
    state.error = (e as Error).message;
  }
}
watch([query, filter, account], () => {
  offset.value = 0;
  clearTimeout(debounce);
  debounce = setTimeout(load, 200);
});
watch(offset, load);
watch(() => props.tasks, load, { immediate: true });
onUnmounted(() => {
  generation++;
  clearTimeout(debounce);
});
const visible = computed(() =>
  (props.filters ? fetched.value || [] : props.tasks).map((task) =>
    state.liveById[task.id] ? { ...task, live: state.liveById[task.id] } : task,
  ),
);
const groups = computed(() => groupTasks(visible.value));
function liveLine(task: Task) {
  const summary = runningSummary(task);
  if (!summary) return "";
  return `${summary.activity} · 预计剩余 ${summary.eta}`;
}
function command(task: Task, op: string) {
  act(
    task.id,
    () => request(`/tasks/${task.id}/${op}`, "POST"),
    op === "retry" ? "已加入重试队列" : "任务指令已发送",
  );
}
</script>
<template>
  <div v-if="filters" class="filterbar">
    <label class="search"
      ><Search :size="17" /><input
        v-model="query"
        placeholder="搜索课程或账号"
        aria-label="搜索任务" /></label
    ><select v-model="account" aria-label="按账号筛选">
      <option value="">所有账号</option>
      <option v-for="a in state.accounts" :value="a.id">
        {{ a.label || a.username }}
      </option></select
    ><select v-model="filter" aria-label="任务状态">
      <option value="active">当前任务</option>
      <option value="all">全部与历史</option>
      <option value="succeeded">已完成</option>
      <option value="failed">需处理</option>
      <option value="paused">已暂停</option>
      <option value="stopped">已停止</option>
    </select>
  </div>
  <div class="task-groups">
    <section v-for="group in groups" :key="group.id" class="account-group">
      <div class="group-heading">
        <span class="avatar">{{ group.label.slice(0, 1) }}</span>
        <div>
          <h2>{{ group.label }}</h2>
          <small
            >{{ group.tasks.length }} 项任务 ·
            {{ group.tasks.filter(active).length }} 项进行中</small
          >
        </div>
        <span class="group-line" />
      </div>
      <div class="task-table">
        <div class="task-table-head">
          <span>课程与任务</span><span>实际进度</span><span>状态</span
          ><span>操作</span>
        </div>
        <article v-for="task in group.tasks" :key="task.id" class="task-row">
          <button class="task-title" @click="$emit('select', task)">
            <span class="course-icon"><Layers :size="18" /></span
            ><span
              ><b>{{ task.course_name || "未命名课程" }}</b
              ><small
                >{{ features[task.feature] }} ·
                {{ date(task.created_at) }}</small
              ></span
            >
          </button>
          <div class="task-progress">
            <div class="progress-label">
              <span v-if="task.progress?.total"
                >已完成 {{ task.progress.completed }} /
                {{ task.progress.total }} 项</span
              ><span v-else>{{
                task.status === "succeeded"
                  ? "执行已结束"
                  : task.status === "pending"
                    ? "等待调度"
                    : "正在读取任务范围"
              }}</span
              ><strong v-if="percent(task) !== null"
                >{{ percent(task) }}%</strong
              >
            </div>
            <div
              :class="[
                'progress-track',
                { indeterminate: percent(task) === null && active(task) },
              ]"
              role="progressbar"
              :aria-valuenow="percent(task) ?? undefined"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-label="task.course_name + '完成进度'"
            >
              <i :style="{ width: (percent(task) ?? 0) + '%' }" />
            </div>
            <small v-if="liveLine(task)" class="task-live-summary">{{
              liveLine(task)
            }}</small>
            <small v-else-if="task.progress?.active?.length">{{
              task.progress.active[0]?.name || "处理中"
            }}</small
            ><small v-else-if="task.progress?.failed"
              >{{ task.progress.failed }} 项未完成，请查看详情</small
            >
          </div>
          <span :class="['status', task.status]"
            ><i />{{ statuses[task.status] || task.status }}</span
          >
          <div class="row-actions">
            <button
              v-if="
                [
                  'running',
                  'starting',
                  'logging_in',
                  'loading_courses',
                ].includes(task.status)
              "
              aria-label="暂停任务"
              class="icon-button"
              :disabled="state.busy.has(task.id)"
              @click="command(task, 'pause')"
            >
              <Pause :size="16" /></button
            ><button
              v-if="task.status === 'paused'"
              class="icon-button"
              aria-label="继续任务"
              :disabled="state.busy.has(task.id)"
              @click="command(task, 'resume')"
            >
              <Play :size="16" /></button
            ><button
              v-if="!terminal(task)"
              class="icon-button"
              aria-label="停止任务"
              :disabled="state.busy.has(task.id)"
              @click="command(task, 'stop')"
            >
              <Square :size="15" /></button
            ><button
              v-if="['failed', 'stopped', 'interrupted'].includes(task.status)"
              class="icon-button"
              aria-label="重试任务"
              :disabled="state.busy.has(task.id)"
              @click="command(task, 'retry')"
            >
              <RotateCcw :size="16" /></button
            ><button
              class="icon-button"
              aria-label="任务详情"
              @click="$emit('select', task)"
            >
              <ChevronRight :size="17" />
            </button>
          </div>
        </article>
      </div>
    </section>
    <div v-if="!groups.length" class="empty">
      <Layers :size="30" />
      <h3>暂无{{ filters ? "符合条件的" : "进行中的" }}任务</h3>
      <p>创建任务后，会按账号显示在这里。</p>
    </div>
    <div v-if="filters && count > 100" class="pagination">
      <button
        :disabled="offset === 0"
        @click="offset = Math.max(0, offset - 100)"
      >
        上一页
      </button>
      <span
        >{{ offset + 1 }}—{{ Math.min(offset + 100, count) }} /
        {{ count }}</span
      >
      <button :disabled="offset + 100 >= count" @click="offset += 100">
        下一页
      </button>
    </div>
  </div>
</template>
