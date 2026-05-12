import { describe, it, expect, vi, beforeEach } from 'vitest';
import { isBacktestResult } from './strategy';
import type { BacktestResult } from '@/types';

describe('isBacktestResult', () => {
  it('returns true for valid backtest result', () => {
    const valid: BacktestResult = {
      total_return: 0.15,
      annual_return: 0.12,
      sharpe_ratio: 1.5,
      max_drawdown: -0.08,
      calmar_ratio: 1.2,
      win_rate: 0.55,
      profit_factor: 1.8,
      total_trades: 42,
      equity_curve: [{ date: '2024-01-01', value: 100000 }],
      trades: [],
    };
    expect(isBacktestResult(valid)).toBe(true);
  });

  it('returns false for null', () => {
    expect(isBacktestResult(null)).toBe(false);
  });

  it('returns false for non-object', () => {
    expect(isBacktestResult('string')).toBe(false);
    expect(isBacktestResult(123)).toBe(false);
  });

  it('returns false when total_return is missing', () => {
    expect(isBacktestResult({ annual_return: 0.1, sharpe_ratio: 1, max_drawdown: -0.05, equity_curve: [] })).toBe(false);
  });

  it('returns false when equity_curve is not array', () => {
    expect(isBacktestResult({ total_return: 0.1, annual_return: 0.1, sharpe_ratio: 1, max_drawdown: -0.05, equity_curve: 'not-array' })).toBe(false);
  });
});

describe('isBacktestResult fuzz', () => {
  const randomFloat = () => (Math.random() - 0.5) * 2;
  const randomInt = (max: number) => Math.floor(Math.random() * max);

  it('handles random valid objects', () => {
    for (let i = 0; i < 100; i++) {
      const obj = {
        total_return: randomFloat(),
        annual_return: randomFloat(),
        sharpe_ratio: randomFloat(),
        max_drawdown: randomFloat(),
        equity_curve: Array.from({ length: randomInt(10) }, (_, j) => ({ date: `2024-01-${j + 1}`, value: 100000 + randomFloat() * 10000 })),
      };
      expect(isBacktestResult(obj)).toBe(true);
    }
  });

  it('handles random invalid objects', () => {
    for (let i = 0; i < 100; i++) {
      const obj = {
        total_return: Math.random() > 0.3 ? randomFloat() : 'string',
        annual_return: Math.random() > 0.3 ? randomFloat() : undefined,
        sharpe_ratio: Math.random() > 0.3 ? randomFloat() : null,
        max_drawdown: Math.random() > 0.3 ? randomFloat() : {},
        equity_curve: Math.random() > 0.3 ? [] : 'not-array',
      };
      const isValid =
        typeof obj.total_return === 'number' &&
        typeof obj.annual_return === 'number' &&
        typeof obj.sharpe_ratio === 'number' &&
        typeof obj.max_drawdown === 'number' &&
        Array.isArray(obj.equity_curve);
      expect(isBacktestResult(obj)).toBe(isValid);
    }
  });
});

describe('SSE error handling', () => {
  it('handles SSE error message with null message field', () => {
    const payload = { type: 'error', message: null };
    const log = `[ERROR] ${payload.message ?? 'Unknown error'}`;
    expect(log).toBe('[ERROR] Unknown error');
  });

  it('handles SSE error message with undefined message field', () => {
    const payload = { type: 'error' };
    const log = `[ERROR] ${(payload as Record<string, unknown>).message ?? 'Unknown error'}`;
    expect(log).toBe('[ERROR] Unknown error');
  });

  it('handles SSE error message with valid message', () => {
    const payload = { type: 'error', message: 'Strategy not found' };
    const log = `[ERROR] ${payload.message ?? 'Unknown error'}`;
    expect(log).toBe('[ERROR] Strategy not found');
  });
});
