import { useState, useEffect, useMemo, useDeferredValue, useRef } from 'react';
import { Shelf, Product, ShelfCell, PrimalQueueItem } from '../types';
import { ApiService } from '../services/api';
import { parseSlotName, formatProductId, normalizeSearch, getShelfCode } from '../utils/coordinates';

export function usePrimalQueueController(active: boolean) {
  const rowHeight = 34;
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [currentShelf, setCurrentShelf] = useState<Shelf | null>(null);
  const [cellsData, setCellsData] = useState<Record<string, ShelfCell>>({});
  const [primalQueue, setPrimalQueue] = useState<PrimalQueueItem[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [catalog, setCatalog] = useState<Product[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [queueScrollTop, setQueueScrollTop] = useState(0);
  const [queueViewportHeight, setQueueViewportHeight] = useState(520);
  const [catalogScrollTop, setCatalogScrollTop] = useState(0);
  const [catalogViewportHeight, setCatalogViewportHeight] = useState(250);
  const shelfRequest = useRef(0);

  // Search & Selection
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCellLoc, setSelectedCellLoc] = useState<string | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);

  useEffect(() => {
    if (!active) return;
    loadInitialData();
  }, [active]);

  const loadInitialData = async () => {
    setQueueLoading(true);
    const [shelfList, queue] = await Promise.all([
      ApiService.getShelves(),
      ApiService.getPrimalQueue(),
    ]);
    setShelves(shelfList);
    setPrimalQueue(queue);
    setQueueLoading(false);
    // Populate the second Tkinter-style list after the queue is ready to render.
    if (catalog.length === 0) {
      setCatalogLoading(true);
      void ApiService.getCatalog().then(setCatalog).finally(() => setCatalogLoading(false));
    }

    if (shelfList.length > 0) {
      const shelfToShow = shelfList.find((shelf) => shelf.id === currentShelf?.id) || shelfList[0];
      void selectShelf(shelfToShow, shelfToShow.id === currentShelf?.id ? selectedCellLoc || undefined : undefined);
    }
  };

  const selectShelf = async (shelf: Shelf, selectedLocation?: string) => {
    const request = ++shelfRequest.current;
    setCurrentShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    if (request !== shelfRequest.current) return;
    setCellsData(cells);
    const parsed = selectedLocation ? parseSlotName(selectedLocation) : null;
    setSelectedCellLoc(parsed ? selectedLocation! : null);
    setSelectedRow(parsed?.row ?? null);
    setSelectedCol(parsed?.col ?? null);
  };

  const selectLocation = (locId?: string | null) => {
    if (!locId) return;
    const parsed = parseSlotName(locId);
    if (!parsed) return;
    const matchShelf = shelves.find(
      (s) => s.floor === parsed.floor && s.side === parsed.side &&
        s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
    );
    if (!matchShelf) return;
    if (matchShelf.id !== currentShelf?.id) {
      void selectShelf(matchShelf, locId);
    } else {
      setSelectedCellLoc(locId);
      setSelectedRow(parsed.row);
      setSelectedCol(parsed.col);
    }
  };

  // Barcode search
  const handleSearchChange = (val: string) => {
    const formatted = formatProductId(val);
    setSearchQuery(formatted);
    setQueueScrollTop(0);
    setCatalogScrollTop(0);

    const term = normalizeSearch(formatted);
    const compact = term.replace(/-/g, '');
    const found = compact.length >= 9 ? primalQueue.find(
      (item) => normalizeSearch(item.barcode).replace(/-/g, '') === compact
    ) : undefined;
    const catalogHit = compact.length >= 9 ? catalog.find(
      (item) => normalizeSearch(item.product_id).replace(/-/g, '') === compact
    ) : undefined;
    selectLocation(found?.target_location || catalogHit?.loc_id);
  };

  // Look up catalog-only products after a complete scan without loading the catalog.
  useEffect(() => {
    if (!active) return;
    const term = normalizeSearch(searchQuery).replace(/-/g, '');
    if (term.length < 9 || primalQueue.some((item) => normalizeSearch(item.barcode).replace(/-/g, '') === term) ||
      catalog.some((item) => normalizeSearch(item.product_id).replace(/-/g, '') === term)) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const result = await ApiService.findProductLocation(searchQuery);
      if (!cancelled && result.location) selectLocation(result.location);
    }, 300);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [active, searchQuery, primalQueue, catalog, shelves]);

  const handleSelectProduct = (locId?: string) => {
    selectLocation(locId);
  };

  const handleCellClick = (row: number, col: number, locId: string) => {
    setSelectedRow(row);
    setSelectedCol(col);
    setSelectedCellLoc(locId);
  };

  const handleRemoveProduct = async (productId: string) => {
    if (!selectedCellLoc) return;
    if (confirm(`Remove ${productId} from ${selectedCellLoc}?`)) {
      await ApiService.removePlacement(productId, selectedCellLoc);
      if (currentShelf) {
        const code = getShelfCode(currentShelf.floor, currentShelf.side, currentShelf.shelf);
        const cells = await ApiService.getShelfCells(code);
        setCellsData(cells);
      }
      setPrimalQueue(await ApiService.getPrimalQueue());
      setCatalog(await ApiService.getCatalog());
    }
  };

  const deferredSearch = useDeferredValue(searchQuery);
  const filteredQueue = useMemo(() => {
    const term = normalizeSearch(deferredSearch);
    if (!term) return primalQueue;
    const compact = term.replace(/-/g, '');
    return primalQueue.filter((item) =>
      normalizeSearch(item.barcode).replace(/-/g, '').includes(compact) ||
      normalizeSearch(item.product_name).includes(term) ||
      Boolean(item.target_location && normalizeSearch(item.target_location).includes(term)),
    );
  }, [primalQueue, deferredSearch]);

  const filteredCatalog = useMemo(() => {
    const term = normalizeSearch(deferredSearch);
    if (!term) return catalog;
    const compact = term.replace(/-/g, '');
    return catalog.filter((item) =>
      normalizeSearch(item.product_id).replace(/-/g, '').includes(compact) ||
      normalizeSearch(item.product_name).includes(term) ||
      Boolean(item.loc_id && normalizeSearch(item.loc_id).includes(term)),
    );
  }, [catalog, deferredSearch]);

  const firstVisibleRow = Math.max(0, Math.floor(queueScrollTop / rowHeight) - 8);
  const visibleRowCount = Math.ceil(queueViewportHeight / rowHeight) + 16;
  const visibleQueue = filteredQueue.slice(firstVisibleRow, firstVisibleRow + visibleRowCount);
  const topSpacerHeight = firstVisibleRow * rowHeight;
  const bottomSpacerHeight = Math.max(0, (filteredQueue.length - firstVisibleRow - visibleQueue.length) * rowHeight);
  const handleQueueScroll = (scrollTop: number, viewportHeight: number) => {
    setQueueScrollTop(scrollTop);
    setQueueViewportHeight(viewportHeight);
  };
  const firstVisibleCatalogRow = Math.max(0, Math.floor(catalogScrollTop / rowHeight) - 8);
  const catalogVisibleCount = Math.ceil(catalogViewportHeight / rowHeight) + 16;
  const visibleCatalog = filteredCatalog.slice(firstVisibleCatalogRow, firstVisibleCatalogRow + catalogVisibleCount);
  const catalogTopSpacerHeight = firstVisibleCatalogRow * rowHeight;
  const catalogBottomSpacerHeight = Math.max(0, (filteredCatalog.length - firstVisibleCatalogRow - visibleCatalog.length) * rowHeight);
  const handleCatalogScroll = (scrollTop: number, viewportHeight: number) => {
    setCatalogScrollTop(scrollTop);
    setCatalogViewportHeight(viewportHeight);
  };

  const activeCellItems = selectedCellLoc && cellsData[selectedCellLoc] ? cellsData[selectedCellLoc].items : [];

  return {
    shelves,
    currentShelf,
    cellsData,
    searchQuery,
    setSearchQuery,
    selectedCellLoc,
    selectedRow,
    selectedCol,
    selectShelf,
    handleSearchChange,
    handleSelectProduct,
    handleCellClick,
    handleRemoveProduct,
    filteredQueue,
    queueLoading,
    filteredCatalog,
    catalogLoading,
    visibleQueue,
    topSpacerHeight,
    bottomSpacerHeight,
    handleQueueScroll,
    visibleCatalog,
    catalogTopSpacerHeight,
    catalogBottomSpacerHeight,
    handleCatalogScroll,
    activeCellItems,
  };
}
