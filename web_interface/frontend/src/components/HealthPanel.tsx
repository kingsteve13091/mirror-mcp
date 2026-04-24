import React, { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, RefreshCw, Server, ShieldCheck, Wifi, X } from 'lucide-react';
import { BackendRouteSupport, HealthSnapshot } from '../types';
import { getBackendRouteSupport, getHealthSnapshot } from '../services/api';
import AppModal from './common/AppModal';
import NoticeBanner from './common/NoticeBanner';
import { useI18n } from '../i18n/I18nProvider';

interface HealthPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

const cardClass = 'rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900/70';

const onboardingClassLabels: Record<string, string> = {
  auto_executable: 'Auto executable',
  auto_routable_manual_confirm: 'Auto routable, confirm',
  manual_only: 'Manual only',
};

const onboardingClassStyles: Record<string, string> = {
  auto_executable: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200',
  auto_routable_manual_confirm: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200',
  manual_only: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200',
};

const selfTestStatusStyles: Record<string, string> = {
  ready: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200',
  passed: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-200',
  planned: 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-200',
  manual_only: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200',
  missing_arguments: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200',
  schema_risk: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-200',
  failed: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-200',
};

function formatList(items: string[] | undefined) {
  return items && items.length ? items.join(', ') : 'none';
}

function formatJson(value: Record<string, any> | undefined) {
  if (!value || Object.keys(value).length === 0) {
    return '{}';
  }
  return JSON.stringify(value, null, 2);
}

const diagnosticRouteCatalog: Array<{
  key: keyof BackendRouteSupport;
  label: string;
  path: string;
  critical?: boolean;
}> = [
  { key: 'health', label: 'Health', path: '/health', critical: true },
  { key: 'systemBootstrap', label: 'Bootstrap', path: '/api/system/bootstrap', critical: true },
  { key: 'runtimeProviders', label: 'Runtime providers', path: '/api/runtime/providers', critical: true },
  { key: 'mcpToolOnboardingAudit', label: 'Tool onboarding audit', path: '/api/mcp/tool-onboarding-audit' },
  { key: 'temBenchmark', label: 'TEM benchmark', path: '/api/tem/benchmark' },
  { key: 'temDecisions', label: 'TEM decisions', path: '/api/tem/decisions' },
  { key: 'memoryPlane', label: 'Memory Plane snapshot', path: '/api/memory-plane', critical: true },
  { key: 'memoryPlaneTraces', label: 'Trace log', path: '/api/memory-plane/traces' },
  { key: 'memoryPlaneLedger', label: 'Ledger', path: '/api/memory-plane/ledger' },
  { key: 'memoryPlaneEvaluate', label: 'Policy evaluate', path: '/api/memory-plane/evaluate' },
  { key: 'memoryPlaneRollback', label: 'Rollback', path: '/api/memory-plane/rollback' },
];

