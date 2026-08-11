import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  datetimeLocalToIso,
  formatLocalDateTime,
  toDatetimeLocalFromISO,
  toDatetimeLocalValue,
} from './dateTime';
import { cn, debounce, formatBytes, generateId } from './utils';

describe('dateTime', () => {
  it('formats valid dates and rejects invalid input', () => {
    expect(formatLocalDateTime(null)).toBe('-');
    expect(formatLocalDateTime('invalid')).toBe('-');
    expect(formatLocalDateTime('2026-08-11T10:20:30')).toMatch(/^2026-08-11 10:20:30$/);
    expect(toDatetimeLocalFromISO('invalid')).toBe('');
  });

  it('round-trips datetime-local values through ISO', () => {
    const date = new Date(2026, 7, 11, 10, 20, 0);
    const local = toDatetimeLocalValue(date);
    expect(local).toBe('2026-08-11T10:20');
    expect(toDatetimeLocalFromISO(date.toISOString())).toBe(local);
    expect(datetimeLocalToIso(local)).toBe(date.toISOString());
    expect(datetimeLocalToIso('')).toBeNull();
    expect(datetimeLocalToIso('invalid')).toBeNull();
  });
});

describe('utils', () => {
  afterEach(() => vi.useRealTimers());

  it('formats bytes and combines class names', () => {
    expect(formatBytes(0)).toBe('0 Bytes');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1536, 1)).toBe('1.5 KB');
    expect(formatBytes(1024 ** 3, -1)).toBe('1 GB');
    expect(cn('base', false, ['active'])).toBe('base active');
  });

  it('debounces calls and generates scoped ids', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-11T00:00:00Z'));
    vi.spyOn(Math, 'random').mockReturnValue(0.5);
    const callback = vi.fn();
    const debounced = debounce(callback, 100);
    debounced('first');
    debounced('second');
    vi.advanceTimersByTime(99);
    expect(callback).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(callback).toHaveBeenCalledOnce();
    expect(callback).toHaveBeenCalledWith('second');
    expect(generateId()).toMatch(/^obj_\d+_[a-z0-9]+$/);
  });
});
