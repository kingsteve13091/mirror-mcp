import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import SettingsPanel from './SettingsPanel';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import {
  ChatSettings,
  ConnectionStatus,
  RuntimeProviderConfig,
  SystemBootstrap,
} from '../types';

const runtimeProviderConfig: RuntimeProviderConfig = {
  credential_mode: 'session_only',
  siliconflow_api_key: '',
  siliconflow_base_url: 'https://api.siliconflow.cn/v1',
  openrouter_api_key: '',
  openrouter_base_url: 'https://openrouter.ai/api/v1',
  default_model: '',
  custom_models: [],
};

const bootstrap: SystemBootstrap = {
  status: 'ok',
  timestamp: '2026-04-13T00:00:00Z',
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
        description: 'Model used by the i18n regression test',
        type: 'text',
        max_tokens: 4096,
        provider: 'openrouter',
      },
    ],
  },
  agent_skills: {
    count: 1,
    skills: [
      {
        id: 'tem-research-review',
        name: 'TEM Research Reviewer',
        description: 'Review Tool Execution Memory claims.',
        trigger: 'manual',
        source_path: 'skills/tem-research-review/SKILL.md',
        root_path: 'skills/tem-research-review',
        body_preview: 'Review TEM evidence carefully.',
        body_length: 29,
        compatibility: ['anthropic-skills', 'agentskills'],
        allowed_tools: ['memory-plane', 'tem'],
        metadata: {
          display_name: 'TEM Research Reviewer',
        },
        license: 'project-local',
        resources: [],
        diagnostics: [],
        activation_mode: 'manual',
        scopes: ['chat'],
        platform_targets: [],
        allowed_mcp_servers: [],
        allowed_toolsets: [],
        preferred_models: [],
        workspace_patterns: [],
        input_patterns: [],
        action_templates: [],
        recovery_policies: [],
        visibility: 'normal',
        requires_confirmation: false,
        runtime_hints: {},
        external_root: false,
      },
    ],
    roots: [],
    failed: [],
  },
  mcp: {
    available: true,
    connected_servers: ['filesystem'],
    tools: [],
    tools_count: 0,
    servers: {
      servers: [],
      total_servers: 1,
      connected_servers: 1,
      total_tools: 0,
      total_resources: 0,
      total_prompts: 0,
      last_update: '2026-04-13T00:00:00Z',
      fastmcp_available: true,
    },
    audit: {
      ok: true,
      errors: [],
      checks: {},
      server_catalog: [],
    },
  },
  tem: {
    mode: 'full_tem',
    supported_modes: ['full_tem'],
    flags: {},
  },
};

const connectionStatus: ConnectionStatus = {
  status: 'connected',
};

const SettingsPanelHarness = () => {
  const [settings, setSettings] = useState<ChatSettings>({
    ...DEFAULT_CHAT_SETTINGS,
    language: 'zh',
  });

  return (
    <I18nProvider settings={settings}>
      <SettingsPanel
        settings={settings}
        onSettingsChange={setSettings}
        onClose={jest.fn()}
        onResetLocalSettings={jest.fn()}
        availableTools={[]}
        bootstrap={bootstrap}
        selectedModel="test-model"
        connectionStatus={connectionStatus}
        onRefreshRuntime={jest.fn()}
        onTemModeChange={jest.fn()}
        onReloadRuntimeParams={jest.fn()}
        temModeLoading={false}
        runtimeReloadLoading={false}
        notice={null}
        runtimeProviderConfig={runtimeProviderConfig}
        runtimeProviderState={null}
        providerConfigLoading={false}
        onRunOnboardingGate={jest.fn()}
      />
    </I18nProvider>
  );
};

describe('SettingsPanel i18n regression', () => {
  it('renders the localized settings shell without crashing', async () => {
    render(<SettingsPanelHarness />);

    expect(screen.queryByText('System Settings')).not.toBeInTheDocument();
    expect(screen.queryByText('Runtime Panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('run-onboarding-gate')).toBeInTheDocument();
    expect(screen.getByText('本地体验设置')).toBeInTheDocument();
    expect(screen.getByText('语言')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '中文' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'English' })).toBeInTheDocument();
    expect(screen.getByText('主题')).toBeInTheDocument();
    expect(screen.getByText('手动工具调用确认')).toBeInTheDocument();
    expect(screen.getByText('高级调试轨迹')).toBeInTheDocument();
    expect(screen.getByText('自定义系统提示词')).toBeInTheDocument();
    expect(screen.getByText('Agent 运行时')).toBeInTheDocument();
  });

  it('shows the one-click onboarding gate entry and triggers it', async () => {
    const user = userEvent.setup();
    const onRunOnboardingGate = jest.fn();

    render(
      <I18nProvider settings={{ ...DEFAULT_CHAT_SETTINGS, language: 'zh' }}>
        <SettingsPanel
          settings={{ ...DEFAULT_CHAT_SETTINGS, language: 'zh' }}
          onSettingsChange={jest.fn()}
          onClose={jest.fn()}
          onResetLocalSettings={jest.fn()}
          availableTools={[]}
          bootstrap={bootstrap}
          selectedModel="test-model"
          connectionStatus={connectionStatus}
          onRefreshRuntime={jest.fn()}
          onTemModeChange={jest.fn()}
          onReloadRuntimeParams={jest.fn()}
          temModeLoading={false}
          runtimeReloadLoading={false}
          notice={null}
          runtimeProviderConfig={runtimeProviderConfig}
          runtimeProviderState={null}
          providerConfigLoading={false}
          onRunOnboardingGate={onRunOnboardingGate}
        />
      </I18nProvider>,
    );

    expect(screen.getByTestId('run-onboarding-gate')).toBeInTheDocument();
    await user.click(screen.getByTestId('run-onboarding-gate'));

    expect(onRunOnboardingGate).toHaveBeenCalledTimes(1);
  });
});
