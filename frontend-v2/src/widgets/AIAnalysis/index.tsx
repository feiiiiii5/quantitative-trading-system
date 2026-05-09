import { useRef, useEffect, useCallback } from 'react';
import { Panel, WidgetErrorBoundary, Button } from '@/shared/ui';
import { useAIStore } from '@/features/ai-panel';
import ReactMarkdown from 'react-markdown';

const QUICK_ACTIONS = [
  'Analyze current risk exposure',
  'Suggest parameter adjustments',
  'Explain today\'s drawdown',
];

export function AIAnalysis() {
  const query = useAIStore((s) => s.query);
  const response = useAIStore((s) => s.response);
  const isStreaming = useAIStore((s) => s.isStreaming);
  const setQuery = useAIStore((s) => s.setQuery);
  const submitQuery = useAIStore((s) => s.submitQuery);
  const responseRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (responseRef.current) {
      responseRef.current.scrollTop = responseRef.current.scrollHeight;
    }
  }, [response]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      submitQuery(query.trim());
    }
  }, [query, submitQuery]);

  const handleQuickAction = useCallback((action: string) => {
    submitQuery(action);
  }, [submitQuery]);

  return (
    <WidgetErrorBoundary>
      <Panel title="AI Analysis" accent="accent">
        <div className="flex flex-col h-full">
          <div ref={responseRef} className="flex-1 overflow-y-auto p-[var(--space-2)] text-[var(--font-size-sm)]">
            {response ? (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{response}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-[var(--text-muted)] text-center py-[var(--space-4)]">
                Ask the AI about market conditions...
              </div>
            )}
            {isStreaming && <span className="inline-block w-1.5 h-3 bg-[var(--text-accent)] animate-pulse ml-0.5" />}
          </div>

          <div className="flex flex-wrap gap-1 px-[var(--space-2)] py-[var(--space-1)] border-t border-[var(--bg-border)]">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action}
                onClick={() => handleQuickAction(action)}
                className="px-2 py-0.5 text-[var(--font-size-xs)] text-[var(--text-accent)] bg-[var(--text-accent)]/10 rounded-[var(--radius-sm)] hover:bg-[var(--text-accent)]/20 transition-colors"
              >
                {action}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="flex gap-[var(--space-1)] p-[var(--space-2)] border-t border-[var(--bg-border)]">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask the AI..."
              disabled={isStreaming}
              className="flex-1 h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)] disabled:opacity-50"
            />
            <Button type="submit" size="sm" disabled={isStreaming || !query.trim()}>
              Send
            </Button>
          </form>
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
}
