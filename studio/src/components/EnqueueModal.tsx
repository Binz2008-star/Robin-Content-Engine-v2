import React, { useState, useEffect } from 'react';
import { ShieldAlert, Video, Plus, FolderOpen, Lock, Link as LinkIcon, X } from 'lucide-react';
import { GoogleDrivePicker } from './GoogleDrivePicker';
import { GoogleDriveFile } from '../lib/googleDrive';
import { EnqueueJobRequest } from '../types';

interface EnqueueModalProps {
  isOpen: boolean;
  onClose: () => void;
  onEnqueue: (payload: EnqueueJobRequest) => Promise<void> | void;
}

export const EnqueueModal: React.FC<EnqueueModalProps> = ({
  isOpen,
  onClose,
  onEnqueue,
}) => {
  const [title, setTitle] = useState('My Original Fortnite Match');
  const [sourcePath, setSourcePath] = useState('C:\\media\\my-gameplay.mp4');
  const [sourceUrl, setSourceUrl] = useState('');
  const [rightsNote, setRightsNote] = useState('Recorded by Robin for Robin Life & Gaming');
  const [confirmRights, setConfirmRights] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Field validation errors
  const [errors, setErrors] = useState<{
    title?: string;
    source?: string;
    rightsNote?: string;
    confirmRights?: string;
  }>({});

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSelectDriveFile = (file: GoogleDriveFile) => {
    setTitle(file.name.replace(/\.[^/.]+$/, ''));
    setSourcePath(`gdrive://${file.id}/${file.name}`);
    setErrors((prev) => ({ ...prev, source: undefined, title: undefined }));
  };

  const validate = (): boolean => {
    const newErrors: {
      title?: string;
      source?: string;
      rightsNote?: string;
      confirmRights?: string;
    } = {};

    if (!title.trim()) {
      newErrors.title = 'Source title is required.';
    }

    if (!sourcePath.trim() && !sourceUrl.trim()) {
      newErrors.source = 'Either source path or source URL must be provided.';
    }

    if (!rightsNote.trim()) {
      newErrors.rightsNote = 'Rights note is required (e.g. "Recorded by Robin Life & Gaming").';
    }

    if (!confirmRights) {
      newErrors.confirmRights = 'You must explicitly confirm copyright ownership or license rights.';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      await onEnqueue({
        source_title: title.trim(),
        source_path: sourcePath.trim() || undefined,
        source_url: sourceUrl.trim() || undefined,
        rights_note: rightsNote.trim(),
        rights_confirmed: confirmRights,
      });
      onClose();
    } catch (err) {
      console.error('Failed to enqueue job:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="enqueue-modal-title"
    >
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden my-8">
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
              <Video className="w-5 h-5" />
            </div>
            <div>
              <h2 id="enqueue-modal-title" className="font-bold text-slate-100 text-sm">
                Enqueue Gameplay Video
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                CLI equivalent: robin-engine enqueue-local
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg text-sm transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 max-h-[80vh] overflow-y-auto">
          <GoogleDrivePicker onSelectDriveFile={handleSelectDriveFile} />

          {/* Title */}
          <div className="space-y-1.5">
            <label htmlFor="enqueue-source-title" className="text-xs font-semibold text-slate-300 block">
              Gameplay Video Title / Identifier <span className="text-amber-400">*</span>
            </label>
            <input
              id="enqueue-source-title"
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (errors.title) setErrors((p) => ({ ...p, title: undefined }));
              }}
              placeholder="e.g. Fortnite Solo Clutch Match"
              className={`w-full px-3.5 py-2 bg-slate-950 border ${
                errors.title ? 'border-rose-500' : 'border-slate-800'
              } rounded-xl text-xs text-slate-200 focus:outline-none focus:border-amber-500/50`}
            />
            {errors.title && <p className="text-[11px] text-rose-400">{errors.title}</p>}
          </div>

          {/* Local File Path */}
          <div className="space-y-1.5">
            <label htmlFor="enqueue-source-path" className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span>Local Video File Path</span>
              <span className="text-[10px] text-slate-500 font-mono">9:16 vertical video</span>
            </label>
            <div className="relative">
              <input
                id="enqueue-source-path"
                type="text"
                value={sourcePath}
                onChange={(e) => {
                  setSourcePath(e.target.value);
                  if (errors.source) setErrors((p) => ({ ...p, source: undefined }));
                }}
                placeholder="C:\media\my-gameplay.mp4"
                className={`w-full pl-3.5 pr-10 py-2 bg-slate-950 border ${
                  errors.source ? 'border-rose-500' : 'border-slate-800'
                } rounded-xl text-xs font-mono text-amber-300/90 focus:outline-none focus:border-amber-500/50`}
              />
              <FolderOpen className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>

          {/* Remote Source URL */}
          <div className="space-y-1.5">
            <label htmlFor="enqueue-source-url" className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span>OR Remote Source URL</span>
              <span className="text-[10px] text-slate-500 font-mono">Optional HTTP/S URL</span>
            </label>
            <div className="relative">
              <input
                id="enqueue-source-url"
                type="text"
                value={sourceUrl}
                onChange={(e) => {
                  setSourceUrl(e.target.value);
                  if (errors.source) setErrors((p) => ({ ...p, source: undefined }));
                }}
                placeholder="https://storage.googleapis.com/my-bucket/gameplay.mp4"
                className={`w-full pl-3.5 pr-10 py-2 bg-slate-950 border ${
                  errors.source ? 'border-rose-500' : 'border-slate-800'
                } rounded-xl text-xs font-mono text-amber-300/90 focus:outline-none focus:border-amber-500/50`}
              />
              <LinkIcon className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
            {errors.source && <p className="text-[11px] text-rose-400">{errors.source}</p>}
          </div>

          {/* YouTube Privacy Default Notice */}
          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex items-center gap-2 text-xs text-slate-300">
            <Lock className="w-4 h-4 text-amber-400 shrink-0" />
            <div>
              <p className="font-semibold text-slate-200">YouTube Upload Privacy Notice</p>
              <p className="text-[11px] text-slate-400">
                🔒 All uploaded videos are set to <strong>Private</strong> by backend default for safety and manual verification. YouTube privacy selection is managed on the backend.
              </p>
            </div>
          </div>

          {/* Mandatory Ownership & Rights Check */}
          <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl space-y-3">
            <div className="flex items-start gap-2.5">
              <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-xs font-bold text-amber-300">
                  Mandatory Rights & Ownership Policy
                </h3>
                <p className="text-[11px] text-amber-200/80 leading-relaxed mt-0.5">
                  Robin Engine requires explicit confirmation that you own or possess full permissions for the gameplay footage before processing.
                </p>
              </div>
            </div>

            <div className="space-y-2 pt-1 border-t border-amber-500/20">
              <label htmlFor="enqueue-rights-note" className="text-[11px] font-semibold text-amber-300 block">
                Rights Note / Citation <span className="text-amber-400">*</span>
              </label>
              <input
                id="enqueue-rights-note"
                type="text"
                value={rightsNote}
                onChange={(e) => {
                  setRightsNote(e.target.value);
                  if (errors.rightsNote) setErrors((p) => ({ ...p, rightsNote: undefined }));
                }}
                placeholder="--rights-note 'Recorded by Robin for Robin Life & Gaming'"
                className={`w-full px-3 py-1.5 bg-slate-950/80 border ${
                  errors.rightsNote ? 'border-rose-500' : 'border-amber-500/30'
                } rounded-lg text-xs font-mono text-slate-200 focus:outline-none`}
              />
              {errors.rightsNote && <p className="text-[11px] text-rose-400">{errors.rightsNote}</p>}

              <div className="pt-1">
                <label className="flex items-start gap-2 cursor-pointer select-none" htmlFor="enqueue-confirm-rights">
                  <input
                    id="enqueue-confirm-rights"
                    type="checkbox"
                    checked={confirmRights}
                    onChange={(e) => {
                      setConfirmRights(e.target.checked);
                      if (errors.confirmRights) setErrors((p) => ({ ...p, confirmRights: undefined }));
                    }}
                    className="w-4 h-4 mt-0.5 rounded text-amber-500 focus:ring-amber-500 bg-slate-950 border-amber-500/50 cursor-pointer"
                  />
                  <span className="text-xs font-bold text-amber-200">
                    I confirm that this video is original content recorded by me or licensed. (--confirm-rights)
                  </span>
                </label>
                {errors.confirmRights && <p className="text-[11px] text-rose-400 mt-1">{errors.confirmRights}</p>}
              </div>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="pt-4 border-t border-slate-800 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 text-slate-950 font-bold text-xs rounded-xl shadow-lg transition disabled:opacity-50 flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4 stroke-[3]" />
              <span>{isSubmitting ? 'Enqueuing...' : 'Enqueue Video Job'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
