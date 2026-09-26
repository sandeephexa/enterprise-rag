import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../api/client';

/** Cancels obsolete work and prevents late results from replacing newer state. */
export function useRequest<T>() {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({ data: null, loading: false, error: null });
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const execute = useCallback(async (task: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> => {
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    setState(previous => ({ ...previous, loading: true, error: null }));
    try {
      const data = await task(controller.signal);
      if (!controller.signal.aborted) { setState({ data, loading: false, error: null }); return data; }
    } catch (error) {
      if (!controller.signal.aborted) setState(previous => ({ ...previous, loading: false, error: errorMessage(error) }));
    }
  }, []);
  return { ...state, execute };
}
