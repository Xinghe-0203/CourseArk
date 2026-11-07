<script setup lang="ts">
// 统一的二次确认弹窗：危险操作（停止任务、清空缓存、删除账号）共用，
// 避免各页手写一份 ModalShell + 按钮对，文案与交互也保持一致。
import ModalShell from "./ModalShell.vue";
defineProps<{
  title: string;
  message: string;
  hint?: string;
  confirmText?: string;
  danger?: boolean;
  busy?: boolean;
}>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>
<template>
  <ModalShell :title="title" @close="emit('cancel')">
    <p class="confirm-message">{{ message }}</p>
    <p v-if="hint" class="confirm-hint">{{ hint }}</p>
    <div class="form-actions">
      <button type="button" @click="emit('cancel')">取消</button>
      <button
        :class="danger === false ? 'primary' : 'danger'"
        :disabled="busy"
        @click="emit('confirm')"
      >
        {{ busy ? "处理中…" : confirmText || "确认" }}
      </button>
    </div>
  </ModalShell>
</template>

<style scoped>
.confirm-message {
  font-size: var(--fs-body);
  line-height: 1.65;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.confirm-hint {
  margin-top: 8px;
  font-size: var(--fs-meta);
  line-height: 1.6;
  color: var(--mute);
}
</style>
