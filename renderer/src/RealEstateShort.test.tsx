import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {describe, expect, it, vi} from "vitest";

vi.mock("remotion", async () => {
  const ReactModule = await import("react");
  const container = ({children}: React.PropsWithChildren) => ReactModule.createElement("div", null, children);
  return {
    AbsoluteFill: container,
    Audio: () => ReactModule.createElement("audio"),
    Img: (props: React.ImgHTMLAttributes<HTMLImageElement>) => ReactModule.createElement("img", props),
    OffthreadVideo: (props: React.VideoHTMLAttributes<HTMLVideoElement>) => ReactModule.createElement("video", props),
    Sequence: container,
    interpolate: () => 1,
    useCurrentFrame: () => 15,
    useVideoConfig: () => ({fps: 30, width: 1080, height: 1920, durationInFrames: 30}),
  };
});

import {
  RealEstateShort,
  SUBTITLE_SAFE_AREA,
  activeSubtitleAt,
  secondsToFrameRange,
} from "./RealEstateShort";
import {makeManifest} from "./test-fixtures";

describe("real-estate-short-v1 composition", () => {
  it("renders scene media, overlay, subtitle, logo-safe CTA, and vertical safe area", () => {
    const manifest = makeManifest("data:image/png;base64,AA==");
    const html = renderToStaticMarkup(<RealEstateShort manifest={manifest} />);

    expect(html).toContain("TIN NOI BAT");
    expect(html).toContain("Thong tin");
    expect(html).toContain("Phu de thu nghiem");
    expect(html).toContain("Dang ky tham quan");
    expect(html).toContain("data:image/png;base64,AA==");
    expect(html).toContain("Noto Sans");
    expect(SUBTITLE_SAFE_AREA).toEqual({left: 74, right: 74, bottom: 255, maxLines: 3});
  });

  it("uses manifest timing to select subtitles", () => {
    const manifest = makeManifest("data:image/png;base64,AA==");
    expect(activeSubtitleAt(manifest, 0.5)?.text).toBe("Phu de thu nghiem");
    expect(activeSubtitleAt(manifest, 1)).toBeUndefined();
    expect(secondsToFrameRange(7.533, 10.067, 30)).toEqual({from: 226, durationInFrames: 76});
    expect(secondsToFrameRange(0.15, 0.151, 30)).toEqual({from: 5, durationInFrames: 1});
  });
});
