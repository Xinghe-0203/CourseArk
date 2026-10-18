<script setup lang="ts">
import { computed } from "vue";
import {
  Users,
  Layers,
  Bell,
  ArrowUpRight,
  Pause,
  Square,
  ChevronRight,
} from "lucide-vue-next";
import { state, act, navigate } from "../store";
import { request } from "../api";
import { features, statuses, date } from "../format";
import { executionProfiles } from "../overview";
import type { Task } from "../types";
const emit = defineEmits<{ select: [task: Task] }>();
const profiles = computed(() => executionProfiles(state.workspaces));
const tasks = computed(() => profiles.value.flatMap((p) => p.tasks));
const totals = computed(() =>
  tasks.value.reduce(
    (s, t) => ({
      completed: s.completed + t.progress.completed,
      total: s.total + t.progress.total,
      issues: s.issues + t.progress.failed + t.progress.blocked,
    }),
    { completed: 0, total: 0, issues: 0 },
  ),
);
const known = computed(
  () =>
    tasks.value.length > 0 &&
    tasks.value.every((t) => t.progress.sealed && t.progress.total > 0),
);
const progress = computed(() =>
  known.value
    ? Math.min(
        100,
        Math.round((totals.value.completed / totals.value.total) * 100),
      )
    : null,
);
const phase = computed(() => [
  {
    name: "准备与读取",
    count: tasks.value.filter((t) =>
      ["starting", "logging_in", "loading_courses"].includes(t.status),
    ).length,
    color: "amber",
  },
  {
    name: "执行学习",
    count: tasks.value.filter((t) => t.status === "running").length,
    color: "green",
  },
  {
    name: "处理控制指令",
    count: tasks.value.filter((t) => ["pausing", "stopping"].includes(t.status))
      .length,
    color: "blue",
  },
]);
async function control(id: string, op: string) {
  await act(
    "overview-" + id + op,
    async () => {
      const result = await request<{ accepted: number }>(
        `/accounts/${id}/tasks/${op}`,
        "POST",
      );
      return result.accepted;
    },
    (n) => `已接受 ${n} 项${op === "pause" ? "暂停" : "停止"}操作`,
  );
}
</script>
<template>
  <div class="metrics overview-metrics">
    <div>
      <span>执行中的账号</span
      ><strong>{{ profiles.length }}<small>个账号</small></strong>
      <p>{{ tasks.length }} 项任务正在执行</p>
      <Users :size="21" />
    </div>
    <div>
      <span>执行中的课程</span
      ><strong
        >{{ profiles.reduce((n, p) => n + p.courses.length, 0)
        }}<small>门课程</small></strong
      >
      <p>课程任务点与独立作业</p>
      <Layers :size="21" />
    </div>
    <div>
      <span>本轮已确认</span
      ><strong
        >{{ totals.completed
        }}<small>/ {{ totals.total || "—" }} 项</small></strong
      >
      <p>
        {{
          known
            ? "平台确认的实际完成量"
            : tasks.length
              ? "正在读取完整任务范围"
              : "当前没有执行中的任务"
        }}
      </p>
    </div>
    <div :class="{ attention: state.unreadProblems }">
      <span>站内待处理通知</span
      ><strong>{{ state.unreadProblems }}<small>条</small></strong
      ><button class="text-link" @click="navigate('problems')">
        查看问题中心 <ArrowUpRight :size="14" /></button
      ><Bell :size="21" />
    </div>
  </div>
  <div v-if="tasks.length" class="execution-dashboard">
    <div class="execution-gauge">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="42" class="gauge-track" />
        <circle
          cx="50"
          cy="50"
          r="42"
          class="gauge-value"
          :stroke-dasharray="`${(progress || 0) * 2.639} 263.9`"
        />
      </svg>
      <div>
        <strong>{{ progress === null ? "读取中" : progress + "%" }}</strong
        ><small>{{
          progress === null ? "任务范围尚未完整" : "已确认任务点占比"
        }}</small>
      </div>
    </div>
    <div class="execution-phases">
      <h3>任务运行状态</h3>
      <div v-for="item in phase" :key="item.name">
        <span :class="['dot', item.color]" /><span>{{ item.name }}</span
        ><b>{{ item.count }} 项</b>
        <div class="phase-track">
          <i :style="{ width: (item.count / tasks.length) * 100 + '%' }" />
        </div>
      </div>
    </div>
    <div class="execution-summary">
      <h3>当前执行结果</h3>
      <strong>{{ totals.completed }}<small> 项已确认完成</small></strong>
      <p v-if="totals.issues" class="issue-text">
        {{ totals.issues }} 项内容需要处理，请打开课程详情核对。
      </p>
      <p v-else>各账号独立执行，视频进度、答题来源与提交结果持续更新。</p>
    </div>
  </div>
  <div class="section-heading">
    <div>
      <h2>正在执行的账号</h2>
      <p>仅显示正在执行的课程 · 卡片内滚动查看完整数据</p>
    </div>
    <button class="text-link" @click="navigate('tasks')">
      学习任务 <ArrowUpRight :size="16" />
    </button>
  </div>
  <div class="execution-grid">
    <section
      v-for="p in profiles"
      :key="p.account.id"
      class="execution-account"
    >
      <header class="workspace-account-head">
        <span class="avatar">{{
          (p.account.label || p.account.username).slice(0, 1)
        }}</span>
        <div>
          <h2>{{ p.account.label || p.account.username }}</h2>
          <small
            >{{ p.account.username }} · {{ p.courses.length }} 门课程 /
            {{ p.tasks.length }} 项任务</small
          >
        </div>
        <span class="status running">执行中</span>
      </header>
      <div
        class="execution-scroll"
        tabindex="0"
        :aria-label="(p.account.label || p.account.username) + ' 的任务数据'"
      >
        <article v-for="(c, i) in p.courses" :key="i" class="execution-course">
          <h3>{{ c.name }}</h3>
          <small v-if="c.cached" class="muted"
            >平台任务点缓存 {{ c.cached.mission_fn }} /
            {{ c.cached.mission_all }}</small
          >
          <div v-for="t in c.tasks" :key="t.id" class="execution-task">
            <div class="execution-task-heading">
              <span class="module-tag">{{
                features[t.feature] || t.feature_label
              }}</span
              ><span :class="['status', t.status]">{{
                statuses[t.status]
              }}</span
              ><button class="text-link" @click="emit('select', t)">
                详情 <ChevronRight :size="13" />
              </button>
            </div>
            <div class="live-progress">
              <div
                class="progress-track"
                :class="{ indeterminate: t.progress.percent === null }"
              >
                <i :style="{ width: (t.progress.percent || 0) + '%' }" />
              </div>
              <small
                >{{ t.progress.completed }}/{{ t.progress.total || "—" }}
                项已确认
                <b v-if="t.progress.percent !== null"
                  >{{ t.progress.percent }}%</b
                ></small
              >
            </div>
            <div class="live-details">
              <span
                >开始 {{ date(t.started_at)
                }}<template v-if="t.stats.activity">
                  · {{ (t.stats.activity as { name?: string }).name }}</template
                ></span
              >
              <span
                >答题 {{ t.stats.questions || 0 }} · 缓存命中
                {{ t.stats.cache_hits || 0 }} · AI
                {{ t.stats.llm_calls || 0 }}</span
              ><span
                >提交接受 {{ t.stats.submit_ok || 0 }} · 随机答案
                {{ t.stats.random_answers || 0 }}</span
              >
            </div>
            <p v-if="t.progress.failed + t.progress.blocked" class="issue-text">
              {{ t.progress.failed + t.progress.blocked }}
              项内容待处理，打开详情查看原因。
            </p>
            <ul v-if="t.progress.active.length" class="media-live">
              <li v-for="m in t.progress.active" :key="m.id">
                <span>{{
                  m.kind === "video"
                    ? "视频"
                    : m.kind === "audio"
                      ? "音频"
                      : m.kind === "work"
                        ? "测验"
                        : "任务点"
                }}</span
                ><b :title="m.name">{{ m.name }}</b
                ><small>{{
                  m.total
                    ? `${m.current || 0} / ${m.total}${["video", "audio"].includes(m.kind) ? " 秒" : ""}`
                    : "处理中"
                }}</small>
              </li>
            </ul>
            <p v-else class="muted execution-stage">
              {{
                t.stage === "login"
                  ? "正在验证账号登录"
                  : t.stage === "course"
                    ? "正在读取课程任务"
                    : "正在处理课程内容"
              }}
            </p>
          </div>
        </article>
      </div>
      <footer class="account-controls">
        <button
          :disabled="state.busy.has('overview-' + p.account.id + 'pause')"
          @click="control(p.account.id, 'pause')"
        >
          <Pause :size="14" />暂停账号</button
        ><button
          :disabled="state.busy.has('overview-' + p.account.id + 'stop')"
          @click="control(p.account.id, 'stop')"
        >
          <Square :size="14" />停止账号</button
        ><small>实时任务数据</small>
      </footer>
    </section>
  </div>
  <div v-if="!profiles.length" class="empty">
    <Layers :size="32" />
    <h3>当前没有正在执行的任务</h3>
    <p>创建学习任务后，执行中的账号与课程会显示在这里。</p>
    <button @click="navigate('tasks')">查看学习任务</button>
  </div>
</template>
