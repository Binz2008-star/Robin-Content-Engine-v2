import { useState, useEffect, useRef, useCallback } from 'react';
import { Navbar } from './components/Navbar';
import { DashboardOverview } from './components/DashboardOverview';
import { QueueTable } from './components/QueueTable';
import { EnqueueModal } from './components/EnqueueModal';
import { ScriptGeneratorStudio } from './components/ScriptGeneratorStudio';
import { VideoCanvasPlayer } from './components/VideoCanvasPlayer';
import { ArchitectureSchemaView } from './components/ArchitectureSchemaView';
import { CLIConsoleModal } from './components/CLIConsoleModal';
import {
  VideoJob,
  JobCounts,
  ConnectionStatus,
  StudioTab,
  EnqueueJobRequest,
} from './types';
import { apiClient } from './api/client';
import { POLLING_INTERVAL_MS } from './config';
import { WifiOff } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<StudioTab>('overview');
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [counts, setCounts] = useState<JobCounts>({
    pending: 0,
    processing: 0,
    rendered: 0,
    uploaded: 0,
    failed: 0,
    quarantined: 0,
    total: 0,
  });
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isProcessingWorker, setIsProcessingWorker] = useState(false);
  const [isEnqueueOpen, setIsEnqueueOpen] = useState(false);
  const [isCLIOpen, setIsCLIOpen] = useState(false);
  const [selectedJobForPreview, setSelectedJobForPreview] = useState<VideoJob | null>(null);

  const activeAbortController = useRef<AbortController | null>(null);

  const fetchJobsAndHealth = useCallback(async () => {
    if (activeAbortController.current) {
      activeAbortController.current.abort();
    }
    const controller = new AbortController();
    activeAbortController.current = controller;

    try {
      if (apiClient.isDemoMode()) {
        setConnectionStatus('demo_mode');
      } else {
        await apiClient.getHealth({ signal: controller.signal });
        setConnectionStatus('connected');
      }

      const fetchedJobs = await apiClient.getJobs({ signal: controller.signal });
      const fetchedCounts = await apiClient.getJobCounts({ signal: controller.signal });

      setJobs(fetchedJobs);
      setCounts(fetchedCounts);
      setErrorMessage(null);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      console.error('Failed to fetch API data:', err);

      if (!apiClient.isDemoMode()) {
        setConnectionStatus('offline');
        setErrorMessage(
          err instanceof Error
            ? err.message
            : 'Failed to connect to backend API.'
        );
      }
    }
  }, []);

  useEffect(() => {
    fetchJobsAndHealth();

    let intervalId: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (!intervalId && !document.hidden) {
        intervalId = setInterval(() => {
          if (!document.hidden) {
            fetchJobsAndHealth();
          }
        }, POLLING_INTERVAL_MS);
      }
    };

    const stopPolling = () => {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopPolling();
        if (activeAbortController.current) {
          activeAbortController.current.abort();
        }
      } else {
        fetchJobsAndHealth();
        startPolling();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    startPolling();

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (activeAbortController.current) {
        activeAbortController.current.abort();
      }
    };
  }, [fetchJobsAndHealth]);

  const handleEnqueueJob = async (payload: EnqueueJobRequest) => {
    try {
      await apiClient.enqueueJob(payload);
      setIsEnqueueOpen(false);
      await fetchJobsAndHealth();
    } catch (err) {
      console.error('Enqueue job failed:', err);
      alert(`Enqueue failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleRunWorker = async (renderOnly = false) => {
    setIsProcessingWorker(true);
    try {
      await apiClient.runWorker(renderOnly);
      await fetchJobsAndHealth();
    } catch (err) {
      console.error('Worker run failed:', err);
    } finally {
      setIsProcessingWorker(false);
    }
  };

  const handleSelectJobForPreview = (job: VideoJob) => {
    setSelectedJobForPreview(job);
    setActiveTab('schema');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased selection:bg-amber-500 selection:text-slate-950">
      <Navbar
        connectionStatus={connectionStatus}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onOpenEnqueue={() => setIsEnqueueOpen(true)}
        onOpenCLI={() => setIsCLIOpen(true)}
        onRefresh={fetchJobsAndHealth}
      />

      {connectionStatus === 'offline' && errorMessage && (
        <div className="bg-rose-950/80 border-b border-rose-800 text-rose-200 px-4 py-3 text-xs flex items-center justify-between">
          <div className="max-w-7xl mx-auto flex items-center gap-2 w-full">
            <WifiOff className="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              <strong>Backend Offline:</strong> {errorMessage} Live mode will not silently load demo data.
            </span>
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {activeTab === 'overview' && (
          <DashboardOverview
            counts={counts}
            connectionStatus={connectionStatus}
            onOpenEnqueueModal={() => setIsEnqueueOpen(true)}
          />
        )}

        {activeTab === 'queue' && (
          <QueueTable
            jobs={jobs}
            onRunWorkerJob={(_jobId, renderOnly) => handleRunWorker(renderOnly)}
            onSelectJobForPreview={handleSelectJobForPreview}
            isProcessing={isProcessingWorker}
          />
        )}

        {activeTab === 'script' && <ScriptGeneratorStudio />}

        {activeTab === 'schema' && (
          <div className="space-y-8">
            <VideoCanvasPlayer job={selectedJobForPreview} />
            <ArchitectureSchemaView />
          </div>
        )}
      </main>

      <footer className="border-t border-slate-900 bg-slate-950/80 py-6 mt-12 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-300">Robin Engine Control Studio v2</span>
            <span>•</span>
            <span>Robin Life & Gaming Shorts Pipeline</span>
          </div>
          <div className="font-mono text-[11px] text-slate-400">
            Branch: feat/studio-ui | Target Dir: studio/
          </div>
        </div>
      </footer>

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
