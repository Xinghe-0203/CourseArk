<script setup lang="ts">
import { reactive, ref } from "vue";
import { Save, Download } from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import type { Settings } from "../types";
import ParameterForm from "../components/ParameterForm.vue";
const form = reactive<Settings>(JSON.parse(JSON.stringify(state.settings))),
  tab = ref("learning");
// 2.2.1 新增字段：老配置里没有 sync_on_start 时按默认开启展示。
if (form.scheduler && typeof form.scheduler.sync_on_start !== "boolean")
  form.scheduler.sync_on_start = true;
const labels: Record<string, string> = {
  "scheduler.sync_on_start": "启动时自动同步课程",
  "scheduler.max_active_workers": "同时执行的任务数",
  "scheduler.stop_grace_seconds": "停止任务的等待时间（秒）",
  "llm.base_url": "AI 接口地址",
  "llm.api_key": "API Key",
  "llm.model": "模型名称",
  "llm.temperature": "回答随机程度",
  "llm.max_tokens": "最大输出长度",
  "llm.timeout": "响应等待时间（秒）",
  "defaults.video.mode": "视频播放方式",
  "defaults.video.max_workers": "同时播放的视频数",
  "defaults.answer.mode": "答题方式",
  "defaults.answer.no_answer_action": "没有可靠答案时",
  "defaults.answer.submit_delay": "提交前等待（秒）",
  "defaults.answer.auto_submit": "自动提交答案",
  "defaults.learn_count.times": "每个任务点学习次数",
  "defaults.learn_count.dwell": "每次停留时间（秒）",
  "defaults.download.path": "资源保存目录",
  "defaults.download.scope": "资源下载范围",
  "question_bank.enabled": "启用答题缓存",
  "question_bank.auto_save": "自动保存已验证的答案",
  "advanced.request_delay": "请求间隔（秒）",
  "advanced.request_delay_jitter": "随机间隔（秒）",
  "advanced.max_retries": "失败重试次数",
  "advanced.retry_delay": "重试间隔（秒）",
  "advanced.rotate_ua": "轮换浏览器标识",
  "advanced.log_level": "诊断记录级别",
  "server.port": "本机服务端口",
  "storage.log_retention_days": "日志保留天数",
  "ui.completed_page_size": "「已完成」页每页条数",
};
/** 每个设置项的一句说明，随输入框一起显示，避免只看字段名猜含义。 */
const hints: Record<string, string> = {
  "scheduler.sync_on_start": "打开程序后自动读取已登录账号的课程与任务点。",
  "scheduler.max_active_workers": "同时运行的任务上限，过大可能触发平台验证。",
  "scheduler.stop_grace_seconds": "发出停止指令后等待任务收尾的秒数。",
  "llm.base_url": "兼容 OpenAI 协议的接口地址，例如 https://api.deepseek.com/v1。",
  "llm.api_key": "只保存在本机；已保存的密钥不会回显，留空表示继续使用。",
  "llm.model": "用于自动答题的模型名称，例如 deepseek-chat。",
  "llm.temperature": "0 最稳定，越大回答越随机。答题建议保持较低。",
  "llm.max_tokens": "单次回答的最大长度，过小可能截断解析结果。",
  "llm.timeout": "等待模型响应的最长时间，网络较慢时可调大。",
  "defaults.video.mode": "自动选择最省时的播放方式，或按真实时长播放。",
  "defaults.video.max_workers": "同时播放的视频数量，0 表示由程序自动决定。",
  "defaults.answer.mode": "由 AI 自动作答，或只抓取题目交由你手工填写。",
  "defaults.answer.no_answer_action": "题库与 AI 都没有可靠答案时的处理方式。",
  "defaults.answer.submit_delay": "提交答案前的等待秒数，避免提交过快。",
  "defaults.answer.auto_submit": "关闭后只作答不提交，由你确认后再提交。",
  "defaults.learn_count.times": "「学习次数」类任务点需要重复的次数。",
  "defaults.learn_count.dwell": "每次学习之间的停留时间，过短会被平台判定异常。",
  "defaults.download.path": "课件等资源下载到本机的目录。",
  "defaults.download.scope": "下载全部章节，或只下载你在新建任务时勾选的章节。",
  "question_bank.enabled": "启用后优先使用本机记住的答案，减少重复调用 AI。",
  "question_bank.auto_save": "把已验证成功的答案写入本机缓存。",
  "advanced.request_delay": "两次平台请求之间的基础间隔，过小容易被限流。",
  "advanced.request_delay_jitter": "在基础间隔上叠加的随机浮动，让请求节奏更像人工。",
  "advanced.max_retries": "单步失败后的重试次数，0 表示不重试。",
  "advanced.retry_delay": "两次重试之间的等待秒数。",
  "advanced.rotate_ua": "轮换浏览器标识，降低被平台识别为脚本的概率。",
  "advanced.log_level": "诊断日志的详细程度，排查问题时可临时调低。",
  "server.port": "本机 WebUI 端口，修改后需要重启服务。",
  "storage.log_retention_days": "诊断日志保留天数，过期自动清理。",
  "ui.completed_page_size": "「已完成」专页一页显示多少条记录（10—100）。",
};
/** 枚举型设置用下拉框，避免手输错值。 */
const choices: Record<string, [string, string][]> = {
  "defaults.video.mode": [
    ["hybrid", "自动选择播放方式"],
    ["instant", "优先立即完成"],
    ["real_time", "按实际时长播放"],
  ],
  "defaults.answer.mode": [
    ["ai", "AI 作答"],
    ["manual", "只抓题，由我手动作答"],
  ],
  "defaults.answer.no_answer_action": [
    ["skip", "跳过，留待处理"],
    ["random", "随机选择"],
  ],
  "defaults.download.scope": [
    ["all", "全部章节"],
    ["chapters", "仅新建任务时勾选的章节"],
  ],
  "advanced.log_level": [
    ["DEBUG", "调试（最详细）"],
    ["INFO", "常规"],
    ["WARNING", "仅警告"],
    ["ERROR", "仅错误"],
  ],
};
/** 每个 tab 负责的设置前缀；learning 由 ParameterForm 单独渲染，不在列表里。 */
const groups: Record<string, string[]> = {
  ai: ["llm"],
  bank: ["question_bank"],
  ui: ["ui"],
  advanced: ["scheduler", "advanced", "server", "storage"],
};
const tabs: Record<string, string> = {
  learning: "学习方式",
  ai: "AI 服务",
  bank: "答题缓存",
  ui: "界面显示",
  advanced: "运行与存储",
};
const tabHints: Record<string, string> = {
  ai: "填写兼容接口与模型。已保存的密钥不会显示，留空会保留。",
  bank: "答题缓存用于复用已验证的答案；清空或导入请前往「答题缓存」页面。",
  ui: "调整「已完成」专页等界面的显示方式，保存后立即生效。",
  advanced: "调整后台并发与等待策略。端口变更需要重启服务。",
};
/** 保存反馈：与全局 toast 文案区分，避免同名文本在页面上重复。 */
const feedback = ref<{ ok: boolean; text: string }>({ ok: true, text: "" });
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
  return /api_key|token/.test(path);
}
function hasSecret(path: string) {
  return form.secrets?.[path.replace(/[.-]/g, "_") + "_configured"];
}
function update(event: Event, path: string) {
  const input = event.target as HTMLInputElement;
  if (input.type === "checkbox") set(path, input.checked);
  else if (input.tagName === "SELECT") set(path, input.value);
  else if (input.type === "number")
    set(path, input.value === "" ? "" : Number(input.value));
  else set(path, input.value);
}
function fields() {
  return Object.keys(labels).filter((p) =>
    groups[tab.value]?.includes(p.split(".")[0]!),
  );
}
async function save() {
  feedback.value = { ok: true, text: "" };
  await act(
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
  feedback.value = state.error
    ? { ok: false, text: `保存失败：${state.error}` }
    : { ok: true, text: "已写入本机配置文件" };
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
  <div class="settings">
    <div class="settings-layout">
      <nav class="settings-nav" aria-label="设置分类">
        <button
          v-for="(name, key) in tabs"
          :key="key"
          :class="{ selected: tab === key }"
          :aria-current="tab === key ? 'page' : undefined"
          @click="tab = key"
        >
          {{ name }}
        </button>
      </nav>
      <div class="settings-main">
        <form class="settings-panel" @submit.prevent="save">
          <template v-if="tab === 'learning'">
            <div class="panel-head">
              <h2>默认学习方式</h2>
              <p>
                新建任务时默认使用这里的参数，也可以在向导里临时调整；已有任务按创建时的快照执行。
              </p>
            </div>
            <div class="panel-body">
              <h3>视频与章节任务</h3>
              <ParameterForm :params="form.defaults" feature="course_all" />
              <h3 class="sub-head">章节测验与作业（与上面共用）</h3>
              <p class="settings-hint">
                作答方式、没有可靠答案时的处理与提交等待，与视频任务一起保存；
                「答题缓存」页负责已经记住的答案，这里只管默认策略。
              </p>
            </div>
          </template>
          <template v-else>
            <div class="panel-head">
              <h2>{{ tabs[tab] }}</h2>
              <p>{{ tabHints[tab] }}</p>
            </div>
            <div class="panel-body form-grid">
              <template v-for="path in fields()" :key="path">
                <div v-if="typeof get(path) === 'boolean'" class="settings-switch">
                  <label class="check"
                    ><input
                      :checked="get(path)"
                      type="checkbox"
                      @change="update($event, path)"
                    />{{ labels[path] }}</label
                  ><small v-if="hints[path]" class="settings-hint">{{
                    hints[path]
                  }}</small>
                </div>
                <label v-else class="field"
                  >{{ labels[path]
                  }}<select
                    v-if="choices[path]"
                    :value="get(path) ?? ''"
                    :aria-label="labels[path]"
                    @change="update($event, path)"
                  >
                    <option
                      v-for="[value, name] in choices[path]"
                      :key="value"
                      :value="value"
                    >
                      {{ name }}
                    </option></select
                  ><input
                    v-else
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
                  /><small v-if="hasSecret(path)">已保存 · 输入新值可替换</small
                  ><small v-if="hints[path]" class="settings-hint">{{
                    hints[path]
                  }}</small></label
                >
              </template>
            </div>
          </template>
          <div class="panel-foot">
            <button class="primary" :disabled="state.busy.has('settings')">
              <Save :size="14" />保存设置
            </button>
            <span
              v-if="feedback.text"
              class="settings-feedback"
              :class="{ failed: !feedback.ok }"
              role="status"
              >{{ feedback.text }}</span
            >
          </div>
        </form>

        <details class="settings-backup">
          <summary>配置备份与迁移</summary>
          <p class="settings-backup-hint">
            导出的 JSON 不含明文密钥；导入会覆盖同名设置项。
          </p>
          <div class="button-row">
            <a class="button" href="/api/settings/export" download
              ><Download :size="13" />导出设置</a
            ><label class="button"
              >导入设置<input
                type="file"
                accept=".json"
                class="file-input"
                @change="importFile" /></label
            ><button @click="importSource">从原 CLI 补充空白配置</button>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-layout {
  display: grid;
  grid-template-columns: 184px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.settings-main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.settings-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  position: sticky;
  top: calc(var(--topbar) + 12px);
}

.settings-nav button {
  justify-content: flex-start;
  height: 34px;
  padding: 0 11px;
  border: 0;
  border-radius: var(--r2);
  background: transparent;
  font-size: 12px;
  color: var(--ink2);
}

.settings-nav button:hover:not(:disabled) {
  background: var(--surface2);
  border-color: transparent;
  box-shadow: none;
}

.settings-nav button.selected {
  background: var(--navy-soft);
  color: var(--navy);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--navy);
}

.settings-panel {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.panel-head {
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface2);
}

.panel-head h2 {
  font-size: 14px;
  font-weight: 600;
}

.panel-head p {
  margin-top: 5px;
  font-size: var(--fs-meta);
  color: var(--mute);
  line-height: 1.6;
}

.panel-body {
  padding: 18px 18px 20px;
}

.panel-body h3 {
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  font-size: var(--fs-small);
  font-weight: 600;
  color: var(--ink2);
}

.panel-body.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px 22px;
}

