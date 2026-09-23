import { useState, useEffect, useMemo, useDeferredValue } from 'react';
import { ApiService } from '../services/api';
import { WorkingBatchProduct } from '../types';

interface PendingItem {
  id: number;
  product_id: string;
  product_name: string;
  slot_id: number;
  slot_name: string;
  created_at: string;
}

interface CellItem {
  product_id: string;
  product_name: string;
  stock_qty: number | null;
  assigned_at: string;
}


export function useExceptionsController(active: boolean) {
  // Input fields
  const [productId, setProductId] = useState<string>('');
  const [stockQty, setStockQty] = useState<string>('');
  const [floor, setFloor] = useState<string>('1');
  const [side, setSide] = useState<string>('1');
  const [shelf, setShelf] = useState<string>('A');
  const [row, setRow] = useState<string>('1');
  const [col, setCol] = useState<string>('1');

  // Loaded address state
  const [loadedSlotName, setLoadedSlotName] = useState<string>('');
  const [loadedSlotId, setLoadedSlotId] = useState<number | null>(null);
  const [loadedSlotItems, setLoadedSlotItems] = useState<CellItem[]>([]);
  const [loadedSlotMessage, setLoadedSlotMessage] = useState<string>('No cell loaded. Enter address and click Load address.');

  // Data lists
  const [onHandList, setOnHandList] = useState<WorkingBatchProduct[]>([]);
  const [onHandSearch, setOnHandSearch] = useState<string>('');
  const [pendingItems, setPendingItems] = useState<PendingItem[]>([]);
  const [statusMessage, setStatusMessage] = useState<string>('Ready. Enter product ID and load an address to assign.');
  const [isBusy, setIsBusy] = useState<boolean>(false);

  useEffect(() => {
    if (!active) return;
    loadOnHand();
    loadPending();
  }, [active]);

  const loadOnHand = async () => {
    try {
      const items = await ApiService.getOnHandProducts();
      setOnHandList(items);
    } catch {
      // Ignore error
    }
  };

  const loadPending = async () => {
    try {
      const res = await ApiService.getPendingExceptions();
      if (res && res.items) {
        setPendingItems(res.items);
      }
    } catch {
      // Ignore error
    }
  };

  const handleLoadAddress = async () => {
    const r = parseInt(row, 10);
    const c = parseInt(col, 10);
    if (isNaN(r) || isNaN(c) || r < 1 || c < 1) {
      alert('Row and cell must be positive whole numbers.');
      return;
    }

    try {
      const res = await ApiService.getSlotAddress(floor, side, shelf, r, c);
      if (res && res.success && res.slot) {
        setLoadedSlotId(res.slot.slot_id);
        setLoadedSlotName(res.slot.slot_name);
        setLoadedSlotItems(res.contents || []);
        setLoadedSlotMessage(`Loaded: ${res.slot.slot_name} · ${(res.contents || []).length} product(s)`);
      } else {
        setLoadedSlotId(null);
        setLoadedSlotName('');
        setLoadedSlotItems([]);
        setLoadedSlotMessage(res?.message || `No cell found at Floor ${floor} / Side ${side} / Shelf ${shelf} / R${r}-C${c}.`);
      }
    } catch (e: any) {
      alert(`Failed to load address: ${e.message}`);
    }
  };

  const handleAssignException = async () => {
    const trimmedId = productId.trim();
    if (!trimmedId) {
      alert('Please enter or scan a product ID.');
      return;
    }

    const r = parseInt(row, 10);
    const c = parseInt(col, 10);
    if (isNaN(r) || isNaN(c) || r < 1 || c < 1) {
      alert('Row and cell must be positive whole numbers.');
      return;
    }

    const qty = stockQty.trim() !== '' ? parseInt(stockQty, 10) : null;
    if (qty !== null && (isNaN(qty) || qty < 0)) {
      alert('Stock quantity must be a whole number of 0 or greater, or left blank.');
      return;
    }

    setIsBusy(true);
    try {
      const res = await ApiService.assignException({
        product_id: trimmedId,
        floor,
        side,
        shelf,
        row: r,
        col: c,
        quantity: qty,
      });

      if (res && res.success) {
        setStatusMessage(res.message || `Assigned ${trimmedId} to ${res.slot_name}.`);
        setProductId('');
        setStockQty('');
        // Refresh cell contents and lists
        await handleLoadAddress();
        await loadPending();
        await loadOnHand();
      } else {
        alert(res?.error || res?.message || 'Failed to assign exception.');
      }
    } catch (e: any) {
      alert(`Assignment error: ${e.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const handleAppendToCSV = async () => {
    if (pendingItems.length === 0) {
      alert('There are no staged exception products waiting to update.');
      return;
    }

    const targetCsv = prompt('Enter CSV filename or path to append exception products (leave blank for full_catalogue.csv):', '');
    if (targetCsv === null) {
      return; // Cancelled
    }

    setIsBusy(true);
    try {
      const res = await ApiService.appendExceptionsToCSV(targetCsv.trim() || undefined);
      if (res && res.success) {
        alert(res.message || `Successfully appended ${(res as any).count} exception(s) to CSV with name 'Exc - added later'.`);
        setStatusMessage(res.message || 'Appended exceptions to CSV.');
        await loadPending();
        await loadOnHand();
      } else {
        alert(res?.error || res?.message || 'Failed to append to CSV.');
      }
    } catch (e: any) {
      alert(`Append to CSV error: ${e.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const deferredSearch = useDeferredValue(onHandSearch);
  const filteredOnHand = useMemo(() => {
    const term = deferredSearch.toLowerCase();
    return onHandList.filter((item) =>
      !term || item.product_id.toLowerCase().includes(term) || item.product_name.toLowerCase().includes(term),
    );
  }, [onHandList, deferredSearch]);

  return {
    productId,
    setProductId,
    stockQty,
    setStockQty,
    floor,
    setFloor,
    side,
    setSide,
    shelf,
    setShelf,
    row,
    setRow,
    col,
    setCol,
    loadedSlotName,
    loadedSlotId,
    loadedSlotItems,
    loadedSlotMessage,
    onHandSearch,
    setOnHandSearch,
    pendingItems,
    statusMessage,
    isBusy,
    handleLoadAddress,
    handleAssignException,
    handleAppendToCSV,
    filteredOnHand,
  };
}
