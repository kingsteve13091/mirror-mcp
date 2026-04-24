import { useCallback, useEffect, useState } from 'react';
import { getSystemBootstrap } from '../services/api';
import { SystemBootstrap } from '../types';

export const useSystemBootstrap = () => {
  const [bootstrap, setBootstrap] = useState<SystemBootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const snapshot = await getSystemBootstrap();
      setBootstrap(snapshot);
      return {
        ok: true as const,
        snapshot,
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      return {
        ok: false as const,
        error: message,
      };
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    bootstrap,
    loading,
    error,
    refresh,
  };
};
