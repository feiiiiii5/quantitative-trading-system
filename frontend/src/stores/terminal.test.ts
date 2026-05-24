import { describe, it, expect } from 'vitest';

describe('generateSimulatedOrderBook determinism', () => {
  it('produces identical output with same seed', () => {
    const rng = () => 0.5;
    const result1 = generateSimulatedOrderBook('sh600519', 100, rng);
    const result2 = generateSimulatedOrderBook('sh600519', 100, rng);
    expect(result1).toEqual(result2);
  });

  it('produces different output with different seeds', () => {
    const rng1 = () => 0.1;
    const rng2 = () => 0.9;
    const result1 = generateSimulatedOrderBook('sh600519', undefined, rng1);
    const result2 = generateSimulatedOrderBook('sh600519', undefined, rng2);
    expect(result1.bids[0]!.price).not.toBe(result2.bids[0]!.price);
  });

  it('returns 10 bid and 10 ask levels', () => {
    const rng = () => 0.5;
    const result = generateSimulatedOrderBook('sh600519', 100, rng);
    expect(result.bids).toHaveLength(10);
    expect(result.asks).toHaveLength(10);
  });

  it('bids are descending in price', () => {
    const rng = () => 0.5;
    const result = generateSimulatedOrderBook('sh600519', 100, rng);
    for (let i = 1; i < result.bids.length; i++) {
      expect(result.bids[i]!.price).toBeLessThan(result.bids[i - 1]!.price);
    }
  });

  it('asks are ascending in price', () => {
    const rng = () => 0.5;
    const result = generateSimulatedOrderBook('sh600519', 100, rng);
    for (let i = 1; i < result.asks.length; i++) {
      expect(result.asks[i]!.price).toBeGreaterThan(result.asks[i - 1]!.price);
    }
  });
});

function generateSimulatedOrderBook(
  _symbol: string,
  basePrice?: number,
  rng: () => number = Math.random,
): { bids: Array<{ price: number; quantity: number; orders: number }>; asks: Array<{ price: number; quantity: number; orders: number }> } {
  const price = basePrice ?? 10 + rng() * 90;
  const bids: Array<{ price: number; quantity: number; orders: number }> = [];
  const asks: Array<{ price: number; quantity: number; orders: number }> = [];
  for (let i = 0; i < 10; i++) {
    bids.push({
      price: price - (i + 1) * 0.01,
      quantity: Math.floor(rng() * 500 + 100),
      orders: Math.floor(rng() * 10 + 1),
    });
    asks.push({
      price: price + (i + 1) * 0.01,
      quantity: Math.floor(rng() * 500 + 100),
      orders: Math.floor(rng() * 10 + 1),
    });
  }
  return { bids, asks };
}
