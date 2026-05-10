import { useState, useEffect, useCallback, memo, type CSSProperties } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
}

const NAV_ITEMS: readonly NavItem[] = [
  {
    path: '/',
    label: 'Dashboard',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="2" width="6.5" height="6.5" rx="1.5" />
        <rect x="11.5" y="2" width="6.5" height="6.5" rx="1.5" />
        <rect x="2" y="11.5" width="6.5" height="6.5" rx="1.5" />
        <rect x="11.5" y="11.5" width="6.5" height="6.5" rx="1.5" />
      </svg>
    ),
  },
  {
    path: '/market',
    label: 'Market',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 18V2" />
        <path d="M2 18h16" />
        <path d="M5.5 13l3-5 3 3 4-6" />
      </svg>
    ),
  },
  {
    path: '/strategy',
    label: 'Strategy',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="2.5" />
        <path d="M10 2v3m0 10v3M2 10h3m10 0h3" />
        <path d="M4.93 4.93l2.12 2.12m5.9 5.9l2.12 2.12M4.93 15.07l2.12-2.12m5.9-5.9l2.12-2.12" />
      </svg>
    ),
  },
  {
    path: '/risk',
    label: 'Risk',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 18s7-3.5 7-8.75V4.5L10 2 3 4.5v4.75C3 14.5 10 18 10 18z" />
        <path d="M10 7v3.5" />
        <circle cx="10" cy="13.5" r="0.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    path: '/terminal',
    label: 'Terminal',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 14 7.5 10 3 6" />
        <line x1="10" y1="14" x2="17" y2="14" />
      </svg>
    ),
  },
  {
    path: '/about',
    label: 'About',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="8" />
        <path d="M10 13.5V10" />
        <circle cx="10" cy="6.5" r="0.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
] as const;

const navStyle = (active: boolean): CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  height: '40px',
  width: '100%',
  padding: '0 20px',
  gap: '12px',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
  background: active ? 'var(--accent-soft)' : 'transparent',
  color: active ? 'var(--accent)' : 'var(--label-secondary)',
  transition: 'background var(--dur-fast) var(--ease-apple), color var(--dur-fast) var(--ease-apple), border-color var(--dur-fast) var(--ease-apple)',
});

export const Sidebar = memo(function Sidebar() {
  const [expanded, setExpanded] = useState(false);
  const [time, setTime] = useState('');
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(
        [now.getHours(), now.getMinutes(), now.getSeconds()]
          .map((n) => String(n).padStart(2, '0'))
          .join(':')
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const handleMouseEnter = useCallback(() => setExpanded(true), []);
  const handleMouseLeave = useCallback(() => setExpanded(false), []);

  const isActive = useCallback(
    (path: string): boolean =>
      path === '/' ? location.pathname === '/' : location.pathname === path || location.pathname.startsWith(path + '/'),
    [location.pathname]
  );

  const handleNav = useCallback(
    (path: string) => () => navigate(path),
    [navigate]
  );

  const handleNavHoverIn = useCallback(
    (path: string) => (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isActive(path)) {
        (e.currentTarget as HTMLElement).style.background = 'var(--separator)';
      }
    },
    [isActive]
  );

  const handleNavHoverOut = useCallback(
    (path: string) => (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isActive(path)) {
        (e.currentTarget as HTMLElement).style.background = 'transparent';
      }
    },
    [isActive]
  );

  return (
    <nav
      style={{
        width: expanded ? 'var(--sidebar-expanded)' : 'var(--sidebar-w)',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        borderRight: '1px solid var(--separator)',
        transition: 'width var(--dur-base) var(--ease-apple)',
        overflow: 'hidden',
        flexShrink: 0,
        position: 'relative',
        zIndex: 10,
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        style={{
          height: 'var(--topbar-h)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: expanded ? 'flex-start' : 'center',
          padding: expanded ? '0 20px' : '0',
          width: '100%',
          borderBottom: '1px solid var(--separator)',
          whiteSpace: 'nowrap',
          gap: '10px',
        }}
      >
        <span
          style={{
            fontFamily: 'Georgia, "Times New Roman", serif',
            fontSize: '28px',
            fontWeight: 700,
            color: 'var(--accent)',
            lineHeight: 1,
            minWidth: '20px',
            textAlign: 'center',
            letterSpacing: '-0.02em',
          }}
        >
          Q
        </span>
        <span
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '15px',
            fontWeight: 600,
            color: 'var(--label-primary)',
            letterSpacing: '0.01em',
            opacity: expanded ? 1 : 0,
            transition: 'opacity var(--dur-base) var(--ease-apple)',
          }}
        >
          QuantCore
        </span>
      </div>

      <div style={{ flex: 1, width: '100%', paddingTop: 'var(--s2)' }}>
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.path);
          return (
            <div
              key={item.path}
              role="button"
              tabIndex={0}
              style={navStyle(active)}
              onClick={handleNav(item.path)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') handleNav(item.path)();
              }}
              onMouseEnter={handleNavHoverIn(item.path)}
              onMouseLeave={handleNavHoverOut(item.path)}
            >
              <span style={{ display: 'flex', flexShrink: 0, alignItems: 'center' }}>
                {item.icon}
              </span>
              <span
                style={{
                  fontSize: '13px',
                  fontWeight: 500,
                  opacity: expanded ? 1 : 0,
                  transition: 'opacity var(--dur-base) var(--ease-apple)',
                }}
              >
                {item.label}
              </span>
            </div>
          );
        })}
      </div>

      <div
        style={{
          height: 'var(--topbar-h)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          color: 'var(--label-tertiary)',
          borderTop: '1px solid var(--separator)',
          fontVariantNumeric: 'tabular-nums',
          letterSpacing: '0.04em',
        }}
      >
        {time}
      </div>
    </nav>
  );
});
