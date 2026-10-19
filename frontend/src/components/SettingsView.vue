<script setup lang="ts">
import { reactive, ref } from "vue";
import { Save, Download } from "lucide-vue-next";
import { state, act } from "../store";
import { request } from "../api";
import type { Settings } from "../types";
import ParameterForm from "./ParameterForm.vue";
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
  "notification.enabled": "启用外部通知",
  "notification.server_chan.enabled": "启用 Server 酱推送",
  "notification.server_chan.sendkey": "Server 酱 SendKey",
  "notification.bark.enabled": "启用 Bark 推送",
  "notification.bark.key": "Bark 推送 Key",
  "notification.bark.server": "Bark 服务器地址",
  "notification.telegram.enabled": "启用 Telegram 推送",
  "notification.telegram.bot_token": "Telegram Bot Token",
  "notification.telegram.chat_id": "Telegram 会话 ID",
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
  "notification.enabled": "总开关；关闭后下面三种推送都不会发出。",
  "notification.server_chan.enabled": "任务结束或失败时通过 Server 酱推送提醒。",
  "notification.server_chan.sendkey": "Server 酱的 SendKey，只保存在本机且不回显。",
  "notification.bark.enabled": "通过 Bark 向 iPhone 推送任务结果。",
  "notification.bark.key": "Bark 推送 Key，只保存在本机且不回显。",
  "notification.bark.server": "自建 Bark 服务时填写自己的服务器地址。",
  "notification.telegram.enabled": "通过 Telegram 机器人推送任务结果。",
  "notification.telegram.bot_token": "机器人 Token，只保存在本机且不回显。",
  "notification.telegram.chat_id": "接收消息的会话 ID，可向机器人发送 /start 后获取。",
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
const groups: Record<string, string[]> = {
  ai: ["llm"],
  answer: ["defaults"],
  notify: ["notification"],
  bank: ["question_bank"],
  ui: ["ui"],
  advanced: ["scheduler", "advanced", "server", "storage"],
};
const tabs: Record<string, string> = {
  learning: "学习方式",
  ai: "AI 服务",
  answer: "作答偏好",
  notify: "通知提醒",
  bank: "答题缓存",
  ui: "界面显示",
  advanced: "运行与存储",
};
const tabHints: Record<string, string> = {
  ai: "填写兼容接口与模型。已保存的密钥不会显示，留空会保留。",
  answer: "这些是新建任务时的默认作答方式，已有任务使用各自保存的配置。",
  notify: "任务结束或失败时通过外部渠道提醒你；密钥只保存在本机且不回显。",
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
  return /api_key|token|sendkey|bark.key/.test(path);
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
  <div class="settings-layout">
    <nav class="settings-nav" aria-label="设置分类">
      <button
        v-for="(name, key) in tabs"
        :key="key"
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
        ><h2>{{ tabs[tab] }}</h2>
        <p class="muted">{{ tabHints[tab] }}</p>
        <div class="form-grid">
          <template v-for="path in fields()" :key="path"
            ><div
              v-if="typeof get(path) === 'boolean'"
              class="settings-switch"
            >
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
              /><small v-if="hasSecret(path)"
                >已保存 · 输入新值可替换</small
              ><small v-if="hints[path]" class="settings-hint">{{
                hints[path]
              }}</small></label
            ></template
          >
        </div></template
      >
      <div class="form-actions">
        <button class="primary" :disabled="state.busy.has('settings')">
          <Save :size="16" />保存设置
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
<style scoped>
.settings-switch {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 22px;
}
.settings-switch .check {
  margin-bottom: 0;
}
.settings-hint {
  color: var(--fg-subtle);
  font-size: 11px;
  line-height: 1.6;
}
.settings-feedback {
  margin-left: 14px;
  color: var(--ok);
  font-size: 12px;
}
.settings-feedback.failed {
  color: var(--danger);
}
</style>
