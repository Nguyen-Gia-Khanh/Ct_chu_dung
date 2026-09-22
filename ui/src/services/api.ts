/**
 * API client service for Warehouse Shelf Mapper UI.
 * Connects to the backend server (FastAPI/Flask/IPC) with an intelligent
 * mock localStorage fallback for offline testing and standalone dev preview.
 */

import {
  Shelf,
  Product,
  OnHandProduct,
  PrimalQueueItem,
  ShelfCell,
  AssignLocationPayload,
  TransferCellPayload,
  ApiResponse,
  CSVData,
  CSVColumnMapping,
} from '../types';
import { makeSlotName, getShelfCode, formatProductId } from '../utils/coordinates';

const API_BASE_URL = (typeof window !== 'undefined' && (window as unknown as { __BACKEND_URL__?: string }).__BACKEND_URL__) || 'http://localhost:8000/api';

// Initial dummy data for instant interactive preview
const DEFAULT_SHELVES: Shelf[] = [
  {
    id: 1,
    floor: 1,
    side: 1,
    shelf: 'A',
    rows_count: 8,
    default_cols: 10,
    custom_row_cols: { 1: 10, 2: 10, 3: 10, 4: 10, 5: 10, 6: 10, 7: 10, 8: 10 },
    created_at: '2026-01-10T08:00:00Z',
  },
  {
    id: 2,
    floor: 1,
    side: 1,
    shelf: 'B',
    rows_count: 6,
    default_cols: 8,
    custom_row_cols: { 1: 8, 2: 8, 3: 8, 4: 8, 5: 8, 6: 8 },
    created_at: '2026-01-12T09:30:00Z',
  },
];

const DEFAULT_PRODUCTS: Product[] = [
  {
    product_id: '06410-KFL-850',
    product_name: 'Bố nồi trước Wave Alpha',
    barcode: '06410KFL850',
    on_hand: 24,
    loc_id: 'L1-1A2-4',
    category: 'Phụ tùng Honda',
  },
  {
    product_id: '12100-KWW-740',
    product_name: 'Nòng xi lanh Wave RSX 110',
    barcode: '12100KWW740',
    on_hand: 12,
    loc_id: 'L1-1A3-5',
    category: 'Phụ tùng Honda',
  },
  {
    product_id: '14401-KWB-601',
    product_name: 'Sên cam 90 mắt Wave 110',
    barcode: '14401KWB601',
    on_hand: 50,
    loc_id: 'L1-1A1-1',
    category: 'Động cơ',
  },
  {
    product_id: '16700-K03-H01',
    product_name: 'Bơm xăng điện tử Fi Dream',
    barcode: '16700K03H01',
    on_hand: 8,
    loc_id: 'L1-1A5-2',
    category: 'Hệ thống phun xăng',
  },
  {
    product_id: '22102-KZR-600',
    product_name: 'Chén bi nồi trước Vario 125',
    barcode: '22102KZR600',
    on_hand: 16,
    loc_id: 'L1-1B2-3',
    category: 'Nồi truyền động',
  },
  {
    product_id: '31210-KSS-900',
    product_name: 'Củ đề khởi động Future Neo',
    barcode: '31210KSS900',
    on_hand: 5,
    loc_id: null,
    category: 'Hệ thống điện',
  },
  {
    product_id: '45120-KFL-851',
    product_name: 'Dây curoa Bando xe Vision',
    barcode: '45120KFL851',
    on_hand: 35,
    loc_id: null,
    category: 'Truyền động',
  },
];

class StorageBackend {
  private shelves: Shelf[];
  private products: Product[];
  private cells: Record<string, ShelfCell> = {};

  constructor() {
    try {
      const s = localStorage.getItem('wm_shelves');
      this.shelves = s ? JSON.parse(s) : DEFAULT_SHELVES;
      const p = localStorage.getItem('wm_products');
      this.products = p ? JSON.parse(p) : DEFAULT_PRODUCTS;
    } catch {
      this.shelves = DEFAULT_SHELVES;
      this.products = DEFAULT_PRODUCTS;
    }
    this.rebuildCells();
  }