const HealthPanel: React.FC<HealthPanelProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [routeSupport, setRouteSupport] = useState<BackendRouteSupport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const providerCount = [
    health?.providers?.siliconflow.configured,
    health?.providers?.openrouter.configured,
  ].filter(Boolean).length;
  const providersReadyLabel = health?.providers
    ? `${providerCount}/2`
    : t('health.unknown');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [snapshot, support] = await Promise.all([
        getHealthSnapshot(),
        getBackendRouteSupport(),
      ]);
      setHealth(snapshot);
      setRouteSupport(support);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const missingCriticalRoutes = routeSupport
    ? diagnosticRouteCatalog
      .filter((item) => item.critical && !routeSupport[item.key])
      .map((item) => item.path)
    : [];

  const supportedRouteCount = routeSupport
    ? diagnosticRouteCatalog.filter((item) => routeSupport[item.key]).length
    : 0;

  useEffect(() => {
    if (isOpen) {
      void refresh();
    }
  }, [isOpen, refresh]);

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title={t('health.title')}
      description={t('health.description')}
      maxWidthClassName="max-w-5xl"
      bodyClassName="p-6"
      headerActions={(
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { void refresh(); }}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
            aria-label={t('health.refresh')}
          >
            <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
            aria-label={t('health.close')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      )}
    >
      <div className="space-y-5">
        {error && <NoticeBanner tone="error" message={error} onClose={() => setError(null)} />}
        {!error && missingCriticalRoutes.length > 0 && (
          <NoticeBanner
            tone="warning"
            message={t('health.missingRoutes', { routes: missingCriticalRoutes.join(', ') })}
          />
        )}
        <div className="grid gap-4 md:grid-cols-4">
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('health.system')}</div>
            <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-slate-900 dark:text-white">
              <Activity className="h-5 w-5 text-emerald-500" />
              <span>{health?.status || t('health.loading')}</span>
            </div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('health.providers')}</div>
            <div className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">{providersReadyLabel}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('health.mcpServers')}</div>
            <div className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">{health?.mcp?.servers?.connected_servers || 0}</div>
          </div>
          <div className={cardClass}>
            <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('health.apiRoutes')}</div>
            <div className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">
              {routeSupport ? `${supportedRouteCount}/${diagnosticRouteCatalog.length}` : t('health.loading')}
            </div>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <section className={cardClass}>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Wifi className="h-4 w-4 text-sky-500" />
              <span>{t('health.providersModels')}</span>
            </div>
            <div className="mt-4 space-y-3 text-sm text-slate-600 dark:text-slate-300">
              <div>SiliconFlow: {health?.providers?.siliconflow.configured ? t('health.ready') : t('health.missing')}</div>
              <div>OpenRouter: {health?.providers?.openrouter.configured ? t('health.ready') : t('health.missing')}</div>
              <div>{t('health.defaultModel')}: {health?.models?.default || 'n/a'}</div>
              <div>{t('health.modelCount')}: {health?.models?.count || 0}</div>
              <div>{t('health.siliconflowBaseUrl')}: {health?.siliconflow_base_url || health?.providers?.siliconflow.base_url || 'n/a'}</div>
              <div>{t('health.openRouterBaseUrl')}: {health?.openrouter_base_url || 'n/a'}</div>
            </div>
          </section>

          <section className={cardClass}>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Server className="h-4 w-4 text-cyan-500" />
              <span>{t('health.mcpRuntime')}</span>
            </div>
            <div className="mt-4 space-y-3 text-sm text-slate-600 dark:text-slate-300">
              <div>{t('health.mcpManager')}: {health?.mcp_manager || t('health.unknown')}</div>
              <div>{t('health.connectedServers')}: {(health?.mcp?.connected_servers || []).join(', ') || 'none'}</div>
              <div>{t('health.totalTools')}: {health?.mcp?.tools_count || 0}</div>
              <div>{t('health.auditErrors')}: {health?.mcp?.audit?.errors?.length || 0}</div>
              <div>{t('health.autoExecutableTools')}: {health?.mcp?.tool_onboarding_audit?.summary?.auto_executable_tools || 0}</div>
              <div>{t('health.manualOnlyTools')}: {health?.mcp?.tool_onboarding_audit?.summary?.manual_only_tools || 0}</div>
              <div>{t('health.schemaRiskTools')}: {health?.mcp?.tool_onboarding_audit?.summary?.schema_risk_tools || 0}</div>
              <div>{t('health.temMode')}: {health?.tem?.mode || 'n/a'}</div>
              <div>{t('health.memoryPhase')}: {String(health?.memory_plane?.phase || 'n/a')}</div>
            </div>
          </section>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <section className={cardClass}>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
              <span>{t('health.apiDiagnostics')}</span>
            </div>
            <div className="mt-4 space-y-2 text-sm">
              {diagnosticRouteCatalog.map((item) => {
                const supported = routeSupport ? routeSupport[item.key] : false;
                return (
                  <div
                    key={item.path}
                    className={`flex items-center justify-between rounded-2xl border px-3 py-3 ${
                      supported
                        ? 'border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/40 dark:bg-emerald-950/20'
                        : 'border-amber-200 bg-amber-50/70 dark:border-amber-900/40 dark:bg-amber-950/20'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-slate-900 dark:text-white">{item.label}</div>
                      <div className="truncate font-mono text-xs text-slate-500 dark:text-slate-400">{item.path}</div>
                    </div>
                    <div className={`ml-3 rounded-full px-2.5 py-1 text-xs font-semibold ${
                      supported
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200'
                        : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200'
                    }`}>
                      {supported ? t('health.registered') : t('health.missing')}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className={cardClass}>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              <span>{t('health.auditSummary')}</span>
            </div>
            {health?.mcp?.audit?.ok ? (
              <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200">
                {t('health.noAuditMismatch')}
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
                {(health?.mcp?.audit?.errors || []).join(' | ') || t('health.auditWarning')}
              </div>
            )}
            <div className="mt-4 text-xs leading-6 text-slate-500 dark:text-slate-400">
              {t('health.panelNote')}
            </div>
          </section>
        </div>

        <section className={cardClass}>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
            <ShieldCheck className="h-4 w-4 text-violet-500" />
            <span>{t('health.toolOnboardingAudit')}</span>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-4">
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 dark:border-emerald-900/40 dark:bg-emerald-950/20">
              <div className="text-xs uppercase tracking-[0.2em] text-emerald-700 dark:text-emerald-300">{t('health.autoExecutableTools')}</div>
              <div className="mt-2 text-2xl font-semibold text-emerald-900 dark:text-emerald-100">
                {health?.mcp?.tool_onboarding_audit?.summary?.auto_executable_tools || 0}
              </div>
            </div>
            <div className="rounded-2xl border border-sky-200 bg-sky-50/70 px-4 py-3 dark:border-sky-900/40 dark:bg-sky-950/20">
              <div className="text-xs uppercase tracking-[0.2em] text-sky-700 dark:text-sky-300">{t('health.autoRoutableTools')}</div>
              <div className="mt-2 text-2xl font-semibold text-sky-900 dark:text-sky-100">
                {health?.mcp?.tool_onboarding_audit?.summary?.auto_routable_tools || 0}
              </div>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 dark:border-amber-900/40 dark:bg-amber-950/20">
              <div className="text-xs uppercase tracking-[0.2em] text-amber-700 dark:text-amber-300">{t('health.manualOnlyTools')}</div>
              <div className="mt-2 text-2xl font-semibold text-amber-900 dark:text-amber-100">
                {health?.mcp?.tool_onboarding_audit?.summary?.manual_only_tools || 0}
              </div>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 dark:border-rose-900/40 dark:bg-rose-950/20">
              <div className="text-xs uppercase tracking-[0.2em] text-rose-700 dark:text-rose-300">{t('health.schemaRiskTools')}</div>
              <div className="mt-2 text-2xl font-semibold text-rose-900 dark:text-rose-100">
                {health?.mcp?.tool_onboarding_audit?.summary?.schema_risk_tools || 0}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-sm font-medium text-slate-900 dark:text-white">{t('health.toolOnboardingIssues')}</div>
              {health?.mcp?.tool_onboarding_audit?.issues?.length ? (
                <div className="space-y-2">
                  {health.mcp.tool_onboarding_audit.issues.slice(0, 8).map((issue) => (
                    <div key={issue} className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
                      {issue}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-200">
                  {t('health.toolOnboardingClean')}
                </div>
              )}
            </div>

            <div>
              <div className="mb-2 text-sm font-medium text-slate-900 dark:text-white">{t('health.toolOnboardingFullList')}</div>
              <div className="space-y-3">
                {['auto_executable', 'auto_routable_manual_confirm', 'manual_only'].map((group) => {
                  const groupTools = (health?.mcp?.tool_onboarding_audit?.tools || [])
                    .filter((tool) => tool.automation_class === group);
                  if (groupTools.length === 0) {
                    return null;
                  }
                  return (
                    <details
                      key={group}
                      open={group !== 'manual_only'}
                      className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm dark:border-slate-700 dark:bg-slate-900/40"
                    >
                      <summary className="cursor-pointer list-none font-semibold text-slate-900 dark:text-white">
                        {onboardingClassLabels[group] || group}
                        <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                          {groupTools.length}
                        </span>
                      </summary>
                      <div className="mt-3 space-y-3">
                        {groupTools.map((tool) => {
                          const classStyle = onboardingClassStyles[tool.automation_class] || onboardingClassStyles.manual_only;
                          const selfTestStyle = selfTestStatusStyles[tool.self_test?.status || 'planned'] || selfTestStatusStyles.planned;
                          return (
                            <details
                              key={tool.tool_key}
                              className="rounded-2xl border border-slate-200 bg-white px-3 py-3 dark:border-slate-700 dark:bg-slate-950/40"
                            >
                              <summary className="cursor-pointer list-none">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">{tool.tool_key}</span>
                                  <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${classStyle}`}>
                                    {onboardingClassLabels[tool.automation_class] || tool.automation_class}
                                  </span>
                                  <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${selfTestStyle}`}>
                                    self-test: {tool.self_test?.status || 'planned'}
                                  </span>
                                  {tool.self_test?.gate_required && (
                                    <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs font-semibold text-violet-800 dark:border-violet-900/40 dark:bg-violet-950/30 dark:text-violet-200">
                                      smoke gate
                                    </span>
                                  )}
                                </div>
                              </summary>
                              <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                                {tool.description && (
                                  <div className="line-clamp-3 leading-5 text-slate-500 dark:text-slate-400">{tool.description}</div>
                                )}
                                <div>
                                  {t('health.requiredFieldsLabel')}: {formatList(tool.required_fields)}
                                  {' | '}
                                  {t('health.inferredFieldsLabel')}: {formatList(tool.inferred_fields_sample)}
                                </div>
                                <div>
                                  {t('health.schemaWarningsLabel')}: {formatList(tool.schema_warnings)}
                                </div>
                                {tool.harness && (
                                  <div>
                                    harness: {formatList(tool.harness.capabilities)}
                                    {' | '}
                                    risk: {tool.harness.risk_level || 'unknown'}
                                    {' | '}
                                    visibility: {tool.harness.server_visibility_model || 'server_level'}
                                  </div>
                                )}
                                <div>
                                  self-test reason: {tool.self_test?.reason || 'n/a'}
                                </div>
                                {tool.self_test?.expected_outcome && (
                                  <div>expected: {tool.self_test.expected_outcome}</div>
                                )}
                                <details className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/60">
                                  <summary className="cursor-pointer font-medium text-slate-800 dark:text-slate-100">Minimal call arguments</summary>
                                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-5 text-slate-600 dark:text-slate-300">
                                    {formatJson(tool.self_test?.sample_arguments)}
                                  </pre>
                                </details>
                              </div>
                            </details>
                          );
                        })}
                      </div>
                    </details>
                  );
                })}
              </div>
            </div>
          </div>
        </section>
      </div>
    </AppModal>
  );
};

export default HealthPanel;
