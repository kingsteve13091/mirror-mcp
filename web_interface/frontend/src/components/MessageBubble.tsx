import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CausalTrace, ChatAttachment, ChatMessage, GeneratedImage, MemoryPlaneSnapshot, ResourceReference } from '../types';
import { Clock, Zap, User, Bot, Brain, Eye, FileText, Paperclip, Copy, CheckCircle, ChevronDown, ChevronRight, Wrench, ShieldAlert, ClipboardList, RefreshCw, Link2, FolderOpen } from 'lucide-react';
import { buildApiUrl } from '../config/backend';
import MessageDeliveryBadge from './common/MessageDeliveryBadge';
import { useI18n } from '../i18n/I18nProvider';
import { getAttachmentBodyHiddenNotice } from '../utils/attachmentTransparency';
import { formatToolSectionContent } from '../utils/displaySanitizers';
import AdvancedDebugTracePanel from './AdvancedDebugTracePanel';

interface MessageBubbleProps {
  message: ChatMessage;
  onRetry?: () => void;
  showAdvancedDebugTraces?: boolean;
}

function resolveAttachmentUrl(attachment: ChatAttachment) {
  if (attachment.url) {
    return attachment.url;
  }
  if (attachment.filename) {
    return buildApiUrl(`/api/uploads/${attachment.filename}`);
  }
  return '#';
}

function resolveImageSource(source?: string) {
  const value = String(source || '').trim();
  if (!value) {
    return '';
  }
  if (value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/')) {
    return value;
  }
  return buildApiUrl(`/api/uploads/${value}`);
}

