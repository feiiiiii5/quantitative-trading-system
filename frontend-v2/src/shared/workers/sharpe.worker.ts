import * as Comlink from 'comlink';

function calcRollingSharpe(returns: number[], windowSize: number): number[] {
  if (returns.length < windowSize) return [];
  const result: number[] = [];
  for (let i = windowSize - 1; i < returns.length; i++) {
    const slice = returns.slice(i - windowSize + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / windowSize;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / (windowSize - 1);
    const std = Math.sqrt(variance);
    const annualizedReturn = mean * 252;
    const annualizedStd = std * Math.sqrt(252);
    result.push(annualizedStd === 0 ? 0 : annualizedReturn / annualizedStd);
  }
  return result;
}

Comlink.expose({ calcRollingSharpe });
