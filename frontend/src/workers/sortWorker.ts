interface SortMessage {
  items: Record<string, unknown>[];
  key: string;
  dir: 'asc' | 'desc';
}

self.onmessage = (e: MessageEvent<SortMessage>) => {
  const { items, key, dir } = e.data;
  const sorted = [...items].sort((a: Record<string, unknown>, b: Record<string, unknown>) => {
    const av = a[key];
    const bv = b[key];
    if (typeof av === 'string' && typeof bv === 'string') {
      return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    const numA = av != null ? (av as number) : (dir === 'asc' ? Infinity : -Infinity);
    const numB = bv != null ? (bv as number) : (dir === 'asc' ? Infinity : -Infinity);
    return dir === 'asc' ? numA - numB : numB - numA;
  });
  self.postMessage(sorted);
};
