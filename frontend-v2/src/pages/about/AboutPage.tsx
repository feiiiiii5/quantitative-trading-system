export function AboutPage() {
  const icons = {
    chart: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#C9A96E" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 16l4-6 4 4 5-8"/></svg>`,
    gear: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#C9A96E" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
    shield: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#C9A96E" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  };

  const capabilities = [
    {
      title: 'REAL-TIME DATA',
      subtitle: '实时数据引擎',
      desc: '全市场行情实时推送，覆盖A股/港股/美股，毫秒级数据更新，六大指数同步监控，板块热力图全景展示',
      icon: icons.chart,
    },
    {
      title: 'STRATEGY ENGINE',
      subtitle: '策略引擎',
      desc: '39种量化策略，支持任意股票任意时间段回测，终端日志风格运行状态，净值曲线与回撤可视化',
      icon: icons.gear,
    },
    {
      title: 'RISK CONTROL',
      subtitle: '风控系统',
      desc: '组合风险分析，VaR/CVaR计算，相关性矩阵，风险贡献度分解，实时监控与预警',
      icon: icons.shield,
    },
  ];

  const features = [
    { title: 'HERO TICKER BAR', desc: '六大指数实时展示，迷你折线图直观呈现趋势，64px高度信息密度最大化' },
    { title: 'SECTOR HEATMAP', desc: '30个行业板块热力图，涨跌色深浅渐变，悬停查看板块详情' },
    { title: 'MARKET BREADTH', desc: '涨跌分布水平条形图，实时统计上涨/下跌/平盘家数与成交额' },
    { title: 'SIGNAL BADGES', desc: 'BUY/SELL/HOLD信号标记，2px色条+文字，低透明度背景色块' },
    { title: 'BACKTEST ENGINE', desc: '终端风格日志输出，净值曲线+回撤图叠加，交易明细表' },
    { title: 'GLOBAL SEARCH', desc: 'CMD+K全局搜索，模糊匹配，键盘导航，市场标签颜色区分' },
  ];

  const techStack = [
    { title: 'BACKEND', items: ['Python', 'FastAPI', 'DuckDB', 'WebSocket'], color: '#D4584A' },
    { title: 'FRONTEND', items: ['React 19', 'TypeScript', 'Zustand', 'Canvas2D'], color: '#C9A96E' },
    { title: 'DATA', items: ['AKShare', 'Tushare', 'Realtime Push', 'Kline API'], color: '#5BA8A0' },
    { title: 'AI', items: ['LLM Analysis', 'Sentiment', 'Strategy Rec', 'Risk Model'], color: '#9B7DB8' },
  ];

  const philosophies = [
    { title: 'SWISS GRID', desc: '所有元素严格对齐8px基准网格，布局像《苏黎世财经报》的版式设计' },
    { title: 'VIOLENT TYPOGRAPHY', desc: '大量使用等宽字体作为主要内容字体，数据即视觉，排版即信息' },
    { title: 'RESTRAINED BURST', desc: '整体极度克制，关键数据点用高饱和度冲击色，稀少但震撼' },
    { title: 'DENSITY = AESTHETICS', desc: '信息密度是设计语言的一部分，拒绝无意义留白，每一个像素都在工作' },
  ];

  const cardBase: React.CSSProperties = {
    background: '#0a0a0a',
    borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.04)',
  };

  return (
    <div style={{ minHeight: '100%', background: '#000000' }}>
      <section style={{
        height: 'calc(100vh - 48px)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '600px',
          height: '600px',
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(201,169,110,0.04) 0%, transparent 70%)',
          pointerEvents: 'none',
        }} />
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '140px',
            fontWeight: 300,
            color: '#C9A96E',
            letterSpacing: '-0.04em',
            lineHeight: 1,
          }}>
            Q
          </div>
          <div style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '48px',
            fontWeight: 600,
            color: '#F0EBE3',
            letterSpacing: '-0.02em',
            lineHeight: 1.2,
          }}>
            QuantCore
          </div>
          <div style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '48px',
            fontWeight: 300,
            color: '#9B9490',
            letterSpacing: '0.08em',
            lineHeight: 1.3,
          }}>
            Terminal
          </div>
          <p style={{
            fontFamily: "system-ui, -apple-system, sans-serif",
            fontSize: '16px',
            color: '#9B9490',
            maxWidth: '480px',
            lineHeight: 1.7,
            margin: '24px auto 0',
          }}>
            工业级量化交易系统 — 以精密数据驱动的投资决策引擎
          </p>
          <div style={{ display: 'flex', gap: '12px', marginTop: '32px', justifyContent: 'center' }}>
            {['NOIR ATELIER', 'PRECISION DATA', 'SIGNAL IMPACT'].map(tag => (
              <span key={tag} style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: '9px',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
                color: '#5E5854',
                padding: '4px 12px',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: '2px',
              }}>
                {tag}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section style={{ padding: '80px 0' }}>
        <div style={{ maxWidth: '960px', margin: '0 auto', padding: '0 24px' }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10px',
            color: '#C9A96E',
            letterSpacing: '0.1em',
            marginBottom: '8px',
          }}>
            01
          </div>
          <h2 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '32px',
            color: '#F0EBE3',
            fontWeight: 400,
            margin: '0 0 48px',
          }}>
            核心能力
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
            {capabilities.map(item => (
              <div key={item.title} style={{
                ...cardBase,
                padding: '32px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
              }}>
                <div dangerouslySetInnerHTML={{ __html: item.icon }} />
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '12px',
                  textTransform: 'uppercase',
                  color: '#C9A96E',
                  letterSpacing: '0.06em',
                  marginTop: '16px',
                }}>
                  {item.title}
                </div>
                <div style={{
                  fontFamily: "system-ui, -apple-system, sans-serif",
                  fontSize: '14px',
                  color: '#F0EBE3',
                  marginTop: '4px',
                }}>
                  {item.subtitle}
                </div>
                <div style={{
                  fontFamily: "system-ui, -apple-system, sans-serif",
                  fontSize: '13px',
                  color: '#5E5854',
                  lineHeight: 1.7,
                  marginTop: '12px',
                }}>
                  {item.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ padding: '80px 0' }}>
        <div style={{ maxWidth: '960px', margin: '0 auto', padding: '0 24px' }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10px',
            color: '#C9A96E',
            letterSpacing: '0.1em',
            marginBottom: '8px',
          }}>
            02
          </div>
          <h2 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '32px',
            color: '#F0EBE3',
            fontWeight: 400,
            margin: '0 0 48px',
          }}>
            产品特性
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {features.map(item => (
              <div key={item.title} style={{
                ...cardBase,
                padding: '24px 28px',
                display: 'flex',
                gap: '14px',
                alignItems: 'flex-start',
              }}>
                <div style={{
                  width: '2px',
                  height: '16px',
                  background: '#C9A96E',
                  borderRadius: '1px',
                  flexShrink: 0,
                  marginTop: '3px',
                }} />
                <div>
                  <div style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '12px',
                    color: '#F0EBE3',
                    fontWeight: 500,
                    letterSpacing: '0.02em',
                  }}>
                    {item.title}
                  </div>
                  <div style={{
                    fontFamily: "system-ui, -apple-system, sans-serif",
                    fontSize: '12px',
                    color: '#5E5854',
                    lineHeight: 1.6,
                    marginTop: '6px',
                  }}>
                    {item.desc}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ padding: '80px 0' }}>
        <div style={{ maxWidth: '960px', margin: '0 auto', padding: '0 24px' }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10px',
            color: '#C9A96E',
            letterSpacing: '0.1em',
            marginBottom: '8px',
          }}>
            03
          </div>
          <h2 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '32px',
            color: '#F0EBE3',
            fontWeight: 400,
            margin: '0 0 48px',
          }}>
            技术架构
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
            {techStack.map(stack => (
              <div key={stack.title} style={{
                ...cardBase,
                padding: '24px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                  <div style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: stack.color,
                    flexShrink: 0,
                  }} />
                  <div style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '9px',
                    textTransform: 'uppercase',
                    color: '#5E5854',
                    letterSpacing: '0.08em',
                  }}>
                    {stack.title}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {stack.items.map(item => (
                    <span key={item} style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '12px',
                      color: '#9B9490',
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

      <section style={{ padding: '80px 0' }}>
        <div style={{ maxWidth: '960px', margin: '0 auto', padding: '0 24px' }}>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10px',
            color: '#C9A96E',
            letterSpacing: '0.1em',
            marginBottom: '8px',
          }}>
            04
          </div>
          <h2 style={{
            fontFamily: "'Cormorant Garamond', serif",
            fontSize: '32px',
            color: '#F0EBE3',
            fontWeight: 400,
            margin: '0 0 48px',
          }}>
            设计哲学
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {philosophies.map(item => (
              <div key={item.title} style={{
                ...cardBase,
                padding: '28px',
              }}>
                <div style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '13px',
                  color: '#C9A96E',
                  fontWeight: 500,
                  letterSpacing: '0.05em',
                }}>
                  {item.title}
                </div>
                <div style={{
                  fontFamily: "system-ui, -apple-system, sans-serif",
                  fontSize: '13px',
                  color: '#5E5854',
                  lineHeight: 1.7,
                  marginTop: '8px',
                }}>
                  {item.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer style={{
        padding: '48px 0',
        textAlign: 'center',
        borderTop: '1px solid rgba(255,255,255,0.04)',
      }}>
        <div style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: '32px',
          fontWeight: 300,
          color: '#C9A96E',
        }}>
          Q
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '10px',
          color: '#3A3633',
          letterSpacing: '0.05em',
          marginTop: '12px',
        }}>
          QUANTCORE TERMINAL v4.0
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '9px',
          color: '#3A3633',
          marginTop: '8px',
        }}>
          Built with precision. Powered by data.
        </div>
      </footer>
    </div>
  );
}
