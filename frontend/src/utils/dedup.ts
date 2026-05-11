const map = new Map<string, { p: Promise<unknown>; t: number }>();

export function dedup<T>(key: string, fn: () => Promise<T>, ttl = 150): Promise<T> {
  const e = map.get(key);
  if (e && Date.now() - e.t < ttl) return e.p as Promise<T>;
  const p = fn().finally(() => map.delete(key));
  map.set(key, { p, t: Date.now() });
  return p;
}
