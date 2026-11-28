import React from "react";
import { AbsoluteFill, Audio, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { RenderProps } from "./schema";
import { renderPropsSchema, templatePropsSchema } from "./schema";
import { Scene } from "./Scene";
import { CAPTION } from "./layout";
import { theme } from "./theme";

function CaptionOverlay({ captions }: { captions: RenderProps["captions"] }): React.ReactElement {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const time = frame / fps;
  const current = captions.segments.find((segment) => time >= segment.start && time <= segment.end);
  if (!current) return <></>;
  return <div style={{
    position: "absolute", top: CAPTION.top, left: 90, width: CAPTION.maxWidth, height: CAPTION.height,
    display: "flex", justifyContent: "center", alignItems: "center", flexWrap: "wrap", gap: 12,
    fontSize: 62, fontWeight: 800, lineHeight: 1.05, textAlign: "center",
    textShadow: "0 3px 12px rgba(0,0,0,.8)",
  }}>
    {current.words.map((word, index) => {
      const active = time >= word.start && time <= word.end;
      const spoken = time > word.end;
      return <span key={`${index}-${word.text}`} style={{
        color: active ? theme.green : spoken ? theme.text : theme.dim,
        opacity: active || spoken ? 1 : 0.55,
      }}>{word.text}</span>;
    })}
  </div>;
}

export function Reel(input: RenderProps): React.ReactElement {
  const props = renderPropsSchema.parse(input);
  const audioSrc = /^[a-z][a-z0-9+.-]*:\/\//i.test(props.audio_path)
    ? props.audio_path
    : staticFile(props.audio_path.replaceAll("\\", "/"));
  const frame = useCurrentFrame();
  const active = props.scenes.find((scene) => frame >= scene.from_frame && frame < scene.from_frame + scene.duration_frames);
  if (!active) throw new Error(`No scene covers frame ${frame}`);
  const totalFrames = Math.max(...props.scenes.map((scene) => scene.from_frame + scene.duration_frames));
  if (frame >= totalFrames) throw new Error(`Frame ${frame} is beyond the scene plan`);
  const parsed = templatePropsSchema.parse({ template: active.template, props: active.props });
  return <AbsoluteFill style={{ backgroundColor: theme.background, color: theme.text, fontFamily: theme.fonts.sans }}>
    <Audio src={audioSrc} />
    <div style={{ position: "absolute", left: 64, top: 72, width: 832, height: 64, display: "flex", justifyContent: "space-between", color: theme.dim, fontSize: 24 }}>
      <span>TECH EXPLAINED</span><span>{active.beat_id} / {String(props.scenes.length).padStart(2, "0")}</span>
    </div>
    <div style={{ position: "absolute", left: 64, top: 420, width: 832, height: 210, fontSize: 58, fontWeight: 900, lineHeight: 1.05 }}>
      {active.headline}
    </div>
    <Scene value={parsed} />
    <CaptionOverlay captions={props.captions} />
  </AbsoluteFill>;
}

export const reelDuration = (props: RenderProps): number =>
  Math.max(...props.scenes.map((scene) => scene.from_frame + scene.duration_frames));
