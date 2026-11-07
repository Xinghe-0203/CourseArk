<script setup lang="ts">
import { computed } from "vue";

// 统一进度条：此前 10 个组件各自写 <div class="progress-track"><i :style="…"/>，
// 语义属性与百分比换算各有一套；收敛为单一出口后 a11y 属性不会再漏写。
const props = withDefaults(
  defineProps<{
    /** 0-100 的百分比；不传或传 null 表示暂无确定进度 */
    value?: number | null;
    /** 不确定进度（往复滑动）；缺省时按「没有 value」自动判定 */
    indeterminate?: boolean;
    /** 3px 紧凑变体，用于行内场景 */
    small?: boolean;
    /** 无障碍名称，如「高等数学完成进度」 */
    label?: string;
  }>(),
  { value: null, indeterminate: undefined, small: false, label: "" },
);

const indeterminate = computed(
  () => props.indeterminate ?? (props.value === null || props.value === undefined),
);
const width = computed(() => `${Math.max(0, Math.min(100, props.value ?? 0))}%`);
</script>
<template>
  <div
    :class="['progress-track', { small, indeterminate }]"
    role="progressbar"
    :aria-valuenow="indeterminate ? undefined : (value ?? 0)"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-label="label || '进度'"
  >
    <i :style="{ width }" />
  </div>
</template>
