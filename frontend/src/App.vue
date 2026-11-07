<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, RouterView } from "vue-router";
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
  ChartColumn,
  TriangleAlert,
} from "lucide-vue-next";
import { state, initialize, refresh, navigate } from "./store";
import { engineTotals, overviewCounts } from "./overview";
import { pushAnswerEvent } from "./windows/answers";
import { pushAlertEvent } from "./windows/alerts";
import { closeWindow, openWindow, windows } from "./windows/manager";
import { onDesktopVerifyCaptured } from "./desktop";
import { request } from "./api";
import type { Task } from "./types";
import TaskDrawer from "./components/TaskDrawer.vue";
import NewTask from "./components/NewTask.vue";
import ProgressWindow from "./components/ProgressWindow.vue";
import AnswerFeedWindow from "./components/AnswerFeedWindow.vue";
import AlertWindow from "./components/AlertWindow.vue";
const route = useRoute();
const nav = [
  { key: "overview", title: "工作总览", icon: LayoutDashboard },
  { key: "progress", title: "课程进度", icon: ChartColumn },
  { key: "tasks", title: "学习任务", icon: Layers },
  { key: "accounts", title: "账号与课程", icon: Users },
  { key: "completed", title: "已完成", icon: CheckCircle2 },
  { key: "bank", title: "答题缓存", icon: Database },
  { key: "settings", title: "偏好设置", icon: SlidersHorizontal },
] as const;
// 侧栏按职责分组：工作台只看当前状态，档案放历史与资产，系统放配置。
const groups = [
  { caption: "工作台", keys: ["overview", "progress", "tasks"] },
  { caption: "档案", keys: ["accounts", "completed", "bank"] },
  { caption: "系统", keys: ["settings"] },
] as const;
const sections = groups.map((group) => ({
  caption: group.caption,
  items: nav.filter((item) => (group.keys as readonly string[]).includes(item.key)),
}));
// #/mini 是 Electron 迷你监控子窗的独立视图，不套用工作台外壳。
const isMini = computed(() => route.name === "mini");
const selected = ref<Task | null>(null);
// 只接受带 id 的真实任务：某些 emit 在任务不存在时会传出 undefined/空值，
// 一旦让 TaskDrawer 以空任务挂载，ModalShell 的 inert 锁会永久留在页面上。
function pick(task?: Task | null) {
  if (task && task.id) selected.value = task;
}
function openNewTask() {
  state.newTaskAccount = "";
  state.newTaskFeature = "course_all";
  state.newTask = true;
}
// T9.6 浮层工具条：进度小窗保持「候选存在即显示」的既有行为（toggle 只控开合），
// 逐题/告警小窗由 WindowManager 管注册、上限与持久化。
function toggleWindow(kind: "progress" | "answers" | "alerts") {
  const win = windows.map[kind];
  if (win?.open) closeWindow(kind);
  else openWindow(kind);
}
// T13：页面标题/文案来自路由 meta（mini 子窗路由不在 nav 里，回退总览）。
const page = computed(
  () =>
    nav.find((n) => n.key === route.name) ||
    ({ key: "overview", title: String(route.meta.title || "工作总览") } as const),
);
// 页面说明文案与标题同源：按路由名映射（此前按 state.view 映射，
// T13 迁移后两份来源会在 /mini 等场景各说各话）。
const pageCopy = computed(
  () =>
    ({
      overview: "当前状态摘要与正在运行的任务；账号、课程与任务分别在专页管理。",
      progress: "逐个账号看每门课程的平台任务点与本轮执行进度，找出还没学完的部分。",
      tasks: "左侧选账号，右侧看该账号的课程与任务，随时暂停、继续或查看执行结果。",
      accounts: "管理账号与登录状态、同步课程；课程详情在弹窗中查看。",
      completed: "汇总每次跑完的任务：课程、时间、耗时、逐题明细与结果说明。",
      bank: "查看、导入与清理本机记住的答案，减少重复调用 AI。",
      settings: "设置默认学习方式、账号并发数量与 AI 服务。",
    })[page.value.key as keyof Record<string, string>] || "",
);
// 顶栏统计与总览、心跳共用 /api/overview 真值；接口缺席时回退本地任务口径。
const engine = computed(() => engineTotals(state.overview, state.tasks));
const headCounts = computed(() => overviewCounts(state.overview, state.workspaces));
const port = computed(() => Number(state.settings.server?.port) || 8848);
let stream: EventSource | undefined,
  timer: ReturnType<typeof setInterval>,
  toastTimer: ReturnType<typeof setTimeout> | undefined,
  debounce: ReturnType<typeof setTimeout> | undefined;
