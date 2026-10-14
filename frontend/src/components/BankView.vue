<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from "vue";
import { Search, Upload, Download, Trash2, Database } from "lucide-vue-next";
import { request } from "../api";
import { act, state } from "../store";
import type { BankItem, Settings } from "../types";
import ModalShell from "./ModalShell.vue";
const items = ref<BankItem[]>([]),
  total = ref(0),
  query = ref(""),
  type = ref(""),
  offset = ref(0),
  error = ref(""),
  show = ref(false),
  content = ref(""),
  format = ref("json"),
  preview = ref<Settings | null>(null),
  overwrite = ref(false),
  remove = ref<BankItem | null>(null),
  files = ref<File[]>([]),
  sourcePath = ref("");
let generation = 0;
async function load() {
  const current = ++generation;
  try {
    const data = await request<{ items: BankItem[]; total: number }>(
      `/question-bank/search?q=${encodeURIComponent(query.value)}&question_type=${encodeURIComponent(type.value)}&offset=${offset.value}`,
    );
    if (current === generation) {
      if (offset.value && offset.value >= data.total) {
        offset.value = Math.max(0, Math.floor((data.total - 1) / 50) * 50);
        return;
      }
      items.value = data.items;
      total.value = data.total;
    }
  } catch (e) {
    error.value = (e as Error).message;
  }
}
onMounted(load);
let debounce: ReturnType<typeof setTimeout>;
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
    files.value.forEach((f) => form.append("files", f));
    form.append("preview_only", String(previewOnly));
    form.append("overwrite", String(overwrite.value));
    const response = await fetch("/api/question-bank/import-db", {
      method: "POST",
      body: form,
    });
    result = await response.json();
    if (!response.ok) throw new Error(result.detail || "题库导入失败");
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
</script>
<template>
  <div class="section-heading">
    <p class="muted">共 {{ total }} 道题目</p>
    <div class="button-row">
      <a class="button" href="/api/question-bank/export?format=json" download
        ><Download :size="16" />导出题库</a
      ><button class="primary" @click="show = true">
        <Upload :size="16" />导入题库
      </button>
    </div>
  </div>
  <div class="filterbar">
    <label class="search"
      ><Search :size="17" /><input
        v-model="query"
        placeholder="搜索题目内容"
        aria-label="搜索题库" /></label
    ><select v-model="type" aria-label="题型筛选">
      <option value="">所有题型</option>
      <option v-for="t in ['单选题', '多选题', '判断题', '填空题', '简答题']">
        {{ t }}
      </option>
    </select>
  </div>
  <p v-if="error" class="alert error">{{ error }}</p>
  <div class="bank-list">
    <article v-for="item in items" :key="item.hash" class="bank-item">
      <span class="tag">{{ item.question_type || "未分类" }}</span>
      <div>
        <h3>{{ item.question_text }}</h3>
        <details v-if="item.options?.length">
          <summary>查看选项</summary>
          <p v-for="opt in item.options">{{ opt }}</p>
        </details>
        <p class="bank-answer">
          答案 <b>{{ item.answer }}</b>
        </p>
      </div>
      <button class="icon-button" aria-label="删除题目" @click="remove = item">
        <Trash2 :size="16" />
      </button>
    </article>
    <div v-if="!items.length" class="empty">
      <Database :size="30" />
      <h3>暂无题目</h3>
      <p>可导入已有题库，或调整搜索条件。</p>
    </div>
  </div>
  <div class="pagination">
    <button :disabled="!offset" @click="offset = Math.max(0, offset - 50)">
      上一页</button
    ><span
      >{{ offset + 1 }}—{{ Math.min(offset + 50, total) }} / {{ total }}</span
    ><button :disabled="offset + 50 >= total" @click="offset += 50">
      下一页
    </button>
  </div>
  <ModalShell v-if="show" title="导入题库" wide @close="show = false"
    ><p class="muted">
      支持 JSON、CSV 与 SQLite 题库。SQLite 可一并选择对应的 -wal / -shm 文件。
    </p>
    <label class="field"
      >选择文件<input
        type="file"
        multiple
        accept=".json,.csv,.db,.db-wal,.db-shm"
        @change="selected" /></label
    ><label class="field"
      >或填写服务器本地题库路径<input
        v-model="sourcePath"
        placeholder="留空使用下方内容" /></label
    ><template
      v-if="!sourcePath && (!files.length || !files[0]!.name.endsWith('.db'))"
      ><label class="field"
        >内容格式<select v-model="format">
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select></label
      ><label class="field"
        >题库内容<textarea
          v-model="content"
          rows="8"
          placeholder='[{"question_text":"题目","answer":"A","options":["A.甲","B.乙"]}]'
        /></label></template
    ><label class="check"
      ><input
        v-model="overwrite"
        type="checkbox"
      />更新题库中已有的重复题目</label
    >
    <div v-if="preview" class="import-preview">
      <b
        >已识别 {{ preview.parsed || 0 }} 道题 · 新增 {{ preview.new || 0 }} ·
        重复 {{ preview.duplicate || 0 }}</b
      >
      <p v-if="preview.error_count">
        {{ preview.error_count }} 项内容有问题，导入时会跳过。
      </p>
      <p v-for="e in preview.errors">{{ e }}</p>
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
        @click="act('import-bank', () => importBank(false), '题库已导入')"
      >
        确认导入
      </button>
    </div></ModalShell
  ><ModalShell v-if="remove" title="删除题目" @close="remove = null"
    ><p>{{ remove.question_text }}</p>
    <div class="form-actions">
      <button @click="remove = null">取消</button
      ><button
        class="danger"
        @click="
          act(
            'delete-question',
            async () => {
              await request('/question-bank/' + remove!.hash, 'DELETE');
              remove = null;
              await load();
            },
            '题目已删除',
          )
        "
      >
        删除题目
      </button>
    </div></ModalShell
  >
</template>
