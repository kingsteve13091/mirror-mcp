import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatInterface from './ChatInterface';
import * as api from '../services/api';

const TOOLS_ZERO_LABEL = /Tools: 0|\u5de5\u5177:? 0/i;
const FILE_BODY_HIDDEN_LABEL = /Attachment body text was parsed, but the UI hides the full content|\u9644\u4ef6\u6b63\u6587\u5df2\u89e3\u6790/i;
const TRUNCATION_WARNING_LABEL = /Visible text is truncated; the model will not see the full body\\.|\u5f53\u524d\u663e\u793a\u7684\u662f\u622a\u65ad\u540e\u7684\u53ef\u89c1\u6587\u672c\uff0c\u6a21\u578b\u4e0d\u4f1a\u770b\u5230\u5b8c\u6574\u6b63\u6587\u3002/i;

jest.mock('../services/api');
jest.mock('./MessageBubble', () => ({
  __esModule: true,
  default: (props: any) => {
    const React = require('react');
    return React.createElement('div', { 'data-testid': 'message-bubble' }, props.message.content);
  },
}));
jest.mock('./ConnectionIndicator', () => ({
  __esModule: true,
  default: () => {
    const React = require('react');
    return React.createElement('div', { 'data-testid': 'connection-indicator' }, 'connected');
  },
}));
jest.mock('./SettingsPanel', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./TypingIndicator', () => ({
  __esModule: true,
  default: () => {
    const React = require('react');
    return React.createElement('div', { 'data-testid': 'typing-indicator' }, 'typing');
  },
}));
jest.mock('./ChatHistory', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./MCPToolsPanel', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./TEMPanel', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./HealthPanel', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./TaskCenter', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./ToolSelector', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('./ToolConfirmModal', () => ({
  __esModule: true,
  default: ({ isOpen, onConfirm, initialArgs }: any) => {
    const React = require('react');
    if (!isOpen) {
      return null;
    }
    return React.createElement(
      'button',
      {
        type: 'button',
        onClick: () => onConfirm(initialArgs || {}),
      },
      'confirm tool call',
    );
  },
}));
jest.mock('./AgentRuntimeBar', () => ({
  __esModule: true,
  default: ({ visible, agentModeEnabled, workspaceAgentProfile }: any) => {
    const React = require('react');
    if (!visible) {
      return null;
    }
    return React.createElement(
      'div',
      { 'data-testid': 'agent-runtime-bar' },
      `${agentModeEnabled ? 'agent-on' : 'agent-off'}:${workspaceAgentProfile?.agent_name || 'no-agent'}`,
    );
  },
}));
jest.mock('./ModelSelector', () => ({
  __esModule: true,
  default: ({ selectedModel, models }: any) => {
    const React = require('react');
    const selected = Array.isArray(models)
      ? models.find((model: any) => model.id === selectedModel)
      : null;
    return React.createElement(
      'div',
      { 'data-testid': 'model-selector' },
      selected?.name || selectedModel || 'no-model',
    );
  },
}));

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  readyState = TestWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    TestWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.onclose?.({ code: 1000 });
  }

  open() {
    this.readyState = TestWebSocket.OPEN;
    this.onopen?.();
  }
}

const mockedApi = api as jest.Mocked<typeof api>;

const onboardingAudit = {
  ok: true,
  summary: {
    total_tools: 2,
    auto_routable_tools: 2,
    auto_executable_tools: 1,
    manual_only_tools: 0,
    schema_risk_tools: 0,
  },
  issues: [],
  tools: [
    {
      tool_key: 'filesystem.list_directory',
      server: 'filesystem',
      name: 'list_directory',
      description: 'List files',
      automation_class: 'auto_executable',
      auto_routable: true,
      auto_executable: true,
      inferred_fields_sample: [],
      required_fields: [],
      schema_property_count: 0,
      schema_warnings: [],
      self_test: {
        status: 'planned',
        safe_to_run: true,
        gate_required: true,
        reason: 'Safe read-only directory listing check',
        expected_outcome: 'Returns an allowed directory list or directory entries',
        sample_arguments: {},
        required_fields: [],
        inferred_fields: [],
      },
    },
    {
      tool_key: 'filesystem.read_file',
      server: 'filesystem',
      name: 'read_file',
      description: 'Read file content',
      automation_class: 'auto_routable_manual_confirm',
      auto_routable: true,
      auto_executable: false,
      inferred_fields_sample: ['path'],
      required_fields: ['path'],
      schema_property_count: 3,
      schema_warnings: [],
      self_test: {
        status: 'planned',
        safe_to_run: false,
        gate_required: false,
        reason: 'Requires a concrete path from user context',
        expected_outcome: 'Reads the selected file',
        sample_arguments: { path: 'D:\\mirror_mcp\\README.md' },
        required_fields: ['path'],
        inferred_fields: ['path'],
      },
    },
  ],
};

