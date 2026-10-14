<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue";
import type { Problem } from "../types";
import { AlertCircle, Check, ArrowUpRight } from "lucide-vue-next";
import { state, act, navigate } from "../store";
import { request } from "../api";
import { categories, date } from "../format";
const emit = defineEmits<{ selectTask: [id: string] }>();
const category = ref(""),
  read = ref(false),
  clear = ref(false);
const items = ref<Problem[]>([]),
  offset = ref(0),
  total = ref(0);
let generation = 0;
async function load() {
  const current = ++generation;
  try {
    const data = await request<{ items: Problem[]; filtered_total: number }>(
      `/notifications?include_read=${read.value}&category=${encodeURIComponent(category.value)}&limit=100&offset=${offset.value}`,
    );
    if (current === generation) {
      if (offset.value && offset.value >= data.filtered_total) {
        offset.value = Math.max(
          0,
          Math.floor((data.filtered_total - 1) / 100) * 100,
        );
        return;
      }
      items.value = data.items;
      total.value = data.filtered_total;
    }
  } catch (e) {
    state.error = (e as Error).message;
  }
}
watch([read, category], () => {
  offset.value = 0;
  load();
});
watch(offset, load);
watch(() => state.problems, load, { immediate: true });
onUnmounted(() => generation++);
const hints: Record<string, string> = {
  llm: "检查 API Key、接口地址与模型权限，然后重试受影响的任务。",
  login: "检查账号密码；若需要验证码，请打开学习通完成登录。",
  antispider: "在学习通中完成验证，平台允许后再继续任务。",
  font: "题目未完整识别，请在学习通中核对；未识别题不会自动提交。",
  answer: "查看题目与提交结果，核对未作答内容后重新处理。",
  media:
    "核对视频任务点是否被平台确认。历史 [FAIL] 记录未包含具体原因，请查看关联任务；新任务将显示明确的播放结果。",
  network: "检查网络连接，恢复后重试任务。",
  chapter: "查看对应章节是否开放；未支持的任务点需在学习通处理。",
};
</script>
<template>
  <div class="filterbar">
    <select v-model="category" aria-label="问题分类">
      <option value="">所有问题类别</option>
      <option v-for="(label, id) in categories" :value="id">
        {{ label }}
      </option></select
    ><label class="check"
      ><input v-model="read" type="checkbox" />显示已处理</label
    ><button
      @click="
        act(
          'read-all',
          () => request('/notifications/read', 'POST', { all: true }),
          '所有问题已标记处理',
        )
      "
    >
      全部标为已处理
    </button>
  </div>
  <div class="problem-list">
    <article
      v-for="p in items"
      :key="p.id"
      :class="['problem-card', { read: !!p.read_at }]"
    >
      <span :class="['problem-icon', p.level]"><AlertCircle :size="21" /></span>
      <div>
        <div class="problem-tags">
          <span>{{ categories[p.category] || "其他问题" }}</span
          ><small
            >{{ p.context.account_label || "工作空间" }} · {{ date(p.last_seen)
            }}<template v-if="p.count > 1">
              · 出现 {{ p.count }} 次</template
            ></small
          >
        </div>
        <h3>{{ p.title }}</h3>
        <p>{{ p.detail }}</p>
        <p class="action-hint">
          {{
            hints[p.category] || "查看任务详情，核对运行结果后决定是否重试。"
          }}
        </p>
        <div class="problem-actions">
          <button
            v-if="p.category === 'llm' || p.category === 'bank'"
            class="text-link"
            @click="navigate('settings')"
          >
            前往设置 <ArrowUpRight :size="14" /></button
          ><button
            v-if="p.context.task_id"
            class="text-link"
            @click="emit('selectTask', p.context.task_id!)"
          >
            查看任务 <ArrowUpRight :size="14" />
          </button>
        </div>
      </div>
      <button
        v-if="!p.read_at"
        class="icon-button"
        aria-label="标为已处理"
        @click="
          act(
            'read-' + p.id,
            () => request('/notifications/read', 'POST', { id: p.id }),
            '问题已标记处理',
          )
        "
      >
        <Check :size="19" /></button
      ><span v-else class="muted">已处理</span>
    </article>
    <div v-if="!items.length" class="empty">
      <Check :size="32" />
      <h3>当前没有待处理问题</h3>
      <p>需要关注的信息会在这里按类别保留。</p>
    </div>
  </div>
  <div v-if="total > 100" class="pagination">
    <button :disabled="!offset" @click="offset = Math.max(0, offset - 100)">
      上一页</button
    ><span
      >{{ offset + 1 }}—{{ Math.min(offset + 100, total) }} / {{ total }}</span
    ><button :disabled="offset + 100 >= total" @click="offset += 100">
      下一页
    </button>
  </div>
  <details class="advanced">
    <summary>清理问题记录</summary>
    <p>清除后无法恢复这些问题记录，任务历史和完整日志仍保留。</p>
    <label class="check"
      ><input v-model="clear" type="checkbox" />我确认清空问题记录</label
    ><button
      :disabled="!clear"
      @click="
        act(
          'clear-problems',
          () => request('/notifications?only_read=false', 'DELETE'),
          '问题记录已清空',
        )
      "
    >
      清空记录
    </button>
  </details>
</template>
