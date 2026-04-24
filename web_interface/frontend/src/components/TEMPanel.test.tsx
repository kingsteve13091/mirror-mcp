import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TEMPanel from './TEMPanel';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import * as api from '../services/api';
import { TEMStats } from '../types';

jest.mock('../services/api');

const mockedApi = api as jest.Mocked<typeof api>;

const temStats: TEMStats = {
  mode: 'full_tem',
  total_recipes: 1,
  total_guards: 1,
  total_blocks: 0,
  failure_cause_distribution: {},
  top_recipes: [],
  top_guards: [],
};

function renderPanel() {
  return render(
    <I18nProvider settings={{ ...DEFAULT_CHAT_SETTINGS, language: 'en' }}>
      <TEMPanel
        isOpen
        onClose={jest.fn()}
        clientId="client-test"
        temStats={temStats}
        recipes={[
          {
            id: 'recipe-1',
            name: 'List directory recipe',
            description: 'Reusable filesystem listing.',
            preconditions: [],
            steps: [{ tool_name: 'list_directory', expected_result_hint: 'files', server_name: 'filesystem' }],
            parameter_schema: {},
            success_count: 3,
            fail_count: 0,
            success_rate: 1,
            avg_latency_ms: 12,
            created_at: '2026-04-16T00:00:00Z',
            last_used_at: '2026-04-16T00:00:00Z',
            tags: [],
          },
        ]}
        guards={[
          {
            id: 'guard-1',
            tool_name: 'write_file',
            server_name: 'filesystem',
            error_type: 'permission_denied',
            error_message: 'write blocked',
            argument_pattern: {},
            argument_value_hash: 'hash',
            context_hint: '',
            alternative_suggestion: 'Use read-only tools first.',
            failure_cause: 'unsafe_write',
            block_count: 2,
            created_at: '2026-04-16T00:00:00Z',
            last_triggered_at: '2026-04-16T00:00:00Z',
          },
        ]}
        onRefresh={jest.fn()}
      />
    </I18nProvider>,
  );
}

describe('TEMPanel', () => {
  beforeEach(() => {
    mockedApi.getLearningStatus.mockResolvedValue({
      feedback_count: 2,
      min_feedback_for_update: 5,
      auto_apply_interval: 10,
      exploration_probability: 0.1,
      current_parameters: {},
      pending_recommendations: [],
    } as any);
    mockedApi.runTemBenchmark.mockResolvedValue({
      timestamp: '2026-04-16T00:00:00Z',
      duration_ms: 10,
      scenarios: [],
      summary: {
        total_scenarios: 1,
        passed: 1,
        failed: 0,
        pass_rate: 1,
      },
    });
    mockedApi.getBackendRouteSupport.mockResolvedValue({
      health: true,
      systemBootstrap: true,
      runtimeProviders: true,
      runtimeRequests: true,
      temBenchmark: true,
      temDecisions: true,
      memoryPlane: true,
      memoryPlaneTraces: true,
      memoryPlaneLedger: true,
      memoryPlaneEvaluate: true,
      memoryPlaneEvaluateBatch: true,
      memoryPlaneAutonomousTrajectory: true,
      memoryPlaneRollback: true,
    });
    mockedApi.getMemoryPlaneTraces.mockResolvedValue({ ok: true, trace_path: '', count: 0, items: [] } as any);
    mockedApi.getMemoryPlaneLedger.mockResolvedValue({
      ok: true,
      governance_events: [],
      causal_events: [],
      shadow_replay_events: [],
      rollback_events: [],
    } as any);
    mockedApi.getTemDecisions.mockResolvedValue({ decision_trace_path: '', decisions: [], count: 0 });
  });

  it('renders learned memory and switches to Memory Evaluation tab', async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(screen.getByText('Tool Execution Memory')).toBeInTheDocument();
    expect(screen.getByText('List directory recipe')).toBeInTheDocument();
    expect(screen.getByText('write_file')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Evaluation' })[0]);

    expect(screen.getByText('Memory Evaluation')).toBeInTheDocument();
    expect(screen.getByText('Internal verification only. Full external benchmark results must be run from experiment scripts.')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedApi.getBackendRouteSupport).toHaveBeenCalled();
    });
  });

  it('runs the built-in TEM benchmark from the memory tab', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole('button', { name: 'Run benchmark' }));

    await waitFor(() => {
      expect(mockedApi.runTemBenchmark).toHaveBeenCalled();
      expect(screen.getByText(/Benchmark report:/)).toBeInTheDocument();
    });
  });
});
