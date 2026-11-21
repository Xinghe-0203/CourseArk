<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Plus,
  RefreshCw,
  ExternalLink,
  Pencil,
  Trash2,
  BookOpen,
  Users,
} from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import type { Account, Course } from "../types";
import ModalShell from "../components/ModalShell.vue";
import ConfirmDialog from "../components/ConfirmDialog.vue";
import { missionState, missionTotals } from "../mission";
import { date, loginState } from "../format";
const edit = ref<Partial<Account> | null>(null),
  password = ref(""),
  courses = ref<Course[]>([]),
  showCourses = ref<Account | null>(null),
  remove = ref<Account | null>(null),
  clearingSession = ref<Account | null>(null);
const missionFor = (course: Course) =>
  missionState(course, showCourses.value?.syncing);
/** 课程弹窗顶部合计：给用户一个「这门课还剩多少任务点」的总数，而不是逐门心算。 */
const courseTotals = computed(() => missionTotals(courses.value));
/** 登录状态：接口一直返回 login_state / last_error，但界面此前只显示「登录时自动验证」。 */
const loginOf = (account: Account) => loginState(account);
async function inspect(a: Account) {
  await act(
    "courses-" + a.id,
    async () => {
      courses.value = (
        await request<{ items: Course[] }>(`/accounts/${a.id}/courses`)
      ).items;
      showCourses.value = a;
    },
    "课程列表已读取",
  );
}
function clearSession() {
  const account = clearingSession.value;
  clearingSession.value = null;
  if (!account) return;
  act(
    "clear-session-" + account.id,
    () => request(`/accounts/${account.id}/session`, "DELETE"),
    "登录缓存已清除",
  );
}
function save() {
  const a = edit.value;
  if (!a) return;
  const body = {
    label: a.label,
    username: a.username,
    enabled: a.enabled,
    ...(password.value ? { password: password.value } : {}),
  };
  act(
    "save-account",
    async () => {
      await request(
        a.id ? `/accounts/${a.id}` : "/accounts",
        a.id ? "PATCH" : "POST",
        body,
      );
      edit.value = null;
      password.value = "";
    },
    "账号已保存",
  );
}
</script>
<template>
  <div class="accounts">
    <div class="section-heading">
      <div>
        <h2>账号</h2>
        <p class="muted">
          {{ state.accounts.length }} 个账号 · 凭据仅供本机后台使用
        </p>
      </div>
      <button
        class="primary"
        @click="
          edit = { label: '', username: '', enabled: true };
          password = '';
        "
      >
        <Plus :size="15" />添加账号
      </button>
    </div>

    <div v-if="state.accounts.length" class="accounts-list">
      <div class="accounts-head" aria-hidden="true">
        <span>账号</span><span>课程</span><span>登录</span><span>操作</span>
      </div>
      <article v-for="a in state.accounts" :key="a.id" class="account-row">
        <div class="account-id">
          <span class="avatar">{{ (a.label || a.username).slice(0, 1) }}</span>
          <div>
            <b>{{ a.label || a.username }}</b>
            <small>{{ a.username_masked || a.username }}</small>
            <span v-if="a.display_name" class="account-nickname"
              >平台昵称 {{ a.display_name }}</span
            >
          </div>
          <span :class="['status', loginOf(a).tone]"
            ><i />{{ loginOf(a).text }}</span
          >
          <span
            v-if="!a.enabled"
            class="status stopped account-disabled"
            ><i />已停用</span
          >
        </div>
        <div class="account-courses">
          <b class="num">{{ a.course_count }}</b>
          <small>门已同步课程</small>
          <button class="text-link" @click="inspect(a)">查看课程</button>
          <p v-if="a.syncing" class="account-sync-line">正在同步课程…</p>
          <p
            v-else-if="a.last_sync_status"
            :class="['account-sync-line', { 'is-failed': a.last_sync_status === 'failed' }]"
          >
            课程同步{{ a.last_sync_status === "failed" ? "失败" : "成功"
            }}<template v-if="typeof a.last_sync_at === 'number'"
              >· {{ date(a.last_sync_at) }}</template
            >
          </p>
          <p v-else class="account-sync-line">还没有同步过课程</p>
        </div>
        <div class="account-session">
          <p
            class="account-note"
            :class="{ 'is-failed': loginOf(a).key === 'failed' }"
          >
            {{
              a.session?.fetching
                ? "正在获取登录缓存…"
                : loginOf(a).key === "failed"
                  ? "密码登录失败，需要重新验证"
                  : a.session?.has_session && a.session?.fresh
                    ? "登录缓存可用，执行任务时无需密码"
                    : loginOf(a).key === "ok"
                      ? "已通过密码登录，缓存过期后会自动重登"
                      : "还没有登录过，首次执行任务时自动验证"
            }}
          </p>
          <p
            v-if="loginOf(a).reason"
            class="account-error"
            :title="a.last_error"
          >
            {{ loginOf(a).reason }}
          </p>
          <small v-if="a.last_login_at" class="account-login-when"
            >最近登录 {{ a.last_login_at.replace("T", " ") }}</small
          >
          <details class="advanced">
            <summary>登录状态与缓存</summary>
            <p>
              登录缓存：{{
                a.session?.has_session && a.session?.fresh ? "可用" : "未准备"
              }}
              {{ a.session?.fetching ? " · 正在获取" : "" }}
            </p>
            <p v-if="a.session?.last_result?.message">
              最近结果：{{ a.session.last_result.ok ? "" : "失败 · "
              }}{{ a.session.last_result.message }}
            </p>
            <div class="button-row">
              <button
                class="small"
                @click="
                  act(
                    'session-' + a.id,
                    () => request(`/accounts/${a.id}/session`, 'POST'),
                    '登录缓存获取已开始',
                  )
                "
              >
                更新登录缓存</button
              ><button
                class="small"
                :disabled="state.busy.has('clear-session-' + a.id)"
                @click="clearingSession = a"
              >
                清除缓存
              </button>
            </div>
          </details>
        </div>
        <div class="account-actions">
          <button
            :disabled="a.syncing || state.busy.has('sync-' + a.id)"
            @click="
              act(
                'sync-' + a.id,
                () => request(`/accounts/${a.id}/sync`, 'POST'),
                '课程同步已开始',
              )
            "
          >
            <RefreshCw :size="14" />{{ a.syncing ? "同步中" : "同步课程" }}</button
          ><button
            :disabled="a.session?.fetching || state.busy.has('open-' + a.id)"
            @click="
              act(
                'open-' + a.id,
                () => request(`/accounts/${a.id}/open-chaoxing`, 'POST'),
                '学习通已打开',
              )
            "
          >
            <ExternalLink :size="14" />打开学习通</button
          ><button
            class="icon-button"
            aria-label="编辑账号"
            title="编辑账号"
            @click="
              edit = { ...a };
              password = '';
            "
          >
            <Pencil :size="14" /></button
          ><button
            class="icon-button"
            aria-label="删除账号"
            title="删除账号"
            @click="remove = a"
          >
            <Trash2 :size="14" />
          </button>
        </div>
      </article>
    </div>

    <div v-if="!state.accounts.length" class="empty">
      <Users :size="28" />
      <h3>还没有账号</h3>
      <p>添加学习通账号后可以同步课程、创建学习任务；密码只保存在本机后台。</p>
      <button
        class="primary"
        @click="
          edit = { label: '', username: '', enabled: true };
          password = '';
        "
      >
        <Plus :size="15" />添加第一个账号
      </button>
    </div>

    <ModalShell
      v-if="edit"
      :title="edit.id ? '编辑账号' : '添加账号'"
      @close="edit = null"
      ><form @submit.prevent="save">
        <label class="field"
          >账号备注<input
            v-model="edit.label"
            placeholder="例如：我的学习账号"
            maxlength="64" /></label
        ><label class="field"
          >学习通账号<input
            v-model="edit.username"
            required
            minlength="5"
            maxlength="32"
            autocomplete="username" /></label
        ><label class="field"
          >{{ edit.id ? "新密码（留空保留原密码）" : "密码"
          }}<input
            v-model="password"
            type="password"
            :required="!edit.id"
            autocomplete="new-password"
            maxlength="128" /></label
        ><label class="check"
          ><input v-model="edit.enabled" type="checkbox" />启用账号</label
        >
        <div class="form-actions">
          <button type="button" @click="edit = null">取消</button
          ><button class="primary" :disabled="state.busy.has('save-account')">
            保存账号
          </button>
        </div>
      </form></ModalShell
    >
    <ModalShell
      v-if="showCourses"
      :title="`${showCourses.label || showCourses.username}的课程`"
      wide
      @close="showCourses = null"
      ><div v-if="courses.length" class="course-summary">
        <span class="eyebrow">任务点合计</span>
        <b class="num">{{ courseTotals.fn }} / {{ courseTotals.all || "—" }}</b>
        <small
          >{{ courses.length }} 门课程 ·
          {{ courses.filter((c) => c.if_open).length }} 门可学习 ·
          {{ courseTotals.all - courseTotals.fn > 0
            ? `${courseTotals.all - courseTotals.fn} 个任务点待完成`
            : "已全部完成" }}</small
        >
      </div>
      <div
        v-for="course in courses"
        :key="course.course_id + course.class_id"
        class="course-item"
      >
        <div class="course-item-main">
          <b>{{ course.name }}</b
          ><small>{{ course.author }} · {{ course.if_open ? "可学习" : "已关闭" }}</small>
        </div>
        <span :class="['course-mission', missionFor(course).tone]">{{
          missionFor(course).text
        }}</span>
      </div>
      <div v-if="!courses.length" class="empty">
        <BookOpen :size="28" />
        <h3>这个账号还没有课程</h3>
        <p>弹窗打开时页面被锁住，同步按钮点不到；可以直接在这里同步。</p>
        <div class="button-row">
          <button
            class="primary"
            :disabled="state.busy.has('sync-' + showCourses.id)"
            @click="
              act(
                'sync-' + showCourses.id,
                () => request(`/accounts/${showCourses!.id}/sync`, 'POST'),
                '课程同步已开始，完成后重新打开这里查看',
              )
            "
          >
            <RefreshCw :size="14" />立即同步课程
          </button>
          <button @click="showCourses = null">返回账号列表</button>
        </div>
      </div></ModalShell
    >
    <ConfirmDialog
      v-if="clearingSession"
      title="清除登录缓存"
      :message="`将清除「${clearingSession.label || clearingSession.username}」保存的登录 Cookie。`"
      hint="下次执行任务会重新用账号密码登录，不影响已同步的课程与任务记录。"
      confirm-text="清除缓存"
      :busy="state.busy.has('clear-session-' + clearingSession.id)"
      @confirm="clearSession"
      @cancel="clearingSession = null"
    />
    <ModalShell v-if="remove" title="删除账号" @close="remove = null"
      ><p>
        确认删除「{{
          remove.label || remove.username
        }}」？正在执行任务的账号无法删除。
      </p>
      <div class="form-actions">
        <button @click="remove = null">取消</button
        ><button
          class="danger"
          :disabled="state.busy.has('delete-account')"
          @click="
            act(
              'delete-account',
              async () => {
                await request(`/accounts/${remove!.id}`, 'DELETE');
                remove = null;
              },
              '账号已删除',
            )
          "
        >
          删除账号
        </button>
      </div></ModalShell
    >
  </div>
