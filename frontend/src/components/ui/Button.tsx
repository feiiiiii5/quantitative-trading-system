import { memo, useState, useCallback, type ReactNode, type CSSProperties } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost';

interface ButtonProps {
  variant?: ButtonVariant;
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  style?: CSSProperties;
  fullWidth?: boolean;
}

const VARIANT_BASE: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: 'var(--accent)',
    color: '#ffffff',
    border: 'none',
  },
  secondary: {
    background: 'var(--bg-overlay)',
    color: 'var(--label-primary)',
    border: '1px solid var(--separator)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--label-secondary)',
    border: 'none',
  },
};

export const Button = memo(function Button({
  variant = 'primary',
  children,
  onClick,
  disabled = false,
  style,
  fullWidth = false,
}: ButtonProps) {
  const [pressed, setPressed] = useState(false);
  const [ghostHovered, setGhostHovered] = useState(false);

  const handleMouseDown = useCallback(() => setPressed(true), []);
  const handleMouseUp = useCallback(() => setPressed(false), []);
  const handleMouseLeave = useCallback(() => {
    setPressed(false);
    setGhostHovered(false);
  }, []);
  const handleGhostEnter = useCallback(() => setGhostHovered(true), []);

  const variantStyle = VARIANT_BASE[variant];

  const mergedStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '40px',
    padding: '0 var(--s5)',
    borderRadius: 'var(--r-md)',
    fontFamily: 'var(--font-sans)',
    fontSize: '14px',
    fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
    transition: 'transform var(--dur-fast) var(--ease-apple), background var(--dur-fast) var(--ease-apple), box-shadow var(--dur-fast) var(--ease-apple)',
    ...(fullWidth ? { width: '100%' } : {}),
    ...variantStyle,
    ...(variant === 'ghost' && ghostHovered ? { background: 'var(--bg-overlay)' } : {}),
    ...(pressed && !disabled ? { transform: 'scale(0.98)' } : {}),
    ...style,
  };

  return (
    <button
      style={mergedStyle}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onMouseEnter={variant === 'ghost' ? handleGhostEnter : undefined}
    >
      {children}
    </button>
  );
});
