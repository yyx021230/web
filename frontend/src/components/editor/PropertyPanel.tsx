'use client';

import { useState } from 'react';

export function PropertyPanel() {
  const [width, setWidth] = useState(1242);
  const [height, setHeight] = useState(1656);

  return (
    <div className="p-3 space-y-4">
      <div>
        <h3 className="text-sm font-medium mb-3">画布设置</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">宽度</label>
            <input
              type="number"
              value={width}
              onChange={(e) => setWidth(Number(e.target.value))}
              className="w-full px-2 py-1.5 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">高度</label>
            <input
              type="number"
              value={height}
              onChange={(e) => setHeight(Number(e.target.value))}
              className="w-full px-2 py-1.5 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        </div>
      </div>

      <div className="border-t pt-4">
        <h3 className="text-sm font-medium mb-3">背景颜色</h3>
        <div className="flex gap-2 flex-wrap">
          {['#ffffff', '#000000', '#f8fafc', '#fef2f2', '#eff6ff', '#f0fdf4', '#fefce8'].map(
            (color) => (
              <button
                key={color}
                className="h-7 w-7 rounded-md border shadow-sm"
                style={{ backgroundColor: color }}
              />
            )
          )}
          <input
            type="color"
            className="h-7 w-7 rounded-md border-0 cursor-pointer"
          />
        </div>
      </div>

      <div className="border-t pt-4">
        <h3 className="text-sm font-medium mb-3">AI 快速生图</h3>
        <textarea
          placeholder="描述你想要生成的图片..."
          className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-primary resize-none h-20"
        />
        <button className="mt-2 w-full py-2 text-sm rounded-md bg-primary text-white hover:bg-primary-hover">
          生成图片
        </button>
      </div>
    </div>
  );
}
