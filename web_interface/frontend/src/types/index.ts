export interface ChatMessage {
  id: string;
  type: 'user' | 'assistant' | 'system' | 'error';
  content: string;
  timestamp: string;
  image_path?: string;
  image_paths?: string[];
  attachments?: ChatAttachment[];
  request_id?: string;
  delivery_status?: MessageDeliveryStatus;
  delivery_error?: string;
  retryable?: boolean;
  retry_payload?: WebSocketMessage;
  metadata?: {
    generated_images?: GeneratedImage[];
    execution_time?: number;
    tools_used?: string[];
    model_used?: string;
    model_name?: string;
    memory?: MemoryStats;
    tem_event?: TEMEvent;
    causal_trace?: CausalTrace;
    run_trace?: Record<string, any>;
    guard_evidence?: Record<string, any>;
    recipe_preflight?: Record<string, any>;
    agent_event?: {
      kind: 'task_created' | 'task_running' | 'task_waiting_approval' | 'task_completed' | 'task_failed' | 'task_cancelled' | 'approval_needed' | 'approval_resolved';
      task_id: string;
      title?: string;
      summary?: string;
      status?: string;
      mode?: string;
      goal?: string;
      step_title?: string;
      step_id?: string;
      approval_id?: string;
      approval_action?: string;
      risk_level?: string;
      counts?: {
        mcp?: number;
        system_op?: number;
        completed_steps?: number;
        total_steps?: number;
      };
    };
    action_event?: {
      action_id: string;
      stage: 'prepared' | 'precheck' | 'started' | 'observed' | 'completed' | string;
      status: 'running' | 'success' | 'failed' | 'blocked' | string;
      title?: string;
      summary?: string;
      source_plane?: string;
      target?: {
        server?: string;
        tool?: string;
      };
    };
    resource_refs?: ResourceReference[];
    [key: string]: any;
  };
}

export interface GeneratedImage {
  url?: string;
  data_url?: string;
  path?: string;
  mime_type?: string;
  alt?: string;
  source?: string;
}

export type MessageDeliveryStatus = 'draft' | 'pending' | 'sent' | 'processing' | 'failed' | 'blocked';

export interface ToolCall {
  id: string;
  name: string;
  parameters: Record<string, any>;
  result?: any;
  status: 'pending' | 'running' | 'success' | 'error';
  error?: string;
}

export interface AIModel {
  id: string;
  name: string;
  description: string;
  type: 'text' | 'multimodal';
  max_tokens: number;
  provider?: string;
  available?: boolean;
  provider_configured?: boolean;
}

export interface CustomModelConfig {
  id: string;
  name: string;
  description?: string;
  type: 'text' | 'multimodal';
  max_tokens: number;
  provider: string;
}

export interface RuntimeProviderConfig {
  credential_mode: CredentialStorageMode;
  siliconflow_api_key: string;
  siliconflow_base_url: string;
  openrouter_api_key: string;
  openrouter_base_url: string;
  default_model: string;
  custom_models: CustomModelConfig[];
}

export type CredentialStorageMode = 'session_only' | 'backend_env_only' | 'local_persist';

export interface AvailableTool {
  server: string;
  name: string;
  display_name: string;
}

export interface MCPTool extends AvailableTool {
  enabled: boolean;
  description: string;
  server_status: string;
  client_connected: boolean;
  input_schema?: Record<string, any>;
}

export interface MCPServer {
  name: string;
  status: string;
  enabled: boolean;
  description: string;
  tools: string[];
  tools_count: number;
  resources_count: number;
  prompts_count: number;
  client_connected: boolean;
  connection_type?: string;
  last_ping: string;
  error_message?: string;
}

export interface MCPServerConfig {
  disabled?: boolean;
  description?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  transport?: string;
  timeout?: number;
}

export interface MCPServerConfigItem {
  name: string;
  mode: 'stdio' | 'remote' | 'unknown';
  editable: boolean;
  classification: string;
  config: MCPServerConfig;
}

export interface MCPServerConfigList {
  config_path: string;
  servers: MCPServerConfigItem[];
  protected_servers: string[];
}

export interface MCPServerConfigForm {
  name: string;
  description: string;
  mode: 'stdio' | 'remote';
  disabled: boolean;
  command: string;
  argsText: string;
  envText: string;
  url: string;
  transport: string;
  timeout: number;
}

