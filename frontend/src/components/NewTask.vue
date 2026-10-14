<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from "vue";
import { state, act, navigate } from "../store";
import { request } from "../api";
import { features } from "../format";
import type { Course, Settings } from "../types";
import ModalShell from "./ModalShell.vue";
import ParameterForm from "./ParameterForm.vue";
const emit = defineEmits<{ close: [] }>();
type PickCourse = Course & { account_id: string; account_label: string };
const accounts = computed(() => state.accounts.filter((a) => a.enabled));
const initialAccounts = state.newTaskAccount
  ? [state.newTaskAccount]
  : state.selectedCourses.length
    ? [...new Set(state.selectedCourses.map((k) => k.split(":")[0]!))]
    : state.selectedAccounts;
const selectedAccounts = ref(
  initialAccounts.filter((id) => accounts.value.some((a) => a.id === id)),
);
const step = ref(1),
  feature = ref(state.newTaskFeature || "course_all"),
  chosen = ref<string[]>([...state.selectedCourses]),
  all = ref<PickCourse[]>([]),
  note = ref(""),
  error = ref(""),
  loading = ref(false),
  courseErrors = ref<Record<string, string>>({}),
  presets = ref<{ id: string; name: string; params: Settings }[]>([]),
  presetName = ref("");
const params = reactive(
  JSON.parse(
    JSON.stringify(
      state.settings.defaults || {
        video: { mode: "hybrid", max_workers: 8 },
        answer: {
          mode: "ai",
          auto_submit: true,
          fallback_to_tiku: true,
          no_answer_action: "skip",
          submit_delay: 2,
        },
      },
    ),
  ),
);
const key = (c: PickCourse) =>
  [c.account_id, c.course_id, c.class_id, c.cpi].join(":");
const grouped = computed(() =>
  accounts.value
    .filter((a) => selectedAccounts.value.includes(a.id))
    .map((a) => ({
      account: a,
      courses: all.value.filter((c) => c.account_id === a.id),
    })),
);
const eligible = computed(() =>
  all.value.filter(
    (c) =>
      c.if_open &&
      accounts.value.some((a) => a.id === c.account_id) &&
      selectedAccounts.value.includes(c.account_id),
  ),
);
const targets = computed(() =>
  eligible.value
    .filter((c) => chosen.value.includes(key(c)))
    .map((c) => ({
      account_id: c.account_id,
      course_id: c.course_id,
      class_id: c.class_id,
      cpi: c.cpi,
      course_name: c.name,
    })),
);
let generation = 0,
  alive = true;
