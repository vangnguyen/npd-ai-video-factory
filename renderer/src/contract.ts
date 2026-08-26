import {z} from "zod";

const strictObject = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict();

const visualSchema = strictObject({
  type: z.enum(["video", "image"]),
  uri: z.string().min(1),
  trim_start_seconds: z.number().nonnegative().optional(),
  trim_end_seconds: z.number().positive().optional(),
  fit: z.enum(["cover", "contain"]).optional(),
});

const overlaySchema = strictObject({
  headline: z.string().max(100).optional(),
  body: z.string().max(240).optional(),
  emphasis: z.string().max(60).optional(),
});

export const videoManifestSchema = strictObject({
  version: z.literal("1.0"),
  metadata: strictObject({
    title: z.string().min(1),
    project: z.string().min(1),
    template: z.literal("real-estate-short-v1"),
    duration_seconds: z.number().positive().max(90),
    fps: z.literal(30),
    width: z.literal(1080),
    height: z.literal(1920),
    language: z.literal("vi"),
  }),
  brand: strictObject({
    name: z.string().min(1),
    logo_uri: z.string().min(1),
    cta: z.string().min(1).max(160),
    primary_color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
    accent_color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
  }),
  voice: strictObject({
    audio_uri: z.string().min(1),
    gain_db: z.number().min(-24).max(12).optional(),
  }).optional(),
  music: strictObject({
    audio_uri: z.string().min(1),
    gain_db: z.number().min(-40).max(0),
  }).optional(),
  scenes: z.array(strictObject({
    id: z.string().regex(/^scene_[0-9]{2}$/),
    start_seconds: z.number().nonnegative(),
    duration_seconds: z.number().positive().max(20),
    role: z.enum(["hook", "identity", "information", "evidence", "sales_angle", "cta"]),
    narration: z.string().min(1),
    visual: visualSchema,
    overlay: overlaySchema.optional(),
  })).min(1).max(20),
  subtitles: z.array(strictObject({
    start_seconds: z.number().nonnegative(),
    end_seconds: z.number().positive(),
    text: z.string().min(1).max(160),
  })),
}).superRefine((manifest, context) => {
  const sceneDuration = manifest.scenes.reduce((sum, scene) => sum + scene.duration_seconds, 0);
  if (Math.abs(sceneDuration - manifest.metadata.duration_seconds) > 0.1) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["scenes"],
      message: "scene duration total must match metadata duration",
    });
  }
  for (let index = 1; index < manifest.scenes.length; index += 1) {
    if (manifest.scenes[index].start_seconds < manifest.scenes[index - 1].start_seconds) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["scenes", index, "start_seconds"],
        message: "scene start times must be monotonic",
      });
    }
  }
  for (let index = 0; index < manifest.subtitles.length; index += 1) {
    const subtitle = manifest.subtitles[index];
    if (subtitle.end_seconds <= subtitle.start_seconds) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["subtitles", index, "end_seconds"],
        message: "subtitle end must be after start",
      });
    }
  }
});

export const renderRequestSchema = strictObject({
  job_id: z.string().regex(/^vid_[A-Za-z0-9_-]+$/).max(80),
  manifest_path: z.string().min(1),
  output_path: z.string().min(1).optional(),
});
