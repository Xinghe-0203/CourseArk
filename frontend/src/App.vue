<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  LayoutDashboard,
  Users,
  Layers,
  Database,
  SlidersHorizontal,
  Plus,
  RefreshCw,
  GraduationCap,
  CheckCircle2,
} from "lucide-vue-next";
import { state, initialize, refresh, navigate } from "./store";
import { workspaceStats } from "./stats";
import type { Task, View } from "./types";
import TaskList from "./components/TaskList.vue";
import TaskDrawer from "./components/TaskDrawer.vue";
import AccountsView from "./components/AccountsView.vue";
import NewTask from "./components/NewTask.vue";
import BankView from "./components/BankView.vue";
import SettingsView from "./components/SettingsView.vue";
import AccountWorkspace from "./components/AccountWorkspace.vue";
import OverviewDashboard from "./components/OverviewDashboard.vue";
import CompletedView from "./components/CompletedView.vue";
import ProgressWindow from "./components/ProgressWindow.vue";
const nav = [
  { key: "overview", title: "工作总览", icon: LayoutDashboard },
  { key: "tasks", title: "学习任务", icon: Layers },
  { key: "accounts", title: "账号与课程", icon: Users },
  { key: "completed", title: "已完成", icon: CheckCircle2 },
  { key: "bank", title: "答题缓存", icon: Database },
  { key: "settings", title: "偏好设置", icon: SlidersHorizontal },
] as const;
// 侧栏按职责分组：工作台只看当前状态，档案放历史与资产，系统放配置。
const groups = [
  { caption: "工作台", keys: ["overview", "tasks"] },
  { caption: "档案", keys: ["accounts", "completed", "bank"] },
  { caption: "系统", keys: ["settings"] },
] as const;
const sections = groups.map((group) => ({
  caption: group.caption,
  items: nav.filter((item) => (group.keys as readonly string[]).includes(item.key)),
}));
const selected = ref<Task | null>(null);
const taskTab = ref("accounts");
function openNewTask() {
  state.newTaskAccount = "";
  state.newTaskFeature = "course_all";
  state.newTask = true;
}
const page = computed(() => nav.find((n) => n.key === state.view) || nav[0]);
// 顶栏统计与总览、学习任务共用同一套口径，避免同批账号出现两种课程数。
const totals = computed(() => workspaceStats(state.workspaces, state.tasks));
const port = computed(() => Number(state.settings.server?.port) || 8848);
let stream: EventSource | undefined,
  timer: ReturnType<typeof setInterval>,
  toastTimer: ReturnType<typeof setTimeout> | undefined,
  debounce: ReturnType<typeof setTimeout> | undefined;
