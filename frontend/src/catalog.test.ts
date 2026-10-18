import { describe, expect, it } from "vitest";
import {
  catalogKindLabel,
  catalogMeta,
  catalogStatusTone,
  collectSelection,
  isSelectable,
  selectionError,
  selectableCount,
} from "./catalog";
import type { CatalogItem } from "./types";

const item = (patch: Partial<CatalogItem> = {}): CatalogItem => ({
  id: "i1",
  title: "第三章 测验",
  status: "待做",
  valid: true,
  ...patch,
});

describe("选择目录", () => {
  it("状态色板与是否可选", () => {
    expect(catalogStatusTone("已完成")).toBe("ok");
    expect(catalogStatusTone("待做")).toBe("warn");
    expect(catalogStatusTone("")).toBe("muted");
    expect(isSelectable(item())).toBe(true);
    expect(isSelectable(item({ valid: false }))).toBe(false);
    expect(selectableCount([item(), item({ id: "i2", valid: false })])).toBe(1);
  });

  it("作业与考试显示不同的时间信息", () => {
    expect(
      catalogMeta("work", item({ time_left: "2 天", end_time: "10-20 23:59" })),
    ).toEqual(["剩余 2 天", "截止 10-20 23:59"]);
    expect(
      catalogMeta("exam", {
        ...item(),
        start_time: "10-18 08:00",
        end_time: "10-18 10:00",
        limit_time: 60,
      }),
    ).toEqual(["开始 10-18 08:00", "截止 10-18 10:00", "限时 60 分钟"]);
    expect(catalogKindLabel("exam")).toBe("考试");
    expect(catalogKindLabel("work")).toBe("作业");
  });

  it("未加载或全选时提交 all", () => {
    expect(collectSelection([], false)).toEqual({ mode: "all", ids: [] });
    const state = {
      items: [item(), item({ id: "i2" })],
      selected: new Set(["i1", "i2"]),
    };
    expect(collectSelection([state], true)).toEqual({ mode: "all", ids: [] });
    expect(selectionError("work", { mode: "all", ids: [] }, true)).toBe("");
    expect(selectionError("work", { mode: "selected", ids: [] }, false)).toBe("");
  });

  it("部分勾选时提交 selected，并按加载顺序去重", () => {
    const state = {
      items: [item(), item({ id: "i2" }), item({ id: "i3", valid: false })],
      selected: new Set(["i3", "i2"]),
    };
    expect(collectSelection([state], true)).toEqual({
      mode: "selected",
      ids: ["i2"],
    });
    expect(
      selectionError("exam", { mode: "selected", ids: [] }, true),
    ).toContain("请至少选择一项考试");
  });
});
