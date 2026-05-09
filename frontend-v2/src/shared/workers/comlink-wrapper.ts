import * as Comlink from 'comlink';

export function createWorkerApi<T>(workerUrl: string): Comlink.Remote<T> {
  const worker = new Worker(workerUrl, { type: 'module' });
  return Comlink.wrap<T>(worker);
}
