import React from 'react';
import { Image, Video, Upload, RefreshCw, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import { clsx } from 'clsx';

export interface AssetItem {
  scene_name: string;
  asset_type: 'STOCK' | 'AI_IMAGE' | 'AI_VIDEO' | 'USER_VIDEO';
  prompt: string;
  status: 'pending' | 'fetching' | 'ready' | 'failed';
  local_path?: string;
  pexels_url?: string;
}

interface AssetDashboardProps {
  assets: AssetItem[];
  onRefreshStock: (sceneName: string, index: number) => void;
  onUpload: (sceneName: string, file: File) => void;
}

const AssetDashboard: React.FC<AssetDashboardProps> = ({ assets, onRefreshStock, onUpload }) => {
  const stockAssets = assets.filter(a => a.asset_type === 'STOCK');
  const userAssets = assets.filter(a => a.asset_type !== 'STOCK');
  const [stockIndices, setStockIndices] = React.useState<Record<string, number>>({});

  const handleNextStock = (sceneName: string) => {
    const nextIdx = (stockIndices[sceneName] || 0) + 1;
    setStockIndices(prev => ({ ...prev, [sceneName]: nextIdx }));
    onRefreshStock(sceneName, nextIdx);
  };

  const AssetCard = ({ asset }: { asset: AssetItem }) => (
    <div className="bg-background/40 border border-white/5 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-secondary truncate max-w-[150px]">
          {asset.scene_name}
        </span>
        <div className="flex items-center gap-1">
          {asset.status === 'ready' && <CheckCircle className="w-4 h-4 text-green-500" />}
          {asset.status === 'pending' && <Clock className="w-4 h-4 text-amber-500" />}
          {asset.status === 'fetching' && <RefreshCw className="w-4 h-4 text-blue-500 animate-spin" />}
          {asset.status === 'failed' && <AlertCircle className="w-4 h-4 text-red-500" />}
        </div>
      </div>

      <div className="aspect-video bg-black/40 rounded flex items-center justify-center overflow-hidden border border-white/5 relative group">
        {asset.pexels_url ? (
          <img src={asset.pexels_url} alt={asset.prompt} className="w-full h-full object-cover" />
        ) : (
          <div className="text-center p-4">
            {asset.asset_type.includes('VIDEO') ? (
              <Video className="w-8 h-8 text-secondary mx-auto mb-2" />
            ) : (
              <Image className="w-8 h-8 text-secondary mx-auto mb-2" />
            )}
            <p className="text-[10px] text-secondary line-clamp-2">{asset.prompt}</p>
          </div>
        )}
        
        {/* Overlay for better visibility of type */}
        <div className="absolute top-2 left-2 px-2 py-0.5 bg-black/60 backdrop-blur-md rounded text-[8px] font-bold text-white uppercase tracking-wider border border-white/10">
          {asset.asset_type.replace('_', ' ')}
        </div>
      </div>

      <div className="flex gap-2">
        {asset.asset_type === 'STOCK' ? (
          <button
            onClick={() => handleNextStock(asset.scene_name)}
            className="btn btn-outline py-1 text-xs flex-1 flex items-center justify-center gap-1"
          >
            <RefreshCw className="w-3 h-3" /> Try Another
          </button>
        ) : (
          <label className="btn btn-outline py-1 text-xs flex-1 flex items-center justify-center gap-1 cursor-pointer">
            <Upload className="w-3 h-3" /> Upload
            <input
              type="file"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onUpload(asset.scene_name, e.target.files[0])}
            />
          </label>
        )}
      </div>
    </div>
  );

  return (
    <div className="card flex flex-col gap-6 h-full overflow-hidden">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Image className="w-6 h-6 text-accent" />
          Assets Dashboard
        </h2>
        <div className="text-xs text-secondary bg-white/5 px-3 py-1 rounded-full">
          {assets.filter(a => a.status === 'ready').length} / {assets.length} Ready
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-6 pr-2 custom-scrollbar">
        {stockAssets.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-secondary mb-3 flex items-center gap-2">
              <RefreshCw className="w-4 h-4" /> Stock Assets (Pexels)
            </h3>
            <div className="grid grid-cols-2 gap-4">
              {stockAssets.map((asset, i) => <AssetCard key={i} asset={asset} />)}
            </div>
          </section>
        )}

        {userAssets.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-secondary mb-3 flex items-center gap-2">
              <Upload className="w-4 h-4" /> AI & User Uploads
            </h3>
            <div className="grid grid-cols-2 gap-4">
              {userAssets.map((asset, i) => <AssetCard key={i} asset={asset} />)}
            </div>
          </section>
        )}

        {assets.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-secondary opacity-50 py-12">
            <Image className="w-12 h-12 mb-4" />
            <p>No assets extracted yet. Parse a script to begin.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default AssetDashboard;
