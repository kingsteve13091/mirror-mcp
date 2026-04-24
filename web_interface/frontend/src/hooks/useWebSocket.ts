import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AgentSkillSummary,
  ChatAttachment,
  ChatMessage,
  ConnectionStatus,
  MemoryPlaneSnapshot,
  MemoryStats,
  MemoryStatus,
  MessageDeliveryStatus,
  TEMGuard,
  TEMRecipe,
  TEMStats,
  WebSocketMessage,
  WorkspaceMcpState,
  ResourceReference,
} from '../types';
import { WS_BASE_URL } from '../config/backend';
import { clearOutboundQueue, loadOutboundQueue, saveOutboundQueue } from '../utils/outboundQueueStorage';

const MAX_RECONNECT_ATTEMPTS = 5;
const MAX_RECONNECT_DELAY_MS = 30000;
const RECONNECT_BASE_DELAY_MS = 1000;
const MAX_OUTBOUND_QUEUE_SIZE = 25;
const QUEUEABLE_MESSAGE_TYPES = new Set(['chat', 'tool_call', 'resource_read', 'prompt_get']);

interface SendTrackedResult {
  ok: boolean;
  queued: boolean;
  payload: WebSocketMessage;
  requestId: string;
}

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

interface AddUserMessageOptions {
  imagePath?: string;
  attachments?: ChatAttachment[];
  requestId?: string;
  deliveryStatus?: MessageDeliveryStatus;
  retryable?: boolean;
  retryPayload?: WebSocketMessage;
  metadata?: ChatMessage['metadata'];
}

