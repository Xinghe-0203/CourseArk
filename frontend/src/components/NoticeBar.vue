<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { Bell, X, ArrowUpRight, Check } from "lucide-vue-next";
import { state, navigate, act } from "../store";
import { request } from "../api";
import { categories, date } from "../format";
const open = ref(false);
const root = ref<HTMLElement>();
function close(event: Event) {
  if (
    event instanceof KeyboardEvent
      ? event.key === "Escape"
      : !root.value?.contains(event.target as Node)
  )
    open.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", close);
  document.addEventListener("keydown", close);
});
onUnmounted(() => {
  document.removeEventListener("pointerdown", close);
  document.removeEventListener("keydown", close);
});
</script>
<template>
  <div class="notice-trigger" ref="root">
    <button
      class="icon-button"
      aria-label="打开站内通知栏"
      :aria-expanded="open"
      @click="open = !open"
    >
      <Bell :size="18" /><b v-if="state.unreadProblems" class="notice-count">{{
        state.unreadProblems > 99 ? "99+" : state.unreadProblems
      }}</b>
    </button>
    <section
      v-if="open"
      class="notice-panel"
      role="region"
      aria-label="站内通知栏"
    >
      <header>
        <h2>
          站内通知 <small>{{ state.unreadProblems }} 条未处理</small>
        </h2>
        <button
          class="icon-button"
          aria-label="关闭通知栏"
          @click="open = false"
        >
          <X :size="16" />
        </button>
      </header>
      <div class="notice-items">
        <article v-for="p in state.problems.slice(0, 12)" :key="p.id">
          <span class="tag">{{ categories[p.category] || "任务" }}</span>
          <div>
            <b>{{ p.title }}</b
            ><small
              >{{ p.context.account_label || "工作空间" }} ·
              {{ p.context.course_name || date(p.last_seen) }}</small
            >
            <p>{{ p.detail }}</p>
            <small>{{ date(p.last_seen) }} · 累计 {{ p.count }} 次</small>
          </div>
          <button
            class="icon-button"
            aria-label="处理这条通知"
            @click="
              act(
                'read-' + p.id,
                () => request('/notifications/read', 'POST', { id: p.id }),
                '通知已标记处理',
              )
            "
          >
            <Check :size="15" />
          </button>
        </article>
        <p v-if="!state.problems.length" class="muted">
          目前没有需要处理的通知。
        </p>
      </div>
      <footer>
        <button
          class="text-link"
          @click="
            navigate('problems');
            open = false;
          "
        >
          查看全部通知与分类 <ArrowUpRight :size="14" />
        </button>
      </footer>
    </section>
  </div>
</template>