</template>

<style scoped>
.accounts {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.accounts-list {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.accounts-head,
.account-row {
  display: grid;
  grid-template-columns:
    minmax(0, 1.1fr) minmax(0, 0.8fr) minmax(0, 1.3fr) auto;
  gap: 14px;
  align-items: start;
  padding: 0 12px;
}

.accounts-head {
  height: 34px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.account-row {
  padding: 15px 14px;
  border-bottom: 1px solid var(--line);
}

.account-row:last-child {
  border-bottom: 0;
}

.account-id {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 10px;
  align-items: center;
}

.account-id > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.account-id b {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-id small {
  font-size: 11.5px;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-id .status {
  grid-column: 2;
  justify-self: start;
  margin-top: 3px;
}

.account-id .account-disabled {
  grid-column: 3;
  grid-row: 1;
  align-self: start;
}

.account-nickname {
  font-size: 10.5px;
  color: var(--faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-error {
  font-size: 11px;
  line-height: 1.5;
  color: var(--danger-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-note.is-failed {
  color: var(--danger-ink);
}

.account-login-when {
  font-family: var(--font-num);
  font-size: 10.5px;
  color: var(--faint);
}

.account-sync-line.is-failed {
  color: var(--danger-ink);
}

/* 课程弹窗：合计条 + 每门课右侧任务点徽标 */
.course-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface2);
}

.course-summary b {
  font-size: 16px;
  font-weight: 500;
  color: var(--ink);
}

.course-summary small {
  font-size: 11px;
  color: var(--mute);
}

.course-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}

.course-item:last-child {
  border-bottom: 0;
}

.course-item-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.course-item-main b {
  font-size: 12.5px;
  font-weight: 600;
}

.course-item-main small {
  font-size: 11px;
  color: var(--mute);
}

.course-mission {
  flex: 0 0 auto;
  font-size: 11.5px;
  white-space: nowrap;
}

.course-mission.ok {
  color: var(--ok);
}

.course-mission.pending {
  color: var(--warn-ink);
}

.course-mission.muted {
  color: var(--faint);
}

.account-courses {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  min-width: 0;
}

.account-courses b {
  font-family: var(--font-num);
  font-size: 15px;
  font-weight: 500;
  color: var(--ink);
}

.account-courses small {
  font-size: 11px;
  color: var(--mute);
}

.account-courses .text-link {
  margin-left: 2px;
}

.account-sync-line {
  width: 100%;
  font-size: 11px;
  color: var(--faint);
}

.account-session {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.account-note {
  font-size: 11.5px;
  color: var(--mute);
}

.account-session .advanced {
  margin-top: 0;
  border: 0;
  background: transparent;
  overflow: visible;
}

.account-session .advanced > summary {
  width: fit-content;
  padding: 0;
  font-size: 11px;
  color: var(--navy2);
}

.account-session .advanced > summary:hover {
  text-decoration: underline;
}

.account-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.account-actions button {
  height: 26px;
  padding: 0 8px;
  font-size: 11.5px;
}

.account-actions .icon-button {
  width: 26px;
  padding: 0;
  border-color: var(--line);
}

@media (max-width: 1080px) {
  .accounts-head {
    display: none;
  }

  .account-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .account-actions {
    justify-content: flex-start;
  }
}
</style>
