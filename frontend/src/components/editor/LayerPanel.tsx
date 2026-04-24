'use client';

import { cn } from '@/lib/utils';
import { Eye, EyeOff, Lock, Unlock } from 'lucide-react';

interface Layer {
  id: string;
  name: string;
  type: string;
  visible: boolean;
  locked: boolean;
}

const mockLayers: Layer[] = [
  { id: '1', name: '背景', type: 'rect', visible: true, locked: true },
  { id: '2', name: '标题文字', type: 'text', visible: true, locked: false },
  { id: '3', name: '装饰圆形', type: 'circle', visible: true, locked: false },
  { id: '4', name: '产品图片', type: 'image', visible: false, locked: false },
];

const typeIcons: Record<string, string> = {
  rect: '▬',
  circle: '●',
  triangle: '▲',
  text: 'T',
  image: '🖼',
};

export function LayerPanel() {
  const selectedLayer = '2';

  return (
    <div className="flex-1 overflow-auto">
      <div className="px-3 py-2.5 border-b">
        <h3 className="text-sm font-medium">图层</h3>
      </div>
      <div className="divide-y">
        {mockLayers.map((layer) => (
          <div
            key={layer.id}
            className={cn(
              'flex items-center gap-2 px-3 py-2 cursor-pointer text-sm transition-colors',
              selectedLayer === layer.id
                ? 'bg-primary/10 text-primary'
                : 'hover:bg-accent text-foreground'
            )}
          >
            <span className="w-6 h-6 rounded flex items-center justify-center text-xs bg-muted text-muted-foreground font-medium shrink-0">
              {typeIcons[layer.type] || '?'}
            </span>
            <span className="flex-1 truncate">{layer.name}</span>
            <div className="flex items-center gap-1">
              <button className="p-1 rounded hover:bg-background/50 text-muted-foreground">
                {layer.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              </button>
              <button className="p-1 rounded hover:bg-background/50 text-muted-foreground">
                {layer.locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
