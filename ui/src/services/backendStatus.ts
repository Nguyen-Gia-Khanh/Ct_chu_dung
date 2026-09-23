export type BackendStatus = 'connecting' | 'ready' | 'unavailable';

let status: BackendStatus = 'connecting';
const listeners = new Set<() => void>();

export const getBackendStatus = () => status;

export const subscribeBackendStatus = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

function setBackendStatus(next: BackendStatus) {
  if (status === next) return;
  status = next;
  listeners.forEach((listener) => listener());
}

export async function backendFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    const response = await fetch(input, init);
    setBackendStatus('ready');
    return response;
  } catch (error) {
    setBackendStatus('unavailable');
    throw error;
  }
}
