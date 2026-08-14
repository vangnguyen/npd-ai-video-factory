export type SceneRole = "hook" | "identity" | "information" | "evidence" | "sales_angle" | "cta";

export type VideoManifest = {
  version: "1.0";
  metadata: {
    title: string;
    project: string;
    template: "real-estate-short-v1";
    duration_seconds: number;
    fps: 30;
    width: 1080;
    height: 1920;
    language: "vi";
  };
  brand: {
    name: string;
    logo_uri: string;
    cta: string;
    primary_color?: string;
    accent_color?: string;
  };
  voice?: {
    audio_uri: string;
    gain_db?: number;
  };
  music?: {
    audio_uri: string;
    gain_db: number;
  };
  scenes: Array<{
    id: string;
    start_seconds: number;
    duration_seconds: number;
    role: SceneRole;
    narration: string;
    visual: {
      type: "video" | "image";
      uri: string;
      trim_start_seconds?: number;
      trim_end_seconds?: number;
      fit?: "cover" | "contain";
    };
    overlay?: {
      headline?: string;
      body?: string;
      emphasis?: string;
    };
  }>;
  subtitles: Array<{
    start_seconds: number;
    end_seconds: number;
    text: string;
  }>;
};

export type RendererInputProps = {
  manifest: VideoManifest;
};
