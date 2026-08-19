export type JobStatus =
  | 'pending'
  | 'processing'
  | 'rendered'
  | 'uploaded'
  | 'failed'
  | 'quarantined';

export interface VideoJob {
  id: number;
  source_path: string | null;
  source_url: string | null;
  source_title: string;
  rights_confirmed: boolean;
  rights_note: string | null;
  status: JobStatus;
  generated_title: string | null;
  generated_description: string | null;
  generated_tags: string[];
  generated_script: string | null;
  output_path: string | null;
  youtube_id: string | null;
  attempts: number;
  last_error: string | null;
  claimed_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface EnqueueJobRequest {
  source_path?: string;
  source_url?: string;
  source_title: string;
  rights_confirmed: boolean;
  rights_note?: string;
}

export interface ScriptGenRequest {
  game_name: string;
  topic: string;
  style?: string;
}

export interface GeneratedContent {
  title: string;
  description: string;
  tags: string[];
  script: string;
}

export interface WorkerRunRequest {
  render_only?: boolean;
}

export interface WorkerRunResponse {
  status: string;
  message: string;
  job?: VideoJob | null;
}

export interface HealthResponse {
  status: string;
  database: string;
  version?: string;
  demo_mode?: boolean;
}

export interface JobCounts {
  pending: number;
  processing: number;
  rendered: number;
  uploaded: number;
  failed: number;
  quarantined: number;
  total: number;
}
