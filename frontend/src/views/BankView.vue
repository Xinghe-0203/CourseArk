<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import {
  Search,
  Upload,
  Download,
  Trash2,
  Eraser,
  RefreshCw,
} from "lucide-vue-next";
import { request } from "../api";
import { act, state } from "../store";
import type { BankItem, BankStats, Settings } from "../types";
import ModalShell from "../components/ModalShell.vue";
import EmptyState from "../components/EmptyState.vue";
import Pagination from "../components/Pagination.vue";
const items = ref<BankItem[]>([]),
  total = ref(0),
  query = ref(""),
  type = ref(""),
  offset = ref(0),
  error = ref(""),
  loading = ref(false),
  show = ref(false),
  content = ref(""),
  format = ref("json"),
  preview = ref<Settings | null>(null),
  overwrite = ref(false),
  remove = ref<BankItem | null>(null),
  clearing = ref(false),
  files = ref<File[]>([]),
  sourcePath = ref("");
/** T7.6：/api/question-bank/stats 聚合卡（tab 激活即拉取，容忍 0/失败）。 */
const stats = ref<BankStats | null>(null);
const hitRate = computed(() => {
  const value = stats.value?.hit_rate;
  // 后端 hit_rate = hits / lookups；lookups 为 0 时它必然算出 0%，
  // 直接显示 0% 会让人误以为「缓存完全没用」，所以这里显示占位符。
  if (!stats.value?.lookups) return "—";
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
});
const questionTypes = ["单选题", "多选题", "判断题", "填空题", "简答题"];
let generation = 0,
  debounce: ReturnType<typeof setTimeout>;
