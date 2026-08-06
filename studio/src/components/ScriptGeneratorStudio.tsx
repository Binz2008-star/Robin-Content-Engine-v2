import React, { useState } from 'react';
import { Sparkles, Volume2, Play, Pause, Copy, Check, RefreshCw, Layers, CheckCircle2, ShieldCheck, FileJson } from 'lucide-react';
import { ScriptData } from '../types';

interface ScriptGeneratorStudioProps {
  onApplyScriptToEnqueue?: (script: ScriptData) => void;
}

export const ScriptGeneratorStudio: React.FC<ScriptGeneratorStudioProps> = ({
  onApplyScriptToEnqueue,
}) => {
  const [topic, setTopic] = useState('لقطة قنص مستحيلة في فورتنايت');
  const [gameName, setGameName] = useState('Fortnite');
  const [style, setStyle] = useState('حماسي وكوميدي');
  const [isGenerating, setIsGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [voiceRate, setVoiceRate] = useState<number>(1.0);

  const [generatedScript, setGeneratedScript] = useState<ScriptData>({
    title: 'أقوى سنبّة في فورتنايت! 🎯🔥 #Shorts #Fortnite',
    description: 'شوفوا هالسنيبة الأسطورية من نص الخريطة! لا تنسون اللايك والاشتراك بالقناة يا أبطال 🇦🇪✨',
    tags: ['Fortnite', 'Shorts', 'Gaming', 'الإمارات', 'فورتنايت'],
    script: 'يا خوي شوف هالسنيبة العجيبة! من أول جولة وأنا مترصد له.. وفجأة بوم! رأسية من نص الماب، شو رأيكم بالرمية؟ اكتبوا بالتعليقات!',
  });

  const handleGenerateScript = async () => {
    setIsGenerating(true);
    try {
      const res = await fetch('/api/generate-script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, gameName, style }),
      });
      const json = await res.json();
      if (json.success && json.data) {
        setGeneratedScript(json.data);
      }
    } catch (e) {
      console.error("Script generation error:", e);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSpeakText = () => {
    if (!('speechSynthesis' in window)) {
      alert("Browser speech synthesis not supported, simulating TTS audio output.");
      return;
    }

    if (isPlayingAudio) {
      window.speechSynthesis.cancel();
      setIsPlayingAudio(false);
      return;
    }

    const utterance = new SpeechSynthesisUtterance(generatedScript.script);
    utterance.lang = 'ar-AE'; // Emirati Arabic accent request
    utterance.rate = voiceRate;

    utterance.onend = () => setIsPlayingAudio(false);
    utterance.onerror = () => setIsPlayingAudio(false);

    setIsPlayingAudio(true);
    window.speechSynthesis.speak(utterance);
  };

  const handleCopyJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(generatedScript, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Top Title Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
            <Sparkles className="w-5 h-5" />
            <span>DeepSeek AI Generator & Emirati TTS (ar-AE-HamdanNeural)</span>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 rounded">
              SIMULATED
            </span>
          </div>
          <h2 className="text-xl font-black text-slate-100 mt-1">
            Shorts Script Generator Studio
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Generates structured Pydantic-validated JSON containing <code className="text-amber-300">title</code>, <code className="text-amber-300">description</code>, <code className="text-amber-300">tags</code>, and authentic Emirati dialect <code className="text-amber-300">script</code>.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-slate-950 px-3.5 py-2 rounded-xl border border-slate-800 text-xs font-mono">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span className="text-slate-300">Pydantic Schema: v2.1</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Control Panel */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-bold text-slate-200 text-sm flex items-center gap-2">
            <Layers className="w-4 h-4 text-amber-400" />
            <span>Script Generation Parameters</span>
          </h3>

          <div className="space-y-3 text-xs">
            <div>
              <label className="text-slate-400 font-medium block mb-1">Game Title:</label>
              <input
                type="text"
                value={gameName}
                onChange={(e) => setGameName(e.target.value)}
                placeholder="e.g. Fortnite, FC24, GTA V"
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              />
            </div>

            <div>
              <label className="text-slate-400 font-medium block mb-1">Gameplay Topic / Highlight:</label>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. ريمونتادا الدقيقة 90"
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              />
            </div>

            <div>
              <label className="text-slate-400 font-medium block mb-1">Commentary Tone & Dialect:</label>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-slate-200 focus:outline-none focus:border-amber-500/50"
              >
                <option value="حماسي إماراتي أصيل">حماسي إماراتي أصيل (Emirati Energetic)</option>
                <option value="كوميدي وسريع">كوميدي وساخر (Comedy & Fast)</option>
                <option value="تعليمي ونصائح لعب">تعليمي ونصائح احترافية (Pro Tips & Tricks)</option>
              </select>
            </div>

            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-2">
              <div className="text-slate-300 font-bold flex items-center justify-between text-[11px]">
                <span>Neural Voice Profile:</span>
                <span className="text-amber-400 font-mono">ar-AE-HamdanNeural</span>
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Native Emirati voice synthesizer calibrated for high-speed YouTube Shorts commentary. MoviePy v2 merges this voiceover with background audio ducked to 15%.
              </p>
            </div>
          </div>

          <button
            onClick={handleGenerateScript}
            disabled={isGenerating}
            className="w-full py-3 bg-gradient-to-r from-amber-500 via-orange-500 to-red-500 hover:from-amber-400 hover:to-orange-400 text-slate-950 font-black text-xs rounded-xl shadow-lg transition flex items-center justify-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${isGenerating ? 'animate-spin' : ''}`} />
            <span>{isGenerating ? 'Generating JSON Script...' : 'Generate AI Script (DeepSeek Mode)'}</span>
          </button>
        </div>

        {/* Right Output Inspector */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <FileJson className="w-5 h-5 text-amber-400" />
              <h3 className="font-bold text-slate-100 text-sm">
                Generated JSON & Voiceover Audio
              </h3>
            </div>
            <button
              onClick={handleCopyJSON}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-mono flex items-center gap-1.5 transition"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? 'Copied' : 'Copy JSON'}</span>
            </button>
          </div>

          {/* Generated Fields Preview */}
          <div className="space-y-4 text-xs">
            {/* Title */}
            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">JSON Key: "title"</span>
              <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl font-bold text-slate-100 text-sm">
                {generatedScript.title}
              </div>
            </div>

            {/* Voiceover Script */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400 font-mono text-[11px]">JSON Key: "script" (Emirati Arabic)</span>
                <span className="text-amber-400 font-mono text-[11px]">ar-AE-HamdanNeural</span>
              </div>
              <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl relative space-y-3">
                <p className="text-amber-200/90 text-sm leading-relaxed font-semibold italic">
                  "{generatedScript.script}"
                </p>

                {/* TTS Audio Player Control */}
                <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSpeakText}
                      className="px-3.5 py-1.5 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold rounded-lg text-xs flex items-center gap-1.5 transition"
                    >
                      {isPlayingAudio ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 fill-current" />}
                      <span>{isPlayingAudio ? 'Stop Preview' : 'Play Voiceover (ar-AE)'}</span>
                    </button>
                  </div>

                  <div className="flex items-center gap-2 text-slate-400 font-mono text-[11px]">
                    <span>Speed:</span>
                    {[0.9, 1.0, 1.15].map((speed) => (
                      <button
                        key={speed}
                        onClick={() => setVoiceRate(speed)}
                        className={`px-2 py-0.5 rounded ${
                          voiceRate === speed ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' : 'bg-slate-900'
                        }`}
                      >
                        {speed}x
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Description */}
            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">JSON Key: "description"</span>
              <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-slate-300 leading-relaxed">
                {generatedScript.description}
              </div>
            </div>

            {/* Tags */}
            <div>
              <span className="text-slate-400 font-mono text-[11px] block mb-1">JSON Key: "tags"</span>
              <div className="flex flex-wrap gap-1.5 p-2.5 bg-slate-950 border border-slate-800 rounded-xl">
                {generatedScript.tags.map((tag, idx) => (
                  <span key={idx} className="px-2.5 py-1 bg-slate-900 text-amber-400 rounded-lg text-xs font-mono border border-slate-800">
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