export interface MCPResource {
  server: string;
  uri: string;
  name: string;
  description: string;
  mime_type: string;
}

export interface MCPPrompt {
  server: string;
  name: string;
  description: string;
  arguments?: Record<string, any>;
}

export interface MCPAuditServerCatalogItem {
  name: string;
  classification: string;
  configured_transport: string;
  runtime_connection_type: string;
  runtime_status: string;
  runtime_tools: string[];
}

export interface MCPAuditCheck {
  ok: boolean;
  config: Record<string, any>;
  runtime: Record<string, any>;
  runtime_tools: string[];
  errors: string[];
}

export interface MCPAuditReport {
  ok: boolean;
  errors: string[];
  checks: Record<string, MCPAuditCheck>;
  server_catalog: MCPAuditServerCatalogItem[];
}

export interface MCPToolOnboardingAuditItem {
  tool_key: string;
  server: string;
  name: string;
  description: string;
  automation_class: 'auto_executable' | 'auto_routable_manual_confirm' | 'manual_only';
  auto_routable: boolean;
  auto_executable: boolean;
  inferred_fields_sample: string[];
  required_fields: string[];
  schema_property_count: number;
  schema_warnings: string[];
  harness?: {
    capabilities: string[];
    risk_level: string;
    path_like_fields: string[];
    url_like_fields: string[];
    text_like_fields: string[];
    image_like_fields: string[];
    default_visibility: string;
    server_visibility_model: string;
  };
  self_test: {
    status: string;
    safe_to_run: boolean;
    gate_required?: boolean;
    reason: string;
    expected_outcome?: string;
    sample_arguments: Record<string, any>;
    required_fields: string[];
    inferred_fields: string[];
    command_hint?: string;
  };
}

export interface MCPToolOnboardingAuditReport {
  ok: boolean;
  summary: {
    total_tools: number;
    auto_routable_tools: number;
    auto_executable_tools: number;
    manual_only_tools: number;
    schema_risk_tools: number;
  };
  issues: string[];
  tools: MCPToolOnboardingAuditItem[];
  workspace_mcp?: WorkspaceMcpState;
}

export interface MCPToolOnboardingSelfTestResult {
  tool_key: string;
  server?: string;
  name?: string;
  started_at?: string;
  completed_at?: string;
  ok: boolean;
  status: string;
  skipped?: boolean;
  reason?: string;
  arguments?: Record<string, any>;
  latency_ms?: number;
  result_preview?: string;
  error_preview?: string;
}

export interface MCPToolOnboardingSelfTestRunReport {
  ok: boolean;
  summary: {
    requested: number;
    executed_or_skipped: number;
    passed: number;
    failed: number;
    skipped: number;
    gate_failed: number;
  };
  results: MCPToolOnboardingSelfTestResult[];
  workspace_mcp?: WorkspaceMcpState;
}

export interface WorkspaceAgentProfile {
  agent_name?: string;
  agent_dir?: string;
  allowMCPs?: string[];
  isConfirmCallTool?: boolean;
  modelKey?: string;
  commands?: WorkspaceAgentCommand[];
  skill_runtime?: AgentSkillRuntimeResolution;
}

export interface WorkspaceAgentCommand {
  name: string;
  path?: string;
  description?: string;
  body_preview?: string;
  body_chars?: number;
}

export interface WorkspaceMcpState {
  workspace_enabled?: boolean;
  workspace_root?: string;
  workspace_config_path?: string;
  workspace_servers?: string[];
  sources?: string[];
  error?: string;
}

export interface MCPServerStatusPayload {
  servers: MCPServer[];
  total_servers: number;
  connected_servers: number;
  total_tools: number;
  total_resources: number;
  total_prompts: number;
  last_update: string;
  fastmcp_available: boolean;
}

export interface ProviderStatus {
  configured: boolean;
  base_url?: string;
  runtime_override?: boolean;
}

export interface AgentSkillSummary {
  id: string;
  name: string;
  description: string;
  trigger: string;
  source_path: string;
  root_path: string;
  body_preview: string;
  body_length: number;
  compatibility: string[];
  allowed_tools: string[];
  metadata: Record<string, any>;
  license: string;
  resources: string[];
  diagnostics: string[];
  activation_mode: string;
  scopes: string[];
  platform_targets: string[];
  allowed_mcp_servers: string[];
  allowed_toolsets: string[];
  preferred_models: string[];
  workspace_patterns: string[];
  input_patterns: string[];
  action_templates: Array<Record<string, any>>;
  recovery_policies: string[];
  visibility: string;
  requires_confirmation: boolean;
  runtime_hints: Record<string, any>;
  external_root: boolean;
}

