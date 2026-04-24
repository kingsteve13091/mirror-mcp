import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MessageBubble from './MessageBubble';
import { I18nProvider } from '../i18n/I18nProvider';
import { ChatMessage, ChatSettings } from '../types';

jest.mock('react-markdown', () => ({
  __esModule: true,
  default: ({ children }: any) => {
    const React = require('react');
    return React.createElement('div', null, children);
  },
}));

jest.mock('remark-gfm', () => ({
  __esModule: true,
  default: () => null,
}));

const settings: ChatSettings = {
  dark_mode: false,
  confirmToolCalls: true,
  showAdvancedDebugTraces: false,
  agentModeEnabled: false,
  agentModeProfile: 'chat',
  language: 'en',
  enabledSkillIds: [],
  enableCustomSystemPrompt: false,
  customSystemPrompt: '',
  enableWorkspaceContext: false,
  workspaceContextRoot: '',
  workspaceContextAgentName: '',
  workspaceContextIncludeAgentProfile: true,
  workspaceContextIncludeMemoryFile: true,
  workspaceContextIncludeChatlogs: false,
  sessionAllowMCPs: [],
  toolPolicyEnabled: true,
  toolPolicyDefaultAction: 'allow',
  toolPolicyServerRules: '',
  toolPolicyToolRules: '',
  toolPolicySystemRules: '',
  toolPolicyDenyRiskyWritePaths: true,
  autoToolRoutingMode: 'memory_plane_plus_fallback',
};

const renderBubble = (message: ChatMessage) => render(
  <I18nProvider settings={settings}>
    <MessageBubble message={message} />
  </I18nProvider>,
);

describe('MessageBubble tool result card', () => {
  let writeTextMock: jest.Mock;
  let execCommandMock: jest.Mock;

  beforeEach(() => {
    writeTextMock = jest.fn().mockResolvedValue(undefined);
    execCommandMock = jest.fn().mockReturnValue(true);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: writeTextMock,
      },
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommandMock,
    });
  });

  it('renders tool result sections separately and supports section copy', async () => {
    const user = userEvent.setup();
    const message: ChatMessage = {
      id: 'tool-result-1',
      type: 'system',
      content: 'Tool result: filesystem.read_text_file\n\nHello from file',
      timestamp: new Date().toISOString(),
      metadata: {
        tool_name: 'read_text_file',
        server_name: 'filesystem',
        arguments: {
          path: 'D:\\mirror_mcp\\README.md',
          head: 5,
        },
        result: {
          success: true,
          result: 'Hello from file',
        },
        run_trace: {
          kind: 'tool_call',
          server_name: 'filesystem',
          tool_name: 'read_text_file',
          argument_keys: ['head', 'path'],
          success: true,
          latency_ms: 12.5,
        },
      },
    };

    renderBubble(message);

    expect(screen.getByText('Tool call')).toBeInTheDocument();
    expect(screen.getByText('filesystem.read_text_file')).toBeInTheDocument();
    await user.click(screen.getByTestId('toggle-tool-result-card'));
    expect(screen.getByText('Arguments')).toBeInTheDocument();
    expect(screen.getByText('Result')).toBeInTheDocument();
    const preBlocks = screen.getAllByText((_, element) => element?.tagName.toLowerCase() === 'pre');
    expect(preBlocks.some((block) => block.textContent?.includes('"path": "D:\\\\mirror_mcp\\\\README.md"'))).toBe(true);
    expect(screen.getAllByText('Hello from file').length).toBeGreaterThan(0);

    const resultSection = screen.getByTestId('tool-section-result');
    expect(within(resultSection).getByTestId('copy-tool-section-result')).toBeInTheDocument();
  });

  it('renders error reason in a separate section for failed tool calls', async () => {
    const user = userEvent.setup();
    const message: ChatMessage = {
      id: 'tool-result-2',
      type: 'error',
      content: 'Tool failed',
      timestamp: new Date().toISOString(),
      metadata: {
        tool_name: 'read_file',
        server_name: 'filesystem',
        arguments: {
          path: '',
        },
        result: {
          success: false,
          error_type: 'InputValidationError',
          error: 'Missing required arguments',
        },
        run_trace: {
          kind: 'tool_call',
          server_name: 'filesystem',
          tool_name: 'read_file',
          argument_keys: ['path'],
          success: false,
        },
      },
    };

    renderBubble(message);

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('This real tool call failed. The error reason is available in details.')).toBeInTheDocument();
    await user.click(screen.getByTestId('toggle-tool-result-card'));
    expect(screen.getAllByText('Error').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/InputValidationError/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Missing required arguments/).length).toBeGreaterThan(0);
  });

  it('hides attachment body text in tool result cards when a filesystem read targets an uploaded attachment', async () => {
    const user = userEvent.setup();
    const message: ChatMessage = {
      id: 'tool-result-3',
      type: 'assistant',
      content: 'UploadSummary: FINAL_MARKER found.',
      timestamp: new Date().toISOString(),
      attachments: [
        {
          filename: 'uploaded.txt',
          original_filename: 'resume.txt',
          url: 'http://127.0.0.1:8000/api/uploads/uploaded.txt',
          file_path: 'D:\\mirror_mcp\\web_interface\\backend\\uploads\\uploaded.txt',
          size: 128,
          mime_type: 'text/plain',
          is_image: false,
          parse_status: 'parsed',
          preview_text: 'attachment body preview',
          preview_truncated: true,
          full_text_chars: 1024,
          visible_text_chars: 300,
        },
      ],
      metadata: {
        tool_name: 'read_text_file',
        server_name: 'filesystem',
        arguments: {
          path: 'D:\\mirror_mcp\\web_interface\\backend\\uploads\\uploaded.txt',
        },
        result: {
          success: true,
          result: 'FINAL_MARKER: outside-upload-verification-success',
        },
        run_trace: {
          kind: 'tool_call',
          server_name: 'filesystem',
          tool_name: 'read_text_file',
          argument_keys: ['path'],
          success: true,
          latency_ms: 24.5,
        },
      },
    };

    renderBubble(message);

    expect(screen.getByText('Tool call')).toBeInTheDocument();
    await user.click(screen.getByTestId('toggle-tool-result-card'));
    expect(screen.getByText('Result')).toBeInTheDocument();
    expect(screen.getByText(/Attachment body text was parsed, but the message bubble hides the file body/i)).toBeInTheDocument();
    expect(screen.queryByText('FINAL_MARKER: outside-upload-verification-success')).not.toBeInTheDocument();
  });

  it('keeps tool detail sections collapsed by default and expands on demand', async () => {
    const user = userEvent.setup();
    const message: ChatMessage = {
      id: 'tool-result-4',
      type: 'system',
      content: 'Tool result: fetch.fetch',
      timestamp: new Date().toISOString(),
      metadata: {
        tool_name: 'fetch',
        server_name: 'fetch',
        arguments: {
          url: 'https://example.com',
        },
        result: {
          success: true,
          result: 'Example Domain',
        },
        run_trace: {
          kind: 'tool_call',
          server_name: 'fetch',
          tool_name: 'fetch',
          success: true,
          latency_ms: 48.2,
        },
      },
    };

    renderBubble(message);

    expect(screen.getByText('Result summary')).toBeInTheDocument();
    expect(screen.getByText('Example Domain')).toBeInTheDocument();
    expect(screen.queryByTestId('tool-section-arguments')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('toggle-tool-result-card'));

    expect(screen.getByTestId('tool-section-arguments')).toBeInTheDocument();
    expect(screen.getByTestId('tool-section-result')).toBeInTheDocument();
  });
});

