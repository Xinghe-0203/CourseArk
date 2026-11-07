// T9.4 逐题作答小窗：SSE answer_result 事件流（最近优先），点击行打开任务详情。
import { ref } from "vue";
import { state } from "../store";
import type { Task } from "../types";

export interface AnswerFeedItem {
  key: string;
  taskId: string;
  courseName: string;
  question: string;
  answer: string;
  status: string;
  source: string;
  ts: number;
}

const feed = ref<AnswerFeedItem[]>([]);
const FEED_LIMIT = 30;

/** SSE 分流入口：App.vue 收到 answer_result 事件时调用。 */
export function pushAnswerEvent(taskId: string, payload: Record<string, unknown>, ts: number) {
  const media = String(payload.media || "题目");
  const index = payload.index ?? "?";
  feed.value = [
    {
      key: `${taskId}#${media}#${index}#${ts}`,
      taskId,
      courseName:
        state.tasks.find((task) => task.id === taskId)?.course_name || "学习任务",
      question: String(payload.question || "").slice(0, 60),
      answer: String(payload.answer || "—"),
      status: String(payload.status || "answered"),
      source: String(payload.source || ""),
      ts,
    },
    ...feed.value.filter((item) => !item.key.startsWith(`${taskId}#${media}#${index}#`)),
  ].slice(0, FEED_LIMIT);
}

export function answerFeed() {
  return feed;
}

export function openAnswerTask(item: AnswerFeedItem): Task | undefined {
  return state.tasks.find((task) => task.id === item.taskId);
}
