import { useState, useEffect, memo } from 'react';

interface ShortcutGroup {
  title: string;
  items: Array<{ keys: string; description: string }>;
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: '全局',
    items: [
      { keys: '⌘K', description: '打开命令面板' },
      { keys: '?', description: '显示快捷键帮助' },
      { keys: 'Esc', description: '关闭弹窗' },
    ],
  },
  {
    title: '导航',
    items: [
      { keys: '⌘1', description: 'Dashboard' },
      { keys: '⌘2', description: '市场行情' },
      { keys: '⌘3', description: '策略中心' },
      { keys: '⌘4', description: '风险管理' },
      { keys: '⌘5', description: '交易终端' },
    ],
  },
  {
    title: '列表操作',
    items: [
      { keys: '↑ ↓', description: '上下移动' },
      { keys: 'Enter', description: '确认选择' },
    ],
  },
];

export const KeyboardShortcuts = memo(function KeyboardShortcuts() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return;
        e.preventDefault();
        setOpen(prev => !prev);
      }
      if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  if (!open) return null;

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 10001, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(24px)', display: 'flex', justifyContent: 'center', alignItems: 'center' }}
      onClick={() => setOpen(false)}
    >
      <div
        style={{ width: 480, background: 'var(--bg-elevated)', border: '1px solid var(--separator)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ padding: '20px 24px 12px', borderBottom: '1px solid var(--separator)' }}>
          <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: 16, fontWeight: 600, color: 'var(--label-primary)', margin: 0 }}>键盘快捷键</h2>
        </div>
        <div style={{ padding: '12px 24px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {SHORTCUT_GROUPS.map(group => (
            <div key={group.title}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)', letterSpacing: '0.08em', marginBottom: 6 }}>{group.title}</div>
              {group.items.map(item => (
                <div key={item.keys} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                  <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--label-secondary)' }}>{item.description}</span>
                  <kbd style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-primary)', background: 'var(--bg-overlay)', border: '1px solid var(--separator)', padding: '2px 8px', borderRadius: 'var(--r-xs)', minWidth: 40, textAlign: 'center' }}>{item.keys}</kbd>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
