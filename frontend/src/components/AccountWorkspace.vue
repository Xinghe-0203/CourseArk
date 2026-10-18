<script setup lang="ts">
import { computed, ref, toRef } from "vue";
import {
  Users,
  RefreshCw,
  Pause,
  Play,
  Square,
  ChevronRight,
  ExternalLink,
  CheckCheck,
  Layers,
  Search,
} from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import { active, statuses, features, date } from "../format";
import { missionState, missionTotals } from "../mission";
import type { AccountWorkspace, Course, Task } from "../types";
const emit = defineEmits<{ select: [task: Task] }>();
const query = ref(""),
  compact = ref(localStorage.getItem("account-layout") === "compact"),
  selectedAccounts = toRef(state, "selectedAccounts"),
  module = ref("course_all");
const profiles = computed(() =>
  state.workspaces.filter((p) =>
    `${p.account.label} ${p.account.username} ${p.courses.map((c) => c.name).join(" ")}`.includes(
      query.value,
    ),
  ),
);
const courseKey = (account: string, c: Course) =>
  [account, c.course_id, c.class_id, c.cpi].join(":");
const totalsFor = (p: AccountWorkspace) => missionTotals(p.courses);
const missionFor = (p: AccountWorkspace, c: Course) =>
  missionState(c, p.account.syncing);
