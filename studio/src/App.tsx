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
  JobActionType,
} from './types';
import { apiClient, ApiError } from './api/client';
import { POLLING_INTERVAL_MS } from './config';
import { WifiOff, AlertCircle, Clock, Database } from 'lucide-react';

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
      if (apiClient.isConfigError()) {
        setConnectionStatus('config_error');
        setErrorMessage(
          'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
        );
        setJobs([]);
        setCounts({
          pending: 0,
          processing: 0,
          rendered: 0,
          uploaded: 0,
          failed: 0,
          quarantined: 0,
          total: 0,
        });
        return;
      }

      if (apiClient.isDemoMode()) {
        setConnectionStatus('demo_mode');
        setErrorMessage(null);
      } else {
        const health = await apiClient.getHealth({ signal: controller.signal });
        if (health.database && health.database.includes('disconnected')) {
          setConnectionStatus('db_unavailable');
          setErrorMessage('Database Connection Failure: FastAPI backend is running but database is unreachable.');
        } else {
          setConnectionStatus('connected');
          setErrorMessage(null);
        }
      }

      const res = await apiClient.getJobsAndCounts({ signal: controller.signal });
      setJobs(res.jobs);
      setCounts(res.counts);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      console.error('Failed to fetch API data:', err);

      if (!apiClient.isDemoMode()) {
        if (err instanceof ApiError && err.status === 408) {
          setConnectionStatus('timeout');
          setErrorMessage('API Connection Timeout: The backend request timed out.');
        } else {
          setConnectionStatus('offline');
          setErrorMessage(
            err instanceof Error ? err.message : 'Backend Offline: Unable to reach FastAPI server.'
          );
        }
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

  const handleRunJob = async (jobId: string, renderOnly: boolean) => {
    setIsProcessingWorker(true);
    try {
      await apiClient.runJob(jobId, renderOnly);
      await fetchJobsAndHealth();
    } catch (err) {
      console.error('Run job failed:', err);
      alert(`Run failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsProcessingWorker(false);
    }
  };

  const handleJobAction = async (jobId: string, action: JobActionType) => {
    setIsProcessingWorker(true);
    try {
      await apiClient.performJobAction(jobId, action);
      await fetchJobsAndHealth();
    } catch (err) {
      console.error(`Job action '${action}' failed:`, err);
      alert(`Action '${action}' failed: ${err instanceof Error ? err.message : String(err)}`);
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

      {/* Connection Status Banners */}
      {connectionStatus === 'config_error' && (
        <div className="bg-purple-950/90 border-b border-purple-800 text-purple-200 px-4 py-3 text-xs">
          <div className="max-w-7xl mx-auto flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-purple-400 shrink-0" />
            <span>
              <strong>Configuration Error:</strong> VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.
            </span>
          </div>
        </div>
      )}

      {connectionStatus === 'offline' && (
        <div className="bg-rose-950/90 border-b border-rose-800 text-rose-200 px-4 py-3 text-xs">
          <div className="max-w-7xl mx-auto flex items-center gap-2">
            <WifiOff className="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              <strong>Backend Offline:</strong> {errorMessage || 'Unable to connect to FastAPI backend.'} Live API mode will not silently load demo data.
            </span>
          </div>
        </div>
      )}

      {connectionStatus === 'timeout' && (
        <div className="bg-orange-950/90 border-b border-orange-800 text-orange-200 px-4 py-3 text-xs">
          <div className="max-w-7xl mx-auto flex items-center gap-2">
            <Clock className="w-4 h-4 text-orange-400 shrink-0" />
            <span>
              <strong>Request Timed Out:</strong> FastAPI backend response exceeded {10000}ms. Check backend server logs.
            </span>
          </div>
        </div>
      )}

      {connectionStatus === 'db_unavailable' && (
        <div className="bg-rose-950/90 border-b border-rose-800 text-rose-200 px-4 py-3 text-xs">
          <div className="max-w-7xl mx-auto flex items-center gap-2">
            <Database className="w-4 h-4 text-rose-400 shrink-0" />
            <span>
              <strong>Database Unavailable:</strong> The FastAPI backend is running but PostgreSQL database connection failed.
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
            isDemoMode={connectionStatus === 'demo_mode'}
            isProcessing={isProcessingWorker}
            onRunWorkerJob={handleRunJob}
            onJobAction={handleJobAction}
            onSelectJobForPreview={handleSelectJobForPreview}
            onOpenEnqueueModal={() => setIsEnqueueOpen(true)}
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
            Branch: feat/studio-api-readiness | Target Dir: studio/
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
        onRunOnceCLI={(renderOnly) => {
          if (jobs.length > 0) {
            const firstPending = jobs.find((j) => j.status === 'pending');
            if (firstPending) {
              handleRunJob(String(firstPending.id), renderOnly);
            }
          }
        }}
      />
    </div>
  );
}
