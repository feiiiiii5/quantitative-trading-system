import { useState, useEffect } from 'react';

export type Freshness = 'fresh' | 'stale' | 'dead';

export function useDataFreshness(lastUpdatedAt: number | null): Freshness {
  const [freshness, setFreshness] = useState<Freshness>('dead');

  useEffect(() => {
    if (lastUpdatedAt === null) {
      setFreshness('dead');
      return;
    }

    const compute = () => {
      const elapsed = Date.now() - lastUpdatedAt;
      if (elapsed < 10_000) setFreshness('fresh');
      else if (elapsed < 60_000) setFreshness('stale');
      else setFreshness('dead');
    };

    compute();
    const id = setInterval(compute, 5_000);
    return () => clearInterval(id);
  }, [lastUpdatedAt]);

  return freshness;
}
