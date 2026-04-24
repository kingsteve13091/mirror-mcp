import { render, screen, within } from '@testing-library/react';
import ChatHistory from './ChatHistory';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import { CHAT_SESSIONS_KEY, ChatSession } from '../utils/chatSessionStorage';
import { ChatMessage } from '../types';

const CLIENT_ID = 'client-history-sections';

const currentMessages: ChatMessage[] = [
  {
    id: 'user-current',
    type: 'user',
    content: 'current session question',
    timestamp: '2026-04-21T09:00:00.000Z',
  },
  {
    id: 'assistant-current',
    type: 'assistant',
    content: 'current session answer',
    timestamp: '2026-04-21T09:01:00.000Z',
  },
];

const archivedSession: ChatSession = {
  id: 'archived-session-1',
  title: 'Archived project notes',
  messages: [
    {
      id: 'user-archived',
      type: 'user',
      content: 'archived session question',
      timestamp: '2026-04-20T09:00:00.000Z',
    },
    {
      id: 'assistant-archived',
      type: 'assistant',
      content: 'archived session answer',
      timestamp: '2026-04-20T09:01:00.000Z',
    },
  ],
  timestamp: '2026-04-20T09:01:00.000Z',
  messageCount: 2,
  clientId: CLIENT_ID,
  isAutoSaved: false,
};

const renderHistory = () => render(
  <I18nProvider settings={{ ...DEFAULT_CHAT_SETTINGS, language: 'en' }}>
    <ChatHistory
      isOpen
      clientId={CLIENT_ID}
      onClose={jest.fn()}
      onLoadSession={jest.fn()}
      currentMessages={currentMessages}
      onClearCurrentSession={jest.fn()}
    />
  </I18nProvider>,
);

describe('ChatHistory sections', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem(CHAT_SESSIONS_KEY, JSON.stringify([archivedSession]));
  });

  it('separates the current autosaved session from archived sessions', () => {
    renderHistory();

    const currentSection = screen.getByText('Current session').closest('section');
    const archivedSection = screen.getByText('Archived sessions').closest('section');

    expect(currentSection).toBeTruthy();
    expect(archivedSection).toBeTruthy();
    expect(within(currentSection as HTMLElement).getByText('current session answer')).toBeInTheDocument();
    expect(within(archivedSection as HTMLElement).getByText('archived session answer')).toBeInTheDocument();
    expect(within(currentSection as HTMLElement).queryByText('archived session answer')).not.toBeInTheDocument();
  });
});
