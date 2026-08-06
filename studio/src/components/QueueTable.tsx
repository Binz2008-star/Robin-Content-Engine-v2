import React, { useState, useEffect } from 'react';
import { 
  Play, 
  Film, 
  AlertTriangle, 
  Eye, 
  CheckCircle2, 
  Clock, 
  Youtube, 
  ShieldCheck, 
  Search, 
  Filter,
  FileText,
  Volume2,
  RotateCcw,
  ShieldAlert,
  Inbox,
  X
} from 'lucide-react';
import { VideoJob, JobStatus, JobActionType } from '../types';

interface QueueTableProps {
  jobs: VideoJob[];
  isDemoMode: boolean;
  isProcessing: boolean;
  onRunWorkerJob: (jobId: string, renderOnly: boolean) => void;
  onJobAction: (jobId: string, action: JobActionType) => void;
  onSelectJobForPreview: (job: VideoJob) => void;
  onOpenEnqueueModal: () => void;
}

export const QueueTable: React.FC<QueueTableProps> = ({
  jobs,
  isDemoMode,
  isProcessing,
  onRunWorkerJob,
  onJobAction,
  onSelectJobForPreview,
  onOpenEnqueueModal,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedLogJob, setSelectedLogJob] = useState<VideoJob | null>(null);

  // Confirmation modal state for job actions
  const [actionConfirm, setActionConfirm] = useState<{
    isOpen: boolean;
    job: VideoJob | null;
    action: JobActionType | null;
  }>({
    isOpen: false,
    job: null,
    action: null,
  });

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (actionConfirm.isOpen) setActionConfirm({ isOpen: false, job: null, action: null });
        if (selectedLogJob) setSelectedLogJob(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [actionConfirm.isOpen, selectedLogJob]);

  const filteredJobs = jobs.filter((job) => {
    const searchLower = searchTerm.toLowerCase();
    const matchesSearch =
      job.source_title.toLowerCase().includes(searchLower) ||
      (job.source_path || '').toLowerCase().includes(searchLower) ||
      (job.generated_script || '').toLowerCase().includes(searchLower);

    const matchesStatus = statusFilter === 'all' || job.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: JobStatus) => {
    switch (status) {
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <Clock className="w-3.5 h-3.5" />
            <span>pending</span>
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
            <span>processing</span>
          </span>
        );
      case 'rendered':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
            <Film className="w-3.5 h-3.5" />
            <span>rendered</span>
          </span>
        );
      case 'uploaded':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>uploaded</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>failed</span>
          </span>
        );
      case 'quarantined':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
            <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
            <span>quarantined</span>
          </span>
        );
      default:
        return null;
    }
  };

  const handleConfirmAction = () => {
    if (actionConfirm.job && actionConfirm.action) {
      onJobAction(String(actionConfirm.job.id), actionConfirm.action);
    }
    setActionConfirm({ isOpen: false, job: null, action: null });
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
      {/* Table Header Controls */}
      <div className="p-4 sm:p-5 border-b border-slate-800/80 bg-slate-950/40 flex flex-col md:flex-row gap-3 items-start md:items-center justify-between">
        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
          <div className="relative w-full sm:w-72">
            <label htmlFor="queue-search" className="sr-only">Search gameplay jobs</label>
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              id="queue-search"
              type="text"
              placeholder="Search gameplay jobs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-amber-500/50"
            />
          </div>

          <div className="relative">
            <label htmlFor="queue-status-filter" className="sr-only">Filter by status</label>
            <Filter className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              id="queue-status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="pl-8 pr-8 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-amber-500/50 appearance-none cursor-pointer"
            >
              <option value="all">All Statuses ({jobs.length})</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="rendered">Rendered</option>
              <option value="uploaded">Uploaded</option>
              <option value="failed">Failed</option>
              <option value="quarantined">Quarantined</option>
            </select>
          </div>
        </div>

        <div className="text-xs text-slate-400 font-mono flex items-center gap-2">
          <span>
            Database:{' '}
            {isDemoMode ? (
              <strong className="text-amber-400">Simulated Store (Demo Mode)</strong>
            ) : (
              <strong className="text-emerald-400">Neon PostgreSQL</strong>
            )}
          </span>
          <span className="text-slate-700">•</span>
          <span>Table: <strong className="text-amber-400">video_queue</strong></span>
        </div>
      </div>

      {/* Empty Queue State */}
      {filteredJobs.length === 0 ? (
        <div className="p-12 text-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center mx-auto text-slate-400">
            <Inbox className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h3 className="font-bold text-slate-200 text-sm">Empty Queue</h3>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              No video jobs found matching your search or status filter. Click below to enqueue a new gameplay job.
            </p>
          </div>
          <button
            onClick={onOpenEnqueueModal}
            className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs rounded-xl transition"
          >
            Enqueue Gameplay Job
          </button>
        </div>
      ) : (
        <>
          {/* Desktop Jobs Table (md:table) */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-950/60 text-slate-400 border-b border-slate-800/80 font-mono text-[11px] uppercase tracking-wider">
                  <th className="py-3 px-4 font-semibold">Job ID & Source</th>
                  <th className="py-3 px-4 font-semibold">Rights Note</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold">Format & Voice</th>
                  <th className="py-3 px-4 font-semibold">YouTube Status</th>
                  <th className="py-3 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredJobs.map((job) => {
                  const isPending = job.status === 'pending';
                  const isFailedOrQuarantined = job.status === 'failed' || job.status === 'quarantined';
                  const canQuarantine = job.status !== 'uploaded';

                  return (
                    <tr key={job.id} className="hover:bg-slate-800/40 transition group">
                      {/* Job ID & Source */}
                      <td className="py-3.5 px-4">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-amber-400 text-xs">
                              #{job.id}
                            </span>
                            <span className="text-[10px] text-slate-500 font-mono">
                              {job.created_at ? new Date(job.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                            </span>
                          </div>
                          <p className="font-semibold text-slate-200 text-xs line-clamp-1">
                            {job.source_title}
                          </p>
                          <p className="text-[11px] text-slate-400 font-mono truncate max-w-xs" title={job.source_path || job.source_url || ''}>
                            📁 {job.source_path || job.source_url || 'No source specified'}
                          </p>
                        </div>
                      </td>

                      {/* Rights Note */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5 text-slate-300">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          <span className="text-xs line-clamp-2" title={job.rights_note || ''}>
                            {job.rights_note || 'Confirmed'}
                          </span>
                        </div>
                      </td>

                      {/* Status Badge */}
                      <td className="py-3.5 px-4">
                        <div className="space-y-1">
                          {getStatusBadge(job.status)}
                          {job.last_error && (
                            <p className="text-[10px] text-rose-400 font-mono truncate max-w-[140px]" title={job.last_error}>
                              Err: {job.last_error}
                            </p>
                          )}
                        </div>
                      </td>

                      {/* Format & Voice */}
                      <td className="py-3.5 px-4">
                        <div className="space-y-1 text-slate-400 font-mono text-[11px]">
                          <div className="flex items-center gap-1 text-slate-300">
                            <Film className="w-3 h-3 text-indigo-400" />
                            <span>9:16 (1080x1920)</span>
                          </div>
                          <div className="flex items-center gap-1 text-amber-400">
                            <Volume2 className="w-3 h-3" />
                            <span>ar-AE-HamdanNeural</span>
                          </div>
                        </div>
                      </td>

                      {/* YouTube Status */}
                      <td className="py-3.5 px-4">
                        {job.status === 'uploaded' ? (
                          <div className="flex items-center gap-1.5 text-emerald-400 font-medium">
                            <Youtube className="w-4 h-4 fill-current" />
                            <span>Private (Backend Default)</span>
                          </div>
                        ) : (
                          <span className="text-slate-500 italic">Not uploaded</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {(job.status === 'rendered' || job.status === 'uploaded') && (
                            <button
                              onClick={() => onSelectJobForPreview(job)}
                              aria-label={`Preview Job #${job.id}`}
                              title="Preview Video & Audio Canvas"
                              className="p-1.5 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 transition"
                            >
                              <Eye className="w-3.5 h-3.5" />
                            </button>
                          )}

                          {/* Run Job Button - Only available for Pending jobs */}
                          <button
                            onClick={() => onRunWorkerJob(String(job.id), false)}
                            disabled={isProcessing || !isPending}
                            aria-label={`Run Job #${job.id}`}
                            title={
                              isPending
                                ? 'Run Pipeline (Render + Upload)'
                                : 'Run pipeline is available only for pending jobs.'
                            }
                            className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <Play className="w-3.5 h-3.5 fill-current" />
                          </button>

                          {/* Retry Button - Available for Failed/Quarantined jobs */}
                          <button
                            onClick={() => setActionConfirm({ isOpen: true, job, action: 'retry' })}
                            disabled={isProcessing || !isFailedOrQuarantined}
                            aria-label={`Retry Job #${job.id}`}
                            title={
                              isFailedOrQuarantined
                                ? 'Retry Failed/Quarantined Job'
                                : 'Retry is available only for failed or quarantined jobs.'
                            }
                            className="p-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 transition disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>

                          {/* Quarantine Button - Available for all except Uploaded */}
                          <button
                            onClick={() => setActionConfirm({ isOpen: true, job, action: 'quarantine' })}
                            disabled={isProcessing || !canQuarantine || job.status === 'quarantined'}
                            aria-label={`Quarantine Job #${job.id}`}
                            title={
                              canQuarantine
                                ? 'Move Job to Quarantine'
                                : 'Quarantine is unavailable for uploaded jobs.'
                            }
                            className="p-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 transition disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" />
                          </button>

                          {/* Logs Button */}
                          <button
                            onClick={() => setSelectedLogJob(job)}
                            aria-label={`View logs for Job #${job.id}`}
                            title="View Execution Logs & Script"
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
                          >
                            <FileText className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile Cards View (md:hidden) */}
          <div className="md:hidden divide-y divide-slate-800/80">
            {filteredJobs.map((job) => {
              const isPending = job.status === 'pending';
              const isFailedOrQuarantined = job.status === 'failed' || job.status === 'quarantined';
              const canQuarantine = job.status !== 'uploaded';

              return (
                <div key={job.id} className="p-4 space-y-3 bg-slate-900/60">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-amber-400 text-xs">#{job.id}</span>
                        {getStatusBadge(job.status)}
                      </div>
                      <h4 className="font-semibold text-slate-200 text-sm">{job.source_title}</h4>
                    </div>
                  </div>

                  <p className="text-xs text-slate-400 font-mono truncate">
                    📁 {job.source_path || job.source_url || 'No source specified'}
                  </p>

                  <div className="flex items-center gap-2 text-xs text-slate-300">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span className="truncate">{job.rights_note || 'Rights confirmed'}</span>
                  </div>

                  {job.last_error && (
                    <p className="text-xs text-rose-400 bg-rose-950/40 p-2 rounded-lg border border-rose-800 font-mono">
                      Error: {job.last_error}
                    </p>
                  )}

                  <div className="pt-2 flex items-center justify-between border-t border-slate-800">
                    <button
                      onClick={() => setSelectedLogJob(job)}
                      className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1"
                    >
                      <FileText className="w-3.5 h-3.5" />
                      <span>View Logs</span>
                    </button>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onRunWorkerJob(String(job.id), false)}
                        disabled={isProcessing || !isPending}
                        className="px-2.5 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-semibold disabled:opacity-30 flex items-center gap-1"
                      >
                        <Play className="w-3 h-3 fill-current" />
                        <span>Run</span>
                      </button>

                      <button
                        onClick={() => setActionConfirm({ isOpen: true, job, action: 'retry' })}
                        disabled={isProcessing || !isFailedOrQuarantined}
                        className="px-2.5 py-1 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-lg text-xs font-semibold disabled:opacity-30 flex items-center gap-1"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Retry</span>
                      </button>

                      <button
                        onClick={() => setActionConfirm({ isOpen: true, job, action: 'quarantine' })}
                        disabled={isProcessing || !canQuarantine || job.status === 'quarantined'}
                        className="px-2.5 py-1 bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-semibold disabled:opacity-30 flex items-center gap-1"
                      >
                        <ShieldAlert className="w-3 h-3" />
                        <span>Quarantine</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Confirmation Modal for Job Actions */}
      {actionConfirm.isOpen && actionConfirm.job && actionConfirm.action && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-modal-title"
        >
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div>
                <h3 id="confirm-modal-title" className="font-bold text-slate-100 text-sm">
                  Confirm {actionConfirm.action === 'retry' ? 'Retry' : 'Quarantine'} Action
                </h3>
                <p className="text-xs text-slate-400">
                  Job #{actionConfirm.job.id}: {actionConfirm.job.source_title}
                </p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed bg-slate-950 p-3 rounded-xl border border-slate-800">
              {actionConfirm.action === 'retry' ? (
                <>Are you sure you want to <strong>retry</strong> this job? Its status will be reset to <strong>pending</strong> for the pipeline worker to pick up.</>
              ) : (
                <>Are you sure you want to <strong>quarantine</strong> this job? It will be safely isolated and excluded from active worker execution.</>
              )}
            </p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setActionConfirm({ isOpen: false, job: null, action: null })}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmAction}
                className={`px-4 py-2 rounded-xl text-xs font-bold shadow-lg transition ${
                  actionConfirm.action === 'retry'
                    ? 'bg-amber-500 hover:bg-amber-400 text-slate-950'
                    : 'bg-rose-600 hover:bg-rose-500 text-white'
                }`}
              >
                Confirm {actionConfirm.action === 'retry' ? 'Retry' : 'Quarantine'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Logs Modal */}
      {selectedLogJob && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="logs-modal-title"
        >
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
              <div>
                <h3 id="logs-modal-title" className="font-bold text-slate-200 text-sm flex items-center gap-2">
                  <FileText className="w-4 h-4 text-amber-400" />
                  <span>Execution Logs & Script: #{selectedLogJob.id}</span>
                </h3>
                <p className="text-xs text-slate-400 truncate mt-0.5">{selectedLogJob.source_title}</p>
              </div>
              <button
                onClick={() => setSelectedLogJob(null)}
                aria-label="Close logs dialog"
                className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg text-sm transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 space-y-4 overflow-y-auto font-sans text-xs">
              {selectedLogJob.generated_script && (
                <div className="bg-slate-950 border border-slate-800/80 rounded-xl p-3 space-y-2">
                  <div className="text-amber-400 font-bold text-xs flex items-center justify-between">
                    <span>DeepSeek AI Generated Script (Emirati Dialect)</span>
                  </div>
                  <div>
                    <span className="text-slate-400 font-medium">Voiceover Script: </span>
                    <p className="p-2.5 bg-slate-900 rounded-lg text-amber-200/90 italic mt-1 leading-relaxed border border-slate-800">
                      "{selectedLogJob.generated_script}"
                    </p>
                  </div>
                </div>
              )}

              {selectedLogJob.last_error && (
                <div className="bg-rose-950/40 border border-rose-800 rounded-xl p-3 text-rose-300">
                  <strong>Last Error:</strong> {selectedLogJob.last_error}
                </div>
              )}
            </div>

            <div className="p-3 border-t border-slate-800 bg-slate-950/80 flex justify-end">
              <button
                onClick={() => setSelectedLogJob(null)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold"
              >
                Close Logs
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
