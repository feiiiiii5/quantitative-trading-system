import { memo } from 'react';

const INJECTED_CSS = `
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: translateY(0); }
}
.philosophy-card {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.philosophy-card:hover {
  transform: scale(1.02);
}
`;

const FONT_SANS = '-apple-system, "Helvetica Neue", "PingFang SC", sans-serif';
const FONT_MONO = '"SF Mono", "Fira Code", "JetBrains Mono", monospace';
const EASE = 'cubic-bezier(0.16, 1, 0.3, 1)';

const C = {
  bg: '#000000',
  primary: '#ffffff',
  secondary: 'rgba(255,255,255,0.55)',
  tertiary: 'rgba(255,255,255,0.30)',
  accent: '#0A84FF',
  rise: '#FF1744',
  fall: '#00C853',
  warn: '#FF9100',
  info: '#5AC8FA',
  glass: 'rgba(10,10,10,0.85)',
  separator: 'rgba(255,255,255,0.06)',
};

const glass: React.CSSProperties = {
  background: C.glass,
  backdropFilter: 'blur(24px) saturate(120%)',
  WebkitBackdropFilter: 'blur(24px) saturate(120%)',
  borderRadius: 16,
  border: `1px solid ${C.separator}`,
};

const anim = (delay: number): React.CSSProperties => ({
  animation: `fadeIn 0.6s ${EASE} both`,
  animationDelay: `${delay}s`,
});

const philosophies = [
  { title: '极致暗色', desc: 'Pure darkness eliminates visual noise' },
  { title: '暴力排版', desc: 'Data IS the visual' },
  { title: '克制爆发', desc: 'Restraint with strategic bursts' },
  { title: '密度美学', desc: 'Every pixel works' },
];

const infoLayers = [
  { level: 'L1', name: '决策层', desc: '3秒内获取全局状态', color: C.accent },
  { level: 'L2', name: '分析层', desc: '因子/Alpha/波动率/相关性', color: C.info },
  { level: 'L3', name: '执行层', desc: 'OrderBook/滑点/VWAP/TCA', color: C.fall },
  { level: 'L4', name: '系统层', desc: '数据源/API/延迟/节点', color: C.warn },
];

const capabilities = [
  { title: 'REAL-TIME DATA', subtitle: '实时数据引擎', desc: '全市场行情推送' },
  { title: 'STRATEGY ENGINE', subtitle: '策略引擎', desc: '39种量化策略' },
  { title: 'RISK CONTROL', subtitle: '风控系统', desc: 'VaR/CVaR计算' },
];

const techStack = [
  { title: 'BACKEND', items: ['Python', 'FastAPI', 'DuckDB', 'WebSocket'], color: C.rise },
  { title: 'FRONTEND', items: ['React 19', 'TypeScript', 'Zustand', 'Canvas2D'], color: C.accent },
  { title: 'DATA', items: ['AKShare', 'Tushare', 'Realtime', 'Kline'], color: C.fall },
  { title: 'AI', items: ['LLM', 'Sentiment', 'Strategy', 'Risk'], color: C.warn },
];

const features = [
  { title: 'HERO TICKER', desc: '六大指数实时展示，迷你折线图直观呈现趋势' },
  { title: 'SECTOR HEATMAP', desc: '30个行业板块热力图，涨跌色深浅渐变' },
  { title: 'MARKET BREADTH', desc: '涨跌分布水平条形图，实时统计涨跌家数' },
  { title: 'SIGNAL BADGES', desc: 'BUY/SELL/HOLD信号标记，2px色条+文字' },
  { title: 'BACKTEST ENGINE', desc: '终端风格日志输出，净值曲线+回撤图叠加' },
  { title: 'GLOBAL SEARCH', desc: 'CMD+K全局搜索，模糊匹配，键盘导航' },
];

const SectionNumber = memo(function SectionNumber({ n }: { n: string }) {
  return (
    <div style={{
      fontFamily: FONT_MONO, fontSize: 10, color: C.accent,
      letterSpacing: '0.1em', marginBottom: 8,
    }}>
      {n}
    </div>
  );
});

const SectionTitle = memo(function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontFamily: FONT_SANS, fontSize: 32, fontWeight: 600,
      color: C.primary, letterSpacing: '-0.02em', margin: '0 0 48px',
    }}>
      {children}
    </h2>
  );
});

