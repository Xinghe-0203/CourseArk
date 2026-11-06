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
import { courseKey, taskForCourse } from "../course";
import type { AccountWorkspace, Course, Task } from "../types";
const emit = defineEmits<{ select: [task: Task] }>();
const query = ref(""),
  activeId = ref(""),
  selectedAccounts = toRef(state, "selectedAccounts"),
  module = ref("course_all");
const profiles = computed(() =>
  state.workspaces.filter((p) =>
    `${p.account.label} ${p.account.username} ${p.courses.map((c) => c.name).join(" ")}`.includes(
      query.value,
    ),
  ),
);
// 二级菜单：左侧账号列表，右侧只渲染当前选中账号的详情。
const selected = computed<AccountWorkspace | null>(
  () => profiles.value.find((p) => p.account.id === activeId.value) || profiles.value[0] || null,
);
const totalsFor = (p: AccountWorkspace) => missionTotals(p.courses);
const missionFor = (p: AccountWorkspace, c: Course) => missionState(c, p.account.syncing);
// 任务点用「已完成 / 总数 + 待完成」两个数，避免与右侧状态徽标的「已完成」撞词。
function missionNumbers(c: Course) {
  const all = Math.max(0, Number(c.mission_all) || 0);
  const fn = Math.max(0, Number(c.mission_fn) || 0);
  return { all, fn, pending: Math.max(0, all - fn), percent: all ? Math.min(100, Math.round((fn / all) * 100)) : 0 };
}
function accountTone(p: AccountWorkspace) {
  return p.counts.active ? "running" : p.counts.paused ? "paused" : "pending";
}
function accountState(p: AccountWorkspace) {
  if (p.account.syncing) return "同步中";
  if (!p.account.enabled) return "已停用";
  if (p.counts.active) return "正在执行";
  if (p.counts.paused) return "已暂停";
  return "就绪";
}
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
function chooseVisibleAccounts() {
  const ids = profiles.value.map((p) => p.account.id);
  selectedAccounts.value = ids.every((id) => selectedAccounts.value.includes(id))
    ? selectedAccounts.value.filter((id) => !ids.includes(id))
    : [...new Set([...selectedAccounts.value, ...ids])];
}
function chooseAll(p: AccountWorkspace) {
  if (!p.account.enabled) return;
  const keys = p.courses.filter((c) => c.if_open).map((c) => courseKey(p.account.id, c));
  if (keys.every((k) => state.selectedCourses.includes(k)))
    state.selectedCourses = state.selectedCourses.filter((k) => !keys.includes(k));
  else state.selectedCourses = [...new Set([...state.selectedCourses, ...keys])];
}
function activity(t: Task) {
  return (t.stats.activity as { name?: string } | undefined)?.name || "";
}
function create(p?: AccountWorkspace) {
  if (p && !state.selectedCourses.some((k) => k.startsWith(p.account.id + ":"))) chooseAll(p);
  state.newTaskFeature = module.value;
  state.newTaskAccount = p?.account.id || "";
  state.newTask = true;
}
function chooseAccounts() {
  state.selectedCourses = chosenProfiles.value
    .filter((p) => p.account.enabled)
    .flatMap((p) => p.courses.filter((c) => c.if_open).map((c) => courseKey(p.account.id, c)));
  create();
}
const taskFor = (p: AccountWorkspace, c: Course) => taskForCourse(p, c);
function operation(op: string, profilesToUse: AccountWorkspace[]) {
  act(
    "batch-" + op,
    async () => {
      const results = await Promise.allSettled(
        profilesToUse.map((p) => request(`/accounts/${p.account.id}/tasks/${op}`, "POST")),
      );
      const failed = results.filter((r) => r.status === "rejected");
      const accepted = results.reduce(
        (n, r) => n + (r.status === "fulfilled" ? (r.value as { accepted: number }).accepted : 0),
        0,
      );
      const changed = results.reduce(
        (n, r) => n + (r.status === "fulfilled" ? (r.value as { changed: number }).changed : 0),
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
  <div class="account-workspace">
    <div class="workspace-toolbar">
      <label class="search"
        ><Search :size="15" /><input
          v-model="query"
          placeholder="搜索账号或课程"
          aria-label="搜索账号工作台"
      /></label>
      <select v-model="module" aria-label="批量学习模块">
        <option value="course_all">课程任务点</option>
        <option value="independent_homework">独立作业</option>
      </select>
      <button @click="chooseVisibleAccounts">全选 / 清除当前账号</button>
      <button :disabled="!selectedAccounts.length" @click="chooseAccounts">
        <CheckCheck :size="14" />所选账号开始
      </button>
      <button class="primary" :disabled="!selectedCount" @click="create()">
        创建所选 {{ selectedCount }} 门课程任务
      </button>
    </div>

    <div class="workspace-scope">
      <span
        >{{ profiles.length }} 个账号 · {{ runningCount }} 项正在执行 ·
        {{ pendingCount }} 项排队</span
      >
      <div class="button-row" v-if="selectedAccounts.length">
        <small>已选择 {{ selectedAccounts.length }} 个账号</small
        ><button class="small" @click="operation('pause', chosenProfiles)">
          批量暂停</button
        ><button class="small" @click="operation('resume', chosenProfiles)">
          批量继续</button
        ><button class="small" @click="operation('stop', chosenProfiles)">
          批量停止</button
        >
      </div>
    </div>

    <div class="account-workspaces" v-if="profiles.length">
      <nav class="account-menu" aria-label="账号列表">
        <div class="account-menu-head">
          <span>账号</span><span class="faint">{{ profiles.length }}</span>
        </div>
        <div
          v-for="p in profiles"
          :key="p.account.id"
          class="account-menu-item"
          :class="{ chosen: selected && selected.account.id === p.account.id }"
        >
          <input
            v-model="selectedAccounts"
            type="checkbox"
            :value="p.account.id"
            :aria-label="'选择账号 ' + (p.account.label || p.account.username)"
          />
          <button
            class="account-pick"
            :aria-label="'查看账号 ' + (p.account.label || p.account.username)"
            @click="activeId = p.account.id"
          >
            <span class="avatar">{{
              (p.account.label || p.account.username).slice(0, 1)
            }}</span>
            <span class="pick-copy">
              <b>{{ p.account.label || p.account.username }}</b>
              <small
                >{{ p.courses.length }} 门 · {{ totalsFor(p).fn }} /
                {{ totalsFor(p).all || "—" }} 任务点</small
              >
            </span>
            <span
              :class="['menu-dot', accountTone(p)]"
              :title="accountState(p)"
            ></span>
          </button>
        </div>
      </nav>

      <section class="workspace-account" v-if="selected">
        <header class="workspace-account-head">
          <span class="avatar">{{
            (selected.account.label || selected.account.username).slice(0, 1)
          }}</span>
          <div class="account-name">
            <h2>{{ selected.account.label || selected.account.username }}</h2>
            <small
              >{{ selected.account.username }} ·
              {{
                selected.account.session?.has_session &&
                selected.account.session?.fresh
                  ? "登录缓存可用"
                  : "登录时自动验证"
              }}</small
            >
          </div>
          <span :class="['status', accountTone(selected)]"
            ><i />{{ accountState(selected) }}</span
          >
          <div class="head-actions">
            <button
              :disabled="
                !selected.account.enabled ||
                !selected.courses.some((c) => c.if_open)
              "
              @click="create(selected)"
            >
              <Layers :size="13" />创建任务</button
            ><button
              v-if="selected.counts.active"
              aria-label="暂停此账号"
              title="暂停此账号"
              @click="operation('pause', [selected])"
            >
              <Pause :size="12" />暂停</button
            ><button
              v-if="selected.counts.paused"
              aria-label="继续此账号"
              title="继续此账号"
              @click="operation('resume', [selected])"
            >
              <Play :size="12" />继续</button
            ><button
              v-if="selected.tasks.length"
              aria-label="停止此账号"
              title="停止此账号"
              @click="operation('stop', [selected])"
            >
              <Square :size="12" />停止</button
            ><button
              class="text-link"
              @click="
                act(
                  'open-' + selected.account.id,
                  () =>
                    request(
                      `/accounts/${selected!.account.id}/open-chaoxing`,
                      'POST',
                    ),
                  '学习通已打开',
                )
              "
            >
              <ExternalLink :size="12" />学习通</button
            ><button
              class="icon-button"
              :disabled="
                selected.account.syncing ||
                state.busy.has('sync-' + selected.account.id)
              "
              :aria-label="
                '同步 ' +
                (selected.account.label || selected.account.username) +
                ' 的课程'
              "
              title="同步课程"
              @click="
                act(
                  'sync-' + selected.account.id,
                  () =>
                    request(`/accounts/${selected!.account.id}/sync`, 'POST'),
                  '课程同步已开始',
                )
              "
            >
              <RefreshCw :size="14" />
            </button>
          </div>
        </header>

        <div class="account-numbers">
          <div>
            <strong class="num">{{ selected.courses.length }}</strong
            ><span>课程</span>
          </div>
          <div :class="{ attention: totalsFor(selected).all && totalsFor(selected).fn < totalsFor(selected).all }">
            <strong class="num"
              >{{ totalsFor(selected).fn
              }}<small> / {{ totalsFor(selected).all || "—" }}</small></strong
            ><span>{{
              totalsFor(selected).all ? "平台任务点" : "任务点未同步"
            }}</span>
          </div>
          <div>
            <strong class="num"
              >{{ selected.counts.active
              }}<small> / {{ selected.counts.pending }}</small></strong
            ><span>执行 / 排队</span>
          </div>
          <div :class="{ attention: selected.counts.failed }">
            <strong class="num">{{ selected.counts.failed }}</strong
            ><span>需处理任务</span>
          </div>
          <div>
            <strong class="num">{{ selected.counts.succeeded }}</strong
            ><span>最近完成</span>
          </div>
        </div>

        <div
          class="account-live"
          v-if="selected.tasks.some((t) => active(t) || t.status === 'paused')"
        >
          <article
            v-for="t in selected.tasks.filter(
              (t) => active(t) || t.status === 'paused',
            )"
            :key="t.id"
          >
            <div class="live-heading">
              <span class="live-dot" /><b>{{ t.course_name }}</b
              ><span class="muted"
                >{{ features[t.feature] || t.feature_label }}</span
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
              <div class="progress-pair">
                <span
                  >{{
                    t.progress.total
                      ? `${t.progress.completed}/${t.progress.total} 项已确认`
                      : "正在发现任务点"
                  }}</span
                ><b v-if="t.progress.percent !== null"
                  >{{ t.progress.percent }}%</b
                >
              </div>
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
                <span class="media-kind">{{
                  m.kind === "video"
                    ? "视频"
                    : m.kind === "audio"
                      ? "音频"
                      : m.kind === "work"
                        ? "测验"
                        : "处理中"
                }}</span>
                <b>{{ m.name }}</b>
                <small v-if="m.total" class="num"
                  >{{ m.current || 0 }} / {{ m.total
                  }}{{ ["video", "audio"].includes(m.kind) ? " 秒" : "" }}</small
                >
                <small v-else>进行中</small>
              </li>
            </ul>
          </article>
        </div>
        <div class="account-result" v-else-if="selected.recent.length">
          <span :class="['status', selected.recent[0]!.status]"
            ><i />{{ statuses[selected.recent[0]!.status] }}</span
          >
          <b>{{ selected.recent[0]!.course_name }}</b>
          <small
            >最近结果 · 完成 {{ selected.recent[0]!.progress.completed }} /
            {{ selected.recent[0]!.progress.total || "—" }} 项 · 提交接受
            {{ selected.recent[0]!.stats.submit_ok || 0 }}</small
          >
          <p v-if="selected.recent[0]!.error">{{ selected.recent[0]!.error }}</p>
          <button class="text-link" @click="emit('select', selected.recent[0]!)">
            查看结果
          </button>
          <div class="account-recent-more" v-if="selected.recent.length > 1">
            <button
              v-for="t in selected.recent.slice(1)"
              :key="t.id"
              class="recent-row"
              @click="emit('select', t)"
            >
              <span :class="['status', t.status]"
                ><i />{{ statuses[t.status] }}</span
              >
              <b>{{ t.course_name }}</b>
              <small class="num"
                >{{ t.progress.completed }} / {{ t.progress.total || "—" }} 项</small
              >
            </button>
          </div>
        </div>

        <div class="account-course-heading">
          <h3>课程与任务</h3>
          <button
            class="text-link"
            :disabled="!selected.account.enabled"
            @click="chooseAll(selected)"
          >
            选择可学习课程
          </button>
          <small class="faint">{{
            selected.account.syncing
              ? "同步中…"
              : "缓存更新 " + date(selected.courses[0]?.synced_at)
          }}</small>
        </div>

        <div class="workspace-courses">
          <div class="course-row-head">
            <span>课程</span><span>平台任务点</span><span>本轮任务</span
            ><span>完成度</span>
          </div>
          <article
            v-for="c in selected.courses"
            :key="courseKey(selected.account.id, c)"
            class="workspace-course"
          >
            <div class="course-pick">
              <input
                v-model="state.selectedCourses"
                type="checkbox"
                :value="courseKey(selected.account.id, c)"
                :disabled="!c.if_open || !selected.account.enabled"
                :aria-label="'选择课程 ' + c.name"
              />
              <div class="course-name">
                <b>{{ c.name }}</b>
                <small
                  >{{ c.author || "课程" }} ·
                  {{ c.if_open ? "开放" : "课程已关闭" }}</small
                >
              </div>
            </div>
            <div class="course-mission" :class="missionFor(selected, c).tone">
              <b class="num"
                >{{ missionNumbers(c).fn }}
                <small>/ {{ missionNumbers(c).all || "—" }}</small></b
              >
              <small v-if="missionNumbers(c).all"
                >待完成 {{ missionNumbers(c).pending }}</small
              >
              <small v-else>未同步</small>
            </div>
            <div class="course-task">
              <template v-if="taskFor(selected, c)">
                <span :class="['status', taskFor(selected, c)!.status]"
                  ><i />{{ statuses[taskFor(selected, c)!.status] }}</span
                >
                <small class="muted">{{
                  features[taskFor(selected, c)!.feature] ||
                  taskFor(selected, c)!.feature_label
                }}</small>
                <small v-if="taskFor(selected, c)!.progress.total" class="num"
                  >{{ taskFor(selected, c)!.progress.completed }} /
                  {{ taskFor(selected, c)!.progress.total }} 项</small
                >
              </template>
              <span v-else class="faint">{{
                c.if_open ? "还没有执行过" : "课程已关闭"
              }}</span>
            </div>
            <div class="course-progress">
              <div class="progress-track small">
                <i :style="{ width: missionFor(selected, c).percent + '%' }" />
              </div>
              <b class="num">{{ missionFor(selected, c).percent }}%</b>
              <button
                v-if="taskFor(selected, c)"
                class="text-link"
                @click="emit('select', taskFor(selected, c)!)"
              >
                查看
              </button>
            </div>
          </article>
          <div v-if="!selected.courses.length" class="account-empty">
            暂无课程，点击同步后即可选择。
          </div>
        </div>
      </section>
    </div>

    <div v-if="!profiles.length" class="empty">
      <Users :size="26" />
      <h3>暂无账号</h3>
      <p>在账号与课程中添加账号后，数据会同时显示在这里。</p>
    </div>
  </div>
</template>
<style scoped>
.account-workspace {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workspace-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.workspace-toolbar select {
  width: auto;
  min-width: 132px;
  height: 28px;
}

.workspace-scope {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 12px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface2);
  font-size: 11.5px;
  color: var(--mute);
}

/* 二级菜单：左列账号，右侧详情 */
.account-workspaces {
  display: grid;
  grid-template-columns: 238px minmax(0, 1fr);
  align-items: start;
  gap: 12px;
}

.account-menu {
  position: sticky;
  top: calc(var(--topbar) + 8px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.account-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  color: var(--faint);
}

.account-menu-item {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  padding: 0 8px 0 10px;
  border-bottom: 1px solid var(--line);
}

.account-menu-item:last-child {
  border-bottom: 0;
}

.account-menu-item.chosen {
  background: var(--navy-soft);
}

.account-pick {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) 8px;
  align-items: center;
  gap: 7px;
  width: 100%;
  height: auto;
  padding: 7px 0;
  border: 0;
  background: transparent;
  text-align: left;
}

.pick-copy {
  min-width: 0;
}

.pick-copy b {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pick-copy small {
  display: block;
  font-size: 10.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--line2);
}

.menu-dot.running {
  background: var(--ok);
  animation: pulse 2s infinite;
}

.menu-dot.paused {
  background: var(--warn);
}

.workspace-account {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.workspace-account-head {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 4px 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.account-name {
  min-width: 0;
}

.account-name h2 {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-name small {
  display: block;
  font-size: 10.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.head-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.head-actions button {
  height: 24px;
  padding: 0 8px;
  font-size: 11px;
}

.account-numbers {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}

.account-numbers > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 6px 10px;
  background: var(--surface);
}

.account-numbers strong {
  font-size: 15px;
  font-weight: 500;
  line-height: 1.2;
}

.account-numbers strong small {
  font-size: 11px;
  color: var(--faint);
}

.account-numbers span {
  font-size: 10px;
  color: var(--faint);
}

.account-numbers .attention strong {
  color: var(--warn);
}

.account-live article {
  padding: 8px 12px;
  border-left: 2px solid var(--ok);
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.live-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  font-size: 12px;
}

.live-heading b {
  font-weight: 600;
}

.live-heading .text-link {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  margin-left: auto;
  font-size: 11.5px;
}

.live-progress {
  margin-top: 6px;
}

.live-details {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  margin-top: 5px;
  font-size: 11px;
  color: var(--mute);
}

.media-live {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 6px;
}

.media-live li {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  font-size: 11px;
}

.media-live li b {
  font-weight: 500;
  color: var(--ink2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.media-kind {
  font-size: 10px;
  color: var(--faint);
}

.account-result {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 9px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 11.5px;
}

.account-result > b {
  font-weight: 600;
}

.account-result > p {
  flex-basis: 100%;
  margin: 0;
  font-size: 11px;
  color: var(--danger);
}

.account-recent-more {
  display: flex;
  flex-direction: column;
  flex-basis: 100%;
  gap: 1px;
  margin-top: 2px;
  border-top: 1px solid var(--line);
  padding-top: 4px;
}

.recent-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 24px;
  padding: 0 4px;
  border: 0;
  background: transparent;
  text-align: left;
  font-size: 11.5px;
}

.recent-row:hover {
  background: var(--surface3);
}

.recent-row b {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-course-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px 6px;
}

.account-course-heading h3 {
  font-size: 12px;
  font-weight: 600;
}

.account-course-heading small {
  margin-left: auto;
  font-size: 10.5px;
}

.course-row-head,
.workspace-course {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) 132px minmax(0, 1.15fr) 168px;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
}

.course-row-head {
  height: 24px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.workspace-course {
  padding-top: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line);
}

.workspace-course:last-of-type {
  border-bottom: 0;
}

.workspace-course:hover {
  background: var(--surface2);
}

.course-pick {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.course-name {
  min-width: 0;
}

.course-name b {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-name small {
  display: block;
  font-size: 10.5px;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-mission {
  min-width: 0;
  font-size: 11.5px;
  color: var(--ink2);
}

.course-mission b {
  font-size: 13px;
  font-weight: 500;
}

.course-mission b small {
  font-size: 11px;
  color: var(--faint);
}

.course-mission > small {
  display: block;
  font-size: 10.5px;
  color: var(--mute);
}

.course-mission.ok b {
  color: var(--ok);
}

.course-mission.muted {
  color: var(--faint);
}

.course-task {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px 7px;
  min-width: 0;
  font-size: 11px;
}

.course-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
}

.course-progress b {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink2);
}

.course-progress .text-link {
  font-size: 11.5px;
}

.account-empty {
  padding: 14px 12px;
  font-size: 11.5px;
  color: var(--mute);
}

@media (max-width: 1080px) {
  .account-workspaces {
    grid-template-columns: minmax(0, 1fr);
  }

  .account-menu {
    position: static;
    flex-direction: row;
    overflow-x: auto;
  }

  .account-menu-head {
    display: none;
  }

  .account-menu-item {
    flex: 0 0 auto;
    border-bottom: 0;
    border-right: 1px solid var(--line);
  }

  .account-pick {
    width: 168px;
    grid-template-columns: 26px minmax(0, 1fr) 8px;
  }

  .account-numbers {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .course-row-head {
    display: none;
  }

  .workspace-course {
    grid-template-columns: minmax(0, 1fr) 128px;
    gap: 4px 12px;
    padding-top: 8px;
    padding-bottom: 8px;
  }

  .course-pick {
    grid-column: 1;
  }

  .course-progress {
    grid-column: 2;
    grid-row: 1;
  }

  .course-task {
    grid-column: 1 / -1;
  }
}
</style>
