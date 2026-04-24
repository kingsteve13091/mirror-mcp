import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import ConnectionIndicator from './ConnectionIndicator';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import { ChatSettings } from '../types';

const ConnectionIndicatorHarness = () => {
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
        <ConnectionIndicator status="connected" />
        <ConnectionIndicator status="connecting" />
        <ConnectionIndicator status="error" />
        <ConnectionIndicator status="disconnected" />
      </div>
    </I18nProvider>
  );
};

describe('ConnectionIndicator i18n regression', () => {
  it('switches all realtime status labels with language', async () => {
    const user = userEvent.setup();
    render(<ConnectionIndicatorHarness />);

    expect(screen.getByText('实时连接已建立')).toBeInTheDocument();
    expect(screen.getByText('连接中')).toBeInTheDocument();
    expect(screen.getByText('连接错误')).toBeInTheDocument();
    expect(screen.getByText('未连接')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'English' }));

    expect(screen.getByText('Realtime connected')).toBeInTheDocument();
    expect(screen.getByText('Connecting')).toBeInTheDocument();
    expect(screen.getByText('Connection error')).toBeInTheDocument();
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });
});