export interface AgentSkillRootSummary {
  path: string;
  exists: boolean;
  skill_count: number;
  external: boolean;
  error?: string;
}

export interface AgentSkillExternalConfig {
  ok?: boolean;
  path: string;
  exists: boolean;
  external_skill_dirs: string[];
  env_value?: string;
  error?: string;
  roots?: AgentSkillRootSummary[];
  skills?: AgentSkillSummary[];
}

export interface AgentSkillRuntimeResolution {
  version: string;
  requested_skill_ids: string[];
  active_skill_ids: string[];
  implicit_skill_ids: string[];
  skipped_skill_ids: string[];
  prompt_context: string;
  allowed_mcp_servers: string[];
  preferred_models: string[];
  action_templates: Array<Record<string, any>>;
  recovery_policies: string[];
  capability_overlay: Record<string, any>;
  skill_cards: Array<Record<string, any>>;
}

export interface SystemBootstrap {
  status: string;
  timestamp: string;
  providers: {
    siliconflow: ProviderStatus;
    openrouter: ProviderStatus;
  };
  models: {
    default: string;
    available: AIModel[];
    count: number;
    active_count?: number;
  };
  agent_skills: {
    count: number;
    skills: AgentSkillSummary[];
    roots?: AgentSkillRootSummary[];
    failed?: Array<Record<string, any>>;
  };
  mcp: {
    available: boolean;
    servers: MCPServerStatusPayload;
    connected_servers: string[];
    tools: MCPTool[];
    tools_count: number;
    audit: MCPAuditReport;
    tool_onboarding_audit?: MCPToolOnboardingAuditReport;
  };
  tem: {
    mode: string;
    supported_modes: string[];
    flags: Record<string, boolean>;
  };
  tool_policy?: ToolPolicyState;
  auto_tool_routing?: AutoToolRoutingState;
  memory_plane?: MemoryPlaneSnapshot;
}

export interface RuntimeProviderState {
  providers: {
    siliconflow: ProviderStatus;
    openrouter: ProviderStatus;
  };
  models: {
    default: string;
    available: AIModel[];
    count: number;
    active_count?: number;
    custom_count: number;
  };
  runtime_overrides: {
    has_siliconflow_key: boolean;
    siliconflow_base_url?: string;
    has_openrouter_key: boolean;
    openrouter_base_url?: string;
    default_model?: string;
    custom_models: CustomModelConfig[];
  };
}

export interface ToolPolicyState {
  enabled: boolean;
  default_action: 'allow' | 'confirm' | 'deny';
  tool_actions: Record<string, 'allow' | 'confirm' | 'deny'>;
  server_actions: Record<string, 'allow' | 'confirm' | 'deny'>;
  system_actions?: Record<string, 'allow' | 'confirm' | 'deny'>;
  deny_risky_write_paths: boolean;
  ok?: boolean;
  message?: string;
}

export interface AutoToolRoutingState {
  mode: 'memory_plane_only' | 'memory_plane_plus_fallback';
  fallback_enabled: boolean;
  file_path_fallback_enabled: boolean;
  url_fetch_fallback_enabled: boolean;
  available_modes: Array<{
    id: 'memory_plane_only' | 'memory_plane_plus_fallback';
    label: string;
    description: string;
  }>;
  ok?: boolean;
  message?: string;
}

export interface RuntimeMemoryPlaneState {
  absorb_system_op_audit: boolean;
  ok?: boolean;
  message?: string;
}

export interface RuntimeView {
  availableTools: AvailableTool[];
  connectedServers: string[];
  totalServers: number;
  toolsCount: number;
  temMode: string;
  providerReady: boolean;
}

export interface ProviderConnectivityResult {
  ok: boolean;
  provider: string;
  reachable: boolean;
  authenticated: boolean;
  endpoint: string;
  status_code?: number | null;
  model_count?: number;
  message: string;
  reason?: string;
  error_text?: string;
}

export interface MemoryPlaneAttributionItem {
  source: string;
  item_id: string;
  label: string;
  score: number;
  freshness: number;
  rationale: string;
}

