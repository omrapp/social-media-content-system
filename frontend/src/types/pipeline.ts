export interface PipelineRun {
  id: string;
  stage: string;
  status: string;
  items_processed: number;
  items_failed: number;
  started_at: string;
  created_at?: string;
}

export interface PipelineStage {
  key: string;
  label: string;
}

export interface OrchestrateResult {
  status: string;
  processed: number;
  failed: number;
}
