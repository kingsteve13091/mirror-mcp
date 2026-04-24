import React, { useMemo, useState } from 'react';
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  UploadCloud,
  X,
} from 'lucide-react';
import AppModal from '../common/AppModal';
import {
  AgentTask,
  AgentTaskReplayEvent,
  RuntimeRequestJournalEntry,
  SystemOperationApproval,
} from '../../types';

interface PendingOutboundRequest {
  request_id: string;
  type: string;
  created_at?: string;
  content_preview?: string;
  server_name?: string;
  tool_name?: string;
  prompt_name?: string;
  uri?: string;
}

interface TaskCenterProps {
  isOpen: boolean;
  onClose: () => void;
  loading: boolean;
  pendingQueueSize: number;
  pendingOutboundRequests: PendingOutboundRequest[];
  tasks: RuntimeRequestJournalEntry[];
  agentTasks?: AgentTask[];
  pendingApprovals?: SystemOperationApproval[];
  selectedTaskReplay?: AgentTaskReplayEvent[];
  selectedTaskId?: string;
  onRefresh: () => Promise<void> | void;
  onRetryRequest?: (requestId: string) => void;
  onCancelQueuedRequest?: (requestId: string) => void;
  onCancelAgentTask?: (taskId: string) => void;
  onOpenTaskReplay?: (taskId: string) => void;
  onOpenApproval?: (approval: SystemOperationApproval) => void;
  language: 'zh' | 'en';
}

type TaskFilter = 'all' | 'queued' | 'runtime' | 'agent';

const cardClass = 'rounded-3xl border border-slate-200 bg-white/95 p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900/80';

function t(language: 'zh' | 'en', zh: string, en: string) {
  return language === 'zh' ? zh : en;
}

function zh(value: string) {
  return value;
}

function formatDate(value: string | undefined, language: 'zh' | 'en') {
  if (!value) {
    return t(language, zh('\u672a\u77e5\u65f6\u95f4'), 'Unknown time');
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatRuntimeDuration(durationMs: number | null | undefined, language: 'zh' | 'en') {
  if (typeof durationMs !== 'number') {
    return t(language, zh('\u672a\u8bb0\u5f55'), 'n/a');
  }
  if (durationMs < 1000) {
    return `${durationMs} ms`;
  }
  return `${(durationMs / 1000).toFixed(1)} s`;
}

function statusTone(status: string) {
  switch (status) {
    case 'completed':
    case 'success':
    case 'approved':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200';
    case 'failed':
    case 'interrupted':
    case 'cancelled':
    case 'rejected':
    case 'error':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200';
    case 'blocked':
    case 'waiting_approval':
    case 'pending':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200';
    case 'running':
    case 'inflight':
      return 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-200';
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200';
  }
}

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-right text-slate-900 dark:text-white">{value}</span>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-3xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
      {text}
    </div>
  );
}

function ReplayEventCard({
  event,
  language,
}: {
  event: AgentTaskReplayEvent;
  language: 'zh' | 'en';
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-slate-900 dark:text-white">{event.event}</span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusTone(event.source_plane)}`}>
            {event.source_plane}
          </span>
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {formatDate(event.timestamp, language)}
        </div>
      </div>
      {event.step_id && (
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {t(language, zh('\u6b65\u9aa4'), 'Step')}: {event.step_id}
        </div>
      )}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-slate-600 transition hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {expanded
          ? t(language, zh('\u9690\u85cf\u8be6\u60c5'), 'Hide details')
          : t(language, zh('\u67e5\u770b\u8be6\u60c5'), 'View details')}
      </button>
      {expanded && (
        <pre className="mt-3 max-h-60 overflow-auto rounded-2xl bg-slate-950 px-4 py-3 text-xs text-slate-100">
          {JSON.stringify(event.payload || {}, null, 2)}
        </pre>
      )}
    </div>
  );
}

