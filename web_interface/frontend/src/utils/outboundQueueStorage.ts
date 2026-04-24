import { WebSocketMessage } from '../types';

const OUTBOUND_QUEUE_STORAGE_PREFIX = 'mcp_outbound_queue';
const isBrowser = typeof window !== 'undefined';

function getStorageKey(clientId: string) {
  return `${OUTBOUND_QUEUE_STORAGE_PREFIX}:${clientId}`;
}

export function loadOutboundQueue(clientId: string): WebSocketMessage[] {
  if (!isBrowser) {
    return [];
  }

  try {
    const raw = window.sessionStorage.getItem(getStorageKey(clientId));
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.error('Failed to load outbound queue:', error);
    return [];
  }
}

export function saveOutboundQueue(clientId: string, queue: WebSocketMessage[]) {
  if (!isBrowser) {
    return;
  }

  try {
    window.sessionStorage.setItem(getStorageKey(clientId), JSON.stringify(queue));
  } catch (error) {
    console.error('Failed to save outbound queue:', error);
  }
}

export function clearOutboundQueue(clientId: string) {
  if (!isBrowser) {
    return;
  }

  window.sessionStorage.removeItem(getStorageKey(clientId));
}
