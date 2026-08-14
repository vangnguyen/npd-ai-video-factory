import express from "express";
import {z} from "zod";

const app = express();
app.use(express.json({limit: "1mb"}));

const renderRequest = z.object({
  job_id: z.string().min(4),
  manifest_path: z.string().min(1),
  output_path: z.string().min(1),
});

app.get("/healthz", (_req, res) => {
  res.json({status: "ok", renderer: "skeleton"});
});

app.post("/render", (req, res) => {
  const parsed = renderRequest.safeParse(req.body);
  if (!parsed.success) {
    return res.status(422).json({
      error: {
        code: "REQUEST_INVALID",
        message: "Invalid render request.",
        details: parsed.error.issues,
      },
    });
  }

  // Task 10 will replace this contract-preserving placeholder with Remotion renderMedia().
  return res.status(501).json({
    error: {
      code: "RENDER_FAILED",
      message: "Remotion renderer is not implemented yet (Sprint 1 Task 10).",
      retryable: false,
    },
  });
});

const port = Number(process.env.PORT ?? 3001);
app.listen(port, "0.0.0.0", () => {
  console.log(`npd-video-renderer listening on ${port}`);
});