function connect() {
  stream = new EventSource("/api/events/stream");
  stream.onopen = () => (state.online = true);
  stream.onerror = () => (state.online = false);
  stream.onmessage = (event) => {
    state.eventRevision += 1;
    let name = "";
    try {
      name = JSON.parse(event.data).event || "";
    } catch {
      name = "";
    }
    // 课程同步结束立即刷新课程与任务点，其余事件沿用 500ms 合并刷新。
    if (name === "sync_completed" || name === "sync_failed") {
      refresh();
      return;
    }
    if (!debounce)
      debounce = setTimeout(() => {
        debounce = undefined;
        refresh();
      }, 500);
  };
}
function visibility() {
  if (document.hidden) {
    stream?.close();
    stream = undefined;
  } else {
    refresh();
    connect();
  }
}
function hash() {
  const view = location.hash.slice(1);
  if (nav.some((n) => n.key === view)) state.view = view as View;
}
watch(
  () => state.toast,
  () => {
    // 每次提示更新都重置计时器：否则上一条提示遗留的定时器会提前清掉新提示。
    clearTimeout(toastTimer);
    if (state.toast) toastTimer = setTimeout(() => (state.toast = ""), 4500);
  },
);
onMounted(() => {
  hash();
  initialize();
  connect();
  timer = setInterval(() => {
    if (!document.hidden) refresh();
  }, 10000);
  document.addEventListener("visibilitychange", visibility);
  window.addEventListener("hashchange", hash);
});
onUnmounted(() => {
  stream?.close();
  clearInterval(timer);
  clearTimeout(toastTimer);
  clearTimeout(debounce);
  document.removeEventListener("visibilitychange", visibility);
  window.removeEventListener("hashchange", hash);
});
</script>
<template>
  <div class="shell">
    <aside class="sidebar">
      <a href="#overview" class="brand" @click="navigate('overview')"
        ><span class="brand-mark"><GraduationCap :size="24" /></span
        ><span>课舟<small>超星多账号学习台</small></span></a
      >
      <nav aria-label="主要导航">
        <div v-for="section in sections" :key="section.caption" class="nav-group">
          <div class="nav-caption">{{ section.caption }}</div>
          <button
            v-for="item in section.items"
            :key="item.key"
            :class="{ chosen: state.view === item.key }"
            :aria-current="state.view === item.key ? 'page' : undefined"
            @click="navigate(item.key)"
          >
            <component :is="item.icon" :size="18" /><span>{{ item.title }}</span>
          </button>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="engine" :class="state.online ? 'is-ok' : 'is-warn'">
          <span class="engine-dot"></span>
          <div class="engine-copy">
            <b>{{ state.online ? "后台服务运行中" : "正在连接后台服务" }}</b>
            <small
              >{{ totals.running }} 项运行中 · {{ totals.paused }} 项暂停 · 端口
              {{ port }}</small
            >
          </div>
        </div>
      </div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div class="breadcrumb">工作空间 <span>/</span> {{ page.title }}</div>
        <div class="top-actions">
          <div class="top-stats">
            <div class="stat-item" title="已添加的账号数量">
              <b>{{ totals.accounts }}</b><span>账号</span>
            </div>
            <div class="stat-item" title="已同步课程总数（含停用账号）">
              <b>{{ totals.courses }}</b><span>课程</span>
            </div>
            <div class="stat-item" title="正在执行的任务数量">
              <b>{{ totals.running }}</b><span>运行中</span>
            </div>
          </div>
          <button class="icon-button" aria-label="刷新数据" @click="refresh">
            <RefreshCw :size="17" />
          </button>
        </div>
      </header>
      <div class="page-content">
        <div class="page-heading">
          <div>
            <h1>{{ page.title }}</h1>
            <p>
              {{
                {
                  overview: "当前状态摘要与正在运行的任务；账号、课程与任务分别在专页管理。",
                  tasks: "按账号管理课程与任务，随时暂停、继续或查看执行结果。",
                  accounts: "管理账号与登录状态、同步课程；课程详情在弹窗中查看。",
                  completed: "汇总每次跑完的任务：课程、时间、耗时、逐题明细与结果说明。",
                  bank: "查看、导入与清理本机记住的答案，减少重复调用 AI。",
                  settings: "设置默认学习方式、账号并发数量与 AI 服务。",
                }[state.view]
              }}
            </p>
          </div>
          <button
            v-if="['overview', 'tasks'].includes(state.view)"
            class="primary"
            @click="openNewTask"
          >
            <Plus :size="17" />新建学习任务
          </button>
        </div>
        <div v-if="state.error" class="alert error" role="alert">
          <span>{{ state.error }}</span
          ><button @click="state.error = ''">关闭</button>
        </div>
        <div v-if="state.loading" class="empty">正在读取工作空间…</div>
        <template v-else-if="state.view === 'overview'">
          <OverviewDashboard @select="selected = $event" />
        </template>
        <AccountsView v-else-if="state.view === 'accounts'" />
        <div v-else-if="state.view === 'tasks'">
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
            @select="selected = $event"
          /><TaskList
            v-else
            :tasks="state.tasks"
            filters
            @select="selected = $event"
          />
        </div>
        <CompletedView
          v-else-if="state.view === 'completed'"
          @select="selected = $event"
        />
        <BankView v-else-if="state.view === 'bank'" />
        <SettingsView v-else-if="state.view === 'settings'" />
        <footer>课舟 CourseArk <span>·</span> 数据保存在本机</footer>
      </div>
    </main>
    <TaskDrawer v-if="selected" :task="selected" @close="selected = null" />
    <NewTask v-if="state.newTask" @close="state.newTask = false" />
    <ProgressWindow @select="selected = $event" />
    <div v-if="state.toast" class="toast" role="status">{{ state.toast }}</div>
  </div>
</template>
