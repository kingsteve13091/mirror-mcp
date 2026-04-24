import { buildApiUrl } from '../config/backend';
import {
  AIModel,
  AgentSkillSummary,
  AgentSkillExternalConfig,
  AgentSkillRuntimeResolution,
  AgentCapabilitiesResponse,
  AgentTask,
  AgentTaskListResponse,
  AgentTaskReplayResponse,
  BackendRouteSupport,
  BenchmarkReport,
  HealthSnapshot,
  MemoryPlaneLedger,
  MemoryPlaneTraceList,
  RuntimeRequestJournal,
  RuntimeProviderConfig,
  RuntimeMemoryPlaneState,
  ProviderConnectivityResult,
  RuntimeProviderState,
  AutoToolRoutingState,
  SystemOperationApprovalDecisionResponse,
  SystemOperationApprovalListResponse,
  ToolPolicyState,
  SystemOperationExecutionResponse,
  MCPAuditReport,
  MCPToolOnboardingAuditReport,
  MCPToolOnboardingSelfTestRunReport,
  MCPPrompt,
  MCPResource,
  MCPServerConfigList,
  MCPServerStatusPayload,
  MCPTool,
  WorkspaceAgentCommand,
  AutonomousTrajectoryCaseInput,
  AutonomousTrajectoryResult,
  PolicyEvaluationBatchCaseInput,
  PolicyEvaluationBatchResult,
  PolicyEvaluationResult,
  RollbackResult,
  SystemBootstrap,
  TEMGuard,
  TEMRecipe,
  TEMStats,
} from '../types';

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }

  return response.json() as Promise<T>;
}

export async function getSystemBootstrap(): Promise<SystemBootstrap> {
  return fetchJson<SystemBootstrap>('/api/system/bootstrap');
}

export async function getAgentSkills(): Promise<{
  ok: boolean;
  count: number;
  skills: AgentSkillSummary[];
  roots?: Array<Record<string, any>>;
  failed?: Array<Record<string, any>>;
}> {
  return fetchJson('/api/agent-skills');
}

export async function reloadAgentSkills(): Promise<{
  ok: boolean;
  count: number;
  ids?: string[];
  skills: AgentSkillSummary[];
  roots?: Array<Record<string, any>>;
  failed?: Array<Record<string, any>>;
}> {
  return fetchJson('/api/agent-skills/reload', {
    method: 'POST',
  });
}

