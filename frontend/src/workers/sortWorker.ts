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
    const numA = (av as number) ?? 0;
    const numB = (bv as number) ?? 0;
    return dir === 'asc' ? numA - numB : numB - numA;
  });
  self.postMessage(sorted);
};
