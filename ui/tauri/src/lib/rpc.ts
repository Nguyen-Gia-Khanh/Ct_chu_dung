import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/** A failure reported by the Python service (its exception type and message). */
export class RpcError extends Error {
  constructor(public type: string, message: string) {
    super(message);
  }
}

/** Call one mapper.rpc method; rejects with RpcError. */
export async function call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  try {
    return await invoke<T>("rpc", { method, params });
  } catch (problem) {
    const detail = problem as { type?: string; message?: string } | string;
    if (typeof detail === "string") throw new RpcError("Error", detail);
    throw new RpcError(detail.type ?? "Error", detail.message ?? String(problem));
  }
}

/** Listen to a sidecar event such as "job", "ready" or "exit". */
export function onSidecar<T>(event: string, handler: (data: T) => void): Promise<UnlistenFn> {
  return listen<T>(`sidecar://${event}`, (message) => handler(message.payload));
}
