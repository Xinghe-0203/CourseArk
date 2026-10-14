<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import type { Task, TaskEvent } from "../types";
import { request } from "../api";
import { categories, statuses, date } from "../format";
import ModalShell from "./ModalShell.vue";
const props = defineProps<{ task: Task }>();
defineEmits<{ close: [] }>();
const detail = ref(props.task),
  events = ref<TaskEvent[]>([]),
  tab = ref("activity"),
  category = ref(""),
  level = ref(""),
  error = ref(""),
  follow = ref(false),
  log = ref<HTMLElement>();
let timer: ReturnType<typeof setInterval>;
let closed = false;
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
async function load() {
  try {
    const value = await request<Task>(`/tasks/${props.task.id}`);
    if (closed) return;
    detail.value = value;
    events.value = value.events || [];
    if (follow.value)
      setTimeout(() => log.value?.scrollTo({ top: log.value.scrollHeight }), 0);
  } catch (e) {
    error.value = (e as Error).message;
  }
}
onMounted(() => {
  load();
  timer = setInterval(load, 4000);
});
onUnmounted(() => {
  closed = true;
  clearInterval(timer);
});
</script>
<template>
  <ModalShell :title="task.course_name" wide @close="$emit('close')"
    ><div class="detail-summary">
      <span :class="['status', detail.status]">{{
        statuses[detail.status]
      }}</span
      ><span>{{ detail.account_label }} · {{ detail.feature_label }}</span
      ><span class="muted">{{ date(detail.started_at) }}</span>
    </div>
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
        <strong>{{ detail.stats.questions || 0 }}</strong
        ><small>处理题目</small>
      </div>
      <div>
        <strong>{{ detail.stats.submit_ok || 0 }}</strong
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
      <button
        :class="{ selected: tab === 'activity' }"
        @click="tab = 'activity'"
      >
        学习动态</button
      ><button :class="{ selected: tab === 'logs' }" @click="tab = 'logs'">
        诊断日志</button
      ><button :class="{ selected: tab === 'params' }" @click="tab = 'params'">
        任务参数
      </button>
    </div>
    <template v-if="tab !== 'params'"
      ><div class="filterbar compact">
        <select v-model="category" aria-label="日志分类">
          <option value="">所有分类</option>
          <option v-for="(label, key) in categories" :value="key">
            {{ label }}
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
              categories[e.presentation?.category || e.stage] || "任务运行"
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
