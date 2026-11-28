import React from "react";
import { Composition, type CalculateMetadataFunction } from "remotion";
import { Reel, reelDuration } from "./Reel";
import type { RenderProps } from "./schema";

const defaultProps: RenderProps = {
  schema_version: "1.0",
  job_id: "preview",
  fps: 30,
  size: [1080, 1920],
  audio_path: "",
  scenes: [{
    beat_id: "b01", template: "hook_big_type", from_frame: 0, duration_frames: 30,
    headline: "Local render preview", transition: "cut",
    props: { line1: "AI text", line2: "to tokens", morph_to: [] },
  }],
  captions: { language: "roman_hinglish", segments: [] },
  assets: [],
};

const calculateMetadata: CalculateMetadataFunction<RenderProps> = ({ props }) => ({
  durationInFrames: reelDuration(props),
});

export function Root(): React.ReactElement {
  return <Composition
    id="Reel"
    component={Reel}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={30}
    defaultProps={defaultProps}
    calculateMetadata={calculateMetadata}
  />;
}
