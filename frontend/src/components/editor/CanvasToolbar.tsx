'use client';

import { cn } from '@/lib/utils';
import {
  MousePointer2,
  Square,
  Circle,
  Triangle,
  Type,
  Image,
  Pencil,
  Eraser,
  Undo2,
  Redo2,
} from 'lucide-react';

const tools = [
  { id: 'select', icon: MousePointer2, label: '选择' },
  { id: 'rect', icon: Square, label: '矩形' },
  { id: 'circle', icon: Circle, label: '圆形' },
  { id: 'triangle', icon: Triangle, label: '三角形' },
  { id: 'text', icon: Type, label: '文字' },
  { id: 'image', icon: Image, label: '图片' },
  { id: 'draw', icon: Pencil, label: '画笔' },
  { id: 'eraser', icon: Eraser, label: '橡皮擦' },
];

export function CanvasToolbar() {
  const activeTool = 'select';

  return (
    <div className="flex items-center gap-1 p-2 border-b bg-surface">
      {tools.map((tool) => (
        <button
          key={tool.id}
          title={tool.label}
          className={cn(
            'p-2 rounded-md transition-colors',
            activeTool === tool.id
              ? 'bg-primary text-white'
              : 'hover:bg-accent text-text-secondary'
          )}
        >
          <tool.icon className="h-4 w-4" />
        </button>
      ))}

      <div className="w-px h-6 bg-border mx-2" />

      <button className="p-2 rounded-md hover:bg-accent" title="撤销">
        <Undo2 className="h-4 w-4" />
      </button>
      <button className="p-2 rounded-md hover:bg-accent" title="重做">
        <Redo2 className="h-4 w-4" />
      </button>
    </div>
  );
}
