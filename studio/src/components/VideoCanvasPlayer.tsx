import React, { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Film,
  Pause,
  Play,
  Sparkles,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { VideoJob } from '../types';

interface VideoCanvasPlayerProps {
  job?: VideoJob | null;
}

export const VideoCanvasPlayer: React.FC<VideoCanvasPlayerProps> = ({
  job,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [gameAudioVolume, setGameAudioVolume] = useState(15);
  const [isGameMuted, setIsGameMuted] = useState(false);

  const durationSec = 24;

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;

    if (isPlaying) {
      timer = setInterval(() => {
        setCurrentTimeSec((previous) => {
          if (previous >= durationSec - 1) {
            setIsPlaying(false);
            return 0;
          }
          return previous + 1;
        });
      }, 1000);
    }

    return () => {
      if (timer !== undefined) {
        clearInterval(timer);
      }
    };
  }, [isPlaying, durationSec]);

  const sampleTitle =
    job?.source_title ||
    'مباراة فورتنايت حماسية - لقطة القنص الأسطورية';
  const sampleScript =
    job?.generated_script ||
    'هذا تعليق تجريبي للمعاينة فقط. المعالجة الحقيقية تتم في عامل MoviePy الخلفي.';

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-indigo-400 font-bold text-sm">
            <Film className="w-5 h-5" />
            <span>MoviePy v2 Canvas Preview</span>
          </div>
          <h2 className="text-xl font-black text-slate-100 mt-1">
            Shorts Video & Audio Composition
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Simulated 9:16 preview. Rendering is performed by the backend
            worker.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 px-3.5 py-2 rounded-xl border border-slate-800 text-xs font-mono">
          <CheckCircle2 className="w-4 h-4 text-amber-400" />
          <span className="text-slate-300">1080x1920 preview</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-5 flex justify-center">
          <div className="relative w-full max-w-[320px] aspect-[9/16] bg-slate-950 rounded-3xl border-4 border-slate-800 shadow-2xl overflow-hidden flex flex-col justify-between">
            <div className="absolute inset-0 bg-gradient-to-b from-indigo-950 via-slate-900 to-slate-950" />

            <div className="relative z-10 p-4 flex items-center justify-between text-xs">
              <span className="px-2.5 py-1 rounded-full bg-slate-900/80 text-amber-400 font-bold border border-amber-500/30 text-[10px]">
                9:16 Shorts ({currentTimeSec}s / {durationSec}s)
              </span>
              <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px] font-mono border border-emerald-500/30">
                SIMULATED
              </span>
            </div>

            <div className="relative z-10 px-6 py-4 text-center space-y-4">
              {isPlaying && (
                <div className="flex items-center justify-center gap-1 h-8">
                  {[40, 70, 100, 60, 90, 50, 80, 40].map(
                    (height, index) => (
                      <div
                        key={`${height}-${index}`}
                        className="w-1 bg-amber-400 rounded-full animate-pulse"
                        style={{
                          height: `${height}%`,
                          animationDelay: `${index * 0.1}s`,
                        }}
                      />
                    )
                  )}
                </div>
              )}

              <div className="p-3 bg-slate-950/80 rounded-2xl border border-amber-500/30 shadow-lg">
                <span className="text-amber-300 font-black text-sm tracking-wide leading-relaxed">
                  &quot;{sampleScript}&quot;
                </span>
                <div className="text-[10px] text-slate-400 mt-1 font-mono">
                  Browser preview — backend voiceover required
                </div>
              </div>
            </div>

            <div className="relative z-10 p-4 bg-slate-950/90 border-t border-slate-800 space-y-2">
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-amber-500 to-orange-500 h-full transition-all duration-300"
                  style={{
                    width: `${(currentTimeSec / durationSec) * 100}%`,
                  }}
                />
              </div>

              <div className="flex items-center justify-between pt-1">
                <button
                  type="button"
                  onClick={() => setIsPlaying((playing) => !playing)}
                  aria-label={isPlaying ? 'Pause preview' : 'Play preview'}
                  className="p-2.5 rounded-full bg-amber-500 text-slate-950 font-bold hover:bg-amber-400 transition"
                >
                  {isPlaying ? (
                    <Pause className="w-4 h-4" />
                  ) : (
                    <Play className="w-4 h-4 fill-current" />
                  )}
                </button>

                <div className="text-slate-300 font-mono text-xs">
                  00:{String(currentTimeSec).padStart(2, '0')} / 00:
                  {durationSec}
                </div>

                <button
                  type="button"
                  onClick={() => setIsGameMuted((muted) => !muted)}
                  aria-label={
                    isGameMuted ? 'Unmute game audio' : 'Mute game audio'
                  }
                  className="p-2 rounded-lg bg-slate-800 text-slate-300 hover:text-white"
                >
                  {isGameMuted ? (
                    <VolumeX className="w-4 h-4 text-rose-400" />
                  ) : (
                    <Volume2 className="w-4 h-4 text-amber-400" />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5">
          <h3 className="font-bold text-slate-100 text-base flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-amber-400" />
            <span>Backend render settings</span>
          </h3>

          <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl space-y-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-200">
                Game audio ducking level
              </span>
              <span className="text-amber-400 font-mono font-bold">
                {gameAudioVolume}%
              </span>
            </div>
            <input
              aria-label="Game audio ducking level"
              type="range"
              min={0}
              max={50}
              value={gameAudioVolume}
              onChange={(event) =>
                setGameAudioVolume(Number(event.target.value))
              }
              className="w-full accent-amber-500 cursor-pointer"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl">
              <span className="text-slate-400 text-[11px]">
                Duration constraint
              </span>
              <div className="text-slate-100 font-bold text-sm">
                Max 58 seconds
              </div>
            </div>
            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl">
              <span className="text-slate-400 text-[11px]">
                Codec and container
              </span>
              <div className="text-slate-100 font-bold text-sm">
                H.264 / AAC
              </div>
            </div>
          </div>

          <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl text-xs">
            <div className="text-slate-300 font-bold">
              Active gameplay job
            </div>
            <div className="text-amber-300 font-semibold mt-1">
              {sampleTitle}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
