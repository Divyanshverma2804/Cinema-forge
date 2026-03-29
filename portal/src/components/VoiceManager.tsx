import React from 'react';
import { Mic, Upload, Play, Settings2, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';

export interface VoiceProfile {
  name: string;
  emotion: string;
  has_ref: boolean;
  ref_path?: string;
}

interface VoiceManagerProps {
  voices: VoiceProfile[];
  onUploadRef: (speaker: string, file: File) => void;
  onRemoveRef: (speaker: string) => void;
}

const VoiceManager: React.FC<VoiceManagerProps> = ({ voices, onUploadRef, onRemoveRef }) => {
  const [playing, setPlaying] = React.useState<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const handlePlay = (voice: VoiceProfile) => {
    if (playing === voice.name) {
      audioRef.current?.pause();
      setPlaying(null);
    } else {
      if (audioRef.current) {
        audioRef.current.src = `http://localhost:8001/voices/play/${voice.name}`;
        audioRef.current.play();
        setPlaying(voice.name);
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
        <div className="text-xs text-secondary bg-white/5 px-3 py-1 rounded-full">
          {voices.filter(v => v.has_ref).length} / {voices.length} Configured
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
        {voices.map((voice, i) => (
          <div key={i} className="bg-background/40 border border-white/5 rounded-lg p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">{voice.name}</h3>
                <span className="text-[10px] text-secondary font-mono bg-white/5 px-2 py-0.5 rounded uppercase">
                  {voice.emotion || 'default'}
                </span>
              </div>
              <div className="flex gap-2">
                {voice.has_ref ? (
                  <>
                    <button
                      onClick={() => handlePlay(voice)}
                      className={clsx(
                        "btn btn-outline p-2 rounded-full transition-colors",
                        playing === voice.name ? "text-primary border-primary" : "hover:text-primary"
                      )}
                    >
                      {playing === voice.name ? (
                        <div className="w-4 h-4 flex items-center gap-0.5">
                          <span className="w-0.5 h-3 bg-current animate-bounce" />
                          <span className="w-0.5 h-4 bg-current animate-bounce [animation-delay:0.1s]" />
                          <span className="w-0.5 h-2 bg-current animate-bounce [animation-delay:0.2s]" />
                        </div>
                      ) : (
                        <Play className="w-4 h-4" />
                      )}
                    </button>
                    <button
                      onClick={() => onRemoveRef(voice.name)}
                      className="btn btn-outline p-2 rounded-full hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <label className="btn btn-primary p-2 rounded-full cursor-pointer">
                    <Upload className="w-4 h-4" />
                    <input
                      type="file"
                      className="hidden"
                      accept=".wav,.mp3"
                      onChange={(e) => e.target.files?.[0] && onUploadRef(voice.name, e.target.files[0])}
                    />
                  </label>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 text-[10px] text-secondary">
              <Settings2 className="w-3 h-3" />
              <span>
                {voice.has_ref 
                  ? 'Using reference audio clone' 
                  : 'Falling back to emotion parameters'}
              </span>
            </div>
          </div>
        ))}

        {voices.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-secondary opacity-50 py-12">
            <Mic className="w-12 h-12 mb-4" />
            <p>No characters detected in script.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default VoiceManager;
