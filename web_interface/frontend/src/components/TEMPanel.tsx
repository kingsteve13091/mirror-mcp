import React, { useEffect, useMemo, useState } from 'react';
import { X, BookOpen, Shield, TrendingUp, Clock, AlertTriangle, CheckCircle, Play, Server, FlaskConical } from 'lucide-react';
import { BenchmarkReport, ParameterLearningStatus, TEMGuard, TEMRecipe, TEMStats } from '../types';
import {
  applyParameterRecommendation,
  getLearningStatus,
  reloadRuntimeParams,
  runTemBenchmark,
} from '../services/api';
import AppModal from './common/AppModal';
import NoticeBanner from './common/NoticeBanner';
import { MemoryEvaluationContent } from './ResearchModePanel';
import { useI18n } from '../i18n/I18nProvider';

interface TEMPanelProps {
  isOpen: boolean;
  onClose: () => void;
  clientId: string;
  temStats: TEMStats | null;
  recipes: TEMRecipe[];
  guards: TEMGuard[];
  onRefresh: () => void;
}

const TEMPanel: React.FC<TEMPanelProps> = ({
  isOpen,
  onClose,
  clientId,
  temStats,
  recipes,
  guards,
  onRefresh,
}) => {
  const { t } = useI18n();
  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null);
  const [benchLoading, setBenchLoading] = useState(false);
  const [learningStatus, setLearningStatus] = useState<ParameterLearningStatus | null>(null);
  const [learningLoading, setLearningLoading] = useState(false);
  const [reloadLoading, setReloadLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'info' | 'success' | 'warning' | 'error'; message: string } | null>(null);
  const [activeTab, setActiveTab] = useState<'memory' | 'evaluation'>('memory');

  const fetchLearningStatus = async () => {
    setLearningLoading(true);
    setNotice(null);
    try {
      const data = await getLearningStatus();
      setLearningStatus(data);
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setLearningLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      onRefresh();
      void fetchLearningStatus();
    }
  }, [isOpen, onRefresh]);
  const tabButtonClass = useMemo(
    () => (tab: 'memory' | 'evaluation') => (
      activeTab === tab
        ? 'rounded-2xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm dark:bg-white dark:text-slate-900'
        : 'rounded-2xl bg-slate-100 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
    ),
    [activeTab],
  );

  if (!isOpen) return null;

  const totalRecipes = temStats?.total_recipes ?? recipes.length;
  const totalGuards = temStats?.total_guards ?? guards.length;
  const totalBlocks = temStats?.total_blocks ?? 0;

  const runBenchmark = async () => {
    setBenchLoading(true);
    setNotice(null);
    try {
      const data = await runTemBenchmark();
      setBenchmark(data);
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBenchLoading(false);
    }
  };

  const reloadParamsNow = async () => {
    setReloadLoading(true);
    setNotice(null);
    try {
      await reloadRuntimeParams();
      setNotice({ tone: 'success', message: t('temPanel.runtimeParamsReloaded') });
      await fetchLearningStatus();
      onRefresh();
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setReloadLoading(false);
    }
  };

  const applyRecommendation = async () => {
    setApplyLoading(true);
    setNotice(null);
    try {
      const data = await applyParameterRecommendation();
      const appliedCount = Number(data?.apply_result?.count || 0);
      setNotice({ tone: 'success', message: t('temPanel.parameterUpdatesApplied', { count: appliedCount }) });
      await fetchLearningStatus();
      onRefresh();
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setApplyLoading(false);
    }
  };

  const downloadJson = (filename: string, payload: unknown) => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <AppModal
      isOpen={isOpen}
      onClose={onClose}
      title={t('app.toolExecutionMemory')}
      description={t('temPanel.description')}
      maxWidthClassName="max-w-5xl"
      bodyClassName="p-6"
      headerActions={(
        <div className="flex items-center gap-2">
          <div className="hidden rounded-2xl border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-900/70 sm:flex">
            <button
              type="button"
              onClick={() => setActiveTab('memory')}
              className={tabButtonClass('memory')}
            >
              {t('temPanel.memory')}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('evaluation')}
              className={tabButtonClass('evaluation')}
            >
              {t('temPanel.evaluation')}
            </button>
          </div>
          <button onClick={onClose} className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white" aria-label={t('temPanel.close')}>
            <X size={20} />
          </button>
        </div>
      )}
    >
      <div className="space-y-6">
        {notice && <NoticeBanner tone={notice.tone} message={notice.message} onClose={() => setNotice(null)} />}

        <div className="flex gap-2 sm:hidden">
          <button
            type="button"
            onClick={() => setActiveTab('memory')}
            className={tabButtonClass('memory')}
          >
            {t('temPanel.memory')}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('evaluation')}
            className={tabButtonClass('evaluation')}
          >
            {t('temPanel.evaluation')}
          </button>
        </div>

        {activeTab === 'evaluation' ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-3 text-sm text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/20 dark:text-sky-100">
              <div className="flex items-center gap-2 font-semibold">
                <FlaskConical className="h-4 w-4" />
                <span>{t('memoryEvaluation.title')}</span>
              </div>
              <div className="mt-1 text-xs leading-6 text-sky-800 dark:text-sky-200">
                {t('memoryEvaluation.description')}
              </div>
            </div>
            <MemoryEvaluationContent
              clientId={clientId}
              temStats={temStats}
              onRefreshTEM={onRefresh}
            />
          </div>
        ) : (
          <>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="flex items-center space-x-3 rounded-2xl bg-slate-50 p-4 shadow-sm dark:bg-slate-950/30">
            <BookOpen size={18} className="text-amber-500" />
            <div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{totalRecipes}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{t('temPanel.recipes')}</div>
            </div>
          </div>
          <div className="flex items-center space-x-3 rounded-2xl bg-slate-50 p-4 shadow-sm dark:bg-slate-950/30">
            <Shield size={18} className="text-red-500" />
            <div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{totalGuards}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{t('temPanel.guards')}</div>
            </div>
          </div>
          <div className="flex items-center space-x-3 rounded-2xl bg-slate-50 p-4 shadow-sm dark:bg-slate-950/30">
            <AlertTriangle size={18} className="text-orange-500" />
            <div>
              <div className="text-lg font-bold text-slate-900 dark:text-white">{totalBlocks}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{t('temPanel.blocks')}</div>
            </div>
          </div>
        </div>

        {temStats?.failure_cause_distribution && Object.keys(temStats.failure_cause_distribution).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(temStats.failure_cause_distribution).map(([cause, count]) => (
              <span key={cause} className="rounded-lg bg-red-50 px-2 py-1 text-xs font-mono text-red-700 dark:bg-red-900/20 dark:text-red-300">
                {cause}: {count}
              </span>
            ))}
          </div>
        )}

        <section className="rounded-2xl border border-cyan-200 bg-cyan-50/40 p-4 dark:border-cyan-900/50 dark:bg-cyan-900/10">
          <h3 className="mb-3 text-sm font-semibold text-cyan-700 dark:text-cyan-300">
            {t('temPanel.parameterLearning')}
          </h3>

          <div className="mb-3 flex flex-wrap gap-2">
            <button
              onClick={() => { void fetchLearningStatus(); }}
              disabled={learningLoading}
              className="rounded-lg bg-cyan-100 px-3 py-1.5 text-xs font-medium text-cyan-700 transition hover:bg-cyan-200 disabled:opacity-50 dark:bg-cyan-900/30 dark:text-cyan-300 dark:hover:bg-cyan-900/50"
            >
              {learningLoading ? t('temPanel.refreshing') : t('temPanel.refreshLearningState')}
            </button>
            <button
              onClick={() => { void reloadParamsNow(); }}
              disabled={reloadLoading}
              className="rounded-lg bg-emerald-100 px-3 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-200 disabled:opacity-50 dark:bg-emerald-900/30 dark:text-emerald-300 dark:hover:bg-emerald-900/50"
            >
              {reloadLoading ? t('temPanel.reloading') : t('temPanel.reloadParameters')}
            </button>
            <button
              onClick={() => { void applyRecommendation(); }}
              disabled={applyLoading}
              className="rounded-lg bg-indigo-100 px-3 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-200 disabled:opacity-50 dark:bg-indigo-900/30 dark:text-indigo-300 dark:hover:bg-indigo-900/50"
            >
              {applyLoading ? t('temPanel.applying') : t('temPanel.applyRecommendation')}
            </button>
          </div>

          {learningStatus ? (
            <div className="grid grid-cols-1 gap-2 text-xs md:grid-cols-4">
              <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
                <div className="text-slate-500 dark:text-slate-400">{t('temPanel.feedback')}</div>
                <div className="font-mono font-semibold text-slate-900 dark:text-white">{learningStatus.feedback_count}</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
                <div className="text-slate-500 dark:text-slate-400">{t('temPanel.minFeedback')}</div>
                <div className="font-mono font-semibold text-slate-900 dark:text-white">{learningStatus.min_feedback_for_update}</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
                <div className="text-slate-500 dark:text-slate-400">{t('temPanel.applyInterval')}</div>
                <div className="font-mono font-semibold text-slate-900 dark:text-white">{learningStatus.auto_apply_interval}</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
                <div className="text-slate-500 dark:text-slate-400">{t('temPanel.exploration')}</div>
                <div className="font-mono font-semibold text-slate-900 dark:text-white">{(learningStatus.exploration_probability * 100).toFixed(1)}%</div>
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-500 dark:text-slate-400">{t('temPanel.learningStatusMissing')}</div>
          )}
        </section>

        {benchmark && (
          <section className="rounded-2xl border border-indigo-200 bg-indigo-50/50 p-4 dark:border-indigo-900/50 dark:bg-indigo-900/10">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="flex items-center space-x-2 text-sm font-semibold text-indigo-700 dark:text-indigo-400">
                <Play size={16} />
                <span>{t('temPanel.benchmarkReport')}: {(benchmark.summary.pass_rate * 100).toFixed(0)}% {t('temPanel.passRate')} ({benchmark.summary.passed}/{benchmark.summary.total_scenarios})</span>
                <span className="text-xs font-normal text-slate-500 dark:text-slate-400">({benchmark.duration_ms}ms)</span>
              </h3>
              <button
                type="button"
                onClick={() => downloadJson('tem-benchmark-report.json', benchmark)}
                className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-50 dark:border-indigo-800 dark:bg-slate-900/50 dark:text-indigo-300"
              >
                {t('common.save')}
              </button>
            </div>
            <div className="space-y-2">
              {benchmark.scenarios.map((scenario) => (
                <div key={scenario.name} className="flex items-center justify-between rounded-lg bg-white p-2 text-xs dark:bg-slate-900/60">
                  <div className="flex items-center space-x-2">
                    {scenario.passed
                      ? <CheckCircle size={14} className="text-green-500" />
                      : <AlertTriangle size={14} className="text-red-500" />}
                    <span className="font-medium text-slate-800 dark:text-slate-200">{scenario.name}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-slate-500 dark:text-slate-400">
                    {Object.entries(scenario.metrics).map(([key, value]) => (
                      <span key={key}>{key}: <span className="font-mono font-medium">{typeof value === 'number' ? value.toFixed(3) : value}</span></span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="flex items-center space-x-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
              <BookOpen size={16} className="text-amber-500" />
              <span>{t('temPanel.learnedRecipes')} ({recipes.length})</span>
            </h3>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => downloadJson('tem-recipes.json', recipes)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
              >
                {t('common.save')}
              </button>
              <button
                onClick={() => { void runBenchmark(); }}
                disabled={benchLoading}
                className="rounded-lg bg-indigo-100 px-3 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-200 disabled:opacity-50 dark:bg-indigo-900/30 dark:text-indigo-300 dark:hover:bg-indigo-900/50"
              >
                {benchLoading ? t('temPanel.runningBenchmark') : t('temPanel.runBenchmark')}
              </button>
            </div>
          </div>
          {recipes.length === 0 ? (
            <div className="py-8 text-center text-slate-400 dark:text-slate-500">
              <BookOpen size={32} className="mx-auto mb-2 opacity-50" />
              <p className="text-sm">{t('temPanel.noLearnedRecipes')}</p>
              <p className="mt-1 text-xs">{t('temPanel.noLearnedRecipesDesc')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {recipes.map((recipe) => (
                <div key={recipe.id} className="rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md dark:border-slate-700 dark:bg-slate-900/60">
                  <div className="mb-2 flex items-start justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-900 dark:text-white" title={recipe.name}>
                        {recipe.name}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
                        {recipe.description}
                      </div>
                    </div>
                    <div className={`ml-2 rounded-full px-2 py-0.5 text-xs font-medium ${
                      recipe.success_rate >= 0.8
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : recipe.success_rate >= 0.5
                          ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                          : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                      {(recipe.success_rate * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="flex items-center space-x-3 text-xs text-slate-500 dark:text-slate-400">
                    <span className="flex items-center space-x-1">
                      <CheckCircle size={12} className="text-green-500" />
                      <span>{recipe.success_count} {t('temPanel.success')}</span>
                    </span>
                    <span className="flex items-center space-x-1">
                      <Clock size={12} />
                      <span>{recipe.avg_latency_ms.toFixed(0)}ms</span>
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {recipe.steps.map((step, index) => (
                      <span key={`${recipe.id}-step-${index}`} className="inline-flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-xs text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
                        {step.tool_name}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="flex items-center space-x-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
              <Shield size={16} className="text-red-500" />
              <span>{t('temPanel.failureGuards')} ({guards.length})</span>
            </h3>
            <button
              type="button"
              onClick={() => downloadJson('tem-guards.json', guards)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-200"
            >
              {t('common.save')}
            </button>
          </div>
          {guards.length === 0 ? (
            <div className="py-8 text-center text-slate-400 dark:text-slate-500">
              <Shield size={32} className="mx-auto mb-2 opacity-50" />
              <p className="text-sm">{t('temPanel.noFailureGuards')}</p>
              <p className="mt-1 text-xs">{t('temPanel.noFailureGuardsDesc')}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {guards.map((guard) => (
                <div key={guard.id} className="rounded-xl border border-red-200 bg-red-50/50 p-4 dark:border-red-900/50 dark:bg-red-900/10">
                  <div className="mb-2 flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium text-slate-900 dark:text-white">{guard.tool_name}</span>
                        {guard.server_name && (
                          <span className="flex items-center space-x-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                            <Server size={10} />
                            <span>{guard.server_name}</span>
                          </span>
                        )}
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-600 dark:bg-red-900/30 dark:text-red-400">
                          {guard.error_type}
                        </span>
                        {guard.failure_cause && guard.failure_cause !== 'unknown' && (
                          <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">
                            {guard.failure_cause}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-xs text-slate-600 dark:text-slate-400">{guard.error_message}</div>
                    </div>
                    <div className="ml-2 flex items-center space-x-1 text-xs font-medium text-red-600 dark:text-red-400">
                      <AlertTriangle size={12} />
                      <span>{guard.block_count}x</span>
                    </div>
                  </div>
                  <div className="mt-2 rounded-lg bg-white p-2 text-xs text-slate-600 dark:bg-slate-900/60 dark:text-slate-300">
                    <TrendingUp size={12} className="mr-1 inline text-green-500" />
                    <span className="font-medium">{t('temPanel.suggestion')}: </span>
                    {guard.alternative_suggestion}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
          </>
        )}
      </div>
    </AppModal>
  );
};

export default TEMPanel;
