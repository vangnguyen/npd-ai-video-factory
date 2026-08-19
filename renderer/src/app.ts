import express from "express";
import {access, mkdir, readFile} from "node:fs/promises";
import {dirname, isAbsolute, relative, resolve} from "node:path";

import {renderRequestSchema, videoManifestSchema} from "./contract";
import type {VideoManifest} from "./types";

export type RenderProgress = (progress: number) => void;

export interface RenderEngine {
  render(input: {
    manifest: VideoManifest;
    outputPath: string;
    onProgress: RenderProgress;
  }): Promise<void>;
}

export type RendererAppOptions = {
  engine: RenderEngine;
  port: number;
  storageRoot: string;
};

type ErrorCode = "REQUEST_INVALID" | "MANIFEST_VALIDATION_FAILED" | "RENDER_ASSET_MISSING" | "RENDER_FAILED";

const failed = (code: ErrorCode, message: string, retryable = false, details: unknown[] = []) => ({
  status: "failed" as const,
  error_code: code,
  message,
  retryable,
  details,
});

export const mapRenderProgress = (progress: number): number => {
  const bounded = Math.min(1, Math.max(0, progress));
  return Math.round(70 + bounded * 25);
};

export const createRendererApp = ({engine, port, storageRoot}: RendererAppOptions) => {
  const root = resolve(storageRoot);
  const app = express();
  app.use(express.json({limit: "1mb"}));
  app.use("/media", express.static(root, {dotfiles: "deny", fallthrough: false}));

  const safeStoragePath = (candidate: string): string => {
    const resolved = resolve(candidate);
    const rel = relative(root, resolved);
    if (rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))) return resolved;
    throw new Error("path must remain inside STORAGE_ROOT");
  };

  const localPath = (candidate: string): string | null => {
    if (/^https?:\/\//i.test(candidate) || /^data:/i.test(candidate)) return null;
    return safeStoragePath(candidate);
  };

  const mediaUrl = (candidate: string): string => {
    const resolved = localPath(candidate);
    if (resolved === null) return candidate;
    const rel = relative(root, resolved).split("\\").join("/");
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

  const assertLocalAssets = async (manifest: VideoManifest): Promise<void> => {
    const candidates = [
      manifest.brand.logo_uri,
      manifest.voice?.audio_uri,
      manifest.music?.audio_uri,
      ...manifest.scenes.map((scene) => scene.visual.uri),
    ].filter((value): value is string => Boolean(value));
    await Promise.all(candidates.map(async (candidate) => {
      const path = localPath(candidate);
      if (path !== null) await access(path);
    }));
  };

  app.get("/healthz", (_req, res) => {
    res.json({status: "ok", renderer: "remotion", composition: "real-estate-short-v1"});
  });

  app.post("/render", async (req, res) => {
    const parsedRequest = renderRequestSchema.safeParse(req.body);
    if (!parsedRequest.success) {
      return res.status(422).json(failed(
        "REQUEST_INVALID",
        "Invalid render request.",
        false,
        parsedRequest.error.issues,
      ));
    }

    const {job_id: jobId, manifest_path: requestedManifestPath} = parsedRequest.data;
    let manifestPath: string;
    let outputPath: string;
    try {
      manifestPath = safeStoragePath(requestedManifestPath);
      outputPath = safeStoragePath(
        parsedRequest.data.output_path ?? resolve(dirname(manifestPath), "final.mp4"),
      );
    } catch {
      return res.status(422).json(failed("REQUEST_INVALID", "Render paths must remain inside storage."));
    }

    let manifest: VideoManifest;
    try {
      const raw: unknown = JSON.parse(await readFile(manifestPath, "utf8"));
      const parsedManifest = videoManifestSchema.safeParse(raw);
      if (!parsedManifest.success) {
        return res.status(422).json(failed(
          "MANIFEST_VALIDATION_FAILED",
          "Video manifest is invalid.",
          false,
          parsedManifest.error.issues,
        ));
      }
      manifest = parsedManifest.data as VideoManifest;
    } catch (error) {
      if (error instanceof SyntaxError) {
        return res.status(422).json(failed("MANIFEST_VALIDATION_FAILED", "Video manifest is not valid JSON."));
      }
      return res.status(404).json(failed("MANIFEST_VALIDATION_FAILED", "Video manifest could not be read."));
    }

    try {
      await assertLocalAssets(manifest);
    } catch {
      return res.status(422).json(failed("RENDER_ASSET_MISSING", "A local render asset is missing or inaccessible."));
    }

    try {
      await mkdir(dirname(outputPath), {recursive: true});
      await engine.render({
        manifest: browserManifest(manifest),
        outputPath,
        onProgress: (progress) => {
          console.log(JSON.stringify({
            event: "render_progress",
            job_id: jobId,
            progress,
            overall_progress: mapRenderProgress(progress),
          }));
        },
      });
      return res.json({
        status: "success",
        job_id: jobId,
        output_path: outputPath,
        duration: manifest.metadata.duration_seconds,
        width: manifest.metadata.width,
        height: manifest.metadata.height,
        fps: manifest.metadata.fps,
        codec: "h264",
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "unknown failure";
      console.error(JSON.stringify({event: "render_failed", job_id: jobId, detail}));
      return res.status(500).json(failed("RENDER_FAILED", "Remotion render failed."));
    }
  });

  return app;
};
