import React, { useState, useEffect, useMemo } from 'react';
import { History, MessageSquare, Trash2, Search, Clock, X, Save, User, Bot, Sparkles, Filter, AlertTriangle } from 'lucide-react';
import { ChatMessage } from '../types';
import AppModal from './common/AppModal';
import NoticeBanner from './common/NoticeBanner';
import { translateForLanguage, useI18n } from '../i18n/I18nProvider';
import {
  buildChatTitleWithFallback,
  ChatSession,
  createSessionSnapshot,
  getDisplaySessions,
  saveCurrentSession as persistCurrentSession,
  loadCurrentSession,
  loadSavedSessions,
  saveSessions as persistSessions,
} from '../utils/chatSessionStorage';

interface ChatHistoryProps {
  isOpen: boolean;
  clientId: string;
  onClose: () => void;
  onLoadSession: (messages: ChatMessage[]) => void;
  currentMessages: ChatMessage[];
  onClearCurrentSession: () => void;
}

const ChatHistory: React.FC<ChatHistoryProps> = ({
  isOpen,
  clientId,
  onClose,
  onLoadSession,
  currentMessages,
  onClearCurrentSession,
}) => {
  const { t, language } = useI18n();
  const fallbackTitle = t('chatHistory.newConversation');
  const fallbackTitleAliases = useMemo(
    () => new Set([
      translateForLanguage('zh', 'chatHistory.newConversation'),
      translateForLanguage('en', 'chatHistory.newConversation'),
    ]),
    [],
  );
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'time' | 'messages'>('time');
  const [showFilters, setShowFilters] = useState(false);
  const [confirmClearAll, setConfirmClearAll] = useState(false);

  useEffect(() => {
    if (currentMessages.length > 0) {
      persistCurrentSession(
        createSessionSnapshot(clientId, currentMessages, {
          isAutoSaved: true,
          fallbackTitle,
        }),
      );
    }

    setSessions(getDisplaySessions(clientId, currentMessages, { fallbackTitle }));
  }, [clientId, currentMessages, fallbackTitle]);

  const saveSessions = (newSessions: ChatSession[]) => {
    setSessions(newSessions);
  };

  const saveCurrentSession = () => {
    if (currentMessages.length === 0) return;

    const archivedSession = createSessionSnapshot(clientId, currentMessages, {
      id: `session-${Date.now()}`,
      isAutoSaved: false,
      fallbackTitle,
    });
    const newSessions = [
      archivedSession,
      ...loadSavedSessions().filter((session) => session.id !== archivedSession.id),
    ];
    persistSessions(newSessions);
    persistCurrentSession(
      createSessionSnapshot(clientId, currentMessages, {
        isAutoSaved: true,
        fallbackTitle,
      }),
    );
    saveSessions([
      archivedSession,
      ...getDisplaySessions(clientId, currentMessages, { fallbackTitle }).filter((session) => session.id !== archivedSession.id),
    ]);
    setSelectedSession(archivedSession.id);
  };

  const loadSession = (session: ChatSession) => {
    if (session.isAutoSaved) {
      persistCurrentSession(session);
    }
    onLoadSession(session.messages);
    setSelectedSession(session.id);
    onClose();
  };

  const deleteSession = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const targetSession = sessions.find((session) => session.id === sessionId);
    const archivedSessions = loadSavedSessions().filter((session) => session.id !== sessionId);
    persistSessions(archivedSessions);

    if (targetSession?.isAutoSaved) {
      onClearCurrentSession();
    }

    const currentSession = loadCurrentSession();
    const visibleSessions = [
      ...(currentSession ? [currentSession] : []),
      ...archivedSessions,
    ].filter((session) => session.id !== sessionId);
    const newSessions = visibleSessions.filter(
      (session, index, list) => list.findIndex((item) => item.id === session.id) === index,
    );
    saveSessions(newSessions);

    if (selectedSession === sessionId) {
      setSelectedSession(null);
    }
  };

  const clearAllHistory = () => {
    persistSessions([]);
    onClearCurrentSession();
    saveSessions([]);
    setSelectedSession(null);
    setConfirmClearAll(false);
  };

  const getSessionDisplayTitle = (session: ChatSession) => {
    const storedTitle = session.title.trim();
    const derivedTitle = buildChatTitleWithFallback(session.messages, fallbackTitle);
    const hasUserTitle = session.messages.some((message) => message.type === 'user' && message.content.trim());

    if (hasUserTitle) {
      return derivedTitle;
    }

    if (!storedTitle || fallbackTitleAliases.has(storedTitle)) {
      return fallbackTitle;
    }

    return storedTitle;
  };

  const filteredAndSortedSessions = sessions
    .filter((session) =>
      getSessionDisplayTitle(session).toLowerCase().includes(searchTerm.toLowerCase())
      || session.messages.some((msg) => msg.content.toLowerCase().includes(searchTerm.toLowerCase())),
    )
    .sort((a, b) => {
      if (sortBy === 'time') {
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      }
      return b.messageCount - a.messageCount;
    });

  const currentSession = filteredAndSortedSessions.find((session) => session.isAutoSaved) ?? null;
  const archivedSessions = filteredAndSortedSessions.filter((session) => !session.isAutoSaved);
  const hasSessions = Boolean(currentSession) || archivedSessions.length > 0;

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

    if (diffInMinutes < 60) {
      return t('chatHistory.minAgo', { count: Math.max(diffInMinutes, 1) });
    }
    if (diffInMinutes < 1440) {
      return t('chatHistory.hrAgo', { count: Math.floor(diffInMinutes / 60) });
    }
    return date.toLocaleDateString(language === 'en' ? 'en-US' : 'zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const currentSectionLabel = language === 'zh' ? '\u5f53\u524d\u4f1a\u8bdd' : 'Current session';
  const currentSectionHint = language === 'zh'
    ? '\u8fd9\u662f\u6b63\u5728\u4f7f\u7528\u7684\u81ea\u52a8\u4fdd\u5b58\u4f1a\u8bdd\u3002'
    : 'This is the autosaved session currently active in the workspace.';
  const archivedSectionLabel = language === 'zh' ? '\u5df2\u5f52\u6863\u4f1a\u8bdd' : 'Archived sessions';
  const archivedSectionHint = language === 'zh'
    ? '\u8fd9\u4e9b\u662f\u5df2\u4fdd\u5b58\u6216\u65b0\u804a\u5929\u65f6\u5f52\u6863\u7684\u5386\u53f2\u4f1a\u8bdd\u3002'
    : 'These are saved conversations archived from earlier chats.';
  const noCurrentSessionLabel = language === 'zh' ? '\u5f53\u524d\u6ca1\u6709\u81ea\u52a8\u4fdd\u5b58\u7684\u4f1a\u8bdd\u3002' : 'No current autosaved session.';
  const noArchivedSessionsLabel = language === 'zh' ? '\u8fd8\u6ca1\u6709\u5df2\u5f52\u6863\u7684\u4f1a\u8bdd\u3002' : 'No archived sessions yet.';

  const renderSessionCard = (session: ChatSession) => {
    const userMessages = session.messages.filter((msg) => msg.type === 'user').length;
    const aiMessages = session.messages.filter((msg) => msg.type === 'assistant').length;
    const displayTitle = getSessionDisplayTitle(session);

    return (
      <div
        key={session.id}
        onClick={() => loadSession(session)}
        className={`group cursor-pointer rounded-3xl border p-5 transition ${selectedSession === session.id ? 'border-sky-300 bg-sky-50/70 dark:border-sky-700/50 dark:bg-sky-950/20' : 'border-slate-200 bg-white/80 hover:border-sky-200 hover:bg-white dark:border-slate-700 dark:bg-slate-900/60 dark:hover:border-sky-700/40'}`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-r from-sky-500 to-violet-600 text-white shadow-sm">
                <MessageSquare className="h-4 w-4" />
              </div>
              <h4 className="truncate text-base font-semibold text-slate-900 dark:text-white">{displayTitle}</h4>
              {session.isAutoSaved && (
                <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                  {t('chatHistory.current')}
                </span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-1"><User className="h-3.5 w-3.5" /> {userMessages}</span>
              <span className="inline-flex items-center gap-1"><Bot className="h-3.5 w-3.5" /> {aiMessages}</span>
              <span className="inline-flex items-center gap-1"><Clock className="h-3.5 w-3.5" /> {formatTime(session.timestamp)}</span>
            </div>
            <div className="mt-3 line-clamp-2 text-sm text-slate-600 dark:text-slate-300">
              {session.messages.length > 0 ? session.messages[session.messages.length - 1].content : t('chatHistory.noMessageContent')}
            </div>
          </div>
          <button
            type="button"
            onClick={(event) => deleteSession(session.id, event)}
            className="rounded-2xl p-2 text-rose-500 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 dark:hover:bg-rose-900/20 dark:hover:text-rose-300"
            aria-label={t('chatHistory.deleteSession', { title: displayTitle })}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  };

  return (
    <>
      <AppModal
        isOpen={isOpen}
        onClose={onClose}
        title={t('chatHistory.title')}
        description={t('chatHistory.description')}
        maxWidthClassName="max-w-[1120px]"
        bodyClassName="p-0"
        closeOnBackdrop
        headerActions={(
          <button
            type="button"
            onClick={onClose}
            className="rounded-2xl border border-slate-200 bg-white/80 p-3 text-slate-500 transition hover:bg-white hover:text-slate-900 dark:border-slate-700 dark:bg-slate-800/80 dark:text-slate-300 dark:hover:text-white"
            aria-label={t('chatHistory.close')}
          >
            <X className="h-5 w-5" />
          </button>
        )}
      >
        <div className="grid min-h-[70vh] grid-cols-1 lg:grid-cols-[360px,1fr]">
          <div className="border-b border-slate-200/80 bg-slate-50/80 p-6 dark:border-slate-700/60 dark:bg-slate-950/35 lg:border-b-0 lg:border-r">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-r from-sky-500 to-emerald-500 text-white shadow-lg">
                <History className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">{t('chatHistory.sessions')}</h3>
                <div className="mt-1 flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1"><Sparkles className="h-4 w-4" /> {sessions.length}</span>
                  <span className="inline-flex items-center gap-1"><MessageSquare className="h-4 w-4" /> {sessions.reduce((total, session) => total + session.messageCount, 0)}</span>
                </div>
              </div>
            </div>

            <div className="mt-5 space-y-4">
              <div className="relative">
                <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder={t('chatHistory.searchPlaceholder')}
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  className="w-full rounded-2xl border border-slate-300 bg-white py-3 pl-11 pr-12 text-sm text-slate-900 outline-none transition focus:border-sky-400 dark:border-slate-700 dark:bg-slate-900/70 dark:text-white"
                />
                <button
                  type="button"
                  onClick={() => setShowFilters((prev) => !prev)}
                  className={`absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1.5 transition ${showFilters ? 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300' : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-200'}`}
                  aria-label={t('chatHistory.toggleSort')}
                >
                  <Filter className="h-4 w-4" />
                </button>
              </div>

              {showFilters && (
                <div className="rounded-2xl border border-slate-200 bg-white/90 p-4 dark:border-slate-700 dark:bg-slate-900/60">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{t('chatHistory.sortBy')}</span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setSortBy('time')}
                        className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${sortBy === 'time' ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}
                      >
                        {t('chatHistory.time')}
                      </button>
                      <button
                        type="button"
                        onClick={() => setSortBy('messages')}
                        className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${sortBy === 'messages' ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}
                      >
                        {t('chatHistory.messages')}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={saveCurrentSession}
                  disabled={currentMessages.length === 0}
                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-100"
                >
                  <Save className="h-4 w-4" />
                  <span>{t('chatHistory.archiveCurrent')}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmClearAll(true)}
                  disabled={sessions.length === 0}
                  className="inline-flex items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300"
                  aria-label={t('chatHistory.clearAllHistory')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <div className="flex flex-col p-6">
            {!hasSessions ? (
              <div className="flex flex-1 flex-col items-center justify-center text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
                  <MessageSquare className="h-8 w-8" />
                </div>
                <h3 className="mt-5 text-lg font-semibold text-slate-800 dark:text-white">
                  {searchTerm ? t('chatHistory.noMatchingSession') : t('chatHistory.noSavedSessionsYet')}
                </h3>
                <p className="mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400">
                  {searchTerm ? t('chatHistory.tryDifferentSearch') : t('chatHistory.startConversationHint')}
                </p>
              </div>
            ) : (
              <div className="space-y-6 overflow-y-auto pr-1">
                <section className="rounded-[28px] border border-sky-200/80 bg-sky-50/60 p-5 dark:border-sky-900/40 dark:bg-sky-950/15">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-700 dark:text-sky-300">
                        {currentSectionLabel}
                      </h3>
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{currentSectionHint}</p>
                    </div>
                    <span className="rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-sky-700 shadow-sm dark:bg-slate-900/70 dark:text-sky-300">
                      {currentSession ? 1 : 0}
                    </span>
                  </div>

                  <div className="mt-4">
                    {currentSession ? (
                      renderSessionCard(currentSession)
                    ) : (
                      <div className="rounded-3xl border border-dashed border-sky-200 bg-white/70 px-4 py-5 text-sm text-slate-500 dark:border-sky-900/40 dark:bg-slate-900/40 dark:text-slate-400">
                        {noCurrentSessionLabel}
                      </div>
                    )}
                  </div>
                </section>

                <section className="rounded-[28px] border border-slate-200/80 bg-white/75 p-5 dark:border-slate-700/70 dark:bg-slate-900/55">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-700 dark:text-slate-200">
                        {archivedSectionLabel}
                      </h3>
                      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{archivedSectionHint}</p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                      {archivedSessions.length}
                    </span>
                  </div>

                  <div className="mt-4 space-y-4">
                    {archivedSessions.length > 0 ? (
                      archivedSessions.map((session) => renderSessionCard(session))
                    ) : (
                      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/35 dark:text-slate-400">
                        {noArchivedSessionsLabel}
                      </div>
                    )}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>
      </AppModal>

      <AppModal
        isOpen={confirmClearAll}
        onClose={() => setConfirmClearAll(false)}
        title={t('chatHistory.clearAllTitle')}
        description={t('chatHistory.clearAllDescription')}
        maxWidthClassName="max-w-lg"
        bodyClassName="p-6"
      >
        <div className="space-y-5">
          <NoticeBanner tone="warning" message={t('chatHistory.clearAllWarning')} />
          <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-200">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4" />
              <span>{t('chatHistory.clearAllDetail')}</span>
            </div>
          </div>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setConfirmClearAll(false)}
              className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {t('chatHistory.cancel')}
            </button>
            <button
              type="button"
              onClick={clearAllHistory}
              className="rounded-2xl bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-rose-700"
            >
              {t('chatHistory.clearAll')}
            </button>
          </div>
        </div>
      </AppModal>
    </>
  );
};

export default ChatHistory;
