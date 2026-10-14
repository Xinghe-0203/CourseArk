<script setup lang="ts">
import { ref } from "vue";
import {
  Plus,
  RefreshCw,
  ExternalLink,
  Pencil,
  Trash2,
  BookOpen,
} from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import type { Account, Course } from "../types";
import ModalShell from "./ModalShell.vue";
const edit = ref<Partial<Account> | null>(null),
  password = ref(""),
  courses = ref<Course[]>([]),
  showCourses = ref<Account | null>(null),
  remove = ref<Account | null>(null);
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
  <div class="section-heading">
    <p class="muted">
      {{ state.accounts.length }} 个账号 · 凭据仅供本机后台使用
    </p>
    <button
      class="primary"
      @click="
        edit = { label: '', username: '', enabled: true };
        password = '';
      "
    >
      <Plus :size="16" />添加账号
    </button>
  </div>
  <div class="accounts-grid">
    <article v-for="a in state.accounts" :key="a.id" class="account-card">
      <div class="account-card-header">
        <span class="avatar large">{{
          (a.label || a.username).slice(0, 1)
        }}</span>
        <div>
          <h2>{{ a.label || a.username }}</h2>
          <small>{{ a.username }}</small>
        </div>
        <span :class="['status', a.enabled ? 'running' : 'paused']">{{
          a.enabled ? "已启用" : "已停用"
        }}</span>
      </div>
      <div class="account-course-count">
        <BookOpen :size="18" /><b>{{ a.course_count }}</b> 门已同步课程<button
          class="text-link"
          @click="inspect(a)"
        >
          查看课程
        </button>
      </div>
      <p class="account-note">
        {{
          a.syncing
            ? "正在同步课程，请稍候…"
            : a.last_sync_status === "failed"
              ? "课程同步未成功，缓存课程仍可查看"
              : a.course_count
                ? "课程已就绪，可以创建任务"
                : "先同步课程，再创建学习任务"
        }}
      </p>
      <div class="card-actions">
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
          <RefreshCw :size="15" />{{
            a.syncing ? "同步中" : "同步课程"
          }}</button
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
          <ExternalLink :size="15" />打开学习通</button
        ><button
          class="icon-button"
          aria-label="编辑账号"
          @click="
            edit = { ...a };
            password = '';
          "
        >
          <Pencil :size="15" /></button
        ><button class="icon-button" aria-label="删除账号" @click="remove = a">
          <Trash2 :size="15" />
        </button>
      </div>
      <details class="advanced">
        <summary>登录状态与缓存</summary>
        <p>
          登录缓存：{{
            a.session?.has_session && a.session?.fresh ? "可用" : "未准备"
          }}
          {{ a.session?.fetching ? " · 正在获取" : "" }}
        </p>
        <button
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
          @click="
            act(
              'session-' + a.id,
              () => request(`/accounts/${a.id}/session`, 'DELETE'),
              '登录缓存已清除',
            )
          "
        >
          清除缓存
        </button>
      </details>
    </article>
    <div v-if="!state.accounts.length" class="empty">
      添加第一个账号，开始管理课程。
    </div>
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
    ><div
      v-for="course in courses"
      :key="course.course_id + course.class_id"
      class="course-item"
    >
      <div>
        <b>{{ course.name }}</b
        ><small
          >{{ course.author }} · {{ course.if_open ? "可学习" : "已关闭" }} ·
          {{ course.mission_fn }} / {{ course.mission_all }} 个任务点</small
        >
      </div>
    </div>
    <div v-if="!courses.length" class="empty">
      暂无课程，请先同步。
    </div></ModalShell
  >
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
</template>
