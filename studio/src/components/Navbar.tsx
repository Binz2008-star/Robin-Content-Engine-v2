import React from 'react';
import { Plus, Terminal, Cpu, RefreshCw, Radio, WifiOff, AlertCircle, Clock, Database, Check } from 'lucide-react';
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
  const renderConnectionBadge = () => {
    switch (connectionStatus) {
      case 'demo_mode':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1">
            <Radio className="w-3 h-3 text-amber-400" />
            <span>DEMO MODE</span>
          </span>
        );
      case 'connecting':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/40 flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
            <span>CONNECTING...</span>
          </span>
        );
      case 'connected':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1">
            <Check className="w-3 h-3 text-emerald-400" />
            <span>BACKEND CONNECTED</span>
          </span>
        );
      case 'offline':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center gap-1">
            <WifiOff className="w-3 h-3 text-rose-400" />
            <span>BACKEND OFFLINE</span>
          </span>
        );
      case 'config_error':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/40 flex items-center gap-1">
            <AlertCircle className="w-3 h-3 text-purple-400" />
            <span>CONFIG ERROR</span>
          </span>
        );
      case 'timeout':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-orange-500/20 text-orange-300 border border-orange-500/40 flex items-center gap-1">
            <Clock className="w-3 h-3 text-orange-400" />
            <span>TIMED OUT</span>
          </span>
        );
      case 'db_unavailable':
        return (
          <span className="px-2.5 py-0.5 text-[10px] font-mono font-bold rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center gap-1">
            <Database className="w-3 h-3 text-rose-400" />
            <span>DB UNAVAILABLE</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <header className="bg-slate-900 border-b border-slate-800 sticky top-0 z-40 text-slate-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-2">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-orange-600 to-red-600 flex items-center justify-center shadow-lg shadow-orange-950/40 shrink-0">
              <Cpu className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="font-bold text-base sm:text-lg tracking-tight text-white">
                  Robin Engine
                </h1>
                <span className="hidden sm:inline-block px-2 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  Control Studio v2
                </span>
                {renderConnectionBadge()}
              </div>
              <p className="text-[11px] sm:text-xs text-slate-400 hidden sm:block">
                Robin Life & Gaming Shorts Pipeline
              </p>
            </div>
          </div>

          {/* Desktop Nav Tabs */}
          <nav aria-label="Main Navigation" className="hidden lg:flex items-center gap-1 bg-slate-950/60 p-1 rounded-xl border border-slate-800/80">
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
              aria-label="Refresh Queue State"
              title="Refresh Queue State"
              className="p-2 rounded-xl bg-slate-800 text-slate-300 hover:text-white transition border border-slate-700"
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <button
              onClick={onOpenCLI}
              aria-label="View CLI Commands"
              title="View CLI Commands"
              className="p-2 rounded-xl bg-slate-800/90 text-slate-300 hover:text-white hover:bg-slate-700 transition border border-slate-700/60 flex items-center gap-1.5 text-xs font-mono"
            >
              <Terminal className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">robin-engine</span>
            </button>

            <button
              onClick={onOpenEnqueue}
              className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 font-bold text-xs flex items-center gap-1.5 hover:from-amber-400 hover:to-orange-500 transition shadow-md shadow-orange-950/40 shrink-0"
            >
              <Plus className="w-4 h-4 stroke-[3]" />
              <span className="hidden sm:inline">Enqueue Job</span>
              <span className="sm:hidden">Enqueue</span>
            </button>
          </div>
        </div>

        {/* Mobile Nav Tabs Bar */}
        <div className="lg:hidden flex items-center gap-1 pb-2 overflow-x-auto no-scrollbar border-t border-slate-800/60 pt-2">
          {[
            { id: 'overview' as StudioTab, label: 'Overview' },
            { id: 'queue' as StudioTab, label: 'Queue Jobs' },
            { id: 'script' as StudioTab, label: 'DeepSeek Script' },
            { id: 'schema' as StudioTab, label: 'Canvas & Schema' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1 text-xs font-medium rounded-lg whitespace-nowrap transition-all ${
                activeTab === tab.id
                  ? 'bg-amber-500 text-slate-950 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 bg-slate-950/40'
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