export interface MemoryPlaneSnapshot {
  timestamp: string;
  schema_version?: string;
  phase?: string;
  client_id?: string;
  routing: Record<string, any>;
  retention: Record<string, any>;
  forgetting: Record<string, any>;
  governance?: Record<string, any>;
  governance_summary?: Record<string, any>;
  ledger_summary?: Record<string, any>;
  memory_plane?: {
    schema_version?: string;
    phase?: string;
    plane_kind?: string;
    trace_artifact_path?: string;
    ledger_artifact_path?: string;
    governance_mode?: string;
    policy_version?: string;
    governance_event_count?: number;
    attribution_count?: number;
  };
  attribution: MemoryPlaneAttributionItem[];
  causal_ablation?: {
    available: boolean;
    reason?: string;
    selected_tool?: string;
    router_type?: string;
    ablations?: Array<{
      feature: string;
      baseline_probability: number;
      counterfactual_probability: number;
      delta: number;
      significant?: boolean;
    }>;
    significant_effects?: string[];
    attribution_sources?: string[];
  };
}

export interface CausalTrace {
  selected_tool: string;
  routing_candidates: string[];
  top_alternative_tool?: string;
  intent_signature?: string;
  recipe_memory_used: boolean;
  guard_memory_used: boolean;
  context_summary_used: boolean;
  counterfactual_without_recipe: string;
  counterfactual_without_guard: string;
  counterfactual_without_summary: string;
  counterfactual_without_global_reliability?: string;
  counterfactual_without_intent_reliability?: string;
  routing_score_observed?: number;
  routing_score_components?: Record<string, number>;
  execution_policy_action?: string;
  recipe_preflight_decision?: string;
  recipe_preflight_reason?: string;
  blocked: boolean;
  success: boolean;
  guard_id?: string;
  counterfactual_action?: string;
  policy_learning_outcome?: string;
  significant_causal_effects?: string[];
  governance_event_count?: number;
  causal_ablation?: MemoryPlaneSnapshot['causal_ablation'];
  shadow_replay?: {
    available: boolean;
    reason?: string;
    selected_tool?: string;
    items?: Array<{
      tool_name: string;
      observed_final_score: number;
      observed_probability: number;
      would_be_selected: boolean;
      memory_components: Record<string, number>;
    }>;
  };
}

export interface ConnectionStatus {
  status: 'connecting' | 'connected' | 'disconnected' | 'error';
  message?: string;
  available_tools?: AvailableTool[];
  mcp_servers_available?: boolean;
  connected_servers?: string[];
  providers_ready?: boolean;
  agent_skills?: AgentSkillSummary[];
  skill_runtime?: AgentSkillRuntimeResolution;
  workspace_mcp?: WorkspaceMcpState;
}

export interface WebSocketMessage {
  type: string;
  [key: string]: any;
}

export interface ChatAttachment {
  filename: string;
  original_filename: string;
  file_path: string;
  url: string;
  size: number;
  mime_type?: string;
  is_image?: boolean;
  parse_status?: string;
  parse_mode?: string;
  parser?: string | null;
  preview_text?: string;
  full_text_chars?: number | null;
  visible_text_chars?: number | null;
  preview_truncated?: boolean;
  parse_error?: string | null;
  transport_role?: 'visual_model' | 'text_context' | 'tool_grounding' | 'metadata_only';
  transport_reason?: string;
  model_visible_on_current_turn?: boolean;
  tool_usable_on_current_turn?: boolean;
}

export interface ResourceReference {
  ref_id: string;
  kind: 'uploaded_image' | 'uploaded_file' | 'workspace_path' | 'url' | string;
  label?: string;
  path?: string;
  url?: string;
  mime_type?: string;
  size?: number;
  source?: string;
  model_visible?: boolean;
  tool_usable?: boolean;
  parse_status?: string;
  transport_role?: string;
}

export interface AttachmentExecutionPlanItem {
  id: string;
  filename: string;
  is_image: boolean;
  parse_status: string;
  transport_role: 'visual_model' | 'text_context' | 'tool_grounding' | 'metadata_only';
  transport_reason: string;
  model_visible_on_current_turn: boolean;
  tool_usable_on_current_turn: boolean;
  will_send_image_data: boolean;
  will_send_attachment_record: boolean;
}

