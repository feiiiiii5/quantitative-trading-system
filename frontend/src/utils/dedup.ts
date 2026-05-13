const map = new Map<string, { p: Promise<unknown>; t: number; refCount: number }>();

export function dedup<T>(key: string, fn: () => Promise<T>, ttl = 150): Promise<T> {
  const e = map.get(key);
  if (e && Date.now() - e.t < ttl) {
    e.refCount++;
    return (e.p as Promise<T>).finally(() => {
      e.refCount--;
      if (e.refCount <= 0) map.delete(key);
    });
  }
  const entry: { p: Promise<unknown>; t: number; refCount: number } = { p: Promise.resolve(), t: Date.now(), refCount: 1 };
  const p = fn().finally(() => {
    entry.refCount--;
    if (entry.refCount <= 0) map.delete(key);
  });
  entry.p = p;
  map.set(key, entry);
  return p;
}
