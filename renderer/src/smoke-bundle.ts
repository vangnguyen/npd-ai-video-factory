import {bundle} from "@remotion/bundler";
import {fileURLToPath} from "node:url";

const entryPoint = fileURLToPath(new URL("./index.ts", import.meta.url));
const serveUrl = await bundle({entryPoint});
console.log(`renderer bundle created: ${serveUrl}`);