const onboardingRun = {
  ok: true,
  summary: {
    requested: 1,
    executed_or_skipped: 1,
    passed: 1,
    failed: 0,
    skipped: 0,
    gate_failed: 0,
  },
  results: [
    {
      tool_key: 'filesystem.list_directory',
      server: 'filesystem',
      name: 'list_directory',
      ok: true,
      status: 'passed',
      arguments: {},
      result_preview: 'allowed directories',
    },
  ],
};

const bootstrap = {
  status: 'ok',
  timestamp: '2026-04-16T00:00:00Z',
  providers: {
    siliconflow: { configured: false },
    openrouter: { configured: true },
  },
  models: {
    default: 'test-model',
    count: 1,
    available: [
      {
        id: 'test-model',
        name: 'Test Model',
        description: 'Test model',
        type: 'text' as const,
        max_tokens: 4096,
        provider: 'openrouter',
      },
    ],
  },
  agent_skills: { count: 0, skills: [] },
  mcp: {
    available: true,
    connected_servers: ['filesystem'],
    tools: [
      {
        server: 'filesystem',
        name: 'list_directory',
        display_name: 'list_directory',
        enabled: true,
        description: 'List files',
        server_status: 'connected',
        client_connected: true,
        input_schema: {
          type: 'object',
          properties: {},
          required: [],
        },
      },
      {
        server: 'filesystem',
        name: 'read_file',
        display_name: 'read_file',
        enabled: true,
        description: 'Read file content',
        server_status: 'connected',
        client_connected: true,
        input_schema: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            tail: { type: 'number', description: 'If provided, returns only the last N lines of the file' },
            head: { type: 'number', description: 'If provided, returns only the first N lines of the file' },
          },
          required: ['path'],
        },
      },
    ],
    tools_count: 2,
    servers: {
      servers: [],
      total_servers: 1,
      connected_servers: 1,
      total_tools: 2,
      total_resources: 0,
      total_prompts: 0,
      last_update: '2026-04-16T00:00:00Z',
      fastmcp_available: true,
    },
    audit: { ok: true, errors: [], checks: {}, server_catalog: [] },
  },
  tem: {
    mode: 'full_tem',
    supported_modes: ['full_tem'],
    flags: {},
  },
};

