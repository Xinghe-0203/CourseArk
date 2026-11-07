<script setup lang="ts">
// 统一空态：软圆底图标 + 标题 + 说明 + 动作。此前 12 处空态各写各的结构，
// 有图没图、有动作没动作全看当次手气；现在只有一个出口。
defineProps<{ title: string; description?: string }>();
</script>
<template>
  <div class="empty">
    <span v-if="$slots.icon" class="empty-icon"><slot name="icon" /></span>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.actions" class="button-row">
      <slot name="actions" />
    </div>
  </div>
</template>
