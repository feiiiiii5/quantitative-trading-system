import { describe, it, expect, vi } from 'vitest';
import { dedup } from './dedup';

describe('dedup', () => {
  it('should execute fn when key is new', async () => {
    const fn = vi.fn().mockResolvedValue('result');
    const result = await dedup('key1', fn);
    expect(result).toBe('result');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should deduplicate concurrent calls with same key', async () => {
    const fn = vi.fn().mockResolvedValue('result');
    const p1 = dedup('key2', fn);
    const p2 = dedup('key2', fn);
    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toBe('result');
    expect(r2).toBe('result');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should allow new call after ttl expires', async () => {
    const fn = vi.fn().mockResolvedValue('result');
    await dedup('key3', fn, 0);
    await new Promise(r => setTimeout(r, 10));
    await dedup('key3', fn, 0);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('should clean up map entry after promise settles', async () => {
    const fn = vi.fn().mockResolvedValue('done');
    await dedup('key4', fn, 0);
    await new Promise(r => setTimeout(r, 10));
    const fn2 = vi.fn().mockResolvedValue('done2');
    await dedup('key4', fn2, 0);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn2).toHaveBeenCalledTimes(1);
  });

  it('should clean up map entry even when promise rejects', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('fail'));
    await expect(dedup('key5', fn)).rejects.toThrow('fail');
    const fn2 = vi.fn().mockResolvedValue('recovered');
    const result = await dedup('key5', fn2);
    expect(result).toBe('recovered');
    expect(fn2).toHaveBeenCalledTimes(1);
  });

  it('should not deduplicate different keys', async () => {
    const fn1 = vi.fn().mockResolvedValue('a');
    const fn2 = vi.fn().mockResolvedValue('b');
    const [r1, r2] = await Promise.all([
      dedup('key6a', fn1),
      dedup('key6b', fn2),
    ]);
    expect(r1).toBe('a');
    expect(r2).toBe('b');
    expect(fn1).toHaveBeenCalledTimes(1);
    expect(fn2).toHaveBeenCalledTimes(1);
  });
});

describe('dedup fuzz', () => {
  it('handles rapid concurrent calls with same key', async () => {
    let callCount = 0;
    const fn = vi.fn().mockImplementation(async () => {
      callCount++;
      await new Promise(r => setTimeout(r, 50));
      return callCount;
    });

    const promises = Array.from({ length: 20 }, () => dedup('fuzz1', fn));
    const results = await Promise.all(promises);

    expect(fn).toHaveBeenCalledTimes(1);
    for (const r of results) {
      expect(r).toBe(1);
    }
  });

  it('handles sequential calls after ttl', async () => {
    const fn = vi.fn().mockResolvedValue('ok');
    for (let i = 0; i < 10; i++) {
      await dedup('fuzz2', fn, 0);
      await new Promise(r => setTimeout(r, 1));
    }
    expect(fn).toHaveBeenCalledTimes(10);
  });
});
