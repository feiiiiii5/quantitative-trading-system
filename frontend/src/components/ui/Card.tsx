import { memo, useState, useCallback, type ReactNode, type CSSProperties } from 'react';

interface CardProps {
  children: ReactNode;
  padding?: string;
  blur?: boolean;
  hover?: boolean;
  onClick?: () => void;
  style?: CSSProperties;
}

const baseStyle: CSSProperties = {
  background: 'var(--bg-glass)',
  borderRadius: 'var(--r-lg)',
  border: '1px solid var(--separator)',
  boxShadow: 'var(--shadow-md)',
  transition: 'transform var(--dur-fast) var(--ease-apple), box-shadow var(--dur-fast) var(--ease-apple)',
};

export const Card = memo(function Card({ children, padding, blur = true, hover = false, onClick, style }: CardProps) {
  const [hovered, setHovered] = useState(false);

  const handleMouseEnter = useCallback(() => {
    if (hover) setHovered(true);
  }, [hover]);

  const handleMouseLeave = useCallback(() => {
    if (hover) setHovered(false);
  }, [hover]);

  const mergedStyle: CSSProperties = {
    ...baseStyle,
    ...(blur ? { backdropFilter: 'blur(20px) saturate(180%)', WebkitBackdropFilter: 'blur(20px) saturate(180%)' } : {}),
    ...(padding ? { padding } : {}),
    ...(hover && hovered
      ? { transform: 'scale(1.005)', boxShadow: 'var(--shadow-lg)' }
      : {}),
    ...(onClick ? { cursor: 'pointer' } : {}),
    ...style,
  };

  return (
    <div
      style={mergedStyle}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
    >
      {children}
    </div>
  );
});
