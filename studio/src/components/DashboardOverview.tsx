import React from 'react';
import { Database, ShieldCheck, Film, Volume2, Youtube, AlertTriangle, Sparkles, Plus, Clock, CheckCircle2 } from 'lucide-react';
import { JobCounts, ConnectionStatus } from '../types';

interface DashboardOverviewProps {
  counts: JobCounts;
  connectionStatus: ConnectionStatus;
  onOpenEnqueueModal: () => void;
}

export const DashboardOverview: React.FC<DashboardOverviewProps> = ({
  counts,
  connectionStatus,
  onOpenEnqueueModal,
}) => {
  return (
    <div className="space-y-6">
      {/* Top Banner Alert / Engine Status */}
      <div className="bg-gradient-to-r from-slate-900 via-amber-950/20 to-slate-900 border border-amber-500/20 rounded-2xl p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-lg shadow-black/40">
        <div className="flex items-start gap-3">
          <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400 mt-0.5 shrink-0">
            <Sparkles className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-bold text-white tracking-wide">
                Robin Engine Studio UI
              </h2>
              {connectionStatus === 'demo_mode' && (
                <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded">
                  DEMO MODE (MOCK DATA)
                </span>
              )}
              {connectionStatus === 'connected' && (
                <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider font-mono font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 rounded">
                  FASTAPI BACKEND CONNECTED
                </span>
              )}
              {connectionStatus === 'offline' && (
                <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider font-mono font-bold bg-rose-500/10 text-rose-300 border border-rose-500/30 rounded">
                  BACKEND OFFLINE
                </span>
              )}
              {connectionStatus === 'config_error' && (
                <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider font-mono font-bold bg-purple-500/10 text-purple-300 border border-purple-500/30 rounded">
                  CONFIG ERROR
                </span>
              )}
            </div>
            <p className="text-xs text-slate-300 mt-1 leading-relaxed">
              Managing Robin Life & Gaming content queue. Real Robin Engine API endpoints run via Python FastAPI backend (<code className="text-amber-300 font-mono">src/robin_content_engine/</code>).
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-end md:self-center shrink-0">
          <button
            onClick={onOpenEnqueueModal}
            className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 text-slate-950 font-bold text-xs transition shadow flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4 stroke-[3]" />
            <span>Enqueue Gameplay Job</span>
          </button>
        </div>
      </div>

      {/* Metrics Cards Grid - All 6 Statuses */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 sm:gap-4">
        {/* Pending Jobs */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-amber-500/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Pending</span>
            <Clock className="w-4 h-4 text-amber-400" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-amber-400 font-mono">{counts.pending}</span>
            <span className="text-[10px] text-slate-500">Awaiting Run</span>
          </div>
        </div>

        {/* Processing */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-blue-500/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Processing</span>
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-blue-400 font-mono">{counts.processing}</span>
            <span className="text-[10px] text-slate-500">Locked</span>
          </div>
        </div>

        {/* Rendered */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-indigo-500/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Rendered</span>
            <Film className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-indigo-400 font-mono">{counts.rendered}</span>
            <span className="text-[10px] text-slate-500">1080x1920 9:16</span>
          </div>
        </div>

        {/* Uploaded */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-emerald-500/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Uploaded</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-emerald-400 font-mono">{counts.uploaded}</span>
            <span className="text-[10px] text-slate-500">Private Default</span>
          </div>
        </div>

        {/* Failed */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-rose-500/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Failed</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-rose-400 font-mono">{counts.failed}</span>
            <span className="text-[10px] text-slate-500">Retryable</span>
          </div>
        </div>

        {/* Quarantined */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-sm hover:border-amber-600/40 transition">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Quarantined</span>
            <ShieldCheck className="w-4 h-4 text-amber-500" />
          </div>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="text-2xl font-black text-slate-300 font-mono">{counts.quarantined}</span>
            <span className="text-[10px] text-slate-500">Isolated</span>
          </div>
        </div>
      </div>

      {/* Engine Components Status Pills */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg shrink-0">
            <Database className="w-4 h-4" />
          </div>
          <div>
            <div className="text-slate-200 font-semibold">
              {connectionStatus === 'demo_mode'
                ? 'Simulated In-Memory Queue'
                : 'Neon PostgreSQL Lock Queue'}
            </div>
            <div className="text-slate-400 text-[11px]">
              {connectionStatus === 'demo_mode'
                ? 'Client-side demo storage for studio validation'
                : 'Atomic job reservation preventing worker collision'}
            </div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 flex items-center gap-3">
          <div className="p-2 bg-amber-500/10 text-amber-400 rounded-lg shrink-0">
            <Volume2 className="w-4 h-4" />
          </div>
          <div>
            <div className="text-slate-200 font-semibold">ar-AE-HamdanNeural Voice</div>
            <div className="text-slate-400 text-[11px]">Authentic Emirati Arabic dialect voiceover</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 flex items-center gap-3">
          <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg shrink-0">
            <Film className="w-4 h-4" />
          </div>
          <div>
            <div className="text-slate-200 font-semibold">MoviePy v2 Modern API</div>
            <div className="text-slate-400 text-[11px]">subclipped, cropped, resized, with_audio</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 flex items-center gap-3">
          <div className="p-2 bg-red-500/10 text-red-400 rounded-lg shrink-0">
            <Youtube className="w-4 h-4" />
          </div>
          <div>
            <div className="text-slate-200 font-semibold">YouTube OAuth2 Resumable</div>
            <div className="text-slate-400 text-[11px]">Private upload with exponential backoff retry</div>
          </div>
        </div>
      </div>
    </div>
  );
};
