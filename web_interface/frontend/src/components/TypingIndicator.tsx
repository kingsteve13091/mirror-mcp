import React from 'react';
import { useI18n } from '../i18n/I18nProvider';

const TypingIndicator: React.FC = () => {
  const { t } = useI18n();

  return (
    <div className="flex items-center space-x-3 py-2">
      <div className="flex items-center space-x-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-r from-blue-500 to-cyan-600 text-xs font-semibold text-white animate-pulse">
          AI
        </div>
        <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
          {t('typing.aiThinking')}
        </span>
      </div>
      <div className="typing-indicator">
        <div className="typing-dot"></div>
        <div className="typing-dot"></div>
        <div className="typing-dot"></div>
      </div>
    </div>
  );
};

export default TypingIndicator;
