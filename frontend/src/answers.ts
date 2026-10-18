import type { AnswerItem, AnswersSummary } from "./types";

export const answerSources: Record<string, string> = {
  ai: "AI 作答",
  cache: "缓存命中",
  random: "随机选择",
  failed: "未作答",
};

export const answerStatuses: Record<string, string> = {
  answered: "已作答",
  skipped: "已跳过",
  unreadable: "未识别",
};

export interface AnswerGroup {
  media: string;
  total: number;
  answered: number;
  skipped: number;
  updated: number;
  items: AnswerItem[];
}

function groupKey(item: AnswerItem): string {
  return item.key || `${item.media || ""}#${item.index}`;
}

// 同一题可能因重试出现多条，按 (media, index) 取最后一条。
export function dedupeAnswers(items: AnswerItem[]): AnswerItem[] {
  const latest = new Map<string, AnswerItem>();
  for (const item of items) latest.set(groupKey(item), item);
  return [...latest.values()];
}

export function groupAnswers(items: AnswerItem[]): AnswerGroup[] {
  const groups = new Map<string, AnswerGroup>();
  for (const item of dedupeAnswers(items)) {
    const media = item.media?.trim() || "未命名作业";
    let group = groups.get(media);
    if (!group) {
      group = {
        media,
        total: 0,
        answered: 0,
        skipped: 0,
        updated: 0,
        items: [],
      };
      groups.set(media, group);
    }
    group.items.push(item);
  }
  const list = [...groups.values()];
  for (const group of list) {
    group.items.sort((a, b) => a.index - b.index);
    group.total = group.items.reduce(
      (max, item) => Math.max(max, item.total || 0),
      group.items.length,
    );
    group.answered = group.items.filter(
      (item) => item.status === "answered",
    ).length;
    group.skipped = group.items.length - group.answered;
    group.updated = group.items.reduce(
      (max, item) => Math.max(max, item.ts || 0),
      0,
    );
  }
  // 最近有作答的作业排在最上面，便于实时任务先看到当前进度。
  return list.sort((a, b) => b.updated - a.updated);
}

function normalizeSummary(summary: Partial<AnswersSummary>): AnswersSummary {
  return {
    answered: Number(summary.answered) || 0,
    skipped: Number(summary.skipped) || 0,
    total: Number(summary.total) || 0,
    ai: Number(summary.ai) || 0,
    cache: Number(summary.cache) || 0,
    random: Number(summary.random) || 0,
    failed: Number(summary.failed) || 0,
    submit_ok: Number(summary.submit_ok) || 0,
    submit_fail: Number(summary.submit_fail) || 0,
  };
}

// 后端摘要存在时以它为提交统计口径，逐题计数仍以明细为准。
export function summarizeAnswers(
  items: AnswerItem[],
  provided?: Partial<AnswersSummary>,
): AnswersSummary {
  const list = dedupeAnswers(items);
  if (!list.length)
    return provided
      ? normalizeSummary(provided)
      : normalizeSummary({ total: 0 });
  const summary: AnswersSummary = {
    answered: 0,
    skipped: 0,
    total: 0,
    ai: 0,
    cache: 0,
    random: 0,
    failed: 0,
    submit_ok: provided?.submit_ok ?? 0,
    submit_fail: provided?.submit_fail ?? 0,
  };
  for (const item of list) {
    if (item.status === "answered") summary.answered += 1;
    else summary.skipped += 1;
    if (item.source === "ai") summary.ai += 1;
    else if (item.source === "cache") summary.cache += 1;
    else if (item.source === "random") summary.random += 1;
    else summary.failed += 1;
  }
  summary.total = Math.max(provided?.total ?? 0, summary.answered + summary.skipped);
  return summary;
}

export function answerSourceLabel(source: string): string {
  return answerSources[source] || source || "未知来源";
}

export function answerStatusLabel(status: string): string {
  return answerStatuses[status] || status || "未知状态";
}
