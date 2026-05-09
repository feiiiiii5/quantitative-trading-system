import { create } from 'zustand';

interface AIState {
  query: string;
  response: string;
  isStreaming: boolean;
  history: Array<{ role: 'user' | 'assistant'; content: string }>;

  setQuery: (query: string) => void;
  appendResponse: (token: string) => void;
  startStreaming: () => void;
  stopStreaming: () => void;
  submitQuery: (query: string) => void;
  clearHistory: () => void;
}

export const useAIStore = create<AIState>((set) => ({
  query: '',
  response: '',
  isStreaming: false,
  history: [],

  setQuery: (query) => set({ query }),

  appendResponse: (token) =>
    set((state) => ({ response: state.response + token })),

  startStreaming: () => set({ isStreaming: true, response: '' }),

  stopStreaming: () =>
    set((state) => ({
      isStreaming: false,
      history: [
        ...state.history,
        { role: 'assistant' as const, content: state.response },
      ],
    })),

  submitQuery: (query) =>
    set((state) => ({
      query: '',
      history: [...state.history, { role: 'user' as const, content: query }],
      response: '',
      isStreaming: true,
    })),

  clearHistory: () => set({ history: [], response: '' }),
}));