.panel-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
  background: var(--surface2);
  position: sticky;
  bottom: 0;
}

.settings-switch {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.settings-switch .check {
  margin-bottom: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink2);
}

.settings-hint {
  font-size: var(--fs-meta);
  line-height: 1.6;
  color: var(--faint);
}

.panel-body .sub-head {
  margin-top: 20px;
}

.param-hint {
  display: block;
  font-size: var(--fs-meta);
  line-height: 1.55;
  color: var(--faint);
}

.param-hint.inline {
  margin-left: 6px;
  display: inline;
}

.settings-feedback {
  font-size: var(--fs-meta);
  color: var(--ok);
}

.settings-feedback.failed {
  color: var(--danger);
}

.settings-backup {
  border: 1px solid var(--line);
  border-radius: var(--r3);
  background: var(--surface);
  overflow: hidden;
}

.settings-backup > summary {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 12px 16px;
  color: var(--ink2);
  font-size: var(--fs-small);
  font-weight: 500;
  cursor: pointer;
  list-style: none;
}

.settings-backup > summary::-webkit-details-marker {
  display: none;
}

.settings-backup > summary::before {
  content: "+";
  font-family: var(--font-num);
  color: var(--faint);
}

.settings-backup[open] > summary::before {
  content: "−";
}

.settings-backup[open] > summary {
  border-bottom: 1px solid var(--line);
}

.settings-backup > summary:hover {
  background: var(--surface2);
}

.settings-backup-hint {
  margin: 12px 16px 0;
  font-size: var(--fs-meta);
  color: var(--mute);
}

.settings-backup .button-row {
  margin: 10px 16px 16px;
}

@media (max-width: 1080px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .settings-nav {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }

  .panel-body.form-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
