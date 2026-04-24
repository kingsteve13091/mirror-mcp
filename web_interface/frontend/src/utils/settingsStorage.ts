import { ChatSettings, CredentialStorageMode, RuntimeProviderConfig } from '../types';

const CHAT_SETTINGS_KEY = 'mcp_chat_settings';
const SELECTED_MODEL_KEY = 'mcp_selected_model';
const RUNTIME_PROVIDER_CONFIG_KEY = 'mcp_runtime_provider_config';
const RUNTIME_PROVIDER_SESSION_KEY = 'mcp_runtime_provider_config_session';

export const DEFAULT_CHAT_SETTINGS: ChatSettings = {
  dark_mode: false,
  confirmToolCalls: true,
  showAdvancedDebugTraces: false,
  agentModeEnabled: false,
  agentModeProfile: 'chat',
  language: 'zh',
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
  toolPolicySystemRules: 'terminal_command=confirm\nprocess_control=confirm\ntest_runner=allow\nlog_read=allow\nbrowser_smoke=allow\nworkspace_file_op=confirm',
  toolPolicyDenyRiskyWritePaths: true,
  autoToolRoutingMode: 'memory_plane_plus_fallback',
};

const isBrowser = typeof window !== 'undefined';
const DEFAULT_CREDENTIAL_MODE: CredentialStorageMode = 'session_only';

function getLocalStorageItem(key: string): string | null {
  if (!isBrowser) {
    return null;
  }
  return window.localStorage.getItem(key);
}

function setLocalStorageItem(key: string, value: string) {
  if (!isBrowser) {
    return;
  }
  window.localStorage.setItem(key, value);
}

function removeLocalStorageItem(key: string) {
  if (!isBrowser) {
    return;
  }
  window.localStorage.removeItem(key);
}

function getSessionStorageItem(key: string): string | null {
  if (!isBrowser) {
    return null;
  }
  return window.sessionStorage.getItem(key);
}

function setSessionStorageItem(key: string, value: string) {
  if (!isBrowser) {
    return;
  }
  window.sessionStorage.setItem(key, value);
}

function removeSessionStorageItem(key: string) {
  if (!isBrowser) {
    return;
  }
  window.sessionStorage.removeItem(key);
}

function parseJson<T>(raw: string | null): T | null {
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as T;
  } catch (error) {
    console.error('Failed to parse stored JSON:', error);
    return null;
  }
}

export function loadChatSettings(): ChatSettings {
  const raw = getLocalStorageItem(CHAT_SETTINGS_KEY);
  if (!raw) {
    return DEFAULT_CHAT_SETTINGS;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<ChatSettings>;
    return {
      ...DEFAULT_CHAT_SETTINGS,
      ...parsed,
    };
  } catch (error) {
    console.error('Failed to load chat settings:', error);
    return DEFAULT_CHAT_SETTINGS;
  }
}

export function saveChatSettings(settings: ChatSettings) {
  setLocalStorageItem(CHAT_SETTINGS_KEY, JSON.stringify(settings));
}

export function resetChatSettings(): ChatSettings {
  removeLocalStorageItem(CHAT_SETTINGS_KEY);
  return DEFAULT_CHAT_SETTINGS;
}

export function loadSelectedModel(): string {
  return getLocalStorageItem(SELECTED_MODEL_KEY) || '';
}

export function saveSelectedModel(modelId: string) {
  if (!modelId) {
    removeLocalStorageItem(SELECTED_MODEL_KEY);
    return;
  }
  setLocalStorageItem(SELECTED_MODEL_KEY, modelId);
}

export const DEFAULT_RUNTIME_PROVIDER_CONFIG: RuntimeProviderConfig = {
  credential_mode: DEFAULT_CREDENTIAL_MODE,
  siliconflow_api_key: '',
  siliconflow_base_url: 'https://api.siliconflow.cn/v1',
  openrouter_api_key: '',
  openrouter_base_url: 'https://openrouter.ai/api/v1',
  default_model: '',
  custom_models: [],
};

export function loadRuntimeProviderConfig(): RuntimeProviderConfig {
  const sessionParsed = parseJson<Partial<RuntimeProviderConfig>>(getSessionStorageItem(RUNTIME_PROVIDER_SESSION_KEY));
  const localParsed = parseJson<Partial<RuntimeProviderConfig>>(getLocalStorageItem(RUNTIME_PROVIDER_CONFIG_KEY));
  const parsed = sessionParsed || localParsed;
  if (!parsed) {
    return DEFAULT_RUNTIME_PROVIDER_CONFIG;
  }
  return {
    ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
    ...parsed,
    credential_mode: parsed.credential_mode || DEFAULT_CREDENTIAL_MODE,
    custom_models: Array.isArray(parsed.custom_models) ? parsed.custom_models : [],
  };
}

export function saveRuntimeProviderConfig(config: RuntimeProviderConfig) {
  const normalized = {
    ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
    ...config,
    credential_mode: config.credential_mode || DEFAULT_CREDENTIAL_MODE,
    custom_models: Array.isArray(config.custom_models) ? config.custom_models : [],
  };

  removeSessionStorageItem(RUNTIME_PROVIDER_SESSION_KEY);
  removeLocalStorageItem(RUNTIME_PROVIDER_CONFIG_KEY);

  if (normalized.credential_mode === 'backend_env_only') {
    return;
  }

  if (normalized.credential_mode === 'local_persist') {
    setLocalStorageItem(RUNTIME_PROVIDER_CONFIG_KEY, JSON.stringify(normalized));
    return;
  }

  setSessionStorageItem(RUNTIME_PROVIDER_SESSION_KEY, JSON.stringify(normalized));
}

export function resetRuntimeProviderConfig(): RuntimeProviderConfig {
  removeSessionStorageItem(RUNTIME_PROVIDER_SESSION_KEY);
  removeLocalStorageItem(RUNTIME_PROVIDER_CONFIG_KEY);
  return DEFAULT_RUNTIME_PROVIDER_CONFIG;
}
