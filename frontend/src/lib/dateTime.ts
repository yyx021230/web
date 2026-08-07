function parseDate(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}


function pad(value: number): string {
  return String(value).padStart(2, '0');
}


export function formatLocalDateTime(value?: string | null): string {
  const date = parseDate(value);
  if (!date) return '-';
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}


export function toDatetimeLocalValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}


export function toDatetimeLocalFromISO(value?: string | null): string {
  const date = parseDate(value);
  if (!date) return '';
  return toDatetimeLocalValue(date);
}


export function datetimeLocalToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}
