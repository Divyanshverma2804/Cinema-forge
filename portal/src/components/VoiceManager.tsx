import React from 'react';
import { Mic, Upload, Play, Settings2, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';

export interface VoiceProfile {
  name: string;
  emotion: string;
  assigned_voice?: string; // name of the system voice file (e.g. "morgan_freeman")
}

export interface SystemVoice {
  name: string;
  filename: string;
}

interface VoiceManagerProps {
  voices: VoiceProfile[];
  systemVoices: SystemVoice[];
  onUploadRef: (speaker: string, file: File) => void;
  onRemoveRef: (speaker: string) => void;
  onAssignVoice: (speaker: string, voiceName: string) => void;
}

const VoiceManager: React.FC<VoiceManagerProps> = ({ 
  voices, 
  systemVoices, 
  onUploadRef, 
  onRemoveRef,
  onAssignVoice 
}) => {
  const [playing, setPlaying] = React.useState<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const handlePlay = (voiceName: string) => {
    if (playing === voiceName) {
      audioRef.current?.pause();
      setPlaying(null);
    } else {
      if (audioRef.current) {
        // Relative path through proxy with cache buster
        audioRef.current.src = `/voices/play/${voiceName}?t=${Date.now()}`;
        audioRef.current.play();
        setPlaying(voiceName);
      }
    }
  };

  return (
    <div className="card h-full flex flex-col gap-4 overflow-hidden">
      <audio 
        ref={audioRef} 
        onEnded={() => setPlaying(null)} 
        className="hidden" 
      />
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Mic className="w-6 h-6 text-primary" />
          Voice Management
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto space-y-6 pr-2 custom-scrollbar">
        {/* Detected Characters Section */}
        <section>
          <h3 className="text-sm font-semibold text-secondary mb-3 flex items-center gap-2">
            <Mic className="w-4 h-4" /> Detected Characters
          </h3>
          <div className="space-y-3">
            {voices.map((char, i) => (
              <div key={i} className="bg-background/40 border border-white/5 rounded-lg p-3 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold">{char.name}</span>
                    <span className="ml-2 text-[10px] text-secondary uppercase bg-white/5 px-1 rounded">{char.emotion}</span>
                  </div>
                </div>
                
                <select 
                  value={char.assigned_voice || ""}
                  onChange={(e) => onAssignVoice(char.name, e.target.value)}
                  className="input py-1 text-xs bg-black/40 border-white/10"
                >
                  <option value="">Default AI Voice</option>
                  {systemVoices.map((sv, j) => (
                    <option key={j} value={sv.name}>{sv.name}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        </section>

        {/* System Voices Registry Section */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-secondary flex items-center gap-2">
              <Settings2 className="w-4 h-4" /> Voice Registry
            </h3>
            <label className="btn btn-outline py-0.5 px-2 text-[10px] cursor-pointer flex items-center gap-1">
              <Upload className="w-3 h-3" /> New
              <input 
                type="file" 
                className="hidden" 
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    const name = prompt("Enter a name for this voice:", file.name.split('.')[0]);
                    if (name) onUploadRef(name, file);
                  }
                }}
              />
            </label>
          </div>

          <div className="grid grid-cols-1 gap-2">
            {systemVoices.map((sv, i) => (
              <div key={i} className="flex items-center justify-between bg-white/5 p-2 rounded-lg border border-white/5 group">
                <span className="text-xs">{sv.name}</span>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button 
                    onClick={() => handlePlay(sv.name)}
                    className={clsx(
                      "p-1 rounded-full hover:bg-white/10",
                      playing === sv.name ? "text-primary" : "text-secondary"
                    )}
                  >
                    {playing === sv.name ? (
                      <div className="w-3 h-3 flex items-center gap-0.5">
                        <span className="w-0.5 h-2 bg-current animate-bounce" />
                        <span className="w-0.5 h-3 bg-current animate-bounce [animation-delay:0.1s]" />
                        <span className="w-0.5 h-1.5 bg-current animate-bounce [animation-delay:0.2s]" />
                      </div>
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                  </button>
                  <button 
                    onClick={() => onRemoveRef(sv.name)}
                    className="p-1 rounded-full hover:bg-white/10 text-secondary hover:text-red-500"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {voices.length === 0 && systemVoices.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-secondary opacity-50 py-12">
            <Mic className="w-12 h-12 mb-4" />
            <p>No voices or characters found.</p>
          </div>
        )}
      </div>
    </div>
  );    
};

export default VoiceManager;
