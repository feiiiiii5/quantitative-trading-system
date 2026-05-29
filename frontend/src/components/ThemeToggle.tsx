import { memo, useCallback } from 'react';
import { useTheme } from '@/hooks/useTheme';

export const ThemeToggle = memo(function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  const handleToggle = useCallback(() => {
    toggleTheme();
  }, [toggleTheme]);

  return (
    <button
      onClick={handleToggle}
      title={theme === 'dark' ? '切换亮色模式' : '切换暗色模式'}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 32,
        height: 32,
        borderRadius: 'var(--r-xs)',
        background: 'var(--accent-soft)',
        border: '1px solid var(--border-default)',
        cursor: 'pointer',
        transition: 'background 0.15s, border-color 0.15s',
        padding: 0,
        fontSize: 14,
        lineHeight: 1,
      }}
    >
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
});
