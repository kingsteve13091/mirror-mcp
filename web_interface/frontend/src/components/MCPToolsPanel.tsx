import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Brain,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Eye,
  FileText,
  Filter,
  Play,
  RefreshCw,
  Search,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Wrench,
  X,
} from 'lucide-react';
import {
  MCPAuditReport,
  MCPPrompt,
  MCPResource,
  MCPServer,
  MCPTool,
} from '../types';
import {
  getMcpAudit,
  getMcpPrompts,
  getMcpResources,
  getMcpServers,
  getMcpTools,
} from '../services/api';
import { useI18n } from '../i18n/I18nProvider';
import {
  coerceJsonSchemaValue,
  getJsonSchemaProperties,
  getJsonSchemaRequired,
  JsonSchemaProperty,
  pruneEmptyOptionalArgs,
  resolveJsonSchemaType,
} from '../utils/jsonSchema';

interface MCPToolsPanelProps {
  onToolCall: (serverName: string, toolName: string, args: Record<string, any>) => void;
  onResourceRead: (serverName: string, uri: string) => void;
  onPromptGet: (serverName: string, promptName: string, args: Record<string, any>) => void;
  onClose?: () => void;
}

const MCP_RUNTIME_POLL_INTERVAL_MS = 30000;

const MCPToolsPanel: React.FC<MCPToolsPanelProps> = ({
  onToolCall,
  onResourceRead,
  onPromptGet,
  onClose,
}) => {
  const { t, language } = useI18n();
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [resources, setResources] = useState<MCPResource[]>([]);
  const [prompts, setPrompts] = useState<MCPPrompt[]>([]);
  const [audit, setAudit] = useState<MCPAuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'tools' | 'servers' | 'resources' | 'prompts'>('tools');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'connected' | 'disconnected'>('all');
  const [callableOnly, setCallableOnly] = useState(false);
  const [expandedServers, setExpandedServers] = useState<Set<string>>(new Set());
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);
  const [toolArgs, setToolArgs] = useState<Record<string, any>>({});
  const [toolValidationError, setToolValidationError] = useState<string | null>(null);
  const [highlightedServer, setHighlightedServer] = useState<string | null>(null);

  const buildDefaultArgs = (tool: MCPTool | null) => {
    const properties = getJsonSchemaProperties(tool?.input_schema || {});
    return Object.entries(properties).reduce<Record<string, any>>((acc, [key, rawSchema]) => {
      const schema = (rawSchema || {}) as JsonSchemaProperty;
      if (schema.default !== undefined) {
        acc[key] = schema.default;
      }
      return acc;
    }, {});
  };

  const getMissingRequiredToolArgs = (tool: MCPTool | null, args: Record<string, any>) => {
    const required = getJsonSchemaRequired(tool?.input_schema || {});
    return required.filter((key) => {
      const value = args[key];
      return value === undefined || value === null || String(value).trim() === '';
    });
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [toolsData, serversData, resourcesData, promptsData, auditData] = await Promise.all([
        getMcpTools(),
        getMcpServers(),
        getMcpResources(),
        getMcpPrompts(),
        getMcpAudit(),
      ]);

      setTools(toolsData.tools || []);
      setServers(serversData.servers?.servers || []);
      setResources(resourcesData.resources || []);
      setPrompts(promptsData.prompts || []);
      setAudit(auditData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, MCP_RUNTIME_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleServerExpanded = (serverName: string) => {
    setExpandedServers((prev) => {
      const next = new Set(prev);
      if (next.has(serverName)) {
        next.delete(serverName);
      } else {
        next.add(serverName);
      }
      return next;
    });
  };

  const filteredTools = useMemo(() => {
    return tools.filter((tool) => {
      const query = searchQuery.toLowerCase();
      const matchesSearch =
        tool.name.toLowerCase().includes(query) ||
        tool.display_name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query) ||
        tool.server.toLowerCase().includes(query);
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'connected' && tool.server_status === 'connected') ||
        (statusFilter === 'disconnected' && tool.server_status !== 'connected');
      const matchesCallable = !callableOnly || tool.server_status === 'connected';
      const matchesHighlightedServer = !highlightedServer || tool.server === highlightedServer;
      return matchesSearch && matchesStatus && matchesCallable && matchesHighlightedServer;
    });
  }, [callableOnly, highlightedServer, searchQuery, statusFilter, tools]);

  const filteredServers = useMemo(() => {
    return servers.filter((server) => {
      const query = searchQuery.toLowerCase();
      const matchesSearch =
        server.name.toLowerCase().includes(query) ||
        server.description.toLowerCase().includes(query);
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'connected' && server.status === 'connected') ||
        (statusFilter === 'disconnected' && server.status !== 'connected');
      const matchesHighlightedServer = !highlightedServer || server.name === highlightedServer;
      return matchesSearch && matchesStatus && matchesHighlightedServer;
    });
  }, [highlightedServer, searchQuery, statusFilter, servers]);

  const filteredResources = useMemo(() => {
    return resources.filter((resource) => {
      const query = searchQuery.toLowerCase();
      const matchesHighlightedServer = !highlightedServer || resource.server === highlightedServer;
      return matchesHighlightedServer && (
        resource.name.toLowerCase().includes(query) ||
        resource.description.toLowerCase().includes(query) ||
        resource.uri.toLowerCase().includes(query) ||
        resource.server.toLowerCase().includes(query)
      );
    });
  }, [highlightedServer, resources, searchQuery]);

  const filteredPrompts = useMemo(() => {
    return prompts.filter((prompt) => {
      const query = searchQuery.toLowerCase();
      const matchesHighlightedServer = !highlightedServer || prompt.server === highlightedServer;
      return matchesHighlightedServer && (
        prompt.name.toLowerCase().includes(query) ||
        prompt.description.toLowerCase().includes(query) ||
        prompt.server.toLowerCase().includes(query)
      );
    });
  }, [highlightedServer, prompts, searchQuery]);

  const groupedTools = useMemo(() => {
    return filteredTools.reduce<Record<string, MCPTool[]>>((acc, tool) => {
      if (!acc[tool.server]) {
        acc[tool.server] = [];
      }
      acc[tool.server].push(tool);
      return acc;
    }, {});
  }, [filteredTools]);

  const renderServerStatus = (server: MCPServer) => {
    if (server.status === 'connected') {
      return <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-1 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">{t('mcpTools.connected')}</span>;
    }
    if (server.status === 'error') {
      return <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-1 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-300">{t('mcpTools.error')}</span>;
    }
    return <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">{server.status}</span>;
  };

  const formatConnectionType = (value?: string) => {
    switch (value) {
      case 'external_transport':
        return t('mcpTools.externalTransport');
      case 'local_stdio':
        return t('mcpTools.localStdio');
      default:
        return value || t('mcpTools.unknown');
    }
  };

  const formatClassification = (value?: string) => {
    switch (value) {
      case 'official_reference_stdio':
        return t('mcpTools.officialStdio');
      case 'project_or_remote_transport':
        return t('mcpTools.projectRemote');
      default:
        return value || t('mcpTools.unclassified');
    }
  };

  const formatTimestamp = (value?: string) => {
    if (!value) {
      return t('mcpTools.unknown');
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const confirmToolCall = () => {
    if (!selectedTool) {
      return;
    }
    const normalizedArgs = pruneEmptyOptionalArgs(selectedTool.input_schema || {}, toolArgs);
    const missingRequired = getMissingRequiredToolArgs(selectedTool, normalizedArgs);
    if (missingRequired.length > 0) {
      setToolValidationError(t('modal.requiredMissing', { fields: missingRequired.join(', ') }));
      return;
    }
    onToolCall(selectedTool.server, selectedTool.name, normalizedArgs);
    setSelectedTool(null);
    setToolArgs({});
    setToolValidationError(null);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center space-x-3 text-gray-600 dark:text-gray-300">
          <RefreshCw className="h-5 w-5 animate-spin" />
          <span>{t('mcpTools.loading')}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center space-y-4 text-center">
        <AlertCircle className="h-10 w-10 text-red-500" />
        <div>
          <p className="text-lg font-semibold text-red-600 dark:text-red-300">{t('mcpTools.loadFailed')}</p>
          <p className="mt-2 max-w-2xl text-sm text-gray-600 dark:text-gray-400">{error}</p>
        </div>
        <button
          type="button"
          onClick={fetchData}
          className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {t('mcpTools.retry')}
        </button>
      </div>
    );
  }

  const expandAllServers = () => {
    setExpandedServers(new Set(Object.keys(groupedTools)));
  };

  const collapseAllServers = () => {
    setExpandedServers(new Set());
  };

  const focusServerTools = (serverName: string) => {
    setActiveTab('tools');
    setHighlightedServer(serverName);
    setExpandedServers(new Set([serverName]));
  };

  const openServerDiagnostics = (serverName: string) => {
    setActiveTab('servers');
    setHighlightedServer(serverName);
  };

  const clearServerFocus = () => {
    setHighlightedServer(null);
  };

  return (
    <div className="flex h-full flex-col bg-gradient-to-br from-stone-50 via-sky-50 to-emerald-50 dark:from-gray-900 dark:via-gray-850 dark:to-gray-900">
      <div className="border-b border-white/30 bg-white/80 px-6 py-5 backdrop-blur-xl dark:border-gray-700/40 dark:bg-gray-800/80">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-r from-sky-500 to-emerald-500 text-white shadow-lg">
                <Wrench className="h-6 w-6" />
              </div>
              <div>
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{t('mcpTools.title')}</h2>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {t('mcpTools.description')}
                </p>
              </div>
            </div>
            {audit && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${audit.ok ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
                  <Shield className="mr-1 h-3.5 w-3.5" />
                  {t('mcpTools.audit')} {audit.ok ? t('mcpTools.auditPass') : t('mcpTools.auditIssue')}
                </div>
                <div className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                  {t('mcpTools.servers')} {servers.length}
                </div>
                <div className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                  {t('mcpTools.tools')} {tools.length}
                </div>
                <div className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                  {t('mcpTools.resources')} {resources.length}
                </div>
                <div className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                  {t('mcpTools.prompts')} {prompts.length}
                </div>
              </div>
            )}
          </div>

          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={fetchData}
              className="rounded-xl border border-white/30 bg-white/80 p-3 text-gray-600 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-gray-200"
              title={t('mcpTools.refresh')}
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl border border-white/30 bg-white/80 p-3 text-gray-600 shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/80 dark:text-gray-200"
                title={t('mcpTools.close')}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="border-b border-white/30 bg-white/60 px-6 py-4 backdrop-blur-xl dark:border-gray-700/40 dark:bg-gray-800/60">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('mcpTools.searchPlaceholder')}
              className="w-full rounded-2xl border border-white/30 bg-white/85 py-3 pl-11 pr-4 text-sm shadow-sm outline-none ring-0 transition focus:border-sky-400 dark:border-gray-700/40 dark:bg-gray-700/85 dark:text-white"
            />
          </div>
          <div className="flex items-center space-x-3">
            <div className="inline-flex items-center space-x-2 rounded-2xl border border-white/30 bg-white/85 px-4 py-3 text-sm shadow-sm dark:border-gray-700/40 dark:bg-gray-700/85 dark:text-white">
              <Filter className="h-4 w-4 text-gray-500" />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as 'all' | 'connected' | 'disconnected')}
                className="bg-transparent outline-none"
              >
                <option value="all">{t('mcpTools.allStatuses')}</option>
                <option value="connected">{t('mcpTools.connectedOnly')}</option>
                <option value="disconnected">{t('mcpTools.disconnectedOnly')}</option>
              </select>
            </div>
            {activeTab === 'tools' && (
              <>
                <label className="inline-flex items-center gap-2 rounded-2xl border border-white/30 bg-white/85 px-4 py-3 text-sm shadow-sm dark:border-gray-700/40 dark:bg-gray-700/85 dark:text-white">
                  <input
                    type="checkbox"
                    checked={callableOnly}
                    onChange={(event) => setCallableOnly(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                  <span>{t('mcpTools.callableOnly')}</span>
                </label>
                <button
                  type="button"
                  onClick={expandAllServers}
                  className="rounded-2xl border border-white/30 bg-white/85 px-4 py-3 text-sm shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/85 dark:text-white"
                >
                  {t('mcpTools.expandAll')}
                </button>
                <button
                  type="button"
                  onClick={collapseAllServers}
                  className="rounded-2xl border border-white/30 bg-white/85 px-4 py-3 text-sm shadow-sm transition hover:bg-white dark:border-gray-700/40 dark:bg-gray-700/85 dark:text-white"
                >
                  {t('mcpTools.collapseAll')}
                </button>
              </>
            )}
            {highlightedServer && (
              <button
                type="button"
                onClick={clearServerFocus}
                className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm font-medium text-sky-700 shadow-sm transition hover:bg-sky-100 dark:border-sky-900/40 dark:bg-sky-900/20 dark:text-sky-200"
              >
                {t('mcpTools.clearServerFocus')} {highlightedServer}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex border-b border-white/30 bg-white/50 px-6 dark:border-gray-700/40 dark:bg-gray-800/50">
        {[
          { key: 'tools', label: t('mcpTools.toolsTab'), count: filteredTools.length, icon: Wrench },
          { key: 'servers', label: t('mcpTools.serversTab'), count: filteredServers.length, icon: Server },
          { key: 'resources', label: t('mcpTools.resourcesTab'), count: filteredResources.length, icon: FileText },
          { key: 'prompts', label: t('mcpTools.promptsTab'), count: filteredPrompts.length, icon: Brain },
        ].map(({ key, label, count, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key as 'tools' | 'servers' | 'resources' | 'prompts')}
            className={`flex items-center space-x-2 border-b-2 px-5 py-4 text-sm font-medium transition ${
              activeTab === key
                ? 'border-sky-500 text-sky-700 dark:text-sky-300'
                : 'border-transparent text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white'
            }`}
          >
            <Icon className="h-4 w-4" />
            <span>{label}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700 dark:bg-slate-700 dark:text-slate-200">
              {count}
            </span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === 'tools' && (
          <div className="space-y-4">
            {Object.keys(groupedTools).length === 0 ? (
              <div className="rounded-2xl border border-dashed border-gray-300 bg-white/70 p-10 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800/70 dark:text-gray-400">
                {t('mcpTools.emptyTools')}
              </div>
            ) : (
              Object.entries(groupedTools).map(([serverName, serverTools]) => (
                <div key={serverName} className="overflow-hidden rounded-2xl border border-white/40 bg-white/80 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                  <button
                    type="button"
                    onClick={() => toggleServerExpanded(serverName)}
                    className="flex w-full items-center justify-between px-5 py-4 text-left"
                  >
                    <div className="flex items-center space-x-3">
                      {expandedServers.has(serverName) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      <div>
                        <div className="font-semibold text-gray-900 dark:text-white">{serverName}</div>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{serverTools.length} {t('mcpTools.tools')}</div>
                      </div>
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {formatClassification(audit?.server_catalog.find((item) => item.name === serverName)?.classification) || t('mcpTools.custom')}
                    </div>
                  </button>

                  {expandedServers.has(serverName) && (
                    <div className="space-y-3 border-t border-white/30 px-5 py-4 dark:border-gray-700/40">
                      {serverTools.map((tool) => (
                        <div key={`${tool.server}.${tool.name}`} className="flex items-start justify-between rounded-xl border border-slate-200 bg-slate-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/40">
                          <div className="pr-4">
                            <div className="flex items-center space-x-2">
                              <span className="font-medium text-gray-900 dark:text-white">{tool.display_name || tool.name}</span>
                              {tool.server_status === 'connected' ? (
                                <CheckCircle className="h-4 w-4 text-green-500" />
                              ) : (
                                <AlertCircle className="h-4 w-4 text-yellow-500" />
                              )}
                            </div>
                            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{tool.description || t('mcpTools.noDescription')}</p>
                              {tool.input_schema?.properties && (
                              <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                                {t('mcpTools.parameters')}: {Object.keys(getJsonSchemaProperties(tool.input_schema || {})).join(', ')}
                              </div>
                            )}
                          </div>
                          <button
                            type="button"
                            disabled={tool.server_status !== 'connected'}
                            onClick={() => {
                              if (Object.keys(getJsonSchemaProperties(tool.input_schema || {})).length > 0) {
                                setSelectedTool(tool);
                                setToolArgs(buildDefaultArgs(tool));
                                setToolValidationError(null);
                              } else {
                                onToolCall(tool.server, tool.name, {});
                              }
                            }}
                            className="inline-flex items-center space-x-2 rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:bg-gray-400"
                          >
                            <Play className="h-4 w-4" />
                            <span>{t('mcpTools.call')}</span>
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'servers' && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
              <div className="rounded-2xl border border-white/40 bg-white/80 p-4 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-center space-x-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                    <CheckCircle className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">{t('mcpTools.connectedSummary')}</div>
                    <div className="text-xl font-semibold text-gray-900 dark:text-white">
                      {servers.filter((server) => server.status === 'connected').length}/{servers.length}
                    </div>
                  </div>
                </div>
              </div>
              <div className="rounded-2xl border border-white/40 bg-white/80 p-4 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-center space-x-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                    <Server className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">{t('mcpTools.official')}</div>
                    <div className="text-xl font-semibold text-gray-900 dark:text-white">
                      {audit?.server_catalog.filter((item) => item.classification === 'official_reference_stdio').length || 0}
                    </div>
                  </div>
                </div>
              </div>
              <div className="rounded-2xl border border-white/40 bg-white/80 p-4 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-center space-x-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                    <Shield className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">{t('mcpTools.audit')}</div>
                    <div className="text-xl font-semibold text-gray-900 dark:text-white">
                      {audit?.ok ? t('common.pass') : t('common.warning')}
                    </div>
                  </div>
                </div>
              </div>
              <div className="rounded-2xl border border-white/40 bg-white/80 p-4 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-center space-x-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300">
                    <AlertCircle className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">{t('mcpTools.issues')}</div>
                    <div className="text-xl font-semibold text-gray-900 dark:text-white">
                      {servers.filter((server) => server.status === 'error' || Boolean(server.error_message)).length}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {filteredServers.map((server) => {
              const auditItem = audit?.server_catalog.find((item) => item.name === server.name);
              const auditCheck = audit?.checks?.[server.name];
              const hasAuditErrors = Boolean(auditCheck && auditCheck.errors.length > 0);
              const hasRuntimeError = Boolean(server.error_message);
              return (
                <div key={server.name} className="rounded-2xl border border-white/40 bg-white/80 p-5 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center space-x-3">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{server.name}</h3>
                        {renderServerStatus(server)}
                      </div>
                      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">{server.description}</p>
                    </div>
                    {auditItem && (
                      <div className="flex flex-col items-end gap-2">
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                          {formatClassification(auditItem.classification)}
                        </span>
                        <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${
                          hasAuditErrors ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                        }`}>
                          {hasAuditErrors ? <ShieldAlert className="mr-1 h-3.5 w-3.5" /> : <ShieldCheck className="mr-1 h-3.5 w-3.5" />}
                          {hasAuditErrors ? t('mcpTools.auditIssues') : t('mcpTools.auditClean')}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.tools')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{server.tools_count}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.resources')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{server.resources_count}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.prompts')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{server.prompts_count}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.runtime')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{formatConnectionType(server.connection_type || auditItem?.runtime_connection_type)}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.configured')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{auditItem?.configured_transport || t('mcpTools.unknown')}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.client')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{server.client_connected ? t('mcpTools.attached') : t('mcpTools.detached')}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.enabled')}</div>
                      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{server.enabled ? t('memoryEvaluation.yes') : t('memoryEvaluation.no')}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-gray-900/40">
                      <div className="text-xs text-gray-500 dark:text-gray-400">{t('mcpTools.lastPing')}</div>
                      <div className="mt-1 text-xs font-semibold text-gray-900 dark:text-white">{formatTimestamp(server.last_ping)}</div>
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
                    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/30">
                      <div className="mb-3 flex items-center space-x-2 text-sm font-medium text-gray-800 dark:text-gray-200">
                        <Server className="h-4 w-4" />
                        <span>{t('mcpTools.runtimeSummary')}</span>
                      </div>
                      <div className="space-y-2 text-xs text-gray-600 dark:text-gray-400">
                        <div>
                          <span className="font-medium text-gray-800 dark:text-gray-200">{t('mcpTools.status')}:</span> {server.status}
                        </div>
                        <div>
                          <span className="font-medium text-gray-800 dark:text-gray-200">{t('mcpTools.classification')}:</span> {formatClassification(auditItem?.classification)}
                        </div>
                        <div>
                          <span className="font-medium text-gray-800 dark:text-gray-200">{t('mcpTools.runtimeConnection')}:</span> {formatConnectionType(auditItem?.runtime_connection_type || server.connection_type)}
                        </div>
                        <div>
                          <span className="font-medium text-gray-800 dark:text-gray-200">{t('mcpTools.runtimeTools')}:</span> {auditItem?.runtime_tools?.length || server.tools.length}
                        </div>
                        <div>
                          <span className="font-medium text-gray-800 dark:text-gray-200">{t('mcpTools.serverTools')}:</span> {server.tools.length > 0 ? server.tools.join(', ') : t('common.none')}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-gray-700 dark:bg-gray-900/30">
                      <div className="mb-3 flex items-center space-x-2 text-sm font-medium text-gray-800 dark:text-gray-200">
                        <Shield className="h-4 w-4" />
                        <span>{t('mcpTools.diagnostics')}</span>
                      </div>
                      <div className="mb-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => focusServerTools(server.name)}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
                        >
                          {t('mcpTools.viewServerTools')}
                        </button>
                        <button
                          type="button"
                          onClick={fetchData}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
                        >
                          {t('mcpTools.refreshRuntime')}
                        </button>
                        <button
                          type="button"
                          onClick={() => openServerDiagnostics(server.name)}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
                        >
                          {t('mcpTools.focusDiagnostics')}
                        </button>
                      </div>
                      {!hasAuditErrors && !hasRuntimeError ? (
                        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300">
                          {t('mcpTools.noRuntimeAuditIssues')}
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {hasRuntimeError && (
                            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                              <div className="mb-1 font-medium">{t('mcpTools.runtimeError')}</div>
                              <div>{server.error_message}</div>
                            </div>
                          )}
                          {hasAuditErrors && (
                            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-3 text-xs text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
                              <div className="mb-1 font-medium">{t('mcpTools.auditErrors')}</div>
                              <ul className="list-disc space-y-1 pl-4">
                                {auditCheck?.errors.map((item) => (
                                  <li key={item}>{item}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                </div>
              );
            })}
          </div>
        )}

        {activeTab === 'resources' && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {filteredResources.map((resource) => (
              <div key={`${resource.server}:${resource.uri}`} className="rounded-2xl border border-white/40 bg-white/80 p-5 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-start justify-between space-x-4">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold text-gray-900 dark:text-white">{resource.name}</h3>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{resource.description || t('mcpTools.noDescription')}</p>
                    <div className="mt-3 space-y-1 text-xs text-gray-500 dark:text-gray-400">
                      <div>{t('mcpTools.server')}: {resource.server}</div>
                      <div>{t('mcpTools.uri')}: {resource.uri}</div>
                      <div>{t('mcpTools.mime')}: {resource.mime_type || t('mcpTools.unknown')}</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onResourceRead(resource.server, resource.uri)}
                    className="inline-flex items-center space-x-2 rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-gray-600 dark:text-slate-200 dark:hover:bg-gray-700"
                  >
                    <Eye className="h-4 w-4" />
                    <span>{t('mcpTools.read')}</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'prompts' && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {filteredPrompts.map((prompt) => (
              <div key={`${prompt.server}:${prompt.name}`} className="rounded-2xl border border-white/40 bg-white/80 p-5 shadow-sm dark:border-gray-700/40 dark:bg-gray-800/80">
                <div className="flex items-start justify-between space-x-4">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold text-gray-900 dark:text-white">{prompt.name}</h3>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{prompt.description || t('mcpTools.noDescription')}</p>
                    <div className="mt-3 text-xs text-gray-500 dark:text-gray-400">
                      {t('mcpTools.server')}: {prompt.server}
                    </div>
                    {prompt.arguments && Object.keys(prompt.arguments).length > 0 && (
                      <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
                        <div className="mb-2 font-medium">{t('mcpTools.arguments')}</div>
                        {Object.entries(prompt.arguments).map(([key, value]) => (
                          <div key={key} className="mb-1 last:mb-0">
                            <span className="font-mono">{key}</span>: {typeof value === 'string' ? value : JSON.stringify(value)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => onPromptGet(prompt.server, prompt.name, {})}
                    className="inline-flex items-center space-x-2 rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-gray-600 dark:text-slate-200 dark:hover:bg-gray-700"
                  >
                    <Brain className="h-4 w-4" />
                    <span>{t('mcpTools.get')}</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedTool && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-white/30 bg-white/95 p-6 shadow-2xl dark:border-gray-700/40 dark:bg-gray-800/95">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xl font-semibold text-gray-900 dark:text-white">{selectedTool.display_name}</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{selectedTool.server}.{selectedTool.name}</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedTool(null);
                  setToolArgs({});
                  setToolValidationError(null);
                }}
                className="rounded-xl p-2 text-gray-500 transition hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm text-gray-700 dark:bg-gray-900/40 dark:text-gray-300">
              {selectedTool.description || t('mcpTools.noDescription')}
            </div>

            <div className="mt-6 space-y-4">
              {Object.entries(getJsonSchemaProperties(selectedTool.input_schema || {})).map(([key, schema]) => (
                <div key={key}>
                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    {((schema as JsonSchemaProperty).title) || key}
                    {getJsonSchemaRequired(selectedTool.input_schema || {}).includes(key) && (
                      <span className="ml-1 text-red-500">*</span>
                    )}
                  </label>
                  {resolveJsonSchemaType((schema as JsonSchemaProperty)) === 'boolean' ? (
                    <label className="inline-flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300">
                      <input
                        type="checkbox"
                        checked={Boolean(toolArgs[key])}
                        onChange={(e) => setToolArgs((prev) => ({ ...prev, [key]: e.target.checked }))}
                        className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                      />
                      <span>{t('modal.booleanEnabled')}</span>
                    </label>
                  ) : resolveJsonSchemaType((schema as JsonSchemaProperty)) === 'object' || resolveJsonSchemaType((schema as JsonSchemaProperty)) === 'array' ? (
                    <textarea
                      value={typeof toolArgs[key] === 'string' ? toolArgs[key] : JSON.stringify(toolArgs[key] ?? '', null, 2)}
                      onChange={(e) => {
                        const raw = e.target.value;
                        try {
                          setToolArgs((prev) => ({ ...prev, [key]: raw.trim() ? JSON.parse(raw) : raw }));
                        } catch {
                          setToolArgs((prev) => ({ ...prev, [key]: raw }));
                        }
                      }}
                      placeholder={(schema as Record<string, any>)?.description || key}
                      rows={4}
                      className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-sky-400 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  ) : (schema as JsonSchemaProperty).enum ? (
                    <select
                      value={String(toolArgs[key] ?? '')}
                      onChange={(e) => setToolArgs((prev) => ({
                        ...prev,
                        [key]: coerceJsonSchemaValue((schema as JsonSchemaProperty), e.target.value),
                      }))}
                      className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-sky-400 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    >
                      <option value="">{t('modal.selectValue')}</option>
                      {((schema as JsonSchemaProperty).enum || []).map((item) => (
                        <option key={String(item)} value={String(item)}>
                          {String(item)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={resolveJsonSchemaType((schema as JsonSchemaProperty)) === 'integer' || resolveJsonSchemaType((schema as JsonSchemaProperty)) === 'number' ? 'number' : 'text'}
                      value={toolArgs[key] ?? ''}
                      onChange={(e) => setToolArgs((prev) => ({
                        ...prev,
                        [key]: coerceJsonSchemaValue((schema as JsonSchemaProperty), e.target.value),
                      }))}
                      placeholder={(schema as Record<string, any>)?.description || key}
                      className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-sky-400 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    />
                  )}
                  {(schema as Record<string, any>)?.description && (
                    <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {(schema as Record<string, any>).description}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {toolValidationError && (
              <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
                {toolValidationError}
              </div>
            )}

            <div className="mt-6 flex justify-end space-x-3">
              <button
                type="button"
                onClick={() => {
                  setSelectedTool(null);
                  setToolArgs({});
                  setToolValidationError(null);
                }}
                className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-gray-600 dark:text-slate-200 dark:hover:bg-gray-700"
              >
                {t('mcpTools.cancel')}
              </button>
              <button
                type="button"
                onClick={confirmToolCall}
                className="inline-flex items-center space-x-2 rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
              >
                <Play className="h-4 w-4" />
                <span>{t('mcpTools.executeTool')}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MCPToolsPanel;
