import React, { useMemo, useState } from 'react';
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Database,
  Cpu,
  Bot,
  Eye,
  KeyRound,
  Languages,
  Moon,
  RefreshCw,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  X,
} from 'lucide-react';
import {
  AgentSkillExternalConfig,
  AgentSkillSummary,
  AgentSkillRootSummary,
  AvailableTool,
  ChatSettings,
  ConnectionStatus,
  MCPServerConfigForm,
  MCPServerConfigItem,
  MCPToolOnboardingAuditReport,
  MCPToolOnboardingSelfTestRunReport,
  AutoToolRoutingState,
  ProviderConnectivityResult,
  RuntimeProviderConfig,
  RuntimeProviderState,
  RuntimeView,
  SystemBootstrap,
  ToolPolicyState,
  WorkspaceAgentProfile,
  WorkspaceMcpState,
} from '../types';
import { useI18n } from '../i18n/I18nProvider';

interface SettingsPanelProps {
  settings: ChatSettings;
  onSettingsChange: (settings: ChatSettings) => void;
  onClose: () => void;
  onResetLocalSettings: () => void;
  availableTools: AvailableTool[];
  runtimeView?: RuntimeView;
  bootstrap: SystemBootstrap | null;
  selectedModel: string;
  connectionStatus: ConnectionStatus;
  onRefreshRuntime: () => Promise<void> | void;
  onTemModeChange: (mode: string) => Promise<void> | void;
  onReloadRuntimeParams: () => Promise<void> | void;
  temModeLoading: boolean;
  runtimeReloadLoading: boolean;
  notice: string | null;
  agentSkills?: AgentSkillSummary[];
  agentSkillRoots?: AgentSkillRootSummary[];
  agentSkillFailed?: Array<Record<string, any>>;
  agentSkillsExternalConfig?: AgentSkillExternalConfig | null;
  externalSkillDirsText?: string;
  agentSkillsLoading?: boolean;
  workspaceAgentProfile?: WorkspaceAgentProfile | null;
  workspaceMcpState?: WorkspaceMcpState | null;
  onReloadAgentSkills?: () => Promise<void> | void;
  onExternalSkillDirsTextChange?: (value: string) => void;
  onApplyExternalSkillDirs?: () => Promise<void> | void;
  runtimeProviderConfig?: RuntimeProviderConfig;
  runtimeProviderState?: RuntimeProviderState | null;
  runtimeToolPolicy?: ToolPolicyState | null;
  runtimeAutoToolRouting?: AutoToolRoutingState | null;
  onboardingAudit?: MCPToolOnboardingAuditReport | null;
  onboardingRun?: MCPToolOnboardingSelfTestRunReport | null;
  onboardingAuditLoading?: boolean;
  onboardingRunLoading?: boolean;
  mcpConfigPath?: string;
  mcpConfigItems?: MCPServerConfigItem[];
  mcpConfigForm?: MCPServerConfigForm;
  mcpConfigLoading?: boolean;
  mcpConfigSaving?: boolean;
  mcpConfigDeleting?: string | null;
  onRuntimeProviderConfigChange?: (config: RuntimeProviderConfig) => void;
  onResetRuntimeProviderConfig?: () => void;
  onApplyRuntimeProviders?: () => Promise<void> | void;
  onApplyRuntimeToolPolicy?: () => Promise<void> | void;
  onApplyRuntimeAutoToolRouting?: () => Promise<void> | void;
  onCheckProviderConnectivity?: (
    provider: 'siliconflow' | 'openrouter',
    config: RuntimeProviderConfig,
  ) => Promise<ProviderConnectivityResult>;
  providerConfigLoading?: boolean;
  toolPolicyLoading?: boolean;
  onRefreshMcpConfig?: () => Promise<void> | void;
  onRefreshOnboardingAudit?: () => Promise<void> | void;
  onRunOnboardingSelfTests?: () => Promise<void> | void;
  onRunOnboardingGate?: () => Promise<void> | void;
  onMcpConfigFormChange?: (patch: Partial<MCPServerConfigForm>) => void;
  onMcpConfigNew?: () => void;
  onMcpConfigEdit?: (item: MCPServerConfigItem) => void;
  onMcpConfigSave?: () => Promise<void> | void;
  onMcpConfigDelete?: (serverName: string) => Promise<void> | void;
}

const cardClassName = 'rounded-3xl border border-white/30 bg-white/90 p-5 shadow-lg backdrop-blur-sm dark:border-slate-700/50 dark:bg-slate-800/80';
const inputClassName = 'w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-100';
const SILICONFLOW_CN_BASE_URL = 'https://api.siliconflow.cn/v1';

