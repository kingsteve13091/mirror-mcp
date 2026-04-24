import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AtSign,
  BookOpen,
  Bot,
  Brain,
  ChevronDown,
  ClipboardList,
  Globe,
  History,
  Image,
  Moon,
  Paperclip,
  Plus,
  Send,
  Settings,
  Sun,
  Trash2,
  Zap,
} from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useSystemBootstrap } from '../hooks/useSystemBootstrap';
import {
  AgentSkillSummary,
  AgentSkillExternalConfig,
  AgentCapabilitiesResponse,
  AgentTask,
  AgentTaskReplayEvent,
  AvailableTool,
  ChatAttachment,
  ChatMessage,
  ChatSettings,
  MCPServerConfigForm,
  MCPServerConfigItem,
  MCPToolOnboardingAuditReport,
  MCPToolOnboardingSelfTestRunReport,
  ProviderConnectivityResult,
  AutoToolRoutingState,
  RuntimeProviderConfig,
  RuntimeProviderState,
  RuntimeRequestJournalEntry,
  RuntimeView,
  SystemOperationApproval,
  ToolPolicyState,
  MCPTool,
  ResourceReference,
  WorkspaceAgentProfile,
} from '../types';
import MessageBubble from './MessageBubble';
import ConnectionIndicator from './ConnectionIndicator';
import SettingsPanel from './SettingsPanel';
import TypingIndicator from './TypingIndicator';
import ChatHistory from './ChatHistory';
import MCPToolsPanel from './MCPToolsPanel';
import ModelSelector from './ModelSelector';
import ToolSelector from './ToolSelector';
import ToolConfirmModal from './ToolConfirmModal';
import TEMPanel from './TEMPanel';
import HealthPanel from './HealthPanel';
import SystemOperationApprovalModal from './system-operation-approval-modal';
import TaskCenter from './task-center';
import NoticeBanner from './common/NoticeBanner';
import AgentRuntimeBar from './AgentRuntimeBar';
import { I18nProvider, translateForLanguage } from '../i18n/I18nProvider';
import { buildApiUrl } from '../config/backend';
import {
  checkRuntimeProviderConnectivity,
  approveAgentOperation,
  clearRuntimeProviders,
  cancelAgentTask,
  createAgentTask,
  deleteMcpConfig,
  getAgentCapabilities,
  getAgentOperationApprovals,
  getAgentTaskReplay,
  getAgentSkills,
  getAgentSkillsExternalConfig,
  getAgentTasks,
  getMcpConfig,
  getMcpToolOnboardingAudit,
  getRuntimeAutoToolRouting,
  getRuntimeProviders,
  getRuntimeRequests,
  reloadAgentSkills,
  reloadRuntimeParams,
  runMcpToolOnboardingSelfTests,
  saveMcpConfig,
  setTemMode,
  getRuntimeToolPolicy,
  uploadFile,
  updateRuntimeAutoToolRouting,
  updateAgentSkillsExternalConfig,
  updateRuntimeToolPolicy,
  updateRuntimeProviders,
  previewWorkspaceContext,
  rejectAgentOperation,
} from '../services/api';
import {
  clearCurrentSession as clearPersistedCurrentSession,
  createSessionSnapshot,
  getStoredClientId,
  loadSavedSessions,
  loadCurrentSession,
  persistClientId,
  saveCurrentSession as persistCurrentSession,
  saveSessions as persistSessions,
} from '../utils/chatSessionStorage';
import {
  loadChatSettings,
  loadRuntimeProviderConfig,
  loadSelectedModel,
  resetChatSettings,
  resetRuntimeProviderConfig,
  saveChatSettings,
  saveRuntimeProviderConfig,
  saveSelectedModel,
} from '../utils/settingsStorage';
import {
  attachmentHasHiddenBodyText,
  getAttachmentBodyHiddenNotice,
  getAttachmentNoBodyContextNotice,
} from '../utils/attachmentTransparency';
import {
  buildAttachmentExecutionPlan,
  getAttachmentTransportRoleLabel,
} from '../utils/attachmentPlan';
import {
  getJsonSchemaProperties,
  getJsonSchemaRequired,
  pruneEmptyOptionalArgs,
  resolveJsonSchemaType,
} from '../utils/jsonSchema';

const MCP_STATUS_POLL_INTERVAL_MS = 30000;
const TOOL_SELECTOR_OFFSET_X = 20;
const TOOL_CALL_PATTERN = /@([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)/g;
const AT_PATH_PATTERN = /@((?:\.{1,2}[\\/]|[A-Za-z]:\\|\/)[^\s"'`<>]+|(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16})/g;
const WORKSPACE_COMMAND_PATTERN = /^\/([A-Za-z0-9_.-]+)\b/;
const BYTES_PER_KILOBYTE = 1024;
const BYTES_PER_MEGABYTE = BYTES_PER_KILOBYTE * 1024;
const DEFAULT_MCP_SERVER_TIMEOUT = 60;
const AGENT_STATUS_POLL_INTERVAL_MS = 6000;
const IMAGE_MIME_PREFIX = 'image/';
const IMAGE_EXTENSIONS = new Set(['.bmp', '.gif', '.jpeg', '.jpg', '.png', '.webp']);
const DOCUMENT_EXTENSIONS = new Set(['.doc', '.docx', '.odt', '.odp', '.ods', '.pdf', '.ppt', '.pptx', '.xls', '.xlsx']);
const TEXT_EXTENSIONS = new Set([
  '.csv',
  '.json',
  '.jsonl',
  '.log',
  '.md',
  '.py',
  '.rst',
  '.text',
  '.toml',
  '.ts',
  '.tsx',
  '.txt',
  '.xml',
  '.yaml',
  '.yml',
]);

interface PendingAttachment {
  id: string;
  file: File;
  previewUrl: string | null;
  uploadedAttachment?: ChatAttachment | null;
  uploadState?: 'pending' | 'uploading' | 'ready' | 'failed';
  uploadError?: string | null;
}

const createClientId = () => `client-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;

const buildSystemMessage = (content: string): ChatMessage => ({
  id: `system-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
  type: 'system',
  content,
  timestamp: new Date().toISOString(),
});

const summarizeAgentTaskEvent = (
  task: AgentTask,
  language: 'zh' | 'en',
  approvals: SystemOperationApproval[] = [],
) => {
  const steps = Array.isArray(task.steps) ? task.steps : [];
  const currentStep = steps.find((step) => ['running', 'waiting_approval'].includes(String(step.status || '')))
    || steps[Math.max(0, Math.min((task.current_step_index || 1) - 1, steps.length - 1))]
    || null;
  const completedSteps = steps.filter((step) => ['completed', 'skipped'].includes(String(step.status || ''))).length;
  const totalSteps = steps.length;
  const pendingApproval = approvals.find((approval) => approval.task_id === task.task_id)
    || (task.pending_approvals || []).find((approval) => approval.status === 'pending')
    || null;
  const status = String(task.status || '');

  if (status === 'waiting_approval' && pendingApproval) {
    return {
      kind: 'approval_needed' as const,
      title: language === 'zh' ? 'Agent \u7b49\u5f85\u5ba1\u6279' : 'Agent waiting approval',
      summary: language === 'zh'
        ? `\u9700\u8981\u5ba1\u6279\u540e\u624d\u80fd\u7ee7\u7eed\u6267\u884c ${pendingApproval.action_type}\u3002`
        : `This task needs approval before continuing ${pendingApproval.action_type}.`,
      stepTitle: currentStep?.title || '',
      approvalAction: pendingApproval.action_type,
      riskLevel: pendingApproval.risk_level || pendingApproval.decision?.risk_level || '',
      approvalId: pendingApproval.approval_id,
      counts: {
        completed_steps: completedSteps,
        total_steps: totalSteps,
        mcp: Number(task.source_plane_counts?.mcp || 0),
        system_op: Number(task.source_plane_counts?.system_op || 0),
      },
    };
  }

  if (status === 'completed') {
    return {
      kind: 'task_completed' as const,
      title: language === 'zh' ? 'Agent \u4efb\u52a1\u5df2\u5b8c\u6210' : 'Agent task completed',
      summary: language === 'zh'
        ? 'Agent \u5df2\u5b8c\u6210\u8ba1\u5212\u6b65\u9aa4\uff0c\u5e76\u6574\u7406\u4e86\u6267\u884c\u7ed3\u679c\u3002'
        : 'The agent completed its planned steps and collected the execution result.',
      stepTitle: currentStep?.title || '',
      counts: {
        completed_steps: completedSteps || totalSteps,
        total_steps: totalSteps,
        mcp: Number(task.source_plane_counts?.mcp || 0),
        system_op: Number(task.source_plane_counts?.system_op || 0),
      },
    };
  }

  if (status === 'failed') {
    return {
      kind: 'task_failed' as const,
      title: language === 'zh' ? 'Agent \u4efb\u52a1\u5931\u8d25' : 'Agent task failed',
      summary: String(task.result_summary?.error || (language === 'zh' ? '\u4efb\u52a1\u6267\u884c\u5931\u8d25\u3002' : 'The task failed.')),
      stepTitle: currentStep?.title || '',
      counts: {
        completed_steps: completedSteps,
        total_steps: totalSteps,
        mcp: Number(task.source_plane_counts?.mcp || 0),
        system_op: Number(task.source_plane_counts?.system_op || 0),
      },
    };
  }

  if (status === 'cancelled') {
    return {
      kind: 'task_cancelled' as const,
      title: language === 'zh' ? 'Agent \u4efb\u52a1\u5df2\u53d6\u6d88' : 'Agent task canceled',
      summary: language === 'zh' ? '\u4efb\u52a1\u5df2\u88ab\u53d6\u6d88\u3002' : 'The task was canceled.',
      stepTitle: currentStep?.title || '',
      counts: {
        completed_steps: completedSteps,
        total_steps: totalSteps,
        mcp: Number(task.source_plane_counts?.mcp || 0),
        system_op: Number(task.source_plane_counts?.system_op || 0),
      },
    };
  }

  return {
    kind: 'task_running' as const,
    title: language === 'zh' ? 'Agent \u6b63\u5728\u6267\u884c' : 'Agent running',
    summary: currentStep?.title
      ? (language === 'zh' ? `\u5f53\u524d\u6b63\u5728\u6267\u884c\uff1a${currentStep.title}` : `Currently executing: ${currentStep.title}`)
      : (language === 'zh' ? '\u4efb\u52a1\u6b63\u5728\u8fd0\u884c\u4e2d\u3002' : 'The task is currently running.'),
    stepTitle: currentStep?.title || '',
    counts: {
      completed_steps: completedSteps,
      total_steps: totalSteps,
      mcp: Number(task.source_plane_counts?.mcp || 0),
      system_op: Number(task.source_plane_counts?.system_op || 0),
    },
  };
};

const formatFileSize = (bytes: number) => {
  if (bytes >= BYTES_PER_MEGABYTE) {
    return `${(bytes / BYTES_PER_MEGABYTE).toFixed(1)} MB`;
  }

  return `${Math.max(bytes / BYTES_PER_KILOBYTE, 0.1).toFixed(1)} KB`;
};

const isImageFile = (file: File | null | undefined) => Boolean(file && file.type.startsWith(IMAGE_MIME_PREFIX));

const getFileExtension = (filename: string) => {
  const normalized = filename.toLowerCase();
  const dotIndex = normalized.lastIndexOf('.');
  return dotIndex >= 0 ? normalized.slice(dotIndex) : '';
};

const isDocumentLikeFile = (file: File) => {
  const extension = getFileExtension(file.name);
  return DOCUMENT_EXTENSIONS.has(extension) || TEXT_EXTENSIONS.has(extension) || file.type.startsWith('text/');
};

const getAttachmentUnderstandingLabel = (
  attachment: ChatAttachment | null | undefined,
  uploadState: PendingAttachment['uploadState'],
  language: 'zh' | 'en',
) => {
  if (uploadState === 'uploading') {
    return language === 'zh' ? '\u6b63\u5728\u4e0a\u4f20\u5e76\u89e3\u6790' : 'Uploading and parsing';
  }
  if (uploadState === 'failed') {
    return language === 'zh' ? '\u4e0a\u4f20\u5931\u8d25' : 'Upload failed';
  }
  const status = attachment?.parse_status || 'pending';
  if (attachment?.is_image) {
    return language === 'zh'
      ? '\u56fe\u7247\u5df2\u4e0a\u4f20\uff0c\u5f53\u524d\u5982\u679c\u4f7f\u7528\u591a\u6a21\u6001\u6a21\u578b\uff0c\u5c06\u4f5c\u4e3a\u89c6\u89c9\u8f93\u5165\u53d1\u9001'
      : 'Image uploaded. It will be sent as visual input when the current model is multimodal';
  }
  if (status === 'parsed') {
    if (attachment?.preview_truncated) {
      return language === 'zh' ? '\u5df2\u89e3\u6790\uff0c\u6a21\u578b\u53ea\u4f1a\u770b\u5230\u88ab\u622a\u65ad\u7684\u53ef\u89c1\u6587\u672c' : 'Parsed; model will see truncated visible text';
    }
    return language === 'zh' ? '\u5df2\u5168\u6587\u89e3\u6790\uff0c\u6a21\u578b\u4f1a\u770b\u5230\u6587\u672c\u5185\u5bb9' : 'Fully parsed; model will see text content';
  }
  if (status === 'parser_missing') {
    return language === 'zh' ? '\u7f3a\u5c11\u89e3\u6790\u5668\uff0c\u6a21\u578b\u53ea\u80fd\u770b\u5230\u5143\u6570\u636e' : 'Parser missing; model sees metadata only';
  }
  if (status === 'metadata_only') {
    return language === 'zh' ? '\u53ea\u6709\u5143\u6570\u636e\uff0c\u6a21\u578b\u770b\u4e0d\u5230\u6b63\u6587' : 'Metadata only; model cannot see body text';
  }
  if (status === 'empty') {
    return language === 'zh' ? '\u5df2\u89e3\u6790\u4f46\u6ca1\u6709\u53ef\u63d0\u53d6\u6587\u672c' : 'Parsed but no extractable text';
  }
  if (status === 'unreadable' || status === 'unavailable') {
    return language === 'zh' ? '\u4e0d\u53ef\u8bfb\u53d6\uff0c\u6a21\u578b\u53ea\u80fd\u770b\u5230\u5143\u6570\u636e' : 'Unreadable; model sees metadata only';
  }
  return language === 'zh' ? '\u7b49\u5f85\u89e3\u6790' : 'Waiting for parsing';
};

const attachmentBadgeClassName = (attachment: ChatAttachment | null | undefined, uploadState: PendingAttachment['uploadState']) => {
  if (uploadState === 'failed') {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/20 dark:text-rose-200';
  }
  if (uploadState === 'uploading' || !attachment) {
    return 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/50 dark:bg-sky-950/20 dark:text-sky-200';
  }
  if (attachment.is_image || attachment.parse_status === 'parsed') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200';
  }
  if (attachment.parse_status === 'parser_missing' || attachment.parse_status === 'metadata_only') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200';
  }
  return 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200';
};

const createPendingAttachment = (file: File): PendingAttachment => ({
  id: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  file,
  previewUrl: isImageFile(file) ? URL.createObjectURL(file) : null,
  uploadedAttachment: null,
  uploadState: 'pending',
  uploadError: null,
});

const toChatAttachment = (upload: Awaited<ReturnType<typeof uploadFile>>): ChatAttachment => {
  const filename = upload.filename;
  const resolvedPath = upload.file_path || upload.path || filename;
  return {
    filename,
    original_filename: upload.original_filename || filename,
    file_path: resolvedPath,
    url: buildApiUrl(`/api/uploads/${filename}`),
    size: upload.size,
    mime_type: upload.mime_type || upload.content_type,
    is_image: Boolean((upload.mime_type || upload.content_type || '').startsWith(IMAGE_MIME_PREFIX)),
    parse_status: upload.parse_status,
    parse_mode: upload.parse_mode,
    parser: upload.parser,
    preview_text: upload.preview_text,
    full_text_chars: upload.full_text_chars,
    visible_text_chars: upload.visible_text_chars,
    preview_truncated: upload.preview_truncated,
    parse_error: upload.parse_error,
    transport_role: 'metadata_only',
    transport_reason: '',
    model_visible_on_current_turn: false,
    tool_usable_on_current_turn: Boolean(resolvedPath),
  };
};

const parsePolicyRulesText = (raw: string): Record<string, 'allow' | 'confirm' | 'deny'> => raw
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)
  .reduce<Record<string, 'allow' | 'confirm' | 'deny'>>((acc, line) => {
    const [key, value] = line.split('=').map((part) => part.trim());
    if (!key) {
      return acc;
    }
    const action = (value || 'allow').toLowerCase();
    if (action === 'allow' || action === 'confirm' || action === 'deny') {
      acc[key] = action;
    }
    return acc;
  }, {});

