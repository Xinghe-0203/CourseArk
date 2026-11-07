<script setup lang="ts">
import { computed } from "vue";

// 统一分页：三处各写一遍「上一页 / 区间 / 下一页」，disabled 条件各有一套；
// 收敛后只传 offset / pageSize / total，翻页语义保持服务端分页不变。
const props = defineProps<{
  offset: number;
  pageSize: number;
  total: number;
}>();
const emit = defineEmits<{ "update:offset": [value: number] }>();

const from = computed(() => (props.total ? props.offset + 1 : 0));
const to = computed(() => Math.min(props.offset + props.pageSize, props.total));
const prev = () => emit("update:offset", Math.max(0, props.offset - props.pageSize));
const next = () => emit("update:offset", props.offset + props.pageSize);
</script>
<template>
  <div class="pagination">
    <button type="button" :disabled="offset === 0" @click="prev">上一页</button>
    <span class="num">{{ from }}-{{ to }} / {{ total }}</span>
    <button
      type="button"
      :disabled="offset + pageSize >= total"
      @click="next"
    >
      下一页
    </button>
  </div>
</template>