const normalizeWorkspaceRoot = (value: string | undefined | null) => String(value || '')
  .trim()
  .replace(/\//g, '\\')
  .replace(/\\+$/, '')
  .toLowerCase();

const workspaceStateMatchesRoot = (state: WorkspaceMcpState | undefined | null, workspaceRoot: string) => {
  if (!state) {
    return false;
  }
  const expected = normalizeWorkspaceRoot(workspaceRoot);
  if (!expected) {
    return normalizeWorkspaceRoot(state.workspace_root) === '';
  }
  return normalizeWorkspaceRoot(state.workspace_root) === expected;
};


const SettingsPanel: React.FC<SettingsPanelProps> = ({
  settings,
  onSettingsChange,
  onClose,
  onResetLocalSettings,
  availableTools,
  runtimeView,
  bootstrap,
  selectedModel,
  connectionStatus,
  onRefreshRuntime,
  onTemModeChange,
  onReloadRuntimeParams,
  temModeLoading,
  runtimeReloadLoading,
  notice,
  agentSkills = [],
  agentSkillRoots = [],
  agentSkillFailed = [],
  agentSkillsExternalConfig = null,
  externalSkillDirsText = '',
  agentSkillsLoading = false,
  workspaceAgentProfile = null,
  workspaceMcpState = null,
  onReloadAgentSkills,
  onExternalSkillDirsTextChange,
  onApplyExternalSkillDirs,
  runtimeProviderConfig,
  runtimeToolPolicy,
  runtimeAutoToolRouting,
  onboardingAudit = null,
  onboardingRun = null,
  onboardingAuditLoading = false,
  onboardingRunLoading = false,
  onRuntimeProviderConfigChange,
  onResetRuntimeProviderConfig,
  onApplyRuntimeProviders,
  onApplyRuntimeToolPolicy,
  onApplyRuntimeAutoToolRouting,
  onRefreshOnboardingAudit,
  onRunOnboardingSelfTests,
  onRunOnboardingGate,
  toolPolicyLoading = false,
}) => {
  const { t } = useI18n();
  const [showMemoryPlane, setShowMemoryPlane] = useState(false);
  const [showSkillRuntimeDetails, setShowSkillRuntimeDetails] = useState(false);

  const memoryPlane = bootstrap?.memory_plane;
  const workspaceRootSetting = settings.enableWorkspaceContext ? settings.workspaceContextRoot.trim() : '';
  const effectiveWorkspaceMcpState = useMemo(() => {
    const auditWorkspaceState = onboardingAudit?.workspace_mcp;
    if (workspaceStateMatchesRoot(auditWorkspaceState, workspaceRootSetting)) {
      return auditWorkspaceState || null;
    }
    if (workspaceStateMatchesRoot(workspaceMcpState, workspaceRootSetting)) {
      return workspaceMcpState || null;
    }
    return auditWorkspaceState || workspaceMcpState || null;
  }, [onboardingAudit?.workspace_mcp, workspaceMcpState, workspaceRootSetting]);
  const temModes = useMemo(() => bootstrap?.tem.supported_modes || [], [bootstrap]);
  const showOnboardingAudit = onboardingAuditLoading || onboardingRunLoading || Boolean(onboardingAudit) || Boolean(onboardingRun);
  const onboardingToolsByServer = useMemo(() => {
    const grouped = new Map<string, MCPToolOnboardingAuditReport['tools']>();
    (onboardingAudit?.tools || []).forEach((tool) => {
      const server = tool.server || 'unknown';
      if (!grouped.has(server)) {
        grouped.set(server, []);
      }
      grouped.get(server)?.push(tool);
    });
    return Array.from(grouped.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [onboardingAudit]);
  const onboardingRunLookup = useMemo(() => {
    const lookup = new Map<string, MCPToolOnboardingSelfTestRunReport['results'][number]>();
    (onboardingRun?.results || []).forEach((result) => {
      if (result.tool_key) {
        lookup.set(result.tool_key, result);
      }
    });
    return lookup;
  }, [onboardingRun]);
  const workspaceServerSummaries = useMemo(() => {
    const workspaceServers = (effectiveWorkspaceMcpState?.workspace_servers || [])
      .map((server) => String(server || '').trim())
      .filter(Boolean);
    if (workspaceServers.length === 0) {
      return [];
    }

    return workspaceServers.map((server) => {
      const tools = (onboardingAudit?.tools || []).filter((tool) => String(tool.server || '').trim() === server);
      const latestRuns = tools
        .map((tool) => onboardingRunLookup.get(tool.tool_key))
        .filter((item): item is NonNullable<typeof item> => Boolean(item));
      const passedRuns = latestRuns.filter((item) => item.ok).length;
      const failedRuns = latestRuns.filter((item) => !item.ok && !item.skipped).length;
      const safeSelfTests = tools.filter((tool) => Boolean(tool.self_test?.safe_to_run)).length;
      const autoExecutable = tools.filter((tool) => tool.automation_class === 'auto_executable').length;
      const autoRoutableManual = tools.filter((tool) => tool.automation_class === 'auto_routable_manual_confirm').length;
      const manualOnly = tools.filter((tool) => tool.automation_class === 'manual_only').length;

      return {
        server,
        toolCount: tools.length,
        autoExecutable,
        autoRoutableManual,
        manualOnly,
        safeSelfTests,
        latestRunsCount: latestRuns.length,
        passedRuns,
        failedRuns,
        sampleToolKeys: tools.slice(0, 4).map((tool) => tool.tool_key),
      };
    });
  }, [effectiveWorkspaceMcpState?.workspace_servers, onboardingAudit?.tools, onboardingRunLookup]);
  const workspaceServerDetails = useMemo(() => {
    const workspaceServers = (effectiveWorkspaceMcpState?.workspace_servers || [])
      .map((server) => String(server || '').trim())
      .filter(Boolean);
    if (workspaceServers.length === 0) {
      return [];
    }

    return workspaceServers.map((server) => {
      const tools = (onboardingAudit?.tools || [])
        .filter((tool) => String(tool.server || '').trim() === server)
        .slice()
        .sort((a, b) => String(a.tool_key || '').localeCompare(String(b.tool_key || '')));
      return {
        server,
        tools: tools.map((tool) => ({
          tool,
          latestRun: onboardingRunLookup.get(tool.tool_key),
        })),
      };
    });
  }, [effectiveWorkspaceMcpState?.workspace_servers, onboardingAudit?.tools, onboardingRunLookup]);
  const resolvedToolsCount = runtimeView?.toolsCount ?? bootstrap?.mcp.tools_count ?? availableTools.length;
  const resolvedConnectedServers = runtimeView?.connectedServers.length ?? bootstrap?.mcp.connected_servers.length ?? 0;
  const resolvedTemMode = runtimeView?.temMode || bootstrap?.tem.mode || 'n/a';

  const updateRuntimeConfig = (patch: Partial<RuntimeProviderConfig>) => {
    if (!runtimeProviderConfig || !onRuntimeProviderConfigChange) {
      return;
    }
    onRuntimeProviderConfigChange({
      ...runtimeProviderConfig,
      ...patch,
    });
  };

  const credentialOptions = useMemo(() => [
    {
      id: 'session_only' as const,
      title: t('settings.sessionOnly'),
      description: t('settings.sessionOnlyDesc'),
    },
    {
      id: 'backend_env_only' as const,
      title: t('settings.backendEnvOnly'),
      description: t('settings.backendEnvOnlyDesc'),
    },
    {
      id: 'local_persist' as const,
      title: t('settings.allowLocalSave'),
      description: t('settings.allowLocalSaveDesc'),
    },
  ], [t]);

  const formatConnectionStatus = (status: ConnectionStatus['status']) => {
    switch (status) {
      case 'connected':
        return t('connection.realtimeConnected');
      case 'connecting':
        return t('connection.connecting');
      case 'disconnected':
        return t('connection.disconnected');
      case 'error':
        return t('common.error');
      default:
        return status;
    }
  };

  const systemActionCount = Object.keys(runtimeToolPolicy?.system_actions || {}).length;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/35 backdrop-blur-sm">
      <div className="flex h-full w-full max-w-4xl flex-col overflow-hidden border-l border-white/20 bg-[linear-gradient(180deg,rgba(248,250,252,0.97)_0%,rgba(240,249,255,0.94)_100%)] shadow-2xl dark:border-slate-700/40 dark:bg-[linear-gradient(180deg,rgba(15,23,42,0.98)_0%,rgba(17,24,39,0.96)_100%)]">
        <div className="flex items-center justify-between border-b border-slate-200/80 px-6 py-5 dark:border-slate-700/60">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-sky-700 dark:text-sky-300">
              <SlidersHorizontal className="h-4 w-4" />
              <span>{t('settings.systemSettings')}</span>
            </div>
            <h2 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{t('settings.runtimePanel')}</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('settings.reviewRuntime')}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={settings.language === 'zh' ? '关闭设置面板' : 'Close settings panel'}
            title={settings.language === 'zh' ? '关闭设置面板' : 'Close settings panel'}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="space-y-5">
            {notice && <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200">{notice}</div>}

            <section className={cardClassName}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <Sparkles className="h-4 w-4 text-sky-500" />
                <span>{settings.language === 'zh' ? '本地体验设置' : 'Local Experience'}</span>
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                    <Languages className="h-4 w-4 text-emerald-500" />
                    <span>{settings.language === 'zh' ? '语言' : 'Language'}</span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {([
                      ['zh', '中文'],
                      ['en', 'English'],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => onSettingsChange({ ...settings, language: value })}
                        className={`rounded-2xl px-4 py-2 text-sm font-medium transition ${
                          settings.language === value
                            ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                            : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                    {settings.dark_mode ? <Moon className="h-4 w-4 text-violet-500" /> : <Sun className="h-4 w-4 text-amber-500" />}
                    <span>{settings.language === 'zh' ? '主题' : 'Theme'}</span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => onSettingsChange({ ...settings, dark_mode: false })}
                      className={`rounded-2xl px-4 py-2 text-sm font-medium transition ${
                        !settings.dark_mode
                          ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                          : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800'
                      }`}
                    >
                      {settings.language === 'zh' ? '浅色' : 'Light'}
                    </button>
                    <button
                      type="button"
                      onClick={() => onSettingsChange({ ...settings, dark_mode: true })}
                      className={`rounded-2xl px-4 py-2 text-sm font-medium transition ${
                        settings.dark_mode
                          ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                          : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800'
                      }`}
                    >
                      {settings.language === 'zh' ? '深色' : 'Dark'}
                    </button>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <label className="rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">
                        {settings.language === 'zh' ? '手动工具调用确认' : 'Manual tool confirmation'}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {settings.language === 'zh'
                          ? '用户通过 @server.tool 显式点名工具时，是否先弹出确认框。'
                          : 'Whether explicit @server.tool calls should open a confirmation modal first.'}
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={settings.confirmToolCalls}
                      onChange={(event) => onSettingsChange({ ...settings, confirmToolCalls: event.target.checked })}
                      className="mt-1 h-4 w-4"
                    />
                  </div>
                </label>

                <label className="rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                        <Eye className="h-4 w-4 text-sky-500" />
                        <span>{settings.language === 'zh' ? '高级调试轨迹' : 'Advanced debug traces'}</span>
                      </div>
                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {settings.language === 'zh'
                          ? '默认关闭，只在研究或开发时显示 Memory / 因果 / 研究轨迹。'
                          : 'Off by default. Show memory, causal, and research traces only for research or development.'}
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={settings.showAdvancedDebugTraces}
                      onChange={(event) => onSettingsChange({ ...settings, showAdvancedDebugTraces: event.target.checked })}
                      className="mt-1 h-4 w-4"
                    />
                  </div>
                </label>
              </div>

              <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                <label className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-white">
                      {settings.language === 'zh' ? '自定义系统提示词' : 'Custom system prompt'}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {settings.language === 'zh'
                        ? '作为会话级提示层加入，不替代 Recipe / Guard / Memory Plane。'
                        : 'Injected as a session-level instruction layer without replacing Recipe / Guard / Memory Plane.'}
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={settings.enableCustomSystemPrompt}
                    onChange={(event) => onSettingsChange({ ...settings, enableCustomSystemPrompt: event.target.checked })}
                    className="h-4 w-4"
                  />
                </label>
                <textarea
                  value={settings.customSystemPrompt}
                  onChange={(event) => onSettingsChange({ ...settings, customSystemPrompt: event.target.value })}
                  rows={5}
                  className={`${inputClassName} mt-4`}
                  disabled={!settings.enableCustomSystemPrompt}
                  placeholder={settings.language === 'zh' ? '输入本会话额外系统提示词' : 'Enter additional system instructions for this session'}
                />
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">
                    {settings.language === 'zh' ? '自动工具路由模式' : 'Auto tool routing mode'}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {([
                      ['memory_plane_only', settings.language === 'zh' ? '仅 Memory Plane' : 'Memory Plane only'],
                      ['memory_plane_plus_fallback', settings.language === 'zh' ? 'Memory Plane + fallback' : 'Memory Plane + fallback'],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => onSettingsChange({
                          ...settings,
                          autoToolRoutingMode: value as ChatSettings['autoToolRoutingMode'],
                        })}
                        className={`rounded-2xl px-4 py-2 text-sm font-medium transition ${
                          settings.autoToolRoutingMode === value
                            ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                            : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {runtimeAutoToolRouting && (
                    <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {settings.language === 'zh'
                        ? `后端当前模式：${runtimeAutoToolRouting.mode}`
                        : `Backend mode: ${runtimeAutoToolRouting.mode}`}
                    </div>
                  )}
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="text-sm font-semibold text-slate-900 dark:text-white">
                    {settings.language === 'zh' ? '\u5df2\u542f\u7528\u6280\u80fd' : 'Enabled skills'}
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {settings.language === 'zh'
                      ? '\u6280\u80fd\u662f\u4eba\u5de5\u7f16\u5199\u80fd\u529b\u5305\uff0c\u4e0d\u7b49\u540c\u4e8e Recipe Memory\u3002'
                      : 'Skills are authored capability packages and are not the same as Recipe Memory.'}
                  </div>
                  <div className="mt-3 max-h-44 space-y-2 overflow-y-auto">
                    {agentSkills.length === 0 && (
                      <div className="rounded-2xl border border-dashed border-slate-200 px-3 py-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                        {settings.language === 'zh' ? '\u5f53\u524d\u6ca1\u6709\u53ef\u9009\u6280\u80fd\u3002' : 'No optional skills are currently available.'}
                      </div>
                    )}
                    {agentSkills.map((skill) => {
                      const checked = settings.enabledSkillIds.includes(skill.id);
                      const skillScopes = Array.isArray(skill.scopes) ? skill.scopes : [];
                      const skillAllowedServers = Array.isArray(skill.allowed_mcp_servers) ? skill.allowed_mcp_servers : [];
                      const activationMode = typeof skill.activation_mode === 'string' && skill.activation_mode.trim()
                        ? skill.activation_mode
                        : 'manual';
                      return (
                        <label key={skill.id} className="flex items-start gap-3 rounded-2xl border border-slate-200 px-3 py-3 dark:border-slate-700">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => {
                              const nextIds = event.target.checked
                                ? [...settings.enabledSkillIds, skill.id]
                                : settings.enabledSkillIds.filter((id) => id !== skill.id);
                              onSettingsChange({
                                ...settings,
                                enabledSkillIds: Array.from(new Set(nextIds)),
                              });
                            }}
                            className="mt-1 h-4 w-4"
                          />
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-slate-900 dark:text-white">{skill.name}</div>
                            <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{skill.description}</div>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
                                {settings.language === 'zh' ? `\u6fc0\u6d3b ${activationMode}` : `Activation ${activationMode}`}
                              </span>
                              {skillScopes.slice(0, 3).map((scope) => (
                                <span key={`${skill.id}-scope-${scope}`} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
                                  {scope}
                                </span>
                              ))}
                              {skillAllowedServers.slice(0, 2).map((serverName) => (
                                <span key={`${skill.id}-server-${serverName}`} className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200">
                                  {serverName}
                                </span>
                              ))}
                              {skill.requires_confirmation && (
                                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                                  {settings.language === 'zh' ? '\u9700\u786e\u8ba4' : 'Confirm'}
                                </span>
                              )}
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => setShowSkillRuntimeDetails((prev) => !prev)}
                      className="text-xs font-medium text-sky-600 transition hover:text-sky-700 dark:text-sky-300 dark:hover:text-sky-200"
                    >
                      {showSkillRuntimeDetails
                        ? (settings.language === 'zh' ? '\u6536\u8d77\u6280\u80fd\u8fd0\u884c\u65f6\u8be6\u60c5' : 'Hide skill runtime details')
                        : (settings.language === 'zh' ? '\u67e5\u770b\u6280\u80fd\u8fd0\u884c\u65f6\u8be6\u60c5' : 'Show skill runtime details')}
                    </button>
                    {onReloadAgentSkills && (
                      <button
                        type="button"
                        onClick={() => { void onReloadAgentSkills(); }}
                        className="text-xs font-medium text-slate-500 transition hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                      >
                        {settings.language === 'zh' ? '\u91cd\u8f7d\u6280\u80fd' : 'Reload skills'}
                      </button>
                    )}
                  </div>
                  {showSkillRuntimeDetails && (
                    <div className="mt-3 space-y-3 rounded-2xl border border-dashed border-slate-200 px-3 py-3 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300">
                      <div>
                        <div className="font-medium text-slate-800 dark:text-slate-100">
                          {settings.language === 'zh' ? '\u5916\u90e8\u6280\u80fd\u76ee\u5f55\u914d\u7f6e' : 'External skill directories'}
                        </div>
                        <div className="mt-1 break-all text-[11px] text-slate-500 dark:text-slate-400">
                          {agentSkillsExternalConfig?.path || '.mcp-mirror/skills.json'}
                        </div>
                        <textarea
                          value={externalSkillDirsText}
                          onChange={(event) => onExternalSkillDirsTextChange?.(event.target.value)}
                          rows={3}
                          className={`${inputClassName} mt-2 font-mono text-xs`}
                          placeholder={settings.language === 'zh' ? '每行一个外部 skills 目录路径' : 'One external skills directory per line'}
                          spellCheck={false}
                        />
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => { void onApplyExternalSkillDirs?.(); }}
                            className="rounded-xl bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-800 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
                          >
                            {settings.language === 'zh' ? '\u4fdd\u5b58\u5e76\u91cd\u8f7d\u6280\u80fd' : 'Save and reload skills'}
                          </button>
                          {agentSkillsExternalConfig?.env_value && (
                            <span className="text-[11px] text-slate-500 dark:text-slate-400">
                              {settings.language === 'zh' ? '环境变量也提供了目录。' : 'Environment variable also provides directories.'}
                            </span>
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="font-medium text-slate-800 dark:text-slate-100">
                          {settings.language === 'zh' ? '\u6280\u80fd\u6839\u76ee\u5f55' : 'Skill roots'}
                        </div>
                        <div className="mt-2 space-y-2">
                          {agentSkillRoots.length === 0 && (
                            <div>{settings.language === 'zh' ? '\u5f53\u524d\u6ca1\u6709\u989d\u5916\u7684\u6280\u80fd\u76ee\u5f55\u4fe1\u606f\u3002' : 'No extra skill root information is currently available.'}</div>
                          )}
                          {agentSkillRoots.map((root) => (
                            <div key={String(root.path || 'skill-root')} className="rounded-xl border border-slate-200 px-3 py-2 dark:border-slate-700">
                              <div className="break-all">{String(root.path || '')}</div>
                              <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                                {Boolean(root.exists)
                                  ? (settings.language === 'zh' ? `\u5df2\u53d1\u73b0 ${Number(root.skill_count || 0)} \u4e2a\u6280\u80fd` : `${Number(root.skill_count || 0)} skills discovered`)
                                  : (settings.language === 'zh' ? '\u76ee\u5f55\u4e0d\u5b58\u5728' : 'Directory missing')}
                                {Boolean(root.external) ? ` · ${settings.language === 'zh' ? '\u5916\u90e8\u76ee\u5f55' : 'external'}` : ''}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                      {agentSkillFailed.length > 0 && (
                        <div>
                          <div className="font-medium text-slate-800 dark:text-slate-100">
                            {settings.language === 'zh' ? '\u52a0\u8f7d\u5931\u8d25' : 'Load failures'}
                          </div>
                          <div className="mt-2 space-y-2">
                            {agentSkillFailed.map((item, index) => (
                              <div key={`${item.source_path || 'failed'}-${index}`} className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200">
                                <div className="break-all">{String(item.source_path || item.path || 'Unknown skill source')}</div>
                                <div className="mt-1 break-all text-[11px]">{String(item.error || 'Unknown loader error')}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </section>

            <section className={cardClassName}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <Server className="h-4 w-4 text-emerald-500" />
                <span>{t('settings.runtimeOverview')}</span>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40">
                  <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('settings.connection')}</div>
                  <div className="mt-2 text-sm text-slate-800 dark:text-slate-200">{t('settings.status')} {formatConnectionStatus(connectionStatus.status)}</div>
                  <div className="mt-1 text-sm text-slate-800 dark:text-slate-200">{t('settings.model')} {selectedModel || bootstrap?.models.default || t('common.none')}</div>
                </div>
                <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40">
                  <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">MCP</div>
                  <div className="mt-2 text-sm text-slate-800 dark:text-slate-200">{t('app.tools')} {resolvedToolsCount}</div>
                  <div className="mt-1 text-sm text-slate-800 dark:text-slate-200">{t('settings.servers')} {resolvedConnectedServers}</div>
                  <div className="mt-1 text-sm text-slate-800 dark:text-slate-200">{t('health.temMode')} {resolvedTemMode}</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <button type="button" onClick={() => { void onRefreshRuntime(); }} className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800">
                  <RefreshCw className="h-4 w-4" />
                  <span>{t('settings.refreshSnapshot')}</span>
                </button>
                <button type="button" onClick={() => { void onReloadRuntimeParams(); }} disabled={runtimeReloadLoading} className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800">
                  <Cpu className="h-4 w-4" />
                  <span>{runtimeReloadLoading ? t('settings.reloading') : t('settings.reloadRuntimeParams')}</span>
                </button>
              </div>
            </section>

            <section className={cardClassName}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <Bot className="h-4 w-4 text-violet-500" />
                <span>{settings.language === 'zh' ? 'Agent 运行时' : 'Agent Runtime'}</span>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                {settings.language === 'zh'
                  ? '开启后，聊天仍按原有 MCP 与 Memory Plane 主链执行，同时旁路登记任务计划、系统操作审计与可取消状态。系统操作不会被写入 mcp_config.json。'
                  : 'When enabled, chat still uses the existing MCP and Memory Plane path while also recording task plans, operation audit, and cancellable task state. System operations are not added to mcp_config.json.'}
              </p>
              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                <label className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 dark:text-white">
                        {settings.language === 'zh' ? '启用 Agent 模式' : 'Enable Agent mode'}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {settings.language === 'zh'
                          ? '普通聊天默认关闭；开启后会生成任务记录，但不会自动执行高风险系统命令。'
                          : 'Off by default for clean chat; when enabled it creates task records without auto-running high-risk system commands.'}
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={settings.agentModeEnabled}
                      onChange={(event) => onSettingsChange({ ...settings, agentModeEnabled: event.target.checked })}
                      className="mt-1 h-4 w-4"
                    />
                  </div>
                </label>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <label className="text-sm font-semibold text-slate-900 dark:text-white">
                    {settings.language === 'zh' ? '运行档位' : 'Runtime profile'}
                  </label>
                  <select
                    value={settings.agentModeProfile}
                    onChange={(event) => onSettingsChange({
                      ...settings,
                      agentModeProfile: event.target.value as ChatSettings['agentModeProfile'],
                    })}
                    className={`${inputClassName} mt-3`}
                    disabled={!settings.agentModeEnabled}
                  >
                    <option value="chat">{settings.language === 'zh' ? 'Chat：仅登记轻量任务' : 'Chat: lightweight task record'}</option>
                    <option value="agent">{settings.language === 'zh' ? 'Agent：任务计划 + 审计' : 'Agent: plan + audit'}</option>
                    <option value="research">{settings.language === 'zh' ? 'Research：保留研究轨迹' : 'Research: keep research traces'}</option>
                  </select>
                </div>
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200">
                  <div className="flex items-center gap-2 font-semibold">
                    <ShieldCheck className="h-4 w-4" />
                    <span>{settings.language === 'zh' ? '安全边界' : 'Safety boundary'}</span>
                  </div>
                  <div className="mt-2 text-xs leading-5">
                    {settings.language === 'zh'
                      ? 'MCP 工具仍由工作区服务池自动发现；系统操作走独立 System Operation Plane，并以 source_plane=system_op 审计。'
                      : 'MCP tools remain auto-discovered from workspace server pools. System operations go through a separate System Operation Plane and are audited as source_plane=system_op.'}
                  </div>
                </div>
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                  <label className="text-sm font-semibold text-slate-900 dark:text-white">
                    {settings.language === 'zh' ? '系统操作策略' : 'System operation policy'}
                  </label>
                  <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {settings.language === 'zh'
                      ? '格式为 action=allow|confirm|deny。terminal 和进程控制即使配置为 allow，也会按安全档位要求确认。'
                      : 'Use action=allow|confirm|deny. Terminal and process-control actions still require confirmation in the safety profile.'}
                  </p>
                  <textarea
                    value={settings.toolPolicySystemRules}
                    onChange={(event) => onSettingsChange({ ...settings, toolPolicySystemRules: event.target.value })}
                    rows={7}
                    className={`${inputClassName} mt-3 font-mono`}
                    spellCheck={false}
                  />
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
                  <div className="font-semibold text-slate-900 dark:text-white">
                    {settings.language === 'zh' ? '当前后端策略快照' : 'Current backend policy snapshot'}
                  </div>
                  <div className="mt-3 space-y-1">
                    <div>{settings.language === 'zh' ? '工具策略启用' : 'Tool policy enabled'}: {String(runtimeToolPolicy?.enabled ?? settings.toolPolicyEnabled)}</div>
                    <div>{settings.language === 'zh' ? '默认动作' : 'Default action'}: {runtimeToolPolicy?.default_action || settings.toolPolicyDefaultAction}</div>
                    <div>{settings.language === 'zh' ? '工具规则数' : 'Tool rules'}: {Object.keys(runtimeToolPolicy?.tool_actions || {}).length}</div>
                    <div>{settings.language === 'zh' ? '服务器规则数' : 'Server rules'}: {Object.keys(runtimeToolPolicy?.server_actions || {}).length}</div>
                    <div>{settings.language === 'zh' ? '系统操作规则数' : 'System action rules'}: {systemActionCount}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => { if (onApplyRuntimeToolPolicy) { void onApplyRuntimeToolPolicy(); } }}
                    disabled={toolPolicyLoading}
                    className="mt-4 rounded-2xl bg-slate-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
                  >
                    {toolPolicyLoading
                      ? (settings.language === 'zh' ? '正在应用策略...' : 'Applying policy...')
                      : (settings.language === 'zh' ? '应用工具与系统操作策略' : 'Apply tool and system policy')}
                  </button>
                </div>
              </div>
            </section>

            <section className={cardClassName}>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <KeyRound className="h-4 w-4 text-sky-500" />
                <span>{t('settings.providerRuntime')}</span>
              </div>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                {t('settings.providerRuntimeDesc')}
              </p>

              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2 rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-900/30">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                    <Database className="h-4 w-4 text-emerald-500" />
                    <span>{t('settings.credentialStorageMode')}</span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {t('settings.credentialStorageModeDesc')}
                  </p>
                  <div className="mt-4 grid gap-3 lg:grid-cols-3">
                    {credentialOptions.map((option) => {
                      const active = runtimeProviderConfig?.credential_mode === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          onClick={() => updateRuntimeConfig({ credential_mode: option.id as RuntimeProviderConfig['credential_mode'] })}
                          className={`rounded-2xl border px-4 py-4 text-left transition ${
                            active
                              ? 'border-sky-300 bg-sky-50 dark:border-sky-700/60 dark:bg-sky-950/20'
                              : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-950/40'
                          }`}
                        >
                          <div className="text-sm font-semibold text-slate-900 dark:text-white">{option.title}</div>
                          <div className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{option.description}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('settings.siliconflowApiKey')}
                  </label>
                  <input
                    type="password"
                    value={runtimeProviderConfig?.siliconflow_api_key || ''}
                    onChange={(event) => updateRuntimeConfig({ siliconflow_api_key: event.target.value })}
                    placeholder="sk-..."
                    className={inputClassName}
                    disabled={runtimeProviderConfig?.credential_mode === 'backend_env_only'}
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('settings.openrouterApiKey')}
                  </label>
                  <input
                    type="password"
                    value={runtimeProviderConfig?.openrouter_api_key || ''}
                    onChange={(event) => updateRuntimeConfig({ openrouter_api_key: event.target.value })}
                    placeholder="sk-or-..."
                    className={inputClassName}
                    disabled={runtimeProviderConfig?.credential_mode === 'backend_env_only'}
                  />
                </div>
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('settings.siliconflowBaseUrl')}
                  </label>
                  <input
                    type="text"
                    value={runtimeProviderConfig?.siliconflow_base_url || ''}
                    onChange={(event) => updateRuntimeConfig({ siliconflow_base_url: event.target.value })}
                    placeholder={SILICONFLOW_CN_BASE_URL}
                    className={inputClassName}
                    disabled={runtimeProviderConfig?.credential_mode === 'backend_env_only'}
                  />
                  <div className="mt-3 rounded-2xl border border-sky-200 bg-sky-50/80 p-3 dark:border-sky-900/40 dark:bg-sky-950/20">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div>
                        <div className="text-sm font-semibold text-sky-950 dark:text-sky-100">
                          {settings.language === 'zh' ? '新增 MCP server 后的一键回归检查' : 'One-click regression check after adding an MCP server'}
                        </div>
                        <div className="mt-1 text-xs leading-5 text-sky-800/80 dark:text-sky-200/80">
                          {settings.language === 'zh'
                            ? '自动执行刷新接入审计与安全最小自测，适合每次新增或修改 MCP server 后快速确认能否稳定接入。'
                            : 'Refresh the onboarding audit and run safe minimal self-tests in one step after every MCP server change.'}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => { if (onRunOnboardingGate) { void onRunOnboardingGate(); } }}
                        className="inline-flex items-center justify-center rounded-2xl bg-slate-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
                        disabled={onboardingAuditLoading || onboardingRunLoading}
                        data-testid="run-onboarding-gate"
                      >
                        {(onboardingAuditLoading || onboardingRunLoading)
                          ? (settings.language === 'zh' ? '回归检查运行中…' : 'Running regression check...')
                          : (settings.language === 'zh' ? '一键回归检查' : 'Run onboarding gate')}
                      </button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                      <span className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-sky-900 dark:border-sky-900/40 dark:bg-slate-950/40 dark:text-sky-100">
                        {settings.language === 'zh'
                          ? `工具总数 ${onboardingAudit?.summary?.total_tools || 0}`
                          : `${onboardingAudit?.summary?.total_tools || 0} tools`}
                      </span>
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-700 dark:border-emerald-900/40 dark:bg-slate-950/40 dark:text-emerald-200">
                        {settings.language === 'zh'
                          ? `最近通过 ${onboardingRun?.summary?.passed || 0}`
                          : `passed ${onboardingRun?.summary?.passed || 0}`}
                      </span>
                      <span className="rounded-full border border-rose-200 bg-white px-2.5 py-1 text-rose-700 dark:border-rose-900/40 dark:bg-slate-950/40 dark:text-rose-200">
                        {settings.language === 'zh'
                          ? `最近失败 ${onboardingRun?.summary?.failed || 0}`
                          : `failed ${onboardingRun?.summary?.failed || 0}`}
                      </span>
                      <span className="rounded-full border border-amber-200 bg-white px-2.5 py-1 text-amber-700 dark:border-amber-900/40 dark:bg-slate-950/40 dark:text-amber-200">
                        {settings.language === 'zh'
                          ? `门禁失败 ${onboardingRun?.summary?.gate_failed || 0}`
                          : `gate failed ${onboardingRun?.summary?.gate_failed || 0}`}
                      </span>
                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
                        {settings.language === 'zh'
                          ? `Schema 风险 ${onboardingAudit?.summary?.schema_risk_tools || 0}`
                          : `schema risks ${onboardingAudit?.summary?.schema_risk_tools || 0}`}
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => { if (onRefreshOnboardingAudit) { void onRefreshOnboardingAudit(); } }}
                      className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      {onboardingAuditLoading
                        ? (settings.language === 'zh' ? '刷新中…' : 'Refreshing...')
                        : (settings.language === 'zh' ? '\u5237\u65b0\u63a5\u5165\u5ba1\u8ba1' : 'Refresh audit')}
                    </button>
                    <button
                      type="button"
                      onClick={() => { if (onRunOnboardingSelfTests) { void onRunOnboardingSelfTests(); } }}
                      className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
                    >
                      {onboardingRunLoading
                        ? (settings.language === 'zh' ? '\u81ea\u6d4b\u8fd0\u884c\u4e2d\u2026' : 'Running self-tests...')
                        : (settings.language === 'zh' ? '仅运行最小自测' : 'Run self-tests only')}
                    </button>
                  </div>
                  {showOnboardingAudit && (
                    <div className="mt-4 space-y-4">
                      {onboardingAuditLoading && (
                        <div className="text-sm text-slate-500 dark:text-slate-400">
                          {settings.language === 'zh' ? '正在加载接入审计…' : 'Loading onboarding audit...'}
                        </div>
                      )}
                      {onboardingRun && (
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-300">
                          <div>
                            {settings.language === 'zh' ? '最近一次自测' : 'Latest self-test'}:
                            {' '}
                            {settings.language === 'zh'
                              ? `通过 ${onboardingRun.summary.passed}，失败 ${onboardingRun.summary.failed}，跳过 ${onboardingRun.summary.skipped}`
                              : `passed ${onboardingRun.summary.passed}, failed ${onboardingRun.summary.failed}, skipped ${onboardingRun.summary.skipped}`}
                          </div>
                          <div className="mt-1">
                            {settings.language === 'zh' ? '门禁失败' : 'Gate failed'}: {onboardingRun.summary.gate_failed}
                            {onboardingRunLoading ? ` | ${settings.language === 'zh' ? '运行中' : 'running'}` : ''}
                          </div>
                        </div>
                      )}
                      {(onboardingAudit?.issues || []).length > 0 && (
                        <div className="space-y-2">
                          {(onboardingAudit?.issues || []).slice(0, 8).map((issue) => (
                            <div key={issue} className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                              {issue}
                            </div>
                          ))}
                        </div>
                      )}
                      {onboardingToolsByServer.map(([server, tools]) => (
                        <details key={server} className="rounded-2xl border border-slate-200 px-4 py-3 dark:border-slate-700">
                          <summary className="cursor-pointer list-none text-sm font-semibold text-slate-900 dark:text-white">
                            {server}
                            <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                              {tools.length}
                            </span>
                          </summary>
                          <div className="mt-3 space-y-3">
                            {tools.map((tool) => {
                              const latestRun = onboardingRunLookup.get(tool.tool_key);
                              return (
                                <div key={tool.tool_key} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 dark:border-slate-700 dark:bg-slate-950/40">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-mono text-xs font-semibold text-slate-900 dark:text-white">{tool.tool_key}</span>
                                    <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200">
                                      {tool.automation_class}
                                    </span>
                                    <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                                      self-test: {tool.self_test?.status || 'planned'}
                                    </span>
                                    {latestRun && (
                                      <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                                        latestRun.ok
                                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200'
                                          : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200'
                                      }`}>
                                        {settings.language === 'zh' ? '最近结果' : 'Latest run'}: {latestRun.status}
                                      </span>
                                    )}
                                  </div>
                                  {tool.description && (
                                    <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{tool.description}</div>
                                  )}
                                  <div className="mt-2 text-xs text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '必填字段' : 'Required fields'}: {tool.required_fields.join(', ') || '-'}
                                  </div>
                                  <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '推断字段样例' : 'Inferred fields'}: {tool.inferred_fields_sample.join(', ') || '-'}
                                  </div>
                                  <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '\u0020Schema \u8b66\u544a' : 'Schema warnings'}: {tool.schema_warnings.join(', ') || '-'}
                                  </div>
                                  {tool.harness && (
                                    <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                                      Harness: {(tool.harness.capabilities || []).join(', ') || '-'} | risk {tool.harness.risk_level || 'unknown'} | {tool.harness.server_visibility_model || 'server-level'}
                                    </div>
                                  )}
                                  <div className="mt-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300">
                                    <div className="font-medium text-slate-900 dark:text-white">
                                      {settings.language === 'zh' ? '最小自测计划' : 'Minimal self-test'}
                                    </div>
                                    <div className="mt-1">{tool.self_test?.reason || '-'}</div>
                                    {tool.self_test?.expected_outcome && <div className="mt-1">{tool.self_test.expected_outcome}</div>}
                                    <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-5">
                                      {JSON.stringify(tool.self_test?.sample_arguments || {}, null, 2)}
                                    </pre>
                                    {latestRun?.reason && (
                                      <div className="mt-2 text-amber-700 dark:text-amber-300">{latestRun.reason}</div>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </details>
                      ))}
                    </div>
                  )}
                </div>

                {runtimeToolPolicy && (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300">
                    <div>{settings.language === 'zh' ? '后端默认动作' : 'Backend default action'}: {runtimeToolPolicy.default_action}</div>
                    <div>{settings.language === 'zh' ? '策略启用' : 'Policy enabled'}: {String(runtimeToolPolicy.enabled)}</div>
                    <div>{settings.language === 'zh' ? '高风险写路径审核' : 'Risky write review'}: {String(runtimeToolPolicy.deny_risky_write_paths)}</div>
                    <div>{settings.language === 'zh' ? '工具规则数' : 'Tool rules'}: {Object.keys(runtimeToolPolicy.tool_actions || {}).length}</div>
                    <div>{settings.language === 'zh' ? '服务器规则数' : 'Server rules'}: {Object.keys(runtimeToolPolicy.server_actions || {}).length}</div>
                  </div>
                )}
              </div>
              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-700 dark:bg-slate-900/40">
                <label className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-900 dark:text-white">
                      {settings.language === 'zh' ? '\u5de5\u4f5c\u533a\u6587\u4ef6\u4e0a\u4e0b\u6587' : 'Workspace file context'}
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {settings.language === 'zh'
                        ? '\u4ece .mcp-mirror/agents \u8bfb\u53d6 agent.yaml\u3001memory.md \u548c\u6700\u8fd1 chatlogs\uff0c\u4f5c\u4e3a\u72ec\u7acb\u5de5\u4f5c\u533a\u4e0a\u4e0b\u6587\u6ce8\u5165\uff0c\u4e0d\u66ff\u4ee3 Recipe / Guard / Memory Plane\u3002'
                        : 'Read agent.yaml, memory.md, and recent chatlogs from .mcp-mirror/agents as a separate workspace context layer without replacing Recipe / Guard / Memory Plane.'}
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={settings.enableWorkspaceContext}
                    onChange={(event) => onSettingsChange({ ...settings, enableWorkspaceContext: event.target.checked })}
                    className="h-4 w-4"
                  />
                </label>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <input
                    value={settings.workspaceContextRoot}
                    onChange={(event) => onSettingsChange({ ...settings, workspaceContextRoot: event.target.value })}
                    placeholder={settings.language === 'zh' ? '\u5de5\u4f5c\u533a\u6839\u76ee\u5f55\uff0c\u4f8b\u5982 D:/project' : 'Workspace root, for example D:/project'}
                    className={inputClassName}
                    disabled={!settings.enableWorkspaceContext}
                  />
                  <input
                    value={settings.workspaceContextAgentName}
                    onChange={(event) => onSettingsChange({ ...settings, workspaceContextAgentName: event.target.value })}
                    placeholder={settings.language === 'zh' ? 'Agent \u540d\u79f0\uff0c\u4f8b\u5982 project-assistant' : 'Agent name, for example project-assistant'}
                    className={inputClassName}
                    disabled={!settings.enableWorkspaceContext}
                  />
                </div>
                <div className="mt-4 flex flex-wrap gap-4 text-sm text-slate-600 dark:text-slate-300">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={settings.workspaceContextIncludeAgentProfile}
                      onChange={(event) => onSettingsChange({ ...settings, workspaceContextIncludeAgentProfile: event.target.checked })}
                      disabled={!settings.enableWorkspaceContext}
                      className="h-4 w-4"
                    />
                    <span>{settings.language === 'zh' ? '\u5305\u542b agent.yaml' : 'Include agent.yaml'}</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={settings.workspaceContextIncludeMemoryFile}
                      onChange={(event) => onSettingsChange({ ...settings, workspaceContextIncludeMemoryFile: event.target.checked })}
                      disabled={!settings.enableWorkspaceContext}
                      className="h-4 w-4"
                    />
                    <span>{settings.language === 'zh' ? '\u5305\u542b memory.md' : 'Include memory.md'}</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={settings.workspaceContextIncludeChatlogs}
                      onChange={(event) => onSettingsChange({ ...settings, workspaceContextIncludeChatlogs: event.target.checked })}
                      disabled={!settings.enableWorkspaceContext}
                      className="h-4 w-4"
                    />
                    <span>{settings.language === 'zh' ? '\u5305\u542b\u6700\u8fd1 chatlogs' : 'Include recent chatlogs'}</span>
                  </label>
                </div>
                {workspaceAgentProfile && (
                  <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-xs text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200">
                    <div className="text-sm font-semibold">
                      {settings.language === 'zh' ? '\u5f53\u524d\u751f\u6548 Agent \u914d\u7f6e' : 'Active agent profile'}
                    </div>
                    <div className="mt-2">Agent: {workspaceAgentProfile.agent_name || '-'}</div>
                    <div className="mt-1">
                      {settings.language === 'zh' ? '\u9ed8\u8ba4\u6a21\u578b' : 'Default model'}: {workspaceAgentProfile.modelKey || '-'}
                    </div>
                    <div className="mt-1">
                      {settings.language === 'zh' ? '\u5de5\u5177\u786e\u8ba4' : 'Tool confirm'}: {String(workspaceAgentProfile.isConfirmCallTool ?? false)}
                    </div>
                    <div className="mt-1">
                      {settings.language === 'zh' ? '\u5141\u8bb8\u7684 MCP Server' : 'Allowed MCP servers'}: {(workspaceAgentProfile.allowMCPs || []).join(', ') || '-'}
                    </div>
                    <div className="mt-1">
                      {settings.language === 'zh' ? '\u5f53\u524d\u53ef\u89c1\u5de5\u5177\u6570' : 'Visible tools now'}: {availableTools.length}
                    </div>
                  </div>
                )}
                <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-4 text-xs text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/20 dark:text-sky-200">
                  <div className="text-sm font-semibold">
                    {settings.language === 'zh' ? '\u5f53\u524d\u5de5\u4f5c\u533a MCP \u670d\u52a1\u6c60' : 'Current workspace MCP pool'}
                  </div>
                  <div className="mt-2">
                    {settings.language === 'zh' ? '\u5de5\u4f5c\u533a\u6a21\u5f0f' : 'Workspace mode'}: {String(Boolean(effectiveWorkspaceMcpState?.workspace_enabled))}
                  </div>
                  <div className="mt-1 break-all">
                    {settings.language === 'zh' ? '\u5de5\u4f5c\u533a\u6839\u76ee\u5f55' : 'Workspace root'}: {effectiveWorkspaceMcpState?.workspace_root || workspaceRootSetting || '-'}
                  </div>
                  <div className="mt-1 break-all">
                    {settings.language === 'zh' ? '工作区 MCP 配置' : 'Workspace MCP config'}: {effectiveWorkspaceMcpState?.workspace_config_path || '-'}
                  </div>
                  <div className="mt-1">
                    {settings.language === 'zh' ? '工作区 servers' : 'Workspace servers'}: {(effectiveWorkspaceMcpState?.workspace_servers || []).join(', ') || '-'}
                  </div>
                  <div className="mt-1">
                    {settings.language === 'zh' ? '配置来源' : 'Config sources'}: {(effectiveWorkspaceMcpState?.sources || ['mcp_config.json']).join(', ')}
                  </div>
                  {workspaceServerSummaries.length > 0 && (
                    <div className="mt-4 space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-200">
                        {settings.language === 'zh' ? '工作区服务概览' : 'Workspace server overview'}
                      </div>
                      {workspaceServerSummaries.map((summary) => {
                        const serverDetail = workspaceServerDetails.find((detail) => detail.server === summary.server);
                        return (
                          <details
                            key={summary.server}
                            className="rounded-2xl border border-sky-200/70 bg-white/70 px-3 py-3 text-xs text-sky-950 dark:border-sky-900/40 dark:bg-slate-950/30 dark:text-sky-100"
                          >
                            <summary className="cursor-pointer list-none">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold">{summary.server}</span>
                                <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200">
                                  {settings.language === 'zh' ? `工具 ${summary.toolCount}` : `${summary.toolCount} tools`}
                                </span>
                                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200">
                                  {settings.language === 'zh' ? `可自动执行 ${summary.autoExecutable}` : `auto ${summary.autoExecutable}`}
                                </span>
                                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                                  {settings.language === 'zh' ? `需确认 ${summary.autoRoutableManual}` : `confirm ${summary.autoRoutableManual}`}
                                </span>
                                <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                                  {settings.language === 'zh' ? `仅手动 ${summary.manualOnly}` : `manual ${summary.manualOnly}`}
                                </span>
                              </div>
                              <div className="mt-2 text-sky-900/80 dark:text-sky-100/80">
                                {settings.language === 'zh'
                                  ? `最小自测可运行 ${summary.safeSelfTests} 个，最近自测通过 ${summary.passedRuns} 个，失败 ${summary.failedRuns} 个。`
                                  : `${summary.safeSelfTests} minimal self-tests are safe to run; latest run passed ${summary.passedRuns} and failed ${summary.failedRuns}.`}
                              </div>
                              <div className="mt-2 break-all text-sky-900/70 dark:text-sky-100/70">
                                {settings.language === 'zh'
                                  ? '点击展开完整工具列表、自动化等级与最近自测结果。'
                                  : 'Expand to inspect the full tool list, automation class, and latest self-test results.'}
                              </div>
                            </summary>
                            <div className="mt-4 space-y-2">
                              {serverDetail?.tools.length ? serverDetail.tools.map(({ tool, latestRun }) => (
                                <div
                                  key={tool.tool_key}
                                  className="rounded-2xl border border-sky-100 bg-white/90 px-3 py-3 text-[11px] text-slate-700 dark:border-sky-900/30 dark:bg-slate-950/50 dark:text-slate-200"
                                >
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-mono font-semibold text-slate-900 dark:text-white">{tool.tool_key}</span>
                                    <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200">
                                      {tool.automation_class}
                                    </span>
                                    <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                                      {settings.language === 'zh'
                                        ? `最小自测 ${tool.self_test?.status || 'planned'}`
                                        : `self-test ${tool.self_test?.status || 'planned'}`}
                                    </span>
                                    {latestRun && (
                                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                                        latestRun.ok
                                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200'
                                          : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200'
                                      }`}>
                                        {settings.language === 'zh' ? '最近结果' : 'latest'}: {latestRun.status}
                                      </span>
                                    )}
                                  </div>
                                  {tool.description && (
                                    <div className="mt-2 leading-5 text-slate-500 dark:text-slate-400">{tool.description}</div>
                                  )}
                                  <div className="mt-2 text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '必填字段' : 'Required fields'}: {tool.required_fields.join(', ') || '-'}
                                  </div>
                                  <div className="mt-1 text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '推断字段' : 'Inferred fields'}: {tool.inferred_fields_sample.join(', ') || '-'}
                                  </div>
                                  <div className="mt-1 text-slate-600 dark:text-slate-300">
                                    {settings.language === 'zh' ? '最小自测' : 'Minimal self-test'}: {tool.self_test?.reason || '-'}
                                  </div>
                                  {latestRun?.reason && (
                                    <div className="mt-1 text-amber-700 dark:text-amber-300">
                                      {settings.language === 'zh' ? '最近说明' : 'Latest note'}: {latestRun.reason}
                                    </div>
                                  )}
                                </div>
                              )) : (
                                <div className="rounded-2xl border border-dashed border-sky-200 px-3 py-3 text-sky-800 dark:border-sky-900/30 dark:text-sky-200">
                                  {settings.language === 'zh'
                                    ? '当前还没有可展开的工具明细，请先刷新接入审计。'
                                    : 'No expandable tool details yet. Refresh the onboarding audit first.'}
                                </div>
                              )}
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  )}
                  {effectiveWorkspaceMcpState?.error && (
                    <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                      {effectiveWorkspaceMcpState.error}
                    </div>
                  )}
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {temModes.map((mode) => (
                  <button key={mode} type="button" onClick={() => { void onTemModeChange(mode); }} disabled={temModeLoading} className={`rounded-2xl px-4 py-2 text-sm font-medium transition ${bootstrap?.tem.mode === mode ? 'bg-amber-500 text-white shadow-md' : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800'} disabled:cursor-not-allowed disabled:opacity-60`}>
                    {mode}
                  </button>
                ))}
              </div>
              <div className="mt-4">
                <button type="button" onClick={onResetLocalSettings} className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200 dark:hover:bg-slate-800">{t('settings.resetLocalSettings')}</button>
              </div>
            </section>

            <section className={cardClassName}>
              <button type="button" onClick={() => setShowMemoryPlane((prev) => !prev)} className="flex w-full items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                  <Brain className="h-4 w-4 text-sky-500" />
                  <span>{t('settings.memoryPlaneSnapshot')}</span>
                </div>
                {showMemoryPlane ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40"><div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('settings.routing')}</div><div className="mt-2 text-sm text-slate-800 dark:text-slate-200">{memoryPlane?.routing?.reason || t('common.notApplicable')}</div></div>
                <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40"><div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('settings.retention')}</div><div className="mt-2 text-sm text-slate-800 dark:text-slate-200">{t('settings.factsCount', { count: memoryPlane?.retention?.retained_facts?.length || 0 })}</div></div>
                <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-900/40"><div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('settings.attribution')}</div><div className="mt-2 text-sm text-slate-800 dark:text-slate-200">{t('settings.itemsCount', { count: memoryPlane?.attribution?.length || 0 })}</div></div>
              </div>
              {showMemoryPlane && <pre className="mt-4 overflow-x-auto rounded-2xl bg-slate-950/95 p-4 text-xs text-slate-100">{JSON.stringify(memoryPlane || {}, null, 2)}</pre>}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsPanel;
