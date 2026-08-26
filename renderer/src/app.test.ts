import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import request from "supertest";
import {afterEach, describe, expect, it, vi} from "vitest";

import {createRendererApp, mapRenderProgress, type RenderEngine} from "./app";
import {makeManifest} from "./test-fixtures";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, {recursive: true, force: true})));
});

const fixture = async () => {
  const root = await mkdtemp(join(tmpdir(), "npd-renderer-"));
  roots.push(root);
  const assetPath = join(root, "fixture.png");
  const manifestPath = join(root, "video-manifest.json");
  await writeFile(assetPath, Buffer.from("png fixture"));
  await writeFile(manifestPath, JSON.stringify(makeManifest(assetPath)));
  return {assetPath, manifestPath, root};
};

describe("renderer HTTP service", () => {
  it("completes a render with metadata and 70-95 progress mapping", async () => {
    const {manifestPath, root} = await fixture();
    const progresses: number[] = [];
    const engine: RenderEngine = {
      render: vi.fn(async ({onProgress}) => {
        for (const value of [0, 0.5, 1]) {
          progresses.push(mapRenderProgress(value));
          onProgress(value);
        }
      }),
    };
    const app = createRendererApp({engine, port: 3001, storageRoot: root});

    const response = await request(app).post("/render").send({
      job_id: "vid_12345678",
      manifest_path: manifestPath,
    });

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      status: "success",
      duration: 1,
      width: 1080,
      height: 1920,
      fps: 30,
      codec: "h264",
    });
    expect(progresses).toEqual([70, 83, 95]);
    expect(engine.render).toHaveBeenCalledOnce();
  });

  it("returns a stable error for a missing local scene asset", async () => {
    const {manifestPath, root} = await fixture();
    await writeFile(manifestPath, JSON.stringify(makeManifest(join(root, "missing.png"))));
    const engine: RenderEngine = {render: vi.fn(async () => undefined)};
    const response = await request(createRendererApp({engine, port: 3001, storageRoot: root}))
      .post("/render")
      .send({job_id: "vid_12345678", manifest_path: manifestPath});

    expect(response.status).toBe(422);
    expect(response.body).toMatchObject({status: "failed", error_code: "RENDER_ASSET_MISSING"});
    expect(engine.render).not.toHaveBeenCalled();
  });

  it("returns a stable error for an invalid manifest", async () => {
    const {manifestPath, root} = await fixture();
    await writeFile(manifestPath, JSON.stringify({version: "invalid"}));
    const engine: RenderEngine = {render: vi.fn(async () => undefined)};
    const response = await request(createRendererApp({engine, port: 3001, storageRoot: root}))
      .post("/render")
      .send({job_id: "vid_12345678", manifest_path: manifestPath});

    expect(response.status).toBe(422);
    expect(response.body).toMatchObject({status: "failed", error_code: "MANIFEST_VALIDATION_FAILED"});
  });

  it("does not expose renderer exception text", async () => {
    const {manifestPath, root} = await fixture();
    const engine: RenderEngine = {render: vi.fn(async () => { throw new Error("secret internal path"); })};
    const response = await request(createRendererApp({engine, port: 3001, storageRoot: root}))
      .post("/render")
      .send({job_id: "vid_12345678", manifest_path: manifestPath});

    expect(response.status).toBe(500);
    expect(response.body).toMatchObject({status: "failed", error_code: "RENDER_FAILED"});
    expect(JSON.stringify(response.body)).not.toContain("secret internal path");
  });
});