const buildWorkspaceContextPayload = (settings: ChatSettings) => {
  const workspaceEnabled = settings.enableWorkspaceContext && settings.workspaceContextRoot.trim();
  const sessionAllowMCPs = settings.sessionAllowMCPs || [];
  if (!workspaceEnabled && sessionAllowMCPs.length === 0) {
    return undefined;
  }
  return {
    workspace_root: workspaceEnabled ? settings.workspaceContextRoot.trim() : '',
    agent_name: workspaceEnabled ? settings.workspaceContextAgentName.trim() : '',
    include_agent_profile: workspaceEnabled ? settings.workspaceContextIncludeAgentProfile : false,
    include_memory_file: workspaceEnabled ? settings.workspaceContextIncludeMemoryFile : false,
    include_chatlogs: workspaceEnabled ? settings.workspaceContextIncludeChatlogs : false,
    session_allow_mcps: sessionAllowMCPs,
  };
};

const workspaceContextDependencyKey = (settings: ChatSettings) => JSON.stringify({
  enableWorkspaceContext: settings.enableWorkspaceContext,
  workspaceContextRoot: settings.workspaceContextRoot,
  workspaceContextAgentName: settings.workspaceContextAgentName,
  workspaceContextIncludeAgentProfile: settings.workspaceContextIncludeAgentProfile,
  workspaceContextIncludeMemoryFile: settings.workspaceContextIncludeMemoryFile,
  workspaceContextIncludeChatlogs: settings.workspaceContextIncludeChatlogs,
  sessionAllowMCPs: settings.sessionAllowMCPs || [],
});

const filterAvailableToolsByAgentProfile = (
  tools: AvailableTool[],
  profile: WorkspaceAgentProfile | null,
  settings?: ChatSettings,
) => {
  const sessionAllowMCPs = new Set((settings?.sessionAllowMCPs || []).map((item) => String(item).trim().toLowerCase()).filter(Boolean));
  if (!profile && sessionAllowMCPs.size === 0) {
    return tools;
  }
  const allowedServers = new Set((profile?.allowMCPs || []).map((item) => String(item).trim().toLowerCase()).filter(Boolean));
  sessionAllowMCPs.forEach((server) => allowedServers.add(server));
  return tools.filter((tool) => {
    const serverName = String(tool.server || '').trim().toLowerCase();
    if (allowedServers.size > 0 && !allowedServers.has(serverName)) {
      return false;
    }
    return true;
  });
};

const createEmptyMcpServerForm = (): MCPServerConfigForm => ({
  name: '',
  description: '',
  mode: 'stdio',
  disabled: false,
  command: '',
  argsText: '',
  envText: '',
  url: '',
  transport: 'sse',
  timeout: DEFAULT_MCP_SERVER_TIMEOUT,
});

const mapConfigItemToForm = (item: MCPServerConfigItem): MCPServerConfigForm => ({
  name: item.name,
  description: item.config.description || '',
  mode: item.mode === 'remote' ? 'remote' : 'stdio',
  disabled: Boolean(item.config.disabled),
  command: item.config.command || '',
  argsText: (item.config.args || []).join('\n'),
  envText: Object.entries(item.config.env || {})
    .map(([key, value]) => `${key}=${value}`)
    .join('\n'),
  url: item.config.url || '',
  transport: item.config.transport || 'sse',
  timeout: item.config.timeout || DEFAULT_MCP_SERVER_TIMEOUT,
});