watch(selectedAccounts, (ids) => {
  chosen.value = chosen.value.filter((k) => ids.includes(k.split(":")[0]!));
});
onMounted(async () => {
  try {
    presets.value = (
      await request<{ items: typeof presets.value }>("/presets")
    ).items;
  } catch (e) {
    if (alive) error.value = (e as Error).message;
  }
});
onUnmounted(() => {
  alive = false;
  generation++;
});
async function loadCourses() {
  const current = ++generation;
  loading.value = true;
  error.value = "";
  courseErrors.value = {};
  const picked = accounts.value.filter((a) =>
    selectedAccounts.value.includes(a.id),
  );
  const results = await Promise.allSettled(
    picked.map(async (a) =>
      (
        await request<{ items: Course[] }>(`/accounts/${a.id}/courses`)
      ).items.map((c) => ({
        ...c,
        account_id: a.id,
        account_label: a.label || a.username,
      })),
    ),
  );
  if (!alive || current !== generation) return;
  all.value = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
  results.forEach((r, i) => {
    if (r.status === "rejected")
      courseErrors.value[picked[i]!.id] =
        r.reason instanceof Error ? r.reason.message : String(r.reason);
  });
  const valid = new Set(eligible.value.map(key));
  chosen.value = chosen.value.filter((k) => valid.has(k));
  loading.value = false;
}
function next() {
  selectedAccounts.value = selectedAccounts.value.filter((id) =>
    accounts.value.some((a) => a.id === id),
  );
  if (!selectedAccounts.value.length) {
    error.value = "请至少选择一个已启用账号";
    return;
  }
  step.value = 2;
  void loadCourses();
}
function selectCourses(courses: PickCourse[]) {
  chosen.value = [
    ...new Set([...chosen.value, ...courses.filter((c) => c.if_open).map(key)]),
  ];
}
function submit() {
  if (step.value === 1) {
    next();
    return;
  }
  error.value = "";
  if (loading.value) return;
  if (!targets.value.length) {
    error.value = "请至少选择一门可学习课程";
    return;
  }
  void act(
    "create-run",
    async () => {
      await request("/runs", "POST", {
        feature: feature.value,
        targets: targets.value,
        params,
        note: note.value,
      });
      emit("close");
      navigate("tasks");
    },
    `已创建 ${targets.value.length} 项学习任务`,
  );
}
function preset(p: Settings) {
  Object.assign(params, JSON.parse(JSON.stringify(p)));
}
function back() {
  generation++;
  loading.value = false;
  error.value = "";
  step.value = 1;
}
</script>
<template>
  <ModalShell title="新建学习任务" wide @close="emit('close')">
    <form @submit.prevent="submit">
      <ol class="task-wizard-steps" aria-label="新建任务步骤">
        <li :class="{ current: step === 1, done: step === 2 }">
          <span>1</span>选择账号
        </li>
        <li :class="{ current: step === 2 }">
          <span>2</span>选择课程与学习方式
        </li>
      </ol>
      <template v-if="step === 1">
        <div class="picker-heading">
          <h3>选择要同时操作的账号</h3>
          <small>已选 {{ selectedAccounts.length }} 个账号</small>
        </div>
        <p class="muted">可多选。下一步分别展示这些账号的课程。</p>
        <div class="picker-actions">
          <button
            type="button"
            @click="selectedAccounts = accounts.map((a) => a.id)"
          >
            全选账号</button
          ><button type="button" @click="selectedAccounts = []">
            清除账号选择
          </button>
        </div>
        <div class="wizard-accounts">
          <label
            v-for="a in accounts"
            :key="a.id"
            :class="[
              'wizard-account',
              { selected: selectedAccounts.includes(a.id) },
            ]"
            ><input
              type="checkbox"
              v-model="selectedAccounts"
              :value="a.id"
              :aria-label="'选择账号 ' + (a.label || a.username)"
            /><span class="avatar">{{
              (a.label || a.username).slice(0, 1)
            }}</span
            ><span
              ><b>{{ a.label || a.username }}</b
              ><small
                >{{ a.username }} · {{ a.course_count }} 门已同步课程</small
              ></span
            ></label
          >
        </div>
        <p v-if="!accounts.length" class="alert warning">
          没有已启用账号，请在账号与课程页面添加或启用账号。
        </p>
      </template>
      <template v-else>
        <div class="picker-heading">
          <h3>选择课程</h3>
          <small
            >{{ selectedAccounts.length }} 个账号 · 已选
            {{ targets.length }} 门课程</small
          >
        </div>
        <div class="picker-actions">
          <button
            type="button"
            :disabled="loading"
            @click="selectCourses(eligible)"
          >
            全选可学习课程</button
          ><button type="button" @click="chosen = []">清除课程选择</button
          ><button type="button" :disabled="loading" @click="loadCourses">
            重新读取课程
          </button>
        </div>
        <p v-if="loading" class="muted" role="status">
          正在读取所选账号的课程…
        </p>
        <div v-else class="course-picker">
          <section v-for="g in grouped" :key="g.account.id">
            <h4>
              {{ g.account.label || g.account.username
              }}<button
                type="button"
                class="text-link"
                @click="selectCourses(g.courses)"
              >
                全选此账号课程
              </button>
            </h4>
            <p
              v-if="courseErrors[g.account.id]"
              class="alert error"
              role="alert"
            >
              课程读取失败：{{
                courseErrors[g.account.id]
              }}。可重新读取或返回调整账号。
            </p>
            <template v-else
              ><label v-for="c in g.courses" :key="key(c)" class="course-option"
                ><input
                  v-model="chosen"
                  :value="key(c)"
                  type="checkbox"
                  :disabled="!c.if_open"
                  :aria-label="'选择课程 ' + c.name"
                /><span
                  ><b>{{ c.name }}</b
                  ><small
                    >{{ c.author }} · {{ c.if_open ? "可学习" : "已关闭" }} ·
                    平台 {{ c.mission_fn }} / {{ c.mission_all }} 点</small
                  ></span
                ></label
              >
              <p v-if="!g.courses.length" class="muted">
                暂无同步课程，请先在账号页面同步。
              </p></template
            >
          </section>
        </div>
        <div class="picker-heading"><h3>学习内容</h3></div>
        <div class="feature-grid">
          <button
            type="button"
            v-for="(label, id) in features"
            :key="id"
            :class="{ selected: feature === id }"
            @click="feature = id"
          >
            {{ label }}
          </button>
        </div>
        <div class="picker-heading"><h3>学习方式</h3></div>
        <div v-if="presets.length" class="preset-list">
          <button
            type="button"
            v-for="p in presets"
            :key="p.id"
            @click="preset(p.params)"
          >
            {{ p.name }}
          </button>
        </div>
        <ParameterForm :params="params" :feature="feature" /><label
          class="field"
          >任务备注（可选）<input v-model="note"
        /></label>
        <details class="advanced">
          <summary>保存当前参数为预设</summary>
          <div class="filterbar">
            <input v-model="presetName" placeholder="预设名称" /><button
              type="button"
              :disabled="!presetName.trim()"
              @click="
                act(
                  'preset',
                  async () => {
                    await request('/presets', 'POST', {
                      name: presetName,
                      params,
                    });
                    presets = (
                      await request<{ items: typeof presets }>('/presets')
                    ).items;
                  },
                  '预设已保存',
                )
              "
            >
              保存预设
            </button>
          </div>
        </details>
      </template>
      <p v-if="error" class="alert error" role="alert">{{ error }}</p>
      <p v-if="state.error" class="alert error" role="alert">
        {{ state.error }}
      </p>
      <div class="form-actions">
        <button type="button" @click="emit('close')">取消</button
        ><button v-if="step === 2" type="button" @click="back">
          上一步：选择账号</button
        ><button
          v-if="step === 1"
          class="primary"
          :disabled="!selectedAccounts.length"
        >
          下一步：选择课程</button
        ><button
          v-else
          class="primary"
          :disabled="loading || !targets.length || state.busy.has('create-run')"
        >
          创建 {{ targets.length }} 项任务
        </button>
      </div>
    </form>
  </ModalShell>
</template>
