import React from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

interface NoticeBannerProps {
  tone?: 'info' | 'success' | 'warning' | 'error';
  message: string;
  onClose?: () => void;
}

const toneClassMap = {
  info: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200',
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200',
  error: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-200',
};

const NoticeBanner: React.FC<NoticeBannerProps> = ({ tone = 'info', message, onClose }) => {
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'error' ? AlertCircle : Info;

  return (
    <div className={`flex items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-sm ${toneClassMap[tone]}`} role="status" aria-live="polite">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <span>{message}</span>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 transition hover:bg-black/5 dark:hover:bg-white/5"
          aria-label="Dismiss notice"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
};

export default NoticeBanner;
