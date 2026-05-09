import { create } from 'zustand';
import type { BacktestJob, BacktestResult, BacktestConfig } from './types';

interface BacktestState {
  currentJob: BacktestJob | null;
  results: Map<string, BacktestResult>;
  config: Partial<BacktestConfig>;

  setCurrentJob: (job: BacktestJob | null) => void;
  updateJobProgress: (jobId: string, progress: number, currentDate: string) => void;
  setJobCompleted: (jobId: string, result: BacktestResult) => void;
  setJobFailed: (jobId: string) => void;
  setConfig: (config: Partial<BacktestConfig>) => void;
}

export const useBacktestStore = create<BacktestState>((set) => ({
  currentJob: null,
  results: new Map(),
  config: {},

  setCurrentJob: (job) => set({ currentJob: job }),

  updateJobProgress: (jobId, progress, currentDate) =>
    set((state) => {
      if (state.currentJob?.jobId === jobId) {
        return { currentJob: { ...state.currentJob, progress, currentDate } };
      }
      return state;
    }),

  setJobCompleted: (jobId, result) =>
    set((state) => {
      const results = new Map(state.results);
      results.set(jobId, result);
      return {
        currentJob: state.currentJob?.jobId === jobId
          ? { ...state.currentJob, status: 'completed', progress: 100, completedAt: Date.now() }
          : state.currentJob,
        results,
      };
    }),

  setJobFailed: (jobId) =>
    set((state) => {
      if (state.currentJob?.jobId === jobId) {
        return { currentJob: { ...state.currentJob, status: 'failed' } };
      }
      return state;
    }),

  setConfig: (config) =>
    set((state) => ({ config: { ...state.config, ...config } })),
}));