export async function resolveAgentSkillRuntime(payload: {
  skill_ids?: string[];
  query?: string;
  model_id?: string;
  scopes?: string[];
  workspace_context?: Record<string, any>;
}): Promise<{
  ok: boolean;
  runtime: AgentSkillRuntimeResolution;
  workspace_agent_profile?: Record<string, any>;
}> {
  return fetchJson('/api/agent-skills/runtime', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getAgentSkillsExternalConfig(): Promise<AgentSkillExternalConfig> {
  return fetchJson('/api/agent-skills/external-config');
}

export async function updateAgentSkillsExternalConfig(payload: {
  external_skill_dirs: string[];
}): Promise<AgentSkillExternalConfig> {
  return fetchJson('/api/agent-skills/external-config', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getModels(): Promise<{ models: AIModel[]; default: string }> {
  return fetchJson<{ models: AIModel[]; default: string }>('/api/models');
}

export async function getRuntimeProviders(): Promise<RuntimeProviderState> {
  return fetchJson<RuntimeProviderState>('/api/runtime/providers');
}

export async function clearRuntimeProviders(): Promise<RuntimeProviderState & { ok: boolean; message: string }> {
  return fetchJson<RuntimeProviderState & { ok: boolean; message: string }>('/api/runtime/providers', {
    method: 'DELETE',
  });
}

export async function updateRuntimeProviders(config: RuntimeProviderConfig): Promise<RuntimeProviderState & { ok: boolean; message: string }> {
  return fetchJson<RuntimeProviderState & { ok: boolean; message: string }>('/api/runtime/providers', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function checkRuntimeProviderConnectivity(payload: {
  provider: 'siliconflow' | 'openrouter';
  api_key?: string;
  base_url?: string;
}): Promise<ProviderConnectivityResult> {
  return fetchJson<ProviderConnectivityResult>('/api/runtime/providers/check', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getRuntimeToolPolicy(): Promise<ToolPolicyState> {
  return fetchJson<ToolPolicyState>('/api/runtime/tool-policy');
}

export async function updateRuntimeToolPolicy(config: ToolPolicyState): Promise<ToolPolicyState> {
  return fetchJson<ToolPolicyState>('/api/runtime/tool-policy', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function getAgentCapabilities(): Promise<AgentCapabilitiesResponse> {
  return fetchJson<AgentCapabilitiesResponse>('/api/agent/capabilities');
}

export async function getAgentTasks(limit = 40, clientId?: string): Promise<AgentTaskListResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (clientId) {
    params.set('client_id', clientId);
  }
  return fetchJson<AgentTaskListResponse>(`/api/agent/tasks?${params.toString()}`);
}

export async function getAgentTask(taskId: string): Promise<{ ok: boolean; task: AgentTask }> {
  return fetchJson(`/api/agent/tasks/${encodeURIComponent(taskId)}`);
}

export async function createAgentTask(payload: {
  goal: string;
  client_id?: string;
  workspace_root?: string;
  attachments?: Record<string, any>[];
  skill_ids?: string[];
  mode?: string;
  run_kind?: string;
  scheduled_for?: string;
  parent_run_id?: string;
  scheduler_id?: string;
}): Promise<{ ok: boolean; task: AgentTask }> {
  return fetchJson('/api/agent/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function cancelAgentTask(taskId: string): Promise<{ ok: boolean; task: AgentTask }> {
  return fetchJson(`/api/agent/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
  });
}

export async function getAgentTaskReplay(taskId: string, limit = 200): Promise<AgentTaskReplayResponse> {
  return fetchJson(`/api/agent/tasks/${encodeURIComponent(taskId)}/replay?limit=${limit}`);
}

export async function getAgentOperationApprovals(params?: {
  client_id?: string;
  task_id?: string;
}): Promise<SystemOperationApprovalListResponse> {
  const query = new URLSearchParams();
  if (params?.client_id) {
    query.set('client_id', params.client_id);
  }
  if (params?.task_id) {
    query.set('task_id', params.task_id);
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return fetchJson(`/api/agent/operations/approvals${suffix}`);
}

export async function approveAgentOperation(taskId: string, approvalId: string, payload?: {
  client_id?: string;
  workspace_root?: string;
  attachments?: Record<string, any>[];
  note?: string;
}): Promise<SystemOperationApprovalDecisionResponse> {
  return fetchJson(`/api/agent/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export async function rejectAgentOperation(taskId: string, approvalId: string, payload?: {
  client_id?: string;
  workspace_root?: string;
  attachments?: Record<string, any>[];
  note?: string;
}): Promise<SystemOperationApprovalDecisionResponse> {
  return fetchJson(`/api/agent/tasks/${encodeURIComponent(taskId)}/approvals/${encodeURIComponent(approvalId)}/reject`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export async function executeSystemOperation(payload: {
  action_type: string;
  payload?: Record<string, any>;
  client_id?: string;
  task_id?: string;
  workspace_root?: string;
  policy_confirmed?: boolean;
}): Promise<SystemOperationExecutionResponse> {
  return fetchJson('/api/system-ops/execute', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getRuntimeAutoToolRouting(): Promise<AutoToolRoutingState> {
  return fetchJson<AutoToolRoutingState>('/api/runtime/auto-tool-routing');
}

export async function updateRuntimeAutoToolRouting(config: {
  mode: 'memory_plane_only' | 'memory_plane_plus_fallback';
}): Promise<AutoToolRoutingState> {
  return fetchJson<AutoToolRoutingState>('/api/runtime/auto-tool-routing', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function getRuntimeMemoryPlane(): Promise<RuntimeMemoryPlaneState> {
  return fetchJson<RuntimeMemoryPlaneState>('/api/runtime/memory-plane');
}

export async function updateRuntimeMemoryPlane(config: {
  absorb_system_op_audit: boolean;
}): Promise<RuntimeMemoryPlaneState> {
  return fetchJson<RuntimeMemoryPlaneState>('/api/runtime/memory-plane', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export async function getMcpTools(): Promise<{ tools: MCPTool[] }> {
  return fetchJson<{ tools: MCPTool[] }>('/api/mcp/tools');
}

export async function getMcpServers(): Promise<{ servers: MCPServerStatusPayload }> {
  return fetchJson<{ servers: MCPServerStatusPayload }>('/api/mcp/servers');
}

export async function getMcpResources(): Promise<{ resources: MCPResource[] }> {
  return fetchJson<{ resources: MCPResource[] }>('/api/mcp/resources');
}

export async function getMcpPrompts(): Promise<{ prompts: MCPPrompt[] }> {
  return fetchJson<{ prompts: MCPPrompt[] }>('/api/mcp/prompts');
}

export async function getMcpAudit(): Promise<MCPAuditReport> {
  return fetchJson<MCPAuditReport>('/api/mcp/audit');
}

export async function getMcpToolOnboardingAudit(workspaceRoot?: string): Promise<MCPToolOnboardingAuditReport> {
  const params = new URLSearchParams();
  if (workspaceRoot?.trim()) {
    params.set('workspace_root', workspaceRoot.trim());
  }
  const query = params.toString();
  return fetchJson<MCPToolOnboardingAuditReport>(`/api/mcp/tool-onboarding-audit${query ? `?${query}` : ''}`);
}

export async function runMcpToolOnboardingSelfTests(payload: {
  tool_keys?: string[];
  execute_safe_only?: boolean;
  max_tools?: number;
  workspace_root?: string;
}): Promise<MCPToolOnboardingSelfTestRunReport> {
  return fetchJson<MCPToolOnboardingSelfTestRunReport>('/api/mcp/tool-onboarding-audit/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function previewWorkspaceContext(payload: {
  workspace_root: string;
  agent_name?: string;
  include_agent_profile?: boolean;
  include_memory_file?: boolean;
  include_chatlogs?: boolean;
}): Promise<{
  ok: boolean;
  context_chars: number;
  preview: string;
  metadata: Record<string, any>;
  agent_profile?: Record<string, any>;
  commands?: WorkspaceAgentCommand[];
}> {
  return fetchJson('/api/workspace-context/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getMcpConfig(): Promise<MCPServerConfigList> {
  return fetchJson<MCPServerConfigList>('/api/mcp/config');
}

export async function saveMcpConfig(payload: {
  name: string;
  description: string;
  mode: 'stdio' | 'remote';
  disabled: boolean;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  transport?: string;
  timeout: number;
}): Promise<{
  ok: boolean;
  message: string;
  saved: Record<string, any>;
  reload_ok: boolean;
  runtime: MCPServerStatusPayload;
}> {
  return fetchJson('/api/mcp/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function deleteMcpConfig(serverName: string): Promise<{
  ok: boolean;
  message: string;
  deleted: Record<string, any>;
  reload_ok: boolean;
  runtime: MCPServerStatusPayload;
}> {
  return fetchJson(`/api/mcp/config/${encodeURIComponent(serverName)}`, {
    method: 'DELETE',
  });
}

export async function getTemStats(): Promise<TEMStats> {
  return fetchJson<TEMStats>('/api/tem/stats');
}

export async function getTemRecipes(): Promise<{ recipes: TEMRecipe[] }> {
  return fetchJson<{ recipes: TEMRecipe[] }>('/api/tem/recipes');
}

export async function getTemGuards(): Promise<{ guards: TEMGuard[] }> {
  return fetchJson<{ guards: TEMGuard[] }>('/api/tem/guards');
}

export async function setTemMode(
  mode: string,
): Promise<{ mode: string; supported_modes: string[]; flags: Record<string, boolean> }> {
  return fetchJson<{ mode: string; supported_modes: string[]; flags: Record<string, boolean> }>(
    '/api/tem/mode',
    {
      method: 'POST',
      body: JSON.stringify({ mode }),
    },
  );
}

export async function reloadRuntimeParams(): Promise<{
  ok: boolean;
  tool_execution_memory: Record<string, number>;
  context_engine: Record<string, string | number | boolean>;
  memory_control_plane: Record<string, string | number | boolean>;
}> {
  return fetchJson('/api/params/reload', {
    method: 'POST',
  });
}

export async function getHealthSnapshot(): Promise<HealthSnapshot> {
  return fetchJson<HealthSnapshot>('/health');
}

export async function getRuntimeRequests(limit = 40, clientId?: string): Promise<RuntimeRequestJournal> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (clientId) {
    params.set('client_id', clientId);
  }
  return fetchJson<RuntimeRequestJournal>(`/api/runtime/requests?${params.toString()}`);
}

export async function getBackendRouteSupport(): Promise<BackendRouteSupport> {
  const openApi = await fetchJson<{ paths?: Record<string, unknown> }>('/openapi.json');
  const paths = openApi?.paths || {};
  const hasPath = (path: string) => Object.prototype.hasOwnProperty.call(paths, path);

  return {
    health: hasPath('/health'),
    systemBootstrap: hasPath('/api/system/bootstrap'),
    runtimeProviders: hasPath('/api/runtime/providers'),
    runtimeRequests: hasPath('/api/runtime/requests'),
    mcpToolOnboardingAudit: hasPath('/api/mcp/tool-onboarding-audit'),
    temBenchmark: hasPath('/api/tem/benchmark'),
    temDecisions: hasPath('/api/tem/decisions'),
    memoryPlane: hasPath('/api/memory-plane'),
    memoryPlaneTraces: hasPath('/api/memory-plane/traces'),
    memoryPlaneLedger: hasPath('/api/memory-plane/ledger'),
    memoryPlaneEvaluate: hasPath('/api/memory-plane/evaluate'),
    memoryPlaneEvaluateBatch: hasPath('/api/memory-plane/evaluate_batch'),
    memoryPlaneAutonomousTrajectory: hasPath('/api/memory-plane/autonomous_trajectory'),
    memoryPlaneRollback: hasPath('/api/memory-plane/rollback'),
  };
}

export async function runTemBenchmark(): Promise<BenchmarkReport> {
  return fetchJson<BenchmarkReport>('/api/tem/benchmark', {
    method: 'POST',
  });
}

export async function getMemoryPlaneSnapshot(): Promise<{ ok: boolean; snapshot: Record<string, any> }> {
  return fetchJson<{ ok: boolean; snapshot: Record<string, any> }>('/api/memory-plane');
}

export async function getMemoryPlaneTraces(limit = 20): Promise<MemoryPlaneTraceList> {
  return fetchJson<MemoryPlaneTraceList>(`/api/memory-plane/traces?limit=${limit}`);
}

export async function getMemoryPlaneLedger(limit = 20): Promise<MemoryPlaneLedger> {
  return fetchJson<MemoryPlaneLedger>(`/api/memory-plane/ledger?limit=${limit}`);
}

export async function evaluateMemoryPolicy(payload: {
  query: string;
  client_id?: string;
  candidate_tools?: string[];
  expected_tool?: string;
}): Promise<PolicyEvaluationResult> {
  return fetchJson<PolicyEvaluationResult>('/api/memory-plane/evaluate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function evaluateMemoryPolicyBatch(payload: {
  cases: PolicyEvaluationBatchCaseInput[];
  dry_run?: boolean;
}): Promise<PolicyEvaluationBatchResult> {
  return fetchJson<PolicyEvaluationBatchResult>('/api/memory-plane/evaluate_batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function evaluateAutonomousTrajectory(payload: {
  cases: AutonomousTrajectoryCaseInput[];
  tem_mode: string;
  reset_tem_before_run?: boolean;
  max_steps_per_case?: number;
  execute_selected_tool?: boolean;
  argument_policy_mode?: string;
  stop_on_misroute?: boolean;
  stop_on_failure?: boolean;
  restore_state_after_run?: boolean;
  feature_mask?: Record<string, boolean>;
}): Promise<AutonomousTrajectoryResult> {
  return fetchJson<AutonomousTrajectoryResult>('/api/memory-plane/autonomous_trajectory', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function rollbackMemoryGovernance(reason: string): Promise<RollbackResult> {
  return fetchJson<RollbackResult>('/api/memory-plane/rollback', {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function getTemDecisions(limit = 20): Promise<{
  decision_trace_path: string;
  decisions: Array<Record<string, any>>;
  count: number;
}> {
  return fetchJson(`/api/tem/decisions?limit=${limit}`);
}

export async function getLearningStatus(): Promise<import('../types').ParameterLearningStatus> {
  return fetchJson('/api/params/learning_status');
}

export async function applyParameterRecommendation(): Promise<Record<string, any>> {
  return fetchJson('/api/params/apply_recommendation', {
    method: 'POST',
  });
}

export async function uploadFile(file: File): Promise<import('../types').UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(buildApiUrl('/api/upload'), {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }

  return response.json() as Promise<import('../types').UploadResponse>;
}
