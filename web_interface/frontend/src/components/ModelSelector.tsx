import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, ChevronDown, Cpu, Eye, Zap } from 'lucide-react';
import { AIModel } from '../types';
import { getModels } from '../services/api';
import { useI18n } from '../i18n/I18nProvider';

interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  disabled?: boolean;
  models?: AIModel[];
}

const ModelSelector: React.FC<ModelSelectorProps> = ({
  selectedModel,
  onModelChange,
  disabled = false,
  models: externalModels,
}) => {
  const { t } = useI18n();
  const [models, setModels] = useState<AIModel[]>([]);
  const [loading, setLoading] = useState(!externalModels);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (externalModels) {
      setModels(externalModels);
      setLoading(false);
      return;
    }

    const load = async () => {
      try {
        const data = await getModels();
        setModels(data.models || []);
      } catch (error) {
        console.error('Failed to load models:', error);
        setModels([]);
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [externalModels]);

  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
      document.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const selectedModelData = useMemo(
    () => models.find((model) => model.id === selectedModel),
    [models, selectedModel],
  );

  const getModelIcon = (model: AIModel) => {
    if (model.type === 'multimodal') {
      return <Eye className="h-4 w-4" />;
    }
    return model.provider === 'openrouter' ? <Zap className="h-4 w-4" /> : <Bot className="h-4 w-4" />;
  };

  const getProviderBadge = (model: AIModel) => (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:bg-slate-700 dark:text-slate-200">
      {model.provider || t('modelSelector.unknown')}
    </span>
  );

  const getAvailabilityBadge = (model: AIModel) => {
    if (model.available === false) {
      return (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
          unavailable
        </span>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="flex items-center space-x-2 rounded-xl bg-white/70 px-3 py-2 text-sm text-gray-500 shadow-sm dark:bg-gray-800/70 dark:text-gray-300">
        <Cpu className="h-4 w-4 animate-pulse" />
        <span>{t('modelSelector.loadingModels')}</span>
      </div>
    );
  }

  return (
    <div ref={dropdownRef} className="relative z-50">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`flex w-full items-center justify-between rounded-2xl border border-white/30 bg-white/80 px-4 py-3 text-left shadow-lg backdrop-blur-md transition dark:border-gray-700/40 dark:bg-gray-800/80 ${
          disabled ? 'cursor-not-allowed opacity-60' : 'hover:bg-white dark:hover:bg-gray-800'
        }`}
      >
        <div className="flex min-w-0 items-center space-x-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-r from-blue-500 to-cyan-500 text-white">
            {selectedModelData ? getModelIcon(selectedModelData) : <Cpu className="h-4 w-4" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center space-x-2">
              <span className="truncate text-sm font-semibold text-gray-900 dark:text-white">
                {selectedModelData?.name || t('modelSelector.selectModel')}
              </span>
              {selectedModelData && getProviderBadge(selectedModelData)}
              {selectedModelData && getAvailabilityBadge(selectedModelData)}
            </div>
            <p className="truncate text-xs text-gray-500 dark:text-gray-400">
              {selectedModelData?.description || t('modelSelector.chooseAvailableModel')}
            </p>
          </div>
        </div>
        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          role="listbox"
          aria-label={t('modelSelector.modelCatalog')}
          className="absolute left-0 right-0 top-full mt-2 max-h-96 overflow-y-auto rounded-2xl border border-white/30 bg-white/95 p-2 shadow-2xl backdrop-blur-xl dark:border-gray-700/40 dark:bg-gray-800/95"
        >
          <div className="px-3 py-2 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {t('modelSelector.modelCatalog')} ({models.length})
          </div>
          {models.length === 0 ? (
            <div className="px-3 py-4 text-sm text-gray-500 dark:text-gray-400">
              {t('modelSelector.noModels')}
            </div>
          ) : (
            models.map((model) => (
              <button
                key={model.id}
                type="button"
                role="option"
                aria-selected={selectedModel === model.id}
                disabled={model.available === false}
                onClick={() => {
                  if (model.available === false) {
                    return;
                  }
                  onModelChange(model.id);
                  setIsOpen(false);
                }}
                className={`flex w-full items-start justify-between rounded-xl px-3 py-3 text-left transition ${
                  model.available === false
                    ? 'cursor-not-allowed opacity-60'
                    : ''
                } ${
                  selectedModel === model.id
                    ? 'bg-blue-50 text-blue-900 dark:bg-blue-900/20 dark:text-blue-100'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <div className="flex min-w-0 items-start space-x-3">
                  <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-100">
                    {getModelIcon(model)}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-medium">{model.name}</span>
                      {getProviderBadge(model)}
                      {getAvailabilityBadge(model)}
                    </div>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {model.description}
                    </p>
                    <div className="mt-2 flex items-center space-x-3 text-[11px] text-gray-500 dark:text-gray-400">
                      <span>{model.type === 'multimodal' ? t('modelSelector.multimodal') : t('modelSelector.text')}</span>
                      <span>{model.max_tokens.toLocaleString()} {t('modelSelector.tokens')}</span>
                    </div>
                  </div>
                </div>
                {selectedModel === model.id && <Check className="h-4 w-4 text-blue-500" />}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default ModelSelector;