  private save() {
    try {
      localStorage.setItem('wm_shelves', JSON.stringify(this.shelves));
      localStorage.setItem('wm_products', JSON.stringify(this.products));
    } catch {
      // ignore storage quota issues
    }
    this.rebuildCells();
  }

  private rebuildCells() {
    this.cells = {};
    for (const prod of this.products) {
      if (!prod.loc_id) continue;
      if (!this.cells[prod.loc_id]) {
        const parts = prod.loc_id.match(/^L\d+-\d+[A-Za-z]+(\d+)-(\d+)$/);
        const row = parts ? parseInt(parts[1], 10) : 1;
        const col = parts ? parseInt(parts[2], 10) : 1;
        this.cells[prod.loc_id] = {
          row,
          col,
          loc_id: prod.loc_id,
          items: [],
          total_quantity: 0,
          is_occupied: true,
        };
      }
      this.cells[prod.loc_id].items.push({
        product_id: prod.product_id,
        product_name: prod.product_name,
        barcode: prod.barcode,
        quantity: prod.on_hand,
        placed_at: new Date().toISOString(),
      });
      this.cells[prod.loc_id].total_quantity += prod.on_hand;
    }
  }

  async getShelves(): Promise<Shelf[]> {
    return [...this.shelves];
  }

  async saveShelf(shelf: Shelf): Promise<Shelf> {
    const existingIndex = this.shelves.findIndex(
      (s) =>
        s.floor === shelf.floor &&
        s.side === shelf.side &&
        s.shelf.toUpperCase() === shelf.shelf.toUpperCase()
    );
    const newShelf = {
      ...shelf,
      id: shelf.id || Date.now(),
      created_at: new Date().toISOString(),
    };
    if (existingIndex >= 0) {
      this.shelves[existingIndex] = newShelf;
    } else {
      this.shelves.push(newShelf);
    }
    this.save();
    return newShelf;
  }

  async deleteShelf(shelfId: number): Promise<void> {
    this.shelves = this.shelves.filter((s) => s.id !== shelfId);
    this.save();
  }

  async getCatalog(): Promise<Product[]> {
    return [...this.products];
  }

  async getPendingQueue(): Promise<OnHandProduct[]> {
    return this.products
      .filter((p) => !p.loc_id)
      .map((p) => ({
        code: p.product_id,
        name: p.product_name,
        on_hand: p.on_hand,
        loc_id: p.loc_id,
        selected: false,
      }));
  }

  async getPrimalQueue(): Promise<PrimalQueueItem[]> {
    return this.products.map((p) => ({
      barcode: p.barcode,
      product_name: p.product_name,
      quantity: p.on_hand,
      status: p.loc_id ? 'assigned' : 'pending',
      target_location: p.loc_id || undefined,
    }));
  }

  async getShelfCells(shelfCode: string): Promise<Record<string, ShelfCell>> {
    const result: Record<string, ShelfCell> = {};
    const prefix = shelfCode.toUpperCase();
    for (const [locId, cell] of Object.entries(this.cells)) {
      if (locId.toUpperCase().startsWith(prefix)) {
        result[locId] = cell;
      }
    }
    return result;
  }

  async assignLocation(payload: AssignLocationPayload): Promise<ApiResponse> {
    const slotName = makeSlotName(
      payload.slot.floor,
      payload.slot.shelf,
      payload.slot.row,
      payload.slot.col,
      payload.slot.side
    );

    const prod = this.products.find(
      (p) =>
        p.product_id.toLowerCase() === payload.product_id.toLowerCase() ||
        p.barcode.toLowerCase() === payload.barcode.toLowerCase()
    );

    if (prod) {
      prod.loc_id = slotName;
    } else {
      this.products.push({
        product_id: payload.product_id,
        product_name: payload.product_name,
        barcode: payload.barcode || payload.product_id,
        on_hand: payload.quantity,
        loc_id: slotName,
      });
    }

    this.save();
    return {
      success: true,
      message: `Assigned ${payload.product_id} to ${slotName} (Qty: ${payload.quantity})`,
    };
  }

