import { ChatMessage } from '../types';

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  timestamp: string;
  messageCount: number;
  clientId?: string;
  isAutoSaved?: boolean;
}

export const CHAT_CLIENT_ID_KEY = 'mcp_chat_client_id';
export const CHAT_CURRENT_SESSION_KEY = 'mcp_chat_current_session';
export const CHAT_SESSIONS_KEY = 'mcp_chat_sessions';

const isBrowser = typeof window !== 'undefined';
const DEFAULT_MAX_MESSAGES = 80;
const DEFAULT_MAX_ARRAY_ITEMS = 20;
const DEFAULT_MAX_OBJECT_KEYS = 24;
const DEFAULT_MAX_STRING_CHARS = 4000;
const DEFAULT_MAX_CONTENT_CHARS = 12000;
const DEFAULT_MAX_TOOL_TEXT_CHARS = 6000;
const DEFAULT_MAX_ATTACHMENTS = 8;
const DEFAULT_MAX_SESSIONS = 40;

type PersistenceLevel = 'default' | 'aggressive' | 'minimal';

type PersistenceLimits = {
  maxMessages: number;
  maxArrayItems: number;
  maxObjectKeys: number;
  maxStringChars: number;
  maxContentChars: number;
  maxToolTextChars: number;
  maxAttachments: number;
  maxSessions: number;
};

const PERSISTENCE_LIMITS: Record<PersistenceLevel, PersistenceLimits> = {
  default: {
    maxMessages: DEFAULT_MAX_MESSAGES,
    maxArrayItems: DEFAULT_MAX_ARRAY_ITEMS,
    maxObjectKeys: DEFAULT_MAX_OBJECT_KEYS,
    maxStringChars: DEFAULT_MAX_STRING_CHARS,
    maxContentChars: DEFAULT_MAX_CONTENT_CHARS,
    maxToolTextChars: DEFAULT_MAX_TOOL_TEXT_CHARS,
    maxAttachments: DEFAULT_MAX_ATTACHMENTS,
    maxSessions: DEFAULT_MAX_SESSIONS,
  },
  aggressive: {
    maxMessages: 50,
    maxArrayItems: 12,
    maxObjectKeys: 16,
    maxStringChars: 2000,
    maxContentChars: 6000,
    maxToolTextChars: 3000,
    maxAttachments: 5,
    maxSessions: 20,
  },
  minimal: {
    maxMessages: 20,
    maxArrayItems: 6,
    maxObjectKeys: 10,
    maxStringChars: 600,
    maxContentChars: 1500,
    maxToolTextChars: 900,
    maxAttachments: 3,
    maxSessions: 8,
  },
};

