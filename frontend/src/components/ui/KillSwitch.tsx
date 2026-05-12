import { memo, useState, useCallback } from 'react';
import { useRiskStore } from '@/stores/risk';
import { Input } from '@/components/ui/Input';

export const KillSwitch = memo(function KillSwitch() {
  const killSwitchActive = useRiskStore(s => s.killSwitchActive);
  const triggerKillSwitch = useRiskStore(s => s.triggerKillSwitch);
  const resetKillSwitch = useRiskStore(s => s.resetKillSwitch);
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const handleActivate = useCallback(() => {
    if (confirmText === 'CONFIRM') {
      triggerKillSwitch();
      setConfirming(false);
      setConfirmText('');
    }
  }, [confirmText, triggerKillSwitch]);

  const handleCancel = useCallback(() => {
    setConfirming(false);
    setConfirmText('');
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleActivate();
      if (e.key === 'Escape') handleCancel();
    },
    [handleActivate, handleCancel],
  );

  if (killSwitchActive) {
    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 10000,
          background: 'rgba(255,23,68,0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 'var(--s4)',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '48px',
            fontWeight: 700,
            color: 'var(--red)',
            letterSpacing: '0.04em',
          }}
        >
          KILL SWITCH ACTIVE
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            color: 'var(--label-secondary)',
          }}
        >
          All trading operations suspended
        </span>
        <button
          onClick={resetKillSwitch}
          style={{
            marginTop: 'var(--s4)',
            padding: '8px 24px',
            background: 'var(--bg-overlay)',
            color: 'var(--label-primary)',
            border: '1px solid var(--separator)',
            borderRadius: 'var(--r-md)',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            cursor: 'pointer',
            transition: 'background var(--dur-fast) var(--ease-apple)',
          }}
        >
          DEACTIVATE
        </button>
      </div>
    );
  }

  if (confirming) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--s2)',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--red)',
            letterSpacing: '0.04em',
          }}
        >
          TYPE "CONFIRM":
        </span>
        <div style={{ width: '120px' }} onKeyDown={handleKeyDown}>
          <Input
            value={confirmText}
            onChange={setConfirmText}
            style={{
              height: '28px',
              fontSize: '11px',
              borderColor: 'rgba(255,23,68,0.3)',
            }}
          />
        </div>
        <button
          onClick={handleActivate}
          style={{
            padding: '4px 12px',
            background: 'var(--red)',
            color: '#ffffff',
            border: 'none',
            borderRadius: 'var(--r-xs)',
            fontFamily: 'var(--font-mono)',
            fontSize: '10px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'opacity var(--dur-fast) var(--ease-apple)',
          }}
        >
          EXECUTE
        </button>
        <button
          onClick={handleCancel}
          style={{
            padding: '4px 8px',
            background: 'transparent',
            color: 'var(--label-tertiary)',
            border: '1px solid var(--separator)',
            borderRadius: 'var(--r-xs)',
            fontFamily: 'var(--font-mono)',
            fontSize: '10px',
            cursor: 'pointer',
            transition: 'color var(--dur-fast) var(--ease-apple)',
          }}
        >
          CANCEL
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      style={{
        padding: '4px 12px',
        background: 'var(--red-soft)',
        color: 'var(--red)',
        border: '1px solid rgba(255,23,68,0.2)',
        borderRadius: 'var(--r-xs)',
        fontFamily: 'var(--font-mono)',
        fontSize: '10px',
        fontWeight: 600,
        letterSpacing: '0.06em',
        cursor: 'pointer',
        transition: 'background var(--dur-fast) var(--ease-apple)',
      }}
    >
      KILL SWITCH
    </button>
  );
});
