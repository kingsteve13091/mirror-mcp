const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, '');

const getApiBaseUrl = (): string => {
  const envBase = (process.env.REACT_APP_API_BASE_URL || '').trim();
  if (envBase) {
    return trimTrailingSlash(envBase);
  }

  if (process.env.NODE_ENV === 'development') {
    const port = (process.env.REACT_APP_BACKEND_PORT || '8000').trim();
    return `http://${window.location.hostname}:${port}`;
  }

  return '';
};

const getWsBaseUrl = (apiBaseUrl: string): string => {
  const envWs = (process.env.REACT_APP_WS_BASE_URL || '').trim();
  if (envWs) {
    return trimTrailingSlash(envWs);
  }

  if (apiBaseUrl) {
    return apiBaseUrl.replace(/^http/i, 'ws');
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
};

export const API_BASE_URL = getApiBaseUrl();
export const WS_BASE_URL = getWsBaseUrl(API_BASE_URL);

export const buildApiUrl = (path: string): string => {
  if (!path.startsWith('/')) {
    return path;
  }

  if (!API_BASE_URL) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
};
