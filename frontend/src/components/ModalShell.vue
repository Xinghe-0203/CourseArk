<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { X } from "lucide-vue-next";
import { state } from "../store";
defineProps<{ title: string; wide?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let previous: Element | null;

// 同时存在的弹窗可能不止一个（任务抽屉叠在列表页、向导里再开确认框）。
// 三条规则必须按「栈」处理，否则叠层会互相干扰：
// 1. inert 与滚动锁用引用计数——先卸载的那个不能把锁清掉；
// 2. 只有最顶层的弹窗响应 Escape，否则一次按键会关掉两层；
// 3. 焦点陷阱同理，只由最顶层接管 Tab。
const stack: symbol[] = [];
const id = Symbol("modal");
let locks = 0;

function lock() {
  if (locks++ > 0) return;
  // 整个应用外壳（侧栏 + 主区 + 浮层）都不可聚焦，弹窗 Teleport 到 body 不受影响。
  document.querySelector<HTMLElement>(".shell")?.setAttribute("inert", "");
  document.body.style.overflow = "hidden";
}
function unlock() {
  if (locks > 0) locks -= 1;
  if (locks > 0) return;
  document.querySelector<HTMLElement>(".shell")?.removeAttribute("inert");
  document.body.style.overflow = "";
}
function isTop() {
  return stack[stack.length - 1] === id;
}
function focusables() {
  return Array.from(
    panel.value?.querySelectorAll<HTMLElement>(
      'button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
    ) || [],
  ).filter((el) => el.offsetParent !== null || el === document.activeElement);
}
function key(event: KeyboardEvent) {
  if (!isTop()) return;
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
    return;
  }
  if (event.key !== "Tab") return;
  const els = focusables();
  if (!els.length) {
    event.preventDefault();
    panel.value?.focus();
    return;
  }
  const first = els[0]!,
    last = els[els.length - 1]!;
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
onMounted(() => {
  previous = document.activeElement;
  stack.push(id);
  lock();
  // 落在第一个可操作控件上；没有控件时退回容器本身。
  const first = focusables()[0];
  (first || panel.value)?.focus();
  document.addEventListener("keydown", key);
});
onUnmounted(() => {
  const index = stack.indexOf(id);
  if (index >= 0) stack.splice(index, 1);
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
            title="关闭面板"
            @click="emit('close')"
          >
            <X :size="18" />
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
