import {
  DEFAULT_RUNTIME_PROVIDER_CONFIG,
  loadRuntimeProviderConfig,
  resetRuntimeProviderConfig,
  saveRuntimeProviderConfig,
} from './settingsStorage';

describe('settingsStorage runtime provider config', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it('stores session_only credentials in sessionStorage only', () => {
    saveRuntimeProviderConfig({
      ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
      credential_mode: 'session_only',
      openrouter_api_key: 'session-key',
    });

    expect(window.sessionStorage.getItem('mcp_runtime_provider_config_session')).toContain('session-key');
    expect(window.localStorage.getItem('mcp_runtime_provider_config')).toBeNull();
    expect(loadRuntimeProviderConfig().openrouter_api_key).toBe('session-key');
  });

  it('stores local_persist credentials in localStorage', () => {
    saveRuntimeProviderConfig({
      ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
      credential_mode: 'local_persist',
      siliconflow_api_key: 'local-key',
    });

    expect(window.localStorage.getItem('mcp_runtime_provider_config')).toContain('local-key');
    expect(window.sessionStorage.getItem('mcp_runtime_provider_config_session')).toBeNull();
  });

  it('clears storage for backend_env_only mode', () => {
    saveRuntimeProviderConfig({
      ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
      credential_mode: 'backend_env_only',
      siliconflow_api_key: 'ignored',
      openrouter_api_key: 'ignored',
    });

    expect(window.localStorage.getItem('mcp_runtime_provider_config')).toBeNull();
    expect(window.sessionStorage.getItem('mcp_runtime_provider_config_session')).toBeNull();
    expect(loadRuntimeProviderConfig()).toEqual(DEFAULT_RUNTIME_PROVIDER_CONFIG);
  });

  it('reset removes both storage scopes', () => {
    saveRuntimeProviderConfig({
      ...DEFAULT_RUNTIME_PROVIDER_CONFIG,
      credential_mode: 'local_persist',
      openrouter_api_key: 'abc',
    });

    const reset = resetRuntimeProviderConfig();

    expect(reset).toEqual(DEFAULT_RUNTIME_PROVIDER_CONFIG);
    expect(window.localStorage.getItem('mcp_runtime_provider_config')).toBeNull();
    expect(window.sessionStorage.getItem('mcp_runtime_provider_config_session')).toBeNull();
  });
});
