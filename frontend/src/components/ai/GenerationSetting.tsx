'use client';

import * as Select from '@radix-ui/react-select';
import { Check, ChevronDown, type LucideIcon } from 'lucide-react';

interface GenerationSettingProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  icon: LucideIcon;
  disabled?: boolean;
  options: { value: string; label: string; description?: string; disabled?: boolean }[];
}

export default function GenerationSetting({ label, value, onChange, icon: Icon, options, disabled }: GenerationSettingProps) {
  return (
    <Select.Root value={value} onValueChange={onChange} disabled={disabled}>
      <Select.Trigger aria-label={label} title={label} className="group flex h-8 min-w-0 items-center gap-1.5 rounded-lg border border-transparent bg-slate-50 px-2.5 text-left outline-none transition-colors hover:bg-indigo-50 focus-visible:ring-2 focus-visible:ring-primary/30 data-[state=open]:bg-indigo-50 disabled:cursor-default">
        <Icon aria-hidden="true" strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="min-w-0 truncate text-[11px] font-medium text-slate-600"><Select.Value /></span>
        {!disabled && <Select.Icon><ChevronDown className="h-3 w-3 text-slate-400 transition-transform group-data-[state=open]:rotate-180" /></Select.Icon>}
      </Select.Trigger>
      <Select.Portal>
        <Select.Content position="popper" side="top" sideOffset={6} collisionPadding={12} className="z-[100] max-h-[var(--radix-select-content-available-height)] min-w-[160px] overflow-hidden rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_12px_36px_rgba(15,23,42,0.14)]">
          <Select.ScrollUpButton className="flex justify-center py-1"><ChevronDown className="h-4 w-4 rotate-180" /></Select.ScrollUpButton>
          <Select.Viewport>
            {options.map(option => (
              <Select.Item key={option.value} value={option.value} disabled={option.disabled} className="relative cursor-pointer rounded-lg py-2 pl-3 pr-9 text-sm text-slate-700 outline-none data-[highlighted]:bg-slate-50 data-[state=checked]:bg-indigo-50 data-[state=checked]:text-primary data-[disabled]:pointer-events-none data-[disabled]:opacity-40">
                <Select.ItemText>{option.label}</Select.ItemText>
                {option.description && <span className="mt-0.5 block text-xs text-slate-500">{option.description}</span>}
                <Select.ItemIndicator className="absolute right-3 top-3"><Check className="h-3.5 w-3.5" /></Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
          <Select.ScrollDownButton className="flex justify-center py-1"><ChevronDown className="h-4 w-4" /></Select.ScrollDownButton>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