describe('ChatInterface', () => {
  const originalWebSocket = global.WebSocket;
  const originalScrollIntoView = window.HTMLElement.prototype.scrollIntoView;

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    TestWebSocket.instances = [];
    window.HTMLElement.prototype.scrollIntoView = jest.fn();
    (global as any).WebSocket = TestWebSocket;
    (global as any).WebSocket.OPEN = TestWebSocket.OPEN;
    (global as any).WebSocket.CONNECTING = TestWebSocket.CONNECTING;
    mockedApi.getSystemBootstrap.mockResolvedValue(bootstrap as any);
    mockedApi.getModels.mockResolvedValue({
      models: bootstrap.models.available as any,
      default: bootstrap.models.default,
    });
    mockedApi.getRuntimeProviders.mockResolvedValue({
      providers: bootstrap.providers,
      models: { ...bootstrap.models, custom_count: 0 },
      runtime_overrides: {
        has_siliconflow_key: false,
        has_openrouter_key: true,
        custom_models: [],
      },
    } as any);
    mockedApi.getRuntimeToolPolicy.mockResolvedValue({
      enabled: true,
      default_action: 'allow',
      tool_actions: {},
      server_actions: {},
      system_actions: {
        terminal_command: 'confirm',
        process_control: 'confirm',
      },
      deny_risky_write_paths: true,
    } as any);
    mockedApi.getRuntimeAutoToolRouting.mockResolvedValue({
      mode: 'memory_plane_plus_fallback',
      fallback_enabled: true,
      file_path_fallback_enabled: true,
      url_fetch_fallback_enabled: true,
      available_modes: [],
    } as any);
    mockedApi.getAgentSkills.mockResolvedValue({ ok: true, count: 0, skills: [] });
    mockedApi.getMcpConfig.mockResolvedValue({
      config_path: 'mcp_config.json',
      servers: [
        {
          name: 'filesystem',
          mode: 'stdio',
          editable: false,
          classification: 'official_stdio',
          config: {
            command: 'npx',
            args: ['-y', '@modelcontextprotocol/server-filesystem', 'D:\\mirror_mcp'],
            timeout: 60,
          },
        },
      ],
      protected_servers: ['filesystem'],
    } as any);
    mockedApi.getRuntimeRequests.mockResolvedValue({ ok: true, journal_path: 'journal.json', count: 0, limit: 40, status_counts: {}, items: [] } as any);
    mockedApi.getAgentTasks.mockResolvedValue({ ok: true, count: 0, status_counts: {}, items: [] } as any);
    mockedApi.getAgentOperationApprovals.mockResolvedValue({ ok: true, count: 0, items: [] } as any);
    mockedApi.createAgentTask.mockResolvedValue({
      ok: true,
      task: {
        task_id: 'agent-task-created',
        client_id: 'client-a',
        goal: 'hello memory',
        mode: 'agent',
        status: 'running',
        created_at: '2026-04-17T01:00:00Z',
        updated_at: '2026-04-17T01:00:00Z',
        plan: {},
        steps: [],
        observations: [],
        verification: {},
        result_summary: {},
        source_plane_counts: { mcp: 0, system_op: 0 },
      },
    } as any);
    mockedApi.cancelAgentTask.mockResolvedValue({
      ok: true,
      task: {
        task_id: 'agent-task-created',
        client_id: 'client-a',
        goal: 'hello memory',
        mode: 'agent',
        status: 'cancelled',
        created_at: '2026-04-17T01:00:00Z',
        updated_at: '2026-04-17T01:00:01Z',
        plan: {},
        steps: [],
        observations: [],
        verification: {},
        result_summary: {},
        source_plane_counts: { mcp: 0, system_op: 0 },
      },
    } as any);
    mockedApi.getMcpToolOnboardingAudit.mockResolvedValue(onboardingAudit as any);
    mockedApi.runMcpToolOnboardingSelfTests.mockResolvedValue(onboardingRun as any);
    mockedApi.previewWorkspaceContext.mockResolvedValue({
      ok: true,
      context_chars: 0,
      preview: '',
      metadata: {},
      agent_profile: {},
      commands: [],
    } as any);
    mockedApi.uploadFile.mockResolvedValue({
      success: true,
      filename: 'uploaded.txt',
      original_filename: 'notes.txt',
      file_path: 'D:\\mirror_mcp\\web_interface\\backend\\uploads\\uploaded.txt',
      size: 20,
      mime_type: 'text/plain',
      content_type: 'text/plain',
      parse_status: 'parsed',
      parse_mode: 'full_text',
      parser: 'utf8_text',
      preview_text: 'visible attachment text',
      full_text_chars: 20,
      visible_text_chars: 20,
      preview_truncated: false,
      parse_error: null,
    } as any);
  });

  afterEach(() => {
    (global as any).WebSocket = originalWebSocket;
    window.HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
  });

  it('uses bootstrap plus websocket runtime status to send a chat request', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await waitFor(() => {
      expect(screen.getByRole('textbox')).not.toBeDisabled();
    });

    await user.type(screen.getByRole('textbox'), 'hello memory');
    const sendButton = screen.getByRole('button', { name: /Send message|发送消息|Run tool|运行工具/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('"type":"chat"') && payload.includes('hello memory'))).toBe(true);
    });
  });

  it('registers an agent task in parallel when agent mode is enabled', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('mcp_chat_settings', JSON.stringify({
      agentModeEnabled: true,
      agentModeProfile: 'agent',
      language: 'zh',
    }));

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await user.type(screen.getByRole('textbox'), 'hello memory');
    const sendButton = screen.getByRole('button', { name: /Send message|发送消息|Run tool|运行工具/i });
    await user.click(sendButton);

    await waitFor(() => {
      expect(mockedApi.createAgentTask).toHaveBeenCalledWith(expect.objectContaining({
        goal: 'hello memory',
        mode: 'agent',
      }));
    });
  });

  it('starts a new chat with a fresh websocket session and clears current messages', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const firstSocket = TestWebSocket.instances[0];
    await act(async () => {
      firstSocket.open();
      firstSocket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await user.type(screen.getByRole('textbox'), 'temporary conversation');
    const sendButton = screen.getByRole('button', { name: /Send message|\u53d1\u9001\u6d88\u606f|Run tool|\u8fd0\u884c\u5de5\u5177/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('temporary conversation')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /New chat options|\u65b0\u804a\u5929\u9009\u9879/i }));
    await user.click(screen.getByRole('menuitem', { name: /New chat|\u65b0\u804a\u5929/i }));

    await waitFor(() => {
      expect(screen.queryByText('temporary conversation')).not.toBeInTheDocument();
    });

    await waitFor(() => {
      expect(TestWebSocket.instances.length).toBeGreaterThan(1);
    });
  });

  it('clears only the current window without starting a new websocket session', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const firstSocket = TestWebSocket.instances[0];
    await act(async () => {
      firstSocket.open();
      firstSocket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await user.type(screen.getByRole('textbox'), 'window only conversation');
    const sendButton = screen.getByRole('button', { name: /Send message|\u53d1\u9001\u6d88\u606f|Run tool|\u8fd0\u884c\u5de5\u5177/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);

    await waitFor(() => {
      expect(screen.getByText('window only conversation')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /New chat options|\u65b0\u804a\u5929\u9009\u9879/i }));
    await user.click(screen.getByRole('menuitem', { name: /Clear current window only|\u4ec5\u6e05\u7a7a\u5f53\u524d\u7a97\u53e3/i }));

    await waitFor(() => {
      expect(screen.queryByText('window only conversation')).not.toBeInTheDocument();
    });

    expect(TestWebSocket.instances).toHaveLength(1);
  });

  it('honors empty runtime MCP snapshots instead of falling back to stale bootstrap tools', async () => {
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: [],
            available_tools: [],
            tools_count: 0,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/MCP: 0\/1/)).toBeInTheDocument();
    });
    expect(screen.getByText(TOOLS_ZERO_LABEL)).toBeInTheDocument();
  });

  it('hides attachment body text before sending while keeping transparency status', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    const file = new File(['visible attachment text'], 'notes.txt', { type: 'text/plain' });
    const attachmentInput = screen.getByTestId('attachment-input') as HTMLInputElement;
    await user.upload(attachmentInput, file);

    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());
    expect(screen.getByText(FILE_BODY_HIDDEN_LABEL)).toBeInTheDocument();
    expect(screen.queryByText('visible attachment text')).not.toBeInTheDocument();
  });
  it('warns when only truncated attachment text will be visible to the model', async () => {
    mockedApi.uploadFile.mockResolvedValueOnce({
      success: true,
      filename: 'truncated.txt',
      original_filename: 'large-notes.txt',
      file_path: 'D:\\mirror_mcp\\web_interface\\backend\\uploads\\truncated.txt',
      size: 5000,
      mime_type: 'text/plain',
      content_type: 'text/plain',
      parse_status: 'parsed',
      parse_mode: 'full_text',
      parser: 'utf8_text',
      preview_text: 'first visible chunk only',
      full_text_chars: 5000,
      visible_text_chars: 1200,
      preview_truncated: true,
      parse_error: null,
    } as any);

    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [{ server: 'filesystem', name: 'list_directory', display_name: 'list_directory' }],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    const file = new File(['large attachment body'], 'large-notes.txt', { type: 'text/plain' });
    const attachmentInput = screen.getByTestId('attachment-input') as HTMLInputElement;
    await user.upload(attachmentInput, file);

    await waitFor(() => expect(mockedApi.uploadFile).toHaveBeenCalled());
    expect(screen.getByText(TRUNCATION_WARNING_LABEL)).toBeInTheDocument();
    expect(screen.getByText(FILE_BODY_HIDDEN_LABEL)).toBeInTheDocument();
    expect(screen.queryByText('first visible chunk only')).not.toBeInTheDocument();

    const attachmentRows = screen.getAllByTestId('pending-attachment-row');
    const attachmentRow = attachmentRows.find((row) => within(row).queryByText('large-notes.txt')) as HTMLElement | undefined;
    expect(attachmentRow).toBeDefined();
    if (!attachmentRow) {
      throw new Error('Expected pending attachment row for large-notes.txt');
    }
    expect(within(attachmentRow).getByText(/Extracted chars|\u539f\u59cb\u53ef\u63d0\u53d6\u5b57\u7b26/i)).toBeInTheDocument();
    expect(within(attachmentRow).getByText(/Visible to model|\u6a21\u578b\u53ef\u89c1\u5b57\u7b26/i)).toBeInTheDocument();
  });

  it('infers only path for read_file attachments and does not leak file paths into numeric head or tail', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [
              { server: 'filesystem', name: 'list_directory', display_name: 'list_directory' },
              { server: 'filesystem', name: 'read_file', display_name: 'read_file' },
            ],
            tools_count: 2,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    const file = new File(['visible attachment text'], 'notes.txt', { type: 'text/plain' });
    const attachmentInput = screen.getByTestId('attachment-input') as HTMLInputElement;
    await user.upload(attachmentInput, file);

    await waitFor(() => {
      expect(mockedApi.uploadFile).toHaveBeenCalled();
    });

    await user.type(screen.getByRole('textbox'), '@filesystem.read_file please inspect this attachment');
    const sendButton = screen.getByRole('button', { name: /Send message|发送消息|Run tool|运行工具/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);
    await user.click(await screen.findByRole('button', { name: 'confirm tool call' }));

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('"type":"tool_call"') && payload.includes('"tool_name":"read_file"'))).toBe(true);
    });

    const toolPayloadRaw = socket.sent.find((payload) => payload.includes('"type":"tool_call"') && payload.includes('"tool_name":"read_file"'));
    expect(toolPayloadRaw).toBeTruthy();
    const toolPayload = JSON.parse(toolPayloadRaw as string);
    expect(toolPayload.arguments.path).toContain('uploaded.txt');
    expect(toolPayload.arguments.head).toBeUndefined();
    expect(toolPayload.arguments.tail).toBeUndefined();
  });

  it('prefers uploaded workspace attachment path over external message path for filesystem reads', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [
              { server: 'filesystem', name: 'read_file', display_name: 'read_file' },
            ],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    const file = new File(['resume body'], 'resume.txt', { type: 'text/plain' });
    const attachmentInput = screen.getByTestId('attachment-input') as HTMLInputElement;
    await user.upload(attachmentInput, file);

    await waitFor(() => {
      expect(mockedApi.uploadFile).toHaveBeenCalled();
    });

    await user.type(screen.getByRole('textbox'), '@filesystem.read_file please inspect C:\\Users\\cys56\\Documents\\resume\\resume.txt');
    const sendButton = screen.getByRole('button', { name: /Send message|发送消息|Run tool|运行工具/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);
    await user.click(await screen.findByRole('button', { name: 'confirm tool call' }));

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('\"type\":\"tool_call\"') && payload.includes('\"tool_name\":\"read_file\"'))).toBe(true);
    });

    const toolPayloadRaw = socket.sent.find((payload) => payload.includes('\"type\":\"tool_call\"') && payload.includes('\"tool_name\":\"read_file\"'));
    expect(toolPayloadRaw).toBeTruthy();
    const toolPayload = JSON.parse(toolPayloadRaw as string);
    expect(toolPayload.arguments.path).toBe('D:\\mirror_mcp\\web_interface\\backend\\uploads\\uploaded.txt');
    expect(toolPayload.arguments.path).not.toContain('C:\\Users\\cys56\\Documents\\resume');
  });

  it('infers workspace @path input as filesystem path argument', async () => {
    const user = userEvent.setup();
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [
              { server: 'filesystem', name: 'read_file', display_name: 'read_file' },
            ],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await user.type(screen.getByRole('textbox'), '@filesystem.read_file 分析 @./src/index.ts');
    const sendButton = screen.getByRole('button', { name: /Send message|发送消息|Run tool|运行工具/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);
    await user.click(await screen.findByRole('button', { name: 'confirm tool call' }));

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('"type":"tool_call"') && payload.includes('"tool_name":"read_file"'))).toBe(true);
    });

    const toolPayloadRaw = socket.sent.find((payload) => payload.includes('"type":"tool_call"') && payload.includes('"tool_name":"read_file"'));
    expect(toolPayloadRaw).toBeTruthy();
    const toolPayload = JSON.parse(toolPayloadRaw as string);
    expect(toolPayload.arguments.path).toBe('./src/index.ts');
  });

  it('sends workspace context when requesting MCP status for workspace-driven runtime', async () => {
    window.localStorage.setItem('mcp_chat_settings', JSON.stringify({
      enableWorkspaceContext: true,
      workspaceContextRoot: 'D:\\project',
      workspaceContextAgentName: 'project-assistant',
      workspaceContextIncludeAgentProfile: true,
      workspaceContextIncludeMemoryFile: true,
      workspaceContextIncludeChatlogs: false,
    }));
    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
    });

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('"type":"get_mcp_status"'))).toBe(true);
    });

    const statusPayloadRaw = [...socket.sent].reverse().find((payload) => payload.includes('"type":"get_mcp_status"'));
    expect(statusPayloadRaw).toBeTruthy();
    const statusPayload = JSON.parse(statusPayloadRaw as string);
    expect(statusPayload.workspace_context).toBeDefined();
    expect(statusPayload.workspace_context.workspace_root).toBe('D:\\project');
    expect(statusPayload.workspace_context.agent_name).toBe('project-assistant');
  });

  it('shows the agent runtime bar when agent mode is enabled without active tasks', async () => {
    window.localStorage.setItem('mcp_chat_settings', JSON.stringify({
      agentModeEnabled: true,
      agentModeProfile: 'agent',
    }));

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByTestId('agent-runtime-bar')).toBeInTheDocument();
    });
  });

  it('sends workspace agent slash command metadata with normal chat messages', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('mcp_chat_settings', JSON.stringify({
      enableWorkspaceContext: true,
      workspaceContextRoot: 'D:\\project',
      workspaceContextAgentName: 'project-assistant',
      workspaceContextIncludeAgentProfile: true,
      workspaceContextIncludeMemoryFile: true,
      workspaceContextIncludeChatlogs: false,
    }));
    mockedApi.previewWorkspaceContext.mockResolvedValue({
      ok: true,
      context_chars: 120,
      preview: '[Workspace Agent Profile]',
      metadata: {},
      agent_profile: {
        agent_name: 'project-assistant',
        allowMCPs: ['filesystem'],
      },
      commands: [
        { name: 'review', description: 'Review code' },
      ],
    } as any);

    render(<ChatInterface />);

    await waitFor(() => {
      expect(screen.getByText('Test Model')).toBeInTheDocument();
    });

    const socket = TestWebSocket.instances[0];
    await act(async () => {
      socket.open();
      socket.onmessage?.({
        data: JSON.stringify({
          type: 'runtime_status_update',
          providers_ready: true,
          mcp: {
            connected_servers: ['filesystem'],
            available_tools: [
              { server: 'filesystem', name: 'read_file', display_name: 'read_file' },
            ],
            tools_count: 1,
          },
          tem: { mode: 'full_tem' },
        }),
      });
    });

    await user.type(screen.getByRole('textbox'), '/review @./src/index.ts');
    const sendButton = screen.getByRole('button', { name: /发送消息|Send message|Run tool/i });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    await user.click(sendButton);

    await waitFor(() => {
      expect(socket.sent.some((payload) => payload.includes('"type":"chat"') && payload.includes('"workspace_agent_command":"review"'))).toBe(true);
    });

    const chatPayloadRaw = socket.sent.find((payload) => payload.includes('"type":"chat"') && payload.includes('"workspace_agent_command":"review"'));
    expect(chatPayloadRaw).toBeTruthy();
    const chatPayload = JSON.parse(chatPayloadRaw as string);
    expect(chatPayload.workspace_agent_command).toBe('review');
    expect(chatPayload.workspace_context.workspace_root).toBe('D:\\project');
    expect(chatPayload.workspace_context.agent_name).toBe('project-assistant');
  });
});

