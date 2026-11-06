<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from "vue";
import { state, act, navigate } from "../store";
import { request } from "../api";
import { features } from "../format";
import {
  catalogKindLabel,
  catalogMeta,
  catalogStatusTone,
  collectSelection,
  isSelectable,
  selectionError,
} from "../catalog";
import type {
  CatalogItem,
  CatalogResponse,
  Course,
  SelectionParams,
  Settings,
} from "../types";
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
          no_answer_action: "skip",
          submit_delay: 2,
        },
      },
    ),
  ),
);
// 兼容旧版本保存的作答配置：只保留 AI / 手动两种方式。
if (!["ai", "manual"].includes(params.answer?.mode)) params.answer.mode = "ai";
delete params.answer?.fallback_to_tiku;
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
type CatalogState = {
  loading: boolean;
  error: string;
  items: CatalogItem[];
  selected: Set<string>;
  fromCache: boolean;
  loaded: boolean;
};
const kind = computed<"work" | "exam">(() =>
  feature.value === "exam" ? "exam" : "work",
);
const catalogKindName = computed(() => catalogKindLabel(kind.value));
const independent = computed(
  () => feature.value === "independent_homework" || feature.value === "exam",
);
const catalogs = reactive<Record<string, CatalogState>>({});
const loadedKeys = ref<Record<string, boolean>>({});
const catalogKey = (t: { account_id: string; course_id: string }) =>
  `${t.account_id}::${t.course_id}::${kind.value}`;
const currentKeys = computed(() => targets.value.map(catalogKey));
const catalogsReady = computed(
  () =>
    currentKeys.value.length > 0 &&
    currentKeys.value.every((k) => loadedKeys.value[k]),
);
const catalogBusy = computed(() => Object.values(catalogs).some((c) => c.loading));
const catalogOf = (t: { account_id: string; course_id: string }) =>
  catalogs[catalogKey(t)];
const loadingOf = (t: { account_id: string; course_id: string }) =>
  !!catalogOf(t)?.loading;
const loadedOf = (t: { account_id: string; course_id: string }) =>
  !!catalogOf(t)?.loaded;
const errorOf = (t: { account_id: string; course_id: string }) =>
  catalogOf(t)?.error || "";
const fromCacheOf = (t: { account_id: string; course_id: string }) =>
  !!catalogOf(t)?.fromCache;
const itemsOf = (t: { account_id: string; course_id: string }) =>
  catalogOf(t)?.items || [];
const selectedOf = (t: { account_id: string; course_id: string }) =>
  catalogOf(t)?.selected || new Set<string>();
