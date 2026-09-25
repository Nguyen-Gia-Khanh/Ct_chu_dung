import React, { useState, useEffect, useRef, useMemo, useDeferredValue } from 'react';
import { Product, ApiResponse, WorkingBatchProduct } from '../types';
import { ApiService } from '../services/api';
import { normalizeSearch } from '../utils/coordinates';

interface QueueItem {
  code: string;
  name: string;
  on_hand: number;
  returned?: boolean;
}

interface SlotInfo {
  slot_id: number;
  floor: number;
  side: number;
  shelf: string;
  row: number;
  col: number;
  slot_name: string;
}

interface LoadedSlotContent {
  product_id: string;
  product_name: string;
  stock_qty: number;
  assigned_at: string;
}


export function useLocationAssignmentController(active: boolean) {
  // Data State
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [pendingQueue, setPendingQueue] = useState<QueueItem[]>([]);
  const [onHandProducts, setOnHandProducts] = useState<WorkingBatchProduct[]>([]);

  // Selection states (multi-select arrays of IDs)
  const [selectedQueueIds, setSelectedQueueIds] = useState<string[]>([]);
  const [selectedCatalogIds, setSelectedCatalogIds] = useState<string[]>([]);
  const [selectedOnHandIds, setSelectedOnHandIds] = useState<string[]>([]);
  const [selectedContentIds, setSelectedContentIds] = useState<string[]>([]);

  // Refs to track anchor row for Shift-click range selection
  const lastQueueIdRef = useRef<string | null>(null);
  const lastCatIdRef = useRef<string | null>(null);
  const lastHandIdRef = useRef<string | null>(null);
  const lastContentIdRef = useRef<string | null>(null);

  // Search & dynamic location indicator
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchLocationText, setSearchLocationText] = useState<string>('');

  // Target Location Inputs (default 1-1-A-1-1)
  const [floor, setFloor] = useState<string | number>(1);
  const [side, setSide] = useState<string | number>(1);
  const [shelf, setShelf] = useState<string>('A');
  const [row, setRow] = useState<number>(1);
  const [col, setCol] = useState<number>(1);

  // Loaded slot state
  const [loadedSlot, setLoadedSlot] = useState<SlotInfo | null>(null);
  const [loadedContents, setLoadedContents] = useState<LoadedSlotContent[]>([]);
  const [addressStatusText, setAddressStatusText] = useState<string>('Enter an existing shelf address and load it.');

  // Web options
  const [webBatchMode, setWebBatchMode] = useState<boolean>(false);
  const [uploadStatusText, setUploadStatusText] = useState<string>('');
  const [copyStatusText, setCopyStatusText] = useState<string>('Double-click a row to copy its Product ID.');

  useEffect(() => {
    if (!active) return;
    refreshData();
    if (loadedSlot) handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    else handleLoadAddressDirect('1', '1', 'A', 1, 1);
  }, [active]);

  const refreshData = async () => {
    const [cats, pends, hands] = await Promise.all([
      ApiService.getCatalog(),
      ApiService.getPendingQueue() as unknown as Promise<QueueItem[]>,
      ApiService.getOnHandProducts(),
    ]);
    setCatalog(cats);
    setPendingQueue(pends || []);
    setOnHandProducts(hands || []);
  };

  // Live location check based on search query matching Tkinter logic
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchLocationText('');
      return;
    }
    const term = normalizeSearch(q);
    const inHand = onHandProducts.find(
      (h) => normalizeSearch(h.product_id) === term || normalizeSearch(h.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inHand) {
      setSearchLocationText(`In on-hand queue · stock ${inHand.stock_qty != null ? inHand.stock_qty : 'Unknown'}`);
      return;
    }
    const inCat = catalog.find(
      (c) => normalizeSearch(c.product_id) === term || normalizeSearch(c.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inCat && inCat.loc_id) {
      setSearchLocationText(`Already at ${inCat.loc_id}`);
      return;
    }
    const inPend = pendingQueue.find(
      (p) => normalizeSearch(p.code) === term || normalizeSearch(p.code.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inPend && inPend.returned) {
      setSearchLocationText(`In total queue · returned stock ${inPend.on_hand != null ? inPend.on_hand : 'Unknown'}`);
      return;
    }
    if (inCat && !inCat.loc_id) {
      setSearchLocationText('Not assigned to any location.');
      return;
    }
    setSearchLocationText('');
  }, [searchQuery, catalog, pendingQueue, onHandProducts]);

  const handleTableSelect = (
    id: string,
    allIds: string[],
    selectedList: string[],
    setSelectedList: React.Dispatch<React.SetStateAction<string[]>>,
    lastRef: React.MutableRefObject<string | null>,
    e?: React.MouseEvent
  ) => {
    if (e && e.shiftKey && lastRef.current && allIds.includes(lastRef.current)) {
      const startIdx = allIds.indexOf(lastRef.current);
      const endIdx = allIds.indexOf(id);
      if (startIdx !== -1 && endIdx !== -1) {
        const [low, high] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
        const range = allIds.slice(low, high + 1);
        const combined = Array.from(new Set([...selectedList, ...range]));
        setSelectedList(combined);
        return;
      }
    }
    lastRef.current = id;
    if (e && (e.ctrlKey || e.metaKey)) {
      setSelectedList((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    } else {
      setSelectedList((prev) => (prev.length === 1 && prev[0] === id ? [] : [id]));
    }
  };

  const handleMoveSelectedToOnHand = async () => {
    if (selectedQueueIds.length === 0) return;
    const res = await ApiService.addToOnHand(selectedQueueIds);
    if (res.success) {
      setSelectedQueueIds([]);
      await refreshData();
    }
  };

  const handleTransferSelectedToQueue = async () => {
    if (selectedCatalogIds.length === 0) return;
    const res = await ApiService.transferCatalogToQueue(selectedCatalogIds);
    if (res.success) {
      setSelectedCatalogIds([]);
      await refreshData();
    }
  };

  const handleCatalogDoubleClick = (productId: string) => {
    setSearchQuery(productId);
  };

  const handleEditSelectedQuantity = async () => {
    if (selectedOnHandIds.length !== 1) return;
    const pid = selectedOnHandIds[0];
    const item = onHandProducts.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : '';
    const val = window.prompt(`Product: ${pid}\nCurrent stock: ${curr !== '' ? curr : '(null)'}\n\nEnter the new whole-number quantity (or empty for null):`, String(curr));
    if (val === null) return;
    const newQty = val.trim() === '' ? 0 : parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateOnHandStock(pid, newQty);
      await refreshData();
    }
  };

  const handleDequeueOnHand = async () => {
    if (selectedOnHandIds.length === 0) return;
    const res = await ApiService.dequeueOnHand(selectedOnHandIds);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
    }
  };

  const handleLoadAddressDirect = async (
    f: string | number,
    s: string | number,
    sh: string,
    r: string | number,
    c: string | number
  ) => {
    const res = await ApiService.getSlotAddress(f, s, sh, r, c) as ApiResponse & {
      slot?: SlotInfo;
      contents?: LoadedSlotContent[];
    };
    if (res.success && res.slot) {
      setLoadedSlot(res.slot);
      setLoadedContents(res.contents || []);
      setAddressStatusText(res.message || `Loaded ${res.slot.slot_name}`);
    } else {
      setLoadedSlot(null);
      setLoadedContents([]);
      setAddressStatusText(res.message || `No saved cell at Floor ${f} / Side ${s} / Shelf ${sh} / Row ${r} / Cell ${c}.`);
    }
  };

  const handleLoadAddress = async () => {
    await handleLoadAddressDirect(floor, side, shelf, row, col);
  };

  const handleAssignAddress = async () => {
    if (!loadedSlot) {
      alert('Enter the shelf address and press Load address first.');
      return;
    }
    const pids = selectedOnHandIds.length > 0 ? selectedOnHandIds : onHandProducts.map((p) => p.product_id);
    if (pids.length === 0) {
      alert('Select one or more on-hand products with click first.');
      return;
    }
    const res = await ApiService.assignOnHandToSlot(loadedSlot.slot_id, pids);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    } else {
      alert(res.error || 'Assignment failed');
    }
  };

  const handleCopyProductId = (productId: string) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(productId);
      setCopyStatusText(`Copied ${productId} to clipboard.`);
    }
  };

  const handleModifyLoadedStock = async () => {
    if (selectedContentIds.length !== 1 || !loadedSlot) return;
    const pid = selectedContentIds[0];
    const item = loadedContents.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : '';
    const val = window.prompt(
      `Product: ${pid}\nLocation: ${loadedSlot.slot_name}\nCurrent stock: ${curr !== '' ? curr : '(null)'}\n\nEnter the new whole-number quantity (or empty for null):`,
      String(curr)
    );
    if (val === null) return;
    const newQty = val.trim() === '' ? 0 : parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateSlotStock(loadedSlot.slot_id, pid, newQty);
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleSelectedToHand = async () => {
    if (!loadedSlot || selectedContentIds.length === 0) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id, selectedContentIds);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleShelfAllToHand = async () => {
    if (!loadedSlot || loadedContents.length === 0) return;
    if (!window.confirm(`Move all ${loadedContents.length} product(s) from ${loadedSlot.slot_name} to on-hand?`)) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleModifyLocationWeb = async () => {
    if (!loadedSlot) return;
    const targetPids = webBatchMode ? loadedContents.map((c) => c.product_id) : selectedContentIds;
    if (targetPids.length === 0) return;
    const res = await ApiService.modifyLocationWeb(targetPids, loadedSlot.slot_name);
    setUploadStatusText(res.message || 'Updated web location.');
  };

  const handleConnectChrome = async () => {
    const res = await ApiService.connectChrome();
    setUploadStatusText(res.message || 'Chrome connection initiated.');
  };

  const deferredSearch = useDeferredValue(searchQuery);
  const searchTerm = useMemo(() => normalizeSearch(deferredSearch), [deferredSearch]);
  const filteredPending = useMemo(() => pendingQueue.filter((product) =>
    !searchTerm || normalizeSearch(product.code).includes(searchTerm) || normalizeSearch(product.name).includes(searchTerm),
  ), [pendingQueue, searchTerm]);
  const filteredCatalog = useMemo(() => catalog.filter((product) =>
    !searchTerm || normalizeSearch(product.product_id).includes(searchTerm) ||
    normalizeSearch(product.barcode).includes(searchTerm) ||
    normalizeSearch(product.product_name).includes(searchTerm) ||
    (product.loc_id ? normalizeSearch(product.loc_id).includes(searchTerm) : false),
  ), [catalog, searchTerm]);
  const visiblePending = useMemo(() => filteredPending.slice(0, 100), [filteredPending]);
  const visibleCatalog = useMemo(() => filteredCatalog.slice(0, 100), [filteredCatalog]);
  const pendingIds = useMemo(() => visiblePending.map((item) => item.code), [visiblePending]);
  const catalogIds = useMemo(() => visibleCatalog.map((item) => item.product_id), [visibleCatalog]);
  const onHandIds = useMemo(() => onHandProducts.map((item) => item.product_id), [onHandProducts]);
  const loadedContentIds = useMemo(() => loadedContents.map((item) => item.product_id), [loadedContents]);

  return {
    catalog,
    onHandProducts,
    selectedQueueIds,
    setSelectedQueueIds,
    selectedCatalogIds,
    setSelectedCatalogIds,
    selectedOnHandIds,
    setSelectedOnHandIds,
    selectedContentIds,
    setSelectedContentIds,
    lastQueueIdRef,
    lastCatIdRef,
    lastHandIdRef,
    lastContentIdRef,
    searchQuery,
    setSearchQuery,
    searchLocationText,
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
    loadedSlot,
    loadedContents,
    addressStatusText,
    webBatchMode,
    setWebBatchMode,
    uploadStatusText,
    copyStatusText,
    handleTableSelect,
    handleMoveSelectedToOnHand,
    handleTransferSelectedToQueue,
    handleCatalogDoubleClick,
    handleEditSelectedQuantity,
    handleDequeueOnHand,
    handleLoadAddress,
    handleAssignAddress,
    handleCopyProductId,
    handleModifyLoadedStock,
    handleSelectedToHand,
    handleShelfAllToHand,
    handleModifyLocationWeb,
    handleConnectChrome,
    filteredPending,
    filteredCatalog,
    visiblePending,
    visibleCatalog,
    pendingIds,
    catalogIds,
    onHandIds,
    loadedContentIds,
  };
}