describe('MessageBubble image rendering', () => {
  it('renders generated assistant images inside the assistant bubble', () => {
    const message: ChatMessage = {
      id: 'assistant-image-1',
      type: 'assistant',
      content: 'Here is the generated image.',
      timestamp: new Date().toISOString(),
      image_paths: ['https://example.com/generated-image.png'],
      metadata: {
        model_name: 'Image Model',
        generated_images: [
          {
            url: 'https://example.com/generated-image.png',
            alt: 'Generated result',
            mime_type: 'image/png',
            source: 'model',
          },
        ],
      },
    };

    renderBubble(message);

    const renderedImage = screen.getByRole('img', { name: 'Generated result' });
    expect(renderedImage).toBeInTheDocument();
    expect(renderedImage).toHaveAttribute('src', 'https://example.com/generated-image.png');
    expect(screen.getByText('Here is the generated image.')).toBeInTheDocument();
  });
});

describe('MessageBubble memory card', () => {
  it('renders compact memory governance by default without advanced debug traces', () => {
    const message: ChatMessage = {
      id: 'memory-card-1',
      type: 'assistant',
      content: 'I used the remembered route and summarized the file.',
      timestamp: new Date().toISOString(),
      metadata: {
        memory_plane: {
          timestamp: new Date().toISOString(),
          routing: {
            selected_tools: ['filesystem.read_text_file'],
            router_type: 'memory_aware',
            scores: [
              {
                tool_name: 'filesystem.read_text_file',
                final_score: 0.72,
              },
            ],
          },
          retention: {},
          forgetting: {},
          attribution: [
            {
              source: 'recipe',
              item_id: 'r1',
              label: 'Read local text file',
              score: 0.8,
              freshness: 0.9,
              rationale: 'matched task',
            },
          ],
        },
        causal_trace: {
          selected_tool: 'filesystem.read_text_file',
          routing_candidates: ['filesystem.read_text_file'],
          recipe_memory_used: true,
          guard_memory_used: false,
          context_summary_used: true,
          counterfactual_without_recipe: 'would prefer fetch.fetch',
          counterfactual_without_guard: 'same',
          counterfactual_without_summary: 'same',
          blocked: false,
          success: true,
          significant_causal_effects: ['recipe'],
        },
        recipe_preflight: {
          decision: 'reuse',
          reason: 'similar successful recipe',
        },
      },
    };

    renderBubble(message);

    const memoryCard = screen.getByTestId('memory-card');
    expect(within(memoryCard).getByText('Memory')).toBeInTheDocument();
    expect(within(memoryCard).getByText('Applied')).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Route: filesystem\.read_text_file/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Main evidence: Read local text file/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Recipe: reuse/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Guard: not triggered/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Summary: used/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Attribution: 1/)).toBeInTheDocument();
    expect(within(memoryCard).getByText(/Effects: 1/)).toBeInTheDocument();
    expect(screen.queryByText(/similar successful recipe/)).not.toBeInTheDocument();
  });
});
