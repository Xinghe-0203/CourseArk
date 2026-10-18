import type { CatalogItem, SelectionParams } from "./types";

export type CatalogKind = "work" | "exam";
export type StatusTone = "ok" | "warn" | "muted";

export const catalogKindLabel = (kind: string) =>
  kind === "exam" ? "考试" : "作业";

/** 平台状态文案不统一，这里按关键词给出统一的色板。 */
export function catalogStatusTone(status?: string): StatusTone {
  const text = (status || "").trim();
  if (!text) return "muted";
  if (/已完成|已交|已提交|已批阅/.test(text)) return "ok";
  if (/待做|未交|未完成|进行中|未开始|待提交|待考试/.test(text)) return "warn";
  return "muted";
}

/** 列表项副文案：作业显示剩余时间，考试显示时间窗与限时。 */
export function catalogMeta(kind: string, item: CatalogItem): string[] {
  const parts: string[] = [];
  if (kind === "exam") {
    if (item.start_time) parts.push(`开始 ${item.start_time}`);
    if (item.end_time) parts.push(`截止 ${item.end_time}`);
    if (
      item.limit_time !== undefined &&
      item.limit_time !== null &&
      String(item.limit_time).trim() !== ""
    )
      parts.push(`限时 ${item.limit_time} 分钟`);
    return parts;
  }
  if (item.time_left) parts.push(`剩余 ${item.time_left}`);
  if (item.end_time) parts.push(`截止 ${item.end_time}`);
  return parts;
}

/** valid=false 表示已提交/已过期，只能展示不能勾选。 */
export function isSelectable(item: CatalogItem): boolean {
  return item.valid !== false;
}

export function selectableCount(items: CatalogItem[]): number {
  return items.filter(isSelectable).length;
}

export interface SelectionState {
  items: CatalogItem[];
  selected: Set<string>;
}

/**
 * 汇总为后端 SelectionParams：
 * - 全部可选条目都勾选（或还没加载列表）→ all
 * - 有勾选 → selected + 按加载顺序的 ids
 * - 一项都没勾 → selected + 空 ids（由创建任务前的校验拦截）
 */
export function collectSelection(
  states: SelectionState[],
  loaded: boolean,
): SelectionParams {
  if (!loaded) return { mode: "all", ids: [] };
  const ids: string[] = [];
  let total = 0,
    selectedCount = 0;
  for (const state of states) {
    for (const item of state.items) {
      if (!isSelectable(item)) continue;
      total += 1;
      if (state.selected.has(item.id)) {
        selectedCount += 1;
        if (!ids.includes(item.id)) ids.push(item.id);
      }
    }
  }
  if (!total || selectedCount === total) return { mode: "all", ids: [] };
  return { mode: "selected", ids };
}

export function selectionError(
  kind: string,
  selection: SelectionParams,
  loaded: boolean,
): string {
  const label = catalogKindLabel(kind);
  if (!loaded) return "";
  if (selection.mode === "selected" && !selection.ids.length)
    return `请至少选择一项${label}，或切换到「全部待做」`;
  return "";
}
