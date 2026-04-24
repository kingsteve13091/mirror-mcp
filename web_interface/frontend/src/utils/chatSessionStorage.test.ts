import {
  CHAT_CURRENT_SESSION_KEY,
  ChatSession,
  createSessionSnapshot,
  loadCurrentSession,
  saveCurrentSession,
} from './chatSessionStorage';
import { ChatMessage } from '../types';

const buildLargeAssistantMessage = (): ChatMessage => ({
  id: 'assistant-1',
  type: 'assistant',
  content: 'tool result '.repeat(4000),
  timestamp: '2026-04-19T00:00:00Z',
  request_id: 'req-1',
  metadata: {
    model_name: 'Test Model',
    result: {
      success: true,
      raw_result: 'X'.repeat(80000),
      arguments: {
        path: 'D:\\mirror_mcp\\uploads\\large.txt',
        head: 100,
      },
    },
    tool_evidence: {
      server_name: 'filesystem',
      tool_name: 'read_file',
      arguments: {
        path: 'D:\\mirror_mcp\\uploads\\large.txt',
        head: 100,
      },
      result: {
        success: true,
        raw_result: 'Y'.repeat(120000),
      },
      run_trace: {
        kind: 'tool_call',
        server_name: 'filesystem',
        tool_name: 'read_file',
        latency_ms: 88.1,
        success: true,
      },
      inferred_arguments: ['path'],
    },
    run_trace: {
      kind: 'tool_call',
      server_name: 'filesystem',
      tool_name: 'read_file',
      latency_ms: 88.1,
      success: true,
    },
    causal_trace: {
      selected_tool: 'read_file',
      routing_candidates: ['read_file'],
      recipe_memory_used: false,
      guard_memory_used: false,
      context_summary_used: false,
      counterfactual_without_recipe: 'unchanged',
      counterfactual_without_guard: 'unchanged',
      counterfactual_without_summary: 'unchanged',
      blocked: false,
      success: true,
      shadow_replay: {
        available: true,
        reason: 'large test payload',
        selected_tool: 'read_file',
        items: Array.from({ length: 200 }, (_, index) => ({
          tool_name: `tool_${index}`,
          observed_final_score: index,
          observed_probability: index / 200,
          would_be_selected: index === 0,
          memory_components: {
            large_component: index,
          },
        })),
      },
    },
  },
  attachments: [
    {
      filename: 'large.txt',
      original_filename: 'large.txt',
      file_path: 'D:\\mirror_mcp\\uploads\\large.txt',
      url: '/api/uploads/large.txt',
      size: 4096,
      mime_type: 'text/plain',
      parse_status: 'parsed',
      preview_text: 'preview body should not be stored',
      full_text_chars: 50000,
      visible_text_chars: 15000,
      preview_truncated: true,
    },
  ],
});

describe('chatSessionStorage', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('falls back to a smaller persisted current session when localStorage quota is exceeded', () => {
    const originalSetItem = window.localStorage.setItem.bind(window.localStorage);
    const setItemSpy = jest.spyOn(window.localStorage.__proto__, 'setItem');

    let firstLargeWriteRejected = false;
    setItemSpy.mockImplementation((...args: unknown[]) => {
      const [key, value] = args as [string, string];
      if (
        key === CHAT_CURRENT_SESSION_KEY
        && !firstLargeWriteRejected
        && value.length > 10000
      ) {
        firstLargeWriteRejected = true;
        const quotaError = new DOMException('Quota exceeded', 'QuotaExceededError');
        throw quotaError;
      }
      return originalSetItem(key, value);
    });

    const session: ChatSession = createSessionSnapshot('client-1', [buildLargeAssistantMessage()], {
      fallbackTitle: 'Test',
    });

    expect(() => saveCurrentSession(session)).not.toThrow();

    const stored = loadCurrentSession();
    expect(stored).not.toBeNull();
    expect(stored?.messages).toHaveLength(1);
    expect(stored?.messages[0].metadata?.tool_evidence?.run_trace?.tool_name).toBe('read_file');
    expect(JSON.stringify(stored)).not.toContain('Z'.repeat(1000));
    expect(JSON.stringify(stored)).not.toContain('preview body should not be stored');

    setItemSpy.mockRestore();
  });
});
