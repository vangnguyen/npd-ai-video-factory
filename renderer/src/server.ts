import {bundle} from "@remotion/bundler";
import {renderMedia, selectComposition} from "@remotion/renderer";
import express from "express";
import {mkdir, readFile} from "node:fs/promises";
import {dirname, isAbsolute, relative, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {z} from "zod";

import {createLegacyTelemetry, readLegacyTelemetrySalt} from "./legacyTelemetry";
import type {VideoManifest} from "./types";

const port = Number(process.env.PORT ?? 3001);
const storageRoot = resolve(process.env.STORAGE_ROOT ?? "/workspace/storage");
const entryPoint = fileURLToPath(new URL("./index.ts", import.meta.url));

const app = express();
const recordLegacyAccess = createLegacyTelemetry(readLegacyTelemetrySalt());
app.use((req, res, next) => {
  res.on("finish", () => {
    recordLegacyAccess({
      path: req.path,
      method: req.method,
      statusCode: res.statusCode,
      peerAddress: req.socket.remoteAddress,
      claimedCallerId: req.get("X-NPD-Caller-ID"),
      userAgent: req.get("User-Agent"),
    });
  });
  next();
});
app.use(express.json({limit: "1mb"}));
app.use("/media", express.static(storageRoot, {dotfiles: "deny", fallthrough: false}));

const renderRequest = z.object({
  job_id: z.string().regex(/^vid_[A-Za-z0-9_-]+$/).max(80),
  manifest_path: z.string().min(1),
  output_path: z.string().min(1),
});

const manifestEnvelope = z.object({
  version: z.literal("1.0"),
  metadata: z.object({
    template: z.literal("real-estate-short-v1"),
    duration_seconds: z.number().positive().max(90),
    fps: z.literal(30),
    width: z.literal(1080),
    height: z.literal(1920),
  }).passthrough(),
  brand: z.object({
    logo_uri: z.string(),
    cta: z.string().min(1),
  }).passthrough(),
  scenes: z.array(z.object({
    visual: z.object({uri: z.string().min(1)}).passthrough(),
  }).passthrough()).min(1),
  subtitles: z.array(z.object({
    start_seconds: z.number().nonnegative(),
    end_seconds: z.number().positive(),
    text: z.string().min(1),
  })),
  voice: z.object({audio_uri: z.string().min(1)}).passthrough().optional(),
  music: z.object({audio_uri: z.string().min(1)}).passthrough().optional(),
}).passthrough();

const safeStoragePath = (candidate: string): string => {
  const resolved = resolve(candidate);
  const rel = relative(storageRoot, resolved);
  if (rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))) return resolved;
  throw new Error("path must remain inside STORAGE_ROOT");
};

const mediaUrl = (candidate: string): string => {
  if (/^https?:\/\//i.test(candidate) || /^data:/i.test(candidate)) return candidate;
  const resolved = safeStoragePath(candidate);
  const rel = relative(storageRoot, resolved).split("\\").join("/");
  return `http://127.0.0.1:${port}/media/${rel.split("/").map(encodeURIComponent).join("/")}`;
};

const browserManifest = (manifest: VideoManifest): VideoManifest => ({
  ...manifest,
  brand: {...manifest.brand, logo_uri: manifest.brand.logo_uri ? mediaUrl(manifest.brand.logo_uri) : ""},
  voice: manifest.voice ? {...manifest.voice, audio_uri: mediaUrl(manifest.voice.audio_uri)} : undefined,
  music: manifest.music ? {...manifest.music, audio_uri: mediaUrl(manifest.music.audio_uri)} : undefined,
  scenes: manifest.scenes.map((scene) => ({
    ...scene,
    visual: {...scene.visual, uri: mediaUrl(scene.visual.uri)},
  })),
});

let serveUrlPromise: Promise<string> | null = null;
const getServeUrl = (): Promise<string> => {
  serveUrlPromise ??= bundle({entryPoint});
  return serveUrlPromise;
};

app.get("/healthz", (_req, res) => {
  res.json({status: "ok", renderer: "remotion", composition: "real-estate-short-v1"});
});

app.post("/render", async (req, res) => {
  const parsed = renderRequest.safeParse(req.body);
  if (!parsed.success) {
    return res.status(422).json({
      error: {code: "REQUEST_INVALID", message: "Invalid render request.", details: parsed.error.issues},
    });
  }

  try {
    const manifestPath = safeStoragePath(parsed.data.manifest_path);
    const outputPath = safeStoragePath(parsed.data.output_path);
    const raw = JSON.parse(await readFile(manifestPath, "utf8"));
    const envelope = manifestEnvelope.parse(raw);
    const manifest = browserManifest(envelope as VideoManifest);
    const serveUrl = await getServeUrl();
    const inputProps = {manifest};
    const composition = await selectComposition({
      serveUrl,
      id: "real-estate-short-v1",
      inputProps,
    });

    await mkdir(dirname(outputPath), {recursive: true});
    await renderMedia({
      composition,
      serveUrl,
      codec: "h264",
      audioCodec: "aac",
      outputLocation: outputPath,
      inputProps,
      onProgress: ({progress}) => {
        console.log(JSON.stringify({event: "render_progress", job_id: parsed.data.job_id, progress}));
      },
    });

    return res.json({
      job_id: parsed.data.job_id,
      status: "complete",
      output_path: outputPath,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown renderer failure";
    console.error(JSON.stringify({event: "render_failed", job_id: parsed.data.job_id, message}));
    return res.status(500).json({
      error: {
        code: "RENDER_FAILED",
        message: "Remotion render failed.",
        retryable: false,
        details: [{message}],
      },
    });
  }
});

app.listen(port, "0.0.0.0", () => {
  console.log(`npd-video-renderer listening on ${port}`);
});