  async directMoveLocation(productId: string, targetSlot: AssignLocationPayload['slot']): Promise<ApiResponse> {
    const slotName = makeSlotName(
      targetSlot.floor,
      targetSlot.shelf,
      targetSlot.row,
      targetSlot.col,
      targetSlot.side
    );
    const prod = this.products.find((p) => p.product_id.toLowerCase() === productId.toLowerCase());
    if (!prod) {
      return { success: false, error: `Product ${productId} not found` };
    }
    prod.loc_id = slotName;
    this.save();
    return { success: true, message: `Moved ${productId} to ${slotName}` };
  }

  async transferCells(payload: TransferCellPayload): Promise<ApiResponse> {
    const srcSlot = `${payload.source_shelf}${payload.source_row}-${payload.source_col}`;
    const dstSlot = `${payload.target_shelf}${payload.target_row}-${payload.target_col}`;

    const srcProducts = this.products.filter((p) => p.loc_id === srcSlot);
    const dstProducts = this.products.filter((p) => p.loc_id === dstSlot);

    if (payload.action === 'switch') {
      srcProducts.forEach((p) => (p.loc_id = dstSlot));
      dstProducts.forEach((p) => (p.loc_id = srcSlot));
    } else if (payload.action === 'combine') {
      srcProducts.forEach((p) => (p.loc_id = dstSlot));
    }

    this.save();
    return {
      success: true,
      message:
        payload.action === 'switch'
          ? `Swapped contents between ${srcSlot} and ${dstSlot}`
          : `Combined ${srcSlot} into ${dstSlot}`,
    };
  }

  async removePlacement(productId: string, locId: string): Promise<ApiResponse> {
    const prod = this.products.find((p) => p.product_id === productId && p.loc_id === locId);
    if (prod) {
      prod.loc_id = null;
      this.save();
      return { success: true, message: `Removed ${productId} from ${locId}` };
    }
    return { success: false, error: 'Placement not found' };
  }

  async importCSV(
    csvData: CSVData,
    mapping: CSVColumnMapping,
    mode: 'new' | 'return'
  ): Promise<ApiResponse<{ imported: number }>> {
    let count = 0;
    for (const row of csvData.rows) {
      const code = formatProductId(row[mapping.code_col] || '');
      const name = row[mapping.name_col] || 'Chưa đặt tên';
      const qty = parseInt(row[mapping.qty_col] || '1', 10) || 1;
      const loc = mapping.loc_col ? row[mapping.loc_col] : null;

      if (!code) continue;

      const existing = this.products.find((p) => p.product_id === code);
      if (existing) {
        existing.on_hand += qty;
        if (loc && mode === 'new') existing.loc_id = loc;
      } else {
        this.products.push({
          product_id: code,
          product_name: name,
          barcode: code.replace(/-/g, ''),
          on_hand: qty,
          loc_id: loc || null,
        });
      }
      count++;
    }
    this.save();
    return { success: true, data: { imported: count }, message: `Imported ${count} items` };
  }

  async findProduct(query: string): Promise<{ product: Product | null; location: string | null }> {
    const term = formatProductId(query.toLowerCase());
    const prod = this.products.find(
      (p) =>
        p.product_id.toLowerCase().includes(term) ||
        p.barcode.toLowerCase().includes(term) ||
        p.product_name.toLowerCase().includes(term)
    );
    if (prod) {
      return { product: prod, location: prod.loc_id };
    }
    return { product: null, location: null };
  }
}

const localBackend = new StorageBackend();

