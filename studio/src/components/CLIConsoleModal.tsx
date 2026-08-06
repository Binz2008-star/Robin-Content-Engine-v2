import React, { useState } from 'react';
import { Terminal, Copy, Check, Play, RefreshCw, Layers } from 'lucide-react';

interface CLIConsoleModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRunOnceCLI: (renderOnly: boolean) => void;
}

export const CLIConsoleModal: React.FC<CLIConsoleModalProps> = ({
  isOpen,
  onClose,
  onRunOnceCLI,
}) => {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);
  const [customTerminalInput, setCustomTerminalInput] = useState('');
  const [terminalLogs, setTerminalLogs] = useState<string[]>([
    '$ robin-engine --version',
    'robin-engine 1.0.0 (feat/initial-engine, commit 779c4d62)',
    'Neon PostgreSQL connection verified.',
    'DeepSeek JSON generator & Pydantic validator initialized.',
    'MoviePy v2 video renderer ready.',
  ]);

  if (!isOpen) return null;

  const copyToClipboard = (cmd: string, key: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(key);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const handleCommandSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customTerminalInput.trim()) return;

    const input = customTerminalInput.trim();
    setTerminalLogs((prev) => [...prev, `$ ${input}`]);

    if (input.includes('run-once') && input.includes('--render-only')) {
      setTerminalLogs((prev) => [
        ...prev,
        '[WORKER] Processing pending job atomically...',
        '[MOVIEPY] Rendered 9:16 vertical 1080x1920 video with ar-AE-HamdanNeural voiceover.',
        '[DONE] Render complete. Skipped upload.',
      ]);
      onRunOnceCLI(true);
    } else if (input.includes('run-once')) {
      setTerminalLogs((prev) => [
        ...prev,
        '[WORKER] Processing pending job atomically...',
        '[MOVIEPY] Rendered 9:16 vertical 1080x1920 video.',
        '[YOUTUBE] Uploaded Private video via resumable OAuth2.',
      ]);
      onRunOnceCLI(false);
    } else if (input.includes('enqueue-local')) {
      setTerminalLogs((prev) => [
        ...prev,
        '[QUEUE] Video enqueued with confirmed rights into Neon PostgreSQL database.',
      ]);
    } else {
      setTerminalLogs((prev) => [...prev, `Command executed: ${input}`]);
    }

    setCustomTerminalInput('');
  };

  const commandsList = [
    {
      key: 'enqueue',
      label: '1. Enqueue Local Gameplay Video (with mandatory rights note):',
      cmd: `robin-engine enqueue-local "C:\\media\\my-gameplay.mp4" ^\n  --title "My original Fortnite match" ^\n  --rights-note "Recorded by Robin for Robin Life & Gaming" ^\n  --confirm-rights`,
    },
    {
      key: 'render-only',
      label: '2. Run Pipeline (Render Only - Review before upload):',
      cmd: `robin-engine run-once --render-only`,
    },
    {
      key: 'upload-run',
      label: '3. Run Full Pipeline (Render + Resumable YouTube Upload):',
      cmd: `robin-engine run-once`,
    },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Terminal Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <h3 className="font-bold text-slate-100 text-sm font-mono">
              robin-engine CLI Terminal
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-200 text-xs font-mono"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-5 text-xs">
          {/* Copyable CLI Commands */}
          <div className="space-y-3">
            <h4 className="font-bold text-slate-200 text-xs flex items-center gap-2">
              <Layers className="w-4 h-4 text-amber-400" />
              <span>Standard CLI Commands Syntax</span>
            </h4>

            {commandsList.map((item) => (
              <div key={item.key} className="space-y-1">
                <div className="text-slate-400 font-medium text-[11px]">{item.label}</div>
                <div className="relative group">
                  <pre className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl font-mono text-[11px] text-amber-300 overflow-x-auto whitespace-pre-wrap">
                    {item.cmd}
                  </pre>
                  <button
                    onClick={() => copyToClipboard(item.cmd, item.key)}
                    className="absolute right-2 top-2 p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-[10px] font-mono flex items-center gap-1 transition"
                  >
                    {copiedCmd === item.key ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedCmd === item.key ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Interactive Live Terminal Feed */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-slate-400 text-[11px] font-mono">
              <span>Interactive CLI Output Logs:</span>
              <span className="text-emerald-400">STATUS: READY</span>
            </div>

            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 font-mono text-[11px] text-emerald-400/90 space-y-1.5 h-44 overflow-y-auto">
              {terminalLogs.map((log, index) => (
                <div key={index} className="flex gap-2 leading-relaxed">
                  <span className="text-slate-600 select-none">&gt;</span>
                  <span>{log}</span>
                </div>
              ))}
            </div>

            {/* Command Input */}
            <form onSubmit={handleCommandSubmit} className="flex gap-2">
              <input
                type="text"
                placeholder="Type command e.g. robin-engine run-once --render-only"
                value={customTerminalInput}
                onChange={(e) => setCustomTerminalInput(e.target.value)}
                className="flex-1 px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl font-mono text-xs text-amber-300 focus:outline-none focus:border-amber-500/50"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-xl font-mono transition"
              >
                Execute
              </button>
            </form>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-800 bg-slate-950 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold"
          >
            Close CLI Modal
          </button>
        </div>
      </div>
    </div>
  );
};
