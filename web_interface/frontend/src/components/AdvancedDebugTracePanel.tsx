import React from 'react';
import {
  Archive,
  ChevronDown,
  Cpu,
  Eye,
  GitBranch,
  ShieldAlert,
  Workflow,
} from 'lucide-react';
import {
  CausalTrace,
  ChatMessage,
  MemoryPlaneAttributionItem,
  MemoryPlaneSnapshot,
} from '../types';
import { getAttachmentBodyHiddenNotice } from '../utils/attachmentTransparency';
import { useI18n } from '../i18n/I18nProvider';

interface AdvancedDebugTracePanelProps {
  message: ChatMessage;
  visible?: boolean;
}

const AdvancedDebugTracePanel: React.FC<AdvancedDebugTracePanelProps> = ({
  message,
  visible = false,
}) => {
  const { t, language } = useI18n();
  const memoryPlane = message.metadata?.memory_plane as MemoryPlaneSnapshot | undefined;
  const causalTrace = message.metadata?.causal_trace as CausalTrace | undefined;
  const runTrace = message.metadata?.run_trace as Record<string, any> | undefined;

  if (
    !visible
    || (
      !message.metadata
      || (
        !memoryPlane
        && !causalTrace
        && !message.metadata.model_used
        && !message.metadata.tem_event
        && !runTrace
      )
    )
  ) {
    return null;
  }

  const renderAttribution = (items: MemoryPlaneAttributionItem[]) => {
    if (!items || items.length === 0) {
      return null;
    }

    return (
      <div className="mt-3 rounded-xl border border-emerald-200/80 bg-emerald-50/80 p-3 dark:border-emerald-900/40 dark:bg-emerald-900/10">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
          {t('message.memoryAttribution')}
        </div>
        <div className="space-y-2">
          {items.slice(0, 4).map((item) => (
            <div key={`${item.source}-${item.item_id}`} className="rounded-lg bg-white/80 px-3 py-2 text-xs text-gray-700 shadow-sm dark:bg-gray-900/40 dark:text-gray-300">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium text-gray-900 dark:text-gray-100">{item.label}</div>
                <div className="font-mono text-[11px] text-gray-500 dark:text-gray-400">
                  {t('message.score')} {item.score.toFixed(3)} | {t('message.freshness')} {item.freshness.toFixed(3)}
                </div>
              </div>
              <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">{item.rationale}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderRunTrace = () => {
    if (!message.metadata || (!memoryPlane && !causalTrace && !message.metadata.model_used && !message.metadata.tem_event && !runTrace)) {
      return null;
    }

    const safeMemoryPlane = memoryPlane || ({
      timestamp: '',
      routing: {},
      retention: {},
      forgetting: {},
      attribution: [],
    } as MemoryPlaneSnapshot);
    const safeRunTrace = runTrace || {};
    const routing = memoryPlane?.routing || {};
    const scores = Array.isArray(routing.scores) ? routing.scores : [];
    const executionPolicy = (safeMemoryPlane as any)?.execution_policy || {};
    const recipePreflight = executionPolicy.recipe_preflight || message.metadata.recipe_preflight;
    const guardEvidence = message.metadata.guard_evidence;
    const attribution = Array.isArray(safeMemoryPlane?.attribution) ? safeMemoryPlane.attribution : [];
    const shadowItems = causalTrace?.shadow_replay?.items || [];
    const attachmentTrace = Array.isArray(safeRunTrace.attachments) ? (safeRunTrace.attachments as any[]) : [];

    return (
      <details className="mt-4 group rounded-2xl border border-slate-200/80 bg-slate-50/90 dark:border-slate-700/60 dark:bg-slate-950/35">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 transition hover:bg-white/50 dark:hover:bg-white/5">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
            <Workflow size={16} />
            <span>{t('message.runTrace')}</span>
          </div>
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 transition group-open:rotate-180 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            <ChevronDown size={16} />
          </span>
        </summary>
        <div className="grid gap-3 px-4 pb-4 text-xs text-slate-600 dark:text-slate-300 lg:grid-cols-3">
          <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70">
            <div className="mb-2 font-semibold text-slate-900 dark:text-white">{t('message.model')}</div>
            <div>{message.metadata.model_name || message.metadata.model_used || t('common.notApplicable')}</div>
            {runTrace?.provider && <div>provider {String(runTrace.provider)}</div>}
            {runTrace?.request_id && <div>request {String(runTrace.request_id)}</div>}
            {message.metadata.execution_time && <div>{t('message.latency')} {Number(message.metadata.execution_time).toFixed(2)}s</div>}
          </div>
          <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70">
            <div className="mb-2 font-semibold text-slate-900 dark:text-white">{t('message.router')}</div>
            <div>{t('message.type')} {routing.router_type || causalTrace?.causal_ablation?.router_type || t('common.notApplicable')}</div>
            <div>{t('message.selected')} {causalTrace?.selected_tool || (routing.selected_tools || [])[0] || t('common.notApplicable')}</div>
            <div>{t('message.candidates')} {scores.length}</div>
          </div>
          <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70">
            <div className="mb-2 font-semibold text-slate-900 dark:text-white">{t('message.recipeGuard')}</div>
            <div>{t('message.recipe')} {recipePreflight?.decision || causalTrace?.recipe_preflight_decision || t('common.notApplicable')}</div>
            <div>{t('message.guard')} {guardEvidence?.guard_id || causalTrace?.guard_id || (causalTrace?.blocked ? t('message.blocked') : t('common.notApplicable'))}</div>
            <div>{t('message.policy')} {causalTrace?.execution_policy_action || executionPolicy.recommended_action || t('common.notApplicable')}</div>
            {runTrace?.tool_policy?.policy_action && <div>runtime policy {String(runTrace.tool_policy.policy_action)}</div>}
          </div>
          {attachmentTrace.length > 0 && (
            <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70 lg:col-span-3">
              <div className="mb-2 font-semibold text-slate-900 dark:text-white">
                {language === 'zh' ? '\u9644\u4ef6\u7406\u89e3' : 'Attachment understanding'}
              </div>
              <div className="space-y-2">
                {attachmentTrace.map((item, index) => (
                  <div key={`${item.filename || 'attachment'}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50/80 px-3 py-2 dark:border-slate-700 dark:bg-slate-950/40">
                    <div className="font-medium text-slate-900 dark:text-white">{item.original_filename || item.filename}</div>
                    <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                      {String(item.mime_type || 'application/octet-stream')} | {String(item.parse_status || 'unknown')}
                      {item.parser ? ` | parser=${String(item.parser)}` : ''}
                      {typeof item.full_text_chars === 'number' ? ` | chars=${item.full_text_chars}` : ''}
                    </div>
                    {item.preview_text && (
                      <div className="mt-2 rounded-md bg-white px-2 py-2 text-[11px] text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                        {getAttachmentBodyHiddenNotice(language, 'bubble')}
                      </div>
                    )}
                    {!item.preview_text && item.error && (
                      <div className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">{String(item.error)}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70 lg:col-span-2">
            <div className="mb-2 font-semibold text-slate-900 dark:text-white">{t('message.attribution')}</div>
            {attribution.length > 0 ? (
              <div className="space-y-1">
                {attribution.slice(0, 4).map((item: MemoryPlaneAttributionItem) => (
                  <div key={`${item.source}-${item.item_id}`} className="flex items-center justify-between gap-3">
                    <span>{item.label}</span>
                    <span className="font-mono">{Number(item.score || 0).toFixed(3)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div>{t('message.noAttribution')}</div>
            )}
          </div>
          <div className="rounded-xl bg-white/85 p-3 dark:bg-slate-900/70">
            <div className="mb-2 font-semibold text-slate-900 dark:text-white">{t('message.shadowReplay')}</div>
            {causalTrace?.shadow_replay?.available ? (
              <div className="space-y-1">
                {shadowItems.slice(0, 3).map((item: any) => (
                  <div key={item.tool_name}>
                    {item.tool_name}: {Number(item.observed_probability || 0).toFixed(3)}
                  </div>
                ))}
              </div>
            ) : (
              <div>{causalTrace?.shadow_replay?.reason || t('message.notAvailable')}</div>
            )}
          </div>
        </div>
      </details>
    );
  };

  const renderMemoryPlane = () => {
    if (!memoryPlane) {
      return null;
    }

    const routingScores = Array.isArray(memoryPlane.routing?.scores) ? memoryPlane.routing.scores : [];
    const forgettingRecipes = Array.isArray(memoryPlane.forgetting?.recipes) ? memoryPlane.forgetting.recipes : [];
    const forgettingGuards = Array.isArray(memoryPlane.forgetting?.guards) ? memoryPlane.forgetting.guards : [];
    const retainedFacts = Array.isArray(memoryPlane.retention?.retained_facts) ? memoryPlane.retention.retained_facts : [];
    const governance = memoryPlane.governance || {};
    const executionPolicy = (memoryPlane as any).execution_policy || {};
    const recipePreflight = executionPolicy.recipe_preflight || message.metadata?.recipe_preflight;
    const causalAblation = memoryPlane.causal_ablation;
    const routingTrainingState = memoryPlane.routing?.router_training_state;

    return (
      <details className="mt-4 group rounded-2xl border border-sky-200/80 bg-gradient-to-br from-sky-50 to-cyan-50 shadow-sm dark:border-sky-700/40 dark:from-slate-900/95 dark:to-sky-950/25">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 transition hover:bg-white/40 dark:hover:bg-white/5">
          <div className="flex items-center gap-2 text-sm font-semibold text-sky-800 dark:text-sky-200">
            <GitBranch size={16} />
            <span>{t('message.memoryPlane')}</span>
          </div>
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-sky-200/80 bg-white/90 text-sky-600 shadow-sm transition group-open:rotate-180 dark:border-sky-700/50 dark:bg-slate-950/70 dark:text-sky-200">
            <ChevronDown size={16} />
          </span>
        </summary>

        <div className="space-y-3 px-4 pb-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-xl bg-white/90 p-3 shadow-sm dark:bg-slate-950/60">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-300">
                <GitBranch size={14} />
                <span>{t('message.routing')}</span>
              </div>
              <div className="space-y-2 text-xs">
                <div className="text-gray-600 dark:text-gray-300">{memoryPlane.routing?.reason || t('message.noRoutingReason')}</div>
                {memoryPlane.routing?.intent_signature && (
                  <div className="font-mono text-[11px] text-gray-500 dark:text-gray-400">
                    {t('message.intent')} {String(memoryPlane.routing.intent_signature)}
                  </div>
                )}
                {routingTrainingState && (
                  <div className="rounded-lg border border-sky-100 bg-white/80 px-2 py-2 text-[11px] text-gray-500 dark:border-sky-800/40 dark:bg-slate-950/50 dark:text-gray-400">
                    {t('message.updates')} {Number(routingTrainingState.updates || 0)} | lr {Number(routingTrainingState.learning_rate || 0).toFixed(3)} | l2 {Number(routingTrainingState.l2 || 0).toFixed(4)}
                  </div>
                )}
                {routingScores.length > 0 ? routingScores.slice(0, 3).map((score: any) => (
                  <div key={score.tool_name} className="rounded-lg border border-sky-100 bg-sky-50/80 px-2 py-2 dark:border-sky-800/40 dark:bg-sky-950/20">
                    <div className="font-medium text-gray-900 dark:text-gray-100">{score.tool_name}</div>
                    <div className="mt-1 font-mono text-[11px] text-gray-500 dark:text-gray-400">
                      {t('message.final')} {Number(score.final_score ?? score.score ?? 0).toFixed(3)} | p {Number(score.router_probability || 0).toFixed(3)}
                    </div>
                    {'lexical_score' in score && (
                      <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                        {t('message.lexical')} {Number(score.lexical_score || 0).toFixed(2)} | {t('message.ngram')} {Number(score.ngram_score || 0).toFixed(2)} | {t('message.recipe')} {Number(score.recipe_support || 0).toFixed(2)} | {t('message.global')} {Number(score.global_reliability || 0).toFixed(2)} | {t('message.intent')} {Number(score.intent_reliability || 0).toFixed(2)} | {t('message.guard')} -{Number(score.guard_penalty || 0).toFixed(2)}
                      </div>
                    )}
                  </div>
                )) : <div className="text-gray-500 dark:text-gray-400">{t('message.noRoutingScores')}</div>}
              </div>
            </div>

            <div className="rounded-xl bg-white/90 p-3 shadow-sm dark:bg-slate-950/60">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                <Archive size={14} />
                <span>{t('message.retentionForgetting')}</span>
              </div>
              <div className="space-y-2 text-xs text-gray-600 dark:text-gray-300">
                <div>{t('message.summary')}: {memoryPlane.forgetting?.summary?.action || t('common.notApplicable')}</div>
                <div>{t('message.retainedFacts')}: {retainedFacts.length}</div>
                <div>{t('message.recipeActions')}: {forgettingRecipes.length}</div>
                <div>{t('message.guardActions')}: {forgettingGuards.length}</div>
                <div>{t('message.policyVersion')}: {memoryPlane.forgetting?.policy_version || t('common.notApplicable')}</div>
                {(governance.recipes || governance.guards || governance.suppressed_fact_hashes) && (
                  <div className="rounded-lg border border-amber-100 bg-white/80 px-2 py-2 text-[11px] dark:border-amber-800/40 dark:bg-slate-950/50">
                    <div>{t('message.governanceRecipes')} {JSON.stringify(governance.recipes || {})}</div>
                    <div>{t('message.governanceGuards')} {JSON.stringify(governance.guards || {})}</div>
                    <div>{t('message.suppressedFacts')} {(governance.suppressed_fact_hashes || []).length}</div>
                    <div>{t('message.executed')} {governance.policy_executed ? t('message.yes') : t('message.no')}</div>
                  </div>
                )}
                {forgettingRecipes.slice(0, 2).map((recipe: any) => (
                  <div key={recipe.id} className="rounded-lg border border-amber-100 bg-amber-50/80 px-2 py-2 dark:border-amber-800/40 dark:bg-amber-950/20">
                    <div className="font-medium text-gray-900 dark:text-gray-100">{recipe.name}</div>
                    <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                      {recipe.action} | q={Number(recipe.quality_score || 0).toFixed(2)} | f={Number(recipe.freshness || 0).toFixed(2)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl bg-white/90 p-3 shadow-sm dark:bg-slate-950/60">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
                <ShieldAlert size={14} />
                <span>{t('message.riskGuard')}</span>
              </div>
              <div className="space-y-2 text-xs text-gray-600 dark:text-gray-300">
                {forgettingGuards.length > 0 ? forgettingGuards.slice(0, 3).map((guard: any) => (
                  <div key={guard.id} className="rounded-lg border border-rose-100 bg-rose-50/80 px-2 py-2 dark:border-rose-800/40 dark:bg-rose-950/20">
                    <div className="font-medium text-gray-900 dark:text-gray-100">{guard.tool}</div>
                    <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                      {guard.action} | p={Number(guard.failure_prob || 0).toFixed(2)} | fresh={Number(guard.freshness || 0).toFixed(2)}
                    </div>
                  </div>
                )) : <div className="text-gray-500 dark:text-gray-400">{t('message.noGuardRiskActions')}</div>}
              </div>
            </div>
          </div>

          {recipePreflight && (
            <div className="mt-3 rounded-xl border border-indigo-200/80 bg-indigo-50/80 p-3 dark:border-indigo-800/40 dark:bg-indigo-950/20">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-indigo-700 dark:text-indigo-300">
                <Cpu size={14} />
                <span>{t('message.executionPolicy')}</span>
              </div>
              <div className="grid gap-2 text-xs text-gray-700 dark:text-gray-300 md:grid-cols-2">
                <div>{t('message.decision')}: {recipePreflight.decision || executionPolicy.recommended_action || t('common.notApplicable')}</div>
                <div>{t('message.reason')}: {recipePreflight.reason || t('common.notApplicable')}</div>
                {recipePreflight.best && (
                  <>
                    <div>{t('message.recipe')}: {recipePreflight.best.recipe_name}</div>
                    <div>{t('message.schema')}: {Number(recipePreflight.best.schema_similarity || 0).toFixed(2)}</div>
                    <div>{t('message.success')}: {Number(recipePreflight.best.success_rate || 0).toFixed(2)}</div>
                    <div>{t('message.verify')}: {Number(recipePreflight.best.verification_rate || 0).toFixed(2)}</div>
                  </>
                )}
              </div>
            </div>
          )}

          {causalAblation?.available && (
            <div className="mt-3 rounded-xl border border-violet-200/80 bg-violet-50/80 p-3 dark:border-violet-800/40 dark:bg-violet-950/20">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
                <Eye size={14} />
                <span>{t('message.causalAblation')}</span>
              </div>
              <div className="space-y-2 text-xs text-gray-700 dark:text-gray-300">
                <div>{t('message.selectedTool')}: {causalAblation.selected_tool || t('common.notApplicable')}</div>
                <div>{t('message.significantEffects')}: {(causalAblation.significant_effects || []).join(', ') || t('message.none')}</div>
                {(causalAblation.ablations || []).slice(0, 4).map((item: any) => (
                  <div key={item.feature} className="rounded-lg border border-violet-100 bg-white/80 px-2 py-2 text-[11px] dark:border-violet-800/40 dark:bg-slate-950/50">
                    {item.feature}: delta {Number(item.delta || 0).toFixed(3)} | cf {Number(item.counterfactual_probability || 0).toFixed(3)}{item.significant ? ` | ${t('message.significant')}` : ''}
                  </div>
                ))}
              </div>
            </div>
          )}

          {renderAttribution(memoryPlane.attribution || [])}
        </div>
      </details>
    );
  };

  const renderCausalTrace = () => {
    if (!causalTrace) {
      return null;
    }

    return (
      <details className="mt-3 group rounded-xl border border-violet-200/80 bg-violet-50/80 dark:border-violet-800/40 dark:bg-violet-950/20">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-3 transition hover:bg-white/40 dark:hover:bg-white/5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
            <Eye size={14} />
            <span>{t('message.causalTrace')}</span>
          </div>
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-violet-200/80 bg-white/90 text-violet-600 shadow-sm transition group-open:rotate-180 dark:border-violet-800/50 dark:bg-slate-950/70 dark:text-violet-200">
            <ChevronDown size={14} />
          </span>
        </summary>
        <div className="grid gap-2 px-3 pb-3 text-xs text-gray-700 dark:text-gray-300 md:grid-cols-2">
          <div>{t('message.selected')}: <span className="font-mono">{causalTrace.selected_tool}</span></div>
          <div>{t('message.alternative')}: {causalTrace.top_alternative_tool || t('common.notApplicable')}</div>
          <div>{t('message.recipeMemory')}: {causalTrace.recipe_memory_used ? t('message.used') : t('message.notUsed')}</div>
          <div>{t('message.guardMemory')}: {causalTrace.guard_memory_used ? t('message.used') : t('message.notUsed')}</div>
          <div>{t('message.summaryMemory')}: {causalTrace.context_summary_used ? t('message.used') : t('message.notUsed')}</div>
          <div>{t('message.blocked')}: {causalTrace.blocked ? t('message.yes') : t('message.no')}</div>
          <div>{t('message.policy')}: {causalTrace.execution_policy_action || t('common.notApplicable')}</div>
          <div>{t('message.routeScore')}: {Number(causalTrace.routing_score_observed || 0).toFixed(3)}</div>
          <div>{t('message.learningOutcome')}: {causalTrace.policy_learning_outcome || t('common.notApplicable')}</div>
          <div>{t('message.governanceEvents')}: {Number(causalTrace.governance_event_count || 0)}</div>
          <div className="md:col-span-2">{t('message.withoutRecipe')}: {causalTrace.counterfactual_without_recipe}</div>
          <div className="md:col-span-2">{t('message.withoutGuard')}: {causalTrace.counterfactual_without_guard}</div>
          <div className="md:col-span-2">{t('message.withoutSummary')}: {causalTrace.counterfactual_without_summary}</div>
          {causalTrace.counterfactual_without_global_reliability && (
            <div className="md:col-span-2">{t('message.withoutGlobalReliability')}: {causalTrace.counterfactual_without_global_reliability}</div>
          )}
          {causalTrace.counterfactual_without_intent_reliability && (
            <div className="md:col-span-2">{t('message.withoutIntentReliability')}: {causalTrace.counterfactual_without_intent_reliability}</div>
          )}
          {causalTrace.recipe_preflight_decision && (
            <div className="md:col-span-2">{t('message.recipePreflight')}: {causalTrace.recipe_preflight_decision} | {causalTrace.recipe_preflight_reason || t('common.notApplicable')}</div>
          )}
          {causalTrace.routing_score_components && (
            <div className="md:col-span-2 font-mono text-[11px] text-gray-500 dark:text-gray-400">
              {Object.entries(causalTrace.routing_score_components)
                .map(([key, value]) => `${key}=${Number(value).toFixed(3)}`)
                .join(' | ')}
            </div>
          )}
          {causalTrace.counterfactual_action && (
            <div className="md:col-span-2">{t('message.counterfactualAction')}: {causalTrace.counterfactual_action}</div>
          )}
          {causalTrace.significant_causal_effects && causalTrace.significant_causal_effects.length > 0 && (
            <div className="md:col-span-2">{t('message.significantCausalEffects')}: {causalTrace.significant_causal_effects.join(', ')}</div>
          )}
          {causalTrace.shadow_replay?.available && (
            <div className="md:col-span-2 rounded-lg border border-violet-100 bg-white/80 px-3 py-2 dark:border-violet-800/40 dark:bg-slate-950/50">
              <div className="mb-2 font-semibold text-violet-700 dark:text-violet-300">{t('message.shadowReplay')}</div>
              <div className="space-y-1 text-[11px] text-gray-500 dark:text-gray-400">
                {(causalTrace.shadow_replay.items || []).slice(0, 4).map((item: any) => (
                  <div key={item.tool_name}>
                    {item.tool_name}: {t('message.score')} {Number(item.observed_final_score || 0).toFixed(3)} | {t('message.probability')} {Number(item.observed_probability || 0).toFixed(3)}{item.would_be_selected ? ` | ${t('message.selected')}` : ''}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </details>
    );
  };

  return (
    <div data-testid="advanced-debug-traces" className="mt-4">
      {renderRunTrace()}
      {renderMemoryPlane()}
      {renderCausalTrace()}
    </div>
  );
};

export default AdvancedDebugTracePanel;
