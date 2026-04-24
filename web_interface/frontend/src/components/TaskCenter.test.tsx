import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TaskCenter from './task-center';

describe('TaskCenter', () => {
  it('renders queued outbound items, runtime requests, and agent tasks', async () => {
    const user = userEvent.setup();
    const onRefresh = jest.fn();

    render(
      <TaskCenter
        isOpen
        onClose={jest.fn()}
        loading={false}
        pendingQueueSize={1}
        pendingOutboundRequests={[
          {
            request_id: 'req-local-1',
            type: 'chat',
            content_preview: 'queued locally',
            created_at: '2026-04-17T01:00:00Z',
          },
        ]}
        tasks={[
          {
            request_id: 'req-backend-1',
            request_type: 'chat',
            status: 'failed',
            started_at: '2026-04-17T01:00:00Z',
            updated_at: '2026-04-17T01:00:02Z',
            client_ids: ['client-a'],
            watcher_count: 0,
            request_summary: {
              content_preview: 'backend request summary',
            },
            result_summary: {
              payload_type: 'error',
              runtime_status: 'failed',
              reason: 'backend failed',
            },
            is_inflight: false,
            is_recoverable: true,
            duration_ms: 2000,
          },
        ]}
        agentTasks={[
          {
            task_id: 'agent-task-1',
            client_id: 'client-a',
            goal: 'Inspect runtime health',
            mode: 'agent',
            status: 'running',
            created_at: '2026-04-17T01:00:00Z',
            updated_at: '2026-04-17T01:00:05Z',
            plan: {},
            steps: [
              {
                step_id: 'step-1',
                title: 'Collect evidence',
                kind: 'analysis',
                action: 'summarize_goal',
              },
            ],
            observations: [],
            verification: {},
            result_summary: {},
            source_plane_counts: {
              mcp: 0,
              system_op: 0,
            },
          },
        ]}
        onRefresh={onRefresh}
        language="en"
      />,
    );

    expect(screen.getByText('Task Center')).toBeInTheDocument();
    expect(screen.getByText('Runtime request journal')).toBeInTheDocument();
    expect(screen.getByText('backend request summary')).toBeInTheDocument();
    expect(screen.getByText('Inspect runtime health')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Queued' }));
    expect(screen.getByText('queued locally')).toBeInTheDocument();
  });
});