async function load() {
  const current = ++generation;
  loading.value = true;
  try {
    const data = await request<{ items: BankItem[]; total: number }>(
      `/question-bank/search?q=${encodeURIComponent(query.value)}&question_type=${encodeURIComponent(type.value)}&offset=${offset.value}`,
    );
    if (current !== generation) return;
    if (offset.value && offset.value >= data.total) {
      offset.value = Math.max(0, Math.floor((data.total - 1) / 50) * 50);
      return;
    }
    items.value = data.items;
    total.value = data.total;
    error.value = "";
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function loadStats() {
  try {
    stats.value = await request<BankStats>("/question-bank/stats?days=30");
  } catch {
    stats.value = null;
  }
}
onMounted(() => {
  load();
  loadStats();
});
watch([query, type], () => {
  offset.value = 0;
  clearTimeout(debounce);
  debounce = setTimeout(load, 250);
});
watch(offset, load);
onUnmounted(() => {
  generation++;
  clearTimeout(debounce);
});
watch(
  [content, format, overwrite, files, sourcePath],
  () => (preview.value = null),
);
async function importBank(previewOnly: boolean) {
  const payload = { overwrite: overwrite.value, preview_only: previewOnly };
  let result: Settings;
  if (
    files.value.length &&
    files.value[0]!.name.toLowerCase().endsWith(".db")
  ) {
    const form = new FormData();
    // 后端 multipart 字段名为 file；同时选中 -wal / -shm 侧车文件时逐个上传。
    files.value.forEach((f) => form.append("file", f));
    form.append("preview_only", String(previewOnly));
    form.append("overwrite", String(overwrite.value));
    const response = await fetch("/api/question-bank/import-db", {
      method: "POST",
      body: form,
    });
    result = await response.json();
    if (!response.ok) throw new Error(result.detail || "缓存导入失败");
  } else if (sourcePath.value) {
    result = await request("/question-bank/import-db", "POST", {
      path: sourcePath.value,
      ...payload,
    });
  } else {
    result = await request("/question-bank/import", "POST", {
      content: content.value,
      format: format.value,
      ...payload,
    });
  }
  if (previewOnly) preview.value = result;
  else {
    show.value = false;
    offset.value = 0;
    await load();
  }
}
async function selected(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || []);
  if (files.value[0] && !files.value[0].name.toLowerCase().endsWith(".db")) {
    format.value = files.value[0].name.toLowerCase().endsWith(".csv")
      ? "csv"
      : "json";
    content.value = await files.value[0].text();
  }
}
function clearBank() {
  act(
    "clear-bank",
    async () => {
      const result = await request<{ deleted: number }>(
        "/question-bank",
        "DELETE",
      );
      clearing.value = false;
      offset.value = 0;
      await load();
      loadStats();
      return result;
    },
    (result) => `已清空 ${(result as { deleted?: number }).deleted || 0} 条答题缓存`,
  );
}
</script>
<template>
  <div class="bank">
    <div class="section-heading">
      <div>
        <h2>缓存题目</h2>
        <p class="muted">
          共 <b class="num">{{ total }}</b> 条缓存 · 命中后不再重复调用 AI
        </p>
      </div>
      <div class="button-row">
        <button
          class="icon-button"
          aria-label="刷新缓存"
          title="刷新缓存"
          @click="
            load();
            loadStats();
          "
        >
          <RefreshCw :size="14" :class="{ spin: loading }" /></button
        ><a class="button" href="/api/question-bank/export?format=json" download
          ><Download :size="13" />导出 JSON</a
        ><a class="button" href="/api/question-bank/export?format=csv" download
          ><Download :size="13" />导出 CSV</a
        ><button class="primary" @click="show = true">
          <Upload :size="13" />导入缓存</button
        ><button
          class="danger"
          :disabled="!total || state.busy.has('clear-bank')"
          @click="clearing = true"
        >
          <Eraser :size="13" />清空全部
        </button>
      </div>
    </div>
    <div v-if="stats" class="bank-stats">
      <div>
        <span>缓存题目</span
        ><strong class="num">{{ stats.total }}<small>条</small></strong
        ><em>近 30 天新增 {{ stats.recent_count }}</em>
      </div>
      <div>
        <span>命中次数</span
        ><strong class="num">{{ stats.hits }}<small>次</small></strong
        ><em>命中缓存、未调用 AI</em>
      </div>
      <div>
        <span>命中率</span><strong class="num">{{ hitRate }}</strong
        ><em>{{
          stats.lookups
            ? `命中 ${stats.hits} / 查询 ${stats.lookups}`
            : "还没有查询记录"
        }}</em>
      </div>
    </div>
    <div class="filterbar">
      <label class="search"
        ><Search :size="14" /><input
          v-model="query"
          placeholder="搜索题干内容"
          aria-label="搜索答题缓存" /></label
      ><select v-model="type" aria-label="题型筛选">
        <option value="">所有题型</option>
        <option v-for="t in questionTypes" :key="t" :value="t">{{ t }}</option>
      </select>
    </div>
    <p v-if="error" class="alert error" role="alert">{{ error }}</p>
    <div class="bank-list">
      <article v-for="item in items" :key="item.hash" class="bank-item">
        <span class="tag">{{ item.question_type || "未分类" }}</span>
        <div class="bank-main">
          <p class="bank-question">{{ item.question_text }}</p>
          <details v-if="item.options?.length">
            <summary>查看选项</summary>
            <p v-for="(opt, i) in item.options" :key="i">{{ opt }}</p>
          </details>
        </div>
        <p class="bank-answer">{{ item.answer }}</p>
        <button
          class="icon-button"
          aria-label="删除缓存"
          title="删除这条缓存"
          @click="remove = item"
        >
          <Trash2 :size="14" />
        </button>
      </article>
      <EmptyState
        v-if="!items.length && !loading"
        :title="query || type ? '没有匹配的答题缓存' : '答题缓存是空的'"
        :description="
          query || type
            ? '换个关键词，或清空筛选条件后再试。'
            : '开启「自动保存已验证的答案」后，AI 答对的题目会自动记在这里；也可以导入 JSON / CSV / SQLite 缓存。'
        "
      >
        <template #icon>
          <svg
            viewBox="0 0 96 96"
            fill="none"
            aria-hidden="true"
            style="width: 40px; height: 40px"
          >            <ellipse
              cx="48"
              cy="36"
              rx="26"
              ry="10"
              fill="var(--surface)"
              stroke="var(--fg-subtle)"
              stroke-width="2"
            />
            <path
              d="M22 36v22c0 5.5 11.6 10 26 10s26-4.5 26-10V36"
              stroke="var(--fg-subtle)"
              stroke-width="2"
              fill="var(--surface)"
            />
            <path
              d="M22 47c0 5.5 11.6 10 26 10s26-4.5 26-10"
              stroke="var(--fg-subtle)"
              stroke-width="2"
            />
            <path
              d="M62 68l6 6 12-13"
              stroke="var(--ok)"
              stroke-width="3.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </template>
        <template #actions>
          <button v-if="query || type" @click="query = ''; type = ''">
            清空筛选条件
          </button>
          <button v-else class="primary" @click="show = true">
            <Upload :size="14" />导入缓存
          </button>
        </template>
      </EmptyState>
    </div>
    <Pagination
      v-if="total"
      :offset="offset"
      :page-size="50"
      :total="total"
      @update:offset="offset = $event"
    />
    <ModalShell v-if="show" title="导入答题缓存" wide @close="show = false"
      ><p class="muted">
        支持 JSON、CSV 与 SQLite 缓存。SQLite 可一并选择对应的 -wal / -shm
        文件；导入前先预览，不影响已有缓存。
      </p>
      <label class="field"
        >选择文件<input
          type="file"
          multiple
          accept=".json,.csv,.db,.db-wal,.db-shm"
          @change="selected" /></label
      ><label class="field"
        >或填写服务器本地缓存路径<input
          v-model="sourcePath"
          placeholder="留空使用下方内容" /></label
      ><template
        v-if="
          !sourcePath &&
          (!files.length || !files[0]!.name.toLowerCase().endsWith('.db'))
        "
        ><label class="field"
          >内容格式<select v-model="format">
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select></label
        ><label class="field"
          >缓存内容<textarea
            v-model="content"
            rows="8"
            placeholder='[{"question_text":"题目","answer":"A","options":["A.甲","B.乙"]}]'
          /></label></template
      ><label class="check"
        ><input
          v-model="overwrite"
          type="checkbox"
        />覆盖缓存中已存在的相同题目</label
      >
      <div v-if="preview" class="import-preview">
        <b
          >已识别 {{ preview.parsed || 0 }} 道题 · 新增 {{ preview.new || 0 }} ·
          重复 {{ preview.duplicate || 0 }}</b
        >
        <p v-if="preview.error_count">
          {{ preview.error_count }} 项内容有问题，导入时会跳过。
        </p>
        <p v-for="(e, i) in preview.errors" :key="i">{{ e }}</p>
      </div>
      <div class="form-actions">
        <button
          :disabled="state.busy.has('import-bank')"
          @click="act('import-bank', () => importBank(true), '预览已生成')"
        >
          检查并预览</button
        ><button
          class="primary"
          :disabled="!preview?.parsed || state.busy.has('import-bank')"
          @click="act('import-bank', () => importBank(false), '缓存已导入')"
        >
          确认导入
        </button>
      </div></ModalShell
    ><ModalShell v-if="remove" title="删除这条缓存" @close="remove = null"
      ><p>{{ remove.question_text }}</p>
      <p class="muted">删除后该题再次遇到时会重新调用 AI。</p>
      <div class="form-actions">
        <button @click="remove = null">取消</button
        ><button
          class="danger"
          :disabled="state.busy.has('delete-question')"
          @click="
            act(
              'delete-question',
              async () => {
                await request('/question-bank/' + remove!.hash, 'DELETE');
                remove = null;
                await load();
                loadStats();
              },
              '缓存已删除',
            )
          "
        >
          删除缓存
        </button>
      </div></ModalShell
    ><ModalShell v-if="clearing" title="清空全部答题缓存" @close="clearing = false"
      ><p>
        即将删除全部
        <b>{{ stats?.total ?? total }}</b> 条答题缓存，删除后无法恢复。
      </p>
      <p class="muted">
        建议先导出备份。已有任务的历史记录不受影响，但之后的相同题目会重新调用
        AI。
      </p>
      <div class="form-actions">
        <button @click="clearing = false">取消</button
        ><button
          class="danger"
          :disabled="state.busy.has('clear-bank')"
          @click="clearBank"
        >
          {{ state.busy.has("clear-bank") ? "正在清空…" : "确认清空全部" }}
        </button>
      </div></ModalShell
    >
  </div>
</template>

<style scoped>
.bank {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-heading {
  align-items: flex-start;
}

.section-heading h2 {
  font-size: 14px;
  font-weight: 600;
}

.section-heading p {
  margin-top: 2px;
  font-size: 11.5px;
}

.bank-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--line);
  overflow: hidden;
}

