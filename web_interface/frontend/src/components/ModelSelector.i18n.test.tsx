import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import ModelSelector from './ModelSelector';
import { I18nProvider } from '../i18n/I18nProvider';
import { DEFAULT_CHAT_SETTINGS } from '../utils/settingsStorage';
import { AIModel, ChatSettings } from '../types';

const models: AIModel[] = [
  {
    id: 'gemma-test',
    name: 'Gemma Test',
    description: 'Model used for i18n regression coverage',
    type: 'text',
    max_tokens: 8192,
    provider: 'openrouter',
  },
  {
    id: 'vision-test',
    name: 'Vision Test',
    description: 'Multimodal model for the selector panel',
    type: 'multimodal',
    max_tokens: 4096,
    provider: 'siliconflow',
  },
];

const ModelSelectorHarness = () => {
  const [settings, setSettings] = useState<ChatSettings>({
    ...DEFAULT_CHAT_SETTINGS,
    language: 'zh',
  });
  const [selectedModel, setSelectedModel] = useState('');

  return (
    <I18nProvider settings={settings}>
      <div>
        <button type="button" onClick={() => setSettings((prev) => ({ ...prev, language: 'zh' }))}>
          中文
        </button>
        <button type="button" onClick={() => setSettings((prev) => ({ ...prev, language: 'en' }))}>
          English
        </button>
        <ModelSelector
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          models={models}
        />
      </div>
    </I18nProvider>
  );
};

describe('ModelSelector i18n regression', () => {
  it('switches selector copy and catalog labels with language', async () => {
    const user = userEvent.setup();
    render(<ModelSelectorHarness />);

    expect(screen.getByText('选择模型')).toBeInTheDocument();
    expect(screen.getByText('选择一个可用模型')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /选择模型/i }));

    expect(screen.getByText('模型目录 (2)')).toBeInTheDocument();
    expect(screen.getByText('文本')).toBeInTheDocument();
    expect(screen.getByText(/8,192\s+token/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'English' }));

    await waitFor(() => {
      expect(screen.getByText('Select model')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Select model/i }));

    expect(screen.getByText('Model catalog (2)')).toBeInTheDocument();
    expect(screen.getByText('Text')).toBeInTheDocument();
    expect(screen.getByText(/8,192\s+tokens/)).toBeInTheDocument();
    expect(screen.getByText('Choose an available model')).toBeInTheDocument();
  });
});
