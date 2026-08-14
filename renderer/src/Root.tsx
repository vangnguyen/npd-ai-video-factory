import React from "react";
import {Composition} from "remotion";

import {RealEstateShort} from "./RealEstateShort";
import type {RendererInputProps, VideoManifest} from "./types";

const defaultManifest: VideoManifest = {
  version: "1.0",
  metadata: {
    title: "NPD AI Video Factory",
    project: "sample",
    template: "real-estate-short-v1",
    duration_seconds: 1,
    fps: 30,
    width: 1080,
    height: 1920,
    language: "vi",
  },
  brand: {
    name: "Ngoc Phuong Dong",
    logo_uri: "",
    cta: "Dang ky tham quan du an",
  },
  scenes: [
    {
      id: "scene_01",
      start_seconds: 0,
      duration_seconds: 1,
      role: "hook",
      narration: "NPD AI Video Factory",
      visual: {
        type: "image",
        uri: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1080' height='1920'%3E%3Crect width='100%25' height='100%25' fill='%23111111'/%3E%3C/svg%3E",
        fit: "cover",
      },
      overlay: {headline: "NPD AI Video Factory"},
    },
  ],
  subtitles: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="real-estate-short-v1"
      component={RealEstateShort}
      durationInFrames={30}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{manifest: defaultManifest} satisfies RendererInputProps}
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(
          1,
          Math.round(props.manifest.metadata.duration_seconds * props.manifest.metadata.fps),
        ),
        fps: props.manifest.metadata.fps,
        width: props.manifest.metadata.width,
        height: props.manifest.metadata.height,
      })}
    />
  );
};
