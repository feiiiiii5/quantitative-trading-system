import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  {
    to: '/',
    label: '行情',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
      </svg>
    ),
  },
  {
    to: '/market',
    label: '股票',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3 3v18h18" />
        <path d="M7 16l4-6 4 4 5-8" />
      </svg>
    ),
  },
  {
    to: '/strategy',
    label: '策略',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v4m0 14v4m-9-11h4m14 0h4m-3.3-6.7l-2.8 2.8m-8.5 8.5l-2.8 2.8m0-14.1l2.8 2.8m8.5 8.5l2.8 2.8" />
      </svg>
    ),
  },
  {
    to: '/about',
    label: '关于',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4m0-4h.01" />
      </svg>
    ),
  },
];

export function Sidebar() {
  const [expanded, setExpanded] = useState(false);
  const [time, setTime] = useState('');

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      setTime(`${hh}:${mm}:${ss}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <nav
      style={{
        width: expanded ? 'var(--sidebar-expanded)' : 'var(--sidebar-w)',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: expanded ? 'flex-start' : 'center',
        borderRight: '1px solid rgba(255,255,255,0.04)',
        backdropFilter: 'blur(24px) saturate(120%)',
        WebkitBackdropFilter: 'blur(24px) saturate(120%)',
        background: 'rgba(5,5,5,0.82)',
        transition: 'width var(--dur-normal) var(--ease-out)',
        overflow: 'hidden',
        flexShrink: 0,
        position: 'relative',
        zIndex: 10,
      }}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      <div
        style={{
          height: 'var(--topbar-h)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: expanded ? 'flex-start' : 'center',
          padding: expanded ? '0 var(--u4)' : '0',
          width: '100%',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          whiteSpace: 'nowrap',
          gap: 'var(--u3)',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: '28px',
            fontWeight: 600,
            color: 'var(--accent)',
            lineHeight: 1,
            minWidth: '18px',
            textAlign: 'center',
            letterSpacing: '-0.02em',
          }}
        >
          Q
        </span>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: '18px',
            fontWeight: 500,
            color: 'var(--text-secondary)',
            letterSpacing: '0.02em',
            opacity: expanded ? 1 : 0,
            transition: 'opacity var(--dur-normal) var(--ease-out)',
          }}
        >
          QuantCore
        </span>
      </div>

      <div style={{ flex: 1, width: '100%', paddingTop: 'var(--u2)' }}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              height: '40px',
              padding: expanded ? '0 var(--u4)' : '0',
              justifyContent: expanded ? 'flex-start' : 'center',
              gap: 'var(--u3)',
              textDecoration: 'none',
              color: isActive ? 'var(--accent)' : 'var(--text-tertiary)',
              background: isActive ? 'var(--accent-muted)' : 'transparent',
              borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'all var(--dur-normal) var(--ease-out)',
              position: 'relative',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            })}
            onMouseEnter={(e) => {
              if (!e.currentTarget.classList.contains('active')) {
                e.currentTarget.style.background = 'rgba(255,255,255,0.02)';
              }
            }}
            onMouseLeave={(e) => {
              if (!e.currentTarget.classList.contains('active')) {
                e.currentTarget.style.background = 'transparent';
              }
            }}
          >
            <span style={{ display: 'flex', flexShrink: 0, alignItems: 'center' }}>{item.icon}</span>
            {expanded && (
              <span
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--fs-sm)',
                  fontWeight: 500,
                }}
              >
                {item.label}
              </span>
            )}
          </NavLink>
        ))}
      </div>

      <div
        style={{
          height: 'var(--topbar-h)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--fs-xs)',
          color: 'var(--text-muted)',
          borderTop: '1px solid rgba(255,255,255,0.04)',
          fontVariantNumeric: 'tabular-nums',
          letterSpacing: '0.04em',
        }}
      >
        {time}
      </div>
    </nav>
  );
}
