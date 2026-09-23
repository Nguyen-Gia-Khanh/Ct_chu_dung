/**
 * API client service for Warehouse Shelf Mapper UI.
 * Connects to the local Python server. It never writes to a mock database.
 */

import {
  Shelf,
  Product,
  OnHandProduct,
  WorkingBatchProduct,
  PrimalQueueItem,
  ShelfCell,
  AssignLocationPayload,
  TransferCellPayload,
  ApiResponse,
  CSVData,
  CSVColumnMapping,
} from '../types';
import { backendFetch } from './backendStatus';

const API_BASE_URL = (typeof window !== 'undefined' && (window as unknown as { __BACKEND_URL__?: string }).__BACKEND_URL__) || '/api';

export const ApiService = {
  async getShelves(): Promise<Shelf[]> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/shelves`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return [];
  },

  async saveShelf(shelf: Shelf): Promise<Shelf & { error?: string }> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/shelves`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(shelf),
      });
      const data = await res.json();
      if (!res.ok) {
        return { ...shelf, error: data.error || `HTTP ${res.status}` };
      }
      return data;
    } catch (e) {
      return { ...shelf, error: String(e) };
    }
  },

  async deleteShelf(shelfId: number): Promise<{ success?: boolean; error?: string }> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/shelves/${shelfId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) {
        return { error: data.error || `HTTP ${res.status}` };
      }
      return data;
    } catch (e) {
      return { error: String(e) };
    }
  },

  async getCatalog(): Promise<Product[]> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/products/catalog`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return [];
  },

  async getPendingQueue(): Promise<OnHandProduct[]> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/products/pending-queue`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return [];
  },

  async getPrimalQueue(): Promise<PrimalQueueItem[]> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/products/primal-queue`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return [];
  },

  async getShelfCells(shelfCode: string): Promise<Record<string, ShelfCell>> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/shelves/${encodeURIComponent(shelfCode)}/cells`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return {};
  },

  async assignLocation(payload: AssignLocationPayload): Promise<ApiResponse> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/assignments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      return await res.json();
    } catch {
      // Fallback
    }
    return { success: false, error: 'Local backend unavailable.' };
  },

  async directMoveLocation(productId: string, targetSlot: AssignLocationPayload['slot']): Promise<ApiResponse> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/assignments/direct-move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, slot: targetSlot }),
      });
      return await res.json();
    } catch {
      // Fallback
    }
    return { success: false, error: 'Local backend unavailable.' };
  },

  async transferCells(payload: TransferCellPayload): Promise<ApiResponse> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/assignments/transfer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      return await res.json();
    } catch {
      // Fallback
    }
    return { success: false, error: 'Local backend unavailable.' };
  },

  async removePlacement(productId: string, locId: string): Promise<ApiResponse> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/assignments/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, loc_id: locId }),
      });
      return await res.json();
    } catch {
      // Fallback
    }
    return { success: false, error: 'Local backend unavailable.' };
  },

  async importCSV(
    csvData: CSVData,
    mapping: CSVColumnMapping,
    mode: 'new' | 'return'
  ): Promise<ApiResponse<{ imported: number }>> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/import-csv`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: csvData, mapping, mode }),
      });
      return await res.json();
    } catch {
      // Fallback
    }
    return { success: false, error: 'Local backend unavailable.' };
  },

  async findProductLocation(query: string): Promise<{ product: Product | null; location: string | null }> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/products/find?q=${encodeURIComponent(query)}`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return { product: null, location: null };
  },

  async getOnHandProducts(): Promise<WorkingBatchProduct[]> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/products/on-hand`);
      if (res.ok) return await res.json();
    } catch {
    }
    return [];
  },

  async addToOnHand(productIds: string[], quantities: Record<string, number> = {}): Promise<ApiResponse> {
    const items = productIds.map((pid) => ({
      product_id: pid,
      quantity: quantities[pid] !== undefined ? quantities[pid] : null,
    }));
    const res = await backendFetch(`${API_BASE_URL}/on-hand/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    return await res.json();
  },

  async dequeueOnHand(productIds: string[]): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/on-hand/dequeue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async updateOnHandStock(productId: string, quantity: number | null): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/on-hand/update-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, quantity }),
    });
    return await res.json();
  },

  async getSlotAddress(floor: number | string, side: number | string, shelf: string, row: number | string, col: number | string): Promise<ApiResponse> {
    const query = new URLSearchParams({
      floor: String(floor),
      side: String(side),
      shelf: String(shelf),
      row: String(row),
      col: String(col),
    });
    const res = await backendFetch(`${API_BASE_URL}/slot-address?${query}`);
    return await res.json();
  },

  async assignOnHandToSlot(slotId: number, productIds: string[]): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/assignments/assign-on-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async moveSlotToOnHand(slotId: number, productIds: string[] | null = null): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/slot-contents/move-to-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async updateSlotStock(slotId: number, productId: string, quantity: number | null): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/slot-contents/update-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_id: productId, quantity }),
    });
    return await res.json();
  },

  async transferCatalogToQueue(productIds: string[]): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/catalog/transfer-to-queue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async connectChrome(): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/web/connect-chrome`, { method: 'POST' });
    return await res.json();
  },

  async modifyLocationWeb(
    target: string[] | { product_id: string; slot_name: string }[],
    slotName?: string
  ): Promise<ApiResponse> {
    const body =
      Array.isArray(target) && target.length > 0 && typeof target[0] === 'object'
        ? { items: target }
        : { product_ids: target, slot_name: slotName };
    const res = await backendFetch(`${API_BASE_URL}/web/modify-location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  },

  async getPendingExceptions(): Promise<{ success: boolean; count: number; items: any[] }> {
    try {
      const res = await backendFetch(`${API_BASE_URL}/exceptions/pending`);
      if (res.ok) return await res.json();
    } catch {
    }
    return { success: true, count: 0, items: [] };
  },

  async assignException(payload: {
    product_id: string;
    floor: string | number;
    side: string | number;
    shelf: string;
    row: number;
    col: number;
    quantity?: number | null;
  }): Promise<ApiResponse> {
    const res = await backendFetch(`${API_BASE_URL}/exceptions/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return await res.json();
  },

  async appendExceptionsToCSV(csvPath?: string): Promise<ApiResponse<{ count: number }>> {
    const res = await backendFetch(`${API_BASE_URL}/exceptions/append-csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_path: csvPath }),
    });
    return await res.json();
  },
};