const isRecord = (value: unknown): value is Record<string, any> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onRetry, showAdvancedDebugTraces = false }) => {
  const { t, language } = useI18n();
  const [copied, setCopied] = useState(false);
  const [copiedToolSection, setCopiedToolSection] = useState<string | null>(null);
  const [toolCardExpanded, setToolCardExpanded] = useState(false);
  const isUser = message.type === 'user';
  const isAssistant = message.type === 'assistant';
  const isSystem = message.type === 'system';
  const timestampClassName = isSystem
    ? 'text-amber-600 dark:text-amber-200/90'
    : 'text-slate-400 dark:text-gray-500';
  const contentClassName = isSystem
    ? 'text-[15px] leading-7 text-amber-950 dark:text-amber-50'
    : 'text-[15px] leading-7 text-slate-800 dark:text-slate-100';
  const inlineCodeClassName = isSystem
    ? 'rounded-md border border-amber-200/80 bg-amber-100/90 px-1.5 py-0.5 text-[0.92em] text-amber-950 dark:border-amber-300/20 dark:bg-amber-300/10 dark:text-amber-100'
    : 'rounded-md bg-slate-100 px-1.5 py-0.5 text-[0.92em] text-slate-700 dark:bg-slate-800 dark:text-slate-200';
  const blockquoteClassName = isSystem
    ? 'mb-3 rounded-r-xl border-l-4 border-amber-300 bg-amber-100/80 px-4 py-2 italic text-amber-900 dark:border-amber-300/50 dark:bg-amber-300/10 dark:text-amber-100'
    : 'mb-3 rounded-r-xl border-l-4 border-slate-300 bg-slate-50 px-4 py-2 italic text-slate-600 dark:border-slate-600 dark:bg-slate-800/70 dark:text-slate-300';
  const linkClassName = isUser
    ? 'font-medium text-white underline decoration-white/50 underline-offset-4'
    : isSystem
      ? 'font-medium text-amber-800 underline decoration-amber-400/70 underline-offset-4 dark:text-amber-200'
      : 'font-medium text-sky-700 underline decoration-sky-300/80 underline-offset-4 dark:text-sky-300';
  const strongClassName = isSystem
    ? 'font-semibold text-amber-950 dark:text-amber-50'
    : 'font-semibold text-slate-900 dark:text-slate-50';
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  const attachmentImageSources = attachments
    .filter((attachment) => attachment.is_image)
    .map((attachment) => resolveAttachmentUrl(attachment));
  const generatedImages = Array.isArray(message.metadata?.generated_images)
    ? (message.metadata?.generated_images as GeneratedImage[])
    : [];
  const bubbleImages = (() => {
    const seen = new Set<string>();
    const items: Array<{ src: string; alt: string }> = [];
    const pushImage = (src?: string, alt?: string) => {
      const resolved = resolveImageSource(src);
      if (!resolved || seen.has(resolved)) {
        return;
      }
      if (isAssistant && attachmentImageSources.includes(resolved)) {
        return;
      }
      seen.add(resolved);
      items.push({
        src: resolved,
        alt: alt || t('message.uploadedImageAlt'),
      });
    };

    if (isUser) {
      attachments
        .filter((attachment) => attachment.is_image)
        .forEach((attachment) => pushImage(resolveAttachmentUrl(attachment), attachment.original_filename || t('message.uploadedImageAlt')));
      if (items.length === 0) {
        pushImage(message.image_path, t('message.uploadedImageAlt'));
        if (Array.isArray(message.image_paths)) {
          message.image_paths.forEach((path) => pushImage(path, t('message.uploadedImageAlt')));
        }
      }
      return items;
    }

    generatedImages.forEach((image) => pushImage(image.url || image.data_url || image.path, image.alt || t('message.uploadedImageAlt')));
    if (Array.isArray(message.image_paths)) {
      message.image_paths.forEach((path) => pushImage(path, t('message.uploadedImageAlt')));
    }
    pushImage(message.image_path, t('message.uploadedImageAlt'));
    return items;
  })();

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

    if (diffInMinutes < 1) return t('message.justNow');
    if (diffInMinutes < 60) return t('message.minAgo', { count: diffInMinutes });
    if (diffInMinutes < 1440) return t('message.hrAgo', { count: Math.floor(diffInMinutes / 60) });

    return date.toLocaleTimeString(language === 'en' ? 'en-US' : 'zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const copyMessageContent = async () => {
    const text = message.content || '';
    if (!text.trim()) {
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', 'true');
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch (error) {
      console.error('Failed to copy message content:', error);
    }
  };

  const copyText = async (text: string, sectionKey: string) => {
    if (!text.trim()) {
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', 'true');
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopiedToolSection(sectionKey);
      window.setTimeout(() => setCopiedToolSection(null), 1600);
    } catch (error) {
      console.error('Failed to copy tool section:', error);
    }
  };

  const getToolMetadata = () => {
    const metadata = message.metadata || {};
    const toolEvidence = metadata.tool_evidence && typeof metadata.tool_evidence === 'object'
      ? (metadata.tool_evidence as Record<string, any>)
      : null;
    if (toolEvidence?.run_trace?.kind === 'tool_call') {
      return toolEvidence;
    }
    if (metadata.run_trace?.kind === 'tool_call') {
      return metadata as Record<string, any>;
    }
    return null;
  };

  const getAgentEventMetadata = () => {
    const metadata = message.metadata || {};
    const agentEvent = metadata.agent_event;
    if (agentEvent && typeof agentEvent === 'object' && typeof agentEvent.task_id === 'string') {
      return agentEvent as Record<string, any>;
    }
    return null;
  };

  const getActionEventMetadata = () => {
    const metadata = message.metadata || {};
    const actionEvent = metadata.action_event;
    if (actionEvent && typeof actionEvent === 'object' && typeof actionEvent.action_id === 'string') {
      return actionEvent as Record<string, any>;
    }
    return null;
  };

  const getResourceRefs = (): ResourceReference[] => {
    const metadataRefs = message.metadata?.resource_refs;
    if (Array.isArray(metadataRefs)) {
      return metadataRefs as ResourceReference[];
    }
    return [];
  };

  const getMemoryCardMetadata = () => {
    if (isUser || !message.metadata) {
      return null;
    }

    const metadata = message.metadata;
    const memoryPlane = isRecord(metadata.memory_plane)
      ? metadata.memory_plane as MemoryPlaneSnapshot
      : undefined;
    const causalTrace = isRecord(metadata.causal_trace)
      ? metadata.causal_trace as CausalTrace
      : undefined;
    const executionPolicy = isRecord((memoryPlane as any)?.execution_policy)
      ? (memoryPlane as any).execution_policy as Record<string, any>
      : {};
    const recipePreflight = isRecord(executionPolicy.recipe_preflight)
      ? executionPolicy.recipe_preflight
      : isRecord(metadata.recipe_preflight)
        ? metadata.recipe_preflight as Record<string, any>
        : undefined;
    const guardEvidence = isRecord(metadata.guard_evidence)
      ? metadata.guard_evidence as Record<string, any>
      : undefined;
    const routing = memoryPlane && isRecord(memoryPlane.routing) ? memoryPlane.routing : {};
    const routingScores = Array.isArray(routing.scores) ? routing.scores : [];
    const selectedTools = Array.isArray(routing.selected_tools) ? routing.selected_tools : [];
    const attribution = memoryPlane && Array.isArray(memoryPlane.attribution) ? memoryPlane.attribution : [];
    const traceSignificantEffects = causalTrace?.significant_causal_effects;
    const memoryPlaneAblationEffects = memoryPlane?.causal_ablation?.significant_effects;
    const causalTraceAblationEffects = causalTrace?.causal_ablation?.significant_effects;
    const significantEffects = Array.isArray(traceSignificantEffects)
      ? traceSignificantEffects
      : Array.isArray(memoryPlaneAblationEffects)
        ? memoryPlaneAblationEffects
        : Array.isArray(causalTraceAblationEffects)
          ? causalTraceAblationEffects
          : [];
    const selectedTool = causalTrace?.selected_tool
      || selectedTools[0]
      || (isRecord(routingScores[0]) ? String(routingScores[0].tool_name || '') : '')
      || [metadata.server_name, metadata.tool_name].filter(Boolean).join('.');
    const recipeDecision = String(
      recipePreflight?.decision
      || causalTrace?.recipe_preflight_decision
      || (causalTrace?.recipe_memory_used ? 'used' : ''),
    );
    const guardDecision = String(
      guardEvidence?.guard_id
      || guardEvidence?.decision
      || causalTrace?.guard_id
      || (causalTrace?.blocked ? 'blocked' : causalTrace?.guard_memory_used ? 'used' : ''),
    );
    const hasMeaningfulMemory = Boolean(
      memoryPlane
      || causalTrace
      || recipePreflight
      || guardEvidence
      || selectedTool
      || recipeDecision
      || guardDecision,
    );

    if (!hasMeaningfulMemory) {
      return null;
    }

    return {
      selectedTool,
      routerType: String(routing.router_type || causalTrace?.causal_ablation?.router_type || ''),
      recipeDecision,
      recipeReason: String(recipePreflight?.reason || causalTrace?.recipe_preflight_reason || ''),
      guardDecision,
      guardBlocked: Boolean(causalTrace?.blocked),
      recipeUsed: Boolean(causalTrace?.recipe_memory_used || recipeDecision),
      guardUsed: Boolean(causalTrace?.guard_memory_used || guardDecision),
      summaryUsed: causalTrace?.context_summary_used,
      attributionCount: attribution.length,
      topAttributionLabel: attribution[0]?.label ? String(attribution[0].label) : '',
      significantEffectCount: significantEffects.length,
    };
  };

  const renderMemoryCard = () => {
    const memoryMetadata = getMemoryCardMetadata();
    if (!memoryMetadata) {
      return null;
    }

    const recipeLabel = memoryMetadata.recipeDecision
      || (memoryMetadata.recipeUsed ? (language === 'zh' ? '\u5df2\u4f7f\u7528' : 'used') : (language === 'zh' ? '\u672a\u4f7f\u7528' : 'not used'));
    const guardLabel = memoryMetadata.guardBlocked
      ? (language === 'zh' ? '\u5df2\u62e6\u622a' : 'blocked')
      : memoryMetadata.guardDecision
        || (memoryMetadata.guardUsed ? (language === 'zh' ? '\u5df2\u4f7f\u7528' : 'used') : (language === 'zh' ? '\u672a\u89e6\u53d1' : 'not triggered'));
    const summaryLabel = memoryMetadata.summaryUsed === undefined
      ? (language === 'zh' ? '\u672a\u8bb0\u5f55' : 'not recorded')
      : memoryMetadata.summaryUsed
        ? (language === 'zh' ? '\u5df2\u4f7f\u7528' : 'used')
        : (language === 'zh' ? '\u672a\u4f7f\u7528' : 'not used');
    const statusClassName = memoryMetadata.guardBlocked
      ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200';

    return (
      <div className="mt-4 rounded-2xl border border-emerald-200/80 bg-emerald-50/65 p-3 text-emerald-950 dark:border-emerald-900/40 dark:bg-emerald-950/15 dark:text-emerald-100" data-testid="memory-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border ${statusClassName}`}>
              <Brain size={16} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">
                  {language === 'zh' ? '\u8bb0\u5fc6\u6cbb\u7406' : 'Memory'}
                </span>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClassName}`}>
                  {memoryMetadata.guardBlocked ? (language === 'zh' ? '\u98ce\u9669\u62e6\u622a' : 'Guard blocked') : (language === 'zh' ? '\u5df2\u53c2\u4e0e' : 'Applied')}
                </span>
              </div>
              {memoryMetadata.selectedTool && (
                <div className="mt-1 max-w-full truncate font-mono text-xs text-slate-500 dark:text-slate-400">
                  {language === 'zh' ? '\u8def\u7531' : 'Route'}: {memoryMetadata.selectedTool}
                </div>
              )}
              {memoryMetadata.topAttributionLabel && (
                <div className="mt-1 text-[12px] leading-5 text-slate-600 dark:text-slate-300">
                  {language === 'zh' ? '\u4e3b\u8981\u4f9d\u636e' : 'Main evidence'}: {memoryMetadata.topAttributionLabel}
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full border border-emerald-200 bg-white px-2 py-0.5 text-emerald-700 dark:border-emerald-900/50 dark:bg-slate-950/40 dark:text-emerald-200">
            {language === 'zh' ? '\u914d\u65b9' : 'Recipe'}: {recipeLabel}
          </span>
          <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
            {language === 'zh' ? '\u5b88\u536b' : 'Guard'}: {guardLabel}
          </span>
          <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
            {language === 'zh' ? '\u6458\u8981\u8bb0\u5fc6' : 'Summary'}: {summaryLabel}
          </span>
          {memoryMetadata.attributionCount > 0 && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
              {language === 'zh' ? '\u5f52\u56e0' : 'Attribution'}: {memoryMetadata.attributionCount}
            </span>
          )}
          {memoryMetadata.significantEffectCount > 0 && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
              {language === 'zh' ? '\u56e0\u679c\u6548\u5e94' : 'Effects'}: {memoryMetadata.significantEffectCount}
            </span>
          )}
          {memoryMetadata.routerType && showAdvancedDebugTraces && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
              {language === 'zh' ? '\u8def\u7531\u5668' : 'Router'}: {memoryMetadata.routerType}
            </span>
          )}
        </div>
        {memoryMetadata.recipeReason && showAdvancedDebugTraces && (
          <div className="mt-2 text-[11px] leading-5 text-slate-500 dark:text-slate-400">
            {memoryMetadata.recipeReason}
          </div>
        )}
      </div>
    );
  };

  const renderAgentEventCard = () => {
    const agentEvent = getAgentEventMetadata();
    if (!agentEvent) {
      return null;
    }

    const kind = String(agentEvent.kind || '');
    const status = String(agentEvent.status || '');
    const counts = agentEvent.counts && typeof agentEvent.counts === 'object'
      ? agentEvent.counts as Record<string, any>
      : {};
    const title = String(agentEvent.title || (language === 'zh' ? '\u6267\u884c\u4e8b\u4ef6' : 'Execution event'));
    const summary = String(agentEvent.summary || message.content || '');
    const stepTitle = String(agentEvent.step_title || '');
    const riskLevel = String(agentEvent.risk_level || '');
    const approvalAction = String(agentEvent.approval_action || '');
    const isCompleted = ['task_completed', 'approval_resolved'].includes(kind) && status !== 'rejected';
    const isWaiting = ['task_waiting_approval', 'approval_needed'].includes(kind);
    const isFailed = ['task_failed', 'task_cancelled'].includes(kind) || status === 'rejected';
    const isRunning = !isCompleted && !isWaiting && !isFailed;
    const toneClass = isCompleted
      ? 'border-emerald-200 bg-emerald-50/80 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200'
      : isWaiting
        ? 'border-amber-200 bg-amber-50/80 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200'
        : isFailed
          ? 'border-rose-200 bg-rose-50/80 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200'
          : 'border-sky-200 bg-sky-50/80 text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/20 dark:text-sky-200';
    const badgeText = isCompleted
      ? (language === 'zh' ? '\u5df2\u5b8c\u6210' : 'Completed')
      : isWaiting
        ? (language === 'zh' ? '\u5f85\u5ba1\u6279' : 'Waiting approval')
        : isFailed
          ? (language === 'zh' ? '\u5df2\u505c\u6b62' : 'Stopped')
          : (language === 'zh' ? '\u6267\u884c\u4e2d' : 'Running');
    const Icon = isCompleted ? CheckCircle : isWaiting ? ShieldAlert : isFailed ? ClipboardList : RefreshCw;

    return (
      <div className={`mt-4 rounded-2xl border p-3 ${toneClass}`} data-testid="agent-event-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border bg-white/70 dark:bg-slate-950/30 ${toneClass}`}>
              <Icon size={16} className={isRunning ? 'animate-spin' : ''} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">{title}</span>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass}`}>
                  {badgeText}
                </span>
              </div>
              <div className="mt-1 text-[13px] leading-6 text-slate-700 dark:text-slate-200">
                {summary}
              </div>
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          {stepTitle && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {language === 'zh' ? '\u6b65\u9aa4' : 'Step'}: {stepTitle}
            </span>
          )}
          {approvalAction && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {language === 'zh' ? '\u5ba1\u6279' : 'Approval'}: {approvalAction}
            </span>
          )}
          {riskLevel && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {language === 'zh' ? '\u98ce\u9669' : 'Risk'}: {riskLevel}
            </span>
          )}
          {(counts.completed_steps !== undefined || counts.total_steps !== undefined) && (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {language === 'zh' ? '\u8fdb\u5ea6' : 'Progress'}: {Number(counts.completed_steps || 0)}/{Number(counts.total_steps || 0)}
            </span>
          )}
        </div>
        {showAdvancedDebugTraces && (
          <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
            <div className="font-mono">{agentEvent.task_id}</div>
            {(counts.mcp !== undefined || counts.system_op !== undefined) && (
              <div className="mt-1">MCP {Number(counts.mcp || 0)} / SYS {Number(counts.system_op || 0)}</div>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderActionEventCard = () => {
    const actionEvent = getActionEventMetadata();
    if (!actionEvent) {
      return null;
    }

    const status = String(actionEvent.status || '');
    const stage = String(actionEvent.stage || '');
    const target = isRecord(actionEvent.target) ? actionEvent.target : {};
    const label = [target.server, target.tool].filter(Boolean).join('.') || String(actionEvent.summary || actionEvent.title || '');
    const isAgentAction = String(actionEvent.source_plane || '') === 'agent';
    const isSuccess = status === 'success' || stage === 'completed';
    const isBlocked = status === 'blocked';
    const isFailed = status === 'failed';
    const isRecovering = stage === 'recovering' || stage === 'recovered' || stage === 'recovery_failed';
    const statusText = isBlocked
      ? (language === 'zh' ? '\u5df2\u62e6\u622a' : 'Blocked')
      : isFailed
        ? (language === 'zh' ? '\u5931\u8d25' : 'Failed')
        : isSuccess
          ? (language === 'zh' ? '\u5df2\u9a8c\u8bc1' : 'Verified')
          : isRecovering
            ? (language === 'zh' ? '\u6b63\u5728\u6062\u590d' : 'Recovering')
            : (language === 'zh' ? '\u6267\u884c\u4e2d' : 'Running');
    const toneClass = isBlocked
      ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200'
      : isFailed
        ? 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200'
        : isSuccess
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200'
          : 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/20 dark:text-sky-200';

    return (
      <div className={`mt-3 rounded-2xl border px-3 py-2.5 ${toneClass}`} data-testid="action-event-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl border bg-white/75 dark:bg-slate-950/30 ${toneClass}`}>
              {isAgentAction ? <Bot size={15} /> : <Zap size={15} className={!isSuccess && !isBlocked && !isFailed ? 'animate-pulse' : ''} />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[13px] font-semibold text-slate-900 dark:text-white">
                  {isAgentAction ? (language === 'zh' ? 'Agent' : 'Agent') : (language === 'zh' ? '\u6267\u884c' : 'Action')}
                </span>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass}`}>
                  {statusText}
                </span>
              </div>
              <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                {label || String(actionEvent.title || '')}
              </div>
            </div>
          </div>
          <span className="rounded-full border border-slate-200 bg-white/85 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
            {isRecovering ? (language === 'zh' ? '\u6062\u590d' : 'recovery') : stage || (language === 'zh' ? '\u4e8b\u4ef6' : 'event')}
          </span>
        </div>
        {actionEvent.summary && (
          <div className="mt-2 text-[12px] leading-5 text-slate-700 dark:text-slate-200">
            {String(actionEvent.summary)}
          </div>
        )}
      </div>
    );
  };

  const renderResourceRefsCard = () => {
    const refs = getResourceRefs();
    if (refs.length === 0 || isUser) {
      return null;
    }
    const visibleRefs = refs.slice(0, 4);
    return (
      <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/80 p-3 dark:border-slate-700 dark:bg-slate-950/30" data-testid="resource-refs-card">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          <Paperclip size={14} />
          <span>{language === 'zh' ? '\u8d44\u6e90\u5f15\u7528' : 'Resources'}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {visibleRefs.map((ref) => {
            const kind = String(ref.kind || '');
            const isUrl = kind === 'url' || Boolean(ref.url);
            const isPath = kind === 'workspace_path' || Boolean(ref.path);
            const Icon = isUrl ? Link2 : isPath ? FolderOpen : FileText;
            const label = String(ref.label || ref.url || ref.path || ref.ref_id);
            return (
              <span
                key={ref.ref_id}
                className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                title={String(ref.path || ref.url || label)}
              >
                <Icon size={12} />
                <span className="max-w-[220px] truncate">{label}</span>
              </span>
            );
          })}
          {refs.length > visibleRefs.length && (
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
              +{refs.length - visibleRefs.length}
            </span>
          )}
        </div>
      </div>
    );
  };

  const renderToolResultCard = () => {
    const toolMetadata = getToolMetadata();
    if (!toolMetadata) {
      return null;
    }

    const runTrace = toolMetadata.run_trace as Record<string, any>;
    const result = toolMetadata.result;
    const serverName = String(runTrace.server_name || toolMetadata.server_name || '');
    const toolName = String(runTrace.tool_name || toolMetadata.tool_name || '');
    const toolLabel = [serverName, toolName].filter(Boolean).join('.') || (language === 'zh' ? '\u5de5\u5177\u8c03\u7528' : 'Tool call');
    const metadataArguments = toolMetadata.arguments;
    const argumentsObject = (metadataArguments && typeof metadataArguments === 'object')
      ? metadataArguments
      : (result && typeof result === 'object' && result.arguments && typeof result.arguments === 'object')
        ? result.arguments
        : null;
    const actualArguments = argumentsObject || {};
    const explicitResultPayload = result && typeof result === 'object' && 'result' in result ? result.result : undefined;
    const resultPayload =
      explicitResultPayload !== undefined
        ? explicitResultPayload
        : result && typeof result === 'object' && 'raw_result' in result
          ? result.raw_result
          : result;
    const errorText = result && typeof result === 'object'
      ? String(
        result.error
        || result.message
        || result.reason
        || '',
      )
      : '';
    const errorType = result && typeof result === 'object' && result.error_type
      ? String(result.error_type)
      : '';
    const success = result && typeof result === 'object' && 'success' in result
      ? Boolean(result.success)
      : Boolean(runTrace.success);
    const inferredArguments = Array.isArray(toolMetadata.inferred_arguments)
      ? (toolMetadata.inferred_arguments as string[])
      : [];
    const messageAttachments = Array.isArray(message.attachments) ? message.attachments : [];
    const resultUsesAttachmentPath = messageAttachments.some((attachment) => {
      const attachmentPath = String(attachment?.file_path || '').trim().toLowerCase();
      const argumentPath = String((actualArguments as Record<string, any>)?.path || '').trim().toLowerCase();
      return Boolean(attachmentPath) && Boolean(argumentPath) && attachmentPath === argumentPath;
    });
    const shouldHideAttachmentBodyResult = (
      resultUsesAttachmentPath
      && serverName === 'filesystem'
      && ['read_file', 'read_text_file', 'read_multiple_files'].includes(toolName)
    );

    const sections = [
      {
        key: 'arguments',
        title: language === 'zh' ? '\u53c2\u6570' : 'Arguments',
        content: Object.keys(actualArguments).length > 0 ? formatToolSectionContent(actualArguments) : (language === 'zh' ? '\u65e0\u53c2\u6570' : 'No arguments'),
      },
      {
        key: 'result',
        title: language === 'zh' ? '\u7ed3\u679c' : 'Result',
        content: shouldHideAttachmentBodyResult
          ? getAttachmentBodyHiddenNotice(language, 'bubble')
          : resultPayload !== undefined
            ? formatToolSectionContent(resultPayload)
            : message.content,
      },
    ];

    if (!success || errorText || errorType) {
      sections.push({
        key: 'error',
        title: language === 'zh' ? '\u9519\u8bef\u539f\u56e0' : 'Error',
        content: formatToolSectionContent({
          error_type: errorType || undefined,
          error: errorText || undefined,
        }),
      });
    }

    let previewText = '';
    if (!success && (errorText || errorType)) {
      previewText = errorText || errorType;
    } else if (shouldHideAttachmentBodyResult) {
      previewText = language === 'zh' ? '\u5df2\u8bfb\u53d6\u9644\u4ef6\uff0c\u6b63\u6587\u5185\u5bb9\u9ed8\u8ba4\u9690\u85cf\u3002' : 'Attachment was read; body text is hidden by default.';
    } else {
      const rendered = resultPayload !== undefined
        ? formatToolSectionContent(resultPayload)
        : String(message.content || '');
      const compact = rendered.replace(/\s+/g, ' ').trim();
      previewText = compact || (language === 'zh' ? '\u6682\u65e0\u7ed3\u679c\u9884\u89c8' : 'No result preview');
      if (previewText.length > 110) {
        previewText = `${previewText.slice(0, 110)}...`;
      }
    }

    const statusLabel = success
      ? (language === 'zh' ? '\u5b8c\u6210' : 'Done')
      : (language === 'zh' ? '\u5931\u8d25' : 'Failed');
    const statusClassName = success
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200'
      : 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-200';
    const containerClassName = success
      ? 'border-slate-200/80 bg-white/70 dark:border-slate-700/70 dark:bg-slate-950/30'
      : 'border-rose-200/80 bg-rose-50/70 dark:border-rose-900/40 dark:bg-rose-950/20';
    const flowText = success
      ? (language === 'zh' ? '\u5df2\u5b8c\u6210\u771f\u5b9e\u5de5\u5177\u8c03\u7528\uff0c\u6a21\u578b\u5df2\u7ee7\u7eed\u57fa\u4e8e\u7ed3\u679c\u56de\u7b54\u3002' : 'The model completed a real tool call and used the result for the answer.')
      : (language === 'zh' ? '\u771f\u5b9e\u5de5\u5177\u8c03\u7528\u5931\u8d25\uff0c\u53ef\u5728\u8be6\u60c5\u4e2d\u67e5\u770b\u9519\u8bef\u539f\u56e0\u3002' : 'This real tool call failed. The error reason is available in details.');

    return (
      <div className={`mt-4 rounded-2xl border p-3 ${containerClassName}`} data-testid="tool-result-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border ${statusClassName}`}>
              <Wrench size={16} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-900 dark:text-white">
                  {language === 'zh' ? '\u5de5\u5177\u8c03\u7528' : 'Tool call'}
                </span>
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClassName}`}>
                  {statusLabel}
                </span>
                {runTrace.latency_ms !== undefined && (
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                    {Number(runTrace.latency_ms).toFixed(0)} ms
                  </span>
                )}
              </div>
              <div className="mt-1 max-w-full truncate font-mono text-xs text-slate-500 dark:text-slate-400">
                {toolLabel}
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setToolCardExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            data-testid="toggle-tool-result-card"
          >
            {toolCardExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span>{toolCardExpanded ? (language === 'zh' ? '\u9690\u85cf' : 'Hide') : (language === 'zh' ? '\u8be6\u60c5' : 'Details')}</span>
          </button>
        </div>

        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/50">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            {language === 'zh' ? '\u7ed3\u679c\u6458\u8981' : 'Result summary'}
          </div>
          <div className="mt-1 text-[13px] leading-6 text-slate-700 dark:text-slate-200">
            {previewText}
          </div>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          <span>{flowText}</span>
          {inferredArguments.length > 0 && toolCardExpanded && (
            <span className="rounded-full bg-sky-50 px-2 py-0.5 text-sky-700 dark:bg-sky-900/20 dark:text-sky-200">
              {language === 'zh' ? `\u5df2\u81ea\u52a8\u586b\u5145 ${inferredArguments.length} \u4e2a\u5b57\u6bb5` : `${inferredArguments.length} fields auto-filled`}
            </span>
          )}
        </div>

        {toolCardExpanded && (
          <div className="mt-3 space-y-3">
            {sections.map((section) => (
              <div
                key={section.key}
                data-testid={`tool-section-${section.key}`}
                className="rounded-xl border border-slate-200 bg-white/90 dark:border-slate-700 dark:bg-slate-900/70"
              >
                <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                    {section.title}
                  </div>
                  <button
                    type="button"
                    data-testid={`copy-tool-section-${section.key}`}
                    onClick={() => { void copyText(section.content, section.key); }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    {copiedToolSection === section.key ? <CheckCircle size={12} /> : <Copy size={12} />}
                    <span>{copiedToolSection === section.key ? (language === 'zh' ? '\u5df2\u590d\u5236' : 'Copied') : (language === 'zh' ? '\u590d\u5236' : 'Copy')}</span>
                  </button>
                </div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-3 py-3 text-[12px] leading-6 text-slate-700 dark:text-slate-200">
                  {section.content}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderContent = () => {
    if (isUser) {
      const fileAttachments = attachments.filter((attachment) => !attachment.is_image);

      return (
        <div>
          <div className="whitespace-pre-wrap font-medium text-white">{message.content}</div>
          {bubbleImages.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-3">
              {bubbleImages.map((image, index) => (
                <a
                  key={`${image.src}-${index}`}
                  href={image.src}
                  target="_blank"
                  rel="noreferrer"
                  className="block overflow-hidden rounded-2xl border border-white/20 shadow-lg"
                >
                  <img
                    src={image.src}
                    alt={image.alt}
                    className="image-preview max-h-80 max-w-sm object-cover"
                  />
                </a>
              ))}
            </div>
          )}
          {fileAttachments.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              {fileAttachments.map((attachment) => (
                <a
                  key={`${attachment.filename}-${attachment.original_filename}`}
                  href={resolveAttachmentUrl(attachment)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-3 rounded-2xl border border-white/20 bg-white/10 px-3 py-2 text-white transition hover:bg-white/15"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15">
                    <FileText size={18} className="text-white" />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{attachment.original_filename || attachment.filename}</div>
                    <div className="text-xs text-white/75">
                      {t('message.fileAttachment')}
                      {typeof attachment.size === 'number' ? ' - ' + Math.max(attachment.size / 1024, 0.1).toFixed(1) + ' KB' : ''}
                    </div>
                  </div>
                </a>
              ))}
            </div>
          )}
        </div>
      );
    }

    if (isSystem && getToolMetadata()) {
      return null;
    }

    if (isSystem && getAgentEventMetadata()) {
      return null;
    }

    if (isSystem && getActionEventMetadata()) {
      return null;
    }

    return (
      <div className={contentClassName}>
        {bubbleImages.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-3">
            {bubbleImages.map((image, index) => (
              <a
                key={`${image.src}-${index}`}
                href={image.src}
                target="_blank"
                rel="noreferrer"
                className="block overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/80 shadow-sm transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/70 dark:hover:border-slate-600"
              >
                <img
                  src={image.src}
                  alt={image.alt}
                  className="image-preview max-h-96 max-w-full min-w-[180px] object-cover"
                />
              </a>
            ))}
          </div>
        )}
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ inline, className, children, ...props }: any) {
              const match = /language-(\w+)/.exec(className || '');
              return !inline && match ? (
                <pre className="mb-3 overflow-x-auto rounded-2xl bg-slate-950 px-4 py-3 text-sm text-slate-100 shadow-inner">
                  <code>{String(children).replace(/\n$/, '')}</code>
                </pre>
              ) : (
                <code className={inlineCodeClassName} {...props}>
                  {children}
                </code>
              );
            },
            p({ children }: any) {
              return <p className="mb-3 last:mb-0">{children}</p>;
            },
            a({ children, href }: any) {
              return (
                <a href={href} className={linkClassName} target="_blank" rel="noreferrer">
                  {children}
                </a>
              );
            },
            strong({ children }: any) {
              return <strong className={strongClassName}>{children}</strong>;
            },
            ul({ children }: any) {
              return <ul className="mb-3 list-inside list-disc space-y-1.5">{children}</ul>;
            },
            ol({ children }: any) {
              return <ol className="mb-3 list-inside list-decimal space-y-1.5">{children}</ol>;
            },
            blockquote({ children }: any) {
              return <blockquote className={blockquoteClassName}>{children}</blockquote>;
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>
    );
  };

  const renderAvatar = () => {
    if (isUser) {
      return (
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl border border-sky-300/50 bg-gradient-to-br from-sky-500 to-cyan-600 shadow-sm">
          <User size={20} className="text-white" />
        </div>
      );
    }

    if (isAssistant) {
      return (
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl border border-emerald-300/40 bg-gradient-to-br from-emerald-500 to-teal-600 shadow-sm">
          <Bot size={20} className="text-white" />
        </div>
      );
    }

    if (isSystem) {
      return (
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl border border-amber-300/50 bg-gradient-to-br from-amber-400 to-amber-500 shadow-sm">
          <Zap size={20} className="text-white" />
        </div>
      );
    }

    return (
      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-2xl border border-rose-300/50 bg-gradient-to-br from-rose-500 to-red-600 shadow-sm">
        <span className="text-sm text-white">!</span>
      </div>
    );
  };

  const senderLabel = isUser
    ? t('message.you')
    : isAssistant
      ? (message.metadata?.model_name ? t('message.assistantWithModel', { model: message.metadata.model_name }) : t('message.assistant'))
      : isSystem
        ? t('message.system')
        : t('message.error');

  const senderLabelClassName = isUser
    ? 'text-sky-600 dark:text-sky-300'
    : isAssistant
      ? 'text-emerald-600 dark:text-emerald-300'
      : isSystem
        ? 'text-amber-700 dark:text-amber-50'
        : 'text-rose-600 dark:text-rose-300';

  const bubbleClassName = isUser
    ? 'rounded-[26px] border border-sky-400/30 bg-gradient-to-br from-sky-500 to-cyan-600 px-5 py-4 text-white shadow-[0_10px_30px_rgba(14,165,233,0.22)]'
    : isAssistant
      ? 'rounded-[26px] border border-slate-200/80 bg-white/95 px-5 py-4 text-slate-900 shadow-sm dark:border-slate-700/75 dark:bg-slate-900/90 dark:text-slate-50'
      : isSystem
        ? 'rounded-[24px] border border-amber-200/80 bg-amber-50/95 px-5 py-4 text-amber-950 shadow-sm dark:border-amber-300/30 dark:bg-slate-900 dark:text-amber-50'
        : 'rounded-[24px] border border-rose-200/80 bg-rose-50/95 px-5 py-4 text-rose-950 shadow-sm dark:border-rose-800/50 dark:bg-rose-950/20 dark:text-rose-100';

  const renderMetaBadges = () => {
    if (!message.metadata) {
      return null;
    }

    const hasModelBadge = isAssistant && Boolean(message.metadata.model_used || message.metadata.model_name);
    const hasAttachmentBadge = Array.isArray(message.attachments) && message.attachments.length > 0;
    const showToolCountBadge = Boolean(showAdvancedDebugTraces && message.metadata.tools_used && message.metadata.tools_used.length > 0);
    const showExecutionTimeBadge = Boolean(showAdvancedDebugTraces && message.metadata.execution_time);

    if (!hasModelBadge && !hasAttachmentBadge && !showToolCountBadge && !showExecutionTimeBadge) {
      return null;
    }

    return (
      <div className={`mt-2 flex flex-wrap items-center gap-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
        {hasModelBadge && (
          <div className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700 dark:border-blue-900/40 dark:bg-blue-900/20 dark:text-blue-300">
            {String(message.metadata?.model_used || '').toLowerCase().includes('vl') ? (
              <Eye size={14} className="text-cyan-500" />
            ) : (
              <Brain size={14} className="text-blue-500" />
            )}
            <span>{message.metadata?.model_name || message.metadata?.model_used}</span>
          </div>
        )}

        {hasAttachmentBadge && (
          <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
            <Paperclip size={14} className="text-slate-500" />
            <span>{t('message.attachmentsUsed', { count: message.attachments!.length })}</span>
          </div>
        )}

        {showToolCountBadge && (
          <div className="inline-flex items-center gap-1.5 rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-medium text-violet-700 dark:border-violet-900/40 dark:bg-violet-900/20 dark:text-violet-300">
            <Zap size={14} className="text-violet-500" />
            <span>{t('message.toolsUsed', { count: message.metadata!.tools_used!.length })}</span>
          </div>
        )}

        {showExecutionTimeBadge && (
          <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
            <Zap size={14} className="text-amber-500" />
            <span>{Number(message.metadata!.execution_time).toFixed(2)}s</span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={`mb-8 flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex w-full max-w-[1320px] gap-4 ${isUser ? 'flex-row-reverse' : 'flex-row'} items-start`}>
        <div className="mt-1 hidden sm:block">
          {renderAvatar()}
        </div>

        <div className={`min-w-0 flex-1 ${isUser ? 'pl-4 md:pl-10' : 'pr-4 md:pr-10'}`}>
          <div className={`mb-2 flex items-center gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div className={`text-sm font-semibold ${senderLabelClassName}`}>{senderLabel}</div>
            <div className={`inline-flex items-center gap-1 text-xs ${timestampClassName}`}>
              <Clock size={13} />
              <span>{formatTimestamp(message.timestamp)}</span>
            </div>
          </div>

          <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div className={`min-w-0 ${isUser ? 'w-full max-w-[820px]' : 'w-full max-w-[1040px]'}`}>
              <div className={bubbleClassName}>
                <div className={`mb-3 flex ${isUser ? 'justify-start' : 'justify-end'}`}>
                  <button
                    type="button"
                    onClick={() => { void copyMessageContent(); }}
                    className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1 text-[11px] font-medium transition ${
                      isUser
                        ? 'border-white/25 bg-white/10 text-white hover:bg-white/15'
                        : 'border-slate-200 bg-white/80 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300'
                    }`}
                    title={language === 'zh' ? '\u590d\u5236\u6d88\u606f' : 'Copy message'}
                  >
                    {copied ? <CheckCircle size={13} /> : <Copy size={13} />}
                    <span>{copied ? (language === 'zh' ? '\u5df2\u590d\u5236' : 'Copied') : (language === 'zh' ? '\u590d\u5236' : 'Copy')}</span>
                  </button>
                </div>
                {renderContent()}
                {renderMemoryCard()}
                {renderToolResultCard()}
                {renderAgentEventCard()}
                {renderActionEventCard()}
                {renderResourceRefsCard()}
              </div>

              <MessageDeliveryBadge
                status={message.delivery_status}
                error={message.delivery_error}
                retryable={message.retryable}
                onRetry={onRetry}
              />
              {renderMetaBadges()}
              <AdvancedDebugTracePanel
                message={message}
                visible={showAdvancedDebugTraces}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;


