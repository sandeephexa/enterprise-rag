import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { AlertCircle, Copy, Check } from 'lucide-react';
import { useState } from 'react';

export function Button({ children, className = '', variant = 'secondary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  return <button type="button" className={`button button-${variant} ${className}`} {...props}>{children}</button>;
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warning' | 'accent' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function ErrorNotice({ message }: { message?: string | null }) {
  return message ? <div role="alert" className="error-notice"><AlertCircle size={17} className="shrink-0" /><span>{message}</span></div> : null;
}
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />;
}
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  return <Button variant="ghost" className="!px-2" aria-label={label} onClick={async () => {
    try { await navigator.clipboard.writeText(value); setState('copied'); }
    catch { setState('failed'); }
  }}>{state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
    <span className={state === 'idle' ? 'sr-only' : 'text-xs'} role="status">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy unavailable' : label}</span>
  </Button>;
}
export const usd = (value: number) => `$${value.toFixed(6)}`;
export const duration = (ms: number) => ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(2)} s`;
export function safeSource(source: string): string | null {
  try { const url = new URL(source); return url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
}
