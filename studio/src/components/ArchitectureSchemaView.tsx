import React, { useState } from 'react';
import {
  Check,
  CheckCircle2,
  Code2,
  Copy,
  Cpu,
  Database,
  ShieldCheck,
} from 'lucide-react';
import { copyTextToClipboard } from '../lib/clipboard';

const QUEUE_FIELDS = [
  'id',
  'source_path',
  'source_url',
  'source_title',
  'rights_confirmed',
  'rights_note',
  'status',
  'generated_title',
  'generated_description',
  'generated_tags',
  'generated_script',
  'output_path',
  'youtube_id',
  'attempts',
  'last_error',
  'claimed_at',
  'completed_at',
  'created_at',
  'updated_at',
];

const QUEUE_STATUSES = [
  'pending',
  'processing',
  'rendered',
  'uploaded',
  'failed',
  'quarantined',
];

const MOVIEPY_EXAMPLE = `# Backend-only MoviePy v2 processing outline
clip = VideoFileClip(input_path)
clip = clip.subclipped(0, min(58, clip.duration))
clip = clip.cropped(...).resized((1080, 1920))
final_clip = clip.with_audio(final_audio)
final_clip.write_videofile(
    output_path,
    codec="libx264",
    audio_codec="aac",
)`;

export const ArchitectureSchemaView: React.FC = () => {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  const copyMoviePyExample = async () => {
    setCopyError(null);
    const success = await copyTextToClipboard(MOVIEPY_EXAMPLE);

    if (!success) {
      setCopied(false);
      setCopyError('Copy failed. Clipboard permission is unavailable.');
      return;
    }

    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
            <Cpu className="w-5 h-5" />
            <span>Robin Engine Architecture Reference</span>
          </div>
          <h2 className="text-xl font-black text-slate-100 mt-1">
            Canonical Queue & Backend Processing
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Read-only facts aligned with the deployed Neon production schema.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 p-2.5 rounded-xl border border-slate-800 text-xs font-mono">
          <span className="px-2 py-1 bg-slate-800 text-slate-300 rounded border border-slate-700 font-bold">
            Backend connection required
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-emerald-400" />
            <h3 className="font-bold text-slate-100 text-sm">
              public.video_queue
            </h3>
          </div>

          <p className="text-xs text-slate-400 leading-relaxed">
            The Studio reads and changes queue state only through the FastAPI
            backend. Database credentials remain backend-only and are never
            embedded in frontend variables or bundles.
          </p>

          <div>
            <h4 className="text-xs font-semibold text-slate-300 mb-2">
              Canonical fields
            </h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {QUEUE_FIELDS.map((field) => (
                <code
                  key={field}
                  className="rounded-lg border border-slate-800 bg-slate-950 px-2 py-1 text-[11px] text-emerald-300"
                >
                  {field}
                </code>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-slate-300 mb-2">
              Queue statuses
            </h4>
            <div className="flex flex-wrap gap-2">
              {QUEUE_STATUSES.map((status) => (
                <span
                  key={status}
                  className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] font-mono text-amber-300"
                >
                  {status}
                </span>
              ))}
            </div>
          </div>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl text-xs space-y-2">
            <div className="text-amber-400 font-bold flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" />
              <span>Atomic worker claims</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Pending jobs are claimed with{' '}
              <code className="text-slate-200">
                FOR UPDATE SKIP LOCKED
              </code>{' '}
              so concurrent workers do not process the same video twice.
            </p>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              YouTube uploads remain Private by backend default until manual
              review is complete.
            </p>
          </div>
        </section>

        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Code2 className="w-4 h-4 text-amber-400" />
              <h3 className="font-bold text-slate-100 text-sm">
                MoviePy v2 backend outline
              </h3>
            </div>
            <button
              type="button"
              onClick={copyMoviePyExample}
              aria-label="Copy MoviePy example"
              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              <span>{copied ? 'Copied' : 'Copy Code'}</span>
            </button>
          </div>

          {copyError && (
            <p role="status" className="text-xs text-rose-400">
              {copyError}
            </p>
          )}

          <pre className="p-4 bg-slate-950 border border-slate-800 rounded-xl font-mono text-[11px] text-amber-300/90 overflow-x-auto leading-relaxed">
            {MOVIEPY_EXAMPLE}
          </pre>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl text-xs space-y-1">
            <div className="text-emerald-400 font-bold flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" />
              <span>Backend-only execution</span>
            </div>
            <p className="text-slate-400 text-[11px] leading-relaxed">
              Rendering, DeepSeek generation, neural TTS, and YouTube OAuth are
              performed by backend workers, never by the browser.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
};
