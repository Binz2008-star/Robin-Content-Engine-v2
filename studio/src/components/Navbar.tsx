import React from 'react';
import { Play, Plus, Terminal, RefreshCw, Cpu, Youtube, GitPullRequest, CheckCircle2 } from 'lucide-react';
import { SystemInfo } from '../types';

interface NavbarProps {
  systemInfo: SystemInfo | null;
  onOpenEnqueue: () => void;
  onOpenCLI: () => void;
  onRunWorker: (renderOnly: boolean) => void;
  isProcessingWorker: boolean;
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  systemInfo,
  onOpenEnqueue,
  onOpenCLI,
  onRunWorker,
  isProcessingWorker,
  activeTab,
  setActiveTab,
}) => {
  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-40 text-slate-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand & Repo Info */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-orange-600 to-red-600 flex items-center justify-center shadow-lg shadow-orange-950/40">
              <Cpu className="w-5 h-5 text-white animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-bold text-lg tracking-tight text-white">
                  Robin Engine
                </h1>
                <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  Shorts Studio UI
                </span>
                <span className="px-2 py-0.5 text-[10px] font-mono font-bold rounded bg-rose-500/20 text-rose-300 border border-rose-500/40">
                  DEMO DATA
                </span>
              </div>
              <p className="text-xs text-slate-400 flex items-center gap-2">
                <span>Robin Life & Gaming</span>
                <span className="text-slate-600">•</span>
                <span className="text-emerald-400 font-mono flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" />
                  {systemInfo?.commitHash ? systemInfo.commitHash.slice(0, 7) : "779c4d6"}
                </span>
                <span className="text-slate-600">•</span>
                <span className="text-amber-400/90 flex items-center gap-1">
                  <GitPullRequest className="w-3 h-3" />
                  Branch: feat/studio-ui (PR #1)
                </span>
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="hidden md:flex items-center gap-1 bg-slate-950/60 p-1 rounded-xl border border-slate-800/80">
            {[
              { id: 'dashboard', label: 'Dashboard & Queue' },
              { id: 'script-studio', label: 'DeepSeek & TTS Studio' },
              { id: 'video-canvas', label: 'MoviePy v2 Canvas' },
              { id: 'architecture', label: 'Architecture & Schema' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all ${
                  activeTab === tab.id
                    ? 'bg-amber-500 text-slate-950 font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={onOpenCLI}
              title="View CLI Commands"
              className="p-2 rounded-xl bg-slate-800/90 text-slate-300 hover:text-white hover:bg-slate-700 transition border border-slate-700/60 flex items-center gap-1.5 text-xs font-mono"
            >
              <Terminal className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">robin-engine</span>
            </button>

            <button
              onClick={() => onRunWorker(false)}
              disabled={isProcessingWorker}
              className={`px-3 py-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition border ${
                isProcessingWorker
                  ? 'bg-amber-950/40 text-amber-500 border-amber-800/50 cursor-wait'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500/50 shadow-md shadow-emerald-950/30'
              }`}
            >
              <Play className={`w-3.5 h-3.5 ${isProcessingWorker ? 'animate-spin' : ''}`} />
              <span>{isProcessingWorker ? 'Simulating Worker...' : 'Run Worker (Simulated)'}</span>
            </button>

            <button
              onClick={onOpenEnqueue}
              className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 font-bold text-xs flex items-center gap-1.5 hover:from-amber-400 hover:to-orange-500 transition shadow-md shadow-orange-950/40"
            >
              <Plus className="w-4 h-4 stroke-[3]" />
              <span>Enqueue Gameplay</span>
            </button>
          </div>
        </div>

        {/* Mobile Nav Tabs */}
        <div className="flex md:hidden overflow-x-auto gap-1 py-2 border-t border-slate-800/60 text-xs no-scrollbar">
          {[
            { id: 'dashboard', label: 'Dashboard & Queue' },
            { id: 'script-studio', label: 'DeepSeek & TTS Studio' },
            { id: 'video-canvas', label: 'MoviePy Canvas' },
            { id: 'architecture', label: 'Architecture' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1 whitespace-nowrap text-xs font-medium rounded-lg transition ${
                activeTab === tab.id
                  ? 'bg-amber-500 text-slate-950 font-bold'
                  : 'text-slate-400 bg-slate-800/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
};
