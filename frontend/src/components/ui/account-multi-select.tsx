'use client';

import { Check, ChevronDown, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

export type AccountMultiSelectOption = {
  value: string;
  label: string;
};

type AccountMultiSelectProps = {
  options: AccountMultiSelectOption[];
  selectedValues: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
  clearLabel: string;
  emptyLabel: string;
  className?: string;
  dropdownClassName?: string;
};

export function AccountMultiSelect({
  options,
  selectedValues,
  onChange,
  placeholder,
  clearLabel,
  emptyLabel,
  className,
  dropdownClassName,
}: AccountMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, []);

  const optionMap = useMemo(() => new Map(options.map((option) => [option.value, option.label])), [options]);
  const selectedLabels = useMemo(() => (
    selectedValues
      .map((value) => optionMap.get(value))
      .filter((label): label is string => Boolean(label))
  ), [optionMap, selectedValues]);
  const triggerLabel = useMemo(() => {
    if (!selectedLabels.length) return placeholder;
    if (selectedLabels.length === 1) return selectedLabels[0];
    return `${selectedLabels[0]} 等 ${selectedLabels.length} 项`;
  }, [placeholder, selectedLabels]);

  const toggleValue = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((item) => item !== value));
      return;
    }
    onChange([...selectedValues, value]);
  };
  const filteredOptions = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return options;
    return options.filter((option) => `${option.label} ${option.value}`.toLowerCase().includes(q));
  }, [keyword, options]);

  const selectFilteredOptions = () => {
    const merged = new Set(selectedValues);
    filteredOptions.forEach((option) => merged.add(option.value));
    onChange(Array.from(merged));
  };

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        title={triggerLabel}
        className="flex h-10 w-full items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white px-3 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.06)] outline-none transition hover:border-slate-300 focus:border-slate-400 focus:ring-4 focus:ring-slate-100"
      >
        <span className="min-w-0 truncate">{triggerLabel}</span>
        <span className="flex shrink-0 items-center gap-2">
          {selectedValues.length ? (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
              {selectedValues.length}
            </span>
          ) : null}
          <ChevronDown className={cn('h-4 w-4 text-slate-400 transition', open && 'rotate-180')} />
        </span>
      </button>

      {open ? (
        <div className={cn('absolute right-0 top-[calc(100%+8px)] z-50 w-full min-w-[280px] rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_24px_60px_rgba(15,23,42,0.16)]', dropdownClassName)}>
          <div className="relative mb-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索名称 / 负责人 / ID"
              className="h-9 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:ring-4 focus:ring-slate-100"
            />
          </div>
          <div className="mb-2 flex items-center justify-between gap-3 px-2 py-1">
            <button
              type="button"
              onClick={() => onChange([])}
              className="text-sm font-medium text-slate-700 transition hover:text-slate-950"
            >
              {clearLabel}
            </button>
            <button
              type="button"
              disabled={!filteredOptions.length}
              onClick={selectFilteredOptions}
              className="text-sm font-medium text-slate-700 transition hover:text-slate-950 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              全选{keyword.trim() ? '当前搜索' : ''}
            </button>
            <span className="text-xs text-slate-400">
              {selectedValues.length ? `已选 ${selectedValues.length}` : '未筛选'}
            </span>
          </div>

          <div className="max-h-72 overflow-y-auto pr-1">
            {filteredOptions.length ? (
              filteredOptions.map((option) => {
                const checked = selectedValues.includes(option.value);
                return (
                  <label
                    key={option.value}
                    title={option.label}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    <span className={cn('flex h-4 w-4 items-center justify-center rounded border transition', checked ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-transparent')}>
                      <Check className="h-3 w-3" />
                    </span>
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggleValue(option.value)}
                    />
                    <span className="min-w-0 flex-1 truncate" title={option.label}>{option.label}</span>
                  </label>
                );
              })
            ) : (
              <div className="px-2 py-6 text-center text-sm text-slate-400">{emptyLabel}</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
