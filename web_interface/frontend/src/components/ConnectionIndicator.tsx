import React from 'react';
import { AlertCircle, CheckCircle, Loader2, WifiOff } from 'lucide-react';
import { ConnectionStatus } from '../types';
import { useI18n } from '../i18n/I18nProvider';

interface ConnectionIndicatorProps {
  status: ConnectionStatus['status'];
}

const ConnectionIndicator: React.FC<ConnectionIndicatorProps> = ({ status }) => {
  const { t } = useI18n();
  const config = (() => {
    switch (status) {
      case 'connected':
        return {
          icon: <CheckCircle className="h-4 w-4" />,
          text: t('connection.realtimeConnected'),
          textColor: 'text-green-700 dark:text-green-300',
          dotColor: 'bg-green-500',
          pulse: false,
        };
      case 'connecting':
        return {
          icon: <Loader2 className="h-4 w-4 animate-spin" />,
          text: t('connection.connecting'),
          textColor: 'text-yellow-700 dark:text-yellow-300',
          dotColor: 'bg-yellow-500',
          pulse: true,
        };
      case 'error':
        return {
          icon: <AlertCircle className="h-4 w-4" />,
          text: t('connection.connectionError'),
          textColor: 'text-red-700 dark:text-red-300',
          dotColor: 'bg-red-500',
          pulse: false,
        };
      case 'disconnected':
      default:
        return {
          icon: <WifiOff className="h-4 w-4" />,
          text: t('connection.disconnected'),
          textColor: 'text-gray-700 dark:text-gray-300',
          dotColor: 'bg-gray-400',
          pulse: false,
        };
    }
  })();

  return (
    <div className="flex items-center space-x-3 rounded-2xl border border-white/30 bg-white/70 px-4 py-2 backdrop-blur-md dark:border-gray-700/40 dark:bg-gray-800/70">
      <div className="relative">
        <div className={`h-3 w-3 rounded-full ${config.dotColor} ${config.pulse ? 'animate-pulse' : ''}`} />
        {config.pulse && (
          <div className={`absolute inset-0 h-3 w-3 rounded-full ${config.dotColor} animate-ping opacity-75`} />
        )}
      </div>
      <div className={`flex items-center space-x-2 text-sm font-medium ${config.textColor}`}>
        {config.icon}
        <span>{config.text}</span>
      </div>
    </div>
  );
};

export default ConnectionIndicator;