const selectedCount = computed(() => state.selectedCourses.length);
const chosenProfiles = computed(() =>
  state.workspaces.filter((p) => selectedAccounts.value.includes(p.account.id)),
);
const runningCount = computed(() =>
  state.workspaces.reduce((n, p) => n + p.counts.active, 0),
);
const pendingCount = computed(() =>
  state.workspaces.reduce((n, p) => n + p.counts.pending, 0),
);
function toggleLayout() {
  compact.value = !compact.value;
  localStorage.setItem("account-layout", compact.value ? "compact" : "cards");
}
function chooseVisibleAccounts() {
  const ids = profiles.value.map((p) => p.account.id);
  selectedAccounts.value = ids.every((id) =>
    selectedAccounts.value.includes(id),
  )
    ? selectedAccounts.value.filter((id) => !ids.includes(id))
    : [...new Set([...selectedAccounts.value, ...ids])];
}
function chooseAll(p: AccountWorkspace) {
  if (!p.account.enabled) return;
  const keys = p.courses
    .filter((c) => c.if_open)
    .map((c) => courseKey(p.account.id, c));
  if (keys.every((k) => state.selectedCourses.includes(k)))
    state.selectedCourses = state.selectedCourses.filter(
      (k) => !keys.includes(k),
    );
  else
    state.selectedCourses = [...new Set([...state.selectedCourses, ...keys])];
}
function activity(t: Task) {
  return (t.stats.activity as { name?: string } | undefined)?.name || "";
}
function create(p?: AccountWorkspace) {
  if (p && !state.selectedCourses.some((k) => k.startsWith(p.account.id + ":")))
    chooseAll(p);
  state.newTaskFeature = module.value;
  state.newTaskAccount = p?.account.id || "";
  state.newTask = true;
}
function chooseAccounts() {
  state.selectedCourses = chosenProfiles.value
    .filter((p) => p.account.enabled)
    .flatMap((p) =>
      p.courses.filter((c) => c.if_open).map((c) => courseKey(p.account.id, c)),
    );
  create();
}
function taskFor(p: AccountWorkspace, c: Course) {
  return (
    p.tasks.find(
      (t) =>
        active(t) && t.course_id === c.course_id && t.class_id === c.class_id,
    ) ||
    p.tasks.find(
      (t) => t.course_id === c.course_id && t.class_id === c.class_id,
    ) ||
    p.recent.find(
      (t) => t.course_id === c.course_id && t.class_id === c.class_id,
    )
  );
}
function operation(op: string, profilesToUse: AccountWorkspace[]) {
  act(
    "batch-" + op,
    async () => {
      const results = await Promise.allSettled(
        profilesToUse.map((p) =>
          request(`/accounts/${p.account.id}/tasks/${op}`, "POST"),
        ),
      );
      const failed = results.filter((r) => r.status === "rejected");
      const accepted = results.reduce(
        (n, r) =>
          n +
          (r.status === "fulfilled"
            ? (r.value as { accepted: number }).accepted
            : 0),
        0,
      );
      const changed = results.reduce(
        (n, r) =>
          n +
          (r.status === "fulfilled"
            ? (r.value as { changed: number }).changed
            : 0),
        0,
      );
      if (failed.length)
        throw new Error(
          `${accepted} 项指令已接受，${failed.length} 个账号未能接受指令，请刷新查看`,
        );
      return { accepted, changed };
    },
    (result) => {
      const value = result as { accepted: number; changed: number };
      return `已接受 ${value.accepted} 项${op === "pause" ? "暂停" : op === "resume" ? "继续" : "停止"}操作${value.changed ? "，" + value.changed + " 项状态已变化" : ""}`;
    },
  );
}
</script>
<template>
  <div class="workspace-toolbar">
    <label class="search"
      ><Search :size="17" /><input
        v-model="query"
        placeholder="搜索账号或课程"
        aria-label="搜索账号工作台"
    /></label>
    <select v-model="module" aria-label="批量学习模块">
      <option value="course_all">课程任务点</option>
      <option value="independent_homework">独立作业</option>
    </select>
    <button @click="toggleLayout">
      {{ compact ? "卡片展开" : "紧凑展开" }}
    </button>
    <button @click="chooseVisibleAccounts">全选 / 清除当前账号</button>
    <button :disabled="!selectedAccounts.length" @click="chooseAccounts">
      <CheckCheck :size="15" />所选账号开始
    </button>
    <button class="primary" :disabled="!selectedCount" @click="create()">
      创建所选 {{ selectedCount }} 门课程任务
    </button>
  </div>
  <div class="workspace-scope">
    <span
      >{{ profiles.length }} 个账号同时展开 · {{ runningCount }} 项正在执行 ·
      {{ pendingCount }} 项排队</span
    >
    <div class="button-row" v-if="selectedAccounts.length">
      <small>已选择 {{ selectedAccounts.length }} 个账号</small
      ><button @click="operation('pause', chosenProfiles)">批量暂停</button
      ><button @click="operation('resume', chosenProfiles)">批量继续</button
      ><button @click="operation('stop', chosenProfiles)">批量停止</button>
    </div>
  </div>
  <div :class="['account-workspaces', { compact }]">
    <section
      v-for="p in profiles"
      :key="p.account.id"
      class="workspace-account"
    >
      <header class="workspace-account-head">
        <input
          v-model="selectedAccounts"
          type="checkbox"
          :value="p.account.id"
          :aria-label="'选择账号 ' + (p.account.label || p.account.username)"
        /><span class="avatar">{{
          (p.account.label || p.account.username).slice(0, 1)
        }}</span>
        <div>
          <h2>{{ p.account.label || p.account.username }}</h2>
          <small
            >{{ p.account.username }} ·
            {{
              p.account.session?.has_session && p.account.session?.fresh
                ? "登录缓存可用"
                : "登录时自动验证"
            }}</small
          >
        </div>
        <span
          :class="[
            'status',
            p.counts.active
              ? 'running'
              : p.counts.paused
                ? 'paused'
                : 'pending',
          ]"
          >{{
            p.counts.active
              ? "正在执行"
              : p.counts.paused
                ? "已暂停"
                : p.account.enabled
                  ? "就绪"
                  : "已停用"
          }}</span
        >
      </header>
      <div class="workspace-account-scroll">
        <div class="account-numbers">
          <div>
            <strong>{{ p.courses.length }}</strong
            ><span>课程</span>
          </div>
          <div
            :class="{
              attention: totalsFor(p).all && totalsFor(p).fn < totalsFor(p).all,
            }"
          >
            <strong
              >{{ totalsFor(p).fn
              }}<small> / {{ totalsFor(p).all || "—" }}</small></strong
            ><span>{{
              totalsFor(p).all ? "平台任务点（缓存）" : "任务点未同步"
            }}</span>
          </div>
          <div>
            <strong
              >{{ p.counts.active
              }}<small> / {{ p.counts.pending }}</small></strong
            ><span>执行 / 排队</span>
          </div>
          <div :class="{ attention: p.counts.failed }">
            <strong>{{ p.counts.failed }}</strong
            ><span>需处理任务</span>
          </div>
        </div>
        <div
          class="account-live"
          v-if="p.tasks.some((t) => active(t) || t.status === 'paused')"
        >
          <article
            v-for="t in p.tasks.filter(
              (t) => active(t) || t.status === 'paused',
            )"
            :key="t.id"
          >
            <div class="live-heading">
              <span class="live-dot" /><b>{{ t.course_name }}</b
              ><span>{{ features[t.feature] || t.feature_label }}</span
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
                >{{
                  t.progress.total
                    ? `${t.progress.completed}/${t.progress.total} 项已确认`
                    : "正在发现任务点"
                }}<b v-if="t.progress.percent !== null"
                  >{{ t.progress.percent }}%</b
                ></small
              >
            </div>
            <div class="live-details">
              <span v-if="t.stats.activity">{{ activity(t) }}</span
              ><span
                >答题 {{ t.stats.questions || 0 }} · 缓存命中
                {{ t.stats.cache_hits || 0 }} · AI
                {{ t.stats.llm_calls || 0 }}</span
              ><span
                >提交接受 {{ t.stats.submit_ok || 0 }} · 未完成
                {{ (t.progress.failed || 0) + (t.progress.blocked || 0) }}</span
              >
            </div>
            <ul class="media-live" v-if="t.progress.active.length">
              <li v-for="m in t.progress.active.slice(0, 6)" :key="m.id">
                <span>{{
                  m.kind === "video"
                    ? "视频"
                    : m.kind === "audio"
                      ? "音频"
                      : m.kind === "work"
                        ? "测验"
                        : "处理中"
                }}</span
                ><b>{{ m.name }}</b
                ><small v-if="m.total"
                  >{{ m.current || 0 }} / {{ m.total
                  }}{{
                    ["video", "audio"].includes(m.kind) ? " 秒" : ""
                  }}</small
                ><small v-else>进行中</small>
              </li>
            </ul>
          </article>
        </div>
        <div class="account-result" v-else-if="p.recent.length">
          <span :class="['status', p.recent[0]!.status]">{{
            statuses[p.recent[0]!.status]
          }}</span>
          <b>{{ p.recent[0]!.course_name }}</b>
          <small
            >最近结果 · 完成 {{ p.recent[0]!.progress.completed }} /
            {{ p.recent[0]!.progress.total || "—" }} 项 · 提交接受
            {{ p.recent[0]!.stats.submit_ok || 0 }}</small
          >
          <p v-if="p.recent[0]!.error">{{ p.recent[0]!.error }}</p>
          <button class="text-link" @click="emit('select', p.recent[0]!)">
            查看结果
          </button>
        </div>
        <div class="account-course-heading">
          <h3>课程与任务</h3>
          <button
            class="text-link"
            :disabled="!p.account.enabled"
            @click="chooseAll(p)"
          >
            选择可学习课程</button
          ><button
            class="icon-button"
            :disabled="
              p.account.syncing || state.busy.has('sync-' + p.account.id)
            "
            :aria-label="'同步 ' + p.account.label + ' 的课程'"
            @click="
              act(
                'sync-' + p.account.id,
                () => request(`/accounts/${p.account.id}/sync`, 'POST'),
                '课程同步已开始',
              )
            "
          >
            <RefreshCw :size="14" />
          </button>
        </div>
        <div class="workspace-courses">
          <article
            v-for="c in p.courses"
            :key="courseKey(p.account.id, c)"
            class="workspace-course"
          >
            <input
              v-model="state.selectedCourses"
              type="checkbox"
              :value="courseKey(p.account.id, c)"
              :disabled="!c.if_open || !p.account.enabled"
              :aria-label="'选择课程 ' + c.name"
            />
            <div class="workspace-course-main">
              <b>{{ c.name }}</b
              ><small
                >{{ c.author || "课程" }} ·
                <span :class="['course-mission', missionFor(p, c).tone]">{{
                  missionFor(p, c).text
                }}</span>
                · {{ c.if_open ? "开放" : "关闭" }}</small
              >
              <div class="course-task-line" v-if="taskFor(p, c)">
                <span :class="['status', taskFor(p, c)!.status]">{{
                  statuses[taskFor(p, c)!.status]
                }}</span
                ><span>{{
                  features[taskFor(p, c)!.feature] ||
                  taskFor(p, c)!.feature_label
                }}</span
                ><span v-if="taskFor(p, c)!.progress.total"
                  >本轮 {{ taskFor(p, c)!.progress.completed }} /
                  {{ taskFor(p, c)!.progress.total }} 项</span
                ><button
                  class="text-link"
                  @click="emit('select', taskFor(p, c)!)"
                >
                  查看
                </button>
              </div>
              <div class="progress-track course-cache-progress">
                <i :style="{ width: missionFor(p, c).percent + '%' }" />
              </div>
            </div>
          </article>
          <div v-if="!p.courses.length" class="account-empty">
            暂无课程，点击同步后即可选择。
          </div>
        </div>
      </div>
      <footer class="account-controls">
        <button
          :disabled="!p.account.enabled || !p.courses.some((c) => c.if_open)"
          @click="create(p)"
        >
          <Layers :size="14" />创建任务</button
        ><button
          v-if="p.counts.active"
          class="icon-button"
          aria-label="暂停此账号"
          @click="operation('pause', [p])"
        >
          <Pause :size="15" /></button
        ><button
          v-if="p.counts.paused"
          class="icon-button"
          aria-label="继续此账号"
          @click="operation('resume', [p])"
        >
          <Play :size="15" /></button
        ><button
          v-if="p.tasks.length"
          class="icon-button"
          aria-label="停止此账号"
          @click="operation('stop', [p])"
        >
          <Square :size="14" /></button
        ><button
          class="text-link"
          @click="
            act(
              'open-' + p.account.id,
              () => request(`/accounts/${p.account.id}/open-chaoxing`, 'POST'),
              '学习通已打开',
            )
          "
        >
          <ExternalLink :size="13" />学习通</button
        ><small>{{
          p.account.syncing
            ? "同步中…"
            : "缓存更新 " + date(p.courses[0]?.synced_at)
        }}</small>
      </footer>
    </section>
  </div>
  <div v-if="!profiles.length" class="empty">
    <Users :size="30" />
    <h3>暂无账号</h3>
    <p>在账号与课程中添加账号后，数据会同时显示在这里。</p>
  </div>
</template>