export interface AttachmentExecutionPlan {
  items: AttachmentExecutionPlanItem[];
  has_visual_model_input: boolean;
  has_text_context_input: boolean;
  has_tool_grounding_input: boolean;
  has_metadata_only_input: boolean;
  summary_label: string;
}

export interface ChatSettings {
  dark_mode: boolean;
  confirmToolCalls: boolean;
  showAdvancedDebugTraces: boolean;
  agentModeEnabled: boolean;
  agentModeProfile: 'chat' | 'agent' | 'research';
  language: 'zh' | 'en';
  enabledSkillIds: string[];
  enableCustomSystemPrompt: boolean;
  customSystemPrompt: string;
  enableWorkspaceContext: boolean;
  workspaceContextRoot: string;
  workspaceContextAgentName: string;
  workspaceContextIncludeAgentProfile: boolean;
  workspaceContextIncludeMemoryFile: boolean;
  workspaceContextIncludeChatlogs: boolean;
  sessionAllowMCPs: string[];
  toolPolicyEnabled: boolean;
  toolPolicyDefaultAction: 'allow' | 'confirm' | 'deny';
  toolPolicyServerRules: string;
  toolPolicyToolRules: string;
  toolPolicySystemRules: string;
  toolPolicyDenyRiskyWritePaths: boolean;
  autoToolRoutingMode: 'memory_plane_only' | 'memory_plane_plus_fallback';
}

export interface AgentTaskStep {
  step_id: string;
  title: string;
  kind: string;
  action: string;
  parallel_group?: string;
  requires_confirmation?: boolean;
  status?: string;
  started_at?: string;
  completed_at?: string;
  result_summary?: Record<string, any>;
  error?: string;
}

export interface AgentTaskObservation {
  timestamp: string;
  source_plane: 'mcp' | 'system_op' | string;
  action: string;
  step_id?: string;
  observation: Record<string, any>;
}

export interface AgentTask {
  task_id: string;
  run_id?: string;
  client_id: string;
  goal: string;
  mode: string;
  status: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  workspace_root?: string;
  plan: Record<string, any>;
  plan_version?: string;
  steps: AgentTaskStep[];
  current_step_index?: number;
  observations: AgentTaskObservation[];
  verification: Record<string, any>;
  result_summary: Record<string, any>;
  source_plane_counts: Record<string, number>;
  pending_approvals?: SystemOperationApproval[];
  replay_events?: AgentTaskReplayEvent[];
  execution_events?: AgentTaskReplayEvent[];
  lifecycle?: {
    phase?: string;
    phase_history?: Array<{
      phase: string;
      timestamp: string;
      reason?: string;
    }>;
    last_error?: string;
    retry_count?: number;
    cancel_requested?: boolean;
    paused?: boolean;
  };
  run_kind?: string;
  scheduler?: {
    scheduler_id?: string;
    trigger?: Record<string, any>;
    scheduled_for?: string;
    last_heartbeat_at?: string;
  };
  relationships?: {
    parent_run_id?: string;
    child_run_ids?: string[];
  };
}

export interface AgentTaskListResponse {
  ok: boolean;
  count: number;
  status_counts: Record<string, number>;
  items: AgentTask[];
}

export interface AgentCapabilitiesResponse {
  ok: boolean;
  system_operation_capabilities: Array<{
    action_type: string;
    title: string;
    description: string;
    risk_level: string;
    requires_confirmation: boolean;
  }>;
  task_runtime: Record<string, any>;
  operation_audit: Record<string, any>;
  scheduler?: Record<string, any>;
}

export interface SystemOperationApproval {
  approval_id: string;
  task_id: string;
  step_id: string;
  client_id?: string;
  action_type: string;
  payload: Record<string, any>;
  payload_preview?: string;
  decision: {
    allowed: boolean;
    requires_confirmation: boolean;
    policy_action: string;
    reason: string;
    suggestion: string;
    risk_level: string;
  };
  risk_level: string;
  reason: string;
  suggestion: string;
  workspace_root?: string;
  status: 'pending' | 'approved' | 'rejected' | string;
  created_at: string;
  resolved_at?: string;
  note?: string;
}

export interface AgentTaskReplayEvent {
  event_id: string;
  timestamp: string;
  event: string;
  source_plane: string;
  step_id?: string;
  event_kind?: string;
  task_id?: string;
  run_id?: string;
  payload: Record<string, any>;
}

