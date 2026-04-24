'use client';

import { useRef } from 'react';

interface CanvasAreaProps {
  canvasRef: React.RefObject<HTMLCanvasElement>;
  width?: number;
  height?: number;
}

export function CanvasArea({ canvasRef, width = 1242, height = 1656 }: CanvasAreaProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-auto canvas-container flex items-center justify-center p-8"
    >
      <div className="relative shadow-lg bg-white">
        <canvas
          ref={canvasRef}
          id="main-canvas"
          className="block"
          style={{ width, height }}
        />
      </div>
    </div>
  );
}
