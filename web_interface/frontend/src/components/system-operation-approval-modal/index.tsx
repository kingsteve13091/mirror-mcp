import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, ShieldAlert, XCircle } from 'lucide-react';
import AppModal from '../common/AppModal';
import { SystemOperationApproval } from '../../types';

interface SystemOperationApprovalModalProps {
  isOpen: boolean;
  approval: SystemOperationApproval | null;
  language: 'zh' | 'en';
  submitting?: boolean;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
  onClose: () => void;
}

function t(language: 'zh' | 'en', zh: string, en: string) {
  return language === 'zh' ? zh : en;
}

function zh(value: string) {
  return value;
}

const riskTone = (level: string) => {
  switch (level) {
    case 'high':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-200';
    case 'medium':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-200';
    default:
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200';
  }
};

const SystemOperationApprovalModal: React.FC<SystemOperationApprovalModalProps> = ({
  isOpen,
  approval,
  language,
  submitting = false,
  onApprove,
  onReject,
  onClose,
}) => {
  const [note, setNote] = useState('');

  useEffect(() => {
    if (isOpen) {
      setNote('');
    }
  }, [isOpen, approval?.approval_id]);

  const title = t(language, zh('\u7cfb\u7edf\u64cd\u4f5c\u5ba1\u6279'), 'System Operation Approval');
  const description = t(
    language,
    zh('\u8be5\u4efb\u52a1\u51c6\u5907\u6267\u884c\u9ad8\u98ce\u9669\u7cfb\u7edf\u64cd\u4f5c\uff0c\u9700\u8981\u4f60\u7684\u786e\u8ba4\u540e\u624d\u80fd\u7ee7\u7eed\u3002'),
    'This task is about to run a high-risk system action and needs your approval to continue.',
  );

  const payloadPreview = useMemo(() => approval?.payload_preview || '', [approval?.payload_preview]);

  if (!approval) {
    return null;
  }

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title={title}
      description={description}
      maxWidthClassName="max-w-3xl"
      bodyClassName="p-6"
    >
      <div className="space-y-5">
        <div className="rounded-3xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-900/60">
          <div className="flex flex-wrap items-center gap-3">
            <ShieldAlert className="h-5 w-5 text-amber-500" />
            <div className="text-base font-semibold text-slate-900 dark:text-white">{approval.action_type}</div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${riskTone(approval.risk_level)}`}>
              {approval.risk_level}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {approval.status}
            </span>
          </div>
          <div className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <div>{t(language, zh('\u539f\u56e0'), 'Reason')}: {approval.reason || '-'}</div>
            <div>{t(language, zh('\u5efa\u8bae'), 'Suggestion')}: {approval.suggestion || '-'}</div>
            <div>{t(language, zh('\u4efb\u52a1 ID'), 'Task ID')}: {approval.task_id}</div>
            {approval.workspace_root && (
              <div className="break-all">{t(language, zh('\u5de5\u4f5c\u533a'), 'Workspace')}: {approval.workspace_root}</div>
            )}
          </div>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950/50">
          <div className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">
            {t(language, zh('\u8bf7\u6c42\u8f7d\u8377\u9884\u89c8'), 'Requested payload preview')}
          </div>
          <pre className="max-h-72 overflow-auto rounded-2xl bg-slate-950 px-4 py-3 text-xs text-slate-100">
            {payloadPreview || '{}'}
          </pre>
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300" htmlFor="system-op-approval-note">
            {t(language, zh('\u5ba1\u6279\u5907\u6ce8\uff08\u53ef\u9009\uff09'), 'Approval note (optional)')}
          </label>
          <textarea
            id="system-op-approval-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={4}
            className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            placeholder={t(
              language,
              zh('\u4f8b\u5982\uff1a\u5141\u8bb8\u67e5\u770b\u65e5\u5fd7\uff0c\u4f46\u4e0d\u8981\u91cd\u542f\u670d\u52a1\u3002'),
              'For example: allow log read, but do not restart services.',
            )}
          />
        </div>

        <div className="flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={() => onReject(note)}
            disabled={submitting}
            className="inline-flex items-center gap-2 rounded-2xl border border-rose-200 px-4 py-2.5 text-sm font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-900/50 dark:text-rose-300 dark:hover:bg-rose-950/30"
          >
            <XCircle className="h-4 w-4" />
            {t(language, zh('\u62d2\u7edd\u5e76\u505c\u6b62\u4efb\u52a1'), 'Reject and stop task')}
          </button>
          <button
            type="button"
            onClick={() => onApprove(note)}
            disabled={submitting}
            className="inline-flex items-center gap-2 rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
          >
            <CheckCircle2 className="h-4 w-4" />
            {t(language, zh('\u6279\u51c6\u5e76\u7ee7\u7eed'), 'Approve and continue')}
          </button>
        </div>

        <div className="flex items-start gap-2 rounded-2xl border border-dashed border-slate-300 px-4 py-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {t(
              language,
              zh('System Operation Plane \u4e0e MCP Tool Plane \u5206\u5c42\u6cbb\u7406\u3002\u8fd9\u91cc\u7684\u5ba1\u6279\u53ea\u5f71\u54cd\u7cfb\u7edf\u64cd\u4f5c\uff0c\u4e0d\u4f1a\u628a system_op \u76f4\u63a5\u5199\u6210 recipe \u6216 guard\u3002'),
              'System Operation Plane stays separate from the MCP Tool Plane. This approval affects system actions only and does not write system_op directly into recipe or guard.',
            )}
          </span>
        </div>
      </div>
    </AppModal>
  );
};

export default SystemOperationApprovalModal;

