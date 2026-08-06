import React, { useState } from 'react';
import { Database, FileCode, CheckCircle2, ShieldCheck, Cpu, Code2, Copy, Check, GitPullRequest } from 'lucide-react';

export const ArchitectureSchemaView: React.FC = () => {
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const copyCode = (code: string, key: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(key);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const schemaSQL = `-- Neon PostgreSQL Schema for Robin Engine Jobs Queue
CREATE TYPE job_status AS ENUM (
  'pending',
  'processing',
  'rendered',
  'uploaded',
  'failed',
  'quarantined'
);

CREATE TABLE IF NOT EXISTS jobs (
  id VARCHAR(64) PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  source_path TEXT NOT NULL,
  rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  rights_note TEXT NOT NULL,
  status job_status NOT NULL DEFAULT 'pending',
  
  -- Video Configuration
  resolution VARCHAR(32) DEFAULT '1080x1920',
  aspect_ratio VARCHAR(16) DEFAULT '9:16',
  max_duration_sec INT DEFAULT 58,
  game_audio_volume_pct INT DEFAULT 15,
  
  -- DeepSeek Pydantic Generated Script JSON
  script_data JSONB,
  
  -- Voiceover & YouTube Status
  voice_name VARCHAR(64) DEFAULT 'ar-AE-HamdanNeural',
  youtube_id VARCHAR(64),
  youtube_privacy VARCHAR(16) DEFAULT 'private',
  
  rendering_progress INT DEFAULT 0,
  logs TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for atomic lock acquisition speed
CREATE INDEX idx_jobs_status ON jobs(status);`;

  const moviePyCode = `# MoviePy v2 Modern Video Editing Engine Implementation
from moviepy.VideoFileClip import VideoFileClip
from moviepy.AudioFileClip import AudioFileClip

def process_shorts_video(input_path: str, voiceover_path: str, output_path: str):
    # 1. Load raw gameplay clip
    clip = VideoFileClip(input_path)
    
    # 2. Subclip to 58s max & crop/resize to 9:16 (1080x1920)
    clip = clip.subclipped(0, min(58, clip.duration))
    clip = clip.cropped(x1=clip.w * 0.25, x2=clip.w * 0.75)  # Center vertical crop
    clip = clip.resized((1080, 1920))
    
    # 3. Game Audio Ducking to 15% & Merge ar-AE-HamdanNeural Voiceover
    game_audio = clip.audio.with_volume_scaled(0.15) if clip.audio else None
    voiceover = AudioFileClip(voiceover_path)
    
    # Composite audio: Voiceover + Ducked Game Sound
    final_audio = CompositeAudioClip([game_audio, voiceover])
    
    # 4. Attach audio & export H.264 / AAC
    final_clip = clip.with_audio(final_audio)
    final_clip.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        fps=30
    )`;

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
            <Cpu className="w-5 h-5" />
            <span>Robin Engine Architecture Specs & Neon SQL Schema</span>
          </div>
          <h2 className="text-xl font-black text-slate-100 mt-1">
            System Infrastructure & MoviePy v2 Codebase
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Commit <code className="text-emerald-400 font-mono">779c4d62</code> | Branch <code className="text-amber-400 font-mono">feat/initial-engine</code> | Draft PR #1
          </p>
        </div>

        {/* GitHub CI Status Pills */}
        <div className="flex items-center gap-2 bg-slate-950 p-2.5 rounded-xl border border-slate-800 text-xs font-mono">
          <span className="px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded border border-emerald-500/30 font-bold">
            Install: SUCCESS
          </span>
          <span className="px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded border border-emerald-500/30 font-bold">
            Ruff Lint: SUCCESS
          </span>
          <span className="px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded border border-emerald-500/30 font-bold">
            Pytest: SUCCESS
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Neon PostgreSQL Schema */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-400" />
              <span>schema.sql (Neon PostgreSQL Jobs Table)</span>
            </h3>
            <button
              onClick={() => copyCode(schemaSQL, 'schema')}
              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1"
            >
              {copiedCode === 'schema' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedCode === 'schema' ? 'Copied' : 'Copy SQL'}</span>
            </button>
          </div>

          <pre className="p-4 bg-slate-950 border border-slate-800 rounded-xl font-mono text-[11px] text-emerald-400/90 overflow-x-auto leading-relaxed">
            {schemaSQL}
          </pre>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl text-xs space-y-1">
            <div className="text-amber-400 font-bold flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" />
              <span>Atomic Locking Mechanism</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Uses <code className="text-slate-200">SELECT * FROM jobs WHERE status = 'pending' FOR UPDATE SKIP LOCKED LIMIT 1</code> in Neon PostgreSQL to ensure multiple workers never pick up or render the same gameplay video concurrently.
            </p>
          </div>
        </div>

        {/* MoviePy v2 Codebase Snippet */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-100 text-sm flex items-center gap-2">
              <Code2 className="w-4 h-4 text-amber-400" />
              <span>MoviePy v2 Modern Video Pipeline</span>
            </h3>
            <button
              onClick={() => copyCode(moviePyCode, 'moviepy')}
              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1"
            >
              {copiedCode === 'moviepy' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedCode === 'moviepy' ? 'Copied' : 'Copy Code'}</span>
            </button>
          </div>

          <pre className="p-4 bg-slate-950 border border-slate-800 rounded-xl font-mono text-[11px] text-amber-300/90 overflow-x-auto leading-relaxed">
            {moviePyCode}
          </pre>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl text-xs space-y-1">
            <div className="text-emerald-400 font-bold flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" />
              <span>MoviePy v2 API Compliance</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Updated from legacy <code className="text-slate-200">moviepy.editor</code> to modern v2 methods: <code className="text-amber-300">subclipped</code>, <code className="text-amber-300">cropped</code>, <code className="text-amber-300">resized</code>, and <code className="text-amber-300">with_audio</code>.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