const selectionStates = computed(() =>
  targets.value.map((t) => {
    const slot = catalogOf(t);
    return {
      items: slot?.items || [],
      selected: slot?.selected || new Set<string>(),
    };
  }),
);
const selection = computed<SelectionParams>(() =>
  collectSelection(selectionStates.value, catalogsReady.value),
);
const examUrl = ref("");
const examUrlMode = computed(
  () => feature.value === "exam" && examUrl.value.trim().length > 0,
);
const examUrlError = computed(() => {
  const value = examUrl.value.trim();
  if (!value || feature.value !== "exam") return "";
  if (!/chaoxing\.com/i.test(value) || !/reVersionTestStartNew/i.test(value)) {
    return "请粘贴「考试答题页」地址：在浏览器进入考试看到题目后复制地址栏 URL（需包含 reVersionTestStartNew 与 enc）";
  }
  return "";
});
const selectedCount = computed(() =>
  selectionStates.value.reduce(
    (sum, slot) =>
      sum + slot.items.filter((i) => isSelectable(i) && slot.selected.has(i.id)).length,
    0,
  ),
);
const totalCount = computed(() =>
  selectionStates.value.reduce(
    (sum, slot) => sum + slot.items.filter(isSelectable).length,
    0,
  ),
);
async function loadCatalogs() {
  if (!targets.value.length) {
    error.value = "请先勾选要处理的课程";
    return;
  }
  error.value = "";
  const targetKind = kind.value;
  await Promise.all(
    targets.value.map(async (t) => {
      const slotKey = catalogKey(t);
      // 必须通过 reactive 代理读写，直接改原始对象不会触发 UI 更新（按钮会一直显示“正在加载”）。
      if (!catalogs[slotKey])
        catalogs[slotKey] = {
          loading: false,
          error: "",
          items: [],
          selected: new Set<string>(),
          fromCache: false,
          loaded: false,
        };
      const slot = catalogs[slotKey]!;
      slot.loading = true;
      slot.error = "";
      slot.loaded = false;
      loadedKeys.value[slotKey] = false;
      try {
        const data = await request<CatalogResponse>(
          `/accounts/${t.account_id}/courses/${t.course_id}/catalog?kind=${targetKind}&refresh=false`,
        );
        slot.items = data.items || [];
        slot.fromCache = !!data.from_cache;
        slot.error = data.error || "";
        slot.selected = new Set(slot.items.filter(isSelectable).map((i) => i.id));
        slot.loaded = true;
        loadedKeys.value[slotKey] = true;
      } catch (e) {
        slot.items = [];
        slot.selected = new Set<string>();
        slot.error = e instanceof Error ? e.message : String(e);
      } finally {
        slot.loading = false;
      }
    }),
  );
}
function toggleCatalog(
  t: { account_id: string; course_id: string },
  id: string,
) {
  const slot = catalogOf(t);
  if (!slot) return;
  if (slot.selected.has(id)) slot.selected.delete(id);
  else slot.selected.add(id);
}
function toggleAllCatalogs() {
  const every = targets.value.every((t) => {
    const slot = catalogOf(t);
    if (!slot?.loaded) return false;
    return slot.items
      .filter(isSelectable)
      .every((item) => slot.selected.has(item.id));
  });
  targets.value.forEach((t) => {
    const slot = catalogOf(t);
    if (!slot) return;
    const ids = slot.items.filter(isSelectable).map((item) => item.id);
    if (every) slot.selected.clear();
    else ids.forEach((id) => slot.selected.add(id));
  });
}
// 考试说明页需要学习通登录态；把会话带到浏览器里，让用户手动完成平台安全验证。
const openingExam = reactive<Record<string, boolean>>({});
const examOpeningKey = (
  t: { account_id: string; course_id: string },
  item: CatalogItem,
) => `${catalogKey(t)}::${item.id}`;
const isExamOpening = (
  t: { account_id: string; course_id: string },
  item: CatalogItem,
) => !!openingExam[examOpeningKey(t, item)];
function examNotesUrl(
  t: { course_id: string; class_id?: string; cpi?: string },
  item: CatalogItem,
) {
  const query = new URLSearchParams({
    courseId: t.course_id,
    classId: t.class_id || "",
    examId: String(item.id),
    cpi: t.cpi || "",
  });
  return `https://mooc1.chaoxing.com/exam/test/examcode/examnotes?${query.toString()}`;
}
async function openExamInBrowser(
  t: { account_id: string; course_id: string; class_id?: string; cpi?: string },
  item: CatalogItem,
) {
  const openingId = examOpeningKey(t, item);
  if (openingExam[openingId]) return;
  openingExam[openingId] = true;
  try {
    await request(`/accounts/${t.account_id}/open-chaoxing`, "POST", {
      url: examNotesUrl(t, item),
    });
    state.toast = "已用浏览器打开考试说明页，请先完成平台安全验证";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    openingExam[openingId] = false;
  }
}
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
  if (feature.value === "exam" && examUrl.value.trim() && examUrlError.value) {
    error.value = examUrlError.value;
    return;
  }
  if (independent.value) {
    const invalid = selectionError(kind.value, selection.value, catalogsReady.value);
    if (invalid && !examUrlMode.value) {
      error.value = invalid;
      return;
    }
  }
  const finalParams = JSON.parse(JSON.stringify(params));
  if (independent.value) finalParams.selection = selection.value;
  else delete finalParams.selection;
  if (examUrlMode.value) finalParams.exam = { url: examUrl.value.trim() };
  else delete finalParams.exam;
  void act(
    "create-run",
    async () => {
      await request("/runs", "POST", {
        feature: feature.value,
        targets: targets.value,
        params: finalParams,
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
    <form class="wizard" @submit.prevent="submit">
      <ol class="task-wizard-steps" aria-label="新建任务步骤">
        <li :class="{ current: step === 1, done: step === 2 }">
          <span>1</span>选择账号
        </li>
        <li :class="{ current: step === 2 }">
          <span>2</span>选择课程与学习方式
        </li>
      </ol>
      <div class="wizard-body">
        <template v-if="step === 1">
          <div class="picker-heading">
            <h3>选择要同时操作的账号</h3>
            <small>已选 {{ selectedAccounts.length }} 个账号</small>
          </div>
          <p class="muted">可多选。下一步分别展示这些账号的课程。</p>
          <div class="picker-actions">
            <button
              type="button"
              class="small"
              @click="selectedAccounts = accounts.map((a) => a.id)"
            >
              全选账号</button
            ><button
              type="button"
              class="small"
              @click="selectedAccounts = []"
            >
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
              class="small"
              :disabled="loading"
              @click="selectCourses(eligible)"
            >
              全选可学习课程</button
            ><button
              type="button"
              class="small"
              @click="chosen = []"
            >
              清除课程选择</button
            ><button
              type="button"
              class="small"
              :disabled="loading"
              @click="loadCourses"
            >
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
              <template v-else>
                <label v-for="c in g.courses" :key="key(c)" class="course-option">
                  <input
                    v-model="chosen"
                    :value="key(c)"
                    type="checkbox"
                    :disabled="!c.if_open"
                    :aria-label="'选择课程 ' + c.name"
                  />
                  <span>
                    <b>{{ c.name }}</b>
                    <small>
                      <span class="course-author">{{ c.author || "课程" }}</span>
                      <span :class="['course-open', c.if_open ? 'ok' : 'off']">{{
                        c.if_open ? "可学习" : "已关闭"
                      }}</span>
                      <span class="num"
                        >平台 {{ c.mission_fn }} / {{ c.mission_all }} 点</span
                      >
                    </small>
                  </span>
                </label>
                <p v-if="!g.courses.length" class="muted">
                  暂无同步课程，请先在账号页面同步。
                </p>
              </template>
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
          <template v-if="independent">
            <div v-if="kind === 'exam'" class="exam-url-block">
              <div class="picker-heading">
                <h3>考试答题页地址（推荐）</h3>
              </div>
              <p class="muted">
                先在浏览器里登录学习通并进入考试，看到题目后复制地址栏 URL
                粘贴到这里：程序会直接在这场考试里逐题作答并交卷。留空则按下方考试列表处理。
                程序不会绕过平台的任何安全验证，考试计时以平台为准。
              </p>
              <input
                v-model="examUrl"
                type="url"
                class="exam-url-input"
                placeholder="https://mooc1.chaoxing.com/exam-ans/exam/test/reVersionTestStartNew?...&enc=..."
                aria-label="考试答题页地址"
                spellcheck="false"
              />
              <p v-if="examUrlError" class="alert error" role="alert">
                {{ examUrlError }}
              </p>
              <p class="muted">
                地址里通常带有 enc 参数；复制完整地址（路径含 reVersionTestStartNew
                的那一条）才能让程序直接进入答题页。
              </p>
            </div>
            <div class="picker-heading">
              <h3>选择{{ catalogKindName }}范围</h3>
              <small v-if="catalogsReady"
                >已选 {{ selectedCount }} / {{ totalCount }} 项</small
              >
            </div>
            <p class="muted">
              先加载所选课程下的待做{{ catalogKindName }}再勾选，默认全选；不加载时按「全部待做」执行。
            </p>
            <div class="picker-actions">
              <button
                type="button"
                class="small"
                :disabled="loading || catalogBusy || !targets.length"
                :aria-label="'加载' + catalogKindName + '列表'"
                @click="loadCatalogs"
              >
                {{
                  catalogBusy
                    ? "正在加载…"
                    : catalogsReady
                      ? "重新加载列表"
                      : "加载列表"
                }}
              </button>
              <button
                type="button"
                class="small"
                :disabled="!catalogsReady || catalogBusy"
                :aria-label="'全选' + catalogKindName"
                @click="toggleAllCatalogs"
              >
                全选 / 取消全选
              </button>
            </div>
            <p v-if="!targets.length" class="muted">
              请先勾选课程，再加载{{ catalogKindName }}列表。
            </p>
            <div v-else class="catalog-list">
              <section
                v-for="t in targets"
                :key="catalogKey(t)"
                class="catalog-group"
              >
                <h4>
                  {{ t.course_name
                  }}<small v-if="fromCacheOf(t)">来自平台缓存</small>
                </h4>
                <p v-if="loadingOf(t)" class="muted" role="status">
                  正在加载{{ catalogKindName }}列表…
                </p>
                <template v-else-if="loadedOf(t)">
                  <p v-if="errorOf(t)" class="alert warning" role="alert">
                    {{ errorOf(t)
                    }}<button
                      type="button"
                      class="text-link"
                      :aria-label="'重试加载' + catalogKindName + '列表'"
                      @click="loadCatalogs"
                    >
                      重试
                    </button>
                  </p>
                  <p v-if="!itemsOf(t).length" class="muted">
                    该课程没有待做的{{ catalogKindName }}。
                  </p>
                  <template v-else>
                    <label
                      v-for="item in itemsOf(t)"
                      :key="item.id"
                      :class="['catalog-item', { done: !isSelectable(item) }]"
                    >
                      <input
                        type="checkbox"
                        :checked="selectedOf(t).has(item.id)"
                        :disabled="!isSelectable(item)"
                        :aria-label="'选择' + catalogKindName + ' ' + item.title"
                        @change="toggleCatalog(t, item.id)"
                      />
                      <span class="catalog-item-body">
                        <b>{{ item.title }}</b>
                        <small>
                          <span
                            :class="[
                              'catalog-status',
                              catalogStatusTone(item.status),
                            ]"
                            >{{ item.status || "状态未知" }}</span
                          >
                          <span
                            v-for="part in catalogMeta(kind, item)"
                            :key="part"
                            >{{ part }}</span
                          >
                        </small>
                        <span
                          v-if="kind === 'exam' && isSelectable(item)"
                          class="catalog-note"
                          ><small
                            >进入前可能需要平台安全验证，可先在浏览器中完成验证。</small
                          ><button
                            type="button"
                            class="text-link"
                            :disabled="isExamOpening(t, item)"
                            aria-label="在浏览器中打开考试"
                            @click.stop.prevent="openExamInBrowser(t, item)"
                          >
                            {{
                              isExamOpening(t, item)
                                ? "正在打开…"
                                : "在浏览器中打开"
                            }}
                          </button></span
                        >
                      </span>
                    </label>
                  </template>
                </template>
                <p v-else class="muted">
                  点击「加载列表」查看待做{{ catalogKindName }}。
                </p>
              </section>
            </div>
          </template>
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
          <div class="param-block">
            <ParameterForm :params="params" :feature="feature" />
          </div>
          <label class="field note-field"
            >任务备注（可选）<input v-model="note" /></label
          >
          <details class="advanced">
            <summary>保存当前参数为预设</summary>
            <div class="filterbar">
              <input v-model="presetName" placeholder="预设名称" /><button
                type="button"
                class="small"
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
      </div>
      <p v-if="error" class="alert error" role="alert">{{ error }}</p>
      <p v-if="state.error" class="alert error" role="alert">
        {{ state.error }}
      </p>
      <div class="wizard-foot">
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

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-wizard-steps {
  display: flex;
  gap: 1px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--line);
  overflow: hidden;
  list-style: none;
  margin: 0;
  padding: 0;
}

.task-wizard-steps li {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  background: var(--surface);
  font-size: 12px;
  color: var(--faint);
}

.task-wizard-steps li span {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid var(--line2);
  border-radius: 50%;
  font-family: var(--font-num);
  font-size: 10px;
  color: var(--faint);
}

.task-wizard-steps li.current {
  background: var(--navy-soft);
  color: var(--navy);
  font-weight: 600;
}

.task-wizard-steps li.current span {
  border-color: var(--navy);
  background: var(--navy);
  color: #fff;
}

.task-wizard-steps li.done {
  color: var(--ink2);
}

.task-wizard-steps li.done span {
  border-color: var(--ok);
  color: var(--ok);
}

.wizard-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.picker-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 6px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.wizard-body > .picker-heading:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}

.picker-heading h3 {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.picker-heading small {
  font-family: var(--font-num);
  font-size: 10.5px;
  color: var(--faint);
}

.picker-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.wizard-accounts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.wizard-account {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface);
  cursor: pointer;
}

.wizard-account:hover {
  border-color: var(--line2);
  background: var(--surface2);
}

.wizard-account.selected {
  border-color: var(--navy2);
  background: var(--navy-soft);
}

.wizard-account > span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.wizard-account b {
  font-size: 12.5px;
  line-height: 1.4;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wizard-account small {
  font-size: 11px;
  line-height: 1.5;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-picker {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.course-picker section {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px 10px;
  align-items: start;
}

.course-picker section > h4,
.course-picker section > .alert {
  grid-column: 1 / -1;
}

.course-picker h4 {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink2);
}

.course-picker h4 .text-link {
  font-size: 10.5px;
  font-weight: 400;
}

.course-option {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface);
  cursor: pointer;
}

.course-option:hover:not(:has(input:disabled)) {
  border-color: var(--line2);
  background: var(--surface2);
}

.course-option:has(input:checked) {
  border-color: var(--navy2);
  background: var(--navy-soft);
}

.course-option:has(input:disabled) {
  opacity: 0.55;
  cursor: not-allowed;
}

.course-option > span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.course-option b {
  font-size: 12px;
  line-height: 1.4;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-option small {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--mute);
}

.course-open.ok {
  color: var(--ok);
}

.course-open.off {
  color: var(--faint);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.feature-grid button {
  height: 32px;
  justify-content: center;
  border-color: var(--line);
  background: var(--surface);
  font-size: 12px;
  color: var(--ink2);
}

.feature-grid button.selected {
  border-color: var(--navy);
  background: var(--navy);
  color: #fff;
}

.feature-grid button.selected:hover:not(:disabled) {
  border-color: var(--navy2);
  background: var(--navy2);
}

.exam-url-block {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-left: 2px solid var(--info);
  border-radius: var(--r2);
  background: var(--surface2);
}

.exam-url-block .exam-url-input {
  width: 100%;
  box-sizing: border-box;
  font-family: var(--font-mono);
  font-size: 11px;
}

.exam-url-block .alert {
  margin: 0;
}

.catalog-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.catalog-group {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface2);
}

.catalog-group h4 {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
  font-weight: 600;
}

.catalog-group h4 small {
  font-size: 10.5px;
  font-weight: 400;
  color: var(--faint);
}

.catalog-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r1);
  background: var(--surface);
  cursor: pointer;
}

