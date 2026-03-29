import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Film, Play, Settings, Terminal, Activity } from 'lucide-react';
import ScriptEditor from './components/ScriptEditor';
import AssetDashboard from './components/AssetDashboard';
import type { AssetItem } from './components/AssetDashboard';
import VoiceManager from './components/VoiceManager';
import type { VoiceProfile } from './components/VoiceManager';
import VideoPreview from './components/VideoPreview';

const API_BASE = '/api';

// No need for complex auth headers if we use the same origin proxy
const getAuthHeaders = () => {
  return {};
};

const App: React.FC = () => {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [status, setStatus] = useState<string>('idle');
  const [error, setError] = useState<string | null>(null);
  const [videoPaths, setVideoPaths] = useState<{ longform?: string, short?: string }>({});
  const [ytVideoId, setYtVideoId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Poll project status if we have a project ID
  useEffect(() => {
    if (!projectId) return;

    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/projects/${projectId}`, {
          headers: getAuthHeaders(),
        });
        const data = res.data;
        setStatus(data.status);
        setVideoPaths({ longform: data.output_path, short: data.short_path });
        setYtVideoId(data.yt_video_id_en);
        setErrorMsg(data.error_msg);
        
        // In a real app, the API would return these structures
        // For now, we simulate the asset manifest updates
        if (data.manifest) {
          // Re-map from API format to our frontend format
          const allAssets: AssetItem[] = [
            ...data.manifest.auto_fetch.map((a: any) => ({ ...a, asset_type: 'STOCK' })),
            ...data.manifest.user_upload.map((a: any) => ({ ...a, asset_type: a.asset_type })),
          ];
          setAssets(allAssets);
        }
      } catch (err) {
        console.error('Status poll failed:', err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [projectId]);

  const handleParseScript = async (script: string) => {
    setIsParsing(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('script_md', script);
      
      const res = await axios.post(`${API_BASE}/submit`, formData, {
        headers: getAuthHeaders(),
      });
      if (res.data.ok) {
        setProjectId(res.data.project_id);
        // We also need to extract voices from the script locally for now
        // Or wait for the backend to return them
        extractVoices(script);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to parse script');
    } finally {
      setIsParsing(false);
    }
  };

  const extractVoices = (script: string) => {
    const speakerRegex = /^# Speaker:\s*(.+?)\s*\[(.+?)\]$/gm;
    const detected: Record<string, VoiceProfile> = {};
    let match;
    while ((match = speakerRegex.exec(script)) !== null) {
      detected[match[1]] = {
        name: match[1],
        emotion: match[2],
        has_ref: false,
      };
    }
    setVoices(Object.values(detected));
  };

  const handleRefreshStock = async (sceneName: string, index: number) => {
    if (!projectId) return;
    try {
      await axios.post(`${API_BASE}/projects/${projectId}/fetch_stock`, { 
        scene: sceneName,
        index: index
      }, {
        headers: getAuthHeaders(),
      });
    } catch (err) {
      console.error('Refresh failed:', err);
    }
  };

  const handleUploadAsset = async (sceneName: string, file: File) => {
    if (!projectId) return;
    try {
      const formData = new FormData();
      formData.append('file', file);
      await axios.post(`${API_BASE}/projects/${projectId}/upload/${sceneName}`, formData, {
        headers: getAuthHeaders(),
      });
    } catch (err) {
      console.error('Upload failed:', err);
    }
  };

  const handleUploadVoiceRef = async (speaker: string, file: File) => {
    if (!projectId) return;
    try {
      const formData = new FormData();
      formData.append('file', file);
      await axios.post(`${API_BASE}/voices/upload/${speaker}`, formData, {
        headers: getAuthHeaders(),
      });
      setVoices(prev => prev.map(v => v.name === speaker ? { ...v, has_ref: true } : v));
    } catch (err) {
      console.error('Voice upload failed:', err);
    }
  };

  const handleRemoveVoiceRef = async (speaker: string) => {
    if (!projectId) return;
    try {
      await axios.delete(`${API_BASE}/voices/${speaker}`, {
        headers: getAuthHeaders(),
      });
      setVoices(prev => prev.map(v => v.name === speaker ? { ...v, has_ref: false } : v));
    } catch (err) {
      console.error('Voice delete failed:', err);
    }
  };

  const handleRender = async () => {
    if (!projectId) return;
    try {
      await axios.post(`${API_BASE}/projects/${projectId}/render`, {}, {
        headers: getAuthHeaders(),
      });
      setStatus('rendering');
    } catch (err) {
      console.error('Render trigger failed:', err);
    }
  };

  const handleUploadToYoutube = async (format: 'longform' | 'short') => {
    if (!projectId) return;
    try {
      await axios.post(`${API_BASE}/projects/${projectId}/upload_yt?format=${format}`, {}, {
        headers: getAuthHeaders(),
      });
      setStatus('uploading');
    } catch (err) {
      console.error('YT Upload failed:', err);
    }
  };

  const isReadyToRender = assets.length > 0 && assets.every(a => a.status === 'ready');

  return (
    <div className="min-h-screen bg-background p-6 flex flex-col gap-6">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-white/10 pb-6">
        <div className="flex items-center gap-3">
          <div className="bg-primary/20 p-2 rounded-lg">
            <Film className="w-8 h-8 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-black tracking-tight m-0">CINEMA<span className="text-primary">FORGE</span></h1>
            <p className="text-xs text-secondary font-medium uppercase tracking-widest">Production Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-white/5 px-4 py-2 rounded-full border border-white/10">
            <Activity className="w-4 h-4 text-green-500" />
            <span className="text-sm font-semibold capitalize">{status}</span>
          </div>
          <button className="btn btn-outline p-2 rounded-full">
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Main Content Grid */}
      <main className="flex-1 grid grid-cols-12 gap-6 overflow-hidden min-h-0">
        {/* Left Column: Script Editor */}
        <div className="col-span-12 lg:col-span-4 flex flex-col">
          <ScriptEditor onParse={handleParseScript} isParsing={isParsing} />
        </div>

        {/* Middle Column: Assets Dashboard */}
        <div className="col-span-12 lg:col-span-5 flex flex-col">
          <AssetDashboard 
            assets={assets} 
            onRefreshStock={handleRefreshStock} 
            onUpload={handleUploadAsset} 
          />
        </div>

        {/* Right Column: Voice & Control */}
        <div className="col-span-12 lg:col-span-3 flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar">
          <div className="flex-shrink-0">
            <VideoPreview 
              status={status}
              outputPath={videoPaths.longform}
              shortPath={videoPaths.short}
              ytVideoId={ytVideoId || undefined}
              errorMsg={errorMsg || undefined}
              onUpload={handleUploadToYoutube}
            />
          </div>

          <div className="flex-1">
            <VoiceManager 
              voices={voices} 
              onUploadRef={handleUploadVoiceRef}
              onRemoveRef={handleRemoveVoiceRef} 
            />
          </div>

          {/* Render Control */}
          <div className="card bg-primary/10 border-primary/20 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="font-bold flex items-center gap-2">
                <Terminal className="w-4 h-4" /> Ready to Render?
              </h3>
            </div>
            <p className="text-xs text-secondary">
              Rendering will combine all assets, generate TTS, and composite the final video.
            </p>
            <button 
              disabled={!isReadyToRender || status === 'rendering'}
              onClick={handleRender}
              className="btn btn-primary w-full flex items-center justify-center gap-2 py-3"
            >
              <Play className="w-4 h-4 fill-current" />
              START PRODUCTION
            </button>
            {!isReadyToRender && assets.length > 0 && (
              <p className="text-[10px] text-amber-500 text-center font-medium">
                Waiting for {assets.filter(a => a.status !== 'ready').length} assets to be finalized.
              </p>
            )}
          </div>
        </div>
      </main>

      {/* Error Toast */}
      {error && (
        <div className="fixed bottom-6 right-6 bg-red-500 text-white px-6 py-3 rounded-lg shadow-xl flex items-center gap-3 animate-in fade-in slide-in-from-bottom-4">
          <span className="font-medium">{error}</span>
          <button onClick={() => setError(null)} className="opacity-70 hover:opacity-100">×</button>
        </div>
      )}
    </div>
  );
};

export default App;
