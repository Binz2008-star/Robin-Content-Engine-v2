import React, { useState } from 'react';
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
  Volume2
} from 'lucide-react';
import { VideoJob, JobStatus } from '../types';

interface QueueTableProps {
  jobs: VideoJob[];
  onRunWorkerJob: (jobId: string, renderOnly: boolean) => void;
  onSelectJobForPreview: (job: VideoJob) => void;
  isProcessing: boolean;
}

export const QueueTable: React.FC<QueueTableProps> = ({
  jobs,
  onRunWorkerJob,
  onSelectJobForPreview,
  isProcessing,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedLogJob, setSelectedLogJob] = useState<VideoJob | null>(null);

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
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
            <ShieldCheck className="w-3.5 h-3.5 text-rose-400" />
            <span>quarantined</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
      {/* Table Header Controls */}
      <div className="p-4 sm:p-5 border-b border-slate-800/80 bg-slate-950/40 flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <div className="relative w-full sm:w-72">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search gameplay jobs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-amber-500/50"
            />
          </div>

          <div className="relative">
            <Filter className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="pl-8 pr-8 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-amber-500/50 appearance-none cursor-pointer"
            >
              <option value="all">All Statuses ({jobs.length})</option>
              <option value="pending">Pending</option>
              <option value="processing">Processing</option>
              <option value="rendered">Rendered</option>
              <option value="uploaded">Uploaded</option>
              <option value="quarantined">Quarantined</option>
            </select>
          </div>
        </div>

        <div className="text-xs text-slate-400 font-mono flex items-center gap-2 self-end sm:self-center">
          <span>Database: <strong className="text-emerald-400">Neon PostgreSQL</strong></span>
          <span className="text-slate-700">•</span>
          <span>Table: <strong className="text-amber-400">video_queue</strong></span>
        </div>
      </div>

      {/* Jobs List Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-slate-950/60 text-slate-400 border-b border-slate-800/80 font-mono text-[11px] uppercase tracking-wider">
              <th className="py-3 px-4 font-semibold">Job ID & Details</th>
              <th className="py-3 px-4 font-semibold">Rights Note</th>
              <th className="py-3 px-4 font-semibold">Status</th>
              <th className="py-3 px-4 font-semibold">Format & TTS</th>
              <th className="py-3 px-4 font-semibold">YouTube Status</th>
              <th className="py-3 px-4 font-semibold text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {filteredJobs.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-500">
                  No jobs found matching your criteria. Click "Enqueue Job" to add a new video job.
                </td>
              </tr>
            ) : (
              filteredJobs.map((job) => (
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
                      <p className="text-[11px] text-slate-400 font-mono truncate max-w-xs" title={job.source_path || ''}>
                        📁 {job.source_path || 'No source path'}
                      </p>
                    </div>
                  </td>

                  {/* Rights Note */}
                  <td className="py-3.5 px-4">
                    <div className="flex items-center gap-1.5 text-slate-300">
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span className="text-xs line-clamp-2" title={job.rights_note || ''}>
                        {job.rights_note || 'Recorded by Robin'}
                      </span>
                    </div>
                  </td>

                  {/* Status Badge */}
                  <td className="py-3.5 px-4">
                    <div className="space-y-1">
                      {getStatusBadge(job.status)}
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
                        <span>Private (Resumable)</span>
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
                          title="Preview Video & Audio Canvas"
                          className="p-1.5 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 transition"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                      )}

                      <button
                        onClick={() => onRunWorkerJob(String(job.id), false)}
                        disabled={isProcessing}
                        title="Run Pipeline (Render + Upload)"
                        className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition disabled:opacity-50"
                      >
                        <Play className="w-3.5 h-3.5 fill-current" />
                      </button>

                      <button
                        onClick={() => onRunWorkerJob(String(job.id), true)}
                        disabled={isProcessing}
                        title="Render Only (Skip YouTube Upload)"
                        className="p-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 transition disabled:opacity-50"
                      >
                        <Film className="w-3.5 h-3.5" />
                      </button>

                      <button
                        onClick={() => setSelectedLogJob(job)}
                        title="View Execution Logs & Script"
                        className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
                      >
                        <FileText className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Logs Drawer Modal */}
      {selectedLogJob && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
              <div>
                <h3 className="font-bold text-slate-200 text-sm flex items-center gap-2">
                  <FileText className="w-4 h-4 text-amber-400" />
                  <span>Execution Logs & Script: #{selectedLogJob.id}</span>
                </h3>
                <p className="text-xs text-slate-400 truncate mt-0.5">{selectedLogJob.source_title}</p>
              </div>
              <button
                onClick={() => setSelectedLogJob(null)}
                className="p-1 text-slate-400 hover:text-slate-200 rounded-lg"
              >
                ✕
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
