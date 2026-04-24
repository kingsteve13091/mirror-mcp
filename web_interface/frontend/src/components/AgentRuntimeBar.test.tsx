import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentRuntimeBar from './AgentRuntimeBar';

describe('AgentRuntimeBar', () => {
  it('renders workspace agent, capability, and runtime status summary', async () => {
    const user = userEvent.setup();
    const onOpenTasks = jest.fn();

    render(
      <AgentRuntimeBar
        visible
        language="en"
        agentModeEnabled
        agentModeProfile="agent"
        workspaceAgentProfile={{
          agent_name: 'project-assistant',
          allowMCPs: ['filesystem', 'fetch'],
          isConfirmCallTool: true,
          modelKey: 'Qwen/Qwen3-VL-8B-Instruct',
          commands: [
            { name: 'review', description: 'Review code' },
            { name: 'test', description: 'Run tests' },
          ],
        }}
        workspaceMcpState={{
          workspace_enabled: true,
          workspace_root: 'D:\\mirror_mcp',
          workspace_servers: ['filesystem', 'fetch'],
        }}
        agentCapabilities={{
          ok: true,
          system_operation_capabilities: [
            {
              action_type: 'terminal_command',
              title: 'Terminal',
              description: 'Run terminal command',
              risk_level: 'high',
              requires_confirmation: true,
            },
            {
              action_type: 'workspace_file_op',
              title: 'Workspace file op',
              description: 'Operate files',
              risk_level: 'medium',
              requires_confirmation: true,
            },
          ],
          task_runtime: {},
          operation_audit: {},
        }}
        availableTools={[
          { server: 'filesystem', name: 'read_file', display_name: 'read_file' },
          { server: 'fetch', name: 'fetch', display_name: 'fetch' },
          { server: 'memory', name: 'store', display_name: 'store' },
        ]}
        sessionAllowedServers={['filesystem']}
        runningAgentTasks={2}
        activeRuntimeRequestsCount={1}
        pendingApprovalsCount={1}
        completedAgentTasks={3}
        showCompletedCount
        onOpenTasks={onOpenTasks}
      />,
    );

    expect(screen.getByTestId('agent-runtime-bar')).toBeInTheDocument();
    expect(screen.getByText('Agent Runtime')).toBeInTheDocument();
    expect(screen.getByText(/Workspace agent: project-assistant/)).toBeInTheDocument();
    expect(screen.getByText(/2 visible MCP servers/)).toBeInTheDocument();
    expect(screen.getByText(/3 tools available/)).toBeInTheDocument();
    expect(screen.getByText(/2 workspace commands/)).toBeInTheDocument();
    expect(screen.getByText(/Terminal capability ready/)).toBeInTheDocument();
    expect(screen.getByText(/2 system actions/)).toBeInTheDocument();
    expect(screen.getByText(/2 approval-gated/)).toBeInTheDocument();
    expect(screen.getByText(/2 running/)).toBeInTheDocument();
    expect(screen.getByText(/1 runtime requests/)).toBeInTheDocument();
    expect(screen.getAllByText(/1 approvals/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /Open task center/i }));
    expect(onOpenTasks).toHaveBeenCalledTimes(1);
  });
});
