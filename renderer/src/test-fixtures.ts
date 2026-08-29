import type {VideoManifest} from "./types";

export const makeManifest = (visualUri: string): VideoManifest => ({
  version: "1.0",
  metadata: {
    title: "Renderer test",
    project: "renderer-test",
    template: "real-estate-short-v1",
    duration_seconds: 1,
    fps: 30,
    width: 1080,
    height: 1920,
    language: "vi",
  },
  brand: {
    name: "Ngoc Phuong Dong",
    logo_uri: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E",
    cta: "Dang ky tham quan",
  },
  scenes: [{
    id: "scene_01",
    start_seconds: 0,
    duration_seconds: 1,
    role: "hook",
    narration: "Noi dung thu nghiem",
    visual: {type: "image", uri: visualUri, fit: "cover"},
    overlay: {headline: "TIN NOI BAT", body: "Thong tin", emphasis: "Moi"},
  }],
  subtitles: [{start_seconds: 0, end_seconds: 1, text: "Phu de thu nghiem"}],
});
