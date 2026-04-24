import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BrainCircuit, CheckCircle2, Layers, Play, RefreshCw, RotateCcw, Search, ShieldAlert, TestTube2, X } from 'lucide-react';
import {
  AutonomousTrajectoryCaseInput,
  AutonomousTrajectoryResult,
  BackendRouteSupport,
  BenchmarkReport,
  MemoryPlaneLedger,
  MemoryPlaneTraceList,
  PolicyEvaluationBatchResult,
  PolicyEvaluationResult,
  RollbackResult,
  TEMStats,
} from '../types';
import {
  evaluateAutonomousTrajectory,
  evaluateMemoryPolicy,
  evaluateMemoryPolicyBatch,
  getBackendRouteSupport,
  getMemoryPlaneLedger,
  getMemoryPlaneTraces,
  getTemDecisions,
  rollbackMemoryGovernance,
  runTemBenchmark,
} from '../services/api';
import AppModal from './common/AppModal';
import NoticeBanner from './common/NoticeBanner';
import { useI18n } from '../i18n/I18nProvider';

export interface MemoryEvaluationContentProps {
  clientId: string;
  temStats: TEMStats | null;
  onRefreshTEM: () => void;
}

interface ResearchModePanelProps extends MemoryEvaluationContentProps {
  isOpen: boolean;
  onClose: () => void;
}

type SupportKey = keyof BackendRouteSupport;

const panelCard = 'rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900/70';
const inputClass = 'w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-100';
const tableHeaderClass = 'px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400';
const tableCellClass = 'px-3 py-2 text-sm text-slate-700 dark:text-slate-300';

const researchRouteCatalog: Array<{ key: SupportKey; label: string; path: string; critical?: boolean }> = [
  { key: 'temBenchmark', label: 'TEM benchmark', path: '/api/tem/benchmark', critical: true },
  { key: 'temDecisions', label: 'TEM decisions', path: '/api/tem/decisions' },
  { key: 'memoryPlaneTraces', label: 'Trace log', path: '/api/memory-plane/traces', critical: true },
  { key: 'memoryPlaneLedger', label: 'Ledger', path: '/api/memory-plane/ledger', critical: true },
  { key: 'memoryPlaneEvaluate', label: 'Policy evaluate', path: '/api/memory-plane/evaluate', critical: true },
  { key: 'memoryPlaneEvaluateBatch', label: 'Batch policy evaluation', path: '/api/memory-plane/evaluate_batch', critical: true },
  { key: 'memoryPlaneRollback', label: 'Rollback', path: '/api/memory-plane/rollback', critical: true },
];

const routeMissingTraceList: MemoryPlaneTraceList = {
  ok: false,
  availability: 'route_missing',
  reason: 'backend_route_missing',
  trace_path: '',
  count: 0,
  items: [],
};
const routeMissingLedger: MemoryPlaneLedger = {
  ok: false,
  availability: 'route_missing',
  reason: 'backend_route_missing',
  governance_events: [],
  causal_events: [],
  shadow_replay_events: [],
  rollback_events: [],
};
const sampleBatchInput = JSON.stringify([
  {
    id: 'filesystem_safe_listing',
    query: 'List files in the workspace safely without modifying anything.',
    expected_tool: 'list_directory',
    candidate_tools: ['list_directory', 'read_file', 'write_file'],
  },
  {
    id: 'fetch_web_page',
    query: 'Fetch a public web page for inspection.',
    expected_tool: 'fetch',
    candidate_tools: ['fetch', 'read_file', 'search_files'],
  },
], null, 2);

const sampleAutonomousInput = JSON.stringify([
  {
    id: 'filesystem_write_verify_demo',
    task: 'Create a small demo note under artifacts/runtime_eval, then read it back to verify the content.',
    category: 'filesystem_writeback',
    difficulty: 'medium',
    expected_success: true,
    tools_available: ['create_directory', 'write_file', 'read_text_file'],
    memory_focus: ['recipe_reuse', 'tool_effect_verification'],
    steps: [
      {
        tool: 'create_directory',
        server: 'filesystem',
        arguments: { path: 'D:\\mirror_mcp\\artifacts\\runtime_eval' },
        should_succeed: true,
      },
      {
        tool: 'write_file',
        server: 'filesystem',
        arguments: {
          path: 'D:\\mirror_mcp\\artifacts\\runtime_eval\\phase9_demo.txt',
          content: 'phase9 autonomous trajectory verification\\nmetric: actual_case_success_rate',
        },
        should_succeed: true,
        expect_contains: ['phase9_demo.txt'],
      },
      {
        tool: 'read_text_file',
        server: 'filesystem',
        arguments: { path: 'D:\\mirror_mcp\\artifacts\\runtime_eval\\phase9_demo.txt' },
        should_succeed: true,
        expect_contains: ['phase9 autonomous trajectory verification', 'actual_case_success_rate'],
      },
    ],
  },
  {
    id: 'memory_link_verify_demo',
    task: 'Store a file pointer in memory and then search for it before reading the file.',
    category: 'memory_chain_grounding',
    difficulty: 'hard',
    expected_success: true,
    tools_available: ['create_entities', 'search_nodes', 'read_text_file'],
    memory_focus: ['cross_tool_linking', 'verification'],
    steps: [
      {
        tool: 'create_entities',
        server: 'memory',
        arguments: {
          entities: [
            {
              name: 'phase9_demo_entity',
              entityType: 'file_ref',
              observations: ['path::D:\\mirror_mcp\\artifacts\\runtime_eval\\phase9_demo.txt'],
            },
          ],
        },
        should_succeed: true,
        expect_contains: ['phase9_demo_entity'],
      },
      {
        tool: 'search_nodes',
        server: 'memory',
        arguments: { query: 'phase9 demo entity' },
        should_succeed: true,
        expect_contains: ['phase9_demo_entity'],
      },
      {
        tool: 'read_text_file',
        server: 'filesystem',
        arguments: { path: 'D:\\mirror_mcp\\artifacts\\runtime_eval\\phase9_demo.txt' },
        should_succeed: true,
        expect_contains: ['phase9 autonomous trajectory verification'],
      },
    ],
  },
], null, 2);

