import React, { useState } from 'react';
import { ShieldAlert, Video, Plus, FolderOpen } from 'lucide-react';
import { GoogleDrivePicker } from './GoogleDrivePicker';
import { GoogleDriveFile } from '../lib/googleDrive';
import { EnqueueJobRequest } from '../types';

interface EnqueueModalProps {
  isOpen: boolean;
  onClose: () => void;
  onEnqueue: (payload: EnqueueJobRequest) => void;
}

export const EnqueueModal: React.FC<EnqueueModalProps> = ({
  isOpen,
  onClose,
  onEnqueue,
}) => {
  const [title, setTitle] = useState('My Original Fortnite Match');
  const [sourcePath, setSourcePath] = useState('C:\\media\\my-gameplay.mp4');
  const [rightsNote, setRightsNote] = useState('Recorded by Robin for Robin Life & Gaming');
  const [confirmRights, setConfirmRights] = useState(true);

  if (!isOpen) return null;

  const handleSelectDriveFile = (file: GoogleDriveFile) => {
    setTitle(file.name.replace(/\.[^/.]+$/, ''));
    setSourcePath(`gdrive://${file.id}/${file.name}`);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!confirmRights) {
      alert("Rights confirmation is mandatory before enqueuing videos into Robin Engine.");
      return;
    }

    onEnqueue({
      source_title: title,
      source_path: sourcePath,
      rights_note: rightsNote,
      rights_confirmed: confirmRights,
    });

    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
              <Video className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-100 text-sm">
                Enqueue Gameplay Video
              </h3>
              <p className="text-xs text-slate-400 font-mono">
                CLI equivalent: robin-engine enqueue-local
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-200 rounded-lg text-sm"
          >
            ✕
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 max-h-[80vh] overflow-y-auto">
          <GoogleDrivePicker onSelectDriveFile={handleSelectDriveFile} />

          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300">
              Gameplay Video Title / Identifier
            </label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Fortnite Solo Clutch Match"
              className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-amber-500/50"
            />
          </div>

          {/* Local File Path */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
              <span>Video File Path or Google Drive Source</span>
              <span className="text-[10px] text-slate-500 font-mono">9:16 vertical crop</span>
            </label>
            <div className="relative">
              <input
                type="text"
                required
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
                placeholder="C:\media\my-gameplay.mp4"
                className="w-full pl-3.5 pr-10 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-amber-300/90 focus:outline-none focus:border-amber-500/50"
              />
              <FolderOpen className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2" />
            </div>
          </div>

          {/* Mandatory Ownership & Rights Check */}
          <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl space-y-3">
            <div className="flex items-start gap-2.5">
              <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-xs font-bold text-amber-300">
                  Mandatory Rights & Ownership Policy
                </h4>
                <p className="text-[11px] text-amber-200/80 leading-relaxed mt-0.5">
                  Robin Engine requires explicit confirmation that you own or possess full permissions for the gameplay footage before processing.
                </p>
              </div>
            </div>

            <div className="space-y-2 pt-1 border-t border-amber-500/20">
              <input
                type="text"
                value={rightsNote}
                onChange={(e) => setRightsNote(e.target.value)}
                placeholder="--rights-note 'Recorded by Robin for Robin Life & Gaming'"
                className="w-full px-3 py-1.5 bg-slate-950/80 border border-amber-500/30 rounded-lg text-xs font-mono text-slate-200 focus:outline-none"
              />

              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={confirmRights}
                  onChange={(e) => setConfirmRights(e.target.checked)}
                  className="w-4 h-4 rounded text-amber-500 focus:ring-amber-500 bg-slate-950 border-amber-500/50 cursor-pointer"
                />
                <span className="text-xs font-bold text-amber-200">
                  I confirm that this video is original content recorded by me or licensed. (--confirm-rights)
                </span>
              </label>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="pt-4 border-t border-slate-800 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!confirmRights}
              className="px-5 py-2 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 text-slate-950 font-bold text-xs rounded-xl shadow-lg transition disabled:opacity-50 flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4 stroke-[3]" />
              <span>Enqueue Video Job</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