const isRecord = (value: unknown): value is Record<string, any> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const truncateText = (value: string, maxChars: number): string => {
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, Math.max(maxChars - 24, 0))}\n...[truncated ${value.length - maxChars} chars]`;
};

const sanitizeValue = (
  value: unknown,
  limits: PersistenceLimits,
  depth = 0,
): unknown => {
  if (typeof value === 'string') {
    return truncateText(value, limits.maxStringChars);
  }

  if (
    value === null
    || value === undefined
    || typeof value === 'number'
    || typeof value === 'boolean'
  ) {
    return value;
  }

  if (Array.isArray(value)) {
    const items = value
      .slice(0, limits.maxArrayItems)
      .map((item) => sanitizeValue(item, limits, depth + 1));
    if (value.length > limits.maxArrayItems) {
      items.push(`[${value.length - limits.maxArrayItems} more items truncated]`);
    }
    return items;
  }

  if (!isRecord(value)) {
    return truncateText(String(value), limits.maxStringChars);
  }

  if (depth >= 3) {
    return `[object truncated with ${Object.keys(value).length} keys]`;
  }

  const entries = Object.entries(value).slice(0, limits.maxObjectKeys);
  const nextObject = Object.fromEntries(
    entries.map(([key, item]) => [key, sanitizeValue(item, limits, depth + 1)]),
  );

  if (Object.keys(value).length > limits.maxObjectKeys) {
    nextObject.__truncated__ = `${Object.keys(value).length - limits.maxObjectKeys} keys omitted`;
  }

  return nextObject;
};

const sanitizeAttachment = (attachment: Record<string, any>, limits: PersistenceLimits) => ({
  filename: attachment.filename,
  original_filename: attachment.original_filename,
  file_path: attachment.file_path,
  url: attachment.url,
  size: attachment.size,
  mime_type: attachment.mime_type,
  is_image: attachment.is_image,
  parse_status: attachment.parse_status,
  parse_mode: attachment.parse_mode,
  parser: attachment.parser,
  full_text_chars: attachment.full_text_chars,
  visible_text_chars: attachment.visible_text_chars,
  preview_truncated: attachment.preview_truncated,
  parse_error: typeof attachment.parse_error === 'string'
    ? truncateText(attachment.parse_error, limits.maxStringChars)
    : attachment.parse_error,
});

const extractToolSummary = (
  metadata: Record<string, any>,
  limits: PersistenceLimits,
): Record<string, any> | null => {
  const toolEvidence = isRecord(metadata.tool_evidence) ? metadata.tool_evidence : null;
  const runTrace = isRecord(toolEvidence?.run_trace)
    ? toolEvidence?.run_trace
    : isRecord(metadata.run_trace)
      ? metadata.run_trace
      : null;

  if (!runTrace || runTrace.kind !== 'tool_call') {
    return null;
  }

  const resultSource = toolEvidence?.result ?? metadata.result;
  const argumentsSource = toolEvidence?.arguments ?? metadata.arguments ?? (isRecord(resultSource) ? resultSource.arguments : undefined);
  const inferredArguments = Array.isArray(toolEvidence?.inferred_arguments)
    ? toolEvidence?.inferred_arguments.slice(0, limits.maxArrayItems).map((item: unknown) => String(item))
    : [];

  return {
    tool_evidence: {
      run_trace: {
        kind: 'tool_call',
        server_name: runTrace.server_name ?? toolEvidence?.server_name ?? metadata.server_name,
        tool_name: runTrace.tool_name ?? toolEvidence?.tool_name ?? metadata.tool_name,
        latency_ms: runTrace.latency_ms,
        success: runTrace.success,
      },
      server_name: toolEvidence?.server_name ?? metadata.server_name ?? runTrace.server_name,
      tool_name: toolEvidence?.tool_name ?? metadata.tool_name ?? runTrace.tool_name,
      arguments: sanitizeValue(argumentsSource ?? {}, limits),
      inferred_arguments: inferredArguments,
      result: sanitizeValue(resultSource, {
        ...limits,
        maxStringChars: limits.maxToolTextChars,
      }),
    },
  };
};

const summarizeToolMessageContent = (
  message: ChatMessage,
  toolSummary: Record<string, any> | null,
  limits: PersistenceLimits,
): string => {
  const runTrace = isRecord(toolSummary?.tool_evidence?.run_trace)
    ? toolSummary?.tool_evidence?.run_trace
    : null;
  const serverName = runTrace?.server_name ? String(runTrace.server_name) : 'tool';
  const toolName = runTrace?.tool_name ? String(runTrace.tool_name) : 'call';
  const status = runTrace?.success === false ? 'failed' : 'completed';
  const fallback = message.content?.trim();

  if (!fallback) {
    return `${serverName}.${toolName} ${status}`;
  }

  return truncateText(fallback, Math.min(limits.maxToolTextChars, 240));
};

const sanitizeMetadata = (
  metadata: Record<string, any> | undefined,
  limits: PersistenceLimits,
): Record<string, any> | undefined => {
  if (!metadata) {
    return undefined;
  }

  const nextMetadata: Record<string, any> = {};

  if (metadata.execution_time !== undefined) {
    nextMetadata.execution_time = metadata.execution_time;
  }
  if (metadata.model_used) {
    nextMetadata.model_used = truncateText(String(metadata.model_used), 160);
  }
  if (metadata.model_name) {
    nextMetadata.model_name = truncateText(String(metadata.model_name), 160);
  }
  if (Array.isArray(metadata.tools_used) && metadata.tools_used.length > 0) {
    nextMetadata.tools_used = metadata.tools_used.slice(0, limits.maxArrayItems).map((item) => truncateText(String(item), 120));
  }
  if (isRecord(metadata.memory_plane)) {
    nextMetadata.memory_plane = {
      phase: truncateText(String(metadata.memory_plane.phase || ''), 80),
      routing: sanitizeValue(metadata.memory_plane.routing, {
        ...limits,
        maxStringChars: Math.min(limits.maxStringChars, 400),
        maxArrayItems: Math.min(limits.maxArrayItems, 8),
      }),
      retention: sanitizeValue(metadata.memory_plane.retention, {
        ...limits,
        maxStringChars: Math.min(limits.maxStringChars, 400),
        maxArrayItems: Math.min(limits.maxArrayItems, 8),
      }),
    };
  }
  if (isRecord(metadata.recipe_preflight)) {
    nextMetadata.recipe_preflight = sanitizeValue(metadata.recipe_preflight, {
      ...limits,
      maxStringChars: Math.min(limits.maxStringChars, 400),
      maxArrayItems: Math.min(limits.maxArrayItems, 8),
    });
  }
  if (isRecord(metadata.guard_evidence)) {
    nextMetadata.guard_evidence = sanitizeValue(metadata.guard_evidence, {
      ...limits,
      maxStringChars: Math.min(limits.maxStringChars, 400),
      maxArrayItems: Math.min(limits.maxArrayItems, 8),
    });
  }
  if (isRecord(metadata.action_event)) {
    nextMetadata.action_event = {
      action_id: truncateText(String(metadata.action_event.action_id || ''), 80),
      stage: truncateText(String(metadata.action_event.stage || ''), 80),
      status: truncateText(String(metadata.action_event.status || ''), 80),
      title: truncateText(String(metadata.action_event.title || ''), 160),
      summary: truncateText(String(metadata.action_event.summary || ''), 300),
      source_plane: truncateText(String(metadata.action_event.source_plane || ''), 80),
    };
  }

  const toolSummary = extractToolSummary(metadata, limits);
  if (toolSummary) {
    Object.assign(nextMetadata, toolSummary);
  }

  return Object.keys(nextMetadata).length > 0 ? nextMetadata : undefined;
};

const sanitizeMessage = (
  message: ChatMessage,
  limits: PersistenceLimits,
): ChatMessage => {
  const metadata = sanitizeMetadata(message.metadata, limits);
  const toolSummaryMetadata = isRecord(metadata?.tool_evidence) ? metadata : null;

  return {
    id: message.id,
    type: message.type,
    content: toolSummaryMetadata
      ? summarizeToolMessageContent(message, toolSummaryMetadata, limits)
      : truncateText(message.content || '', limits.maxContentChars),
    timestamp: message.timestamp,
    image_path: message.image_path,
    image_paths: Array.isArray(message.image_paths)
      ? message.image_paths
        .slice(0, limits.maxArrayItems)
        .map((path) => truncateText(String(path), limits.maxStringChars))
      : undefined,
    attachments: Array.isArray(message.attachments)
      ? message.attachments
        .slice(0, limits.maxAttachments)
        .map((attachment) => sanitizeAttachment(attachment as Record<string, any>, limits))
      : undefined,
    request_id: message.request_id,
    delivery_status: message.delivery_status,
    delivery_error: typeof message.delivery_error === 'string'
      ? truncateText(message.delivery_error, limits.maxStringChars)
      : message.delivery_error,
    retryable: false,
    metadata,
  };
};

const sanitizeSession = (
  session: ChatSession,
  level: PersistenceLevel,
): ChatSession => {
  const limits = PERSISTENCE_LIMITS[level];
  const sourceMessages = session.messages.length > limits.maxMessages
    ? session.messages.slice(session.messages.length - limits.maxMessages)
    : session.messages;

  return {
    id: session.id,
    title: truncateText(session.title, 160),
    messages: sourceMessages.map((message) => sanitizeMessage(message, limits)),
    timestamp: session.timestamp,
    messageCount: session.messageCount,
    clientId: session.clientId,
    isAutoSaved: session.isAutoSaved,
  };
};

const buildMinimalSessionStub = (session: ChatSession): ChatSession => ({
  id: session.id,
  title: truncateText(session.title || 'Conversation', 80),
  messages: [],
  timestamp: session.timestamp,
  messageCount: session.messageCount,
  clientId: session.clientId,
  isAutoSaved: session.isAutoSaved,
});

const isQuotaExceededError = (error: unknown) => {
  if (!error || typeof error !== 'object') {
    return false;
  }
  const quotaLikeError = error as { name?: string; code?: number };
  return quotaLikeError.name === 'QuotaExceededError' || quotaLikeError.code === 22;
};

const getStorageItem = (key: string): string | null => {
  if (!isBrowser) {
    return null;
  }
  return window.localStorage.getItem(key);
};

const setStorageItem = (key: string, value: string): boolean => {
  if (!isBrowser) {
    return false;
  }

  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch (error) {
    if (isQuotaExceededError(error)) {
      try {
        window.localStorage.removeItem(key);
        window.localStorage.setItem(key, value);
        return true;
      } catch (retryError) {
        console.warn(`Storage quota exceeded while writing ${key}.`, retryError);
        return false;
      }
    }
    console.error(`Failed to write ${key} to localStorage.`, error);
    return false;
  }
};

const removeStorageItem = (key: string) => {
  if (!isBrowser) {
    return;
  }
  window.localStorage.removeItem(key);
};

export const buildChatTitle = (messages: ChatMessage[]): string => {
  return buildChatTitleWithFallback(messages, 'New conversation');
};

export const buildChatTitleWithFallback = (messages: ChatMessage[], fallbackTitle: string): string => {
  const firstUserMessage = messages.find((message) => message.type === 'user' && message.content.trim());
  if (firstUserMessage) {
    const title = firstUserMessage.content.trim();
    return title.length > 30 ? `${title.slice(0, 30)}...` : title;
  }
  return fallbackTitle;
};

export const createSessionSnapshot = (
  clientId: string,
  messages: ChatMessage[],
  options?: {
    id?: string;
    timestamp?: string;
    isAutoSaved?: boolean;
    fallbackTitle?: string;
  }
): ChatSession => {
  const timestamp = options?.timestamp ?? new Date().toISOString();
  return {
    id: options?.id ?? `session-${clientId}`,
    title: buildChatTitleWithFallback(messages, options?.fallbackTitle ?? 'New conversation'),
    messages,
    timestamp,
    messageCount: messages.length,
    clientId,
    isAutoSaved: options?.isAutoSaved ?? false,
  };
};

export const getStoredClientId = (): string | null => getStorageItem(CHAT_CLIENT_ID_KEY);

export const persistClientId = (clientId: string) => {
  setStorageItem(CHAT_CLIENT_ID_KEY, clientId);
};

export const loadSavedSessions = (): ChatSession[] => {
  const raw = getStorageItem(CHAT_SESSIONS_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.error('Failed to load chat sessions:', error);
    return [];
  }
};

export const saveSessions = (sessions: ChatSession[]) => {
  const levels: PersistenceLevel[] = ['default', 'aggressive', 'minimal'];
  for (const level of levels) {
    const limits = PERSISTENCE_LIMITS[level];
    const trimmedSessions = sessions
      .slice(0, limits.maxSessions)
      .map((session) => sanitizeSession(session, level));
    const saved = setStorageItem(CHAT_SESSIONS_KEY, JSON.stringify(trimmedSessions));
    if (saved) {
      return;
    }
  }

  setStorageItem(CHAT_SESSIONS_KEY, JSON.stringify([]));
};

export const loadCurrentSession = (): ChatSession | null => {
  const raw = getStorageItem(CHAT_CURRENT_SESSION_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as ChatSession;
  } catch (error) {
    console.error('Failed to load current chat session:', error);
    return null;
  }
};

export const saveCurrentSession = (session: ChatSession) => {
  const variants: ChatSession[] = [
    sanitizeSession(session, 'default'),
    sanitizeSession(session, 'aggressive'),
    sanitizeSession(session, 'minimal'),
    buildMinimalSessionStub(session),
  ];

  for (const variant of variants) {
    const saved = setStorageItem(CHAT_CURRENT_SESSION_KEY, JSON.stringify(variant));
    if (saved) {
      return;
    }
  }

  console.warn('Failed to persist current chat session after applying storage fallbacks.');
};

export const clearCurrentSession = () => {
  removeStorageItem(CHAT_CURRENT_SESSION_KEY);
};

export const getDisplaySessions = (
  clientId: string,
  currentMessages: ChatMessage[],
  options?: {
    fallbackTitle?: string;
  }
): ChatSession[] => {
  const archivedSessions = loadSavedSessions();
  const persistedCurrentSession = loadCurrentSession();
  const currentSession =
    persistedCurrentSession && (!persistedCurrentSession.clientId || persistedCurrentSession.clientId === clientId)
      ? persistedCurrentSession
      : null;

  if (currentMessages.length > 0) {
    const liveSession = createSessionSnapshot(clientId, currentMessages, {
      isAutoSaved: true,
      fallbackTitle: options?.fallbackTitle,
    });
    return [
      liveSession,
      ...archivedSessions.filter((session) => session.id !== liveSession.id),
    ];
  }

  if (currentSession) {
    return [
      currentSession,
      ...archivedSessions.filter((session) => session.id !== currentSession.id),
    ];
  }

  return archivedSessions;
};
