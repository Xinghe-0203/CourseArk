// T9.5 告警小窗：task_failed / interrupted / worker_crash 等异常事件流，
// 支持直接「继续执行」（resumeTask）。
import { ref } from "vue";

export interface AlertItem {
  key: string;
  taskId: string;
  title: string;
  message: string;
  ts: number;
}

const alerts = ref<AlertItem[]>([]);
const ALERT_LIMIT = 20;

/** SSE 分流入口：App.vue 收到异常类事件时调用。 */
export function pushAlertEvent(
  taskId: string,
  message: string,
  ts: number,
  level = "error",
) {
  // 同任务同消息的重复告警去重（SSE 重连补发场景）。
  const key = `${taskId}#${message}`;
  if (alerts.value.some((item) => item.key === key)) return;
  alerts.value = [
    {
      key: `${key}#${ts}`,
      taskId,
      title: level === "warning" ? "需要关注" : "任务异常",
      message,
      ts,
    },
    ...alerts.value,
  ].slice(0, ALERT_LIMIT);
}

export function alertFeed() {
  return alerts;
}

export function dismissAlert(key: string) {
  alerts.value = alerts.value.filter((item) => item.key !== key);
}
