import { describe, it, expect } from "vitest";
import { dedupeAnswers, groupAnswers, summarizeAnswers } from "./answers";
import type { AnswerItem } from "./types";

function answer(overrides: Partial<AnswerItem> = {}): AnswerItem {
  return {
    key: "",
    index: 1,
    total: 1,
    media: "作业",
    question_type: "单选题",
    question: "题目",
    answer: "A",
    source: "ai",
    status: "answered",
    ts: 100,
    ...overrides,
  };
}

describe("AI 做题明细", () => {
  it("按 media 分组，组内按题号排序，最近作答的作业在前", () => {
    const groups = groupAnswers([
      answer({ key: "a#1", media: "作业一", index: 1, ts: 100 }),
      answer({ key: "b#1", media: "测验二", index: 1, ts: 300 }),
      answer({ key: "a#2", media: "作业一", index: 2, ts: 120 }),
    ]);
    expect(groups.map((g) => g.media)).toEqual(["测验二", "作业一"]);
    expect(groups[1]!.items.map((i) => i.index)).toEqual([1, 2]);
    expect(groups.map((g) => g.total)).toEqual([1, 2]);
  });

  it("同一题重试取最后一条，不重复计数", () => {
    const items = [
      answer({ key: "a#1", index: 1, answer: "", status: "skipped", source: "failed" }),
      answer({ key: "a#1", index: 1, answer: "B", status: "answered" }),
    ];
    expect(dedupeAnswers(items)).toHaveLength(1);
    const [group] = groupAnswers(items);
    expect(group!.items[0]!.answer).toBe("B");
    expect(group!.answered).toBe(1);
    expect(group!.skipped).toBe(0);
  });

  it("摘要按来源与状态统计，提交结果沿用后端口径", () => {
    const summary = summarizeAnswers(
      [
        answer({ source: "ai" }),
        answer({ key: "x#2", index: 2, source: "cache" }),
        answer({
          key: "x#3",
          index: 3,
          source: "random",
          answer: "",
          status: "skipped",
        }),
        answer({
          key: "x#4",
          index: 4,
          source: "failed",
          answer: "",
          status: "unreadable",
        }),
      ],
      { total: 6, submit_ok: 2, submit_fail: 1 },
    );
    expect(summary).toMatchObject({
      answered: 2,
      skipped: 2,
      total: 6,
      ai: 1,
      cache: 1,
      random: 1,
      failed: 1,
      submit_ok: 2,
      submit_fail: 1,
    });
  });

  it("没有逐题明细时回退到后端摘要，空数据不报错", () => {
    expect(summarizeAnswers([], { answered: 3, skipped: 1, total: 4 }).answered).toBe(
      3,
    );
    expect(groupAnswers([])).toEqual([]);
    expect(summarizeAnswers([])).toMatchObject({ answered: 0, total: 0 });
  });
});