export const ApiService = {
  async getShelves(): Promise<Shelf[]> {
    try {
      const res = await fetch(`${API_BASE_URL}/shelves`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.getShelves();
  },

  async saveShelf(shelf: Shelf): Promise<Shelf & { error?: string }> {
    try {
      const res = await fetch(`${API_BASE_URL}/shelves`, {
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
      const res = await fetch(`${API_BASE_URL}/shelves/${shelfId}`, { method: 'DELETE' });
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
      const res = await fetch(`${API_BASE_URL}/products/catalog`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.getCatalog();
  },

  async getPendingQueue(): Promise<OnHandProduct[]> {
    try {
      const res = await fetch(`${API_BASE_URL}/products/pending-queue`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.getPendingQueue();
  },

  async getPrimalQueue(): Promise<PrimalQueueItem[]> {
    try {
      const res = await fetch(`${API_BASE_URL}/products/primal-queue`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.getPrimalQueue();
  },

  async getShelfCells(shelfCode: string): Promise<Record<string, ShelfCell>> {
    try {
      const res = await fetch(`${API_BASE_URL}/shelves/${shelfCode}/cells`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.getShelfCells(shelfCode);
  },

  async assignLocation(payload: AssignLocationPayload): Promise<ApiResponse> {
    try {
      const res = await fetch(`${API_BASE_URL}/assignments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.assignLocation(payload);
  },

  async directMoveLocation(productId: string, targetSlot: AssignLocationPayload['slot']): Promise<ApiResponse> {
    try {
      const res = await fetch(`${API_BASE_URL}/assignments/direct-move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, slot: targetSlot }),
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.directMoveLocation(productId, targetSlot);
  },

  async transferCells(payload: TransferCellPayload): Promise<ApiResponse> {
    try {
      const res = await fetch(`${API_BASE_URL}/assignments/transfer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.transferCells(payload);
  },

  async removePlacement(productId: string, locId: string): Promise<ApiResponse> {
    try {
      const res = await fetch(`${API_BASE_URL}/assignments/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: productId, loc_id: locId }),
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.removePlacement(productId, locId);
  },

  async importCSV(
    csvData: CSVData,
    mapping: CSVColumnMapping,
    mode: 'new' | 'return'
  ): Promise<ApiResponse<{ imported: number }>> {
    try {
      const res = await fetch(`${API_BASE_URL}/import-csv`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: csvData, mapping, mode }),
      });
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.importCSV(csvData, mapping, mode);
  },

  async findProductLocation(query: string): Promise<{ product: Product | null; location: string | null }> {
    try {
      const res = await fetch(`${API_BASE_URL}/products/find?q=${encodeURIComponent(query)}`);
      if (res.ok) return await res.json();
    } catch {
      // Fallback
    }
    return localBackend.findProduct(query);
  },

  async getOnHandProducts(): Promise<OnHandProduct[]> {
    try {
      const res = await fetch(`${API_BASE_URL}/products/on-hand`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getOnHandProducts error:', e);
    }
    return [];
  },

  async addToOnHand(productIds: string[], quantities: Record<string, number> = {}): Promise<ApiResponse> {
    const items = productIds.map((pid) => ({
      product_id: pid,
      quantity: quantities[pid] !== undefined ? quantities[pid] : null,
    }));
    const res = await fetch(`${API_BASE_URL}/on-hand/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    return await res.json();
  },

  async dequeueOnHand(productIds: string[]): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/on-hand/dequeue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async updateOnHandStock(productId: string, quantity: number | null): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/on-hand/update-stock`, {
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
    const res = await fetch(`${API_BASE_URL}/slot-address?${query}`);
    return await res.json();
  },

  async assignOnHandToSlot(slotId: number, productIds: string[]): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/assignments/assign-on-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async moveSlotToOnHand(slotId: number, productIds: string[] | null = null): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/slot-contents/move-to-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async updateSlotStock(slotId: number, productId: string, quantity: number | null): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/slot-contents/update-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_id: productId, quantity }),
    });
    return await res.json();
  },

  async transferCatalogToQueue(productIds: string[]): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/catalog/transfer-to-queue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async connectChrome(): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE_URL}/web/connect-chrome`, { method: 'POST' });
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
    const res = await fetch(`${API_BASE_URL}/web/modify-location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  },

  async getPendingExceptions(): Promise<{ success: boolean; count: number; items: any[] }> {
    try {
      const res = await fetch(`${API_BASE_URL}/exceptions/pending`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getPendingExceptions error:', e);
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
    const res = await fetch(`${API_BASE_URL}/exceptions/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return await res.json();
  },

  async appendExceptionsToCSV(csvPath?: string): Promise<ApiResponse<{ count: number }>> {
    const res = await fetch(`${API_BASE_URL}/exceptions/append-csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_path: csvPath }),
    });
    return await res.json();
  },
};
