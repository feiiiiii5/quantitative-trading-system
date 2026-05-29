const map = new Map<string, { p: Promise<unknown>; t: number; v?: unknown; ok?: boolean }>();

export function dedup<T>(key: string, fn: () => Promise<T>, ttl = 150): Promise<T> {
  const e = map.get(key);
  if (e && Date.now() - e.t < ttl) {
    if (e.ok) return e.v as T;
    return e.p as Promise<T>;
  }
  const p = fn().then((v) => {
    const current = map.get(key);
    if (current && current.p === p) {
      current.v = v;
      current.ok = true;
    }
    return v;
  }).catch((err) => {
    const current = map.get(key);
    if (current && current.p === p) {
      map.delete(key);  // 失败时删除，允许重试
    }
    throw err;
  });
  map.set(key, { p, t: Date.now() });
  return p;
}