.catalog-item:has(input:checked) {
  border-color: var(--navy2);
}

.catalog-item.done {
  opacity: 0.6;
  cursor: not-allowed;
}

.catalog-item-body {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.catalog-item-body b {
  font-size: 12px;
  line-height: 1.4;
  font-weight: 500;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-item-body small {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--mute);
}

.catalog-status {
  color: var(--ink2);
}

.catalog-status.done {
  color: var(--ok);
}

.catalog-status.warn {
  color: var(--warn);
}

.catalog-status.idle {
  color: var(--faint);
}

.catalog-note {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--warn);
}

.catalog-note .text-link {
  font-size: 10px;
}

.preset-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset-list button {
  height: 28px;
  padding: 0 11px;
  font-size: 11.5px;
  border-radius: var(--r-pill);
}

.param-block {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r2);
  background: var(--surface2);
}

.note-field {
  max-width: 320px;
}

.wizard-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  margin-bottom: -16px;
  padding-top: 12px;
  padding-bottom: 16px;
  border-top: 1px solid var(--line);
  position: sticky;
  bottom: -16px;
  background: var(--surface);
}

.wizard-foot > :first-child {
  margin-right: auto;
}

@media (max-width: 760px) {
  .wizard-accounts {
    grid-template-columns: minmax(0, 1fr);
  }

  .feature-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