function createRequestId() {
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function isQueueableOutboundMessage(message: WebSocketMessage) {
  return QUEUEABLE_MESSAGE_TYPES.has(String(message.type || '')) && typeof message.request_id === 'string';
}

function summarizeOutboundMessage(message: WebSocketMessage): PendingOutboundRequest {
  const type = String(message.type || 'unknown');
  const content = String(message.content || '');
  return {
    request_id: String(message.request_id || ''),
    type,
    created_at: typeof message.timestamp === 'string' ? message.timestamp : undefined,
    content_preview: content ? content.slice(0, 160) : undefined,
    server_name: typeof message.server_name === 'string' ? message.server_name : undefined,
    tool_name: typeof message.tool_name === 'string' ? message.tool_name : undefined,
    prompt_name: typeof message.prompt_name === 'string' ? message.prompt_name : undefined,
    uri: typeof message.uri === 'string' ? message.uri : undefined,
  };
}

function formatPerformanceReport(report: any) {
  const total = report.total_orchestrations || 0;
  const ok = report.successful_orchestrations || 0;
  const rate = total > 0 ? ((ok / total) * 100).toFixed(1) : '0.0';

  return [
    'Performance Report',
    '',
    `Total orchestrations: ${total}`,
    `Successful runs: ${ok}`,
    `Success rate: ${rate}%`,
    `Average execution time: ${(report.average_execution_time || 0).toFixed(2)} ms`,
  ].join('\n');
}

function buildMetadata(message: WebSocketMessage) {
  return {
    ...(message.metadata || {}),
    generated_images: message.metadata?.generated_images || message.generated_images,
    image_paths: message.metadata?.image_paths || message.image_paths,
    image_path: message.metadata?.image_path || message.image_path,
    model_used: message.metadata?.model_used || message.model_used,
    model_name: message.metadata?.model_name || message.model_name,
    memory: message.metadata?.memory || message.memory,
    tem_event: message.metadata?.tem_event || message.tem_event,
    memory_plane: message.metadata?.memory_plane || message.memory_plane,
    causal_trace: message.metadata?.causal_trace || message.causal_trace,
    recipe_preflight: message.metadata?.recipe_preflight || message.recipe_preflight,
    guard_evidence: message.metadata?.guard_evidence || message.guard_evidence,
    run_trace: message.metadata?.run_trace || message.run_trace,
    policy_action: message.metadata?.policy_action || message.policy_action,
    policy_reason: message.metadata?.policy_reason || message.policy_reason,
    block_source: message.metadata?.block_source || message.block_source,
    execution_time: message.metadata?.execution_time || message.execution_time,
    tools_used: message.metadata?.tools_used || message.tools_used,
    harness: message.metadata?.harness || message.harness,
    resource_refs: message.metadata?.resource_refs || message.resource_refs,
    action_event: message.metadata?.action_event || message.action_event,
  };
}

function normalizeImagePaths(message: WebSocketMessage, metadata?: Record<string, any>) {
  const paths: string[] = [];
  const pushPath = (value: unknown) => {
    if (typeof value !== 'string') {
      return;
    }
    const trimmed = value.trim();
    if (trimmed && !paths.includes(trimmed)) {
      paths.push(trimmed);
    }
  };
  const collectImages = (value: unknown) => {
    if (!Array.isArray(value)) {
      return;
    }
    value.forEach((item) => {
      if (typeof item === 'string') {
        pushPath(item);
      } else if (item && typeof item === 'object') {
        const record = item as Record<string, any>;
        pushPath(record.url);
        pushPath(record.data_url);
        pushPath(record.path);
      }
    });
  };

  pushPath(message.image_path);
  if (Array.isArray(message.image_paths)) {
    message.image_paths.forEach(pushPath);
  }
  if (metadata) {
    pushPath(metadata.image_path);
    if (Array.isArray(metadata.image_paths)) {
      metadata.image_paths.forEach(pushPath);
    }
    collectImages(metadata.generated_images);
  }
  collectImages(message.generated_images);
  return paths;
}

function applyDeliveryUpdate(messages: ChatMessage[], requestId: string, status: MessageDeliveryStatus, message?: string) {
  return messages.map((item) => {
    if (item.request_id !== requestId) {
      return item;
    }

    return {
      ...item,
      delivery_status: status,
      delivery_error: status === 'failed' ? message || 'Request failed' : undefined,
      retryable: status === 'failed' || status === 'blocked' ? true : item.retryable,
    };
  });
}

function buildToolEvidenceMetadata(message: WebSocketMessage) {
  return {
    ...buildMetadata(message),
    tool_name: message.tool_name,
    server_name: message.server_name,
    arguments: message.arguments,
    result: message.result,
    inferred_arguments: message.inferred_arguments,
    resource_refs: message.resource_refs,
  };
}

function isActionEventMessage(item: ChatMessage, requestId?: string) {
  if (!requestId || item.request_id !== requestId || item.type !== 'system') {
    return false;
  }
  return Boolean(item.metadata?.action_event?.action_id);
}

function mergeActionEventIntoMessage(message: ChatMessage, metadata: Record<string, any>) {
  return {
    ...message,
    metadata: {
      ...(message.metadata || {}),
      ...metadata,
      action_event: metadata.action_event,
      resource_refs: metadata.resource_refs,
    },
  };
}

function isStandaloneToolResultMessage(item: ChatMessage, requestId?: string) {
  if (!requestId || item.request_id !== requestId || item.type !== 'system') {
    return false;
  }
  return item.metadata?.run_trace?.kind === 'tool_call' || item.metadata?.tool_result_available === true;
}

function mergeToolEvidenceIntoAssistantMessage(message: ChatMessage, toolEvidence: Record<string, any>) {
  return {
    ...message,
    metadata: {
      ...(message.metadata || {}),
      ...toolEvidence,
      tool_result_available: true,
      tool_evidence: toolEvidence,
      tool_name: message.metadata?.tool_name || toolEvidence.tool_name,
      server_name: message.metadata?.server_name || toolEvidence.server_name,
      arguments: toolEvidence.arguments,
      result: toolEvidence.result,
      inferred_arguments: toolEvidence.inferred_arguments,
      run_trace: toolEvidence.run_trace || message.metadata?.run_trace,
      memory_plane: toolEvidence.memory_plane || message.metadata?.memory_plane,
      causal_trace: toolEvidence.causal_trace || message.metadata?.causal_trace,
      recipe_preflight: toolEvidence.recipe_preflight || message.metadata?.recipe_preflight,
      tem_event: toolEvidence.tem_event || message.metadata?.tem_event,
      execution_time: message.metadata?.execution_time || toolEvidence.execution_time,
      tools_used: message.metadata?.tools_used || toolEvidence.tools_used,
    },
  };
}

function getPendingToolEvidence(messages: ChatMessage[], requestId?: string) {
  if (!requestId) {
    return null;
  }
  const pendingToolMessage = messages.find((item) => isStandaloneToolResultMessage(item, requestId));
  return pendingToolMessage?.metadata ? { ...pendingToolMessage.metadata } : null;
}

function getBackendToolEvidence(metadata: Record<string, any>) {
  return metadata.tool_evidence && typeof metadata.tool_evidence === 'object'
    ? (metadata.tool_evidence as Record<string, any>)
    : null;
}

function mergeEvidenceMetadata(baseMetadata: Record<string, any>, toolEvidence: Record<string, any> | null) {
  if (!toolEvidence) {
    return baseMetadata;
  }
  return {
    ...baseMetadata,
    ...toolEvidence,
    tool_result_available: true,
    tool_evidence: toolEvidence,
  };
}

function stripStandaloneToolMessages(messages: ChatMessage[], requestId?: string) {
  if (!requestId) {
    return [...messages];
  }
  return messages.filter((item) => !isStandaloneToolResultMessage(item, requestId));
}

function findRequestAttachments(messages: ChatMessage[], requestId?: string): ChatAttachment[] | undefined {
  if (!requestId) {
    return undefined;
  }
  const source = messages.find((item) => (
    item.request_id === requestId
    && Array.isArray(item.attachments)
    && item.attachments.length > 0
  ));
  return source?.attachments;
}

export const useWebSocket = (clientId: string) => {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    status: 'disconnected',
    message: 'Not connected',
  });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [memoryStatus, setMemoryStatus] = useState<MemoryStatus | null>(null);
  const [temStats, setTemStats] = useState<TEMStats | null>(null);
  const [temRecipes, setTemRecipes] = useState<TEMRecipe[]>([]);
  const [temGuards, setTemGuards] = useState<TEMGuard[]>([]);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<{
    providers_ready?: boolean;
    providers?: Record<string, any>;
    models?: Record<string, any>;
    mcp?: {
      connected_servers?: string[];
      tools_count?: number;
      available_tools?: ConnectionStatus['available_tools'];
    };
    tem?: Record<string, any>;
    tool_policy?: Record<string, any>;
    memory_plane?: MemoryPlaneSnapshot;
    agent_skills?: {
      count?: number;
      skills?: AgentSkillSummary[];
      roots?: Array<Record<string, any>>;
      failed?: Array<Record<string, any>>;
    };
    skill_runtime?: ConnectionStatus['skill_runtime'];
    workspace_mcp?: WorkspaceMcpState;
    last_event?: string;
    last_message?: string;
    timestamp?: string;
  } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const manualCloseRef = useRef(false);
  const connectionGenerationRef = useRef(0);
  const outboundQueueRef = useRef<WebSocketMessage[]>([]);
  const [pendingQueueSize, setPendingQueueSize] = useState(0);
  const [pendingOutboundRequests, setPendingOutboundRequests] = useState<PendingOutboundRequest[]>([]);

  const appendMessage = useCallback((message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const updateMessage = useCallback((messageId: string, patch: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((item) => (item.id === messageId ? { ...item, ...patch } : item)));
  }, []);

  const markRequestDelivery = useCallback((requestId: string, status: MessageDeliveryStatus, message?: string) => {
    setMessages((prev) => applyDeliveryUpdate(prev, requestId, status, message));
  }, []);

  const persistOutboundQueue = useCallback(() => {
    if (outboundQueueRef.current.length === 0) {
      clearOutboundQueue(clientId);
      setPendingOutboundRequests([]);
      return;
    }
    saveOutboundQueue(clientId, outboundQueueRef.current);
    setPendingOutboundRequests(outboundQueueRef.current.map(summarizeOutboundMessage));
  }, [clientId]);

  const removeQueuedRequest = useCallback((requestId: string) => {
    if (!requestId) {
      return;
    }
    const nextQueue = outboundQueueRef.current.filter((item) => item.request_id !== requestId);
    if (nextQueue.length === outboundQueueRef.current.length) {
      return;
    }
    outboundQueueRef.current = nextQueue;
    setPendingQueueSize(nextQueue.length);
    if (nextQueue.length === 0) {
      clearOutboundQueue(clientId);
      setPendingOutboundRequests([]);
      return;
    }
    saveOutboundQueue(clientId, nextQueue);
    setPendingOutboundRequests(nextQueue.map(summarizeOutboundMessage));
  }, [clientId]);

  const cancelQueuedRequest = useCallback((requestId: string) => {
    if (!requestId) {
      return false;
    }
    const existed = outboundQueueRef.current.some((item) => item.request_id === requestId);
    if (!existed) {
      return false;
    }
    removeQueuedRequest(requestId);
    markRequestDelivery(requestId, 'failed', 'Queued request canceled locally');
    return true;
  }, [markRequestDelivery, removeQueuedRequest]);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case 'connection':
        setConnectionStatus({
          status: 'connected',
          message: 'Realtime connection ready',
          available_tools: message.available_tools,
          agent_skills: message.agent_skills?.skills,
          connected_servers: message.connected_servers,
          mcp_servers_available: message.mcp_servers_available,
          workspace_mcp: message.workspace_mcp,
          providers_ready: typeof message.providers_ready === 'boolean'
            ? message.providers_ready
            : Boolean(message.siliconflow_available || message.openrouter_available),
        });
        break;

      case 'connection_status':
        setConnectionStatus((prev) => ({
          ...prev,
          status: message.status,
          message: message.message,
        }));
        break;

      case 'mcp_status_update':
        setConnectionStatus((prev) => ({
          ...prev,
          available_tools: message.available_tools,
          connected_servers: message.connected_servers,
          mcp_servers_available: message.mcp_servers_available,
          workspace_mcp: message.workspace_mcp || prev.workspace_mcp,
          providers_ready: typeof message.providers_ready === 'boolean'
            ? message.providers_ready
            : prev.providers_ready,
        }));
        break;

      case 'status':
        if (message.status === 'processing') {
          setIsTyping(true);
          if (message.request_id) {
            markRequestDelivery(message.request_id, 'processing', message.message);
          }
        }
        break;

      case 'request_delivery': {
        const statusMap: Record<string, MessageDeliveryStatus> = {
          received: 'sent',
          processing: 'processing',
          completed: 'sent',
          blocked: 'blocked',
          failed: 'failed',
        };
        if (message.request_id) {
          markRequestDelivery(message.request_id, statusMap[message.status] || 'pending', message.message);
          if (['completed', 'failed', 'blocked'].includes(String(message.status))) {
            removeQueuedRequest(message.request_id);
          }
        }
        break;
      }

      case 'runtime_status_update':
        setRuntimeSnapshot({
          providers_ready: message.providers_ready,
          providers: message.providers,
          models: message.models,
          mcp: message.mcp,
          tem: message.tem,
          tool_policy: message.tool_policy,
          memory_plane: message.memory_plane,
          agent_skills: message.agent_skills,
          workspace_mcp: message.workspace_mcp,
          last_event: message.event,
          last_message: message.message,
          timestamp: message.timestamp,
        });
        setConnectionStatus((prev) => ({
          ...prev,
          providers_ready: typeof message.providers_ready === 'boolean' ? message.providers_ready : prev.providers_ready,
          connected_servers: Array.isArray(message.mcp?.connected_servers)
            ? message.mcp.connected_servers
            : prev.connected_servers,
          available_tools: Array.isArray(message.mcp?.available_tools)
            ? message.mcp.available_tools
            : prev.available_tools,
          agent_skills: Array.isArray(message.agent_skills?.skills)
            ? message.agent_skills.skills
            : prev.agent_skills,
          workspace_mcp: message.workspace_mcp || prev.workspace_mcp,
          mcp_servers_available:
            Array.isArray(message.mcp?.connected_servers)
              ? message.mcp.connected_servers.length > 0
              : prev.mcp_servers_available,
        }));
        break;

      case 'context_status':
        if (message.memory) {
          setMemoryStats(message.memory);
        }
        if (message.workspace_mcp || message.skill_runtime || message.memory_plane) {
          setRuntimeSnapshot((prev) => ({
            ...(prev || {}),
            workspace_mcp: message.workspace_mcp || prev?.workspace_mcp,
            skill_runtime: message.skill_runtime || prev?.skill_runtime,
            memory_plane: message.memory_plane || prev?.memory_plane,
            timestamp: message.timestamp || prev?.timestamp,
          }));
          setConnectionStatus((prev) => {
            const next = {
              ...prev,
              workspace_mcp: message.workspace_mcp || prev.workspace_mcp,
              skill_runtime: message.skill_runtime || prev.skill_runtime,
            };
            return next;
          });
        }
        break;

      case 'response_start':
        setMessages((prev) => {
          const requestId = typeof message.request_id === 'string' ? message.request_id : undefined;
          const messageId = String(message.id || (requestId ? `assistant-${requestId}` : `assistant-${Date.now()}`));
          const nextBase = stripStandaloneToolMessages(prev, requestId);
          const existingIndex = nextBase.findIndex((item) => (
            item.id === messageId
            || (requestId && item.type === 'assistant' && item.request_id === requestId)
          ));
          const requestAttachments = findRequestAttachments(prev, requestId);
          const baseMetadata = buildMetadata(message);
          const combinedMetadata = mergeEvidenceMetadata(
            baseMetadata,
            getBackendToolEvidence(baseMetadata) || getPendingToolEvidence(prev, requestId),
          );
          const imagePaths = normalizeImagePaths(message, combinedMetadata);
          const baseMessage: ChatMessage = {
            id: messageId,
            request_id: requestId,
            type: 'assistant',
            content: '',
            timestamp: message.timestamp || new Date().toISOString(),
            attachments: requestAttachments,
            image_path: imagePaths[0],
            image_paths: imagePaths,
            metadata: combinedMetadata,
          };

          if (existingIndex >= 0) {
            const next = [...nextBase];
            next[existingIndex] = {
              ...next[existingIndex],
              id: next[existingIndex].id || messageId,
              request_id: next[existingIndex].request_id || requestId,
              timestamp: next[existingIndex].timestamp || baseMessage.timestamp,
              attachments: next[existingIndex].attachments || requestAttachments,
              image_path: next[existingIndex].image_path || baseMessage.image_path,
              image_paths: next[existingIndex].image_paths?.length ? next[existingIndex].image_paths : baseMessage.image_paths,
              metadata: {
                ...(next[existingIndex].metadata || {}),
                ...baseMessage.metadata,
              },
            };
            return next;
          }

          return [...nextBase, baseMessage];
        });
        if (message.request_id) {
          markRequestDelivery(message.request_id, 'processing', 'Receiving model response');
        }
        setIsTyping(true);
        break;

      case 'response_delta':
        setMessages((prev) => {
          const requestId = typeof message.request_id === 'string' ? message.request_id : undefined;
          const messageId = String(message.id || (requestId ? `assistant-${requestId}` : `assistant-${Date.now()}`));
          const delta = String(message.delta || '');
          const nextBase = stripStandaloneToolMessages(prev, requestId);
          const existingIndex = nextBase.findIndex((item) => (
            item.id === messageId
            || (requestId && item.type === 'assistant' && item.request_id === requestId)
          ));

          if (existingIndex >= 0) {
            const next = [...nextBase];
            next[existingIndex] = {
              ...next[existingIndex],
              content: `${next[existingIndex].content || ''}${delta}`,
              timestamp: message.timestamp || next[existingIndex].timestamp,
            };
            return next;
          }

          return [
            ...prev,
            {
              id: messageId,
              request_id: requestId,
              type: 'assistant',
              content: delta,
              timestamp: message.timestamp || new Date().toISOString(),
              attachments: findRequestAttachments(prev, requestId),
              metadata: mergeEvidenceMetadata(
                buildMetadata(message),
                getPendingToolEvidence(prev, requestId),
              ),
            },
          ];
        });
        setIsTyping(true);
        break;

      case 'response_done':
        if (message.memory) {
          setMemoryStats(message.memory);
        }
        setMessages((prev) => {
          const requestId = typeof message.request_id === 'string' ? message.request_id : undefined;
          const messageId = String(message.id || (requestId ? `assistant-${requestId}` : `assistant-${Date.now()}`));
          const existingIndex = prev.findIndex((item) => (
            item.id === messageId
            || (requestId && item.type === 'assistant' && item.request_id === requestId)
          ));
          const baseMetadata = buildMetadata(message);
          const combinedToolEvidence = getBackendToolEvidence(baseMetadata) || getPendingToolEvidence(prev, requestId);
          const requestAttachments = findRequestAttachments(prev, requestId);
          const finalMetadata = mergeEvidenceMetadata(baseMetadata, combinedToolEvidence);
          const imagePaths = normalizeImagePaths(message, finalMetadata);
          const finalContent = String(message.content || '');
          const nextBase = requestId
            ? prev.filter((item) => !isStandaloneToolResultMessage(item, requestId))
            : [...prev];
          const adjustedExistingIndex = existingIndex >= 0
            ? nextBase.findIndex((item) => (
              item.id === messageId
              || (requestId && item.type === 'assistant' && item.request_id === requestId)
            ))
            : -1;

          if (adjustedExistingIndex >= 0) {
            const next = [...nextBase];
            next[adjustedExistingIndex] = {
              ...next[adjustedExistingIndex],
              id: next[adjustedExistingIndex].id || messageId,
              request_id: next[adjustedExistingIndex].request_id || requestId,
              type: 'assistant',
              content: finalContent || next[adjustedExistingIndex].content || '',
              timestamp: message.timestamp || next[adjustedExistingIndex].timestamp,
              attachments: next[adjustedExistingIndex].attachments || requestAttachments,
              image_path: imagePaths[0] || next[adjustedExistingIndex].image_path,
              image_paths: imagePaths.length > 0 ? imagePaths : next[adjustedExistingIndex].image_paths,
              metadata: {
                ...(next[adjustedExistingIndex].metadata || {}),
                ...finalMetadata,
              },
            };
            return next;
          }

          return [
            ...nextBase,
            {
              id: messageId,
              request_id: requestId,
              type: 'assistant',
              content: finalContent,
              timestamp: message.timestamp || new Date().toISOString(),
              attachments: requestAttachments,
              image_path: imagePaths[0],
              image_paths: imagePaths,
              metadata: finalMetadata,
            },
          ];
        });
        if (message.request_id) {
          markRequestDelivery(message.request_id, 'sent');
        }
        setIsTyping(false);
        break;

      case 'response':
      case 'chat_response':
        if (message.memory) {
          setMemoryStats(message.memory);
        }
        setMessages((prev) => {
          const baseMetadata = buildMetadata(message);
          const combinedToolEvidence = getBackendToolEvidence(baseMetadata) || getPendingToolEvidence(prev, message.request_id);
          const requestAttachments = findRequestAttachments(prev, message.request_id);
          const finalMetadata = mergeEvidenceMetadata(baseMetadata, combinedToolEvidence);
          const imagePaths = normalizeImagePaths(message, finalMetadata);

          const assistantMessage: ChatMessage = {
            id: message.id || `assistant-${Date.now()}`,
            request_id: message.request_id,
            type: 'assistant',
            content: message.content || '',
            timestamp: message.timestamp || new Date().toISOString(),
            attachments: requestAttachments,
            image_path: imagePaths[0],
            image_paths: imagePaths,
            metadata: finalMetadata,
          };

          const next = combinedToolEvidence && message.request_id
            ? prev.filter((item) => !isStandaloneToolResultMessage(item, message.request_id))
            : prev;
          return [...next, assistantMessage];
        });
        if (message.request_id) {
          markRequestDelivery(message.request_id, 'sent');
        }
        setIsTyping(false);
        break;

      case 'memory_status':
        if (message.memory) {
          setMemoryStatus(message.memory);
        }
        break;

      case 'memory_cleared':
        setMemoryStats(null);
        setMemoryStatus(null);
        appendMessage({
          id: `system-${Date.now()}`,
          type: 'system',
          content: `Conversation memory cleared${message.message ? `: ${message.message}` : ''}`,
          timestamp: message.timestamp || new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      case 'model_selected':
        appendMessage({
          id: `model-${Date.now()}`,
          type: 'system',
          content: message.message || `Model switched to ${message.model_name || message.model_id}`,
          timestamp: new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      case 'typing':
        setIsTyping(message.status === 'start');
        break;

      case 'error':
        appendMessage({
          id: `error-${Date.now()}`,
          request_id: message.request_id,
          type: 'error',
          content: `Error: ${message.message}`,
          timestamp: message.timestamp || new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        if (message.request_id) {
          markRequestDelivery(message.request_id, 'failed', message.message);
        }
        setIsTyping(false);
        break;

      case 'tool_call_status':
        break;

      case 'tool_result':
        setMessages((prev) => {
          const toolEvidence = buildToolEvidenceMetadata(message);
          const requestId = typeof message.request_id === 'string' ? message.request_id : undefined;
          const requestAttachments = findRequestAttachments(prev, requestId);
          if (requestId) {
            const assistantIndex = prev.findIndex((item) => item.type === 'assistant' && item.request_id === requestId);
            if (assistantIndex >= 0) {
              const next = [...prev];
              next[assistantIndex] = {
                ...mergeToolEvidenceIntoAssistantMessage(next[assistantIndex], toolEvidence),
                attachments: next[assistantIndex].attachments || requestAttachments,
              };
              return next.filter((item, index) => index === assistantIndex || !isStandaloneToolResultMessage(item, requestId));
            }
          }

          return [
            ...prev,
            {
              id: `tool-result-${Date.now()}`,
              request_id: message.request_id,
              type: 'system',
              content: `Tool result: ${message.server_name}.${message.tool_name}`,
              timestamp: message.timestamp || new Date().toISOString(),
              attachments: requestAttachments,
              metadata: {
                ...toolEvidence,
                tool_result_available: true,
                tool_evidence: toolEvidence,
              },
            },
          ];
        });
        if (message.request_id) {
          const success = typeof message.result === 'object' ? Boolean(message.result?.success) : true;
          markRequestDelivery(message.request_id, success ? 'sent' : 'failed', success ? undefined : 'Tool execution failed');
        }
        setIsTyping(true);
        break;

      case 'action_event':
        setMessages((prev) => {
          const requestId = typeof message.request_id === 'string' ? message.request_id : undefined;
          const actionId = String(message.action_id || '').trim();
          const metadata = {
            ...buildMetadata(message),
            action_event: {
              action_id: actionId,
              stage: String(message.stage || ''),
              status: String(message.status || ''),
              title: String(message.title || ''),
              summary: String(message.summary || ''),
              source_plane: String(message.source_plane || ''),
              target: typeof message.target === 'object' && message.target ? message.target : undefined,
            },
            resource_refs: Array.isArray(message.resource_refs)
              ? (message.resource_refs as ResourceReference[])
              : [],
          };
          const existingIndex = actionId
            ? prev.findIndex((item) => (
              item.request_id === requestId
              && item.type === 'system'
              && item.metadata?.action_event?.action_id === actionId
            ))
            : -1;
          const content = metadata.action_event.summary || metadata.action_event.title || 'Action event';

          if (existingIndex >= 0) {
            const next = [...prev];
            next[existingIndex] = mergeActionEventIntoMessage(next[existingIndex], metadata);
            next[existingIndex].content = content;
            next[existingIndex].timestamp = message.timestamp || next[existingIndex].timestamp;
            return next;
          }

          return [
            ...prev,
            {
              id: `action-${metadata.action_event.action_id || Date.now()}`,
              request_id: requestId,
              type: 'system',
              content,
              timestamp: message.timestamp || new Date().toISOString(),
              attachments: findRequestAttachments(prev, requestId),
              metadata,
            },
          ];
        });
        break;

      case 'tool_blocked':
        appendMessage({
          id: `blocked-${Date.now()}`,
          request_id: message.request_id,
          type: 'error',
          content: [
            `Tool blocked: ${message.tool_name}`,
            '',
            `Reason: ${message.reason}`,
            `Suggestion: ${message.suggestion}`,
          ].join('\n'),
          timestamp: message.timestamp || new Date().toISOString(),
          metadata: {
            ...buildMetadata(message),
            tool_name: message.tool_name,
            server_name: message.server_name,
            arguments: message.arguments,
            result: {
              success: false,
              blocked: true,
              reason: message.reason,
              suggestion: message.suggestion,
              guard_id: message.guard_id,
              block_source: message.block_source,
              policy_action: message.policy_action,
              policy_reason: message.policy_reason,
            },
            inferred_arguments: message.inferred_arguments,
          },
        });
        if (message.request_id) {
          markRequestDelivery(message.request_id, 'blocked', message.reason);
        }
        setIsTyping(false);
        break;

      case 'tem_status':
        if (message.stats) {
          setTemStats(message.stats);
        }
        break;

      case 'recipes_list':
        if (message.recipes) {
          setTemRecipes(message.recipes);
        }
        break;

      case 'guards_list':
        if (message.guards) {
          setTemGuards(message.guards);
        }
        break;

      case 'resource_result':
        appendMessage({
          id: `resource-${Date.now()}`,
          request_id: message.request_id,
          type: 'system',
          content: [
            `Resource result: ${message.uri}`,
            '',
            typeof message.result === 'string'
              ? message.result
              : JSON.stringify(message.result, null, 2),
          ].join('\n'),
          timestamp: message.timestamp || new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      case 'prompt_result':
        appendMessage({
          id: `prompt-${Date.now()}`,
          request_id: message.request_id,
          type: 'system',
          content: [
            `Prompt result: ${message.prompt_name}`,
            '',
            typeof message.result === 'string'
              ? message.result
              : JSON.stringify(message.result, null, 2),
          ].join('\n'),
          timestamp: message.timestamp || new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      case 'tool_call_result':
        appendMessage({
          id: `tool-call-result-${Date.now()}`,
          request_id: message.request_id,
          type: message.status === 'success' ? 'system' : 'error',
          content:
            message.status === 'success'
              ? `Tool ${message.tool_name} call succeeded`
              : `Tool ${message.tool_name} call failed: ${message.error}`,
          timestamp: new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      case 'performance_report':
        appendMessage({
          id: `report-${Date.now()}`,
          type: 'system',
          content: formatPerformanceReport(message.report),
          timestamp: new Date().toISOString(),
          metadata: buildMetadata(message),
        });
        break;

      default:
        break;
    }
  }, [appendMessage, markRequestDelivery, removeQueuedRequest]);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const enqueueOutboundMessage = useCallback((payload: WebSocketMessage) => {
    if (!isQueueableOutboundMessage(payload)) {
      return false;
    }

    const requestId = String(payload.request_id);
    const alreadyQueued = outboundQueueRef.current.some((item) => item.request_id === requestId);
    if (alreadyQueued) {
      return true;
    }

    const retainedQueue = outboundQueueRef.current.slice(-(MAX_OUTBOUND_QUEUE_SIZE - 1));
    outboundQueueRef.current = [...retainedQueue, payload];
    setPendingQueueSize(outboundQueueRef.current.length);
    saveOutboundQueue(clientId, outboundQueueRef.current);
    setPendingOutboundRequests(outboundQueueRef.current.map(summarizeOutboundMessage));
    return true;
  }, [clientId]);

  const flushOutboundQueue = useCallback(() => {
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || outboundQueueRef.current.length === 0) {
      return;
    }

    const queued = [...outboundQueueRef.current];

    const failed: WebSocketMessage[] = [];
    queued.forEach((payload) => {
      try {
        socket.send(JSON.stringify(payload));
      } catch (error) {
        failed.push(payload);
      }
    });

    if (failed.length > 0) {
      outboundQueueRef.current = failed.slice(-MAX_OUTBOUND_QUEUE_SIZE);
      setPendingQueueSize(outboundQueueRef.current.length);
      persistOutboundQueue();
      return;
    }
    outboundQueueRef.current = [];
    setPendingQueueSize(0);
    persistOutboundQueue();
  }, [persistOutboundQueue]);

  const connect = useCallback(() => {
    manualCloseRef.current = false;

    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    setConnectionStatus((prev) => ({
      ...prev,
      status: 'connecting',
      message: 'Establishing realtime connection...',
    }));

    const wsUrl = `${WS_BASE_URL}/ws/${clientId}`;

    try {
      const generation = connectionGenerationRef.current + 1;
      connectionGenerationRef.current = generation;
      const socket = new WebSocket(wsUrl);
      wsRef.current = socket;
      const isCurrentSocket = () => wsRef.current === socket && connectionGenerationRef.current === generation;

      socket.onopen = () => {
        if (!isCurrentSocket()) {
          return;
        }
        reconnectAttempts.current = 0;
        clearReconnectTimeout();
        setConnectionStatus((prev) => ({
          ...prev,
          status: 'connected',
          message: 'Realtime connection ready',
        }));
        flushOutboundQueue();
      };

      socket.onmessage = (event) => {
        if (!isCurrentSocket()) {
          return;
        }
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          handleMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      socket.onclose = (event) => {
        if (!isCurrentSocket()) {
          return;
        }
        wsRef.current = null;

        if (manualCloseRef.current) {
          setConnectionStatus((prev) => ({
            ...prev,
            status: 'disconnected',
            message: 'Not connected',
          }));
          return;
        }

        const canReconnect = reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS;
        setConnectionStatus((prev) => ({
          ...prev,
          status: 'disconnected',
          message: canReconnect
            ? `Realtime connection interrupted (${event.code}); reconnecting...`
            : `Realtime connection closed (${event.code})`,
        }));

        if (canReconnect) {
          const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempts.current, MAX_RECONNECT_DELAY_MS);
          reconnectTimeoutRef.current = setTimeout(() => {
            if (manualCloseRef.current || wsRef.current) {
              return;
            }
            reconnectAttempts.current += 1;
            connect();
          }, delay);
        }
      };

      socket.onerror = () => {
        if (!isCurrentSocket()) {
          return;
        }
        setConnectionStatus((prev) => ({
          ...prev,
          status: 'error',
          message: 'Realtime connection error',
        }));
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setConnectionStatus((prev) => ({
        ...prev,
        status: 'error',
        message: 'Unable to create realtime connection',
      }));
    }
  }, [clearReconnectTimeout, clientId, flushOutboundQueue, handleMessage]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    connectionGenerationRef.current += 1;
    clearReconnectTimeout();

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setConnectionStatus((prev) => ({
      ...prev,
      status: 'disconnected',
      message: 'Not connected',
    }));
  }, [clearReconnectTimeout]);

  const sendMessage = useCallback((message: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify(message));
        return true;
      } catch (error) {
        console.error('Failed to send WebSocket message:', error);
        return false;
      }
    }
    return false;
  }, []);

  const sendTrackedMessage = useCallback((message: WebSocketMessage): SendTrackedResult => {
    const requestId = typeof message.request_id === 'string' && message.request_id.trim()
      ? message.request_id
      : createRequestId();
    const payload = {
      ...message,
      request_id: requestId,
    };
    const ok = sendMessage(payload);
    const queued = ok ? false : enqueueOutboundMessage(payload);
    return {
      ok,
      queued,
      payload,
      requestId,
    };
  }, [enqueueOutboundMessage, sendMessage]);

  const requestMCPStatus = useCallback((workspaceContext?: Record<string, any>) => sendMessage({
    type: 'get_mcp_status',
    ...(workspaceContext ? { workspace_context: workspaceContext } : {}),
  }), [sendMessage]);
  const requestMemoryStatus = useCallback(() => sendMessage({ type: 'get_memory_status' }), [sendMessage]);
  const clearMemory = useCallback(() => sendMessage({ type: 'clear_memory' }), [sendMessage]);
  const requestTEMStatus = useCallback(() => sendMessage({ type: 'get_tem_status' }), [sendMessage]);
  const requestRecipes = useCallback(() => sendMessage({ type: 'get_recipes' }), [sendMessage]);
  const requestGuards = useCallback(() => sendMessage({ type: 'get_guards' }), [sendMessage]);

  const addUserMessage = useCallback((content: string, options: AddUserMessageOptions = {}) => {
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      request_id: options.requestId,
      type: 'user',
      content,
      timestamp: new Date().toISOString(),
      image_path: options.imagePath,
      attachments: options.attachments,
      delivery_status: options.deliveryStatus,
      retryable: options.retryable,
      retry_payload: options.retryPayload,
      metadata: options.metadata,
    };
    setMessages((prev) => [...prev, userMessage]);
    return userMessage;
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  useEffect(() => {
    const restoredQueue = loadOutboundQueue(clientId);
    setMessages([]);
    setIsTyping(false);
    setMemoryStats(null);
    setMemoryStatus(null);
    setTemStats(null);
    setTemRecipes([]);
    setTemGuards([]);
    setRuntimeSnapshot(null);
    setPendingQueueSize(0);
    setPendingOutboundRequests([]);
    outboundQueueRef.current = [];

    if (restoredQueue.length > 0) {
      outboundQueueRef.current = restoredQueue.slice(-MAX_OUTBOUND_QUEUE_SIZE);
      setPendingQueueSize(outboundQueueRef.current.length);
      setPendingOutboundRequests(outboundQueueRef.current.map(summarizeOutboundMessage));
    }

    connect();
    return () => {
      manualCloseRef.current = true;
      connectionGenerationRef.current += 1;
      clearReconnectTimeout();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [clearReconnectTimeout, clientId, connect]);

  useEffect(() => {
    if (connectionStatus.status !== 'connected' || pendingQueueSize <= 0) {
      return;
    }
    flushOutboundQueue();
  }, [connectionStatus.status, pendingQueueSize, flushOutboundQueue]);

  return {
    connectionStatus,
    messages,
    isTyping,
    memoryStats,
    memoryStatus,
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
    markRequestDelivery,
    clearMessages,
    setMessages,
    connect,
    disconnect,
    requestMCPStatus,
    requestMemoryStatus,
    clearMemory,
    requestTEMStatus,
    requestRecipes,
    requestGuards,
  };
};
