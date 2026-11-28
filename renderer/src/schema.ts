import { z } from "zod";

const hook = z.object({
  template: z.literal("hook_big_type"),
  props: z.object({ line1: z.string(), line2: z.string(), accent_word: z.string().nullable().optional(), morph_to: z.array(z.string()).optional() }).strict(),
});
const problem = z.object({
  template: z.literal("problem_explain"),
  props: z.object({ headline: z.string(), bullets: z.array(z.string()).min(1).max(4), tone: z.enum(["problem", "neutral"]).optional() }).strict(),
});
const analogy = z.object({
  template: z.literal("analogy"),
  props: z.object({ metaphor: z.string(), left_label: z.string(), right_label: z.string(), items: z.array(z.string()).min(1).max(6) }).strict(),
});
const tokenSplit = z.object({
  template: z.literal("token_split"),
  props: z.object({ sentence: z.string(), tokens: z.array(z.string()).min(1), illustrative: z.boolean().optional(), show_count: z.boolean().optional() }).strict(),
});
const flowDiagram = z.object({
  template: z.literal("flow_diagram"),
  props: z.object({
    nodes: z.array(z.object({ id: z.string(), label: z.string(), color: z.string().optional() }).strict()).min(2).max(7),
    edges: z.array(z.object({ src: z.string(), dst: z.string(), label: z.string().nullable().optional() }).strict()).min(1),
    direction: z.enum(["horizontal", "vertical"]).optional(),
  }).strict(),
});
const comparePane = z.object({ title: z.string(), lines: z.array(z.string()).min(1).max(5), color: z.string().optional() }).strict();
const splitCompare = z.object({
  template: z.literal("split_compare"),
  props: z.object({ left: comparePane, right: comparePane, verdict: z.string().nullable().optional() }).strict(),
});
const beforeAfter = z.object({
  template: z.literal("before_after"),
  props: z.object({ before: comparePane, after: comparePane, verdict: z.string().nullable().optional() }).strict(),
});
const architecture = z.object({
  template: z.literal("architecture"),
  props: z.object({
    title: z.string(),
    nodes: z.array(z.object({ id: z.string(), label: z.string(), color: z.string().optional() }).strict()).min(2).max(10),
    edges: z.array(z.object({ src: z.string(), dst: z.string(), label: z.string().nullable().optional() }).strict()).min(1),
    direction: z.enum(["horizontal", "vertical"]).optional(),
  }).strict(),
});
const terminal = z.object({
  template: z.literal("terminal_code"),
  props: z.object({ lines: z.array(z.string()).min(1).max(20), language: z.string().optional(), highlight_lines: z.array(z.number()).optional(), title: z.string().nullable().optional() }).strict(),
});
const browser = z.object({
  template: z.literal("browser_ui"),
  props: z.object({ url: z.string(), title: z.string(), content_html: z.string(), highlight: z.string().nullable().optional() }).strict(),
});
const chat = z.object({
  template: z.literal("chat_ui"),
  props: z.object({ messages: z.array(z.object({ role: z.enum(["user", "assistant", "system"]), text: z.string() }).strict()).min(1).max(10), typing: z.boolean().optional() }).strict(),
});
const steps = z.object({
  template: z.literal("step_process"),
  props: z.object({ steps: z.array(z.object({ number: z.number(), label: z.string(), done: z.boolean().optional() }).strict()).min(2).max(8), current_step: z.number().nullable().optional() }).strict(),
});
const counter = z.object({
  template: z.literal("counter"),
  props: z.object({ from_value: z.number(), to_value: z.number(), unit: z.string().optional(), label: z.string(), illustrative: z.boolean().optional() }).strict(),
});
const keyword = z.object({
  template: z.literal("keyword_highlight"),
  props: z.object({ sentence: z.string(), keywords: z.array(z.string()).min(1), style: z.enum(["underline", "bold", "glow"]).optional() }).strict(),
});
const dataViz = z.object({
  template: z.literal("data_viz"),
  props: z.object({ kind: z.enum(["meter", "bar", "line"]), title: z.string(), series: z.array(z.object({ label: z.string(), value: z.number() }).strict()).min(1).max(8), unit: z.string().nullable().optional(), illustrative: z.boolean().optional() }).strict(),
});
const takeaway = z.object({
  template: z.literal("takeaway"),
  props: z.object({ title: z.string(), items: z.array(z.string()).min(1).max(5) }).strict(),
});
const cta = z.object({
  template: z.literal("cta"),
  props: z.object({ primary: z.string(), secondary: z.string().nullable().optional(), style: z.enum(["share", "comment", "follow"]).optional() }).strict(),
});

export const templatePropsSchema = z.discriminatedUnion("template", [
  hook, problem, analogy, tokenSplit, flowDiagram, splitCompare, beforeAfter,
  architecture, terminal, browser, chat, steps, counter, keyword, dataViz, takeaway, cta,
]);

const captionWord = z.object({ text: z.string(), start: z.number().nonnegative(), end: z.number().positive() }).strict();
const captionSegment = z.object({
  start: z.number().nonnegative(), end: z.number().positive(),
  words: z.array(captionWord).min(1).max(4),
}).strict();
const scene = z.object({
  beat_id: z.string(),
  template: z.enum([
    "hook_big_type", "problem_explain", "analogy", "token_split", "flow_diagram",
    "split_compare", "before_after", "architecture", "terminal_code", "browser_ui",
    "chat_ui", "step_process", "counter", "keyword_highlight", "data_viz", "takeaway", "cta",
  ]),
  from_frame: z.number().int().nonnegative(),
  duration_frames: z.number().int().positive(),
  headline: z.string(),
  props: z.record(z.string(), z.unknown()),
  transition: z.string(),
}).strict().superRefine((value, context) => {
  const parsed = templatePropsSchema.safeParse({ template: value.template, props: value.props });
  if (!parsed.success) context.addIssue({ code: "custom", message: parsed.error.message, path: ["props"] });
});

export const renderPropsSchema = z.object({
  schema_version: z.string(),
  job_id: z.string(),
  fps: z.literal(30),
  size: z.tuple([z.literal(1080), z.literal(1920)]),
  audio_path: z.string(),
  scenes: z.array(scene).min(1),
  captions: z.object({ language: z.literal("roman_hinglish"), segments: z.array(captionSegment) }).strict(),
  assets: z.array(z.string()),
}).strict();

export type TemplateProps = z.infer<typeof templatePropsSchema>;
export type RenderProps = z.infer<typeof renderPropsSchema>;
export type RenderScene = RenderProps["scenes"][number];
