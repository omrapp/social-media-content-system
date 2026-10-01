import type { PipelineStage } from "@/types/pipeline";

export const PIPELINE_STAGES: PipelineStage[] = [
  { key: "index",        label: "Index" },
  { key: "classify",     label: "Classify" },
  { key: "resize",       label: "Resize" },
  { key: "enhance",      label: "Enhance" },
  { key: "edit",         label: "Edit" },
  { key: "upload",       label: "Upload" },
  { key: "caption",      label: "Caption" },
  { key: "schedule",     label: "Schedule" },
];
