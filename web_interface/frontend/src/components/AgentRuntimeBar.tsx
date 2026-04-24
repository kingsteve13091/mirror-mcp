import React, { useMemo } from 'react';
import {
  Bot,
  ClipboardList,
  FolderKanban,
  ShieldAlert,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import {
  AgentSkillRuntimeResolution,
  AgentCapabilitiesResponse,
  AvailableTool,
  WorkspaceAgentProfile,
  WorkspaceMcpState,
} from '../types';

interface AgentRuntimeBarProps {
  visible: boolean;
  language: 'zh' | 'en';
  agentModeEnabled: boolean;
  agentModeProfile: 'chat' | 'agent' | 'research';
  workspaceAgentProfile?: WorkspaceAgentProfile | null;
  workspaceMcpState?: WorkspaceMcpState | null;
  skillRuntime?: AgentSkillRuntimeResolution | null;
  agentCapabilities?: AgentCapabilitiesResponse | null;
  availableTools: AvailableTool[];
  sessionAllowedServers?: string[];
  runningAgentTasks: number;
  activeRuntimeRequestsCount: number;
  pendingApprovalsCount: number;
  completedAgentTasks?: number;
  showCompletedCount?: boolean;
  onOpenTasks: () => void;
}

function t(language: 'zh' | 'en', zh: string, en: string) {
  return language === 'zh' ? zh : en;
}

const AgentRuntimeBar: React.FC<AgentRuntimeBarProps> = ({
  visible,
  language,
  agentModeEnabled,
  agentModeProfile,
  workspaceAgentProfile = null,
  workspaceMcpState = null,
  skillRuntime = null,
  agentCapabilities = null,
  availableTools,
  sessionAllowedServers = [],
  runningAgentTasks,
  activeRuntimeRequestsCount,
  pendingApprovalsCount,
  completedAgentTasks = 0,
  showCompletedCount = false,
  onOpenTasks,
}) => {
  const allowedServerNames = useMemo(() => {
    const merged = new Set<string>();
    (workspaceAgentProfile?.allowMCPs || []).forEach((item) => {
      const value = String(item || '').trim();
      if (value) {
        merged.add(value);
      }
    });
    sessionAllowedServers.forEach((item) => {
      const value = String(item || '').trim();
      if (value) {
        merged.add(value);
      }
    });
    return Array.from(merged);
  }, [sessionAllowedServers, workspaceAgentProfile]);

  const workspaceServerCount = useMemo(() => {
    if (allowedServerNames.length > 0) {
      return allowedServerNames.length;
    }
    return Array.isArray(workspaceMcpState?.workspace_servers) ? workspaceMcpState!.workspace_servers!.length : 0;
  }, [allowedServerNames, workspaceMcpState]);

  const systemCapabilities = Array.isArray(agentCapabilities?.system_operation_capabilities)
    ? agentCapabilities!.system_operation_capabilities
    : [];
  const commandCount = Array.isArray(workspaceAgentProfile?.commands) ? workspaceAgentProfile!.commands!.length : 0;
  const skillRuntimePayload = skillRuntime ?? undefined;
  const rawSkillRuntimeCards = skillRuntimePayload?.skill_cards;
  const rawActiveSkillIds = skillRuntimePayload?.active_skill_ids;
  const rawImplicitSkillIds = skillRuntimePayload?.implicit_skill_ids;
  const rawRecoveryPolicies = skillRuntimePayload?.recovery_policies;
  const rawActionTemplates = skillRuntimePayload?.action_templates;
  const skillRuntimeCards = Array.isArray(rawSkillRuntimeCards) ? rawSkillRuntimeCards : [];
  const activeSkillIds = Array.isArray(rawActiveSkillIds) ? rawActiveSkillIds : [];
  const implicitSkillIds = Array.isArray(rawImplicitSkillIds) ? rawImplicitSkillIds : [];
  const recoveryPolicies = Array.isArray(rawRecoveryPolicies) ? rawRecoveryPolicies : [];
  const actionTemplates = Array.isArray(rawActionTemplates) ? rawActionTemplates : [];
  const activeSkillCount = activeSkillIds.length;
  const implicitSkillCount = implicitSkillIds.length;
  const recoveryPolicyCount = recoveryPolicies.length;
  const actionTemplateCount = actionTemplates.length;
  const topSkillNames = skillRuntimeCards
    .map((item) => String(item?.name || '').trim())
    .filter(Boolean)
    .slice(0, 2);
  const terminalReady = systemCapabilities.some((item) => item.action_type === 'terminal_command');
  const confirmRequiredCount = systemCapabilities.filter((item) => item.requires_confirmation).length;
  const statusToneClass = pendingApprovalsCount > 0
    ? 'border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-100'
    : agentModeEnabled
      ? 'border-violet-200 bg-violet-50/80 text-violet-900 dark:border-violet-900/40 dark:bg-violet-950/20 dark:text-violet-100'
      : 'border-slate-200 bg-slate-50/80 text-slate-800 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-100';

  if (!visible) {
    return null;
  }

  return (
    <div className="px-4 pt-3 sm:px-5 lg:px-8 xl:px-10" data-testid="agent-runtime-bar">
      <div className="mx-auto w-full max-w-[1500px]">
        <div className={`rounded-2xl border px-4 py-3 shadow-sm ${statusToneClass}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-2 text-sm font-semibold">
                  <Bot className="h-4 w-4" />
                  <span>{t(language, '\u4ee3\u7406\u8fd0\u884c\u6001', 'Agent Runtime')}</span>
                </span>
                <span className="rounded-full border border-current/15 px-2.5 py-1 text-xs font-medium">
                  {agentModeEnabled ? t(language, '\u5df2\u542f\u7528', 'Enabled') : t(language, '\u672a\u542f\u7528', 'Disabled')}
                </span>
                <span className="rounded-full border border-current/15 px-2.5 py-1 text-xs font-medium">
                  {agentModeProfile}
                </span>
                {workspaceAgentProfile?.agent_name && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1 text-xs font-medium">
                    {t(language, '\u5de5\u4f5c\u533a Agent', 'Workspace agent')}: {workspaceAgentProfile.agent_name}
                  </span>
                )}
                {workspaceAgentProfile?.modelKey && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1 text-xs font-medium">
                    {t(language, '\u6a21\u578b', 'Model')}: {workspaceAgentProfile.modelKey}
                  </span>
                )}
                {activeSkillCount > 0 && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1 text-xs font-medium">
                    {t(language, `\u6280\u80fd ${activeSkillCount}`, `${activeSkillCount} skills active`)}
                  </span>
                )}
              </div>

              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                  <FolderKanban className="h-3.5 w-3.5" />
                  <span>
                    {workspaceServerCount > 0
                      ? t(language, `\u53ef\u89c1 MCP Server ${workspaceServerCount}`, `${workspaceServerCount} visible MCP servers`)
                      : t(language, '\u672a\u9650\u5236 MCP Server', 'MCP servers not restricted')}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                  <Wrench className="h-3.5 w-3.5" />
                  <span>{t(language, `\u53ef\u7528\u5de5\u5177 ${availableTools.length}`, `${availableTools.length} tools available`)}</span>
                </span>
                {commandCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <ClipboardList className="h-3.5 w-3.5" />
                    <span>{t(language, `\u5de5\u4f5c\u533a\u547d\u4ee4 ${commandCount}`, `${commandCount} workspace commands`)}</span>
                  </span>
                )}
                <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                  <TerminalSquare className="h-3.5 w-3.5" />
                  <span>
                    {terminalReady
                      ? t(language, '\u7ec8\u7aef\u80fd\u529b\u5df2\u5c31\u7eea', 'Terminal capability ready')
                      : t(language, '\u7ec8\u7aef\u80fd\u529b\u672a\u5f00\u653e', 'Terminal capability unavailable')}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  <span>
                    {systemCapabilities.length > 0
                      ? t(language, `\u7cfb\u7edf\u64cd\u4f5c ${systemCapabilities.length} \u7c7b`, `${systemCapabilities.length} system actions`)
                      : t(language, '\u7cfb\u7edf\u64cd\u4f5c\u672a\u52a0\u8f7d', 'System actions not loaded')}
                  </span>
                </span>
                {confirmRequiredCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <ShieldAlert className="h-3.5 w-3.5" />
                    <span>{t(language, `\u9700\u5ba1\u6279 ${confirmRequiredCount}`, `${confirmRequiredCount} approval-gated`)}</span>
                  </span>
                )}
                {activeSkillCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <Bot className="h-3.5 w-3.5" />
                    <span>
                      {topSkillNames.length > 0
                        ? topSkillNames.join(' + ')
                        : t(language, '\u5df2\u89e3\u6790\u6280\u80fd\u8fd0\u884c\u65f6', 'Skill runtime active')}
                    </span>
                  </span>
                )}
                {implicitSkillCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <Bot className="h-3.5 w-3.5" />
                    <span>{t(language, `\u81ea\u52a8\u6fc0\u6d3b ${implicitSkillCount}`, `${implicitSkillCount} auto-activated`)}</span>
                  </span>
                )}
                {actionTemplateCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <ClipboardList className="h-3.5 w-3.5" />
                    <span>{t(language, `\u6267\u884c\u811a\u624b\u67b6 ${actionTemplateCount}`, `${actionTemplateCount} action templates`)}</span>
                  </span>
                )}
                {recoveryPolicyCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-current/15 bg-white/60 px-2.5 py-1 dark:bg-slate-950/20">
                    <ShieldAlert className="h-3.5 w-3.5" />
                    <span>{t(language, `\u6062\u590d\u7b56\u7565 ${recoveryPolicyCount}`, `${recoveryPolicyCount} recovery policies`)}</span>
                  </span>
                )}
              </div>

              <div className="mt-2 text-xs opacity-80">
                {pendingApprovalsCount > 0
                  ? t(language, '\u68c0\u6d4b\u5230 system operation \u5f85\u5ba1\u6279\uff0c\u6279\u51c6\u540e Agent \u4f1a\u81ea\u52a8\u7ee7\u7eed\u6267\u884c\u3002', 'A system operation is waiting for approval. The agent continues automatically after approval.')
                  : t(language, '\u5f53\u524d\u4f1a\u8bdd\u6309\u5de5\u4f5c\u533a Agent \u548c MCP \u53ef\u89c1\u6027\u89c4\u5219\u63ed\u9732\u5de5\u5177\uff0cMemory Plane \u4e3b\u94fe\u4fdd\u6301\u4e0d\u53d8\u3002', 'This session exposes tools according to the workspace agent and MCP visibility rules while keeping the Memory Plane flow unchanged.')}
              </div>
            </div>

            <div className="flex flex-col items-stretch gap-2 sm:items-end">
              <div className="flex flex-wrap justify-end gap-2 text-xs">
                {runningAgentTasks > 0 && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1">
                    {t(language, `\u8fd0\u884c\u4e2d ${runningAgentTasks}`, `${runningAgentTasks} running`)}
                  </span>
                )}
                {activeRuntimeRequestsCount > 0 && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1">
                    {t(language, `\u94fe\u8def\u8bf7\u6c42 ${activeRuntimeRequestsCount}`, `${activeRuntimeRequestsCount} runtime requests`)}
                  </span>
                )}
                {pendingApprovalsCount > 0 && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1">
                    {t(language, `\u5f85\u5ba1\u6279 ${pendingApprovalsCount}`, `${pendingApprovalsCount} approvals`)}
                  </span>
                )}
                {showCompletedCount && completedAgentTasks > 0 && (
                  <span className="rounded-full border border-current/15 px-2.5 py-1">
                    {t(language, `\u5df2\u5b8c\u6210 ${completedAgentTasks}`, `${completedAgentTasks} completed`)}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={onOpenTasks}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-current/15 bg-white/70 px-3 py-2 text-xs font-medium transition hover:bg-white dark:bg-slate-950/30 dark:hover:bg-slate-950/50"
              >
                <ClipboardList className="h-4 w-4" />
                <span>{t(language, '\u6253\u5f00\u4efb\u52a1\u4e2d\u5fc3', 'Open task center')}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AgentRuntimeBar;
