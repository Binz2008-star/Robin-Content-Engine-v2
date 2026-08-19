import React, { useState } from 'react';
import { HardDrive, Cloud, FileVideo, Check, RefreshCw, LogIn } from 'lucide-react';
import { fetchGoogleDriveVideos, GoogleDriveFile } from '../lib/googleDrive';

interface GoogleDrivePickerProps {
  onSelectDriveFile: (file: GoogleDriveFile) => void;
}

export const GoogleDrivePicker: React.FC<GoogleDrivePickerProps> = ({ onSelectDriveFile }) => {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [files, setFiles] = useState<GoogleDriveFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);

  const handleFetchDriveFiles = async (token: string) => {
    setIsLoading(true);
    const driveFiles = await fetchGoogleDriveVideos(token);
    setFiles(driveFiles);
    setIsLoading(false);
  };

  const handleSimulateDriveConnect = () => {
    // Simulated token for preview when OAuth is not completed
    const simToken = "simulated_drive_token";
    setAccessToken(simToken);
    setFiles([
      {
        id: "drive_file_01",
        name: "fortnite_clutch_gameplay_1080p.mp4",
        mimeType: "video/mp4",
        size: "142 MB",
      },
      {
        id: "drive_file_02",
        name: "fc24_last_minute_goal_stream.mp4",
        mimeType: "video/mp4",
        size: "89 MB",
      },
      {
        id: "drive_file_03",
        name: "gta5_stunt_jump_raw.mp4",
        mimeType: "video/mp4",
        size: "210 MB",
      },
    ]);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-bold text-slate-200">Google Drive Video Import</span>
        </div>
        <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded">
          DEMO / SIMULATED
        </span>
      </div>

      {!accessToken ? (
        <div className="text-center py-4 bg-slate-950/60 rounded-lg border border-slate-800/80 p-3 space-y-2">
          <Cloud className="w-6 h-6 text-slate-500 mx-auto" />
          <p className="text-xs text-slate-400">
            Connect your Google Drive account to import gameplay clips directly.
          </p>
          <button
            type="button"
            onClick={handleSimulateDriveConnect}
            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 mx-auto"
          >
            <LogIn className="w-3.5 h-3.5" />
            <span>Connect Google Drive (Simulated)</span>
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span>Select a gameplay video file:</span>
            <button
              type="button"
              onClick={() => handleFetchDriveFiles(accessToken)}
              className="text-amber-400 hover:underline flex items-center gap-1"
            >
              <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>

          <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
            {files.map((file) => (
              <div
                key={file.id}
                onClick={() => {
                  setSelectedFileId(file.id);
                  onSelectDriveFile(file);
                }}
                className={`p-2 rounded-lg border text-xs flex items-center justify-between cursor-pointer transition ${
                  selectedFileId === file.id
                    ? 'bg-amber-500/10 border-amber-500/50 text-amber-300 font-semibold'
                    : 'bg-slate-950 border-slate-800 hover:border-slate-700 text-slate-300'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <FileVideo className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                  <span className="truncate">{file.name}</span>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-500 shrink-0 font-mono">
                  <span>{file.size || 'Video'}</span>
                  {selectedFileId === file.id && <Check className="w-3.5 h-3.5 text-amber-400" />}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