const createTrackedRequestId = () => `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

const detectWorkspaceAgentCommand = (content: string) => {
  const match = String(content || '').trim().match(WORKSPACE_COMMAND_PATTERN);
  return match?.[1] ? match[1] : '';
};

type DetectedToolCall = {
  serverName: string;
  toolName: string;
  fullMatch: string;
};

const getToolSchema = (tool?: MCPTool | null) => tool?.input_schema || {};

const PATH_ARGUMENT_NAMES = new Set([
  'path',
  'file',
  'file_path',
  'filepath',
  'filename',
  'source',
  'source_path',
  'input',
  'uri',
  'url',
]);

const URL_PATTERN = /https?:\/\/[^\s"'<>]+/i;
const WINDOWS_PATH_PATTERN = /[A-Za-z]:\\[^\s"'<>]+/;
const UNIX_PATH_PATTERN = /(?:\.{1,2}\/|\/)[^\s"'<>]+/;
const QUOTED_PATH_PATTERN = /["'`]([^"'`]*(?:\\|\/)[^"'`]*)["'`]/;

const normalizePathForComparison = (value: string) => value.trim().replace(/\//g, '\\').toLowerCase();

const getFilesystemAllowedRoots = (configItems: MCPServerConfigItem[]) => {
  const filesystemConfig = configItems.find((item) => item.name === 'filesystem')?.config;
  const rawArgs = filesystemConfig?.args;
  const args = Array.isArray(rawArgs) ? rawArgs : [];
  let pathArgs = args;
  const packageIndex = args.findIndex((item) => item === '@modelcontextprotocol/server-filesystem');
  if (packageIndex >= 0) {
    pathArgs = args.slice(packageIndex + 1);
  }
  const roots = pathArgs
    .map((item) => String(item || '').trim())
    .filter((item) => item && !item.startsWith('-') && !item.startsWith('@modelcontextprotocol/'));
  return roots;
};

const buildClientResourceRefs = (
  content: string,
  attachments: ChatAttachment[],
) : ResourceReference[] => {
  const refs: ResourceReference[] = [];
  const seen = new Set<string>();

  const addRef = (ref: ResourceReference) => {
    const key = `${String(ref.kind || '')}:${String(ref.path || ref.url || ref.label || '')}`.toLowerCase();
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    refs.push(ref);
  };

  attachments.forEach((attachment, index) => {
    addRef({
      ref_id: `client-att-${index}-${attachment.filename}`,
      kind: attachment.is_image ? 'uploaded_image' : 'uploaded_file',
      label: attachment.original_filename || attachment.filename,
      path: attachment.file_path,
      url: attachment.url,
      model_visible: Boolean(attachment.model_visible_on_current_turn),
      tool_usable: Boolean(attachment.tool_usable_on_current_turn),
    });
  });

  const urlMatches = String(content || '').match(/https?:\/\/[^\s"'<>]+/gi) || [];
  urlMatches.forEach((url, index) => {
    addRef({
      ref_id: `client-url-${index}`,
      kind: 'url',
      label: url,
      url,
      model_visible: true,
      tool_usable: true,
    });
  });

  return refs;
};

const isFilesystemPathAllowed = (value: string, configItems: MCPServerConfigItem[]) => {
  const candidate = normalizePathForComparison(value);
  if (!candidate) {
    return false;
  }
  const isWindowsAbsolute = /^[a-z]:\\/.test(candidate);
  const isUnixAbsolute = candidate.startsWith('\\');
  if (!isWindowsAbsolute && !isUnixAbsolute) {
    return !candidate.startsWith('..\\') && !candidate.includes('\\..\\');
  }
  const allowedRoots = getFilesystemAllowedRoots(configItems);
  if (allowedRoots.length === 0) {
    return false;
  }
  return allowedRoots.some((root) => {
    const normalizedRoot = normalizePathForComparison(root).replace(/\\+$/, '');
    return candidate === normalizedRoot || candidate.startsWith(`${normalizedRoot}\\`);
  });
};

const getUploadedAttachmentFilesystemPath = (attachment?: ChatAttachment) => {
  if (!attachment) {
    return '';
  }
  return attachment.file_path || '';
};

const extractPathLikeText = (text: string, preferUrl: boolean) => {
  const urlMatch = text.match(URL_PATTERN);
  if (preferUrl && urlMatch) {
    return urlMatch[0];
  }
  const atPathMatch = text.match(AT_PATH_PATTERN);
  if (atPathMatch?.[0]) {
    return atPathMatch[0].slice(1);
  }
  const quotedPath = text.match(QUOTED_PATH_PATTERN);
  if (quotedPath?.[1]) {
    return quotedPath[1];
  }
  const windowsPath = text.match(WINDOWS_PATH_PATTERN);
  if (windowsPath) {
    return windowsPath[0];
  }
  const unixPath = text.match(UNIX_PATH_PATTERN);
  if (unixPath) {
    return unixPath[0];
  }
  return urlMatch?.[0] || '';
};

const isLikelyPathArgument = (key: string, schema: Record<string, any>) => {
  const schemaType = resolveJsonSchemaType(schema);
  if (schemaType && schemaType !== 'string') {
    return false;
  }

  const normalizedKey = key.toLowerCase();
  const description = String(schema.description || schema.title || '').toLowerCase();
  return (
    PATH_ARGUMENT_NAMES.has(normalizedKey)
    || normalizedKey.endsWith('_path')
    || normalizedKey.endsWith('path')
    || normalizedKey.includes('filename')
    || normalizedKey === 'uri'
    || normalizedKey === 'url'
    || description.includes('path')
    || description.includes('uri')
    || description.includes('url')
  );
};

const inferToolArguments = (
  tool: MCPTool | null | undefined,
  messageText: string,
  attachments: ChatAttachment[],
  mcpConfigItems: MCPServerConfigItem[] = [],
) => {
  const schema = getToolSchema(tool);
  const properties = getJsonSchemaProperties(schema);
  const inferredArgs: Record<string, any> = {};
  const inferredFields: string[] = [];
  const inferredReasons: Record<string, string> = {};
  const firstAttachment = attachments[0];
  const isFilesystemTool = tool?.server === 'filesystem';
  const uploadedAttachmentPath = getUploadedAttachmentFilesystemPath(firstAttachment);

  Object.entries(properties).forEach(([key, rawSchema]) => {
    const propertySchema = (rawSchema || {}) as Record<string, any>;
    if (!isLikelyPathArgument(key, propertySchema)) {
      return;
    }

    const lowerKey = key.toLowerCase();
    const preferUrl = lowerKey === 'url' || lowerKey === 'uri' || String(propertySchema.description || '').toLowerCase().includes('url');
    const extracted = extractPathLikeText(messageText, preferUrl);
    let nextValue = extracted;
    let reason = extracted ? 'message_text' : '';

    if (
      isFilesystemTool
      && uploadedAttachmentPath
      && !preferUrl
      && !lowerKey.includes('filename')
      && (!nextValue || !isFilesystemPathAllowed(nextValue, mcpConfigItems))
    ) {
      nextValue = uploadedAttachmentPath;
      reason = extracted ? 'attachment_path_over_external_path' : 'attachment_path';
    }

    if (!nextValue && firstAttachment) {
      if (preferUrl && firstAttachment.url) {
        nextValue = firstAttachment.url;
        reason = 'attachment_url';
      } else if (lowerKey.includes('filename')) {
        nextValue = firstAttachment.original_filename || firstAttachment.filename;
        reason = 'attachment_filename';
      } else {
        nextValue = firstAttachment.file_path || firstAttachment.url || firstAttachment.filename;
        reason = 'attachment_path';
      }
    }

    if (nextValue) {
      inferredArgs[key] = nextValue;
      inferredFields.push(key);
      inferredReasons[key] = reason || 'message_text';
    }
  });

  return { inferredArgs, inferredFields, inferredReasons };
};

const getMissingRequiredToolArgs = (tool: MCPTool | null | undefined, args: Record<string, any>) => {
  const schema = getToolSchema(tool);
  const required = getJsonSchemaRequired(schema);
  return required.filter((key) => {
    const value = args[key];
    return value === undefined || value === null || String(value).trim() === '';
  });
};

function buildRuntimeView(
  bootstrap: ReturnType<typeof useSystemBootstrap>['bootstrap'],
  runtimeSnapshot: ReturnType<typeof useWebSocket>['runtimeSnapshot'],
  connectionStatus: ReturnType<typeof useWebSocket>['connectionStatus'],
): RuntimeView {
  const runtimeMcp = runtimeSnapshot?.mcp;
  const runtimeTools = Array.isArray(runtimeMcp?.available_tools)
    ? runtimeMcp?.available_tools ?? []
    : null;
  const connectionTools = Array.isArray(connectionStatus.available_tools)
    ? connectionStatus.available_tools
    : null;
  const bootstrapTools = bootstrap?.mcp.tools?.map((tool) => ({
    server: tool.server,
    name: tool.name,
    display_name: tool.display_name,
  })) || [];
  const availableTools = runtimeTools
    ?? connectionTools
    ?? bootstrapTools;

  const connectedServers = Array.isArray(runtimeMcp?.connected_servers)
    ? runtimeMcp?.connected_servers ?? []
    : Array.isArray(connectionStatus.connected_servers)
      ? connectionStatus.connected_servers
      : bootstrap?.mcp.connected_servers
        || [];
  const totalServers = bootstrap?.mcp.servers.total_servers || connectedServers.length;
  const toolsCount = runtimeSnapshot?.mcp?.tools_count
    ?? availableTools.length
    ?? bootstrap?.mcp.tools_count
    ?? 0;
  const temMode = String(runtimeSnapshot?.tem?.mode || bootstrap?.tem.mode || '');
  const providerReady = connectionStatus.providers_ready
    ?? runtimeSnapshot?.providers_ready
    ?? Boolean(bootstrap?.providers.siliconflow.configured || bootstrap?.providers.openrouter.configured);

  return {
    availableTools,
    connectedServers,
    totalServers,
    toolsCount,
    temMode,
    providerReady,
  };
}

const ChatInterface: React.FC = () => {
  const [clientId, setClientId] = useState(() => {
    const existingClientId = getStoredClientId();
    if (existingClientId) {
      return existingClientId;
    }

    const nextClientId = createClientId();
    persistClientId(nextClientId);
    return nextClientId;
  });

  const [inputText, setInputText] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showMCPTools, setShowMCPTools] = useState(false);
  const [showTEMPanel, setShowTEMPanel] = useState(false);
  const [showHealthPanel, setShowHealthPanel] = useState(false);
  const [showTaskCenter, setShowTaskCenter] = useState(false);
  const [showToolSelector, setShowToolSelector] = useState(false);
  const [showNewChatMenu, setShowNewChatMenu] = useState(false);
  const [toolSelectorPosition, setToolSelectorPosition] = useState({ x: 0, y: 0 });
  const [toolSearchQuery, setToolSearchQuery] = useState('');
  const [atSymbolPosition, setAtSymbolPosition] = useState(-1);
  const [allowedDirectToolsForChat, setAllowedDirectToolsForChat] = useState<Set<string>>(new Set());
  const [workspaceAgentProfile, setWorkspaceAgentProfile] = useState<WorkspaceAgentProfile | null>(null);
  const [selectedModel, setSelectedModel] = useState(() => loadSelectedModel());
  const [agentModelAutoAppliedFor, setAgentModelAutoAppliedFor] = useState<string>('');
  const [settings, setSettings] = useState<ChatSettings>(() => loadChatSettings());
  const [runtimeProviderConfig, setRuntimeProviderConfig] = useState<RuntimeProviderConfig>(() =>
    loadRuntimeProviderConfig(),
  );
  const [runtimeProviderState, setRuntimeProviderState] = useState<RuntimeProviderState | null>(null);
  const [runtimeToolPolicy, setRuntimeToolPolicy] = useState<ToolPolicyState | null>(null);
  const [runtimeAutoToolRouting, setRuntimeAutoToolRouting] = useState<AutoToolRoutingState | null>(null);
  const [mcpConfigItems, setMcpConfigItems] = useState<MCPServerConfigItem[]>([]);
  const [mcpConfigPath, setMcpConfigPath] = useState('');
  const [mcpConfigLoading, setMcpConfigLoading] = useState(false);
  const [mcpConfigSaving, setMcpConfigSaving] = useState(false);
  const [mcpConfigDeleting, setMcpConfigDeleting] = useState<string | null>(null);
  const [mcpConfigForm, setMcpConfigForm] = useState<MCPServerConfigForm>(() => createEmptyMcpServerForm());
  const [onboardingAudit, setOnboardingAudit] = useState<MCPToolOnboardingAuditReport | null>(null);
  const [onboardingRun, setOnboardingRun] = useState<MCPToolOnboardingSelfTestRunReport | null>(null);
  const [onboardingAuditLoading, setOnboardingAuditLoading] = useState(false);
  const [onboardingRunLoading, setOnboardingRunLoading] = useState(false);
  const [onboardingGateLoading, setOnboardingGateLoading] = useState(false);
  const [agentSkills, setAgentSkills] = useState<AgentSkillSummary[]>([]);
  const [agentSkillsExternalConfig, setAgentSkillsExternalConfig] = useState<AgentSkillExternalConfig | null>(null);
  const [externalSkillDirsText, setExternalSkillDirsText] = useState('');
  const [agentCapabilities, setAgentCapabilities] = useState<AgentCapabilitiesResponse | null>(null);
  const [agentSkillsLoading, setAgentSkillsLoading] = useState(false);
  const [providerConfigLoading, setProviderConfigLoading] = useState(false);
  const [toolPolicyLoading, setToolPolicyLoading] = useState(false);
  const [taskCenterLoading, setTaskCenterLoading] = useState(false);
  const [runtimeTasks, setRuntimeTasks] = useState<RuntimeRequestJournalEntry[]>([]);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [pendingSystemApprovals, setPendingSystemApprovals] = useState<SystemOperationApproval[]>([]);
  const [selectedSystemApproval, setSelectedSystemApproval] = useState<SystemOperationApproval | null>(null);
  const [systemApprovalSubmitting, setSystemApprovalSubmitting] = useState(false);
  const [selectedTaskReplayId, setSelectedTaskReplayId] = useState<string>('');
  const [selectedTaskReplayEvents, setSelectedTaskReplayEvents] = useState<AgentTaskReplayEvent[]>([]);
  const [showToolConfirm, setShowToolConfirm] = useState(false);
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  const [settingsNoticeTone, setSettingsNoticeTone] = useState<'info' | 'success' | 'warning' | 'error'>('info');
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [temModeLoading, setTemModeLoading] = useState(false);
  const [runtimeReloadLoading, setRuntimeReloadLoading] = useState(false);
  const [pendingToolCall, setPendingToolCall] = useState<{
    tool: DetectedToolCall;
    toolDetails: MCPTool | null;
    messageText: string;
    requestId?: string;
    imagePaths?: string[];
    attachments?: ChatAttachment[];
    initialArgs?: Record<string, any>;
    suggestedFields?: string[];
    autoFillReasons?: Record<string, string>;
  } | null>(null);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => translateForLanguage(settings.language, key, vars),
    [settings.language],
  );
  const languageRef = useRef(settings.language);
  languageRef.current = settings.language;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const newChatMenuRef = useRef<HTMLDivElement>(null);
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([]);
  const onboardingWorkspaceScopeRef = useRef<string>('');
  const lastAgentTaskStateRef = useRef<Map<string, string>>(new Map());

  const {
    bootstrap,
    loading: bootstrapLoading,
    error: bootstrapError,
    refresh: refreshBootstrap,
  } = useSystemBootstrap();

  const {
    connectionStatus,
    messages,
    isTyping,
    memoryStats,
    temStats,
    temRecipes,
    temGuards,
    runtimeSnapshot,
    pendingQueueSize,
    pendingOutboundRequests,
    cancelQueuedRequest,
    sendMessage,
    sendTrackedMessage,
    addUserMessage,
    updateMessage,
    clearMessages,
    setMessages,
    requestMCPStatus,
    clearMemory,
    requestTEMStatus,
    requestRecipes,
    requestGuards,
  } = useWebSocket(clientId);

  useEffect(() => {
    persistClientId(clientId);
  }, [clientId]);

  useEffect(() => {
    if (!showNewChatMenu) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (newChatMenuRef.current && !newChatMenuRef.current.contains(event.target as Node)) {
        setShowNewChatMenu(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowNewChatMenu(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [showNewChatMenu]);

  useEffect(() => {
    const savedSession = loadCurrentSession();
    if (!savedSession || savedSession.messages.length === 0) {
      return;
    }

    if (savedSession.clientId && savedSession.clientId !== clientId) {
      return;
    }

    setMessages(savedSession.messages);
  }, [clientId, setMessages]);

  useEffect(() => {
    if (messages.length === 0) {
      const persistedSession = loadCurrentSession();
      if (persistedSession && (!persistedSession.clientId || persistedSession.clientId === clientId)) {
        return;
      }
      clearPersistedCurrentSession();
      return;
    }

    persistCurrentSession(
      createSessionSnapshot(clientId, messages, {
        isAutoSaved: true,
        fallbackTitle: translateForLanguage(settings.language, 'chatHistory.newConversation'),
      }),
    );
  }, [clientId, messages, settings.language]);

  useEffect(() => {
    if (!bootstrap) {
      return;
    }

    const runtimeReadyModels = bootstrap.models.available.filter((model) => model.available !== false);
    const availableIds = new Set(runtimeReadyModels.map((model) => model.id));
    if (selectedModel && availableIds.has(selectedModel)) {
      return;
    }

    const fallbackModel =
      (bootstrap.models.default && availableIds.has(bootstrap.models.default) && bootstrap.models.default) ||
      runtimeReadyModels[0]?.id ||
      bootstrap.models.available[0]?.id ||
      '';

    if (fallbackModel && fallbackModel !== selectedModel) {
      setSelectedModel(fallbackModel);
    }
  }, [bootstrap, selectedModel]);

  useEffect(() => {
    if (bootstrap?.agent_skills?.skills) {
      setAgentSkills(bootstrap.agent_skills.skills);
    }
  }, [bootstrap?.agent_skills?.skills]);

  useEffect(() => {
    if (!bootstrapError) {
      return;
    }

    setMessages((prev) => {
      const exists = prev.some((message) => message.id === 'bootstrap-error');
      if (exists) {
        return prev;
      }
      return [
        ...prev,
        {
          id: 'bootstrap-error',
          type: 'error',
          content: t('app.bootstrapError', { error: bootstrapError }),
          timestamp: new Date().toISOString(),
        },
      ];
    });
  }, [bootstrapError, setMessages, t]);

  useEffect(() => {
    if (!bootstrap) {
      return;
    }

    setMessages((prev) => {
      const withoutBootstrapError = prev.filter((message) => message.id !== 'bootstrap-error');
      const summaryId = 'system-bootstrap-summary';
      const summaryContent = [
        t('app.bootstrapLoaded'),
        '',
        `${t('app.bootstrapProvider')}: SiliconFlow ${bootstrap.providers.siliconflow.configured ? t('health.ready') : t('health.missing')} / OpenRouter ${bootstrap.providers.openrouter.configured ? t('health.ready') : t('health.missing')}`,
        `${t('app.bootstrapModels')}: ${bootstrap.models.count}`,
        `${t('app.bootstrapConnectedServers')}: ${bootstrap.mcp.connected_servers.length}`,
        `${t('app.bootstrapTools')}: ${bootstrap.mcp.tools_count}`,
        `${t('app.bootstrapTemMode')}: ${bootstrap.tem.mode}`,
        `${t('app.bootstrapAudit')}: ${bootstrap.mcp.audit.ok ? t('app.pass') : t('app.warning')}`,
      ].join('\n');

      const existingIndex = withoutBootstrapError.findIndex((message) => message.id === summaryId);
      const nextMessage: ChatMessage = {
        id: summaryId,
        type: 'system',
        content: summaryContent,
        timestamp: new Date().toISOString(),
      };

      if (existingIndex >= 0) {
        const copy = [...withoutBootstrapError];
        copy[existingIndex] = nextMessage;
        return copy;
      }

      return withoutBootstrapError.length === 0 ? [nextMessage] : [...withoutBootstrapError, nextMessage];
    });
  }, [bootstrap, setMessages, t]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  useEffect(() => {
    if (settings.dark_mode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [settings.dark_mode]);

  useEffect(() => {
    saveChatSettings(settings);
  }, [settings]);

  const workspaceContextKey = workspaceContextDependencyKey(settings);
  const workspaceContextPayload = useMemo(
    () => buildWorkspaceContextPayload(settings),
    // workspaceContextKey tracks the subset of settings that affects this payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workspaceContextKey],
  );

  useEffect(() => {
    const payload = workspaceContextPayload;
    if (!payload) {
      setWorkspaceAgentProfile(null);
      setAgentModelAutoAppliedFor('');
      return;
    }
    let cancelled = false;
    void previewWorkspaceContext(payload)
      .then((result) => {
        if (cancelled) {
          return;
        }
        const nextProfile = ((result.agent_profile as WorkspaceAgentProfile) || null);
        setWorkspaceAgentProfile(nextProfile ? {
          ...nextProfile,
          commands: result.commands || [],
        } : null);
      })
      .catch((error) => {
        if (!cancelled) {
          console.error('Failed to preview workspace context:', error);
          setWorkspaceAgentProfile(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceContextPayload]);

  useEffect(() => {
    if (!workspaceAgentProfile?.modelKey || !bootstrap?.models?.available?.length) {
      return;
    }
    const modelKey = String(workspaceAgentProfile.modelKey).trim();
    const profileKey = `${workspaceAgentProfile.agent_name || ''}::${modelKey}`;
    const availableIds = new Set(
      bootstrap.models.available
        .filter((model) => model.available !== false)
        .map((model) => model.id),
    );
    if (!availableIds.has(modelKey)) {
      return;
    }
    if (agentModelAutoAppliedFor === profileKey) {
      return;
    }
    setSelectedModel(modelKey);
    setAgentModelAutoAppliedFor(profileKey);
  }, [agentModelAutoAppliedFor, bootstrap?.models?.available, workspaceAgentProfile]);

  useEffect(() => {
    saveSelectedModel(selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    saveRuntimeProviderConfig(runtimeProviderConfig);
  }, [runtimeProviderConfig]);

  useEffect(() => {
    if (!settingsNotice) {
      return undefined;
    }

    const timeout = window.setTimeout(() => {
      setSettingsNotice(null);
    }, 4000);

    return () => window.clearTimeout(timeout);
  }, [settingsNotice]);

  const pushSettingsNotice = useCallback((
    message: string,
    tone: 'info' | 'success' | 'warning' | 'error' = 'info',
  ) => {
    setSettingsNoticeTone(tone);
    setSettingsNotice(message);
  }, []);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [inputText]);

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments;
  }, [pendingAttachments]);

  useEffect(() => () => {
    pendingAttachmentsRef.current.forEach((attachment) => {
      if (attachment.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
    });
  }, []);

  useEffect(() => {
    if (connectionStatus.status !== 'connected') {
      return undefined;
    }

    requestMCPStatus(workspaceContextPayload);
    const interval = setInterval(() => {
      requestMCPStatus(workspaceContextPayload);
    }, MCP_STATUS_POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [
    connectionStatus.status,
    requestMCPStatus,
    workspaceContextPayload,
  ]);

  useEffect(() => {
    if (!showSettings || connectionStatus.status !== 'connected') {
      return;
    }
    requestMCPStatus(workspaceContextPayload);
  }, [
    showSettings,
    connectionStatus.status,
    requestMCPStatus,
    workspaceContextPayload,
  ]);

  const refreshAgentSkills = useCallback(async (showFailureNotice = true) => {
    setAgentSkillsLoading(true);
    try {
      const result = await getAgentSkills();
      setAgentSkills(result.skills || []);
      try {
        const externalConfig = await getAgentSkillsExternalConfig();
        setAgentSkillsExternalConfig(externalConfig);
        setExternalSkillDirsText((externalConfig.external_skill_dirs || []).join('\n'));
      } catch (configError) {
        console.error('Failed to refresh external skill config:', configError);
      }
    } catch (error) {
      console.error('Failed to refresh agent skills:', error);
      if (showFailureNotice) {
        pushSettingsNotice(
          translateForLanguage(
            languageRef.current,
            'app.agentSkillsRefreshFailed',
            { error: error instanceof Error ? error.message : String(error) },
          ),
          'error',
        );
      }
    } finally {
      setAgentSkillsLoading(false);
    }
  }, [pushSettingsNotice]);

  useEffect(() => {
    void refreshAgentSkills(false);
  }, [refreshAgentSkills]);

  const syncSupplementalRuntimeState = useCallback(async () => {
    try {
      const state = await getRuntimeProviders();
      setRuntimeProviderState(state);
      setRuntimeProviderConfig((prev) => ({
        ...prev,
        siliconflow_base_url:
          prev.siliconflow_base_url
          || state.runtime_overrides.siliconflow_base_url
          || state.providers.siliconflow.base_url
          || 'https://api.siliconflow.cn/v1',
        openrouter_base_url:
          prev.openrouter_base_url
          || state.runtime_overrides.openrouter_base_url
          || state.providers.openrouter.base_url
          || 'https://openrouter.ai/api/v1',
        default_model:
          prev.default_model
          || state.runtime_overrides.default_model
          || state.models.default
          || '',
        credential_mode: prev.credential_mode || 'session_only',
        custom_models:
          prev.custom_models.length > 0
            ? prev.custom_models
            : state.runtime_overrides.custom_models,
      }));
    } catch (error) {
      console.error('Failed to load runtime provider state:', error);
    }

    try {
      const policy = await getRuntimeToolPolicy();
      setRuntimeToolPolicy(policy);
    } catch (error) {
      console.error('Failed to load runtime tool policy:', error);
    }

    try {
      const autoToolRouting = await getRuntimeAutoToolRouting();
      setRuntimeAutoToolRouting(autoToolRouting);
      setSettings((prev) => ({
        ...prev,
        autoToolRoutingMode: autoToolRouting.mode || prev.autoToolRoutingMode,
      }));
    } catch (error) {
      console.error('Failed to load runtime auto tool routing state:', error);
    }

    try {
      const capabilities = await getAgentCapabilities();
      setAgentCapabilities(capabilities);
    } catch (error) {
      console.error('Failed to load agent capabilities:', error);
    }

    try {
      const configState = await getMcpConfig();
      setMcpConfigItems(configState.servers);
      setMcpConfigPath(configState.config_path);
    } catch (error) {
      console.error('Failed to load MCP config state:', error);
    }
  }, []);

  useEffect(() => {
    void syncSupplementalRuntimeState();
  }, [syncSupplementalRuntimeState]);

  const refreshRuntimeTasks = useCallback(async () => {
    setTaskCenterLoading(true);
    try {
      const [runtimeResult, agentResult, approvalResult] = await Promise.all([
        getRuntimeRequests(40, clientId),
        getAgentTasks(40, clientId),
        getAgentOperationApprovals({ client_id: clientId }),
      ]);
      setRuntimeTasks(runtimeResult.items || []);
      setAgentTasks(agentResult.items || []);
      setPendingSystemApprovals(approvalResult.items || []);
    } catch (error) {
      console.error('Failed to load runtime or agent tasks:', error);
    } finally {
      setTaskCenterLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    if (!showTaskCenter) {
      return;
    }
    void refreshRuntimeTasks();
  }, [refreshRuntimeTasks, showTaskCenter]);

  useEffect(() => {
    if (!settings.agentModeEnabled) {
      return undefined;
    }

    void refreshRuntimeTasks();
    const intervalId = window.setInterval(() => {
      void refreshRuntimeTasks();
    }, AGENT_STATUS_POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshRuntimeTasks, settings.agentModeEnabled]);

  const runtimeView = useMemo(
    () => buildRuntimeView(bootstrap, runtimeSnapshot, connectionStatus),
    [bootstrap, connectionStatus, runtimeSnapshot],
  );
  const availableTools = useMemo(
    () => filterAvailableToolsByAgentProfile(runtimeView.availableTools, workspaceAgentProfile, settings),
    [runtimeView.availableTools, settings, workspaceAgentProfile],
  );
  const providerReady = runtimeView.providerReady;
  const runningAgentTasks = agentTasks.filter((task) => ['running', 'waiting_approval'].includes(String(task.status || ''))).length;
  const completedAgentTasks = agentTasks.filter((task) => String(task.status || '') === 'completed').length;
  const activeRuntimeRequestsCount = runtimeTasks.filter((task) => task.status === 'inflight').length;
  const hasActiveTaskSignals = pendingQueueSize > 0
    || activeRuntimeRequestsCount > 0
    || runningAgentTasks > 0
    || pendingSystemApprovals.length > 0;
  const showResearchPanels = settings.showAdvancedDebugTraces;
  const workspaceAgentAttached = Boolean(
    workspaceAgentProfile?.agent_name
    || workspaceAgentProfile?.allowMCPs?.length
    || workspaceAgentProfile?.modelKey,
  );
  const workspaceMcpAttached = Boolean(
    connectionStatus.workspace_mcp?.workspace_enabled
    || runtimeSnapshot?.workspace_mcp?.workspace_enabled,
  );
  const showTaskCenterEntry = hasActiveTaskSignals || showResearchPanels;
  const showAgentStatusBanner = pendingSystemApprovals.length > 0
    || runningAgentTasks > 0
    || activeRuntimeRequestsCount > 0
    || settings.agentModeEnabled
    || workspaceAgentAttached
    || workspaceMcpAttached
    || showResearchPanels;
  const selectedModelData = useMemo(
    () => bootstrap?.models.available.find((model) => model.id === selectedModel),
    [bootstrap?.models.available, selectedModel],
  );
  const selectedModelSupportsImages = selectedModelData?.type === 'multimodal';
  const uploadedAttachmentsForPlan = useMemo(
    () => pendingAttachments
      .map((attachment) => attachment.uploadedAttachment)
      .filter((attachment): attachment is ChatAttachment => Boolean(attachment)),
    [pendingAttachments],
  );
  const attachmentExecutionPlan = useMemo(
    () => buildAttachmentExecutionPlan({
      attachments: uploadedAttachmentsForPlan,
      selectedModelSupportsImages: Boolean(selectedModelSupportsImages),
      language: settings.language,
    }),
    [settings.language, selectedModelSupportsImages, uploadedAttachmentsForPlan],
  );
  const attachmentPlanByFilename = useMemo(() => {
    const lookup = new Map<string, typeof attachmentExecutionPlan.items[number]>();
    attachmentExecutionPlan.items.forEach((item) => {
      lookup.set(item.filename, item);
    });
    return lookup;
  }, [attachmentExecutionPlan]);
  const acceptedAttachmentExtensions = useMemo(() => Array.from(new Set([
    ...Array.from(IMAGE_EXTENSIONS),
    ...Array.from(DOCUMENT_EXTENSIONS),
    ...Array.from(TEXT_EXTENSIONS),
  ])).sort(), []);

  const isSupportedAttachmentFile = useCallback(
    (file: File) => {
      if (isImageFile(file)) {
        return true;
      }
      return isDocumentLikeFile(file);
    },
    [],
  );

  const handleAttachmentSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    addPendingFiles(files);
  };

  const convertImageToBase64 = (file: File): Promise<string> => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const parts = result.split(',');
      resolve(parts.length > 1 ? parts[1] : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

  const uploadAttachment = async (file: File): Promise<ChatAttachment | null> => {
    try {
      const result = await uploadFile(file);
      return toChatAttachment(result);
    } catch (error) {
      console.error('Upload error:', error);
      return null;
    }
  };

  const uploadPendingAttachment = useCallback(async (pendingId: string, file: File) => {
    setPendingAttachments((prev) => prev.map((attachment) => (
      attachment.id === pendingId
        ? { ...attachment, uploadState: 'uploading', uploadError: null }
        : attachment
    )));

    try {
      const uploadedAttachment = await uploadAttachment(file);
      if (!uploadedAttachment) {
        throw new Error('upload_failed');
      }
      setPendingAttachments((prev) => prev.map((attachment) => (
        attachment.id === pendingId
          ? {
            ...attachment,
            uploadedAttachment,
            uploadState: 'ready',
            uploadError: null,
          }
          : attachment
      )));
    } catch (error) {
      setPendingAttachments((prev) => prev.map((attachment) => (
        attachment.id === pendingId
          ? {
            ...attachment,
            uploadState: 'failed',
            uploadError: error instanceof Error ? error.message : String(error),
          }
          : attachment
      )));
    }
  }, []);

  const addPendingFiles = useCallback((files: File[]) => {
    if (files.length === 0) {
      return;
    }

    const supportedFiles: File[] = [];
    let rejectedCount = 0;

    files.forEach((file) => {
      if (isSupportedAttachmentFile(file)) {
        supportedFiles.push(file);
      } else {
        rejectedCount += 1;
      }
    });

    if (rejectedCount > 0) {
      pushSettingsNotice(
        t('app.attachmentFilteredByModel', { count: rejectedCount }),
        'warning',
      );
    }

    if (supportedFiles.length === 0) {
      return;
    }

    const createdAttachments = supportedFiles.map((file) => createPendingAttachment(file));
    setPendingAttachments((prev) => [
      ...prev,
      ...createdAttachments,
    ]);
    createdAttachments.forEach((attachment) => {
      void uploadPendingAttachment(attachment.id, attachment.file);
    });
  }, [isSupportedAttachmentFile, pushSettingsNotice, t, uploadPendingAttachment]);

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    const cursorPosition = event.target.selectionStart;
    setInputText(value);

    const lastAtIndex = value.lastIndexOf('@', cursorPosition - 1);
    if (lastAtIndex === -1) {
      setShowToolSelector(false);
      return;
    }

    const textAfterAt = value.substring(lastAtIndex + 1, cursorPosition);
    if (/[\s\n]/.test(textAfterAt)) {
      setShowToolSelector(false);
      return;
    }

    setAtSymbolPosition(lastAtIndex);
    setToolSearchQuery(textAfterAt);

    if (textareaRef.current) {
      const rect = textareaRef.current.getBoundingClientRect();
      setToolSelectorPosition({
        x: rect.left + TOOL_SELECTOR_OFFSET_X,
        y: rect.top,
      });
    }

    setShowToolSelector(true);
  };

  const handleToolSelect = (toolName: string, serverName: string) => {
    if (atSymbolPosition === -1) {
      return;
    }

    const beforeAt = inputText.substring(0, atSymbolPosition);
    const afterQuery = inputText.substring(atSymbolPosition + 1 + toolSearchQuery.length);
    const newText = `${beforeAt}@${serverName}.${toolName} ${afterQuery}`;
    setInputText(newText);
    setShowToolSelector(false);
    setAtSymbolPosition(-1);
    setToolSearchQuery('');

    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        const position = beforeAt.length + serverName.length + toolName.length + 2;
        textareaRef.current.setSelectionRange(position, position);
      }
    }, 0);
  };

  const handleCloseToolSelector = () => {
    setShowToolSelector(false);
    setAtSymbolPosition(-1);
    setToolSearchQuery('');
  };

  const detectToolCalls = (text: string) => {
    const matches: DetectedToolCall[] = [];
    let match: RegExpExecArray | null;
    TOOL_CALL_PATTERN.lastIndex = 0;
    while ((match = TOOL_CALL_PATTERN.exec(text)) !== null) {
      matches.push({
        serverName: match[1],
        toolName: match[2],
        fullMatch: match[0],
      });
    }
    return matches;
  };

  const resolveToolDetails = useCallback(
    (toolCall: DetectedToolCall | null | undefined): MCPTool | null => {
      if (!toolCall) {
        return null;
      }
      const visibleToolKeys = new Set(availableTools.map((tool) => `${tool.server}.${tool.name}`));
      if (visibleToolKeys.size > 0 && !visibleToolKeys.has(`${toolCall.serverName}.${toolCall.toolName}`)) {
        return null;
      }
      const matched = bootstrap?.mcp.tools?.find(
        (tool) => tool.server === toolCall.serverName && tool.name === toolCall.toolName,
      );
      return matched || null;
    },
    [availableTools, bootstrap],
  );

  const resetComposer = () => {
    setInputText('');
    setPendingAttachments((prev) => {
      prev.forEach((attachment) => {
        if (attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      });
      return [];
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const archiveCurrentConversation = () => {
    if (messages.length === 0) {
      return false;
    }

    const archivedSession = createSessionSnapshot(clientId, messages, {
      id: `session-${Date.now()}`,
      isAutoSaved: false,
      fallbackTitle: translateForLanguage(settings.language, 'chatHistory.newConversation'),
    });

    persistSessions([
      archivedSession,
      ...loadSavedSessions().filter((session) => session.id !== archivedSession.id),
    ]);
    return true;
  };

  const clearCurrentChatWindow = ({
    resetInput = false,
    closeHistory = false,
  }: {
    resetInput?: boolean;
    closeHistory?: boolean;
  } = {}) => {
    if (resetInput) {
      resetComposer();
    }
    clearPersistedCurrentSession();
    clearMessages();
    setAllowedDirectToolsForChat(new Set());
    setRuntimeTasks([]);
    setPendingToolCall(null);
    setShowToolConfirm(false);
    setShowToolSelector(false);
    setToolSearchQuery('');
    setAtSymbolPosition(-1);
    setShowNewChatMenu(false);
    if (closeHistory) {
      setShowHistory(false);
    }
  };

  const handleStartNewChat = () => {
    const archived = archiveCurrentConversation();
    clearCurrentChatWindow({ resetInput: true, closeHistory: true });

    const nextClientId = createClientId();
    setClientId(nextClientId);

    pushSettingsNotice(
      settings.language === 'zh'
        ? (
          archived
            ? '\u5df2\u65b0\u5efa\u804a\u5929\uff0c\u5f53\u524d\u5bf9\u8bdd\u5df2\u5f52\u6863\u5230\u5386\u53f2\u8bb0\u5f55\u3002'
            : '\u5df2\u65b0\u5efa\u7a7a\u767d\u804a\u5929\u3002'
        )
        : (archived ? 'Started a new chat. The current conversation was archived to history.' : 'Started a new blank chat.'),
      'success',
    );

    window.setTimeout(() => {
      textareaRef.current?.focus();
    }, 0);
  };

  const handleClearCurrentWindowOnly = () => {
    clearCurrentChatWindow({ resetInput: true });
    pushSettingsNotice(
      settings.language === 'zh'
        ? '\u5df2\u6e05\u7a7a\u5f53\u524d\u7a97\u53e3\uff0c\u540e\u7aef\u4f1a\u8bdd\u4e0a\u4e0b\u6587\u4fdd\u6301\u4e0d\u53d8\u3002'
        : 'Cleared the current window only. The backend session context was kept.',
      'info',
    );

    window.setTimeout(() => {
      textareaRef.current?.focus();
    }, 0);
  };

  const handleToolConfirm = async (args: Record<string, any>) => {
    if (!pendingToolCall) {
      return;
    }

    const { tool, toolDetails, messageText, requestId, imagePaths, attachments } = pendingToolCall;
    const { _allowThisChat, ...toolArgsRaw } = args;
    const toolKey = `${tool.serverName}.${tool.toolName}`;
    const toolSchema = getToolSchema(toolDetails);
    const toolArgs = pruneEmptyOptionalArgs(toolSchema, toolArgsRaw);
    const missingRequired = getMissingRequiredToolArgs(toolDetails, toolArgs);

    if (missingRequired.length > 0) {
      pushSettingsNotice(
        t('modal.requiredMissing', { fields: missingRequired.join(', ') }),
        'warning',
      );
      return;
    }

    setShowToolConfirm(false);
    setPendingToolCall(null);

    if (_allowThisChat) {
      setAllowedDirectToolsForChat((prev) => {
        const next = new Set(prev);
        next.add(toolKey);
        return next;
      });
    }

    const payload = {
      type: 'tool_call',
      request_id: requestId || createTrackedRequestId(),
      server_name: tool.serverName,
      tool_name: tool.toolName,
      arguments: toolArgs,
      model_id: selectedModel || bootstrap?.models.default || '',
      skill_ids: settings.enabledSkillIds,
      custom_system_prompt: settings.enableCustomSystemPrompt ? settings.customSystemPrompt : '',
      workspace_context: workspaceContextPayload,
      workspace_agent_command: detectWorkspaceAgentCommand(messageText),
      policy_confirmed: true,
      content: messageText,
      image_path: imagePaths?.[0],
      attachments,
    };

    const tracked = sendTrackedMessage(payload);
    addUserMessage(messageText, {
      imagePath: imagePaths?.[0],
      attachments,
      requestId: tracked.requestId,
      deliveryStatus: tracked.ok || tracked.queued ? 'pending' : 'failed',
      retryable: true,
      retryPayload: tracked.payload,
    });
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.toolQueuedDisconnected'),
        tracked.queued ? 'info' : 'warning',
      );
    }
    resetComposer();
  };

  const handleToolCancel = () => {
    setShowToolConfirm(false);
    setPendingToolCall(null);
  };

  const handleSendMessage = async () => {
    const trimmedInput = inputText.trim();
    const workspaceAgentCommand = detectWorkspaceAgentCommand(trimmedInput);
    const toolCalls = detectToolCalls(trimmedInput);
    const canDirectToolCall = toolCalls.length > 0;
    const primaryDetectedTool = toolCalls[0];
    const primaryToolKey = primaryDetectedTool ? `${primaryDetectedTool.serverName}.${primaryDetectedTool.toolName}` : '';
    const effectiveConfirmToolCalls = workspaceAgentProfile?.isConfirmCallTool ?? settings.confirmToolCalls;
    const requiresDirectToolConfirmation =
      canDirectToolCall
      && effectiveConfirmToolCalls
      && (!primaryToolKey || !allowedDirectToolsForChat.has(primaryToolKey));

    if ((!trimmedInput && pendingAttachments.length === 0) || connectionStatus.status !== 'connected') {
      return;
    }

    if (!providerReady && !canDirectToolCall) {
      return;
    }

    const uploadingAttachments = pendingAttachments.filter((attachment) => attachment.uploadState === 'uploading' || attachment.uploadState === 'pending');
    if (uploadingAttachments.length > 0) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? '\u4ecd\u6709\u9644\u4ef6\u6b63\u5728\u4e0a\u4f20\u6216\u89e3\u6790\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u540e\u518d\u53d1\u9001\u3002'
          : 'Some attachments are still uploading or parsing. Wait before sending.',
        'warning',
      );
      return;
    }

    const failedAttachments = pendingAttachments.filter((attachment) => attachment.uploadState === 'failed');
    if (failedAttachments.length > 0) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? '\u5b58\u5728\u4e0a\u4f20\u5931\u8d25\u7684\u9644\u4ef6\uff0c\u8bf7\u79fb\u9664\u6216\u91cd\u65b0\u6dfb\u52a0\u540e\u518d\u53d1\u9001\u3002'
          : 'Some attachments failed to upload. Remove or re-add them before sending.',
        'error',
      );
      return;
    }

    let imageBase64: string | undefined;
    let imageBase64List: string[] = [];
    let uploadedImagePaths: string[] = [];
    const uploadedAttachments: ChatAttachment[] = attachmentExecutionPlan.items.flatMap((planItem) => {
      const matched = uploadedAttachmentsForPlan.find((attachment) => (
        (attachment.original_filename || attachment.filename) === planItem.filename
      ));
      return matched
        ? {
          ...matched,
          transport_role: planItem.transport_role,
          transport_reason: planItem.transport_reason,
          model_visible_on_current_turn: planItem.model_visible_on_current_turn,
          tool_usable_on_current_turn: planItem.tool_usable_on_current_turn,
        }
        : [];
    });

    if (pendingAttachments.length > 0) {
      const containsImage = pendingAttachments.some((attachment) => isImageFile(attachment.file));
      if (containsImage && !providerReady && !canDirectToolCall) {
        pushSettingsNotice(t('app.imageMessagesNeedProvider'), 'warning');
        return;
      }

      for (const pendingAttachment of pendingAttachments) {
        const planItem = pendingAttachment.uploadedAttachment
          ? attachmentPlanByFilename.get(
            pendingAttachment.uploadedAttachment.original_filename || pendingAttachment.uploadedAttachment.filename,
          )
          : null;

        if (isImageFile(pendingAttachment.file) && providerReady && planItem?.will_send_image_data) {
          imageBase64List.push(await convertImageToBase64(pendingAttachment.file));
        }

        if (pendingAttachment.uploadedAttachment?.is_image && providerReady && planItem?.will_send_image_data) {
          uploadedImagePaths.push(pendingAttachment.uploadedAttachment.url);
        }
      }

      if (imageBase64List.length > 0) {
        imageBase64 = imageBase64List[0];
      }
    }

    const requestId = createTrackedRequestId();
    const primaryToolDetails = resolveToolDetails(primaryDetectedTool);
    const primaryToolInference = inferToolArguments(primaryToolDetails, trimmedInput, uploadedAttachments, mcpConfigItems);
    const primarySchemaProperties = Object.keys(getJsonSchemaProperties(getToolSchema(primaryToolDetails)));
    const primaryToolRequiresSchemaReview =
      primarySchemaProperties.length > 0
      && (!primaryToolKey || !allowedDirectToolsForChat.has(primaryToolKey));

    if (canDirectToolCall && (requiresDirectToolConfirmation || primaryToolRequiresSchemaReview)) {
      setPendingToolCall({
        tool: toolCalls[0],
        toolDetails: primaryToolDetails,
        messageText: trimmedInput,
        requestId,
        imagePaths: uploadedImagePaths,
        attachments: uploadedAttachments,
        initialArgs: primaryToolInference.inferredArgs,
        suggestedFields: primaryToolInference.inferredFields,
        autoFillReasons: primaryToolInference.inferredReasons,
      });
      setShowToolConfirm(true);
      return;
    }

    void registerAgentTaskForMessage(
      trimmedInput || (settings.language === 'zh' ? '\u5206\u6790\u5df2\u4e0a\u4f20\u9644\u4ef6' : 'Analyze uploaded attachments'),
      uploadedAttachments,
    );

    if (canDirectToolCall) {
      const firstToolCall = toolCalls[0];
      const firstToolDetails = resolveToolDetails(firstToolCall);
      const firstToolInference = inferToolArguments(firstToolDetails, trimmedInput, uploadedAttachments, mcpConfigItems);
      const normalizedToolArgs = pruneEmptyOptionalArgs(getToolSchema(firstToolDetails), firstToolInference.inferredArgs);
      const missingRequired = getMissingRequiredToolArgs(firstToolDetails, normalizedToolArgs);

      if (missingRequired.length > 0) {
        setPendingToolCall({
          tool: firstToolCall,
          toolDetails: firstToolDetails,
          messageText: trimmedInput,
          requestId,
          imagePaths: uploadedImagePaths,
          attachments: uploadedAttachments,
          initialArgs: normalizedToolArgs,
          suggestedFields: firstToolInference.inferredFields,
          autoFillReasons: firstToolInference.inferredReasons,
        });
        setShowToolConfirm(true);
        return;
      }

      const tracked = sendTrackedMessage({
        type: 'tool_call',
        request_id: requestId,
        server_name: firstToolCall.serverName,
        tool_name: firstToolCall.toolName,
        arguments: normalizedToolArgs,
        model_id: selectedModel || bootstrap?.models.default || '',
        skill_ids: settings.enabledSkillIds,
        custom_system_prompt: settings.enableCustomSystemPrompt ? settings.customSystemPrompt : '',
        workspace_context: workspaceContextPayload,
        workspace_agent_command: workspaceAgentCommand,
        policy_confirmed: false,
        content: trimmedInput,
        web_search_enabled: webSearchEnabled,
        image_path: uploadedImagePaths[0],
        attachments: uploadedAttachments,
        attachment_plan: attachmentExecutionPlan,
        resource_refs: buildClientResourceRefs(trimmedInput, uploadedAttachments),
      });
      addUserMessage(trimmedInput, {
        imagePath: uploadedImagePaths[0],
        attachments: uploadedAttachments,
        requestId: tracked.requestId,
        deliveryStatus: tracked.ok || tracked.queued ? 'pending' : 'failed',
        retryable: true,
        retryPayload: tracked.payload,
        metadata: {
          attachment_plan: attachmentExecutionPlan,
          resource_refs: buildClientResourceRefs(trimmedInput, uploadedAttachments),
          web_search_enabled: webSearchEnabled,
        },
      });
      if (!tracked.ok) {
        pushSettingsNotice(
          tracked.queued ? t('app.requestQueuedForReconnect') : t('app.toolSendUnavailable'),
          tracked.queued ? 'info' : 'error',
        );
      }
      resetComposer();
      return;
    }

    const tracked = sendTrackedMessage({
      type: 'chat',
      request_id: requestId,
      content: trimmedInput,
      image_data: imageBase64,
      image_data_list: imageBase64List,
      image_path: uploadedImagePaths[0],
      image_paths: uploadedImagePaths,
      attachments: uploadedAttachments,
      attachment_plan: attachmentExecutionPlan,
      model_id: selectedModel || bootstrap?.models.default || '',
      skill_ids: settings.enabledSkillIds,
      custom_system_prompt: settings.enableCustomSystemPrompt ? settings.customSystemPrompt : '',
      workspace_context: workspaceContextPayload,
      workspace_agent_command: workspaceAgentCommand,
      web_search_enabled: webSearchEnabled,
      resource_refs: buildClientResourceRefs(trimmedInput, uploadedAttachments),
    });
    addUserMessage(trimmedInput, {
      imagePath: uploadedImagePaths[0],
      attachments: uploadedAttachments,
      requestId: tracked.requestId,
      deliveryStatus: tracked.ok || tracked.queued ? 'pending' : 'failed',
      retryable: true,
      retryPayload: tracked.payload,
      metadata: {
        attachment_plan: attachmentExecutionPlan,
        resource_refs: buildClientResourceRefs(trimmedInput, uploadedAttachments),
        web_search_enabled: webSearchEnabled,
      },
    });
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.messageSendUnavailable'),
        tracked.queued ? 'info' : 'error',
      );
    }

    resetComposer();
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (showToolSelector) {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleCloseToolSelector();
      }
      return;
    }

    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSendMessage();
    }
  };

  const handleModelChange = (modelId: string) => {
    setSelectedModel(modelId);
    if (workspaceAgentProfile?.modelKey && modelId !== workspaceAgentProfile.modelKey) {
      setAgentModelAutoAppliedFor(`${workspaceAgentProfile.agent_name || ''}::${workspaceAgentProfile.modelKey}`);
    }
    sendMessage({
      type: 'model_select',
      model_id: modelId,
    });
  };

  const handleRetryMessage = (message: ChatMessage) => {
    if (!message.retry_payload) {
      pushSettingsNotice(t('app.retryUnavailable'), 'warning');
      return;
    }
    const tracked = sendTrackedMessage({
      ...message.retry_payload,
      request_id: message.request_id || message.retry_payload.request_id || createTrackedRequestId(),
    });
    updateMessage(message.id, {
      request_id: tracked.requestId,
      delivery_status: tracked.ok || tracked.queued ? 'pending' : 'failed',
      delivery_error: tracked.ok || tracked.queued ? undefined : 'Realtime connection is unavailable',
      retry_payload: tracked.payload,
      retryable: true,
    });
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.retryFailedDisconnected'),
        tracked.queued ? 'info' : 'error',
      );
    }
  };

  const handleComposerPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedFiles = Array.from(event.clipboardData.files || []);
    if (pastedFiles.length === 0) {
      return;
    }
    event.preventDefault();
    addPendingFiles(pastedFiles);
  };

  const handleComposerDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (event.dataTransfer.types.includes('Files')) {
      event.preventDefault();
    }
  };

  const handleComposerDrop = (event: React.DragEvent<HTMLDivElement>) => {
    const droppedFiles = Array.from(event.dataTransfer.files || []);
    if (droppedFiles.length === 0) {
      return;
    }
    event.preventDefault();
    addPendingFiles(droppedFiles);
  };

  const handleMCPToolCall = (serverName: string, toolName: string, args: Record<string, any>) => {
    const requestId = createTrackedRequestId();
    const tracked = sendTrackedMessage({
      type: 'tool_call',
      request_id: requestId,
      server_name: serverName,
      tool_name: toolName,
      arguments: args,
      model_id: selectedModel || bootstrap?.models.default || '',
      skill_ids: settings.enabledSkillIds,
      custom_system_prompt: settings.enableCustomSystemPrompt ? settings.customSystemPrompt : '',
      workspace_context: workspaceContextPayload,
      policy_confirmed: false,
      timestamp: new Date().toISOString(),
    });
    setMessages((prev) => [
      ...prev,
      {
        ...buildSystemMessage(t('app.manualToolCall', { server: serverName, tool: toolName })),
        request_id: tracked.requestId,
        delivery_status: tracked.ok || tracked.queued ? 'pending' : 'failed',
        retryable: true,
        retry_payload: tracked.payload,
      },
    ]);
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.toolSendUnavailable'),
        tracked.queued ? 'info' : 'error',
      );
    }
  };

  const handleMCPResourceRead = (serverName: string, uri: string) => {
    const requestId = createTrackedRequestId();
    const tracked = sendTrackedMessage({
      type: 'resource_read',
      request_id: requestId,
      server_name: serverName,
      uri,
      timestamp: new Date().toISOString(),
    });
    setMessages((prev) => [
      ...prev,
      {
        ...buildSystemMessage(t('app.manualResourceRead', { server: serverName, uri })),
        request_id: tracked.requestId,
        delivery_status: tracked.ok || tracked.queued ? 'pending' : 'failed',
        retryable: true,
        retry_payload: tracked.payload,
      },
    ]);
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.resourceSendUnavailable'),
        tracked.queued ? 'info' : 'error',
      );
    }
  };

  const handleMCPPromptGet = (serverName: string, promptName: string, args: Record<string, any>) => {
    const requestId = createTrackedRequestId();
    const tracked = sendTrackedMessage({
      type: 'prompt_get',
      request_id: requestId,
      server_name: serverName,
      prompt_name: promptName,
      arguments: args,
      timestamp: new Date().toISOString(),
    });
    setMessages((prev) => [
      ...prev,
      {
        ...buildSystemMessage(t('app.manualPromptLoad', { server: serverName, prompt: promptName })),
        request_id: tracked.requestId,
        delivery_status: tracked.ok || tracked.queued ? 'pending' : 'failed',
        retryable: true,
        retry_payload: tracked.payload,
      },
    ]);
    if (!tracked.ok) {
      pushSettingsNotice(
        tracked.queued ? t('app.requestQueuedForReconnect') : t('app.promptSendUnavailable'),
        tracked.queued ? 'info' : 'error',
      );
    }
  };

  const removeAttachment = (attachmentId: string) => {
    setPendingAttachments((prev) => {
      const target = prev.find((attachment) => attachment.id === attachmentId);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((attachment) => attachment.id !== attachmentId);
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const toggleDarkMode = () => {
    setSettings((prev) => ({ ...prev, dark_mode: !prev.dark_mode }));
  };

  const handleSettingsChange = (nextSettings: ChatSettings) => {
    setSettings(nextSettings);
    pushSettingsNotice(t('app.localSettingsSaved'), 'success');
  };

  const handleResetLocalSettings = () => {
    const defaultSettings = resetChatSettings();
    setSettings(defaultSettings);
    pushSettingsNotice(t('app.localSettingsReset'), 'success');
  };

  const handleRefreshRuntime = async () => {
    const result = await refreshBootstrap();
    requestMCPStatus(workspaceContextPayload);
    requestTEMStatus();
    requestRecipes();
    requestGuards();
    await refreshRuntimeTasks();

    try {
      const skillsState = await getAgentSkills();
      setAgentSkills(skillsState.skills || []);
    } catch (error) {
      console.error('Failed to refresh agent skills:', error);
    }

    await syncSupplementalRuntimeState();

    if (result.ok) {
      pushSettingsNotice(t('app.systemSnapshotRefreshed'), 'success');
    } else {
      pushSettingsNotice(t('app.systemSnapshotRefreshFailed', { error: result.error }), 'error');
    }
  };

  const handleReloadAgentSkills = async () => {
    setAgentSkillsLoading(true);
    try {
      const result = await reloadAgentSkills();
      setAgentSkills(result.skills || []);
      try {
        const externalConfig = await getAgentSkillsExternalConfig();
        setAgentSkillsExternalConfig(externalConfig);
        setExternalSkillDirsText((externalConfig.external_skill_dirs || []).join('\n'));
      } catch (configError) {
        console.error('Failed to refresh external skill config:', configError);
      }
      setSettings((prev) => ({
        ...prev,
        enabledSkillIds: prev.enabledSkillIds.filter((skillId) =>
          (result.skills || []).some((skill) => skill.id === skillId),
        ),
      }));
      pushSettingsNotice(t('app.agentSkillsReloaded', { count: result.count || 0 }), 'success');
      await refreshBootstrap();
    } catch (error) {
      pushSettingsNotice(
        t('app.agentSkillsReloadFailed', { error: error instanceof Error ? error.message : String(error) }),
        'error',
      );
    } finally {
      setAgentSkillsLoading(false);
    }
  };

  const handleApplyExternalSkillDirs = async () => {
    setAgentSkillsLoading(true);
    try {
      const dirs = externalSkillDirsText
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      const result = await updateAgentSkillsExternalConfig({ external_skill_dirs: dirs });
      setAgentSkillsExternalConfig(result);
      setExternalSkillDirsText((result.external_skill_dirs || []).join('\n'));
      if (Array.isArray(result.skills)) {
        setAgentSkills(result.skills);
      } else {
        const refreshed = await reloadAgentSkills();
        setAgentSkills(refreshed.skills || []);
      }
      pushSettingsNotice(
        settings.language === 'zh' ? '\u5916\u90e8\u6280\u80fd\u76ee\u5f55\u5df2\u4fdd\u5b58\u5e76\u91cd\u8f7d\u3002' : 'External skill directories saved and reloaded.',
        'success',
      );
    } catch (error) {
      console.error('Failed to update external skill directories:', error);
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u4fdd\u5b58\u5916\u90e8\u6280\u80fd\u76ee\u5f55\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Failed to save external skill directories: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    } finally {
      setAgentSkillsLoading(false);
    }
  };

  const handleTemModeChange = async (mode: string) => {
    if (runtimeView.temMode === mode) {
      pushSettingsNotice(t('app.temAlreadyMode', { mode }), 'info');
      return;
    }

    setTemModeLoading(true);
    try {
      const result = await setTemMode(mode);
      await handleRefreshRuntime();
      setMessages((prev) => [
        ...prev,
        buildSystemMessage(t('app.temModeSwitched', { mode: result.mode })),
      ]);
      pushSettingsNotice(t('app.temModeSwitched', { mode: result.mode }), 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.temModeSwitchFailed', { error: message }), 'error');
    } finally {
      setTemModeLoading(false);
    }
  };

  const handleReloadRuntimeParams = async () => {
    setRuntimeReloadLoading(true);
    try {
      await reloadRuntimeParams();
      await handleRefreshRuntime();
      setMessages((prev) => [
        ...prev,
        buildSystemMessage(t('app.backendRuntimeReloaded')),
      ]);
      pushSettingsNotice(t('app.backendRuntimeReloadedAndRefreshed'), 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.runtimeReloadFailed', { error: message }), 'error');
    } finally {
      setRuntimeReloadLoading(false);
    }
  };

  const handleApplyRuntimeProviders = async () => {
    setProviderConfigLoading(true);
    try {
      const result = runtimeProviderConfig.credential_mode === 'backend_env_only'
        ? await clearRuntimeProviders()
        : await updateRuntimeProviders(runtimeProviderConfig);
      setRuntimeProviderState(result);
      await handleRefreshRuntime();
      if (result.models.default) {
        setSelectedModel(result.models.default);
      }
      pushSettingsNotice(
        runtimeProviderConfig.credential_mode === 'backend_env_only'
          ? t('app.runtimeOverridesCleared')
          : (result.message || t('app.runtimeProviderApplied')),
        'success',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.runtimeProviderFailed', { error: message }), 'error');
    } finally {
      setProviderConfigLoading(false);
    }
  };

  const handleApplyRuntimeToolPolicy = async () => {
    setToolPolicyLoading(true);
    try {
      const result = await updateRuntimeToolPolicy({
        enabled: settings.toolPolicyEnabled,
        default_action: settings.toolPolicyDefaultAction,
        tool_actions: parsePolicyRulesText(settings.toolPolicyToolRules),
        server_actions: parsePolicyRulesText(settings.toolPolicyServerRules),
        system_actions: parsePolicyRulesText(settings.toolPolicySystemRules),
        deny_risky_write_paths: settings.toolPolicyDenyRiskyWritePaths,
      });
      setRuntimeToolPolicy(result);
      await handleRefreshRuntime();
      pushSettingsNotice(
        settings.language === 'zh' ? '\u8fd0\u884c\u65f6\u5de5\u5177\u7b56\u7565\u5df2\u5e94\u7528\u3002' : 'Runtime tool policy applied.',
        'success',
      );
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u8fd0\u884c\u65f6\u5de5\u5177\u7b56\u7565\u66f4\u65b0\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Runtime tool policy update failed: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    } finally {
      setToolPolicyLoading(false);
    }
  };

  const handleApplyRuntimeAutoToolRouting = async () => {
    try {
      const result = await updateRuntimeAutoToolRouting({
        mode: settings.autoToolRoutingMode,
      });
      setRuntimeAutoToolRouting(result);
      await handleRefreshRuntime();
      pushSettingsNotice(
        settings.language === 'zh'
          ? '\u81ea\u52a8\u5de5\u5177\u8def\u7531\u6a21\u5f0f\u5df2\u5e94\u7528\u3002'
          : 'Auto tool routing mode applied.',
        'success',
      );
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u81ea\u52a8\u5de5\u5177\u8def\u7531\u66f4\u65b0\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Auto tool routing update failed: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    }
  };

  const handleCheckProviderConnectivity = async (
    provider: 'siliconflow' | 'openrouter',
    config: RuntimeProviderConfig,
  ): Promise<ProviderConnectivityResult> => checkRuntimeProviderConnectivity({
    provider,
    api_key: provider === 'openrouter' ? config.openrouter_api_key : config.siliconflow_api_key,
    base_url: provider === 'openrouter' ? config.openrouter_base_url : config.siliconflow_base_url,
  });

  const handleResetRuntimeProviderForm = () => {
    const defaults = resetRuntimeProviderConfig();
    setRuntimeProviderConfig(defaults);
    pushSettingsNotice(t('app.runtimeProviderReset'), 'success');
  };

  const loadMcpConfigState = useCallback(async () => {
    setMcpConfigLoading(true);
    try {
      await syncSupplementalRuntimeState();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpConfigLoadFailed', { error: message }), 'error');
    } finally {
      setMcpConfigLoading(false);
    }
  }, [pushSettingsNotice, syncSupplementalRuntimeState, t]);

  const loadOnboardingAudit = useCallback(async () => {
    setOnboardingAuditLoading(true);
    try {
      const workspaceRoot = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
      onboardingWorkspaceScopeRef.current = workspaceRoot;
      const audit = await getMcpToolOnboardingAudit(workspaceRoot);
      setOnboardingAudit(audit);
      setOnboardingRun((prev) => {
        if (!prev) {
          return prev;
        }
        const resultWorkspaceRoot = String(prev.workspace_mcp?.workspace_root || '').trim();
        if (resultWorkspaceRoot !== workspaceRoot) {
          return null;
        }
        return prev;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpRefreshFailed', { error: message }), 'warning');
    } finally {
      setOnboardingAuditLoading(false);
    }
  }, [pushSettingsNotice, settings.enableWorkspaceContext, settings.workspaceContextRoot, t]);

  const runOnboardingAuditSelfTests = useCallback(async () => {
    setOnboardingRunLoading(true);
    try {
      const workspaceRoot = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
      onboardingWorkspaceScopeRef.current = workspaceRoot;
      const result = await runMcpToolOnboardingSelfTests({
        execute_safe_only: true,
        max_tools: 50,
        workspace_root: workspaceRoot,
      });
      setOnboardingRun(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpRefreshFailed', { error: message }), 'warning');
    } finally {
      setOnboardingRunLoading(false);
    }
  }, [pushSettingsNotice, settings.enableWorkspaceContext, settings.workspaceContextRoot, t]);

  const runOnboardingGate = useCallback(async () => {
    setOnboardingGateLoading(true);
    setOnboardingAuditLoading(true);
    setOnboardingRunLoading(true);
    try {
      const workspaceRoot = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
      onboardingWorkspaceScopeRef.current = workspaceRoot;
      const audit = await getMcpToolOnboardingAudit(workspaceRoot);
      setOnboardingAudit(audit);
      const result = await runMcpToolOnboardingSelfTests({
        execute_safe_only: true,
        max_tools: 50,
        workspace_root: workspaceRoot,
      });
      setOnboardingRun(result);
      await syncSupplementalRuntimeState();
      const failed = result.summary.failed || 0;
      const gateFailed = result.summary.gate_failed || 0;
      if (failed > 0 || gateFailed > 0) {
        pushSettingsNotice(
          settings.language === 'zh'
            ? `MCP \u56de\u5f52\u68c0\u67e5\u5b8c\u6210\uff1a\u901a\u8fc7 ${result.summary.passed}\uff0c\u5931\u8d25 ${failed}\uff0c\u95e8\u7981\u5931\u8d25 ${gateFailed}\u3002`
            : `MCP regression check finished: ${result.summary.passed} passed, ${failed} failed, ${gateFailed} gate failures.`,
          'warning',
        );
      } else {
        pushSettingsNotice(
          settings.language === 'zh'
            ? `MCP \u56de\u5f52\u68c0\u67e5\u901a\u8fc7\uff1a${result.summary.passed} \u4e2a\u5b89\u5168\u6700\u5c0f\u81ea\u6d4b\u901a\u8fc7\u3002`
            : `MCP regression check passed: ${result.summary.passed} safe minimal self-tests passed.`,
          'success',
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpRefreshFailed', { error: message }), 'warning');
    } finally {
      setOnboardingAuditLoading(false);
      setOnboardingRunLoading(false);
      setOnboardingGateLoading(false);
    }
  }, [pushSettingsNotice, settings.enableWorkspaceContext, settings.language, settings.workspaceContextRoot, syncSupplementalRuntimeState, t]);

  const handleMcpConfigFormChange = (patch: Partial<MCPServerConfigForm>) => {
    setMcpConfigForm((prev) => ({ ...prev, ...patch }));
  };

  const handleMcpConfigNew = () => {
    setMcpConfigForm(createEmptyMcpServerForm());
    pushSettingsNotice(t('app.mcpReadyForNewServer'), 'info');
  };

  const handleMcpConfigEdit = (item: MCPServerConfigItem) => {
    if (!item.editable) {
      pushSettingsNotice(t('app.mcpProtectedServer', { name: item.name }), 'warning');
      return;
    }
    setMcpConfigForm(mapConfigItemToForm(item));
    pushSettingsNotice(t('app.mcpEditingServer', { name: item.name }), 'info');
  };

  const handleMcpConfigSave = async () => {
    const parseEnvText = (value: string) => {
      const env: Record<string, string> = {};
      value
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .forEach((line) => {
          const separatorIndex = line.indexOf('=');
          if (separatorIndex <= 0) {
            throw new Error(`Invalid env line: ${line}`);
          }
          const key = line.slice(0, separatorIndex).trim();
          const envValue = line.slice(separatorIndex + 1);
          env[key] = envValue;
        });
      return env;
    };

    setMcpConfigSaving(true);
    try {
      const payload = {
        name: mcpConfigForm.name.trim(),
        description: mcpConfigForm.description.trim(),
        mode: mcpConfigForm.mode,
        disabled: mcpConfigForm.disabled,
        command: mcpConfigForm.mode === 'stdio' ? mcpConfigForm.command.trim() : undefined,
        args:
          mcpConfigForm.mode === 'stdio'
            ? mcpConfigForm.argsText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
            : undefined,
        env: mcpConfigForm.mode === 'stdio' ? parseEnvText(mcpConfigForm.envText) : undefined,
        url: mcpConfigForm.mode === 'remote' ? mcpConfigForm.url.trim() : undefined,
        transport: mcpConfigForm.mode === 'remote' ? mcpConfigForm.transport.trim() : undefined,
        timeout: Number(mcpConfigForm.timeout) || DEFAULT_MCP_SERVER_TIMEOUT,
      } as const;

      const result = await saveMcpConfig(payload);
      await handleRefreshRuntime();
      setMcpConfigForm(createEmptyMcpServerForm());
      pushSettingsNotice(
        result.reload_ok
          ? t('app.mcpSavedReloaded', { name: payload.name })
          : t('app.mcpSavedWithIssues', { name: payload.name }),
        result.reload_ok ? 'success' : 'warning',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpSaveFailed', { error: message }), 'error');
    } finally {
      setMcpConfigSaving(false);
    }
  };

  const handleMcpConfigDelete = async (serverName: string) => {
    setMcpConfigDeleting(serverName);
    try {
      const result = await deleteMcpConfig(serverName);
      await handleRefreshRuntime();
      if (mcpConfigForm.name === serverName) {
        setMcpConfigForm(createEmptyMcpServerForm());
      }
      pushSettingsNotice(
        result.reload_ok
          ? t('app.mcpDeletedReloaded', { name: serverName })
          : t('app.mcpDeletedWithIssues', { name: serverName }),
        result.reload_ok ? 'success' : 'warning',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushSettingsNotice(t('app.mcpDeleteFailed', { error: message }), 'error');
    } finally {
      setMcpConfigDeleting(null);
    }
  };

  const registerAgentTaskForMessage = useCallback(async (
    goal: string,
    attachments: ChatAttachment[],
  ) => {
    if (!settings.agentModeEnabled) {
      return;
    }
    try {
      const workspaceRoot = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
      await createAgentTask({
        goal,
        client_id: clientId,
        workspace_root: workspaceRoot,
        attachments,
        skill_ids: settings.enabledSkillIds,
        mode: settings.agentModeProfile,
      });
      setMessages((prev) => [
        ...prev,
        {
          id: `agent-created-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          type: 'system',
          content: settings.language === 'zh'
            ? '已为当前请求登记 Agent 任务。'
            : 'An agent task has been registered for this request.',
          timestamp: new Date().toISOString(),
          metadata: {
            agent_event: {
              kind: 'task_created',
              task_id: `pending-${Date.now()}`,
              title: settings.language === 'zh' ? 'Agent 任务已创建' : 'Agent task created',
              summary: settings.language === 'zh'
                ? '系统已开始为这条消息跟踪任务执行。'
                : 'The system has started tracking an agent task for this message.',
              status: 'running',
              mode: settings.agentModeProfile,
              goal,
            },
          },
        },
      ]);
      if (showTaskCenter) {
        await refreshRuntimeTasks();
      }
    } catch (error) {
      console.error('Failed to start agent task:', error);
      pushSettingsNotice(
        settings.language === 'zh'
          ? `Agent \u4efb\u52a1\u542f\u52a8\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Agent task start failed: ${error instanceof Error ? error.message : String(error)}`,
        'warning',
      );
    }
  }, [
    clientId,
    pushSettingsNotice,
    refreshRuntimeTasks,
    setMessages,
    settings.agentModeEnabled,
    settings.agentModeProfile,
    settings.enableWorkspaceContext,
    settings.language,
    settings.workspaceContextRoot,
    showTaskCenter,
  ]);
  const handleCancelAgentTask = useCallback(async (taskId: string) => {
    try {
      await cancelAgentTask(taskId);
      await refreshRuntimeTasks();
      pushSettingsNotice(
        settings.language === 'zh' ? 'Agent \u4efb\u52a1\u5df2\u53d6\u6d88\u3002' : 'Agent task canceled.',
        'info',
      );
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u53d6\u6d88 Agent \u4efb\u52a1\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Failed to cancel agent task: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    }
  }, [pushSettingsNotice, refreshRuntimeTasks, settings.language]);

  const handleOpenTaskReplay = useCallback(async (taskId: string) => {
    try {
      const replay = await getAgentTaskReplay(taskId, 200);
      setSelectedTaskReplayId(taskId);
      setSelectedTaskReplayEvents(replay.events || []);
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u52a0\u8f7d\u4efb\u52a1\u56de\u653e\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Failed to load task replay: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    }
  }, [pushSettingsNotice, settings.language]);

  const handleOpenSystemApproval = useCallback((approval: SystemOperationApproval) => {
    setSelectedSystemApproval(approval);
  }, []);

  const handleApproveSystemOperation = useCallback(async (note: string) => {
    if (!selectedSystemApproval) {
      return;
    }
    setSystemApprovalSubmitting(true);
    try {
      await approveAgentOperation(selectedSystemApproval.task_id, selectedSystemApproval.approval_id, {
        client_id: clientId,
        workspace_root: selectedSystemApproval.workspace_root || (settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : ''),
        attachments: uploadedAttachmentsForPlan,
        note,
      });
      setSelectedSystemApproval(null);
      await refreshRuntimeTasks();
      await handleOpenTaskReplay(selectedSystemApproval.task_id);
      pushSettingsNotice(
        settings.language === 'zh'
          ? '\u7cfb\u7edf\u64cd\u4f5c\u5df2\u6279\u51c6\uff0cAgent \u5c06\u7ee7\u7eed\u6267\u884c\u3002'
          : 'System operation approved. The agent will continue.',
        'success',
      );
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u5ba1\u6279\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Approval failed: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    } finally {
      setSystemApprovalSubmitting(false);
    }
  }, [
    clientId,
    handleOpenTaskReplay,
    pushSettingsNotice,
    refreshRuntimeTasks,
    selectedSystemApproval,
    settings.enableWorkspaceContext,
    settings.language,
    settings.workspaceContextRoot,
    uploadedAttachmentsForPlan,
  ]);

  const handleRejectSystemOperation = useCallback(async (note: string) => {
    if (!selectedSystemApproval) {
      return;
    }
    setSystemApprovalSubmitting(true);
    try {
      await rejectAgentOperation(selectedSystemApproval.task_id, selectedSystemApproval.approval_id, {
        client_id: clientId,
        workspace_root: selectedSystemApproval.workspace_root || (settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : ''),
        attachments: uploadedAttachmentsForPlan,
        note,
      });
      setSelectedSystemApproval(null);
      await refreshRuntimeTasks();
      await handleOpenTaskReplay(selectedSystemApproval.task_id);
      pushSettingsNotice(
        settings.language === 'zh'
          ? '\u7cfb\u7edf\u64cd\u4f5c\u5df2\u62d2\u7edd\uff0c\u76f8\u5173 Agent \u4efb\u52a1\u5df2\u505c\u6b62\u3002'
          : 'System operation rejected. The related agent task has stopped.',
        'info',
      );
    } catch (error) {
      pushSettingsNotice(
        settings.language === 'zh'
          ? `\u62d2\u7edd\u5ba1\u6279\u5931\u8d25\uff1a${error instanceof Error ? error.message : String(error)}`
          : `Failed to reject approval: ${error instanceof Error ? error.message : String(error)}`,
        'error',
      );
    } finally {
      setSystemApprovalSubmitting(false);
    }
  }, [
    clientId,
    handleOpenTaskReplay,
    pushSettingsNotice,
    refreshRuntimeTasks,
    selectedSystemApproval,
    settings.enableWorkspaceContext,
    settings.language,
    settings.workspaceContextRoot,
    uploadedAttachmentsForPlan,
  ]);

  useEffect(() => {
    void loadMcpConfigState();
  }, [loadMcpConfigState]);

  useEffect(() => {
    if (!showSettings) {
      return;
    }
    void loadOnboardingAudit();
  }, [loadOnboardingAudit, showSettings]);

  useEffect(() => {
    const workspaceRoot = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
    if (onboardingWorkspaceScopeRef.current === workspaceRoot) {
      return;
    }
    onboardingWorkspaceScopeRef.current = workspaceRoot;
    setOnboardingAudit((prev) => {
      const currentRoot = String(prev?.workspace_mcp?.workspace_root || '').trim();
      if (!prev || currentRoot === workspaceRoot) {
        return prev;
      }
      return null;
    });
    setOnboardingRun(null);
  }, [settings.enableWorkspaceContext, settings.workspaceContextRoot]);

  const handleLoadSession = (sessionMessages: ChatMessage[]) => {
    setMessages(sessionMessages);
    setAllowedDirectToolsForChat(new Set());
  };

  const handleClearCurrentSession = () => {
    clearCurrentChatWindow();
  };

  const directToolCalls = detectToolCalls(inputText.trim());
  const directToolCallReady = directToolCalls.length > 0;
  const primaryToolCall = directToolCalls[0] ?? null;
  const canSend =
    connectionStatus.status === 'connected'
    && ((providerReady && (inputText.trim().length > 0 || pendingAttachments.length > 0)) || directToolCallReady);
  const attachmentUploadEnabled = connectionStatus.status === 'connected';
  const inputPlaceholder =
    connectionStatus.status === 'connected'
      ? providerReady
        ? (
          webSearchEnabled
            ? (
              settings.language === 'zh'
                ? '\u5df2\u5f00\u542f\u8054\u7f51\u641c\u7d22\uff0c\u76f4\u63a5\u63d0\u95ee\u5373\u53ef\uff0c\u7cfb\u7edf\u4f1a\u4f18\u5148\u68c0\u7d22\u7f51\u9875\u518d\u603b\u7ed3\u56de\u7b54\u3002'
                : 'Web search is on. Ask naturally and the system will search the web first when helpful.'
            )
            : (
              settings.language === 'zh'
                ? '\u63cf\u8ff0\u4f60\u7684\u9700\u6c42\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u9009\u62e9\u5408\u9002\u7684\u5de5\u5177\u5e76\u7ed9\u51fa\u603b\u7ed3\u56de\u7b54\u3002'
                : 'Describe what you need. The system will choose tools when helpful and then answer normally.'
            )
        )
        : (
          settings.language === 'zh'
            ? '\u5f53\u524d\u672a\u914d\u7f6e\u6a21\u578b\u901a\u9053\uff0c\u4f46\u4ecd\u53ef\u4f7f\u7528 MCP \u5de5\u5177\u3002'
            : 'No model provider is configured yet, but MCP tools are still available.'
        )
      : t('app.waitingRealtime');
  const composerModeLabel =
    connectionStatus.status !== 'connected'
      ? t('app.connecting')
      : directToolCallReady
        ? t('app.toolCall')
        : webSearchEnabled
          ? (settings.language === 'zh' ? '\u8054\u7f51\u641c\u7d22' : 'Web search')
        : providerReady
          ? t('app.chatReady')
          : t('app.toolsOnly');
  const sendButtonLabel = directToolCallReady ? t('app.runTool') : t('app.sendMessage');
  const composerModeClassName =
    connectionStatus.status !== 'connected'
      ? 'border-slate-200 bg-slate-100 text-slate-700 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-200'
      : directToolCallReady
        ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200'
        : webSearchEnabled
          ? 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200'
        : providerReady
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200'
          : 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200';

  const statusSummary = useMemo(() => {
    if (!bootstrap) {
      return t('app.loadingSnapshot');
    }

    return [
      `${t('app.providers')}: ${providerReady ? t('health.ready') : t('health.missing')}`,
      `MCP: ${runtimeView.connectedServers.length}/${runtimeView.totalServers}`,
      `${t('app.tools')}: ${runtimeView.toolsCount}`,
      `TEM: ${runtimeView.temMode || bootstrap.tem.mode}`,
      pendingQueueSize > 0 ? `${t('app.pendingQueue')}: ${pendingQueueSize}` : '',
    ].filter(Boolean).join('  |  ');
  }, [bootstrap, pendingQueueSize, providerReady, runtimeView, t]);

  useEffect(() => {
    if (!settings.agentModeEnabled) {
      lastAgentTaskStateRef.current.clear();
      return;
    }

    const nextSnapshot = new Map<string, string>();
    agentTasks.forEach((task) => {
      const summary = summarizeAgentTaskEvent(task, settings.language, pendingSystemApprovals);
      const stateKey = [
        task.status,
        summary.kind,
        summary.stepTitle || '',
        summary.approvalId || '',
        summary.counts?.completed_steps || 0,
        summary.counts?.total_steps || 0,
      ].join('|');
      nextSnapshot.set(task.task_id, stateKey);

      if (lastAgentTaskStateRef.current.get(task.task_id) === stateKey) {
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: `agent-event-${task.task_id}-${Date.now()}`,
          type: 'system',
          content: summary.summary,
          timestamp: new Date().toISOString(),
          metadata: {
            agent_event: {
              kind: summary.kind,
              task_id: task.task_id,
              title: summary.title,
              summary: summary.summary,
              status: task.status,
              mode: task.mode,
              goal: task.goal,
              step_title: summary.stepTitle,
              approval_id: summary.approvalId,
              approval_action: summary.approvalAction,
              risk_level: summary.riskLevel,
              counts: summary.counts,
            },
            action_event: {
              action_id: `agent-task-${task.task_id}`,
              stage: summary.kind,
              status:
                summary.kind === 'task_completed'
                  ? 'success'
                  : summary.kind === 'task_failed' || summary.kind === 'task_cancelled'
                    ? 'failed'
                    : summary.kind === 'approval_needed'
                      ? 'blocked'
                      : 'running',
              title: summary.title,
              summary: summary.summary,
              source_plane: 'agent',
              target: {
                server: 'agent',
                tool: summary.stepTitle || task.mode || 'task',
              },
            },
          },
        },
      ]);
    });

    if (!selectedSystemApproval) {
      const firstPendingApproval = pendingSystemApprovals.find((approval) => approval.status === 'pending');
      if (firstPendingApproval) {
        setSelectedSystemApproval(firstPendingApproval);
      }
    }

    lastAgentTaskStateRef.current = nextSnapshot;
  }, [agentTasks, pendingSystemApprovals, selectedSystemApproval, setMessages, settings.agentModeEnabled, settings.language]);

  const composerHintText =
    connectionStatus.status !== 'connected'
      ? t('app.waitingBackend')
      : directToolCallReady && primaryToolCall
        ? t('app.directToolCall', { server: primaryToolCall.serverName, tool: primaryToolCall.toolName })
        : pendingAttachments.length > 0
          ? t('app.pendingAttachmentsHint', { count: pendingAttachments.length })
        : providerReady
          ? (
            settings.language === 'zh'
              ? '\u76f4\u63a5\u7528\u81ea\u7136\u8bed\u8a00\u63d0\u95ee\u5373\u53ef\uff0c\u5de5\u5177\u4f1a\u5728\u9700\u8981\u65f6\u81ea\u52a8\u8c03\u7528\u3002'
              : 'Ask naturally. Tools will be called automatically when needed.'
          )
          : t('app.noModelProviderToolsOnly');
  const newChatButtonLabel = settings.language === 'zh' ? '\u65b0\u804a\u5929' : 'New chat';
  const clearCurrentWindowLabel = settings.language === 'zh' ? '\u4ec5\u6e05\u7a7a\u5f53\u524d\u7a97\u53e3' : 'Clear current window only';
  const newChatMenuLabel = settings.language === 'zh' ? '\u65b0\u804a\u5929\u9009\u9879' : 'New chat options';
  const newChatMenuHint = settings.language === 'zh'
    ? '\u5f52\u6863\u5f53\u524d\u5bf9\u8bdd\u5e76\u5f00\u542f\u5168\u65b0\u4f1a\u8bdd'
    : 'Archive the current conversation and start a fresh session';
  const clearCurrentWindowHint = settings.language === 'zh'
    ? '\u53ea\u6e05\u7a7a\u5f53\u524d\u7a97\u53e3\u5185\u5bb9\uff0c\u4fdd\u7559\u540e\u7aef\u4f1a\u8bdd\u4e0a\u4e0b\u6587'
    : 'Only clear the visible window and keep the backend session context';


  return (
    <I18nProvider settings={settings}>
      <div className="flex h-screen flex-col bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.10),_transparent_30%),radial-gradient(circle_at_top_right,_rgba(16,185,129,0.12),_transparent_32%),linear-gradient(180deg,#f5f7f2_0%,#eef4f8_48%,#edf3ed_100%)] dark:bg-[linear-gradient(180deg,#0f172a_0%,#111827_100%)]">
      <header className="relative z-40 mx-4 mt-4 rounded-[28px] border border-white/40 bg-white/80 px-6 py-5 shadow-2xl backdrop-blur-xl dark:border-gray-700/40 dark:bg-gray-800/80">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center space-x-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-r from-sky-500 via-cyan-500 to-emerald-500 text-white shadow-lg">
              <Brain className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('app.title')}</h1>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {t('app.subtitle')}
              </p>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{statusSummary}</p>
            </div>
          </div>

          <div className="flex flex-1 items-center justify-end gap-3">
            <ConnectionIndicator status={connectionStatus.status} />
            <div className="w-full max-w-md">
              <ModelSelector
                selectedModel={selectedModel}
                onModelChange={handleModelChange}
                disabled={connectionStatus.status !== 'connected' || bootstrapLoading}
                models={bootstrap?.models.available}
              />
            </div>
            <div className="relative" ref={newChatMenuRef}>
              <div className="inline-flex overflow-hidden rounded-2xl border border-white/30 bg-white/80 shadow-sm dark:border-gray-700/40 dark:bg-gray-700/80">
                <button
                  type="button"
                  onClick={handleStartNewChat}
                  className="inline-flex items-center gap-2 px-4 py-3 text-gray-700 transition hover:bg-white dark:text-gray-200 dark:hover:bg-gray-700"
                  title={newChatButtonLabel}
                  aria-label={newChatButtonLabel}
                >
                  <Plus className="h-5 w-5" />
                  <span className="hidden text-sm font-medium lg:inline">{newChatButtonLabel}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setShowNewChatMenu((prev) => !prev)}
                  className="border-l border-white/40 px-3 py-3 text-gray-600 transition hover:bg-white dark:border-gray-700/60 dark:text-gray-300 dark:hover:bg-gray-700"
                  aria-label={newChatMenuLabel}
                  aria-haspopup="menu"
                  aria-expanded={showNewChatMenu}
                  title={newChatMenuLabel}
                >
                  <ChevronDown className={`h-4 w-4 transition ${showNewChatMenu ? 'rotate-180' : ''}`} />
                </button>
              </div>

              {showNewChatMenu && (
                <div
                  role="menu"
                  aria-label={newChatMenuLabel}
                  className="absolute right-0 top-full z-50 mt-2 w-72 rounded-3xl border border-slate-200/80 bg-white/95 p-2 shadow-2xl backdrop-blur dark:border-slate-700/70 dark:bg-slate-900/95"
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={handleStartNewChat}
                    className="flex w-full items-start gap-3 rounded-2xl px-3 py-3 text-left transition hover:bg-slate-100 dark:hover:bg-slate-800/90"
                  >
                    <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                      <Plus className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">{newChatButtonLabel}</div>
                      <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{newChatMenuHint}</p>
                    </div>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={handleClearCurrentWindowOnly}
                    className="flex w-full items-start gap-3 rounded-2xl px-3 py-3 text-left transition hover:bg-slate-100 dark:hover:bg-slate-800/90"
                  >
                    <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                      <Trash2 className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">{clearCurrentWindowLabel}</div>
                      <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{clearCurrentWindowHint}</p>
                    </div>
                  </button>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setShowHistory(true)}
              className="rounded-2xl border border-white/30 bg-white/80 p-3 text-gray-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-gray-200"
              title={t('app.chatHistory')}
            >
              <History className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => setShowTEMPanel(true)}
              className="relative rounded-2xl border border-white/30 bg-white/80 p-3 text-amber-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-amber-300"
              title={t('app.toolExecutionMemory')}
            >
              <BookOpen className="h-5 w-5" />
              {(temStats?.total_recipes ?? 0) > 0 && (
                <span className="absolute -right-1 -top-1 rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {temStats?.total_recipes}
                </span>
              )}
            </button>
            {showResearchPanels && (
              <>
                <button
                  type="button"
                  onClick={() => setShowMCPTools(true)}
                  className="rounded-2xl border border-white/30 bg-white/80 p-3 text-sky-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-sky-300"
                  title={t('app.mcpRuntimeCenter')}
                >
                  <Zap className="h-5 w-5" />
                </button>
                <button
                  type="button"
                  onClick={() => setShowHealthPanel(true)}
                  className="rounded-2xl border border-white/30 bg-white/80 p-3 text-emerald-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-emerald-300"
                  title={t('app.healthPanel')}
                >
                  <Activity className="h-5 w-5" />
                </button>
              </>
            )}
            {showTaskCenterEntry && (
              <button
                type="button"
                onClick={() => setShowTaskCenter(true)}
                className="relative rounded-2xl border border-white/30 bg-white/80 p-3 text-violet-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-violet-300"
                title={settings.language === 'zh' ? '\u4efb\u52a1\u4e2d\u5fc3' : 'Task Center'}
              >
                <ClipboardList className="h-5 w-5" />
                {hasActiveTaskSignals && (
                  <span className="absolute -right-1 -top-1 rounded-full bg-violet-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                    {pendingQueueSize + activeRuntimeRequestsCount + runningAgentTasks + pendingSystemApprovals.length}
                  </span>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={toggleDarkMode}
              className="rounded-2xl border border-white/30 bg-white/80 p-3 text-gray-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-gray-200"
              title={settings.dark_mode ? t('app.switchToLight') : t('app.switchToDark')}
            >
              {settings.dark_mode ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <button
              type="button"
              onClick={() => setShowSettings((prev) => !prev)}
              className="rounded-2xl border border-white/30 bg-white/80 p-3 text-gray-700 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-gray-200"
              title={t('app.settings')}
            >
              <Settings className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => {
                handleClearCurrentSession();
                clearMemory();
              }}
              className="rounded-2xl border border-red-200 bg-red-50 p-3 text-red-600 shadow-sm transition hover:bg-red-100 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
              title={t('app.clearChatAndMemory')}
            >
              <Trash2 className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      {showSettings && (
        <SettingsPanel
          settings={settings}
          onSettingsChange={handleSettingsChange}
          onClose={() => setShowSettings(false)}
          onResetLocalSettings={handleResetLocalSettings}
          availableTools={availableTools}
          runtimeView={runtimeView}
          bootstrap={bootstrap}
          selectedModel={selectedModel}
          connectionStatus={connectionStatus}
          onRefreshRuntime={handleRefreshRuntime}
          onTemModeChange={handleTemModeChange}
          onReloadRuntimeParams={handleReloadRuntimeParams}
          temModeLoading={temModeLoading}
          runtimeReloadLoading={runtimeReloadLoading}
          notice={settingsNotice}
          runtimeProviderConfig={runtimeProviderConfig}
          runtimeProviderState={runtimeProviderState}
          runtimeToolPolicy={runtimeToolPolicy}
          runtimeAutoToolRouting={runtimeAutoToolRouting}
          mcpConfigPath={mcpConfigPath}
          mcpConfigItems={mcpConfigItems}
          mcpConfigForm={mcpConfigForm}
          mcpConfigLoading={mcpConfigLoading}
          mcpConfigSaving={mcpConfigSaving}
          mcpConfigDeleting={mcpConfigDeleting}
          agentSkills={agentSkills}
          agentSkillRoots={bootstrap?.agent_skills?.roots || []}
          agentSkillFailed={bootstrap?.agent_skills?.failed || []}
          agentSkillsExternalConfig={agentSkillsExternalConfig}
          externalSkillDirsText={externalSkillDirsText}
          agentSkillsLoading={agentSkillsLoading}
          onReloadAgentSkills={handleReloadAgentSkills}
          onExternalSkillDirsTextChange={setExternalSkillDirsText}
          onApplyExternalSkillDirs={handleApplyExternalSkillDirs}
          onRuntimeProviderConfigChange={setRuntimeProviderConfig}
          onResetRuntimeProviderConfig={handleResetRuntimeProviderForm}
          onApplyRuntimeProviders={handleApplyRuntimeProviders}
          onApplyRuntimeToolPolicy={handleApplyRuntimeToolPolicy}
          onApplyRuntimeAutoToolRouting={handleApplyRuntimeAutoToolRouting}
          onCheckProviderConnectivity={handleCheckProviderConnectivity}
          providerConfigLoading={providerConfigLoading}
          toolPolicyLoading={toolPolicyLoading}
          onRefreshMcpConfig={loadMcpConfigState}
          onRefreshOnboardingAudit={loadOnboardingAudit}
          onRunOnboardingSelfTests={runOnboardingAuditSelfTests}
          onRunOnboardingGate={runOnboardingGate}
          onMcpConfigFormChange={handleMcpConfigFormChange}
          onMcpConfigNew={handleMcpConfigNew}
          onMcpConfigEdit={handleMcpConfigEdit}
          onMcpConfigSave={handleMcpConfigSave}
          onMcpConfigDelete={handleMcpConfigDelete}
          workspaceAgentProfile={workspaceAgentProfile}
          workspaceMcpState={connectionStatus.workspace_mcp || runtimeSnapshot?.workspace_mcp || null}
          onboardingAudit={onboardingAudit}
          onboardingRun={onboardingRun}
          onboardingAuditLoading={onboardingAuditLoading || onboardingGateLoading}
          onboardingRunLoading={onboardingRunLoading || onboardingGateLoading}
        />
      )}

      {settingsNotice && (
        <div className="px-4 pt-3 sm:px-5 lg:px-8 xl:px-10">
          <div className="mx-auto w-full max-w-[1500px]">
            <NoticeBanner
              tone={settingsNoticeTone}
              message={settingsNotice}
              onClose={() => setSettingsNotice(null)}
            />
          </div>
        </div>
      )}
      <AgentRuntimeBar
        visible={showAgentStatusBanner}
        language={settings.language}
        agentModeEnabled={settings.agentModeEnabled}
        agentModeProfile={settings.agentModeProfile}
        workspaceAgentProfile={workspaceAgentProfile}
        workspaceMcpState={connectionStatus.workspace_mcp || runtimeSnapshot?.workspace_mcp || null}
        skillRuntime={connectionStatus.skill_runtime || runtimeSnapshot?.skill_runtime || workspaceAgentProfile?.skill_runtime || null}
        agentCapabilities={agentCapabilities}
        availableTools={availableTools}
        sessionAllowedServers={settings.sessionAllowMCPs}
        runningAgentTasks={runningAgentTasks}
        activeRuntimeRequestsCount={activeRuntimeRequestsCount}
        pendingApprovalsCount={pendingSystemApprovals.length}
        completedAgentTasks={completedAgentTasks}
        showCompletedCount={showResearchPanels}
        onOpenTasks={() => setShowTaskCenter(true)}
      />

      <ChatHistory
        isOpen={showHistory}
        clientId={clientId}
        onClose={() => setShowHistory(false)}
        onLoadSession={handleLoadSession}
        currentMessages={messages}
        onClearCurrentSession={handleClearCurrentSession}
      />

      {showMCPTools && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6 backdrop-blur-sm">
          <div className="h-[88vh] w-[92vw] max-w-7xl overflow-hidden rounded-[32px] border border-white/20 bg-white/90 shadow-2xl dark:border-gray-700/40 dark:bg-gray-900/90">
            <MCPToolsPanel
              onToolCall={handleMCPToolCall}
              onResourceRead={handleMCPResourceRead}
              onPromptGet={handleMCPPromptGet}
              onClose={() => setShowMCPTools(false)}
            />
          </div>
        </div>
      )}

      <TEMPanel
        isOpen={showTEMPanel}
        onClose={() => setShowTEMPanel(false)}
        clientId={clientId}
        temStats={temStats}
        recipes={temRecipes}
        guards={temGuards}
        onRefresh={() => {
          requestTEMStatus();
          requestRecipes();
          requestGuards();
        }}
      />

      <HealthPanel
        isOpen={showHealthPanel}
        onClose={() => setShowHealthPanel(false)}
      />

      <TaskCenter
        isOpen={showTaskCenter}
        onClose={() => setShowTaskCenter(false)}
        loading={taskCenterLoading}
        pendingQueueSize={pendingQueueSize}
        pendingOutboundRequests={pendingOutboundRequests}
        tasks={runtimeTasks}
        agentTasks={agentTasks}
        pendingApprovals={pendingSystemApprovals}
        selectedTaskReplay={selectedTaskReplayEvents}
        selectedTaskId={selectedTaskReplayId}
        onRefresh={refreshRuntimeTasks}
        onCancelAgentTask={handleCancelAgentTask}
        onOpenTaskReplay={handleOpenTaskReplay}
        onOpenApproval={handleOpenSystemApproval}
        onCancelQueuedRequest={(requestId: string) => {
          const canceled = cancelQueuedRequest(requestId);
          if (canceled) {
            pushSettingsNotice(
              settings.language === 'zh' ? '\u672c\u5730\u6392\u961f\u8bf7\u6c42\u5df2\u53d6\u6d88\u3002' : 'Queued local request canceled.',
              'info',
            );
          }
        }}
        onRetryRequest={(requestId: string) => {
          const targetMessage = [...messages]
            .reverse()
            .find((message) => message.request_id === requestId && message.retryable);
          if (targetMessage) {
            handleRetryMessage(targetMessage);
            setShowTaskCenter(false);
            return;
          }
          pushSettingsNotice(
            settings.language === 'zh'
              ? '\u6ca1\u6709\u627e\u5230\u53ef\u91cd\u8bd5\u7684\u539f\u59cb\u6d88\u606f\uff0c\u8bf7\u5728\u6d88\u606f\u5217\u8868\u4e2d\u624b\u52a8\u68c0\u67e5\u3002'
              : 'No retryable source message was found. Check the message list manually.',
            'warning',
          );
        }}
        language={settings.language}
      />

      <SystemOperationApprovalModal
        isOpen={Boolean(selectedSystemApproval)}
        approval={selectedSystemApproval}
        language={settings.language}
        submitting={systemApprovalSubmitting}
        onApprove={handleApproveSystemOperation}
        onReject={handleRejectSystemOperation}
        onClose={() => setSelectedSystemApproval(null)}
      />

      <div className="flex-1 overflow-y-auto px-3 py-5 sm:px-5 lg:px-8 xl:px-10">
        <div className="mx-auto w-full max-w-[1500px]">
          {messages.length === 0 && (
            <div className="py-16 text-center">
              <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-r from-sky-500 to-emerald-500 text-white shadow-xl">
                <Bot className="h-9 w-9" />
              </div>
              <h2 className="mt-6 text-3xl font-bold text-gray-800 dark:text-white">{t('app.memoryFirstTitle')}</h2>
              <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-gray-600 dark:text-gray-400">
                {t('app.memoryFirstBody')}
              </p>
            </div>
          )}

          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onRetry={message.retryable ? () => handleRetryMessage(message) : undefined}
              showAdvancedDebugTraces={settings.showAdvancedDebugTraces}
            />
          ))}

          {isTyping && (
            <div className="mb-6 flex justify-start">
              <div className="flex w-full max-w-[1280px] items-start space-x-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-lg">
                  <Bot className="h-5 w-5" />
                </div>
                <div className="rounded-3xl border border-white/30 bg-white/85 px-5 py-4 shadow-lg backdrop-blur-sm dark:border-gray-700/40 dark:bg-gray-800/85">
                  <TypingIndicator />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {memoryStats && (
        <div className="px-3 pb-2 sm:px-5 lg:px-8 xl:px-10">
          <div className="mx-auto w-full max-w-[1420px] rounded-2xl border border-sky-200/50 bg-sky-50/80 px-4 py-3 text-xs text-sky-800 backdrop-blur-sm dark:border-sky-800/50 dark:bg-sky-900/20 dark:text-sky-200">
            <div className="flex flex-wrap items-center gap-4">
              <span className="inline-flex items-center space-x-1 font-medium">
                <Brain className="h-4 w-4" />
                <span>{t('app.contextMemory')}</span>
              </span>
              <span>{t('app.messages')} {memoryStats.total_messages}</span>
              <span>{t('app.sent')} {memoryStats.messages_sent}</span>
              <span>{t('app.compressedTokens')} {memoryStats.compressed_tokens}</span>
              {memoryStats.compression_ratio > 1.1 && <span>{t('app.compression')} {memoryStats.compression_ratio}x</span>}
              {memoryStats.has_summary && <span>{t('app.summaryEnabled')}</span>}
              {memoryStats.long_term_facts > 0 && <span>{t('app.facts')} {memoryStats.long_term_facts}</span>}
            </div>
          </div>
        </div>
      )}

      <div className="px-3 pb-4 sm:px-5 lg:px-8 xl:px-10">
        <div className="mx-auto w-full max-w-[1420px] rounded-[26px] border border-slate-200/70 bg-white/95 p-2 shadow-[0_12px_32px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-gray-700/60 dark:bg-gray-900/90">
          {pendingAttachments.length > 0 && (
            <div className="mb-2 flex flex-col gap-2 rounded-2xl border border-slate-200/90 bg-slate-50/95 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/70">
              {attachmentExecutionPlan.items.length > 0 && (
                <div className="rounded-2xl border border-sky-200/70 bg-sky-50/80 px-3 py-2 text-xs text-sky-800 dark:border-sky-800/40 dark:bg-sky-950/20 dark:text-sky-200">
                  <div className="font-medium">{attachmentExecutionPlan.summary_label}</div>
                  <div className="mt-1 opacity-80">
                    {settings.language === 'zh'
                      ? '\u53d1\u9001\u65f6\u4f1a\u6309\u4e0b\u9762\u7684\u9644\u4ef6\u901a\u9053\u89c4\u5212\u51b3\u5b9a\u54ea\u4e9b\u8fdb\u5165\u6a21\u578b\uff0c\u54ea\u4e9b\u4ec5\u4f5c\u4e3a\u5de5\u5177\u5b9a\u4f4d\u4f9d\u636e\u3002'
                      : 'This turn will use the attachment plan below to decide which files enter model context and which stay as tool-grounding inputs.'}
                  </div>
                </div>
              )}
              {pendingAttachments.map((attachment) => (
                <div key={attachment.id} data-testid="pending-attachment-row" className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-xl border border-white bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
                      {attachment.previewUrl ? (
                        <img src={attachment.previewUrl} alt={t('message.uploadedImageAlt')} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-slate-400 dark:text-gray-500">
                          {isImageFile(attachment.file) ? <Image className="h-5 w-5" /> : <Paperclip className="h-5 w-5" />}
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-900 dark:text-white">{attachment.file.name}</div>
                      <div className="text-xs text-slate-500 dark:text-gray-400">
                        {formatFileSize(attachment.file.size)}
                      </div>
                      <div className={`mt-2 inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium ${attachmentBadgeClassName(attachment.uploadedAttachment, attachment.uploadState)}`}>
                        {getAttachmentUnderstandingLabel(attachment.uploadedAttachment, attachment.uploadState, settings.language)}
                      </div>
                          {attachment.uploadedAttachment && (() => {
                            const planItem = attachmentPlanByFilename.get(
                              attachment.uploadedAttachment.original_filename || attachment.uploadedAttachment.filename,
                            );
                            if (!planItem) {
                              return null;
                            }
                            return (
                              <div className="mt-2">
                                <span className="inline-flex items-center rounded-full border border-slate-200 bg-white/90 px-2.5 py-1 text-[11px] font-medium text-slate-700 dark:border-gray-700 dark:bg-gray-900/70 dark:text-gray-200">
                                  {settings.language === 'zh' ? '\u672c\u8f6e\u901a\u9053' : 'This turn'}: {getAttachmentTransportRoleLabel(planItem.transport_role, settings.language)}
                                </span>
                              </div>
                            );
                          })()}
                          {attachment.uploadedAttachment && (
                        <div className="mt-2 space-y-1 text-xs text-slate-600 dark:text-gray-300">
                          <div>
                            {settings.language === 'zh' ? '\u89e3\u6790\u72b6\u6001' : 'Parse status'}: {attachment.uploadedAttachment.parse_status || 'unknown'}
                            {attachment.uploadedAttachment.parser ? ` | parser=${attachment.uploadedAttachment.parser}` : ''}
                          </div>
                          {typeof attachment.uploadedAttachment.full_text_chars === 'number' && (
                            <div>
                              {settings.language === 'zh' ? '\u539f\u59cb\u53ef\u63d0\u53d6\u5b57\u7b26' : 'Extracted chars'}: {attachment.uploadedAttachment.full_text_chars}
                              {typeof attachment.uploadedAttachment.visible_text_chars === 'number'
                                ? ` | ${settings.language === 'zh' ? '\u6a21\u578b\u53ef\u89c1\u5b57\u7b26' : 'Visible to model'}: ${attachment.uploadedAttachment.visible_text_chars}`
                                : ''}
                            </div>
                          )}
                          {attachment.uploadedAttachment.preview_truncated && (
                            <div className="text-amber-700 dark:text-amber-300">
                              {settings.language === 'zh'
                                ? '\u5f53\u524d\u663e\u793a\u7684\u662f\u622a\u65ad\u540e\u7684\u53ef\u89c1\u6587\u672c\uff0c\u6a21\u578b\u4e0d\u4f1a\u770b\u5230\u5b8c\u6574\u6b63\u6587\u3002'
                                : 'Visible text is truncated; the model will not see the full body.'}
                            </div>
                          )}
                          {attachment.uploadedAttachment.parse_error && (
                            <div className="text-amber-700 dark:text-amber-300">
                              {settings.language === 'zh' ? '\u539f\u56e0' : 'Reason'}: {attachment.uploadedAttachment.parse_error}
                            </div>
                          )}
                          {attachmentHasHiddenBodyText(attachment.uploadedAttachment) && (
                            <div className="rounded-xl border border-slate-200 bg-white/90 p-2 text-[11px] leading-5 text-slate-700 dark:border-gray-700 dark:bg-gray-900/70 dark:text-gray-200">
                              <div className="font-medium text-slate-500 dark:text-gray-400">
                                {getAttachmentBodyHiddenNotice(settings.language, 'composer')}
                              </div>
                            </div>
                          )}
                          {attachment.uploadedAttachment.is_image && !selectedModelSupportsImages && (
                            <div className="rounded-xl border border-amber-200 bg-amber-50/90 p-2 text-[11px] leading-5 text-amber-800 dark:border-amber-800/40 dark:bg-amber-950/20 dark:text-amber-200">
                              {settings.language === 'zh'
                                ? '\u5f53\u524d\u9009\u4e2d\u7684\u662f\u7eaf\u6587\u672c\u6a21\u578b\uff0c\u8fd9\u5f20\u56fe\u7247\u4f1a\u4f5c\u4e3a\u9644\u4ef6\u4fdd\u7559\uff0c\u4f46\u4e0d\u4f1a\u5728\u672c\u8f6e\u76f4\u63a5\u8fdb\u5165\u89c6\u89c9\u8f93\u5165\u3002\u5207\u6362\u5230 VL \u6216\u5176\u4ed6\u591a\u6a21\u6001\u6a21\u578b\u540e\uff0c\u6a21\u578b\u624d\u80fd\u76f4\u63a5\u770b\u56fe\u3002'
                                : 'The current model is text-only. This image stays attached, but it will not be sent as visual input on this turn. Switch to a VL or other multimodal model for direct image understanding.'}
                            </div>
                          )}
                          {!attachmentHasHiddenBodyText(attachment.uploadedAttachment) && attachment.uploadedAttachment.parse_status !== 'parsed' && (
                            <div className="text-slate-500 dark:text-gray-400">
                              {getAttachmentNoBodyContextNotice(settings.language)}
                            </div>
                          )}
                        </div>
                      )}
                      {attachment.uploadState === 'failed' && attachment.uploadError && (
                        <div className="mt-2 text-xs text-rose-600 dark:text-rose-300">
                          {settings.language === 'zh' ? '\u4e0a\u4f20\u5931\u8d25' : 'Upload failed'}: {attachment.uploadError}
                        </div>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeAttachment(attachment.id)}
                    className="rounded-xl px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-white hover:text-red-600 dark:text-gray-300 dark:hover:bg-gray-900/60 dark:hover:text-red-300"
                  >
                    {t('app.remove')}
                  </button>
                </div>
              ))}
            </div>
          )}

          <div
            className="rounded-[22px] border border-slate-200/90 bg-gradient-to-b from-slate-50/90 to-white transition duration-200 focus-within:border-sky-300 focus-within:bg-white focus-within:shadow-[0_0_0_3px_rgba(14,165,233,0.07)] dark:border-gray-700 dark:from-gray-900/55 dark:to-gray-950/35 dark:focus-within:border-sky-700 dark:focus-within:shadow-[0_0_0_3px_rgba(14,165,233,0.08)]"
            onDragOver={handleComposerDragOver}
            onDrop={handleComposerDrop}
          >
            <textarea
              ref={textareaRef}
              value={inputText}
              onChange={handleInputChange}
              onKeyDown={handleKeyPress}
              onPaste={handleComposerPaste}
              placeholder={inputPlaceholder}
              className="min-h-[60px] max-h-56 w-full resize-none rounded-[22px] bg-transparent px-4 py-2.5 text-[15px] leading-7 text-slate-900 outline-none placeholder:text-slate-400 dark:text-white dark:placeholder:text-gray-500"
              disabled={connectionStatus.status !== 'connected'}
              rows={1}
            />

            <div className="flex flex-col gap-2 border-t border-slate-200/80 px-3 py-2 dark:border-gray-700/70 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-gray-400">
                <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium ${composerModeClassName}`}>
                  {directToolCallReady ? <AtSign className="h-3.5 w-3.5" /> : <Zap className="h-3.5 w-3.5" />}
                  <span>{composerModeLabel}</span>
                </span>
                <span className="truncate rounded-full bg-slate-100/80 px-2.5 py-1 text-slate-500 dark:bg-gray-800/90 dark:text-gray-400">
                  {composerHintText}
                </span>
                {showResearchPanels && bootstrap && (
                  <span className="hidden rounded-full bg-slate-100/80 px-2.5 py-1 text-slate-500 dark:bg-gray-800/90 dark:text-gray-400 sm:inline">
                    {t('app.tools')} {bootstrap.mcp.tools_count}
                  </span>
                )}
                {showResearchPanels && <span className="hidden md:inline">{t('app.enterSend')}</span>}
                {showResearchPanels && <span className="hidden md:inline">{t('app.shiftEnter')}</span>}
              </div>

              <div className="flex items-center justify-end gap-2">
                <input
                  data-testid="attachment-input"
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={acceptedAttachmentExtensions.join(',')}
                  onChange={handleAttachmentSelect}
                  className="hidden"
                />

                <button
                  type="button"
                  onClick={() => setWebSearchEnabled((prev) => !prev)}
                  disabled={!providerReady || connectionStatus.status !== 'connected' || directToolCallReady}
                  className={`inline-flex h-9 w-9 items-center justify-center rounded-2xl border transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    webSearchEnabled
                      ? 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-300'
                      : 'border-transparent bg-transparent text-slate-600 hover:border-slate-200 hover:bg-white hover:text-sky-700 dark:text-gray-300 dark:hover:border-gray-700 dark:hover:bg-gray-800 dark:hover:text-sky-300'
                  }`}
                  title={settings.language === 'zh' ? '\u8054\u7f51\u641c\u7d22' : 'Web search'}
                  data-testid="web-search-toggle"
                >
                  <Globe className="h-4 w-4" />
                </button>

                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!attachmentUploadEnabled}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-2xl border border-transparent bg-transparent text-slate-600 transition hover:border-slate-200 hover:bg-white hover:text-sky-700 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-300 dark:hover:border-gray-700 dark:hover:bg-gray-800 dark:hover:text-sky-300"
                  title={t('app.addAttachment')}
                >
                  <Paperclip className="h-4 w-4" />
                </button>

                <button
                  type="button"
                  onClick={() => {
                    void handleSendMessage();
                  }}
                  disabled={!canSend}
                  className="inline-flex h-9 min-w-[106px] items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 text-sm font-semibold text-white shadow-[0_8px_18px_rgba(15,23,42,0.14)] transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-slate-900 dark:hover:bg-gray-100"
                  title={sendButtonLabel}
                >
                  <span className="hidden sm:inline">{sendButtonLabel}</span>
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {showToolSelector && (
        <ToolSelector
          position={toolSelectorPosition}
          onSelectTool={handleToolSelect}
          onClose={handleCloseToolSelector}
          searchQuery={toolSearchQuery}
          availableTools={availableTools}
        />
      )}

      <ToolConfirmModal
        isOpen={showToolConfirm}
        onConfirm={handleToolConfirm}
        onCancel={handleToolCancel}
        initialArgs={pendingToolCall?.initialArgs}
        suggestedFields={pendingToolCall?.suggestedFields || []}
        autoFillReasons={pendingToolCall?.autoFillReasons}
        attachments={pendingToolCall?.attachments || []}
        tool={
          pendingToolCall
            ? {
                server: pendingToolCall.tool.serverName,
                name: pendingToolCall.tool.toolName,
                display_name:
                  pendingToolCall.toolDetails?.display_name
                  || pendingToolCall.tool.toolName.replace(/_/g, ' '),
                description:
                  pendingToolCall.toolDetails?.description
                  || 'Detected an explicit tool-call syntax in the input. Confirm before executing it.',
                input_schema: pendingToolCall.toolDetails?.input_schema || {},
              }
            : null
        }
      />
      </div>
    </I18nProvider>
  );
};

export default ChatInterface;
