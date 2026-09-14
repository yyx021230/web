import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Ratio } from 'lucide-react';
import GenerationSetting from './GenerationSetting';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const options = [
  { value: '1:1', label: '1:1', description: 'Square' },
  { value: '3:4', label: '3:4', description: 'Portrait' },
];

describe('compact generation controls', () => {
  it('keeps an accessible label while displaying the selected value', async () => {
    await act(async () => root.render(<GenerationSetting label="Aspect ratio" icon={Ratio} value="3:4" onChange={vi.fn()} options={options} />));
    const trigger = host.querySelector('[role="combobox"]');
    expect(trigger?.getAttribute('aria-label')).toBe('Aspect ratio');
    expect(trigger?.getAttribute('title')).toBe('Aspect ratio');
    expect(trigger?.textContent).toContain('3:4');
  });

  it('updates the displayed value when model defaults change', async () => {
    const render = (value: string) => root.render(<GenerationSetting label="Aspect ratio" icon={Ratio} value={value} onChange={vi.fn()} options={options} />);
    await act(async () => render('3:4'));
    await act(async () => render('1:1'));
    expect(host.querySelector('[role="combobox"]')?.textContent).toContain('1:1');
  });

  it('prevents editing a setting fixed by the selected model', async () => {
    await act(async () => root.render(<GenerationSetting label="Aspect ratio" icon={Ratio} value="1:1" onChange={vi.fn()} options={options} disabled />));
    expect(host.querySelector('button')?.disabled).toBe(true);
  });
});