function parseBatchCases(raw: string, clientId: string) {
  const trimmed = raw.trim();
  if (!trimmed) {
    return [];
  }
  try {
    const parsed = JSON.parse(trimmed);
    const rows = Array.isArray(parsed) ? parsed : [parsed];
    return rows
      .filter((row) => row && typeof row === 'object')
      .map((row: any, index: number) => ({
        id: String(row.id || `case_${index}`),
        query: String(row.query || '').trim(),
        expected_tool: row.expected_tool ? String(row.expected_tool).trim() : undefined,
        candidate_tools: Array.isArray(row.candidate_tools)
          ? row.candidate_tools.map((name: unknown) => String(name).trim()).filter(Boolean)
          : [],
        client_id: row.client_id ? String(row.client_id).trim() : `${clientId}_batch_${index}`,
      }))
      .filter((row) => row.query);
  } catch {
    return trimmed
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line, index) => {
        const [query, expectedTool = '', tools = ''] = line.split('|').map((part) => part.trim());
        return {
          id: `line_${index}`,
          query,
          expected_tool: expectedTool || undefined,
          candidate_tools: tools ? tools.split(',').map((name) => name.trim()).filter(Boolean) : [],
          client_id: `${clientId}_batch_${index}`,
        };
      })
      .filter((row) => row.query);
  }
}

function parseAutonomousCases(raw: string, clientId: string): AutonomousTrajectoryCaseInput[] {
  const trimmed = raw.trim();
  if (!trimmed) {
    return [];
  }
  const parsed = JSON.parse(trimmed);
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  return rows
    .filter((row) => row && typeof row === 'object' && Array.isArray((row as any).steps))
    .map((row: any, index: number) => ({
      id: row.id ? String(row.id) : `auto_case_${index}`,
      task: String(row.task || '').trim(),
      category: row.category ? String(row.category) : undefined,
      difficulty: row.difficulty ? String(row.difficulty) : undefined,
      expected_success: row.expected_success !== false,
      candidate_tools: Array.isArray(row.candidate_tools) ? row.candidate_tools.map((item: unknown) => String(item).trim()).filter(Boolean) : [],
      tools_available: Array.isArray(row.tools_available) ? row.tools_available.map((item: unknown) => String(item).trim()).filter(Boolean) : [],
      memory_focus: Array.isArray(row.memory_focus) ? row.memory_focus.map((item: unknown) => String(item).trim()).filter(Boolean) : [],
      client_id: row.client_id ? String(row.client_id) : `${clientId}_autonomous_${index}`,
      steps: (row.steps || [])
        .filter((step: any) => step && typeof step === 'object' && step.tool)
        .map((step: any) => ({
          tool: String(step.tool).trim(),
          server: step.server ? String(step.server).trim() : '',
          arguments: step.arguments && typeof step.arguments === 'object' ? step.arguments : {},
          should_succeed: step.should_succeed !== false,
          error_type: step.error_type ? String(step.error_type) : undefined,
          error_message: step.error_message ? String(step.error_message) : undefined,
          expect_contains: Array.isArray(step.expect_contains) ? step.expect_contains.map((item: unknown) => String(item)) : [],
          expect_not_contains: Array.isArray(step.expect_not_contains) ? step.expect_not_contains.map((item: unknown) => String(item)) : [],
        })),
    }))
    .filter((row) => row.task && row.steps.length > 0);
}

function buildAutonomousModeComparison(resultMap: Record<string, AutonomousTrajectoryResult | null>) {
  const modeOrder = ['baseline', 'recipe_only', 'guard_only', 'full_tem'];
  const rows = modeOrder
    .map((mode) => {
      const result = resultMap[mode];
      if (!result?.summary) {
        return null;
      }
      const summary = result.summary;
      return {
        mode,
        actual_case_success_rate: Number(summary.actual_case_success_rate || 0),
        expectation_match_rate: Number(summary.expectation_match_rate || 0),
        route_top1_accuracy: Number(summary.route_top1_accuracy || 0),
        wasted_call_rate: Number(summary.wasted_call_rate || 0),
        state_reuse_rate: Number(summary.argument_policy?.state_reuse_rate || 0),
        fallback_rate: Number(summary.argument_policy?.fallback_rate || 0),
        unsupported_rate: Number(summary.argument_policy?.unsupported_rate || 0),
      };
    })
    .filter(Boolean) as Array<Record<string, number | string>>;
  const baseline = rows.find((row) => row.mode === 'baseline');
  const deltas = baseline
    ? rows
        .filter((row) => row.mode !== 'baseline')
        .map((row) => ({
          mode: row.mode,
          actual_case_success_rate: Number(row.actual_case_success_rate) - Number(baseline.actual_case_success_rate),
          expectation_match_rate: Number(row.expectation_match_rate) - Number(baseline.expectation_match_rate),
          route_top1_accuracy: Number(row.route_top1_accuracy) - Number(baseline.route_top1_accuracy),
          wasted_call_rate: Number(row.wasted_call_rate) - Number(baseline.wasted_call_rate),
          state_reuse_rate: Number(row.state_reuse_rate) - Number(baseline.state_reuse_rate),
          fallback_rate: Number(row.fallback_rate) - Number(baseline.fallback_rate),
          unsupported_rate: Number(row.unsupported_rate) - Number(baseline.unsupported_rate),
        }))
    : [];
  return { rows, deltas };
}