.bank-stats > div {
  display: grid;
  grid-template-columns: auto auto;
  align-items: baseline;
  gap: 6px 10px;
  padding: 13px 14px;
  background: var(--surface);
}

.bank-stats span {
  grid-column: 1 / -1;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--faint);
}

.bank-stats strong {
  font-family: var(--font-num);
  font-size: 19px;
  font-weight: 500;
  line-height: 1.1;
}

.bank-stats strong small {
  margin-left: 2px;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--faint);
}

.bank-stats em {
  font-size: 10.5px;
  font-style: normal;
  color: var(--mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bank-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.bank-list:empty {
  display: none;
}

/* 空态用完整插画而不是单色图标：放开 EmptyState 的 44px 软圆底，按原尺寸展示 */
.bank-list :deep(.empty-icon) {
  width: auto;
  height: auto;
  background: transparent;
}

.bank-item {
  display: grid;
  grid-template-columns: 62px minmax(0, 1fr) minmax(0, 190px) 28px;
  align-items: start;
  gap: 14px;
  padding: 13px 14px;
  border-bottom: 1px solid var(--line);
}

.bank-item:last-child {
  border-bottom: 0;
}

.bank-item:hover {
  background: var(--surface2);
}

.bank-item .tag {
  justify-self: start;
  margin-top: 1px;
}

.bank-main {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.bank-question {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink);
}

.bank-main details {
  font-size: 11px;
  color: var(--mute);
}

.bank-main details p {
  margin: 1px 0 0;
}

.bank-answer {
  justify-self: start;
  max-width: 100%;
  margin: 0;
  padding: 3px 8px;
  border-radius: var(--r1);
  background: var(--ok-soft);
  font-family: var(--font-body);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ok);
  overflow-wrap: anywhere;
}

.bank-item .icon-button {
  width: 26px;
  height: 26px;
}

.empty {
  border: 0;
  border-radius: 0;
  padding: 28px 16px;
}

@media (max-width: 1080px) {
  .bank-stats {
    grid-template-columns: minmax(0, 1fr);
  }

  .bank-item {
    grid-template-columns: 58px minmax(0, 1fr) 26px;
  }

  .bank-answer {
    grid-column: 2;
  }

  .bank-item .icon-button {
    grid-row: 1;
    grid-column: 3;
  }
}
</style>
