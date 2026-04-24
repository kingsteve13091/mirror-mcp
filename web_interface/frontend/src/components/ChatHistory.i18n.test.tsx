import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import ChatHistory from './ChatHistory';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import { CHAT_CURRENT_SESSION_KEY, ChatSession } from '../utils/chatSessionStorage';
import { ChatMessage, ChatSettings } from '../types';

const CLIENT_ID = 'client-i18n';

const CURRENT_MESSAGES: ChatMessage[] = [
  {
    id: 'system-1',
    type: 'system',
    content: 'system seeded message',
    timestamp: '2026-04-13T11:59:00.000Z',
  },
];

const PERSISTED_SESSION: ChatSession = {
  id: `session-${CLIENT_ID}`,
  title: '新对话',
  messages: [
    {
      id: 'system-2',
      type: 'system',
      content: 'persisted system message',
      timestamp: '2026-04-13T11:59:00.000Z',
    },
  ],
  timestamp: '2026-04-13T11:59:00.000Z',
  messageCount: 1,
  clientId: CLIENT_ID,
  isAutoSaved: true,
};

const ChatHistoryHarness = ({
  currentMessages,
}: {
  currentMessages: ChatMessage[];
}) => {
  const [settings, setSettings] = useState<ChatSettings>({
    ...DEFAULT_CHAT_SETTINGS,
    language: 'zh',
  });

  return (
    <I18nProvider settings={settings}>
      <div>
        <button type="button" onClick={() => setSettings((prev) => ({ ...prev, language: 'zh' }))}>
          中文
        </button>
        <button type="button" onClick={() => setSettings((prev) => ({ ...prev, language: 'en' }))}>
          English
        </button>
        <ChatHistory
          isOpen
          clientId={CLIENT_ID}
          onClose={jest.fn()}
          onLoadSession={jest.fn()}
          currentMessages={currentMessages}
          onClearCurrentSession={jest.fn()}
        />
      </div>
    </I18nProvider>
  );
};

describe('ChatHistory i18n regression', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-04-13T12:00:00.000Z'));
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('switches default fallback session title with language', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    render(<ChatHistoryHarness currentMessages={CURRENT_MESSAGES} />);

    expect(screen.getByText('新对话')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'English' }));

    await waitFor(() => {
      expect(screen.getByText('New conversation')).toBeInTheDocument();
    });
    expect(screen.queryByText('新对话')).not.toBeInTheDocument();
  });

  it('switches relative time formatting for persisted sessions with language', async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    window.localStorage.setItem(CHAT_CURRENT_SESSION_KEY, JSON.stringify(PERSISTED_SESSION));

    render(<ChatHistoryHarness currentMessages={[]} />);

    expect(screen.getByText('1 分钟前')).toBeInTheDocument();
    expect(screen.getByText('新对话')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'English' }));

    await waitFor(() => {
      expect(screen.getByText('1 min ago')).toBeInTheDocument();
    });
    expect(screen.getByText('New conversation')).toBeInTheDocument();
    expect(screen.queryByText('1 分钟前')).not.toBeInTheDocument();
  });
});
