import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import type { TemplateProps } from "./schema";
import { colorByName, theme } from "./theme";

const card: React.CSSProperties = {
  background: theme.surface,
  border: `1px solid ${theme.border}`,
  borderRadius: theme.radius,
  padding: 32,
  color: theme.text,
};

function color(name?: string): string {
  return name ? (colorByName[name] ?? theme.blue) : theme.blue;
}

function BulletList({ items }: { items: string[] }): React.ReactElement {
  return <div style={{ display: "grid", gap: 20, fontSize: 38, lineHeight: 1.25 }}>
    {items.map((item, index) => <div key={`${index}-${item}`} style={{ display: "flex", gap: 18 }}>
      <span style={{ color: theme.green }}>•</span><span>{item}</span>
    </div>)}
  </div>;
}

function Pane({ title, lines, tint }: { title: string; lines: string[]; tint?: string }): React.ReactElement {
  return <div style={{ ...card, borderTop: `8px solid ${color(tint)}`, flex: 1 }}>
    <div style={{ color: color(tint), fontSize: 30, fontWeight: 800, marginBottom: 24 }}>{title}</div>
    <BulletList items={lines} />
  </div>;
}

function SceneContent({ value }: { value: TemplateProps }): React.ReactElement {
  switch (value.template) {
    case "hook_big_type":
      return <div style={{ textAlign: "left", fontSize: 86, fontWeight: 900, lineHeight: 1.05 }}>
        <div>{value.props.line1}</div><div style={{ color: theme.green }}>{value.props.line2}</div>
        {value.props.morph_to?.length ? <div style={{ marginTop: 36, fontSize: 42, color: theme.dim }}>{value.props.morph_to.join("  ·  ")}</div> : null}
      </div>;
    case "problem_explain":
      return <div style={{ ...card, borderLeft: `10px solid ${theme.red}` }}>
        <h2 style={{ color: theme.red, fontSize: 48, margin: "0 0 30px" }}>{value.props.headline}</h2>
        <BulletList items={value.props.bullets} />
      </div>;
    case "analogy":
      return <div style={{ ...card, textAlign: "center" }}>
        <div style={{ color: theme.amber, fontSize: 30, fontWeight: 800 }}>{value.props.metaphor.toUpperCase()} ANALOGY</div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 32, margin: "42px 0" }}>
          <strong>{value.props.left_label}</strong><span style={{ color: theme.green, fontSize: 54 }}>↔</span><strong>{value.props.right_label}</strong>
        </div><BulletList items={value.props.items} />
      </div>;
    case "token_split":
      return <div style={{ ...card, textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 36 }}>{value.props.sentence}</div>
        <div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 14 }}>
          {value.props.tokens.map((token, index) => <span key={`${index}-${token}`} style={{
            border: `2px solid ${color([theme.green, theme.cyan, theme.purple, theme.amber][index % 4])}`,
            borderRadius: 14, padding: "14px 18px", fontSize: 34, background: "#111922",
          }}>{token}</span>)}
        </div>
        {value.props.show_count ? <div style={{ color: theme.dim, fontSize: 28, marginTop: 24 }}>{value.props.tokens.length} illustrative tokens</div> : null}
        {value.props.illustrative ? <div style={{ color: theme.amber, fontSize: 22, marginTop: 12 }}>ILLUSTRATIVE SPLIT</div> : null}
      </div>;
    case "flow_diagram":
    case "architecture":
      return <div style={{ ...card, display: "flex", flexDirection: "column", gap: 18, alignItems: "center" }}>
        {"title" in value.props ? <div style={{ fontSize: 32, color: theme.dim }}>{value.props.title}</div> : null}
        {value.props.nodes.map((node, index) => <React.Fragment key={node.id}>
          <div style={{ ...card, width: 560, textAlign: "center", borderColor: color(node.color), fontSize: 36 }}>{node.label}</div>
          {index < value.props.nodes.length - 1 ? <div style={{ color: theme.green, fontSize: 32 }}>↓</div> : null}
        </React.Fragment>)}
      </div>;
    case "terminal_code":
      return <div style={{ ...card, background: "#080B0F", fontFamily: theme.fonts.mono, fontSize: 30 }}>
        <div style={{ color: theme.green, marginBottom: 24 }}>{value.props.title ?? value.props.language}</div>
        {value.props.lines.map((line, index) => <div key={`${index}-${line}`} style={{ color: value.props.highlight_lines?.includes(index + 1) ? theme.amber : theme.text, marginBottom: 12 }}>{line}</div>)}
      </div>;
    case "cta":
      return <div style={{ ...card, textAlign: "center", padding: 50 }}>
        <div style={{ fontSize: 64, fontWeight: 900, color: theme.green }}>{value.props.primary}</div>
        {value.props.secondary ? <div style={{ fontSize: 36, color: theme.dim, marginTop: 26 }}>{value.props.secondary}</div> : null}
        <div style={{ margin: "44px auto 0", width: 220, padding: 16, borderRadius: 999, background: theme.green, color: theme.background, fontSize: 30, fontWeight: 800 }}>
          {value.props.style?.toUpperCase() ?? "SHARE"}
        </div>
      </div>;
    case "split_compare":
      return <div style={{ display: "flex", gap: 20, alignItems: "stretch" }}>
        <Pane title={value.props.left.title} lines={value.props.left.lines} tint={value.props.left.color} />
        <Pane title={value.props.right.title} lines={value.props.right.lines} tint={value.props.right.color} />
      </div>;
    case "before_after":
      return <div style={{ display: "flex", gap: 20 }}>
        <Pane title={value.props.before.title} lines={value.props.before.lines} tint={value.props.before.color} />
        <Pane title={value.props.after.title} lines={value.props.after.lines} tint={value.props.after.color} />
      </div>;
    case "browser_ui":
      return <div style={{ ...card, fontSize: 30 }}>
        <div style={{ color: theme.cyan }}>{value.props.url}</div><h2>{value.props.title}</h2>
        <div>{value.props.content_html}</div>
      </div>;
    case "chat_ui":
      return <div style={{ display: "grid", gap: 18 }}>
        {value.props.messages.map((message, index) => <div key={index} style={{ ...card, justifySelf: message.role === "user" ? "end" : "start", maxWidth: 700, fontSize: 32 }}>
          {message.text}
        </div>)}
      </div>;
    case "step_process":
      return <div style={{ ...card, display: "grid", gap: 22 }}>
        {value.props.steps.map((step) => <div key={step.number} style={{ display: "flex", alignItems: "center", gap: 22, fontSize: 34 }}>
          <span style={{ color: step.done || step.number === value.props.current_step ? theme.green : theme.dim, fontFamily: "monospace" }}>{String(step.number).padStart(2, "0")}</span>
          <span>{step.label}</span>
        </div>)}
      </div>;
    case "counter":
      return <div style={{ ...card, textAlign: "center" }}>
        <div style={{ color: theme.dim, fontSize: 30 }}>{value.props.label}</div>
        <div style={{ color: theme.green, fontSize: 88, fontFamily: "monospace", fontWeight: 800 }}>
          {value.props.from_value}{value.props.unit ?? ""} → {value.props.to_value}{value.props.unit ?? ""}
        </div>
        {value.props.illustrative ? <div style={{ color: theme.amber, fontSize: 24 }}>ILLUSTRATIVE</div> : null}
      </div>;
    case "keyword_highlight": {
      const words = value.props.sentence.split(/(\s+)/);
      return <div style={{ ...card, fontSize: 46, lineHeight: 1.4 }}>
        {words.map((word, index) => <span key={index} style={value.props.keywords.some((item) => item.toLowerCase() === word.toLowerCase()) ? { color: theme.green, fontWeight: 900 } : undefined}>{word}</span>)}
      </div>;
    }
    case "data_viz":
      return <div style={{ ...card }}>
        <div style={{ fontSize: 34, marginBottom: 34 }}>{value.props.title}</div>
        {value.props.series.map((point) => <div key={point.label} style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 26, marginBottom: 8 }}>{point.label}: {point.value}{value.props.unit ?? ""}</div>
          <div style={{ height: 26, borderRadius: 20, background: theme.border }}>
            <div style={{ height: "100%", width: `${Math.min(100, Math.max(0, point.value))}%`, borderRadius: 20, background: theme.cyan }} />
          </div>
        </div>)}
        {value.props.illustrative ? <div style={{ color: theme.amber, fontSize: 22 }}>ILLUSTRATIVE</div> : null}
      </div>;
    case "takeaway":
      return <div style={{ ...card, borderTop: `8px solid ${theme.amber}` }}>
        <div style={{ color: theme.amber, fontWeight: 900, fontSize: 36, marginBottom: 30 }}>{value.props.title}</div>
        <BulletList items={value.props.items} />
      </div>;
  }
}

export function Scene({ value }: { value: TemplateProps }): React.ReactElement {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", left: 64, top: 680, width: 832, height: 610, display: "flex", alignItems: "center", opacity }}>
    <div style={{ width: "100%", maxHeight: 610, overflow: "hidden" }}><SceneContent value={value} /></div>
  </div>;
}
