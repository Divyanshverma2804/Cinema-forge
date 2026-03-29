import React from 'react';
import { Play, ExternalLink, Download, Clock, CheckCircle, AlertCircle, Video } from 'lucide-react';

interface VideoPreviewProps {
  status: string;
  outputPath?: string;
  shortPath?: string;
  ytVideoId?: string;
  errorMsg?: string;
  onUpload: (format: 'longform' | 'short') => void;
}

const VideoPreview: React.FC<VideoPreviewProps> = ({ 
  status, outputPath, shortPath, ytVideoId, errorMsg, onUpload 
}) => {
  // Use relative paths through Nginx proxy
  const getUrl = (path?: string) => {
    if (!path) return '';
    const filename = path.split(/[/\\]/).pop();
    const match = path.match(/project_\d+[/\\](.+)/);
    if (match) {
      const projectId = path.match(/project_(\d+)/)?.[1];
      return `/output/project_${projectId}/${match[1]}`;
    }
    return `/output/${filename}`;
  };

  const videoUrl = getUrl(outputPath);

  if (status === 'idle') return null;

  return (
    <div className="card bg-card/50 border-white/5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold flex items-center gap-2">
          <Play className="w-5 h-5 text-primary" />
          Production Result
        </h2>
        <div className="flex items-center gap-2">
          {status === 'rendering' && (
            <div className="flex items-center gap-2 text-xs text-blue-400">
              <Clock className="w-4 h-4 animate-spin" /> Rendering...
            </div>
          )}
          {status === 'rendered' && (
            <div className="flex items-center gap-2 text-xs text-green-400">
              <CheckCircle className="w-4 h-4" /> Ready to View
            </div>
          )}
          {status === 'uploading' && (
            <div className="flex items-center gap-2 text-xs text-purple-400">
              <Video className="w-4 h-4 animate-pulse" /> Uploading to YT...
            </div>
          )}
          {status === 'done' && (
            <div className="flex items-center gap-2 text-xs text-green-500 font-bold">
              <Video className="w-4 h-4" /> Published
            </div>
          )}
          {status === 'failed' && (
            <div className="flex items-center gap-2 text-xs text-red-400">
              <AlertCircle className="w-4 h-4" /> Failed
            </div>
          )}
        </div>
      </div>

      {errorMsg && (
        <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400">
          {errorMsg}
        </div>
      )}

      {(status === 'rendered' || status === 'uploading' || status === 'done') && (
        <div className="space-y-4">
          {videoUrl && (
            <div className="space-y-2">
              <p className="text-[10px] text-secondary font-mono uppercase tracking-widest">Main Production (16:9)</p>
              <video controls src={videoUrl} className="w-full rounded-lg border border-white/10 aspect-video bg-black" />
              <div className="flex gap-2">
                <button 
                  onClick={() => onUpload('longform')}
                  disabled={status === 'uploading' || status === 'done'}
                  className="btn btn-primary flex-1 py-2 text-xs flex items-center justify-center gap-2"
                >
                  <Video className="w-4 h-4" />
                  Upload to YouTube
                </button>
                <a 
                  href={videoUrl} 
                  download 
                  className="btn btn-outline p-2 rounded-lg"
                  title="Download"
                >
                  <Download className="w-4 h-4" />
                </a>
              </div>
            </div>
          )}

          {ytVideoId && (
            <div className="p-4 bg-primary/5 border border-primary/20 rounded-xl flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="bg-primary/20 p-2 rounded-lg">
                  <Video className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <p className="text-xs font-bold">Video Live on YouTube</p>
                  <p className="text-[10px] text-secondary">ID: {ytVideoId}</p>
                </div>
              </div>
              <a 
                href={`https://youtu.be/${ytVideoId}`} 
                target="_blank" 
                rel="noreferrer"
                className="btn btn-outline py-1 px-3 text-[10px] flex items-center gap-1"
              >
                View <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default VideoPreview;
