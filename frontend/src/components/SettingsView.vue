<script setup lang="ts">
import { reactive, ref } from "vue";
import { Save, Download } from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import type { Settings } from "../types";
import ParameterForm from "./ParameterForm.vue";
const form = reactive<Settings>(JSON.parse(JSON.stringify(state.settings))),
  tab = ref("learning");
const labels: Record<string, string> = {
  "scheduler.max_active_workers": "同时执行的任务数",
  "scheduler.stop_grace_seconds": "停止任务的等待时间（秒）",
  "llm.base_url": "AI 接口地址",
  "llm.api_key": "API Key",
  "llm.model": "模型名称",
  "llm.temperature": "回答随机程度",
  "llm.max_tokens": "最大输出长度",
  "llm.timeout": "响应等待时间（秒）",
  "tiku.enabled": "启用在线题库",
  "tiku.timeout": "题库等待时间（秒）",
  "tiku.order": "题库查询顺序（逗号分隔）",
  "tiku.enncy-token": "Enncy Token",
  "tiku.icodef-token": "ICodef Token",
  "tiku.datam-token": "Datam Token",
  "question_bank.enabled": "启用本地题库",
  "question_bank.auto_save": "保存已验证的答案",
  "advanced.request_delay": "请求间隔（秒）",
  "advanced.request_delay_jitter": "随机间隔（秒）",
  "advanced.max_retries": "失败重试次数",
  "advanced.retry_delay": "重试间隔（秒）",
  "advanced.rotate_ua": "轮换浏览器标识",
  "advanced.log_level": "诊断记录级别",
  "server.port": "本机服务端口",
  "storage.log_retention_days": "日志保留天数",
};
const groups: Record<string, string[]> = {
  ai: ["llm"],
  bank: ["tiku", "question_bank"],
  advanced: ["scheduler", "advanced", "server", "storage"],
};
function get(path: string): any {
  return path.split(".").reduce((v, k) => v?.[k], form as Settings);
}
function set(path: string, value: unknown) {
  const keys = path.split(".");
  const last = keys.pop()!;
  let node = form;
  for (const key of keys) {
    node[key] ??= {};
    node = node[key];
  }
  node[last] = value;
}
function secret(path: string) {
  return /api_key|token|sendkey|bark.key/.test(path);
}
function hasSecret(path: string) {
  return form.secrets?.[path.replace(/[.-]/g, "_") + "_configured"];
}
function update(event: Event, path: string) {
  const input = event.target as HTMLInputElement;
  if (input.type === "checkbox") set(path, input.checked);
  else if (input.type === "number")
    set(path, input.value === "" ? "" : Number(input.value));
  else if (path === "tiku.order")
    set(
      path,
      input.value
        .split(/[,，]/)
        .map((x) => x.trim())
        .filter(Boolean),
    );
  else set(path, input.value);
}
function fields() {
  return Object.keys(labels).filter((p) =>
    groups[tab.value]?.includes(p.split(".")[0]!),
  );
}
function save() {
  act(
    "settings",
    async () => {
      const data = JSON.parse(JSON.stringify(form));
      for (const path of Object.keys(labels).filter(secret)) {
        if (!get(path)) {
          const keys = path.split("."),
            last = keys.pop()!;
          let node = data;
          for (const key of keys) node = node[key];
          delete node[last];
        }
      }
      await request("/settings", "PATCH", data);
      state.settings = await request("/settings");
      Object.assign(form, JSON.parse(JSON.stringify(state.settings)));
    },
    "设置已保存，后续创建的任务将使用新配置",
  );
}
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  await act(
    "settings-import",
    async () => {
      await request("/settings/import", "POST", { content: await file.text() });
      state.settings = await request("/settings");
      Object.assign(form, JSON.parse(JSON.stringify(state.settings)));
    },
    "设置已导入",
  );
}
function importSource() {
  act(
    "import-source",
    async () => {
      await request("/settings/import-source", "POST", { only_empty: true });
      state.settings = await request("/settings");
      Object.assign(form, JSON.parse(JSON.stringify(state.settings)));
    },
    "已补充源 CLI 配置",
  );
}
</script>
<template>
  <div class="settings-layout">
    <nav class="settings-nav" aria-label="设置分类">
      <button
        v-for="(name, key) in {
          learning: '学习方式',
          ai: 'AI 服务',
          bank: '题库来源',

          advanced: '运行与存储',
        }"
        :class="{ selected: tab === key }"
        @click="tab = key"
      >
        {{ name }}
      </button>
    </nav>
    <form class="settings-panel" @submit.prevent="save">
      <template v-if="tab === 'learning'"
        ><h2>默认学习方式</h2>
        <p class="muted">
          创建任务时可调整这些参数；已有任务使用各自保存的配置。
        </p>
        <h3>视频与章节任务</h3>
        <ParameterForm
          :params="form.defaults"
          feature="course_all"
        /> </template
      ><template v-else
        ><h2>
          {{
            {
              ai: "AI 服务",
              bank: "题库来源",

              advanced: "运行与存储",
            }[tab]
          }}
        </h2>
        <p class="muted">
          {{
            tab === "ai"
              ? "填写兼容接口与模型。已保存的密钥不会显示，留空会保留。"
              : tab === "advanced"
                ? "调整后台并发与等待策略。端口变更需要重启服务。"
                : "按需要启用并保存配置。"
          }}
        </p>
        <div class="form-grid">
          <template v-for="path in fields()" :key="path"
            ><label v-if="typeof get(path) === 'boolean'" class="check"
              ><input
                :checked="get(path)"
                type="checkbox"
                @change="update($event, path)"
              />{{ labels[path] }}</label
            ><label v-else class="field"
              >{{ labels[path]
              }}<input
                :type="
                  secret(path)
                    ? 'password'
                    : typeof get(path) === 'number'
                      ? 'number'
                      : 'text'
                "
                :step="typeof get(path) === 'number' ? 'any' : undefined"
                :value="
                  Array.isArray(get(path))
                    ? get(path).join(',')
                    : (get(path) ?? '')
                "
                :aria-label="labels[path]"
                :placeholder="hasSecret(path) ? '已配置，留空保留' : undefined"
                @input="update($event, path)"
              /><small v-if="hasSecret(path)"
                >已保存 · 输入新值可替换</small
              ></label
            ></template
          >
        </div></template
      >
      <div class="form-actions">
        <button class="primary" :disabled="state.busy.has('settings')">
          <Save :size="16" />保存设置
        </button>
      </div>
    </form>
  </div>
  <details class="advanced">
    <summary>配置备份与迁移</summary>
    <div class="button-row">
      <a class="button" href="/api/settings/export" download
        ><Download :size="16" />导出设置</a
      ><label class="button"
        >导入设置<input
          type="file"
          accept=".json"
          class="file-input"
          @change="importFile" /></label
      ><button @click="importSource">从原 CLI 补充空白配置</button>
    </div>
  </details>
</template>
