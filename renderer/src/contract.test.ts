import {describe, expect, it} from "vitest";

import {renderRequestSchema, videoManifestSchema} from "./contract";
import {makeManifest} from "./test-fixtures";

describe("renderer contracts", () => {
  it("accepts the current manifest and two-field render request", () => {
    expect(videoManifestSchema.parse(makeManifest("data:image/png;base64,AA==")).metadata).toMatchObject({
      template: "real-estate-short-v1",
      width: 1080,
      height: 1920,
      fps: 30,
    });
    expect(renderRequestSchema.parse({job_id: "vid_12345678", manifest_path: "/storage/manifest.json"})).toEqual({
      job_id: "vid_12345678",
      manifest_path: "/storage/manifest.json",
    });
  });

  it("rejects invalid dimensions, unknown fields, and broken timelines", () => {
    const invalid = {
      ...makeManifest("data:image/png;base64,AA=="),
      metadata: {...makeManifest("x").metadata, width: 1920},
      unexpected: true,
    };
    expect(videoManifestSchema.safeParse(invalid).success).toBe(false);

    const brokenTimeline = makeManifest("data:image/png;base64,AA==");
    brokenTimeline.scenes[0].duration_seconds = 0.5;
    expect(videoManifestSchema.safeParse(brokenTimeline).success).toBe(false);

    const gapTimeline = makeManifest("data:image/png;base64,AA==");
    gapTimeline.scenes[0].start_seconds = 0.2;
    expect(videoManifestSchema.safeParse(gapTimeline).success).toBe(false);

    const subtitleOutsideComposition = makeManifest("data:image/png;base64,AA==");
    subtitleOutsideComposition.subtitles[0].end_seconds = 1.2;
    expect(videoManifestSchema.safeParse(subtitleOutsideComposition).success).toBe(false);
  });
});