export interface AgentTaskReplayResponse {
  ok: boolean;
  task_id: string;
  run_id?: string;
  status: string;
  current_step_index?: number;
  events: AgentTaskReplayEvent[];
  execution_events?: AgentTaskReplayEvent[];
  observations: AgentTaskObservation[];
  pending_approvals: SystemOperationApproval[];
}

export interface SystemOperationApprovalListResponse {
  ok: boolean;
  count: number;
  items: SystemOperationApproval[];
}

export interface SystemOperationApprovalDecisionResponse {
  ok: boolean;
  approval: SystemOperationApproval;
  task?: AgentTask;
  result?: Record<string, any>;
  audit?: Record<string, any>;
  decision?: Record<string, any>;
}

export interface SystemOperationExecutionResponse {
  ok: boolean;
  blocked?: boolean;
  action_type: string;
  task_id?: string;
  decision: {
    allowed: boolean;
    requires_confirmation: boolean;
    policy_action: string;
    reason: string;
    suggestion: string;
    risk_level: string;
  };
  result?: Record<string, any>;
  audit?: Record<string, any>;
}

export interface PerformanceReport {
  total_orchestrations: number;
  successful_orchestrations: number;
  average_execution_time: number;
  best_performing_paths: Record<string, any>;
  server_reliability: Record<string, number>;
}

export interface UploadResponse {
  success: boolean;
  filename: string;
  original_filename?: string;
  file_path?: string;
  path?: string;
  size: number;
  mime_type?: string;
  content_type?: string;
  parse_status?: string;
  parse_mode?: string;
  parser?: string | null;
  preview_text?: string;
  full_text_chars?: number | null;
  visible_text_chars?: number | null;
  preview_truncated?: boolean;
  parse_error?: string | null;
}

export interface MemoryStats {
  total_messages: number;
  messages_sent: number;
  messages_summarized: number;
  original_tokens: number;
  compressed_tokens: number;
  compression_ratio: number;
  long_term_facts: number;
  has_summary: boolean;
}

export interface MemoryStatus {
  client_id: string;
  message_count: number;
  total_user_messages: number;
  total_compressions: number;
  has_summary: boolean;
  summary_preview: string;
  long_term_facts: string[];
  estimated_tokens: number;
  created_at: string;
}

export interface TEMRecipe {
  id: string;
  name: string;
  description: string;
  preconditions: string[];
  steps: {
    tool_name: string;
    parameter_schema?: Record<string, string>;
    expected_result_hint: string;
    server_name: string;
  }[];
  parameter_schema: Record<string, string>;
  success_count: number;
  fail_count: number;
  success_rate: number;
  failure_rate?: number;
  avg_latency_ms: number;
  created_at: string;
  last_used_at: string;
  tags: string[];
  evidence_count?: number;
  schema_consistency?: number;
  contamination_risk?: number;
  promotion_state?: string;
  quality_score?: number;
  last_failed_at?: string;
  retired_at?: string;
  suppression_reason?: string;
  governance_state?: string;
  governance_reason?: string;
  retrieval_count?: number;
  verification_rate?: number;
  verified_success_count?: number;
  verified_fail_count?: number;
  last_verified_at?: string;
  program_memory_type?: string;
  verification_total?: number;
  verifiable?: boolean;
  quality_evidence?: Record<string, any>;
}

export interface TEMGuard {
  id: string;
  tool_name: string;
  server_name: string;
  error_type: string;
  error_message: string;
  argument_pattern: Record<string, string>;
  argument_value_hash: string;
  context_hint: string;
  alternative_suggestion: string;
  failure_cause: string;
  block_count: number;
  created_at: string;
  last_triggered_at: string;
  posterior_failure_prob?: number;
  governance_state?: string;
  governance_reason?: string;
  avoided_count?: number;
  match_level?: string;
  counterfactual_memory_type?: string;
  counterfactual?: Record<string, any>;
}

export interface BenchmarkScenario {
  name: string;
  passed: boolean;
  metrics: Record<string, number>;
  details: string;
}

export interface BenchmarkReport {
  timestamp: string;
  duration_ms: number;
  scenarios: BenchmarkScenario[];
  summary: {
    total_scenarios: number;
    passed: number;
    failed: number;
    pass_rate: number;
  };
}

