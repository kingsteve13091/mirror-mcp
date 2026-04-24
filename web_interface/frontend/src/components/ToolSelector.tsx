import React, { useEffect, useState } from 'react';
import { Search, X, Zap } from 'lucide-react';
import { AvailableTool } from '../types';
import { useI18n } from '../i18n/I18nProvider';

interface ToolSelectorProps {
  position: { x: number; y: number };
  onSelectTool: (toolName: string, serverName: string) => void;
  onClose: () => void;
  searchQuery: string;
  availableTools: AvailableTool[];
}

const ToolSelector: React.FC<ToolSelectorProps> = ({
  position,
  onSelectTool,
  onClose,
  searchQuery,
  availableTools,
}) => {
  const { t } = useI18n();
  const [filteredTools, setFilteredTools] = useState<AvailableTool[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const query = searchQuery.toLowerCase();
    const next = availableTools.filter((tool) =>
      tool.name.toLowerCase().includes(query)
      || tool.display_name.toLowerCase().includes(query)
      || tool.server.toLowerCase().includes(query),
    );
    setFilteredTools(next);
    setSelectedIndex(0);
  }, [availableTools, searchQuery]);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, filteredTools.length - 1));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
        break;
      case 'Enter':
        event.preventDefault();
        if (filteredTools[selectedIndex]) {
          onSelectTool(filteredTools[selectedIndex].name, filteredTools[selectedIndex].server);
          onClose();
        }
        break;
      case 'Escape':
        event.preventDefault();
        onClose();
        break;
      default:
        break;
    }
  };

  if (filteredTools.length === 0) {
    return null;
  }

  return (
    <div
      className="fixed z-50 w-80 max-w-md rounded-2xl border border-white/30 bg-white/95 shadow-2xl backdrop-blur-xl dark:border-gray-700/40 dark:bg-gray-800/95"
      style={{
        left: position.x,
        top: position.y - 10,
        transform: 'translateY(-100%)',
      }}
      onKeyDown={handleKeyDown}
      tabIndex={-1}
    >
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <div className="flex items-center space-x-2">
          <Zap className="h-4 w-4 text-sky-500" />
          <span className="text-sm font-semibold text-gray-900 dark:text-white">{t('toolSelector.title')}</span>
        </div>
        <button type="button" onClick={onClose} className="text-gray-400 transition hover:text-gray-700 dark:hover:text-gray-200">
          <X className="h-4 w-4" />
        </button>
      </div>

      {searchQuery && (
        <div className="border-b border-gray-200 bg-sky-50 px-4 py-2 text-sm text-sky-700 dark:border-gray-700 dark:bg-sky-900/20 dark:text-sky-300">
          <div className="flex items-center space-x-2">
            <Search className="h-3.5 w-3.5" />
            <span>{t('toolSelector.searchPrefix', { query: searchQuery })}</span>
          </div>
        </div>
      )}

      <div className="max-h-64 overflow-y-auto">
        {filteredTools.map((tool, index) => (
          <button
            key={`${tool.server}.${tool.name}`}
            type="button"
            onClick={() => {
              onSelectTool(tool.name, tool.server);
              onClose();
            }}
            className={`flex w-full items-start space-x-3 px-4 py-3 text-left transition ${
              index === selectedIndex
                ? 'border-l-4 border-sky-500 bg-sky-50 dark:bg-sky-900/20'
                : 'hover:bg-gray-50 dark:hover:bg-gray-700'
            }`}
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-r from-sky-500 to-emerald-500 text-white">
              <Zap className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center space-x-2">
                <span className="truncate font-medium text-gray-900 dark:text-white">{tool.display_name}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                  {tool.server}
                </span>
              </div>
              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">@{tool.server}.{tool.name}</div>
            </div>
          </button>
        ))}
      </div>

      <div className="border-t border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500 dark:border-gray-700 dark:bg-gray-700/40 dark:text-gray-400">
        {t('toolSelector.footerHint')}
      </div>
    </div>
  );
};

export default ToolSelector;
