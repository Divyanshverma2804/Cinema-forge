import React, { useState } from 'react';
import { Send, FileText } from 'lucide-react';

interface ScriptEditorProps {
  onParse: (script: string) => void;
  isParsing: boolean;
}

const ScriptEditor: React.FC<ScriptEditorProps> = ({ onParse, isParsing }) => {
  const [script, setScript] = useState('');

  return (
    <div className="card h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <FileText className="w-6 h-6 text-primary" />
          Production Script
        </h2>
        <button
          onClick={() => onParse(script)}
          disabled={isParsing || !script.trim()}
          className="btn btn-primary flex items-center gap-2"
        >
          {isParsing ? 'Parsing...' : 'Extract Assets'}
          <Send className="w-4 h-4" />
        </button>
      </div>
      <textarea
        value={script}
        onChange={(e) => setScript(e.target.value)}
        placeholder="Paste your production script here...
# ProjectName: ...
# Type: narration
...
## Scene: ...
Background: [STOCK] ..."
        className="flex-1 input font-mono text-sm resize-none bg-background/50"
      />
    </div>
  );
};

export default ScriptEditor;
