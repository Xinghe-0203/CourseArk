<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  LayoutDashboard,
  Users,
  Layers,
  BookOpen,
  SlidersHorizontal,
  Bell,
  Plus,
  RefreshCw,
  GraduationCap,
} from "lucide-vue-next";
import { state, initialize, refresh, navigate } from "./store";
import { request } from "./api";
import type { Task, View } from "./types";
import TaskList from "./components/TaskList.vue";
import TaskDrawer from "./components/TaskDrawer.vue";
import AccountsView from "./components/AccountsView.vue";
import NewTask from "./components/NewTask.vue";
import ProblemsView from "./components/ProblemsView.vue";
import BankView from "./components/BankView.vue";
import SettingsView from "./components/SettingsView.vue";
import AccountWorkspace from "./components/AccountWorkspace.vue";
import NoticeBar from "./components/NoticeBar.vue";
import OverviewDashboard from "./components/OverviewDashboard.vue";
const nav = [
  { key: "overview", title: "工作总览", icon: LayoutDashboard },
  { key: "accounts", title: "账号与课程", icon: Users },
  { key: "tasks", title: "学习任务", icon: Layers },
  { key: "bank", title: "我的题库", icon: BookOpen },
  { key: "problems", title: "问题中心", icon: Bell },
  { key: "settings", title: "偏好设置", icon: SlidersHorizontal },
] as const;
const selected = ref<Task | null>(null);
const unread = computed(() => state.unreadProblems);
const taskTab = ref("accounts");
function openNewTask() {
  state.newTaskAccount = "";
  state.newTaskFeature = "course_all";
  state.newTask = true;
}
const page = computed(() => nav.find((n) => n.key === state.view) || nav[0]);
async function selectTask(id: string) {
  try {
    selected.value =
      state.tasks.find((t) => t.id === id) ||
      (await request<Task>(`/tasks/${id}`));
  } catch (e) {
    state.error = (e as Error).message;
  }
}
let stream: EventSource | undefined,
  timer: ReturnType<typeof setInterval>,
  debounce: ReturnType<typeof setTimeout> | undefined;
function connect() {
  stream = new EventSource("/api/events/stream");
  stream.onopen = () => (state.online = true);
  stream.onerror = () => (state.online = false);
  stream.onmessage = () => {
    if (!debounce)
      debounce = setTimeout(() => {
        debounce = undefined;
        refresh();
      }, 750);
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
    if (state.toast) setTimeout(() => (state.toast = ""), 4500);
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
  clearTimeout(debounce);
  document.removeEventListener("visibilitychange", visibility);
  window.removeEventListener("hashchange", hash);
});
</script>
<template>
  <div class="shell">
    <aside class="sidebar">
      <a href="#overview" class="brand" @click="navigate('overview')"
        ><span class="brand-mark"><GraduationCap :size="25" /></span
        ><span>AutoCx<small>学习控制台</small></span></a
      >
      <div class="nav-caption">工作空间</div>
      <nav aria-label="主要导航">
        <button
          v-for="item in nav"
          :key="item.key"
          :class="{ chosen: state.view === item.key }"
          @click="navigate(item.key)"
        >
          <component :is="item.icon" :size="19" /><span>{{ item.title }}</span
          ><b v-if="item.key === 'problems' && unread" class="nav-count">{{
            unread
          }}</b>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <span :class="['dot', state.online ? 'green' : 'amber']"></span
        ><span
          >{{ state.online ? "本机服务已连接" : "正在连接服务"
          }}<small>任务在后台持续运行</small></span
        >
      </div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div class="breadcrumb">工作空间 <span>/</span> {{ page.title }}</div>
        <div class="top-actions">
          <button class="icon-button" aria-label="刷新数据" @click="refresh">
            <RefreshCw :size="17" /></button
          ><NoticeBar /><span class="local-label">本地工作空间</span>
        </div>
      </header>
      <div class="page-content">
        <div class="page-heading">
          <div>
            <div class="eyebrow">
              {{
                state.view === "overview"
                  ? "今天的学习，一目了然"
                  : "AUTO CX / WORKSPACE"
              }}
            </div>
            <h1>{{ page.title }}</h1>
            <p>
              {{
                {
                  overview:
                    "跟进正在执行的账号与课程，查看真实任务进度和处理结果。",
                  accounts: "统一管理账号、登录状态与可学习的课程。",
                  tasks: "按账号查看任务，随时暂停、继续或检查结果。",
                  bank: "检索与整理答案，导入前先检查内容。",
                  problems: "需要你处理的问题集中在这里，不会被运行日志淹没。",
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
        <BankView v-else-if="state.view === 'bank'" />
        <ProblemsView
          v-else-if="state.view === 'problems'"
          @select-task="selectTask"
        />
        <SettingsView v-else-if="state.view === 'settings'" />
        <footer>AutoCx 学习控制台 <span>·</span> 数据保存在本机</footer>
      </div>
    </main>
    <TaskDrawer v-if="selected" :task="selected" @close="selected = null" />
    <NewTask v-if="state.newTask" @close="state.newTask = false" />
    <div v-if="state.toast" class="toast" role="status">{{ state.toast }}</div>
  </div>
</template>
