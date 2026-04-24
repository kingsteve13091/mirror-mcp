import { act, renderHook, waitFor } from '@testing-library/react';
import { useWebSocket } from './useWebSocket';

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = TestWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    TestWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = TestWebSocket.CLOSED;
    this.onclose?.({ code: 1000 });
  }

  open() {
    this.readyState = TestWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

describe('useWebSocket runtime behavior', () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    TestWebSocket.instances = [];
    window.sessionStorage.clear();
    (global as any).WebSocket = TestWebSocket;
    (global as any).WebSocket.OPEN = TestWebSocket.OPEN;
    (global as any).WebSocket.CONNECTING = TestWebSocket.CONNECTING;
  });

  afterEach(() => {
    (global as any).WebSocket = originalWebSocket;
  });

  it('connects, receives runtime status updates, and appends chat responses', async () => {
    const { result } = renderHook(() => useWebSocket('client-test'));
    const socket = TestWebSocket.instances[0];

    act(() => {
      socket.open();
      socket.receive({
        type: 'runtime_status_update',
        providers_ready: true,
        mcp: {
          connected_servers: ['filesystem'],
          available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
          tools_count: 1,
        },
        tem: { mode: 'full_tem' },
        agent_skills: { count: 0, skills: [] },
      });
      socket.receive({
        type: 'chat_response',
        request_id: 'req-1',
        content: 'hello from assistant',
        timestamp: '2026-04-16T00:00:00Z',
      });
    });

    await waitFor(() => {
      expect(result.current.connectionStatus.status).toBe('connected');
      expect(result.current.runtimeSnapshot?.providers_ready).toBe(true);
      expect(result.current.connectionStatus.connected_servers).toEqual(['filesystem']);
      expect(result.current.messages).toHaveLength(1);
    });
    expect(result.current.messages[0].content).toBe('hello from assistant');
  });

  it('queues tracked messages when disconnected and flushes them on reconnect', async () => {
    const { result, unmount } = renderHook(() => useWebSocket('queued-client'));

    let tracked: ReturnType<typeof result.current.sendTrackedMessage> | undefined;
    act(() => {
      tracked = result.current.sendTrackedMessage({
        type: 'chat',
        content: 'queued message',
      });
    });

    expect(tracked?.ok).toBe(false);
    expect(tracked?.queued).toBe(true);
    expect(result.current.pendingQueueSize).toBe(1);
    expect(window.sessionStorage.getItem('mcp_outbound_queue:queued-client')).toContain('queued message');

    unmount();

    const { result: restored } = renderHook(() => useWebSocket('queued-client'));
    const socket = TestWebSocket.instances[TestWebSocket.instances.length - 1];

    await waitFor(() => {
      expect(restored.current.pendingQueueSize).toBe(1);
    });

    act(() => {
      socket.open();
    });

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('queued message'))).toBe(true);
      expect(restored.current.pendingQueueSize).toBe(0);
    });
    expect(window.sessionStorage.getItem('mcp_outbound_queue:queued-client')).toBeNull();
  });

  it('cancels queued requests from the local outbound queue', async () => {
    const { result } = renderHook(() => useWebSocket('cancel-client'));

    let tracked: ReturnType<typeof result.current.sendTrackedMessage> | undefined;
    act(() => {
      tracked = result.current.sendTrackedMessage({
        type: 'chat',
        content: 'cancel me',
      });
    });

    expect(result.current.pendingQueueSize).toBe(1);
    expect(result.current.pendingOutboundRequests[0].content_preview).toBe('cancel me');

    act(() => {
      result.current.cancelQueuedRequest(tracked?.requestId || '');
    });

    expect(result.current.pendingQueueSize).toBe(0);
    expect(result.current.pendingOutboundRequests).toEqual([]);
    expect(window.sessionStorage.getItem('mcp_outbound_queue:cancel-client')).toBeNull();
  });

  it('folds a pending tool result into the streamed assistant response for the same request', async () => {
    const { result } = renderHook(() => useWebSocket('stream-tool-client'));
    const socket = TestWebSocket.instances[0];

    act(() => {
      socket.open();
      socket.receive({
        type: 'tool_result',
        request_id: 'req-tool-stream',
        server_name: 'fetch',
        tool_name: 'fetch',
        arguments: { url: 'http://127.0.0.1:8000/health' },
        result: {
          success: true,
          result: 'healthy',
        },
        run_trace: {
          kind: 'tool_call',
          server_name: 'fetch',
          tool_name: 'fetch',
          success: true,
          latency_ms: 12,
        },
        timestamp: '2026-04-16T00:00:00Z',
      });
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
      expect(result.current.messages[0].type).toBe('system');
    });

    act(() => {
      socket.receive({
        type: 'response_start',
        request_id: 'req-tool-stream',
        id: 'assistant-req-tool-stream',
        model_used: 'Qwen/Qwen3-8B',
        model_name: 'Qwen3-8B',
        timestamp: '2026-04-16T00:00:01Z',
      });
      socket.receive({
        type: 'response_delta',
        request_id: 'req-tool-stream',
        id: 'assistant-req-tool-stream',
        delta: 'Endpoint summary: healthy',
      });
      socket.receive({
        type: 'response_done',
        request_id: 'req-tool-stream',
        id: 'assistant-req-tool-stream',
        content: 'Endpoint summary: healthy',
        model_used: 'Qwen/Qwen3-8B',
        model_name: 'Qwen3-8B',
        timestamp: '2026-04-16T00:00:02Z',
      });
    });

    await waitFor(() => {
      expect(result.current.messages).toHaveLength(1);
      expect(result.current.messages[0].type).toBe('assistant');
      expect(result.current.messages[0].content).toBe('Endpoint summary: healthy');
      expect(result.current.messages[0].metadata?.tool_result_available).toBe(true);
      expect(result.current.messages[0].metadata?.tool_name).toBe('fetch');
    });
  });
});