const SignalIcon = memo(function SignalIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
      <circle cx="20" cy="24" r="3" fill={C.accent} />
      <path d="M14 18a8.5 8.5 0 0112 0" stroke={C.accent} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10 14a14 14 0 0120 0" stroke={C.accent} strokeWidth="1.5" strokeLinecap="round" opacity={0.6} />
      <path d="M6 10a19 19 0 0128 0" stroke={C.accent} strokeWidth="1.5" strokeLinecap="round" opacity={0.3} />
    </svg>
  );
});

const GearIcon = memo(function GearIcon() {
  const teeth = [0, 45, 90, 135, 180, 225, 270, 315];
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
      <circle cx="20" cy="20" r="6" stroke={C.accent} strokeWidth="1.5" />
      <circle cx="20" cy="20" r="2.5" fill={C.accent} />
      {teeth.map(deg => {
        const rad = (deg * Math.PI) / 180;
        return (
          <line
            key={deg}
            x1={20 + 8 * Math.cos(rad)}
            y1={20 + 8 * Math.sin(rad)}
            x2={20 + 12 * Math.cos(rad)}
            y2={20 + 12 * Math.sin(rad)}
            stroke={C.accent}
            strokeWidth="2.5"
            strokeLinecap="round"
          />
        );
      })}
    </svg>
  );
});

const ShieldIcon = memo(function ShieldIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
      <path
        d="M20 4L6 10v10c0 9.6 6 15.4 14 18 8-2.6 14-8.4 14-18V10L20 4z"
        stroke={C.accent}
        strokeWidth="1.5"
      />
      <path d="M15 20l3.5 3.5L26 16" stroke={C.accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
});

const CAPABILITY_ICONS: React.FC[] = [SignalIcon, GearIcon, ShieldIcon];

