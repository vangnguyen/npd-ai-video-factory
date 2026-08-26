import {createRendererApp} from "./app";
import {RemotionRenderEngine} from "./engine";

const port = Number(process.env.PORT ?? 3001);
const storageRoot = process.env.STORAGE_ROOT ?? "/workspace/storage";
const app = createRendererApp({engine: new RemotionRenderEngine(), port, storageRoot});

app.listen(port, "0.0.0.0", () => {
  console.log(`npd-video-renderer listening on ${port}`);
});
