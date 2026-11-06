<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { X } from "lucide-vue-next";
import { state } from "../store";
defineProps<{ title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let previous: Element | null;
// 同时存在的弹窗可能不止一个（任务抽屉叠在列表页、向导里再开确认框）。
// inert 与滚动锁必须引用计数：否则先卸载的那个会把锁清掉，
// 或者某个实例异常卸载后把整页永久锁死（点击全部落到 shell 上）。
let locks = 0;
function lock() {
  if (locks++ > 0) return;
  document.querySelector<HTMLElement>(".workspace")?.setAttribute("inert", "");
  document.querySelector<HTMLElement>(".sidebar")?.setAttribute("inert", "");
  document.body.style.overflow = "hidden";
}
function unlock() {
  if (locks > 0) locks -= 1;
  if (locks > 0) return;
  document.querySelector<HTMLElement>(".workspace")?.removeAttribute("inert");
  document.querySelector<HTMLElement>(".sidebar")?.removeAttribute("inert");
  document.body.style.overflow = "";
}
function key(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
  if (event.key === "Tab") {
    const els = panel.value?.querySelectorAll<HTMLElement>(
      'button:not(:disabled),a,input,select,textarea,[tabindex="0"]',
    );
    if (!els?.length) return;
    const first = els[0]!,
      last = els[els.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
}
onMounted(() => {
  previous = document.activeElement;
  lock();
  panel.value?.focus();
  document.addEventListener("keydown", key);
});
onUnmounted(() => {
  unlock();
  document.removeEventListener("keydown", key);
  if (previous instanceof HTMLElement) previous.focus();
});
</script>

<template>
  <Teleport to="body"
    ><div class="overlay" @click.self="emit('close')">
      <section
        ref="panel"
        tabindex="-1"
        :class="['modal', { wide }]"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
      >
        <div class="modal-heading">
          <h2>{{ title }}</h2>
          <button
            class="icon-button"
            aria-label="关闭面板"
            @click="emit('close')"
          >
            <X :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <div v-if="state.error" class="alert error" role="alert">
            <span>{{ state.error }}</span
            ><button @click="state.error = ''">关闭</button>
          </div>
          <slot />
        </div>
      </section></div
  ></Teleport>
</template>