import React, { useState } from 'react';
import {
  Check,
  CheckCircle2,
  Copy,
  FileJson,
  Layers,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { apiClient, ApiError } from '../api/client';
import { ScriptData } from '../types';
import { copyTextToClipboard } from '../lib/clipboard';

const EMPTY_SCRIPT: ScriptData = {
  title: 'No script generated yet',
  description:
    'Use Demo Mode for a simulated preview. Live generation requires a future backend endpoint.',
  tags: [],
  script: 'No voiceover script is available yet.',
};

export const ScriptGeneratorStudio: React.FC = () => {
  const [topic, setTopic] = useState('لقطة قنص مستحيلة في فورتنايت');
  const [gameName, setGameName] = useState('Fortnite');
  const [style, setStyle] = useState('حماسي إماراتي أصيل');
  const [isGenerating, setIsGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [ttsError, setTtsError] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [voiceRate, setVoiceRate] = useState(1);
  const [generatedScript, setGeneratedScript] =
    useState<ScriptData>(EMPTY_SCRIPT);

  const isDemoMode = apiClient.isDemoMode();

  const handleGenerateScript = async () => {
    setIsGenerating(true);
    setGenerationError(null);

    try {
      const generated = await apiClient.generateScript({
        game_name: gameName.trim(),
        topic: topic.trim(),
        style,
      });
      setGeneratedScript(generated);
    } catch (error) {
      if (error instanceof ApiError && error.status === 501) {
        setGenerationError(
          'Backend feature not available yet. Script generation is not enabled in Live Mode.'
        );
      } else {
        setGenerationError(
          error instanceof Error
            ? error.message
            : 'Script generation could not be completed.'
        );
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSpeakText = () => {
    setTtsError(null);

    if (!('speechSynthesis' in window)) {
      setTtsError('Browser speech preview is unavailable on this device.');
      return;
    }

    if (isPlayingAudio) {
      window.speechSynthesis.cancel();
      setIsPlayingAudio(false);
      return;
    }

    const utterance = new SpeechSynthesisUtterance(generatedScript.script);
    utterance.lang = 'ar-AE';
    utterance.rate = voiceRate;
    utterance.onend = () => setIsPlayingAudio(false);
    utterance.onerror = () => {
      setIsPlayingAudio(false);
      setTtsError('Browser speech preview could not play this text.');
    };

    setIsPlayingAudio(true);
    window.speechSynthesis.speak(utterance);
  };

  const handleCopyJSON = async () => {
    setCopyError(null);
    const success = await copyTextToClipboard(
      JSON.stringify(generatedScript, null, 2)
    );

    if (!success) {
      setCopied(false);
      setCopyError('Copy failed. Clipboard permission is unavailable.');
      return;
    }

    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
            <Sparkles className="w-5 h-5" />
            <span>Script & Voiceover Preparation Studio</span>
          </div>
          <h2 className="text-xl font-black text-slate-100 mt-1">
            Shorts Script Generator
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Demo Mode produces clearly labelled simulated content. Live AI and
            neural TTS require backend services that are not connected yet.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 px-3.5 py-2 rounded-xl border border-slate-800 text-xs font-mono">
          <CheckCircle2
            className={`w-4 h-4 ${
              isDemoMode ? 'text-amber-400' : 'text-slate-500'
            }`}
          />
          <span className="text-slate-300">
            {isDemoMode ? 'SIMULATED DEMO MODE' : 'BACKEND REQUIRED'}
          </span>
        </div>
      </div>

      {generationError && (
        <div
          role="alert"
          className="rounded-xl border border-rose-800 bg-rose-950/70 p-3 text-xs text-rose-200"
        >
          {generationError}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-bold text-slate-200 text-sm flex items-center gap-2">
            <Layers className="w-4 h-4 text-amber-400" />
            <span>Script Parameters</span>
          </h3>

          <div className="space-y-3 text-xs">
            <div>
              <label
                htmlFor="script-game-name"
                className="text-slate-400 font-medium block mb-1"
              >
                Game Title
              </label>
              <input
                id="script-game-name"
                type="text"
                value={gameName}
                onChange={(event) => setGameName(event.target.value)}
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              />
            </div>

            <div>
              <label
                htmlFor="script-topic"
                className="text-slate-400 font-medium block mb-1"
              >
                Gameplay Topic / Highlight
              </label>
              <input
                id="script-topic"
                type="text"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              />
            </div>

            <div>
              <label
                htmlFor="script-style"
                className="text-slate-400 font-medium block mb-1"
              >
                Commentary Tone
              </label>
              <select
                id="script-style"
                value={style}
                onChange={(event) => setStyle(event.target.value)}
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              >
                <option value="حماسي إماراتي أصيل">
                  حماسي إماراتي أصيل
                </option>
                <option value="كوميدي وسريع">كوميدي وسريع</option>
                <option value="تعليمي ونصائح لعب">
                  تعليمي ونصائح لعب
                </option>
              </select>
            </div>

            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-[11px] text-slate-400">
              Browser speech synthesis is available only as a local preview. It
              is not the backend ar-AE-HamdanNeural service.
            </div>
          </div>

          <button
            type="button"
            onClick={handleGenerateScript}
            disabled={isGenerating}
            className="w-full py-3 bg-gradient-to-r from-amber-500 via-orange-500 to-red-500 text-slate-950 font-black text-xs rounded-xl shadow-lg transition flex items-center justify-center gap-2 disabled:opacity-60"
          >
            <RefreshCw
              className={`w-4 h-4 ${
                isGenerating ? 'animate-spin' : ''
              }`}
            />
            <span>
              {isGenerating
                ? 'Preparing Script...'
                : isDemoMode
                  ? 'Generate Simulated Script'
                  : 'Request Backend Script'}
            </span>
          </button>
        </div>

        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <FileJson className="w-5 h-5 text-amber-400" />
              <h3 className="font-bold text-slate-100 text-sm">
                Generated JSON & Browser Voice Preview
              </h3>
            </div>
            <button
              type="button"
              onClick={handleCopyJSON}
              aria-label="Copy generated JSON"
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1.5 transition"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              <span>{copied ? 'Copied' : 'Copy JSON'}</span>
            </button>
          </div>

          {copyError && (
            <p role="status" className="text-xs text-rose-400">
              {copyError}
            </p>
          )}

          <div className="space-y-4 text-xs">
            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">
                JSON Key: "title"
              </span>
              <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl font-bold text-slate-100 text-sm">
                {generatedScript.title}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400 font-mono text-[11px]">
                  JSON Key: "script"
                </span>
                <span className="text-slate-500 font-mono text-[11px]">
                  Browser preview only
                </span>
              </div>
              <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl space-y-3">
                <p className="text-amber-200/90 text-sm leading-relaxed font-semibold italic">
                  "{generatedScript.script}"
                </p>

                <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={handleSpeakText}
                    className="px-3.5 py-1.5 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold rounded-lg text-xs flex items-center gap-1.5 transition"
                  >
                    {isPlayingAudio ? (
                      <Pause className="w-3.5 h-3.5" />
                    ) : (
                      <Play className="w-3.5 h-3.5 fill-current" />
                    )}
                    <span>
                      {isPlayingAudio
                        ? 'Stop Preview'
                        : 'Play Browser Preview'}
                    </span>
                  </button>

                  <div className="flex items-center gap-2 text-slate-400 font-mono text-[11px]">
                    <span>Speed:</span>
                    {[0.9, 1, 1.15].map((speed) => (
                      <button
                        type="button"
                        key={speed}
                        onClick={() => setVoiceRate(speed)}
                        className={`px-2 py-0.5 rounded ${
                          voiceRate === speed
                            ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                            : 'bg-slate-900'
                        }`}
                      >
                        {speed}x
                      </button>
                    ))}
                  </div>
                </div>

                {ttsError && (
                  <p role="status" className="text-xs text-rose-400">
                    {ttsError}
                  </p>
                )}
              </div>
            </div>

            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">
                JSON Key: "description"
              </span>
              <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-slate-300 leading-relaxed">
                {generatedScript.description}
              </div>
            </div>

            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">
                JSON Key: "tags"
              </span>
              <div className="flex flex-wrap gap-1.5 p-2.5 bg-slate-950 border border-slate-800 rounded-xl min-h-10">
                {generatedScript.tags.length === 0 ? (
                  <span className="text-slate-500">No tags generated.</span>
                ) : (
                  generatedScript.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2.5 py-1 bg-slate-900 text-amber-400 rounded-lg text-xs font-mono border border-slate-800"
                    >
                      #{tag}
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
