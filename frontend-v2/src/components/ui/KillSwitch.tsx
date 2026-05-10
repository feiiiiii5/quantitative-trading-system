import { useState, useCallback } from 'react';
import { useRiskStore } from '@/stores/risk';

export function KillSwitch() {
  const { killSwitchActive, triggerKillSwitch, resetKillSwitch } = useRiskStore();
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const handleActivate = useCallback(() => {
    if (confirmText === 'CONFIRM') {
      triggerKillSwitch();
      setConfirming(false);
      setConfirmText('');
    }
  }, [confirmText, triggerKillSwitch]);

  if (killSwitchActive) {
    return (
      <div style={{
        position: 'fixed', inset: 0, zIndex: 10000,
        background: 'rgba(212, 88, 74, 0.08)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: '16px',
      }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: '48px', color: '#D4584A', fontWeight: 600 }}>
          KILL SWITCH ACTIVE
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
          All trading operations suspended
        </div>
        <button
          onClick={resetKillSwitch}
          style={{
            marginTop: '16px', padding: '8px 24px',
            background: 'var(--bg-raised)', color: 'var(--text-primary)',
            border: '1px solid var(--border-mid)', borderRadius: '6px',
            fontFamily: 'var(--font-mono)', fontSize: '12px', cursor: 'pointer',
          }}
        >
          DEACTIVATE
        </button>
      </div>
    );
  }

  if (confirming) {
    return (
      <div style={{
        padding: '12px 16px', background: 'rgba(212, 88, 74, 0.06)',
        border: '1px solid rgba(212, 88, 74, 0.2)', borderRadius: '6px',
        display: 'flex', alignItems: 'center', gap: '8px',
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#D4584A' }}>
          TYPE "CONFIRM":
        </span>
        <input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleActivate(); if (e.key === 'Escape') setConfirming(false); }}
          autoFocus
          style={{ width: '100px', height: '28px', background: 'var(--bg-void)', borderColor: 'rgba(212,88,74,0.3)' }}
        />
        <button onClick={handleActivate} style={{
          padding: '4px 12px', background: '#D4584A', color: '#000',
          border: 'none', borderRadius: '4px', fontFamily: 'var(--font-mono)',
          fontSize: '10px', fontWeight: 600, cursor: 'pointer',
        }}>
          EXECUTE
        </button>
        <button onClick={() => { setConfirming(false); setConfirmText(''); }} style={{
          padding: '4px 8px', background: 'transparent', color: 'var(--text-tertiary)',
          border: '1px solid var(--border-dim)', borderRadius: '4px',
          fontFamily: 'var(--font-mono)', fontSize: '10px', cursor: 'pointer',
        }}>
          CANCEL
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      style={{
        padding: '4px 12px', background: 'rgba(212, 88, 74, 0.08)',
        color: '#D4584A', border: '1px solid rgba(212, 88, 74, 0.2)',
        borderRadius: '4px', fontFamily: 'var(--font-mono)', fontSize: '10px',
        fontWeight: 600, letterSpacing: '0.06em', cursor: 'pointer',
        transition: 'background 160ms ease-out',
      }}
    >
      KILL SWITCH
    </button>
  );
}
