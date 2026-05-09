import { wsEngine } from '@/shared/ws';
import { useMarketStore } from '../model/useMarketStore';
import type { TickData } from '@/entities/tick';
import type { DepthData, TradeRecord } from '../model/types';

export function subscribeMarketData(symbol: string): () => void {
  const unsubs: Array<() => void> = [];

  unsubs.push(
    wsEngine.subscribe<TickData>(`tick.${symbol}`, (quote) => {
      useMarketStore.getState().updateQuote(symbol, quote);
    })
  );

  unsubs.push(
    wsEngine.subscribe<DepthData>(`orderbook.${symbol}`, (depth) => {
      useMarketStore.getState().updateDepth(symbol, depth);
    })
  );

  unsubs.push(
    wsEngine.subscribe<TradeRecord>(`trades.${symbol}`, (trade) => {
      useMarketStore.getState().appendTrade(symbol, trade);
    })
  );

  wsEngine.send('market', { type: 'subscribe', symbols: [symbol] });

  return () => {
    for (const unsub of unsubs) unsub();
    wsEngine.send('market', { type: 'unsubscribe', symbols: [symbol] });
  };
}
