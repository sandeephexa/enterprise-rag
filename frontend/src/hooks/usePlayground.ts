import { useCallback, useEffect, useReducer, useRef } from 'react';
import { ApiClient, errorMessage } from '../api/client';
import type { Answer } from '../api/schemas';

export type Run = { id: string; question: string; started: string;
  status: 'pending' | 'complete' | 'error' | 'cancelled'; answer?: Answer; error?: string };
export type RunState = { runs: Run[]; selectedId: string | null };
export type RunAction = { type: 'start'; run: Run } | { type: 'success'; id: string; answer: Answer }
  | { type: 'error'; id: string; error: string } | { type: 'cancel'; id: string }
  | { type: 'select'; id: string } | { type: 'clear' };

export function runReducer(state: RunState, action: RunAction): RunState {
  if (action.type === 'clear') return { runs: [], selectedId: null };
  if (action.type === 'select') return { ...state, selectedId: action.id };
  if (action.type === 'start') return { runs: [...state.runs.slice(-29), action.run], selectedId: action.run.id };
  return { ...state, runs: state.runs.map(run => {
    if (run.id !== action.id || run.status !== 'pending') return run;
    if (action.type === 'success') return { ...run, status: 'complete', answer: action.answer };
    if (action.type === 'error') return { ...run, status: 'error', error: action.error };
    return { ...run, status: 'cancelled' };
  }) };
}

/** Independent query runs, not a conversational API; at most 30 are kept in memory. */
export function usePlayground(api: ApiClient) {
  const [state, dispatch] = useReducer(runReducer, { runs: [], selectedId: null });
  const active = useRef<{ id: string; controller: AbortController } | null>(null);
  useEffect(() => () => active.current?.controller.abort(), []);
  const cancel = useCallback(() => {
    if (active.current) { active.current.controller.abort(); dispatch({ type: 'cancel', id: active.current.id }); active.current = null; }
  }, []);
  const submit = async (question: string) => {
    if (active.current || question.trim().length < 3 || question.length > 2000) return;
    const id = crypto.randomUUID();
    const controller = new AbortController(); active.current = { id, controller };
    dispatch({ type: 'start', run: { id, question: question.trim(), started: new Date().toISOString(), status: 'pending' } });
    try {
      const answer = await api.query(question.trim(), controller.signal);
      if (!controller.signal.aborted) dispatch({ type: 'success', id, answer });
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'error', id, error: errorMessage(error) });
    } finally { if (active.current?.id === id) active.current = null; }
  };
  return { ...state, submit, cancel, busy: state.runs.some(run => run.status === 'pending'),
    select: (id: string) => dispatch({ type: 'select', id }),
    clear: () => { cancel(); dispatch({ type: 'clear' }); } };
}
