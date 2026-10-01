import React from 'react';
import { Plus, Terminal, Cpu, RefreshCw, Radio } from 'lucide-react';
import { ConnectionStatus, StudioTab } from '../types';

interface NavbarProps {
  connectionStatus: ConnectionStatus;
  activeTab: StudioTab;
  setActiveTab: (tab: StudioTab) => void;
  onOpenEnqueue: () => void;
  onOpenCLI: () => void;
  onRefresh: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  connectionStatus,
  activeTab,
  setActiveTab,
  onOpenEnqueue,
  onOpenCLI,
  onRefresh,
}) => {
  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-40 text-slate-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-orange-600 to-red-600 flex items-center justify-center shadow-lg shadow-orange-950/40">
              <Cpu className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-bold text-lg tracking-tight text-white">
                  Robin Engine
                </h1>
                <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  Control Studio v2
                </span>

                {connectionStatus === 'demo_mode' && (
                  <span className="px-2 py-0.5 text-[10px] font-mono font-bold rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1">
                    <Radio className="w-3 h-3 text-amber-400" />
                    <span>DEMO MODE</span>
                  </span>
                )}

                {connectionStatus === 'connected' && (
                  <span className="px-2 py-0.5 text-[10px] font-mono font-bold rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                    <span>API ONLINE</span>
                  </span>
                )}

                {connectionStatus === 'offline' && (
                  <span className="px-2 py-0.5 text-[10px] font-mono font-bold rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-rose-400" />
                    <span>OFFLINE</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                Robin Life & Gaming Shorts Pipeline
              </p>
            </div>
          </div>

          {/* Nav Tabs */}
          <nav className="hidden md:flex items-center gap-1 bg-slate-950/60 p-1 rounded-xl border border-slate-800/80">
            {[
              { id: 'overview' as StudioTab, label: 'Overview' },
              { id: 'queue' as StudioTab, label: 'Queue Jobs' },
              { id: 'script' as StudioTab, label: 'DeepSeek Script' },
              { id: 'schema' as StudioTab, label: 'Canvas & Schema' },
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

          {/* Header Action Buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={onRefresh}
              title="Refresh Queue State"
              className="p-2 rounded-xl bg-slate-800 text-slate-300 hover:text-white transition border border-slate-700"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <button
              onClick={onOpenCLI}
              title="View CLI Commands"
              className="p-2 rounded-xl bg-slate-800/90 text-slate-300 hover:text-white hover:bg-slate-700 transition border border-slate-700/60 flex items-center gap-1.5 text-xs font-mono"
            >
              <Terminal className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">robin-engine</span>
            </button>

            <button
              onClick={onOpenEnqueue}
              className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 font-bold text-xs flex items-center gap-1.5 hover:from-amber-400 hover:to-orange-500 transition shadow-md shadow-orange-950/40"
            >
              <Plus className="w-4 h-4 stroke-[3]" />
              <span>Enqueue Job</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
