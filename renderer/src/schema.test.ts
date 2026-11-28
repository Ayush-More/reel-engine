import { describe, expect, it } from "vitest";
import { isInsideSafeArea, isInsideStageSafeArea, overlaps } from "./layout";
import { templatePropsSchema } from "./schema";

const propsByTemplate: Record<string, unknown> = {
  hook_big_type: { line1: "AI text", line2: "to tokens", morph_to: [] },
  problem_explain: { headline: "What changed?", bullets: ["Text", "Tokens"] },
  analogy: { metaphor: "Lego", left_label: "Whole", right_label: "Parts", items: ["One", "Two"] },
  token_split: { sentence: "Hello world", tokens: ["Hello", " world"], illustrative: true },
  flow_diagram: { nodes: [{ id: "a", label: "Text" }, { id: "b", label: "Tokens" }], edges: [{ src: "a", dst: "b" }] },
  split_compare: { left: { title: "A", lines: ["One"] }, right: { title: "B", lines: ["Two"] } },
  before_after: { before: { title: "Before", lines: ["Old"] }, after: { title: "After", lines: ["New"] } },
  architecture: { title: "Stack", nodes: [{ id: "a", label: "A" }, { id: "b", label: "B" }], edges: [{ src: "a", dst: "b" }] },
  terminal_code: { lines: ["$ echo tokens"], language: "bash" },
  browser_ui: { url: "https://example.test", title: "Example", content_html: "<p>text</p>" },
  chat_ui: { messages: [{ role: "user", text: "Hi" }] },
  step_process: { steps: [{ number: 1, label: "Start" }, { number: 2, label: "End" }] },
  counter: { from_value: 1, to_value: 2, label: "Count" },
  keyword_highlight: { sentence: "AI tokens", keywords: ["tokens"] },
  data_viz: { kind: "meter", title: "Usage", series: [{ label: "Used", value: 40 }] },
  takeaway: { title: "Remember", items: ["Text", "Tokens"] },
  cta: { primary: "Share this" },
};

describe("renderer contracts", () => {
  it("accepts props for every supported Pydantic template", () => {
    for (const [template, props] of Object.entries(propsByTemplate)) {
      expect(templatePropsSchema.safeParse({ template, props }).success, template).toBe(true);
    }
  });

  it("rejects unknown props instead of silently forwarding them", () => {
    const result = templatePropsSchema.safeParse({
      template: "hook_big_type",
      props: { line1: "A", line2: "B", extra_layout: "not allowed" },
    });
    expect(result.success).toBe(false);
  });
});

describe("1080x1920 layout guard", () => {
  it("reserves 64px sides, the 480px bottom UI region, and 120px stage buffer", () => {
    expect(isInsideSafeArea({ x: 64, y: 680, width: 832, height: 610 })).toBe(true);
    expect(isInsideStageSafeArea({ x: 64, y: 680, width: 832, height: 610 })).toBe(true);
    expect(isInsideStageSafeArea({ x: 64, y: 680, width: 833, height: 610 })).toBe(false);
    expect(isInsideSafeArea({ x: 64, y: 1441, width: 900, height: 10 })).toBe(false);
    expect(overlaps(
      { x: 64, y: 680, width: 832, height: 610 },
      { x: 90, y: 1310, width: 900, height: 100 },
    )).toBe(false);
  });
});
