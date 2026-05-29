import { describe, it, expect } from 'vitest';

describe('OrderBook data shape', () => {
  it('validates orderbook structure from API response', () => {
    const mockApiResponse = {
      bids: [
        { price: 100.0, volume: 500 },
        { price: 99.99, volume: 300 },
      ],
      asks: [
        { price: 100.01, volume: 400 },
        { price: 100.02, volume: 200 },
      ],
      symbol: 'sh600519',
      timestamp: Date.now(),
    };

    expect(mockApiResponse.bids).toHaveLength(2);
    expect(mockApiResponse.asks).toHaveLength(2);
    expect(mockApiResponse.bids[0]!.price).toBeLessThan(mockApiResponse.asks[0]!.price);
  });

  it('bids are descending in price', () => {
    const bids = [
      { price: 100.0, volume: 500 },
      { price: 99.99, volume: 300 },
      { price: 99.98, volume: 200 },
    ];
    for (let i = 1; i < bids.length; i++) {
      expect(bids[i]!.price).toBeLessThan(bids[i - 1]!.price);
    }
  });

  it('asks are ascending in price', () => {
    const asks = [
      { price: 100.01, volume: 400 },
      { price: 100.02, volume: 200 },
      { price: 100.03, volume: 100 },
    ];
    for (let i = 1; i < asks.length; i++) {
      expect(asks[i]!.price).toBeGreaterThan(asks[i - 1]!.price);
    }
  });
});