export const MemoryEvaluationContent: React.FC<MemoryEvaluationContentProps> = ({ clientId, temStats, onRefreshTEM }) => {
  const { language, t } = useI18n();
  const batchUi = useMemo(() => ({
    title: language === 'zh' ? '批量策略评估' : 'Batch policy evaluation',
    desc: language === 'zh'
      ? '真实调用 /api/memory-plane/evaluate_batch。支持 JSON 数组，或每行 query | expected_tool | tool_a,tool_b。'
      : 'Calls the real /api/memory-plane/evaluate_batch endpoint. Accepts a JSON array or one line per case: query | expected_tool | tool_a,tool_b.',
    run: language === 'zh' ? '运行批量评估' : 'Run batch evaluation',
    parsed: language === 'zh' ? '已解析 {count} 条案例' : 'Parsed {count} cases',
    empty: language === 'zh' ? '请先输入至少一个批量案例。' : 'Enter at least one batch case first.',
    missing: language === 'zh'
      ? '当前后端进程没有暴露 /api/memory-plane/evaluate_batch。请先重启后端。'
      : 'The current backend process does not expose /api/memory-plane/evaluate_batch. Restart the backend first.',
    cases: language === 'zh' ? '案例' : 'Cases',
    expected: language === 'zh' ? '期望' : 'Expected',
    predicted: language === 'zh' ? '推荐' : 'Predicted',
    match: language === 'zh' ? '命中' : 'Match',
    meanScore: language === 'zh' ? '平均分' : 'Mean score',
    featureTable: language === 'zh' ? '特征消融收益表' : 'Feature ablation gain',
    calibration: language === 'zh' ? '校准表' : 'Calibration table',
    meanValue: language === 'zh' ? '均值' : 'Mean value',
    empirical: language === 'zh' ? '经验命中率' : 'Empirical accuracy',
    gap: language === 'zh' ? '误差' : 'Gap',
    maskedTop1: language === 'zh' ? '屏蔽后Top1' : 'Masked Top1',
    top1Gain: language === 'zh' ? 'Top1增益' : 'Top1 gain',
    flipRate: language === 'zh' ? '翻转率' : 'Flip rate',
  }), [language]);

  const autonomousUi = useMemo(() => ({
    routeLabel: language === 'zh' ? '\u81ea\u4e3b\u8f68\u8ff9' : 'Autonomous trajectory',
    title: language === 'zh' ? '\u81ea\u4e3b\u8f68\u8ff9\u8bc4\u4f30' : 'Autonomous trajectory evaluation',
    desc: language === 'zh'
      ? '\u771f\u5b9e\u8c03\u7528 /api/memory-plane/autonomous_trajectory\uff0c\u5e76\u5728 baseline\u3001recipe_only\u3001guard_only \u548c full_tem \u56db\u79cd\u6a21\u5f0f\u4e0b\u6267\u884c\u3002\u5b83\u4f1a\u8fd0\u884c\u771f\u5b9e MCP \u5de5\u5177\uff0c\u6bd4\u5355\u6b65\u63a8\u8350\u8bc4\u4f30\u66f4\u4e25\u683c\u3002'
      : 'Runs the real /api/memory-plane/autonomous_trajectory endpoint across baseline, recipe_only, guard_only, and full_tem. This executes real MCP tools and is stronger than first-step recommendation checks.',
    routeMissing: language === 'zh'
      ? '\u5f53\u524d\u540e\u7aef\u8fdb\u7a0b\u6ca1\u6709\u66b4\u9732 /api/memory-plane/autonomous_trajectory\u3002\u8bf7\u5148\u91cd\u542f\u540e\u7aef\u3002'
      : 'The current backend process does not expose /api/memory-plane/autonomous_trajectory. Restart the backend first.',
    empty: language === 'zh' ? '\u8bf7\u5148\u8f93\u5165\u81f3\u5c11\u4e00\u4e2a\u81ea\u4e3b\u8f68\u8ff9\u6848\u4f8b\u3002' : 'Enter at least one autonomous trajectory case first.',
    completed: language === 'zh'
      ? '\u5df2\u5728 4 \u79cd TEM \u6a21\u5f0f\u4e0b\u5b8c\u6210 {count} \u6761\u81ea\u4e3b\u8f68\u8ff9\u6848\u4f8b\u3002'
      : 'Autonomous trajectory completed for {count} cases across 4 TEM modes.',
    run: language === 'zh' ? '\u8fd0\u884c\u81ea\u4e3b\u8f68\u8ff9\u8bc4\u4f30' : 'Run autonomous trajectory',
    executeSelectedTool: language === 'zh' ? '\u6267\u884c\u9009\u4e2d\u7684\u5de5\u5177' : 'Execute selected tool',
    parsed: language === 'zh'
      ? '\u5df2\u89e3\u6790 {count} \u6761\u81ea\u4e3b\u8f68\u8ff9\u6848\u4f8b\u3002\u771f\u5b9e\u6267\u884c\u53ef\u80fd\u4f1a\u5728\u6848\u4f8b\u6307\u5b9a\u8def\u5f84\u4e0b\u521b\u5efa\u6216\u66f4\u65b0\u6587\u4ef6\u3002'
      : 'Parsed {count} autonomous cases. Real execution can create or update files under the paths used in the cases.',
    success: language === 'zh' ? '\u6210\u529f' : 'Success',
    route: language === 'zh' ? '\u8def\u7531' : 'Route',
    wasted: language === 'zh' ? '\u6d6a\u8d39\u8c03\u7528' : 'Wasted',
    mode: language === 'zh' ? '\u6a21\u5f0f' : 'Mode',
    expectation: language === 'zh' ? '\u671f\u671b\u4e00\u81f4' : 'Expectation',
    routeTop1: language === 'zh' ? '\u8def\u7531 Top1' : 'Route Top1',
    stateReuse: language === 'zh' ? '\u72b6\u6001\u590d\u7528' : 'State reuse',
    fallback: language === 'zh' ? '\u56de\u9000' : 'Fallback',
    unsupported: language === 'zh' ? '\u4e0d\u652f\u6301' : 'Unsupported',
    deltaSuccess: language === 'zh' ? '\u0394 \u6210\u529f' : '\u0394 Success',
    deltaExpectation: language === 'zh' ? '\u0394 \u671f\u671b\u4e00\u81f4' : '\u0394 Expectation',
    deltaRouteTop1: language === 'zh' ? '\u0394 \u8def\u7531 Top1' : '\u0394 Route Top1',
    deltaWasted: language === 'zh' ? '\u0394 \u6d6a\u8d39\u8c03\u7528' : '\u0394 Wasted',
    deltaStateReuse: language === 'zh' ? '\u0394 \u72b6\u6001\u590d\u7528' : '\u0394 State reuse',
    deltaFallback: language === 'zh' ? '\u0394 \u56de\u9000' : '\u0394 Fallback',
    deltaUnsupported: language === 'zh' ? '\u0394 \u4e0d\u652f\u6301' : '\u0394 Unsupported',
    policySteps: language === 'zh' ? '\u7b56\u7565\u6b65\u6570' : 'Policy steps',
    schema: language === 'zh' ? '\u6a21\u5f0f\u5339\u914d' : 'Schema',
    exact: language === 'zh' ? '\u7cbe\u786e\u5339\u914d' : 'Exact',
    memoryConditioned: language === 'zh' ? '\u8bb0\u5fc6\u6761\u4ef6\u5316' : 'Memory-conditioned',
    category: language === 'zh' ? '\u7c7b\u522b' : 'Category',
    cases: language === 'zh' ? '\u6848\u4f8b\u6570' : 'Cases',
    step: language === 'zh' ? '\u6b65\u9aa4' : 'Step',
    supported: language === 'zh' ? '\u652f\u6301\u7387' : 'Supported',
    verified: language === 'zh' ? '\u9a8c\u8bc1\u7387' : 'Verified',
  }), [language]);

  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null);
  const [policyQuery, setPolicyQuery] = useState(t('memoryEvaluation.queryDefault'));
  const [expectedTool, setExpectedTool] = useState('');
  const [policyResult, setPolicyResult] = useState<PolicyEvaluationResult | null>(null);
  const [batchInput, setBatchInput] = useState(sampleBatchInput);
  const [batchResult, setBatchResult] = useState<PolicyEvaluationBatchResult | null>(null);
  const [autonomousInput, setAutonomousInput] = useState(sampleAutonomousInput);
  const [autonomousArgumentPolicyMode, setAutonomousArgumentPolicyMode] = useState('memory_conditioned_with_fallback');
  const [autonomousExecuteSelectedTool, setAutonomousExecuteSelectedTool] = useState(true);
  const [autonomousMaxSteps, setAutonomousMaxSteps] = useState(6);
  const [autonomousResults, setAutonomousResults] = useState<Record<string, AutonomousTrajectoryResult | null>>({
    baseline: null,
    recipe_only: null,
    guard_only: null,
    full_tem: null,
  });
  const [traces, setTraces] = useState<MemoryPlaneTraceList | null>(null);
  const [ledger, setLedger] = useState<MemoryPlaneLedger | null>(null);
  const [decisions, setDecisions] = useState<Array<Record<string, any>>>([]);
  const [rollbackResult, setRollbackResult] = useState<RollbackResult | null>(null);

  const downloadJson = (filename: string, payload: unknown) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const [routeSupport, setRouteSupport] = useState<BackendRouteSupport | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'info' | 'success' | 'warning' | 'error'; message: string } | null>(null);

  const parsedBatchCases = useMemo(() => parseBatchCases(batchInput, clientId), [batchInput, clientId]);
  const parsedAutonomousCases = useMemo(() => {
    try {
      return parseAutonomousCases(autonomousInput, clientId);
    } catch {
      return [];
    }
  }, [autonomousInput, clientId]);

  const refreshResearchData = useCallback(async () => {
    setLoadingKey('refresh');
    setNotice(null);
    try {
      const support = await getBackendRouteSupport();
      setRouteSupport(support);
      const missingPaths = researchRouteCatalog.filter((item) => item.critical && !support[item.key]).map((item) => item.path);
      const [traceData, ledgerData, decisionData] = await Promise.all([
        support.memoryPlaneTraces ? getMemoryPlaneTraces(30) : Promise.resolve(routeMissingTraceList),
        support.memoryPlaneLedger ? getMemoryPlaneLedger(30) : Promise.resolve(routeMissingLedger),
        support.temDecisions ? getTemDecisions(30) : Promise.resolve({ decision_trace_path: '', decisions: [], count: 0 }),
      ]);
      setTraces(traceData);
      setLedger(ledgerData);
      setDecisions(decisionData.decisions || []);
      onRefreshTEM();
      if (missingPaths.length > 0) {
        setNotice({ tone: 'warning', message: t('memoryEvaluation.currentBackendMissing', { routes: missingPaths.join(', ') }) });
      }
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  }, [onRefreshTEM, t]);

  useEffect(() => {
    void refreshResearchData();
  }, [refreshResearchData]);
  const runBenchmark = async () => {
    if (routeSupport && !routeSupport.temBenchmark) {
      setNotice({ tone: 'warning', message: t('memoryEvaluation.benchmarkMissing') });
      return;
    }
    setLoadingKey('benchmark');
    setNotice(null);
    try {
      const data = await runTemBenchmark();
      setBenchmark(data);
      setNotice({ tone: 'success', message: `${t('memoryEvaluation.runBenchmark')}: ${data.summary.passed}/${data.summary.total_scenarios}` });
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  };

  const runPolicyEvaluation = async () => {
    if (!policyQuery.trim()) {
      setNotice({ tone: 'warning', message: t('memoryEvaluation.enterQuery') });
      return;
    }
    if (routeSupport && !routeSupport.memoryPlaneEvaluate) {
      setNotice({ tone: 'warning', message: t('memoryEvaluation.evaluateMissing') });
      return;
    }
    setLoadingKey('policy');
    setNotice(null);
    try {
      const result = await evaluateMemoryPolicy({
        query: policyQuery.trim(),
        client_id: clientId,
        expected_tool: expectedTool.trim() || undefined,
      });
      if (!result || typeof result.candidate_count !== 'number') {
        throw new Error(t('memoryEvaluation.policyEmpty'));
      }
      setPolicyResult(result);
      setNotice({ tone: 'success', message: t('memoryEvaluation.policyCandidates', { count: result.candidate_count }) });
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  };

  const runBatchPolicyEvaluation = async () => {
    if (routeSupport && !routeSupport.memoryPlaneEvaluateBatch) {
      setNotice({ tone: 'warning', message: batchUi.missing });
      return;
    }
    if (parsedBatchCases.length === 0) {
      setNotice({ tone: 'warning', message: batchUi.empty });
      return;
    }
    setLoadingKey('batch');
    setNotice(null);
    try {
      const result = await evaluateMemoryPolicyBatch({ cases: parsedBatchCases, dry_run: true });
      setBatchResult(result);
      setNotice({ tone: 'success', message: `${batchUi.title}: ${result.summary.total} cases, Top1 ${(result.summary.top1_accuracy * 100).toFixed(1)}%` });
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  };

  const runRollback = async () => {
    if (routeSupport && !routeSupport.memoryPlaneRollback) {
      setNotice({ tone: 'warning', message: t('memoryEvaluation.rollbackMissing') });
      return;
    }
    setLoadingKey('rollback');
    setNotice(null);
    try {
      const result = await rollbackMemoryGovernance('frontend_memory_evaluation_recovery_check');
      setRollbackResult(result);
      setNotice({ tone: 'success', message: t('memoryEvaluation.rollbackCompleted') });
      await refreshResearchData();
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  };

  const traceSummary = useMemo(() => {
    const latestTrace = traces?.items?.[traces.items.length - 1];
    return {
      traceCount: traces?.count || 0,
      latestPhase:
        latestTrace?.phase
        || latestTrace?.memory_plane?.phase
        || (traces?.availability === 'route_missing' ? 'route_missing' : 'n/a'),
      governance: ledger?.governance_events.length || 0,
      causal: ledger?.causal_events.length || 0,
      shadow: ledger?.shadow_replay_events.length || 0,
      rollback: ledger?.rollback_events.length || 0,
    };
  }, [ledger, traces]);

  const supportedRouteCount = useMemo(() => {
    if (!routeSupport) {
      return 0;
    }
    return researchRouteCatalog.filter((item) => routeSupport[item.key]).length;
  }, [routeSupport]);

  const localizedRouteCatalog = useMemo(() => {
    const labelMap: Record<SupportKey, string> = {
      health: t('health.title'),
      systemBootstrap: 'Bootstrap',
      runtimeProviders: 'Runtime providers',
      runtimeRequests: 'Runtime requests',
      mcpToolOnboardingAudit: 'Tool onboarding audit',
      temBenchmark: t('memoryEvaluation.benchmark'),
      temDecisions: 'TEM decisions',
      memoryPlane: 'Memory Plane snapshot',
      memoryPlaneTraces: 'Trace log',
      memoryPlaneLedger: t('memoryEvaluation.ledger'),
      memoryPlaneEvaluate: t('memoryEvaluation.policyEvaluation'),
      memoryPlaneEvaluateBatch: batchUi.title,
      memoryPlaneAutonomousTrajectory: autonomousUi.routeLabel,
      memoryPlaneRollback: t('memoryEvaluation.rollback'),
    };
    return researchRouteCatalog.map((item) => ({ ...item, label: labelMap[item.key] || item.label }));
  }, [autonomousUi.routeLabel, batchUi.title, t]);

  const topFeatureRows = useMemo(() => (
    Object.entries(batchResult?.per_feature || {})
      .sort((left, right) => Number(right[1].top1_gain || 0) - Number(left[1].top1_gain || 0))
      .slice(0, 8)
  ), [batchResult]);

  const autonomousModeComparison = useMemo(
    () => buildAutonomousModeComparison(autonomousResults),
    [autonomousResults],
  );

  const runAutonomousTrajectory = async () => {
    if (routeSupport && !routeSupport.memoryPlaneAutonomousTrajectory) {
      setNotice({ tone: 'warning', message: autonomousUi.routeMissing });
      return;
    }
    let cases: AutonomousTrajectoryCaseInput[];
    try {
      cases = parseAutonomousCases(autonomousInput, clientId);
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
      return;
    }
    if (cases.length === 0) {
      setNotice({ tone: 'warning', message: autonomousUi.empty });
      return;
    }
    setLoadingKey('autonomous');
    setNotice(null);
    try {
      const modes: Array<'baseline' | 'recipe_only' | 'guard_only' | 'full_tem'> = ['baseline', 'recipe_only', 'guard_only', 'full_tem'];
      const entries = await Promise.all(
        modes.map(async (mode) => {
          const result = await evaluateAutonomousTrajectory({
            cases,
            tem_mode: mode,
            reset_tem_before_run: false,
            max_steps_per_case: autonomousMaxSteps,
            execute_selected_tool: autonomousExecuteSelectedTool,
            argument_policy_mode: autonomousArgumentPolicyMode,
            stop_on_misroute: false,
            stop_on_failure: false,
            restore_state_after_run: true,
            feature_mask: {},
          });
          return [mode, result] as const;
        }),
      );
      const nextResults: Record<string, AutonomousTrajectoryResult | null> = {
        baseline: null,
        recipe_only: null,
        guard_only: null,
        full_tem: null,
      };
      entries.forEach(([mode, result]) => {
        nextResults[mode] = result;
      });
      setAutonomousResults(nextResults);
      setNotice({ tone: 'success', message: autonomousUi.completed.replace('{count}', String(cases.length)) });
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoadingKey(null);
    }
  };

  return (
    <div className="space-y-5">
      {notice && <NoticeBanner tone={notice.tone} message={notice.message} onClose={() => setNotice(null)} />}

      <div className="grid gap-4 md:grid-cols-4">
        <div className={panelCard}>
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('memoryEvaluation.temArtifacts')}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{temStats?.total_recipes || 0}/{temStats?.total_guards || 0}</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.recipesGuards')}</div>
        </div>
        <div className={panelCard}>
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('memoryEvaluation.traces')}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{traceSummary.traceCount}</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.latestPhase')} {traceSummary.latestPhase}</div>
        </div>
        <div className={panelCard}>
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('memoryEvaluation.causalShadow')}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{traceSummary.causal}/{traceSummary.shadow}</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.ledgerEvents')}</div>
        </div>
        <div className={panelCard}>
          <div className="text-xs uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('memoryEvaluation.rollback')}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{traceSummary.rollback}</div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.recoveryEvents')}</div>
        </div>
      </div>

      <section className={panelCard}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.whatIs')}</div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('memoryEvaluation.whatIsDesc')}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-950/40">
            <div className="font-semibold text-slate-900 dark:text-white">
              {t('memoryEvaluation.routeSupport')} {routeSupport ? `${supportedRouteCount}/${localizedRouteCatalog.length}` : t('health.loading')}
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.routeSupportHint')}</div>
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-3 text-sm text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/20 dark:text-sky-100">
          <span className="font-semibold">{t('memoryEvaluation.internalOnly')}</span>{' '}
          {t('memoryEvaluation.internalOnlyDesc')}
        </div>

        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {localizedRouteCatalog.map((item) => {
            const supported = routeSupport ? routeSupport[item.key] : false;
            return (
              <div key={item.path} className={`rounded-2xl border px-3 py-3 text-sm ${supported ? 'border-emerald-200 bg-emerald-50/80 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200' : 'border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200'}`}>
                <div className="font-medium">{item.label}</div>
                <div className="mt-1 font-mono text-xs opacity-80">{item.path}</div>
                <div className="mt-2 text-xs">{supported ? t('memoryEvaluation.routeRegistered') : t('memoryEvaluation.routeMissingState')}</div>
              </div>
            );
          })}
        </div>
      </section>
      <section className={panelCard}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <TestTube2 className="h-4 w-4 text-indigo-500" />
              <span>{t('memoryEvaluation.benchmark')}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('memoryEvaluation.benchmarkDesc')}</p>
          </div>
          <button
            type="button"
            onClick={runBenchmark}
            disabled={loadingKey === 'benchmark' || Boolean(routeSupport && !routeSupport.temBenchmark)}
            className="inline-flex items-center gap-2 rounded-2xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingKey === 'benchmark' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
            <span>{loadingKey === 'benchmark' ? t('memoryEvaluation.running') : t('memoryEvaluation.runBenchmark')}</span>
          </button>
        </div>
        {benchmark && (
          <div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/70 p-4 text-sm dark:border-indigo-900/40 dark:bg-indigo-950/20">
            <div className="flex items-center justify-between gap-3">
              <div className="font-semibold text-indigo-800 dark:text-indigo-200">
                {t('memoryEvaluation.passRate')} {(benchmark.summary.pass_rate * 100).toFixed(1)}% ({benchmark.summary.passed}/{benchmark.summary.total_scenarios})
              </div>
              <button
                type="button"
                onClick={() => downloadJson('memory-evaluation-benchmark.json', benchmark)}
                className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-50 dark:border-indigo-800 dark:bg-slate-900/50 dark:text-indigo-300"
              >
                {t('common.save')}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className={panelCard}>
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
          <BrainCircuit className="h-4 w-4 text-sky-500" />
          <span>{t('memoryEvaluation.policyEvaluation')}</span>
        </div>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('memoryEvaluation.policyEvaluationDesc')}</p>
        <div className="mt-4 grid gap-3 lg:grid-cols-[1fr,260px,auto]">
          <input className={inputClass} value={policyQuery} onChange={(event) => setPolicyQuery(event.target.value)} />
          <input className={inputClass} value={expectedTool} onChange={(event) => setExpectedTool(event.target.value)} placeholder={t('memoryEvaluation.expectedTool')} />
          <button
            type="button"
            onClick={runPolicyEvaluation}
            disabled={loadingKey === 'policy' || Boolean(routeSupport && !routeSupport.memoryPlaneEvaluate)}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
          >
            {loadingKey === 'policy' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            <span>{t('memoryEvaluation.evaluate')}</span>
          </button>
        </div>
        {policyResult && (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-slate-700 dark:bg-slate-950/40">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.routerResult')}</div>
                <button
                  type="button"
                  onClick={() => downloadJson('memory-policy-evaluation.json', policyResult)}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
                >
                  {t('common.save')}
                </button>
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                <div>{t('memoryEvaluation.router')}: {policyResult.router_type}</div>
                <div>{t('memoryEvaluation.intent')}: {policyResult.intent_signature || t('memoryEvaluation.decisionFallback')}</div>
                <div>{t('memoryEvaluation.candidateCount')}: {policyResult.candidate_count}</div>
                <div>{t('memoryEvaluation.topScore')}: {Number(policyResult.top_score || 0).toFixed(3)}</div>
                {policyResult.expected_tool && <div>{t('memoryEvaluation.top1Match')}: {policyResult.top1_match ? t('memoryEvaluation.yes') : t('memoryEvaluation.no')}</div>}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50/90 p-4 dark:border-slate-700 dark:bg-slate-950/40">
              <div className="text-sm font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.topCandidates')}</div>
              <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                {policyResult.routing_scores.slice(0, 5).map((score) => (
                  <div key={String(score.tool_name)} className="rounded-xl bg-white/80 px-3 py-2 dark:bg-slate-900/70">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-slate-900 dark:text-white">{String(score.tool_name)}</span>
                      <span className="font-mono">{Number(score.final_score || score.score || 0).toFixed(3)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className={panelCard}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Layers className="h-4 w-4 text-violet-500" />
              <span>{autonomousUi.title}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {autonomousUi.desc}
            </p>
          </div>
          <button
            type="button"
            onClick={runAutonomousTrajectory}
            disabled={loadingKey === 'autonomous' || Boolean(routeSupport && !routeSupport.memoryPlaneAutonomousTrajectory)}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingKey === 'autonomous' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            <span>{loadingKey === 'autonomous' ? t('memoryEvaluation.running') : autonomousUi.run}</span>
          </button>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[220px,220px,220px]">
          <select
            className={inputClass}
            value={autonomousArgumentPolicyMode}
            onChange={(event) => setAutonomousArgumentPolicyMode(event.target.value)}
          >
            <option value="gold">gold</option>
            <option value="controlled">controlled</option>
            <option value="controlled_with_fallback">controlled_with_fallback</option>
            <option value="memory_conditioned">memory_conditioned</option>
            <option value="memory_conditioned_with_fallback">memory_conditioned_with_fallback</option>
          </select>
          <input
            className={inputClass}
            type="number"
            min={1}
            max={12}
            value={autonomousMaxSteps}
            onChange={(event) => setAutonomousMaxSteps(Number(event.target.value) || 1)}
          />
          <label className="flex items-center gap-3 rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200">
            <input
              type="checkbox"
              checked={autonomousExecuteSelectedTool}
              onChange={(event) => setAutonomousExecuteSelectedTool(event.target.checked)}
            />
            <span>{autonomousUi.executeSelectedTool}</span>
          </label>
        </div>

        <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {autonomousUi.parsed.replace('{count}', String(parsedAutonomousCases.length))}
        </div>

        <textarea
          className={`${inputClass} mt-4 min-h-[240px] font-mono text-xs`}
          value={autonomousInput}
          onChange={(event) => setAutonomousInput(event.target.value)}
        />

        {autonomousModeComparison.rows.length > 0 && (
          <div className="mt-5 space-y-4">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => downloadJson('autonomous-trajectory-results.json', autonomousResults)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
              >
                {t('common.save')}
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              {autonomousModeComparison.rows.map((row) => (
                <div key={String(row.mode)} className="rounded-2xl border border-violet-100 bg-violet-50/70 p-4 dark:border-violet-900/40 dark:bg-violet-950/20">
                  <div className="text-xs uppercase tracking-[0.18em] text-violet-700 dark:text-violet-200">{String(row.mode)}</div>
                  <div className="mt-2 text-sm text-slate-700 dark:text-slate-300">
                    {autonomousUi.success} {(Number(row.actual_case_success_rate) * 100).toFixed(1)}%
                  </div>
                  <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                    {autonomousUi.route} {(Number(row.route_top1_accuracy) * 100).toFixed(1)}%
                  </div>
                  <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                    {autonomousUi.wasted} {(Number(row.wasted_call_rate) * 100).toFixed(1)}%
                  </div>
                </div>
              ))}
            </div>

            <div className="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
              <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                <thead className="bg-slate-50 dark:bg-slate-950/50">
                  <tr>
                    <th className={tableHeaderClass}>{autonomousUi.mode}</th>
                    <th className={tableHeaderClass}>{autonomousUi.success}</th>
                    <th className={tableHeaderClass}>{autonomousUi.expectation}</th>
                    <th className={tableHeaderClass}>{autonomousUi.routeTop1}</th>
                    <th className={tableHeaderClass}>{autonomousUi.wasted}</th>
                    <th className={tableHeaderClass}>{autonomousUi.stateReuse}</th>
                    <th className={tableHeaderClass}>{autonomousUi.fallback}</th>
                    <th className={tableHeaderClass}>{autonomousUi.unsupported}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white/80 dark:divide-slate-800 dark:bg-slate-900/50">
                  {autonomousModeComparison.rows.map((row) => (
                    <tr key={String(row.mode)}>
                      <td className={tableCellClass}>{String(row.mode)}</td>
                      <td className={tableCellClass}>{(Number(row.actual_case_success_rate) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.expectation_match_rate) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.route_top1_accuracy) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.wasted_call_rate) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.state_reuse_rate) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.fallback_rate) * 100).toFixed(1)}%</td>
                      <td className={tableCellClass}>{(Number(row.unsupported_rate) * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {autonomousModeComparison.deltas.length > 0 && (
              <div className="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
                <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                  <thead className="bg-slate-50 dark:bg-slate-950/50">
                    <tr>
                      <th className={tableHeaderClass}>{autonomousUi.mode}</th>
                      <th className={tableHeaderClass}>Δ Success</th>
                      <th className={tableHeaderClass}>Δ Expectation</th>
                      <th className={tableHeaderClass}>Δ Route Top1</th>
                      <th className={tableHeaderClass}>Δ Wasted</th>
                      <th className={tableHeaderClass}>Δ State reuse</th>
                      <th className={tableHeaderClass}>Δ Fallback</th>
                      <th className={tableHeaderClass}>Δ Unsupported</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white/80 dark:divide-slate-800 dark:bg-slate-900/50">
                    {autonomousModeComparison.deltas.map((row) => (
                      <tr key={String(row.mode)}>
                        <td className={tableCellClass}>{String(row.mode)}</td>
                        <td className={tableCellClass}>{(Number(row.actual_case_success_rate) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.expectation_match_rate) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.route_top1_accuracy) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.wasted_call_rate) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.state_reuse_rate) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.fallback_rate) * 100).toFixed(1)} pts</td>
                        <td className={tableCellClass}>{(Number(row.unsupported_rate) * 100).toFixed(1)} pts</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="grid gap-4 xl:grid-cols-2">
              {Object.entries(autonomousResults).map(([mode, result]) => {
                if (!result) {
                  return null;
                }
                const categoryRows = Object.entries(result.summary.per_category || {}).slice(0, 8);
                const stepRows = Object.entries(result.summary.per_step || {}).sort((a, b) => Number(a[0]) - Number(b[0])).slice(0, 8);
                return (
                  <div key={mode} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                    <div className="text-sm font-semibold text-slate-900 dark:text-white">{mode}</div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
                        {autonomousUi.policySteps} {result.summary.argument_policy.policy_steps}
                      </div>
                      <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
                        {autonomousUi.schema} {(result.summary.argument_policy.schema_match_rate * 100).toFixed(1)}%
                      </div>
                      <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
                        {autonomousUi.exact} {(result.summary.argument_policy.exact_match_rate * 100).toFixed(1)}%
                      </div>
                      <div className="rounded-xl bg-white/80 px-3 py-2 text-xs text-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
                        {autonomousUi.memoryConditioned} {(result.summary.argument_policy.memory_conditioned_step_share * 100).toFixed(1)}%
                      </div>
                    </div>

                    <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
                      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                        <thead className="bg-slate-50 dark:bg-slate-950/50">
                          <tr>
                            <th className={tableHeaderClass}>{autonomousUi.category}</th>
                            <th className={tableHeaderClass}>{autonomousUi.cases}</th>
                            <th className={tableHeaderClass}>{autonomousUi.success}</th>
                            <th className={tableHeaderClass}>{autonomousUi.fallback}</th>
                            <th className={tableHeaderClass}>{autonomousUi.stateReuse}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 bg-white/80 dark:divide-slate-800 dark:bg-slate-900/50">
                          {categoryRows.map(([category, metrics]) => (
                            <tr key={`${mode}_${category}`}>
                              <td className={tableCellClass}>{category}</td>
                              <td className={tableCellClass}>{metrics.cases}</td>
                              <td className={tableCellClass}>{(metrics.actual_case_success_rate * 100).toFixed(1)}%</td>
                              <td className={tableCellClass}>{(metrics.fallback_rate * 100).toFixed(1)}%</td>
                              <td className={tableCellClass}>{(metrics.state_reuse_rate * 100).toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
                      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                        <thead className="bg-slate-50 dark:bg-slate-950/50">
                          <tr>
                            <th className={tableHeaderClass}>{autonomousUi.step}</th>
                            <th className={tableHeaderClass}>{autonomousUi.supported}</th>
                            <th className={tableHeaderClass}>{autonomousUi.fallback}</th>
                            <th className={tableHeaderClass}>{autonomousUi.stateReuse}</th>
                            <th className={tableHeaderClass}>{autonomousUi.verified}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 bg-white/80 dark:divide-slate-800 dark:bg-slate-900/50">
                          {stepRows.map(([stepIndex, metrics]) => (
                            <tr key={`${mode}_step_${stepIndex}`}>
                              <td className={tableCellClass}>{stepIndex}</td>
                              <td className={tableCellClass}>{(metrics.supported_rate * 100).toFixed(1)}%</td>
                              <td className={tableCellClass}>{(metrics.fallback_rate * 100).toFixed(1)}%</td>
                              <td className={tableCellClass}>{(metrics.state_reuse_rate * 100).toFixed(1)}%</td>
                              <td className={tableCellClass}>{(metrics.verified_rate * 100).toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      <section className={panelCard}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Layers className="h-4 w-4 text-cyan-500" />
              <span>{batchUi.title}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{batchUi.desc}</p>
          </div>
          <button
            type="button"
            onClick={runBatchPolicyEvaluation}
            disabled={loadingKey === 'batch' || Boolean(routeSupport && !routeSupport.memoryPlaneEvaluateBatch)}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingKey === 'batch' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Layers className="h-4 w-4" />}
            <span>{loadingKey === 'batch' ? t('memoryEvaluation.running') : batchUi.run}</span>
          </button>
        </div>
        <textarea
          className={`${inputClass} mt-4 min-h-[170px] font-mono text-xs`}
          value={batchInput}
          onChange={(event) => setBatchInput(event.target.value)}
        />
        <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {batchUi.parsed.replace('{count}', String(parsedBatchCases.length))}
        </div>

        {batchResult && (
          <div className="mt-4 space-y-4">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => downloadJson('memory-policy-batch.json', batchResult)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
              >
                {t('common.save')}
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-2xl border border-cyan-100 bg-cyan-50/70 p-4 dark:border-cyan-900/40 dark:bg-cyan-950/20">
                <div className="text-xs text-cyan-700 dark:text-cyan-200">{batchUi.cases}</div>
                <div className="mt-1 text-2xl font-semibold text-cyan-900 dark:text-cyan-100">{batchResult.summary.total}</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                <div className="text-xs text-slate-500 dark:text-slate-400">Top1</div>
                <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{(batchResult.summary.top1_accuracy * 100).toFixed(1)}%</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                <div className="text-xs text-slate-500 dark:text-slate-400">TopK</div>
                <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{(batchResult.summary.topk_recall * 100).toFixed(1)}%</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                <div className="text-xs text-slate-500 dark:text-slate-400">{batchUi.meanScore}</div>
                <div className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{Number(batchResult.summary.mean_top_score || 0).toFixed(3)}</div>
              </div>
            </div>
            <div className="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
              <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                <thead className="bg-slate-50 dark:bg-slate-950/50">
                  <tr>
                    <th className={tableHeaderClass}>ID</th>
                    <th className={tableHeaderClass}>{batchUi.expected}</th>
                    <th className={tableHeaderClass}>{batchUi.predicted}</th>
                    <th className={tableHeaderClass}>{batchUi.match}</th>
                    <th className={tableHeaderClass}>{batchUi.meanScore}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white/80 dark:divide-slate-800 dark:bg-slate-900/50">
                  {batchResult.cases.slice(0, 8).map((item) => (
                    <tr key={item.id}>
                      <td className={tableCellClass}>{item.id}</td>
                      <td className={tableCellClass}>{item.expected_tool || 'n/a'}</td>
                      <td className={tableCellClass}>{item.recommended_tools?.[0] || 'n/a'}</td>
                      <td className={tableCellClass}>{item.top1_match ? t('memoryEvaluation.yes') : t('memoryEvaluation.no')}</td>
                      <td className={`${tableCellClass} font-mono`}>{Number(item.top_score || 0).toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">{batchUi.featureTable}</div>
                <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                  {topFeatureRows.map(([feature, metrics]) => (
                    <div key={feature} className="grid grid-cols-[1fr,88px,76px,72px] gap-2 rounded-xl bg-white/80 px-3 py-2 dark:bg-slate-900/70">
                      <span className="truncate font-medium text-slate-900 dark:text-white">{feature}</span>
                      <span>{batchUi.maskedTop1}: {(Number(metrics.masked_top1_accuracy || metrics.top1_accuracy || 0) * 100).toFixed(0)}%</span>
                      <span>{batchUi.top1Gain}: {(Number(metrics.top1_gain || 0) * 100).toFixed(0)}%</span>
                      <span>{batchUi.flipRate}: {(Number(metrics.top1_flip_rate || 0) * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
                <div className="text-sm font-semibold text-slate-900 dark:text-white">{batchUi.calibration}</div>
                <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                  {batchResult.calibration.map((bucket) => (
                    <div key={bucket.bucket} className="grid grid-cols-[1fr,78px,72px] gap-2 rounded-xl bg-white/80 px-3 py-2 dark:bg-slate-900/70">
                      <span className="font-mono text-slate-900 dark:text-white">{bucket.bucket}</span>
                      <span>{batchUi.empirical}: {(bucket.empirical_top1_accuracy * 100).toFixed(0)}%</span>
                      <span>{batchUi.gap}: {bucket.gap.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className={panelCard}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <ShieldAlert className="h-4 w-4 text-amber-500" />
              <span>{t('memoryEvaluation.rollbackLedger')}</span>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('memoryEvaluation.rollbackLedgerDesc')}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={refreshResearchData}
              disabled={loadingKey === 'refresh'}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RefreshCw className={`h-4 w-4 ${loadingKey === 'refresh' ? 'animate-spin' : ''}`} />
              <span>{t('memoryEvaluation.refreshTraces')}</span>
            </button>
            <button
              type="button"
              onClick={runRollback}
              disabled={loadingKey === 'rollback' || Boolean(routeSupport && !routeSupport.memoryPlaneRollback)}
              className="inline-flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-800 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200"
            >
              {loadingKey === 'rollback' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              <span>{t('memoryEvaluation.runRollback')}</span>
            </button>
            <button
              type="button"
              onClick={() => downloadJson('memory-evaluation-artifacts.json', { traces, ledger, decisions, rollbackResult })}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950/40 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <span>{t('common.save')}</span>
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <div className="rounded-2xl bg-slate-50 p-4 text-sm dark:bg-slate-950/40">
            <div className="font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.recentDecisions')}</div>
            <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
              {decisions.slice(0, 5).map((decision, index) => (
                <div key={`${decision.timestamp || 'decision'}-${index}`} className="rounded-xl bg-white/80 px-3 py-2 dark:bg-slate-900/70">
                  {String(decision.event || decision.kind || decision.tool_name || 'decision')}
                </div>
              ))}
              {decisions.length === 0 && <div>{t('memoryEvaluation.noRecentDecisions')}</div>}
            </div>
          </div>
          <div className="rounded-2xl bg-slate-50 p-4 text-sm dark:bg-slate-950/40">
            <div className="font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.ledger')}</div>
            <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
              <div>{t('memoryEvaluation.governance')} {ledger?.governance_events.length || 0}</div>
              <div>{t('memoryEvaluation.causal')} {ledger?.causal_events.length || 0}</div>
              <div>{t('memoryEvaluation.shadowReplay')} {ledger?.shadow_replay_events.length || 0}</div>
              <div>{t('memoryEvaluation.rollback')} {ledger?.rollback_events.length || 0}</div>
            </div>
          </div>
          <div className="rounded-2xl bg-slate-50 p-4 text-sm dark:bg-slate-950/40">
            <div className="font-semibold text-slate-900 dark:text-white">{t('memoryEvaluation.lastRollback')}</div>
            {rollbackResult ? (
              <div className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-300">
                <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" /> {t('memoryEvaluation.completed')}</div>
                <div>recipes {JSON.stringify(rollbackResult.restored_recipes)}</div>
                <div>guards {JSON.stringify(rollbackResult.restored_guards)}</div>
              </div>
            ) : (
              <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">{t('memoryEvaluation.noRollbackYet')}</div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

const ResearchModePanel: React.FC<ResearchModePanelProps> = ({ isOpen, onClose, clientId, temStats, onRefreshTEM }) => {
  const { t } = useI18n();
  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title={t('memoryEvaluation.title')}
      description={t('memoryEvaluation.description')}
      maxWidthClassName="max-w-6xl"
      bodyClassName="p-6"
      headerActions={(
        <button
          type="button"
          onClick={onClose}
          className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
          aria-label={t('health.close')}
        >
          <X className="h-5 w-5" />
        </button>
      )}
    >
      <MemoryEvaluationContent clientId={clientId} temStats={temStats} onRefreshTEM={onRefreshTEM} />
    </AppModal>
  );
};

export default ResearchModePanel;
