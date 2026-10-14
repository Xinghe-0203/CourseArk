<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { X } from "lucide-vue-next";
import { state } from "../store";
defineProps<{ title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let previous: Element | null;
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
  document.querySelector<HTMLElement>(".workspace")!.inert = true;
  document.querySelector<HTMLElement>(".sidebar")!.inert = true;
  document.body.style.overflow = "hidden";
  panel.value?.focus();
  document.addEventListener("keydown", key);
});
onUnmounted(() => {
  document.querySelector<HTMLElement>(".workspace")!.inert = false;
  document.querySelector<HTMLElement>(".sidebar")!.inert = false;
  document.body.style.overflow = "";
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
