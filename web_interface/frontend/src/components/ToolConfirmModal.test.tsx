import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ToolConfirmModal from './ToolConfirmModal';
import { I18nProvider } from '../i18n/I18nProvider';
import { ChatSettings } from '../types';

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

describe('ToolConfirmModal', () => {
  it('offers schema default and attachment candidate quick actions', async () => {
    const user = userEvent.setup();
    const onConfirm = jest.fn();

    render(
      <I18nProvider settings={settings}>
        <ToolConfirmModal
          isOpen
          onConfirm={onConfirm}
          onCancel={jest.fn()}
          initialArgs={{}}
          suggestedFields={[]}
          attachments={[
            {
              filename: 'uploaded.txt',
              original_filename: 'notes.txt',
              file_path: 'D:\\mirror_mcp\\uploads\\uploaded.txt',
              url: 'http://127.0.0.1:8000/api/uploads/uploaded.txt',
              size: 12,
            },
          ]}
          tool={{
            server: 'filesystem',
            name: 'read_text_file',
            display_name: 'read_text_file',
            description: 'Read a text file',
            input_schema: {
              properties: {
                path: {
                  type: 'string',
                  default: 'D:\\mirror_mcp\\README.md',
                },
              },
              required: ['path'],
            },
          }}
        />
      </I18nProvider>,
    );

    await user.click(screen.getByRole('button', { name: /Use schema default/i }));
    expect(screen.getByDisplayValue('D:\\mirror_mcp\\README.md')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Use attachment: notes\.txt/i }));
    expect(screen.getByDisplayValue('D:\\mirror_mcp\\uploads\\uploaded.txt')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Confirm tool call/i }));
    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        path: 'D:\\mirror_mcp\\uploads\\uploaded.txt',
      }),
    );
  });
});
