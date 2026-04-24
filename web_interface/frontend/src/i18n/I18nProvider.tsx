import React, { createContext, useContext, useMemo } from 'react';
import { ChatSettings } from '../types';
import { messages, Language } from './messages';

type MessageTree = Record<string, unknown>;

interface I18nContextValue {
  language: Language;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue>({
  language: 'zh',
  t: (key: string) => key,
});

function getNestedValue(source: MessageTree, key: string): string | undefined {
  const parts = key.split('.');
  let current: unknown = source;
  for (const part of parts) {
    if (!current || typeof current !== 'object' || !(part in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === 'string' ? current : undefined;
}

function interpolate(template: string, vars?: Record<string, string | number>) {
  if (!vars) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (_, key) => String(vars[key] ?? `{${key}}`));
}

export const I18nProvider: React.FC<{
  settings: ChatSettings;
  children: React.ReactNode;
}> = ({ settings, children }) => {
  const language = settings.language || 'zh';

  const value = useMemo<I18nContextValue>(() => ({
    language,
    t: (key: string, vars?: Record<string, string | number>) => {
      const dictionary = messages[language] || messages.zh;
      const translated = getNestedValue(dictionary, key) || getNestedValue(messages.zh, key) || key;
      return interpolate(translated, vars);
    },
  }), [language]);

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
};

export function useI18n() {
  return useContext(I18nContext);
}

export type { Language };

export function translateForLanguage(
  language: Language | undefined,
  key: string,
  vars?: Record<string, string | number>,
) {
  const resolvedLanguage = language || 'zh';
  const dictionary = messages[resolvedLanguage] || messages.zh;
  const translated = getNestedValue(dictionary, key) || getNestedValue(messages.zh, key) || key;
  return interpolate(translated, vars);
}