const HeroSection = memo(function HeroSection() {
  return (
    <section style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      position: 'relative',
      overflow: 'hidden',
      ...anim(0),
    }}>
      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 600,
        height: 600,
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(10,132,255,0.08) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />
      <div style={{ position: 'relative', zIndex: 1 }}>
        <div style={{
          fontFamily: FONT_SANS,
          fontSize: 120,
          fontWeight: 200,
          color: C.accent,
          letterSpacing: '-0.04em',
          lineHeight: 1,
        }}>
          Q
        </div>
        <div style={{
          fontFamily: FONT_SANS,
          fontSize: 56,
          fontWeight: 700,
          color: C.primary,
          letterSpacing: '-0.02em',
          lineHeight: 1.2,
        }}>
          QuantCore
        </div>
        <div style={{
          fontFamily: FONT_SANS,
          fontSize: 56,
          fontWeight: 200,
          color: C.secondary,
          letterSpacing: '0.08em',
          lineHeight: 1.3,
        }}>
          Terminal
        </div>
        <p style={{
          fontFamily: FONT_SANS,
          fontSize: 16,
          color: C.secondary,
          maxWidth: 480,
          lineHeight: 1.7,
          margin: '24px auto 0',
        }}>
          工业级量化交易系统 — 以精密数据驱动的投资决策引擎
        </p>
        <div style={{ display: 'flex', gap: 12, marginTop: 32, justifyContent: 'center' }}>
          {['PURE BLACK', 'PRECISION DATA', 'SIGNAL IMPACT'].map(tag => (
            <span key={tag} style={{
              fontFamily: FONT_MONO,
              fontSize: 9,
              textTransform: 'uppercase' as const,
              letterSpacing: '0.1em',
              color: C.tertiary,
              padding: '6px 14px',
              border: `1px solid ${C.separator}`,
              borderRadius: 100,
            }}>
              {tag}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
});

const PhilosophySection = memo(function PhilosophySection() {
  return (
    <section style={{ padding: '80px 0', ...anim(0.15) }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
        <SectionNumber n="01" />
        <SectionTitle>设计哲学</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {philosophies.map(item => (
            <div key={item.title} className="philosophy-card" style={{
              ...glass,
              padding: 28,
              borderTop: `3px solid ${C.accent}`,
            }}>
              <div style={{
                fontFamily: FONT_SANS, fontSize: 18,
                color: C.primary, fontWeight: 600, marginBottom: 8,
              }}>
                {item.title}
              </div>
              <div style={{
                fontFamily: FONT_SANS, fontSize: 13,
                color: C.tertiary, lineHeight: 1.7,
              }}>
                {item.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

const ArchitectureSection = memo(function ArchitectureSection() {
  return (
    <section style={{ padding: '80px 0', ...anim(0.3) }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
        <SectionNumber n="02" />
        <SectionTitle>四层信息架构</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {infoLayers.map(layer => (
            <div key={layer.level} style={{
              ...glass,
              padding: 24,
              borderTop: `3px solid ${layer.color}`,
            }}>
              <div style={{
                fontFamily: FONT_MONO, fontSize: 10, color: layer.color,
                letterSpacing: '0.1em', marginBottom: 4,
              }}>
                {layer.level}
              </div>
              <div style={{
                fontFamily: FONT_SANS, fontSize: 18,
                color: C.primary, fontWeight: 600, marginBottom: 12,
              }}>
                {layer.name}
              </div>
              <div style={{
                fontFamily: FONT_SANS, fontSize: 12,
                color: C.tertiary, lineHeight: 1.6,
              }}>
                {layer.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

const CapabilitiesSection = memo(function CapabilitiesSection() {
  return (
    <section style={{ padding: '80px 0', ...anim(0.45) }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
        <SectionNumber n="03" />
        <SectionTitle>核心能力</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
          {capabilities.map((item, i) => {
            const Icon = CAPABILITY_ICONS[i];
            if (!Icon) return null;
            return (
              <div key={item.title} style={{ ...glass, padding: 40 }}>
                <Icon />
                <div style={{
                  fontFamily: FONT_MONO, fontSize: 12,
                  textTransform: 'uppercase' as const, color: C.accent,
                  letterSpacing: '0.06em', marginTop: 20,
                }}>
                  {item.title}
                </div>
                <div style={{
                  fontFamily: FONT_SANS, fontSize: 16,
                  color: C.primary, fontWeight: 600, marginTop: 6,
                }}>
                  {item.subtitle}
                </div>
                <div style={{
                  fontFamily: FONT_SANS, fontSize: 13,
                  color: C.tertiary, lineHeight: 1.7, marginTop: 12,
                }}>
                  {item.desc}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
});

const TechStackSection = memo(function TechStackSection() {
  return (
    <section style={{ padding: '80px 0', ...anim(0.6) }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
        <SectionNumber n="04" />
        <SectionTitle>技术架构</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          {techStack.map(stack => (
            <div key={stack.title} style={{ ...glass, padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: stack.color, flexShrink: 0,
                }} />
                <div style={{
                  fontFamily: FONT_MONO, fontSize: 9,
                  textTransform: 'uppercase' as const, color: C.tertiary,
                  letterSpacing: '0.08em',
                }}>
                  {stack.title}
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {stack.items.map(item => (
                  <span key={item} style={{
                    fontFamily: FONT_MONO, fontSize: 12,
                    color: C.secondary,
                  }}>
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

const FeaturesSection = memo(function FeaturesSection() {
  return (
    <section style={{ padding: '80px 0', ...anim(0.75) }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
        <SectionNumber n="05" />
        <SectionTitle>产品特性</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {features.map(item => (
            <div key={item.title} style={{
              ...glass,
              padding: '24px 28px',
              display: 'flex',
              gap: 14,
              alignItems: 'flex-start',
            }}>
              <div style={{
                width: 3,
                height: 16,
                background: C.accent,
                borderRadius: 2,
                flexShrink: 0,
                marginTop: 3,
              }} />
              <div>
                <div style={{
                  fontFamily: FONT_MONO, fontSize: 12,
                  color: C.primary, fontWeight: 500, letterSpacing: '0.02em',
                }}>
                  {item.title}
                </div>
                <div style={{
                  fontFamily: FONT_SANS, fontSize: 12,
                  color: C.tertiary, lineHeight: 1.6, marginTop: 6,
                }}>
                  {item.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
});

const FooterSection = memo(function FooterSection() {
  return (
    <footer style={{
      padding: '48px 0',
      textAlign: 'center',
      borderTop: `1px solid ${C.separator}`,
      ...anim(0.9),
    }}>
      <div style={{
        fontFamily: FONT_SANS, fontSize: 32,
        fontWeight: 200, color: C.accent,
      }}>
        Q
      </div>
      <div style={{
        fontFamily: FONT_MONO, fontSize: 10,
        color: C.tertiary, letterSpacing: '0.05em', marginTop: 12,
      }}>
        QUANTCORE TERMINAL v4.0
      </div>
      <div style={{
        fontFamily: FONT_SANS, fontSize: 11,
        color: C.tertiary, marginTop: 8,
      }}>
        Built with precision. Powered by data.
      </div>
    </footer>
  );
});

export function AboutPage() {
  return (
    <>
      <style>{INJECTED_CSS}</style>
      <div style={{ minHeight: '100%', background: C.bg }}>
        <HeroSection />
        <PhilosophySection />
        <ArchitectureSection />
        <CapabilitiesSection />
        <TechStackSection />
        <FeaturesSection />
        <FooterSection />
      </div>
    </>
  );
}
