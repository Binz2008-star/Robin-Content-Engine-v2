export type JobStatus = 'pending' | 'processing' | 'rendered' | 'uploaded' | 'failed' | 'quarantined';

export interface VideoFormatConfig {
  resolution: string;
  aspectRatio: string;
  maxDurationSec: number;
  gameAudioDuckingPct: number;
  codec: string;
}

export interface ScriptData {
  title: string;
  description: string;
  tags: string[];
  script: string;
}

export interface VoiceoverConfig {
  voice: string;
  durationSec?: number;
  audioUrl?: string;
}

export interface EngineJob {
  id: string;
  title: string;
  sourcePath: string;
  rightsConfirmed: boolean;
  rightsNote: string;
  status: JobStatus;
  videoFormat: VideoFormatConfig;
  scriptData?: ScriptData;
  voiceover?: VoiceoverConfig;
  renderingProgress?: number;
  renderedVideoUrl?: string;
  youtubeId?: string;
  youtubePrivacy?: 'private' | 'unlisted' | 'public';
  logs: string[];
  createdAt: string;
  updatedAt: string;
  errorReason?: string;
}

export interface SystemInfo {
  engineVersion: string;
  commitHash: string;
  prStatus: string;
  database: {
    provider: string;
    table: string;
    lockingStrategy: string;
    statuses: string[];
  };
  renderingEngine: {
    library: string;
    methodsUsed: string[];
    resolution: string;
    maxDuration: string;
    gameAudioVolume: string;
    codec: string;
  };
  ttsVoice: string;
  aiModel: string;
  youtubeUploader: string;
}