function connect() {
  // T10：携带上次收到的 id 增量重连；EventSource 原生重连自带 Last-Event-ID，
  // 手动重建（回前台/掉线重开）需要把游标拼进 URL。
  const cursor = state.lastEventId > 0 ? `?last_event_id=${state.lastEventId}` : "";
  stream = new EventSource(`/api/events/stream${cursor}`);
  stream.onopen = () => (state.online = true);
  stream.onerror = () => (state.online = false);
  stream.onmessage = (event) => {
    state.eventRevision += 1;
    // 记录游标：SSE id: 行只在持久化事件上出现（id=0 的即时同步消息不带 id）。
    if (event.lastEventId) state.lastEventId = Number(event.lastEventId) || 0;
    let name = "";
    let data: Record<string, unknown> = {};
    try {
      data = (JSON.parse(event.data) || {}) as Record<string, unknown>;
      name = String(data.event || "");
    } catch {
      name = "";
    }
    // T9.6 SSE 分流：逐题小窗吃 answer_result，告警小窗吃异常事件。
    if (name === "answer_result") {
      const payload = (data.payload || {}) as Record<string, unknown>;
      pushAnswerEvent(String(data.task_id || ""), payload, Number(data.ts) || 0);
    }
    if (name === "task_failed" || name === "worker_crash" || name === "interrupted") {
      const narrative = (data.narrative || {}) as Record<string, unknown>;
      pushAlertEvent(
        String(data.task_id || ""),
        String(data.message || narrative.title || "任务异常"),
        Number(data.ts) || 0,
        String(data.level || "error"),
      );
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
    // 增量重连补齐离屏期间的事件；补到的数据经 onmessage 防抖刷新，
    // 但任务/账号列表本身仍需一次全量对账（顺序无关）。
    connect();
    refresh();
  }
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
  initialize();
  connect();
  // T16：应用内验证窗捕获到答题页地址 → Cookie 回写会话缓存 + 交给 NewTask 预填。
  // 浏览器端无桌面桥，注册是空操作。
  onDesktopVerifyCaptured((data) => {
    state.capturedExamUrl = data.url;
    state.toast = "已捕获答题页地址，新建考试任务时会自动带入";
    request(`/accounts/${data.accountId}/session/cookies`, "POST", {
      items: data.cookies,
    }).catch(() => {
      // 回写失败不阻塞预填：地址本身已带回，Cookie 仍可用「获取会话」刷新
    });
  });
  timer = setInterval(() => {
    if (!document.hidden) refresh();
  }, 10000);
  document.addEventListener("visibilitychange", visibility);
});
onUnmounted(() => {
  stream?.close();
  clearInterval(timer);
  clearTimeout(toastTimer);
  clearTimeout(debounce);
  document.removeEventListener("visibilitychange", visibility);
});
</script>
<template>
  <!-- 迷你监控子窗（#/mini）只渲染监控面板本身：Electron 以 340×220 无框窗口
       加载同一地址，若套上侧栏与顶栏会把 220px 高度挤成残片。 -->
  <RouterView v-if="isMini" />
  <div v-else class="shell">
    <aside class="sidebar">
      <a href="#overview" class="brand" @click.prevent="navigate('overview')"
        ><span class="brand-mark"><GraduationCap :size="16" /></span
        ><span>课舟<small>CourseArk</small></span></a
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
            <component :is="item.icon" :size="16" /><span>{{ item.title }}</span>
          </button>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <div class="engine" :class="state.online ? 'is-ok' : 'is-warn'">
          <span class="engine-dot"></span>
          <div class="engine-copy">
            <b>{{ state.online ? "后台服务运行中" : "正在连接后台服务" }}</b>
            <small
              >{{ engine.running }} 运行 · {{ engine.paused }} 暂停 · :{{ port }}</small
            >
          </div>
        </div>
      </div>
    </aside>
    <main class="workspace">
      <header class="topbar">
        <div class="top-title">
          <h1>{{ page.title }}</h1>
          <p>{{ pageCopy }}</p>
        </div>
        <div class="top-actions">
          <button
            v-if="['overview', 'progress', 'tasks'].includes(state.view)"
            class="primary"
            @click="openNewTask"
          >
            <Plus :size="15" />新建学习任务
          </button>
          <div class="top-stats">
            <div class="stat-item" title="已添加的账号数量">
              <b>{{ headCounts.accounts }}</b><span>账号</span>
            </div>
            <div class="stat-item" title="已同步课程总数（含停用账号）">
              <b>{{ headCounts.courses }}</b><span>课程</span>
            </div>
            <div class="stat-item" title="正在执行的任务数量">
              <b>{{ engine.running }}</b><span>运行中</span>
            </div>
          </div>
          <span class="top-sep"></span>
          <div class="window-switcher" role="group" aria-label="浮层小窗开关">
            <button
              :class="{ on: windows.map.progress?.open }"
              :aria-pressed="!!windows.map.progress?.open"
              aria-label="进度小窗开关"
              title="进度小窗"
              @click="toggleWindow('progress')"
            >
              <GraduationCap :size="14" />
            </button>
            <button
              :class="{ on: windows.map.answers?.open }"
              :aria-pressed="!!windows.map.answers?.open"
              aria-label="逐题小窗开关"
              title="逐题作答小窗"
              @click="toggleWindow('answers')"
            >
              <Layers :size="14" />
            </button>
            <button
              :class="{ on: windows.map.alerts?.open }"
              :aria-pressed="!!windows.map.alerts?.open"
              aria-label="告警小窗开关"
              title="任务告警小窗"
              @click="toggleWindow('alerts')"
            >
              <TriangleAlert :size="14" />
            </button>
          </div>
          <button
            class="icon-button"
            aria-label="刷新数据"
            title="刷新数据"
            :disabled="state.loading"
            @click="refresh"
          >
            <RefreshCw :size="15" :class="{ spin: state.loading }" />
          </button>
        </div>
      </header>
      <div class="page-content">
        <div v-if="state.error" class="alert error" role="alert">
          <span>{{ state.error }}</span
          ><button @click="state.error = ''">关闭</button>
        </div>
        <div v-if="state.loading" class="loading-state" role="status" aria-live="polite">
          <span class="loading-dot" />正在读取工作空间…
        </div>
        <!-- T13：页面主体交给 RouterView（routes 见 router.ts）。
             与旧模板一致，loading 期间不挂载页面——SettingsView 等组件在 setup
             时对 state.settings 做一次性快照，必须等 initialize 完成再挂载。 -->
        <RouterView v-else v-slot="{ Component }">
          <component :is="Component" @select="pick" />
        </RouterView>
        <footer class="footer">
          课舟 CourseArk <span>·</span> 数据保存在本机
        </footer>
      </div>
    </main>
    <TaskDrawer v-if="selected" :task="selected" @close="selected = null" />
    <NewTask v-if="state.newTask" @close="state.newTask = false" />
    <ProgressWindow @select="pick" />
    <!-- 两个浮窗共用右上角一列：各自 fixed 到同一坐标会完全重叠，
         叠进 flex 容器后按打开顺序自然错开。 -->
    <div class="float-stack">
      <AnswerFeedWindow v-if="windows.map.answers?.open" @select="pick" />
      <AlertWindow v-if="windows.map.alerts?.open" />
    </div>
    <div v-if="state.toast" class="toast" role="status">{{ state.toast }}</div>
  </div>
</template>