export interface TEMStats {
  mode?: string;
  mode_flags?: Record<string, boolean>;
  total_recipes: number;
  total_guards: number;
  total_blocks: number;
  failure_cause_distribution: Record<string, number>;
  recipe_state_distribution?: Record<string, number>;
  top_recipes: TEMRecipe[];
  top_guards: TEMGuard[];
  recent_decisions?: Array<Record<string, any>>;
  decision_trace_path?: string;
}

export interface TEMEvent {
  tool_name: string;
  success: boolean;
  recipe_learned?: {
    id: string;
    name: string;
    success_count: number;
    success_rate: number;
    quality_score?: number;
    promotion_state?: string;
    contamination_risk?: number;
  };
  recipe_penalties?: string[];
  guard_created?: {
    id: string;
    tool_name: string;
    error_type: string;
    suggestion: string;
    block_count: number;
  };
}

export interface ParameterLearningStatus {
  feedback_count: number;
  min_feedback_for_update: number;
  auto_apply_interval: number;
  exploration_probability: number;
  last_applied_recommendation?: {
    ts?: string;
    applied?: Array<{
      section: string;
      key: string;
      old: string | number | boolean;
      new: string | number | boolean;
    }>;
  };
  state_file: string;
  feedback_log_file: string;
}

export interface BackendRouteSupport {
  health: boolean;
  systemBootstrap: boolean;
  runtimeProviders: boolean;
  runtimeRequests?: boolean;
  mcpToolOnboardingAudit?: boolean;
  temBenchmark: boolean;
  temDecisions: boolean;
  memoryPlane: boolean;
  memoryPlaneTraces: boolean;
  memoryPlaneLedger: boolean;
  memoryPlaneEvaluate: boolean;
  memoryPlaneEvaluateBatch?: boolean;
  memoryPlaneAutonomousTrajectory?: boolean;
  memoryPlaneRollback: boolean;
}

export interface HealthSnapshot {
  status: string;
  timestamp: string;
  mcp_manager: string;
  siliconflow_api: string;
  siliconflow_base_url?: string;
  openrouter_api: string;
  openrouter_base_url?: string;
  providers?: RuntimeProviderState['providers'];
  models?: RuntimeProviderState['models'];
  tem?: {
    mode: string;
    supported_modes?: string[];
    flags?: Record<string, boolean>;
  };
  mcp?: {
    connected_servers: string[];
    servers: MCPServerStatusPayload;
    tools_count: number;
    audit: MCPAuditReport;
    tool_onboarding_audit?: MCPToolOnboardingAuditReport;
  };
  memory_plane?: Record<string, any>;
}

export interface MemoryPlaneTraceList {
  ok: boolean;
  availability?: 'available' | 'unavailable' | 'route_missing';
  reason?: string;
  trace_path: string;
  count: number;
  items: Array<Record<string, any>>;
}

export interface MemoryPlaneLedger {
  ok: boolean;
  availability?: 'available' | 'unavailable' | 'route_missing';
  reason?: string;
  schema_version?: string;
  ledger_path?: string;
  summary?: Record<string, any>;
  training_events?: Array<Record<string, any>>;
  governance_events: Array<Record<string, any>>;
  causal_events: Array<Record<string, any>>;
  shadow_replay_events: Array<Record<string, any>>;
  rollback_events: Array<Record<string, any>>;
}

export interface PolicyEvaluationResult {
  ok: boolean;
  query: string;
  client_id: string;
  expected_tool?: string;
  dry_run?: boolean;
  top1_match?: boolean;
  topk_match?: boolean;
  router_type: string;
  intent_signature: string;
  recommended_tools: string[];
  top_score: number;
  candidate_count: number;
  routing_scores: Array<Record<string, any>>;
  ablation: Record<string, any>;
  attribution: MemoryPlaneAttributionItem[];
  governance: Record<string, any>;
  router_training_state?: Record<string, any>;
  evaluation_ready: boolean;
  policy_learning_ready: boolean;
}

export interface PolicyEvaluationBatchCaseInput {
  id?: string;
  query: string;
  expected_tool?: string;
  candidate_tools?: string[];
  client_id?: string;
}

export interface PolicyEvaluationBatchCaseResult extends PolicyEvaluationResult {
  id: string;
  candidate_pool_size: number;
}

