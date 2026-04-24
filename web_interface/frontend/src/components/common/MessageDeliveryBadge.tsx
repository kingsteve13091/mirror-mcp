import React from 'react';
import { CheckCircle2, Clock3, Loader2, RotateCcw, ShieldAlert, XCircle } from 'lucide-react';
import { MessageDeliveryStatus } from '../../types';
import { useI18n } from '../../i18n/I18nProvider';

interface MessageDeliveryBadgeProps {
  status?: MessageDeliveryStatus;
  error?: string;
  retryable?: boolean;
  onRetry?: () => void;
}

const badgeTone: Record<NonNullable<MessageDeliveryStatus>, string> = {
  draft: 'border-slate-200 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300',
  pending: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-300',
  sent: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-300',
  processing: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900/40 dark:bg-violet-900/20 dark:text-violet-300',
  failed: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300',
  blocked: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300',
};

const MessageDeliveryBadge: React.FC<MessageDeliveryBadgeProps> = ({ status, error, retryable, onRetry }) => {
  const { t } = useI18n();
  if (!status) {
    return null;
  }

  const icon =
    status === 'pending' ? <Clock3 className="h-3.5 w-3.5" />
      : status === 'processing' ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
        : status === 'sent' ? <CheckCircle2 className="h-3.5 w-3.5" />
          : status === 'blocked' ? <ShieldAlert className="h-3.5 w-3.5" />
            : <XCircle className="h-3.5 w-3.5" />;

  const label =
    status === 'pending' ? t('delivery.pending')
      : status === 'processing' ? t('delivery.processing')
        : status === 'sent' ? t('delivery.sent')
          : status === 'blocked' ? t('delivery.blocked')
            : t('delivery.failed');

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium ${badgeTone[status]}`}>
        {icon}
        <span>{label}</span>
      </span>
      {error && (status === 'failed' || status === 'blocked') && (
        <span className="text-[11px] text-rose-500 dark:text-rose-300">{error}</span>
      )}
      {retryable && onRetry && (status === 'failed' || status === 'blocked') && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          <span>{t('delivery.retry')}</span>
        </button>
      )}
    </div>
  );
};

export default MessageDeliveryBadge;
