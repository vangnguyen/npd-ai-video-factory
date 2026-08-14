import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import type {RendererInputProps, VideoManifest} from "./types";

const dbToAmplitude = (db = 0): number => Math.pow(10, db / 20);
const fontFamily = '"Noto Sans", "Liberation Sans", sans-serif';

const SceneLayer: React.FC<{scene: VideoManifest["scenes"][number]}> = ({scene}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = Math.max(1, Math.round(scene.duration_seconds * fps));
  const fade = interpolate(frame, [0, Math.max(1, Math.round(0.2 * fps))], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const variant = scene.id.charCodeAt(scene.id.length - 1) % 2 === 0 ? 1 : -1;
  const zoom = interpolate(frame, [0, durationInFrames], [1.025, 1.1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const panX = interpolate(frame, [0, durationInFrames], [-18 * variant, 18 * variant], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const headlineY = interpolate(frame, [0, Math.max(1, Math.round(0.28 * fps))], [34, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const mediaStyle: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: scene.visual.fit ?? "cover",
    transform: scene.visual.type === "image" ? `translateX(${panX}px) scale(${zoom})` : undefined,
    willChange: scene.visual.type === "image" ? "transform" : undefined,
  };

  return (
    <AbsoluteFill style={{backgroundColor: "#0b0b0b", opacity: fade}}>
      {scene.visual.type === "video" ? (
        <OffthreadVideo
          src={scene.visual.uri}
          muted
          startFrom={Math.round((scene.visual.trim_start_seconds ?? 0) * fps)}
          endAt={
            scene.visual.trim_end_seconds == null
              ? undefined
              : Math.round(scene.visual.trim_end_seconds * fps)
          }
          style={mediaStyle}
        />
      ) : (
        <Img src={scene.visual.uri} style={mediaStyle} />
      )}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.10) 0%, rgba(0,0,0,0.02) 45%, rgba(0,0,0,0.72) 100%)",
        }}
      />
      {scene.overlay?.headline ? (
        <div
          style={{
            position: "absolute",
            left: 72,
            right: 72,
            top: scene.role === "hook" ? 220 : 150,
            color: "white",
            fontFamily,
            fontSize: scene.role === "hook" ? 82 : 60,
            fontWeight: 800,
            lineHeight: 1.05,
            textShadow: "0 4px 18px rgba(0,0,0,0.55)",
            transform: `translateY(${headlineY}px)`,
            opacity: fade,
          }}
        >
          {scene.overlay.headline}
        </div>
      ) : null}
      {scene.overlay?.emphasis ? (
        <div
          style={{
            position: "absolute",
            left: 72,
            top: 115,
            padding: "12px 20px",
            borderRadius: 14,
            backgroundColor: "rgba(0,0,0,0.62)",
            color: "white",
            fontFamily,
            fontSize: 32,
            fontWeight: 700,
          }}
        >
          {scene.overlay.emphasis}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

const Subtitles: React.FC<{manifest: VideoManifest}> = ({manifest}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const active = manifest.subtitles.find(
    (item) => seconds >= item.start_seconds && seconds < item.end_seconds,
  );
  if (!active) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: 74,
        right: 74,
        bottom: 255,
        textAlign: "center",
        color: "white",
        fontFamily,
        fontSize: 48,
        fontWeight: 750,
        lineHeight: 1.2,
        textShadow: "0 3px 8px rgba(0,0,0,0.95), 0 0 2px rgba(0,0,0,1)",
      }}
    >
      {active.text}
    </div>
  );
};

export const RealEstateShort: React.FC<RendererInputProps> = ({manifest}) => {
  const {fps} = useVideoConfig();
  const primary = manifest.brand.primary_color ?? "#d4af37";

  return (
    <AbsoluteFill style={{backgroundColor: "#0b0b0b"}}>
      {manifest.scenes.map((scene) => (
        <Sequence
          key={scene.id}
          from={Math.round(scene.start_seconds * fps)}
          durationInFrames={Math.max(1, Math.round(scene.duration_seconds * fps))}
        >
          <SceneLayer scene={scene} />
        </Sequence>
      ))}

      {manifest.voice?.audio_uri ? (
        <Audio src={manifest.voice.audio_uri} volume={dbToAmplitude(manifest.voice.gain_db)} />
      ) : null}
      {manifest.music?.audio_uri ? (
        <Audio
          src={manifest.music.audio_uri}
          volume={dbToAmplitude(manifest.music.gain_db)}
          loop
        />
      ) : null}

      {manifest.brand.logo_uri ? (
        <div
          style={{
            position: "absolute",
            top: 64,
            right: 56,
            width: 190,
            height: 90,
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
          }}
        >
          <Img
            src={manifest.brand.logo_uri}
            style={{maxWidth: "100%", maxHeight: "100%", objectFit: "contain"}}
          />
        </div>
      ) : null}

      <Subtitles manifest={manifest} />

      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: 14,
          backgroundColor: primary,
        }}
      />

      <Sequence
        from={Math.max(0, Math.round((manifest.metadata.duration_seconds - 5) * fps))}
        durationInFrames={Math.min(Math.round(5 * fps), Math.round(manifest.metadata.duration_seconds * fps))}
      >
        <div
          style={{
            position: "absolute",
            left: 64,
            right: 64,
            bottom: 78,
            borderRadius: 24,
            backgroundColor: "rgba(0,0,0,0.82)",
            border: `3px solid ${primary}`,
            color: "white",
            padding: "28px 34px",
            textAlign: "center",
            fontFamily,
            fontSize: 42,
            fontWeight: 800,
          }}
        >
          {manifest.brand.cta}
        </div>
      </Sequence>
    </AbsoluteFill>
  );
};
