import { memo, useState, useCallback, type CSSProperties } from 'react';

interface InputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  style?: CSSProperties;
  type?: string;
}

export const Input = memo(function Input({ value, onChange, placeholder, style, type = 'text' }: InputProps) {
  const [focused, setFocused] = useState(false);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.value),
    [onChange],
  );

  const handleFocus = useCallback(() => setFocused(true), []);
  const handleBlur = useCallback(() => setFocused(false), []);

  return (
    <input
      type={type}
      value={value}
      onChange={handleChange}
      onFocus={handleFocus}
      onBlur={handleBlur}
      placeholder={placeholder}
      style={{
        width: '100%',
        height: '40px',
        padding: '0 var(--s4)',
        fontFamily: 'var(--font-mono)',
        fontSize: '13px',
        color: 'var(--label-primary)',
        background: 'var(--bg-overlay)',
        border: `1px solid ${focused ? 'var(--accent)' : 'var(--separator)'}`,
        borderRadius: 'var(--r-md)',
        outline: 'none',
        boxShadow: focused ? '0 0 0 3px var(--accent-soft)' : 'none',
        transition: 'border-color var(--dur-fast) var(--ease-apple), box-shadow var(--dur-fast) var(--ease-apple)',
        ...style,
      }}
    />
  );
});
