import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { DashboardOverview } from './components/DashboardOverview';
import { QueueTable } from './components/QueueTable';
import { EnqueueModal } from './components/EnqueueModal';
import { ScriptGeneratorStudio } from './components/ScriptGeneratorStudio';
import { VideoCanvasPlayer } from './components/VideoCanvasPlayer';
import { ArchitectureSchemaView } from './components/ArchitectureSchemaView';
import { CLIConsoleModal } from './components/CLIConsoleModal';
import { EngineJob, SystemInfo, ScriptData } from './types';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [jobs, setJobs] = useState<EngineJob[]>([]);
  const [counts, setCounts] = useState({
    pending: 0,
    processing: 0,
    rendered: 0,
    uploaded: 0,
    failed: 0,
    quarantined: 0,
  });
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [isProcessingWorker, setIsProcessingWorker] = useState(false);
  const [isEnqueueOpen, setIsEnqueueOpen] = useState(false);
  const [isCLIOpen, setIsCLIOpen] = useState(false);
  const [selectedJobForPreview, setSelectedJobForPreview] = useState<EngineJob | null>(null);

  // Fetch Queue Jobs & System Specs
  const fetchQueue = async () => {
    try {
      const res = await fetch('/api/queue');
      const data = await res.json();
      if (data.jobs) {
        setJobs(data.jobs);
        setCounts(data.counts || {
          pending: 0,
          processing: 0,
          rendered: 0,
          uploaded: 0,
          failed: 0,
          quarantined: 0,
        });
      }
    } catch (e) {
      console.error('Error fetching queue:', e);
    }
  };

  const fetchSystemInfo = async () => {
    try {
      const res = await fetch('/api/system-info');
      const data = await res.json();
      setSystemInfo(data);
    } catch (e) {
      console.error('Error fetching system info:', e);
    }
  };

  useEffect(() => {
    fetchQueue();
    fetchSystemInfo();

    // Auto polling every 4 seconds for job updates
    const interval = setInterval(fetchQueue, 4000);
    return () => clearInterval(interval);
  }, []);

  // Enqueue New Video Job
  const handleEnqueueJob = async (data: {
    title: string;
    sourcePath: string;
    rightsNote: string;
    confirmRights: boolean;
    privacy: 'private' | 'unlisted' | 'public';
    customScript?: ScriptData;
  }) => {
    try {
      const res = await fetch('/api/queue/enqueue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json();
      if (result.success) {
        fetchQueue();
      }
    } catch (e) {
      console.error('Enqueue error:', e);
    }
  };

  // Run Worker (All pending jobs or specific job)
  const handleRunWorker = async (renderOnly: boolean = false, jobId?: string) => {
    setIsProcessingWorker(true);
    try {
      const res = await fetch('/api/queue/run-worker', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId, renderOnly }),
      });
      const result = await res.json();
      if (result.success) {
        fetchQueue();
      }
    } catch (e) {
      console.error('Worker error:', e);
    } finally {
      setTimeout(() => setIsProcessingWorker(false), 3000);
    }
  };

  // Update Job Status (Quarantine, Retry, Delete)
  const handleUpdateJobStatus = async (jobId: string, action: 'quarantine' | 'retry' | 'delete') => {
    try {
      const res = await fetch('/api/queue/update-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId, action }),
      });
      const result = await res.json();
      if (result.success) {
        fetchQueue();
      }
    } catch (e) {
      console.error('Update status error:', e);
    }
  };

  const handleSelectJobForPreview = (job: EngineJob) => {
    setSelectedJobForPreview(job);
    setActiveTab('video-canvas');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased selection:bg-amber-500 selection:text-slate-950">
      {/* Top Header Navbar */}
      <Navbar
        systemInfo={systemInfo}
        onOpenEnqueue={() => setIsEnqueueOpen(true)}
        onOpenCLI={() => setIsCLIOpen(true)}
        onRunWorker={(renderOnly) => handleRunWorker(renderOnly)}
        isProcessingWorker={isProcessingWorker}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {activeTab === 'dashboard' && (
          <div className="space-y-8">
            <DashboardOverview
              jobs={jobs}
              counts={counts}
              onRunWorker={(renderOnly) => handleRunWorker(renderOnly)}
              isProcessingWorker={isProcessingWorker}
            />

            <QueueTable
              jobs={jobs}
              onRunWorkerJob={(jobId, renderOnly) => handleRunWorker(renderOnly, jobId)}
              onUpdateJobStatus={handleUpdateJobStatus}
              onSelectJobForPreview={handleSelectJobForPreview}
              isProcessing={isProcessingWorker}
            />
          </div>
        )}

        {activeTab === 'script-studio' && (
          <ScriptGeneratorStudio />
        )}

        {activeTab === 'video-canvas' && (
          <VideoCanvasPlayer activeJob={selectedJobForPreview} />
        )}

        {activeTab === 'architecture' && (
          <ArchitectureSchemaView />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/80 py-6 mt-12 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-300">Robin Engine Studio UI</span>
            <span>•</span>
            <span>Robin Life & Gaming Shorts Pipeline</span>
          </div>
          <div className="font-mono text-[11px] text-slate-400">
            Branch: feat/studio-ui | Target Dir: studio/
          </div>
        </div>
      </footer>

      {/* Modals */}
      <EnqueueModal
        isOpen={isEnqueueOpen}
        onClose={() => setIsEnqueueOpen(false)}
        onEnqueue={handleEnqueueJob}
      />

      <CLIConsoleModal
        isOpen={isCLIOpen}
        onClose={() => setIsCLIOpen(false)}
        onRunOnceCLI={(renderOnly) => handleRunWorker(renderOnly)}
      />
    </div>
  );
}
