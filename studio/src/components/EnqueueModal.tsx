import React, { useEffect, useState } from 'react';
import {
  FolderOpen,
  Link as LinkIcon,
  Lock,
  Plus,
  ShieldAlert,
  Video,
  X,
} from 'lucide-react';
import { EnqueueJobRequest } from '../types';
import { GoogleDriveFile } from '../lib/googleDrive';
import { GoogleDrivePicker } from './GoogleDrivePicker';

interface EnqueueModalProps {
  isOpen: boolean;
  onClose: () => void;
  onEnqueue: (payload: EnqueueJobRequest) => Promise<void> | void;
}

interface FormErrors {
  title?: string;
  source?: string;
  rightsNote?: string;
  confirmRights?: string;
}

export const EnqueueModal: React.FC<EnqueueModalProps> = ({
  isOpen,
  onClose,
  onEnqueue,
}) => {
  const [title, setTitle] = useState('My Original Fortnite Match');
  const [sourcePath, setSourcePath] = useState(
    'C:\\media\\my-gameplay.mp4'
  );
  const [sourceUrl, setSourceUrl] = useState('');
  const [rightsNote, setRightsNote] = useState(
    'Recorded by Robin for Robin Life & Gaming'
  );
  const [confirmRights, setConfirmRights] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
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
    setErrors((previous) => ({
      ...previous,
      source: undefined,
      title: undefined,
    }));
  };

  const validate = (): boolean => {
    const nextErrors: FormErrors = {};

    if (!title.trim()) {
      nextErrors.title = 'Source title is required.';
    }
    if (!sourcePath.trim() && !sourceUrl.trim()) {
      nextErrors.source =
        'Either a source path or a source URL is required.';
    }
    if (!rightsNote.trim()) {
      nextErrors.rightsNote = 'A rights note is required.';
    }
    if (!confirmRights) {
      nextErrors.confirmRights =
        'You must confirm ownership or licensing rights.';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
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
        <div className="p-5 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
              <Video className="w-5 h-5" />
            </div>
            <div>
              <h2
                id="enqueue-modal-title"
                className="font-bold text-slate-100 text-sm"
              >
                Enqueue Gameplay Video
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Rights confirmation is mandatory
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="p-5 space-y-4 max-h-[80vh] overflow-y-auto"
        >
          <GoogleDrivePicker onSelectDriveFile={handleSelectDriveFile} />

          <div className="space-y-1.5">
            <label
              htmlFor="enqueue-source-title"
              className="text-xs font-semibold text-slate-300 block"
            >
              Gameplay Video Title / Identifier
            </label>
            <input
              id="enqueue-source-title"
              type="text"
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                setErrors((previous) => ({
                  ...previous,
                  title: undefined,
                }));
              }}
              className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200"
            />
            {errors.title && (
              <p className="text-[11px] text-rose-400">{errors.title}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="enqueue-source-path"
              className="text-xs font-semibold text-slate-300 block"
            >
              Local Video File Path
            </label>
            <div className="relative">
              <input
                id="enqueue-source-path"
                type="text"
                value={sourcePath}
                onChange={(event) => {
                  setSourcePath(event.target.value);
                  setErrors((previous) => ({
                    ...previous,
                    source: undefined,
                  }));
                }}
                placeholder={'C:\\media\\my-gameplay.mp4'}
                className="w-full pl-3.5 pr-10 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-amber-300/90"
              />
              <FolderOpen className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="enqueue-source-url"
              className="text-xs font-semibold text-slate-300 block"
            >
              Or Remote Source URL
            </label>
            <div className="relative">
              <input
                id="enqueue-source-url"
                type="url"
                value={sourceUrl}
                onChange={(event) => {
                  setSourceUrl(event.target.value);
                  setErrors((previous) => ({
                    ...previous,
                    source: undefined,
                  }));
                }}
                placeholder="https://example.invalid/original-video.mp4"
                className="w-full pl-3.5 pr-10 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-amber-300/90"
              />
              <LinkIcon className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
            {errors.source && (
              <p className="text-[11px] text-rose-400">{errors.source}</p>
            )}
          </div>

          <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-xl flex items-center gap-2 text-xs text-slate-300">
            <Lock className="w-4 h-4 text-amber-400 shrink-0" />
            <p>
              Real YouTube uploads remain <strong>Private</strong> by backend
              default.
            </p>
          </div>

          <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl space-y-3">
            <div className="flex items-start gap-2.5">
              <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0" />
              <p className="text-[11px] text-amber-200/80">
                Confirm that the footage is original or properly licensed.
              </p>
            </div>

            <label
              htmlFor="enqueue-rights-note"
              className="text-[11px] font-semibold text-amber-300 block"
            >
              Rights Note / Citation
            </label>
            <input
              id="enqueue-rights-note"
              type="text"
              value={rightsNote}
              onChange={(event) => {
                setRightsNote(event.target.value);
                setErrors((previous) => ({
                  ...previous,
                  rightsNote: undefined,
                }));
              }}
              className="w-full px-3 py-1.5 bg-slate-950/80 border border-amber-500/30 rounded-lg text-xs text-slate-200"
            />
            {errors.rightsNote && (
              <p className="text-[11px] text-rose-400">
                {errors.rightsNote}
              </p>
            )}

            <label
              className="flex items-start gap-2 cursor-pointer"
              htmlFor="enqueue-confirm-rights"
            >
              <input
                id="enqueue-confirm-rights"
                type="checkbox"
                checked={confirmRights}
                onChange={(event) => {
                  setConfirmRights(event.target.checked);
                  setErrors((previous) => ({
                    ...previous,
                    confirmRights: undefined,
                  }));
                }}
                className="w-4 h-4 mt-0.5"
              />
              <span className="text-xs font-bold text-amber-200">
                I confirm that this video is original content recorded by me
                or properly licensed.
              </span>
            </label>
            {errors.confirmRights && (
              <p className="text-[11px] text-rose-400">
                {errors.confirmRights}
              </p>
            )}
          </div>

          <div className="pt-4 border-t border-slate-800 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 bg-slate-800 text-slate-300 rounded-xl text-xs font-semibold disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 font-bold text-xs rounded-xl disabled:opacity-50 flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>
                {isSubmitting ? 'Enqueuing...' : 'Enqueue Video Job'}
              </span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
