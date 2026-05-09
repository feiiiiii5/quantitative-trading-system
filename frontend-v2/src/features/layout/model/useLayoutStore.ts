import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface PanelConfig {
  id: string;
  type: string;
  area: string;
  visible: boolean;
  width?: number;
  height?: number;
}

interface LayoutConfig {
  panels: PanelConfig[];
  gridTemplateColumns: string;
  gridTemplateRows: string;
  gridTemplateAreas: string;
}

interface LayoutState {
  layout: LayoutConfig;
  setLayout: (layout: LayoutConfig) => void;
  togglePanel: (id: string) => void;
  updatePanelSize: (id: string, width?: number, height?: number) => void;
  resetLayout: () => void;
}

const DEFAULT_LAYOUT: LayoutConfig = {
  panels: [
    { id: 'chart', type: 'chart', area: 'chart', visible: true },
    { id: 'orderbook', type: 'orderbook', area: 'orderbook', visible: true },
    { id: 'strategy', type: 'strategy', area: 'strategy', visible: true },
    { id: 'trades', type: 'trades', area: 'trades', visible: true },
    { id: 'depth', type: 'depth', area: 'depth', visible: true },
    { id: 'risk', type: 'risk', area: 'risk', visible: true },
  ],
  gridTemplateColumns: '1fr 280px 320px',
  gridTemplateRows: '1fr 200px',
  gridTemplateAreas: `
    "chart orderbook strategy"
    "trades depth risk"
  `,
};

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      layout: DEFAULT_LAYOUT,

      setLayout: (layout) => set({ layout }),

      togglePanel: (id) =>
        set((state) => ({
          layout: {
            ...state.layout,
            panels: state.layout.panels.map((p) =>
              p.id === id ? { ...p, visible: !p.visible } : p
            ),
          },
        })),

      updatePanelSize: (id, width, height) =>
        set((state) => ({
          layout: {
            ...state.layout,
            panels: state.layout.panels.map((p) =>
              p.id === id ? { ...p, ...(width !== undefined && { width }), ...(height !== undefined && { height }) } : p
            ),
          },
        })),

      resetLayout: () => set({ layout: DEFAULT_LAYOUT }),
    }),
    {
      name: 'qc-layout',
    }
  )
);