export interface PolicyEvaluationBatchResult {
  ok: boolean;
  dry_run: boolean;
  cases: PolicyEvaluationBatchCaseResult[];
  summary: {
    total: number;
    top1_accuracy: number;
    topk_recall: number;
    mean_top_score: number;
    mean_candidate_count: number;
  };
  per_mode: Record<string, {
    cases: number;
    top1_accuracy: number;
    topk_recall: number;
    mean_top_score: number;
  }>;
  per_feature: Record<string, {
    cases: number;
    mean_feature_value?: number;
    top1_accuracy?: number;
    masked_top1_accuracy?: number;
    masked_topk_recall?: number;
    top1_gain?: number;
    topk_gain?: number;
    mean_score_delta?: number;
    top1_flip_rate?: number;
    mask?: Record<string, boolean>;
  }>;
  calibration: Array<{
    bucket: string;
    count: number;
    mean_predicted_score: number;
    empirical_top1_accuracy: number;
    gap: number;
  }>;
}

export interface AutonomousTrajectoryStepInput {
  tool: string;
  server?: string;
  arguments: Record<string, any>;
  should_succeed?: boolean;
  error_type?: string;
  error_message?: string;
  expect_contains?: string[];
  expect_not_contains?: string[];
}

export interface AutonomousTrajectoryCaseInput {
  id?: string;
  task: string;
  category?: string;
  difficulty?: string;
  expected_success?: boolean;
  candidate_tools?: string[];
  tools_available?: string[];
  memory_focus?: string[];
  steps: AutonomousTrajectoryStepInput[];
  client_id?: string;
}

export interface AutonomousTrajectoryArgumentPolicySummary {
  policy_steps: number;
  supported_rate: number;
  fallback_rate: number;
  unsupported_rate: number;
  schema_match_rate: number;
  exact_match_rate: number;
  memory_conditioned_step_share: number;
  memory_conditioned_supported_rate: number;
  state_reuse_rate: number;
  counts?: Record<string, number>;
}

export interface AutonomousTrajectoryCategorySummary {
  cases: number;
  actual_case_success_rate: number;
  expectation_match_rate: number;
  policy_steps: number;
  fallback_rate: number;
  unsupported_rate: number;
  memory_conditioned_step_share: number;
  memory_conditioned_supported_rate: number;
  state_reuse_rate: number;
}

export interface AutonomousTrajectoryStepSummary {
  steps: number;
  supported_rate: number;
  fallback_rate: number;
  unsupported_rate: number;
  memory_conditioned_step_share: number;
  state_reuse_rate: number;
  verified_rate: number;
  successful_call_rate: number;
}

export interface AutonomousTrajectorySummary {
  total_cases: number;
  total_steps: number;
  routed_steps: number;
  route_top1_accuracy: number;
  execution_rate: number;
  tool_success_rate: number;
  blocked_call_rate: number;
  verification_rate: number;
  misroute_rate: number;
  wasted_call_rate: number;
  actual_case_success_rate: number;
  expectation_match_rate: number;
  argument_policy: AutonomousTrajectoryArgumentPolicySummary;
  per_category: Record<string, AutonomousTrajectoryCategorySummary>;
  per_step: Record<string, AutonomousTrajectoryStepSummary>;
  totals?: Record<string, number>;
}

export interface AutonomousTrajectoryResult {
  ok: boolean;
  tem_mode: string;
  feature_mask: Record<string, boolean>;
  summary: AutonomousTrajectorySummary;
  cases: Array<Record<string, any>>;
}

export interface RollbackResult {
  ok: boolean;
  restored_recipes: Record<string, any>;
  restored_guards: Record<string, any>;
  rollback_event: Record<string, any>;
}

export interface RuntimeRequestResultSummary {
  payload_type: string;
  runtime_status: string;
  timestamp?: string;
  replayed?: boolean;
  replay_source?: string;
  content_preview?: string;
  model_name?: string;
  success?: boolean;
  result_preview?: string;
  reason?: string;
  suggestion?: string;
  error_type?: string;
}

export interface RuntimeRequestJournalEntry {
  request_id: string;
  request_type: string;
  status: string;
  started_at?: string;
  updated_at?: string;
  client_ids: string[];
  watcher_count: number;
  request_summary: Record<string, any>;
  result_summary: RuntimeRequestResultSummary;
  is_inflight: boolean;
  is_recoverable: boolean;
  duration_ms?: number | null;
}

export interface RuntimeRequestJournal {
  ok: boolean;
  journal_path: string;
  count: number;
  limit: number;
  client_id?: string;
  status_counts: Record<string, number>;
  items: RuntimeRequestJournalEntry[];
}