const TaskCenter: React.FC<TaskCenterProps> = ({
  isOpen,
  onClose,
  loading,
  pendingQueueSize,
  pendingOutboundRequests,
  tasks,
  agentTasks = [],
  pendingApprovals = [],
  selectedTaskReplay = [],
  selectedTaskId,
  onRefresh,
  onRetryRequest,
  onCancelQueuedRequest,
  onCancelAgentTask,
  onOpenTaskReplay,
  onOpenApproval,
  language,
}) => {
  const [filter, setFilter] = useState<TaskFilter>('all');

  const visibleRuntimeTasks = useMemo(() => (filter === 'agent' ? [] : tasks), [filter, tasks]);
  const visibleAgentTasks = useMemo(() => (filter === 'runtime' ? [] : agentTasks), [filter, agentTasks]);

  const runningCount = tasks.filter((task) => task.status === 'inflight').length
    + agentTasks.filter((task) => task.status === 'running').length;

  const title = t(language, zh('\u4efb\u52a1\u4e2d\u5fc3'), 'Task Center');
  const description = t(
    language,
    zh('\u96c6\u4e2d\u67e5\u770b\u6392\u961f\u8bf7\u6c42\u3001\u8fd0\u884c\u4e2d\u94fe\u8def\u3001Agent \u591a\u6b65\u4efb\u52a1\u3001\u5ba1\u6279\u52a8\u4f5c\u4e0e\u4efb\u52a1\u56de\u653e\u3002'),
    'A unified view of queued requests, runtime chains, agent tasks, approvals, and replay.',
  );

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title={title}
      description={description}
      maxWidthClassName="max-w-7xl"
      bodyClassName="p-6"
      headerActions={(
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { void onRefresh(); }}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
            aria-label={t(language, zh('\u5237\u65b0\u4efb\u52a1\u4e2d\u5fc3'), 'Refresh task center')}
          >
            <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
            aria-label={t(language, zh('\u5173\u95ed\u4efb\u52a1\u4e2d\u5fc3'), 'Close task center')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      )}
    >
      <div className="space-y-5">
        <div className="grid gap-4 md:grid-cols-5">
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              {t(language, zh('\u672c\u5730\u961f\u5217'), 'Local queue')}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{pendingQueueSize}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              {t(language, zh('\u8fd0\u884c\u65f6\u8bf7\u6c42'), 'Runtime requests')}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{tasks.length}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              {t(language, zh('Agent \u4efb\u52a1'), 'Agent tasks')}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{agentTasks.length}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              {t(language, zh('\u5f85\u5ba1\u6279'), 'Pending approvals')}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{pendingApprovals.length}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
              {t(language, zh('\u8fdb\u884c\u4e2d'), 'Running')}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{runningCount}</div>
          </div>
        </div>

        {pendingApprovals.length > 0 && (
          <section className="rounded-3xl border border-amber-200 bg-amber-50/80 p-4 dark:border-amber-900/40 dark:bg-amber-950/20">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-amber-900 dark:text-amber-100">
              <ShieldAlert className="h-4 w-4" />
              <span>{t(language, zh('\u5f85\u5904\u7406\u7cfb\u7edf\u64cd\u4f5c\u5ba1\u6279'), 'Pending system operation approvals')}</span>
            </div>
            <div className="space-y-3">
              {pendingApprovals.map((approval) => (
                <div
                  key={approval.approval_id}
                  className="rounded-2xl border border-amber-200 bg-white/80 p-4 dark:border-amber-900/40 dark:bg-slate-950/40"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <div className="font-medium text-slate-900 dark:text-white">{approval.action_type}</div>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusTone(approval.status)}`}>
                          {approval.status}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {t(language, zh('\u4efb\u52a1'), 'Task')}: {approval.task_id}
                      </div>
                      <div className="text-sm text-slate-600 dark:text-slate-300">{approval.reason}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => onOpenApproval?.(approval)}
                      className="rounded-2xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
                    >
                      {t(language, zh('\u6253\u5f00\u5ba1\u6279'), 'Open approval')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="flex flex-wrap gap-2">
          {([
            ['all', t(language, zh('\u5168\u90e8'), 'All')],
            ['queued', t(language, zh('\u961f\u5217'), 'Queued')],
            ['runtime', t(language, zh('\u8fd0\u884c\u65f6'), 'Runtime')],
            ['agent', 'Agent'],
          ] as Array<[TaskFilter, string]>).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                filter === value
                  ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {(filter === 'all' || filter === 'queued') && (
          <section className={cardClass}>
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <UploadCloud className="h-4 w-4 text-sky-500" />
              <span>{t(language, zh('\u672c\u5730\u5f85\u53d1\u9001\u961f\u5217'), 'Local outbound queue')}</span>
            </div>
            <div className="space-y-3">
              {pendingOutboundRequests.length === 0 && (
                <EmptyState text={t(language, zh('\u5f53\u524d\u6ca1\u6709\u5f85\u53d1\u9001\u8bf7\u6c42\u3002'), 'No queued outbound requests.')} />
              )}
              {pendingOutboundRequests.map((item) => (
                <div key={item.request_id} className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-700">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-slate-900 dark:text-white">{item.type}</div>
                      <div className="font-mono text-xs text-slate-500 dark:text-slate-400">{item.request_id}</div>
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at, language)}</div>
                  </div>
                  {(item.content_preview || item.tool_name || item.uri || item.prompt_name) && (
                    <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                      {item.content_preview || item.tool_name || item.prompt_name || item.uri}
                    </div>
                  )}
                  {onCancelQueuedRequest && (
                    <button
                      type="button"
                      onClick={() => onCancelQueuedRequest(item.request_id)}
                      className="mt-3 rounded-2xl border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 dark:border-rose-900/50 dark:text-rose-300 dark:hover:bg-rose-950/20"
                    >
                      {t(language, zh('\u53d6\u6d88\u6392\u961f'), 'Cancel queue')}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {(filter === 'all' || filter === 'runtime') && (
          <section className="space-y-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Clock3 className="h-4 w-4 text-emerald-500" />
              <span>{t(language, zh('\u8fd0\u884c\u65f6\u8bf7\u6c42\u65e5\u5fd7'), 'Runtime request journal')}</span>
            </div>
            {visibleRuntimeTasks.length === 0 && (
              <EmptyState text={t(language, zh('\u5f53\u524d\u6ca1\u6709\u8fd0\u884c\u65f6\u8bf7\u6c42\u3002'), 'No runtime requests.')} />
            )}
            {visibleRuntimeTasks.map((task) => (
              <div key={task.request_id} className={cardClass}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-900 dark:text-white">{task.request_type}</span>
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusTone(task.status)}`}>
                        {task.status}
                      </span>
                    </div>
                    <div className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{task.request_id}</div>
                  </div>
                  <div className="text-right text-xs text-slate-500 dark:text-slate-400">
                    <div>{formatDate(task.updated_at || task.started_at, language)}</div>
                    <div>
                      {t(language, zh('\u8017\u65f6'), 'Duration')}: {formatRuntimeDuration(task.duration_ms, language)}
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-3">
                  <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                    <div className="font-medium text-slate-900 dark:text-white">{t(language, zh('\u8bf7\u6c42\u6458\u8981'), 'Request summary')}</div>
                    <div className="mt-2 space-y-1 text-slate-600 dark:text-slate-300">
                      {task.request_summary.content_preview && <div>{task.request_summary.content_preview}</div>}
                      {task.request_summary.tool_name && (
                        <div>{task.request_summary.server_name}.{task.request_summary.tool_name}</div>
                      )}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                    <div className="font-medium text-slate-900 dark:text-white">{t(language, zh('\u7ed3\u679c\u6458\u8981'), 'Result summary')}</div>
                    <div className="mt-2 space-y-1 text-slate-600 dark:text-slate-300">
                      {task.result_summary.reason && <div>{task.result_summary.reason}</div>}
                      {task.result_summary.content_preview && <div>{task.result_summary.content_preview}</div>}
                      {task.result_summary.result_preview && <div>{task.result_summary.result_preview}</div>}
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                    <div className="font-medium text-slate-900 dark:text-white">{t(language, zh('\u6062\u590d\u80fd\u529b'), 'Recovery')}</div>
                    <div className="mt-2 space-y-1 text-slate-600 dark:text-slate-300">
                      <div>{t(language, zh('\u5ba2\u6237\u7aef'), 'Clients')}: {task.client_ids.length}</div>
                      <div>
                        {t(language, zh('\u53ef\u6062\u590d'), 'Recoverable')}:{' '}
                        {task.is_recoverable ? t(language, zh('\u662f'), 'Yes') : t(language, zh('\u5426'), 'No')}
                      </div>
                    </div>
                    {task.is_recoverable && onRetryRequest && (
                      <button
                        type="button"
                        onClick={() => onRetryRequest(task.request_id)}
                        className="mt-3 rounded-2xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        {t(language, zh('\u5b9a\u4f4d\u5e76\u91cd\u8bd5'), 'Find and retry')}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </section>
        )}

        {(filter === 'all' || filter === 'agent') && (
          <section className="space-y-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Bot className="h-4 w-4 text-violet-500" />
              <span>{t(language, zh('Agent \u4efb\u52a1'), 'Agent tasks')}</span>
            </div>
            {visibleAgentTasks.length === 0 && (
              <EmptyState text={t(language, zh('\u5f53\u524d\u6ca1\u6709 Agent \u4efb\u52a1\u3002'), 'No agent tasks.')} />
            )}
            {visibleAgentTasks.map((task) => {
              const pendingApprovalCount = (task.pending_approvals || []).filter((item) => item.status === 'pending').length;
              const currentStep = task.steps[task.current_step_index ?? 0];
              const recentObservations = (task.observations || []).slice(-3);

              return (
                <div key={task.task_id} className={cardClass}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-slate-900 dark:text-white">{task.goal || task.mode}</span>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusTone(task.status)}`}>
                          {task.status}
                        </span>
                        <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold text-violet-700 dark:bg-violet-900/40 dark:text-violet-200">
                          {task.mode}
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{task.task_id}</div>
                    </div>
                    <div className="text-right text-xs text-slate-500 dark:text-slate-400">
                      <div>{formatDate(task.updated_at || task.created_at, language)}</div>
                      <div>{t(language, zh('\u6b65\u9aa4\u6570'), 'Steps')}: {task.steps.length}</div>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 xl:grid-cols-[1.3fr_1fr_1fr_0.9fr]">
                    <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                      <div className="mb-2 font-medium text-slate-900 dark:text-white">{t(language, zh('\u8ba1\u5212\u8fdb\u5ea6'), 'Plan progress')}</div>
                      <div className="space-y-2">
                        {task.steps.map((step, index) => (
                          <div key={step.step_id} className="rounded-2xl border border-slate-200 px-3 py-2 dark:border-slate-700">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-slate-900 dark:text-white">{index + 1}. {step.title}</span>
                              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusTone(step.status || 'pending')}`}>
                                {step.status || 'pending'}
                              </span>
                            </div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {step.kind} / {step.action}
                            </div>
                            {step.error && (
                              <div className="mt-2 rounded-xl bg-rose-50 px-2.5 py-2 text-xs text-rose-700 dark:bg-rose-950/20 dark:text-rose-200">
                                {step.error}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                      <div className="mb-2 font-medium text-slate-900 dark:text-white">{t(language, zh('\u6267\u884c\u6458\u8981'), 'Execution summary')}</div>
                      <div className="space-y-2">
                        <InfoRow
                          label={t(language, zh('\u5f53\u524d\u6b65\u9aa4'), 'Current step')}
                          value={currentStep ? currentStep.title : t(language, zh('\u65e0'), 'None')}
                        />
                        <InfoRow label="MCP" value={task.source_plane_counts?.mcp || 0} />
                        <InfoRow label="system_op" value={task.source_plane_counts?.system_op || 0} />
                        <InfoRow
                          label={t(language, zh('\u5f85\u5ba1\u6279'), 'Pending approvals')}
                          value={pendingApprovalCount}
                        />
                      </div>
                      {task.result_summary && Object.keys(task.result_summary).length > 0 && (
                        <div className="mt-3 rounded-2xl border border-slate-200 bg-white/80 p-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
                          {task.result_summary.summary
                            || task.result_summary.reason
                            || task.result_summary.message
                            || JSON.stringify(task.result_summary)}
                        </div>
                      )}
                    </div>

                    <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                      <div className="mb-2 font-medium text-slate-900 dark:text-white">{t(language, zh('\u6700\u8fd1\u89c2\u5bdf'), 'Recent observations')}</div>
                      <div className="space-y-2">
                        {recentObservations.length === 0 && (
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {t(language, zh('\u6682\u65e0\u89c2\u5bdf\u8bb0\u5f55\u3002'), 'No observations yet.')}
                          </div>
                        )}
                        {recentObservations.map((item, index) => (
                          <div key={`${item.timestamp}-${index}`} className="rounded-2xl border border-slate-200 px-3 py-2 text-xs dark:border-slate-700">
                            <div className="font-medium text-slate-900 dark:text-white">
                              {item.source_plane} / {item.action}
                            </div>
                            <div className="mt-1 line-clamp-2 text-slate-500 dark:text-slate-400">
                              {JSON.stringify(item.observation || {})}
                            </div>
                            <div className="mt-1 text-slate-400 dark:text-slate-500">{formatDate(item.timestamp, language)}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="rounded-2xl bg-slate-50 px-3 py-3 text-sm dark:bg-slate-800/70">
                      <div className="mb-2 flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                        <ListChecks className="h-4 w-4 text-indigo-500" />
                        <span>{t(language, zh('\u64cd\u4f5c'), 'Actions')}</span>
                      </div>
                      <div className="space-y-2">
                        <button
                          type="button"
                          onClick={() => onOpenTaskReplay?.(task.task_id)}
                          className="w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                        >
                          {selectedTaskId === task.task_id
                            ? t(language, zh('\u5df2\u52a0\u8f7d\u56de\u653e'), 'Replay loaded')
                            : t(language, zh('\u67e5\u770b\u56de\u653e'), 'View replay')}
                        </button>
                        {pendingApprovalCount > 0 && (
                          <div className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                            <AlertCircle className="h-3.5 w-3.5" />
                            {t(language, zh('\u7b49\u5f85\u5ba1\u6279'), 'Waiting for approval')}
                          </div>
                        )}
                        {onCancelAgentTask && task.status !== 'completed' && task.status !== 'cancelled' && (
                          <button
                            type="button"
                            onClick={() => onCancelAgentTask(task.task_id)}
                            className="w-full rounded-2xl border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 dark:border-rose-900/50 dark:text-rose-300 dark:hover:bg-rose-950/20"
                          >
                            {t(language, zh('\u53d6\u6d88\u4efb\u52a1'), 'Cancel task')}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </section>
        )}

        {selectedTaskId && (
          <section className={cardClass}>
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <ListChecks className="h-4 w-4 text-indigo-500" />
              <span>{t(language, zh('\u4efb\u52a1\u56de\u653e'), 'Task replay')}: {selectedTaskId}</span>
            </div>
            {selectedTaskReplay.length === 0 ? (
              <EmptyState text={t(language, zh('\u6682\u65f6\u6ca1\u6709\u56de\u653e\u4e8b\u4ef6\u3002'), 'No replay events yet.')} />
            ) : (
              <div className="space-y-3">
                {selectedTaskReplay.map((event) => (
                  <ReplayEventCard key={event.event_id} event={event} language={language} />
                ))}
              </div>
            )}
          </section>
        )}

        <section className="rounded-3xl border border-dashed border-slate-300 px-4 py-4 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          <div className="flex items-start gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            <span>
              {t(
                language,
                zh('\u4efb\u52a1\u4e2d\u5fc3\u4f18\u5148\u5c55\u793a\u4ea7\u54c1\u5316\u6458\u8981\uff1b\u5ba1\u6279\u3001\u56de\u653e\u548c system_op \u4ecd\u4e0e MCP recipe/guard \u5206\u5c42\u6cbb\u7406\uff0c\u4e0d\u4f1a\u6df7\u5199\u3002'),
                'The task center prioritizes product-style summaries while keeping approvals, replay, and system_op separate from MCP recipe/guard governance.',
              )}
            </span>
          </div>
        </section>
      </div>
    </AppModal>
  );
};

export default TaskCenter;

