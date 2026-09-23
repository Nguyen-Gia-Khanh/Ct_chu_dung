import { useState, useEffect, useMemo, useDeferredValue } from 'react';
import { Shelf, Product, ShelfCell, PrimalQueueItem } from '../types';
import { ApiService } from '../services/api';
import { parseSlotName, formatProductId, normalizeSearch, getShelfCode } from '../utils/coordinates';

export function usePrimalQueueController(active: boolean) {
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [currentShelf, setCurrentShelf] = useState<Shelf | null>(null);
  const [cellsData, setCellsData] = useState<Record<string, ShelfCell>>({});
  const [primalQueue, setPrimalQueue] = useState<PrimalQueueItem[]>([]);
  const [catalog, setCatalog] = useState<Product[]>([]);

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
    const [shelfList, queue, cats] = await Promise.all([
      ApiService.getShelves(),
      ApiService.getPrimalQueue(),
      ApiService.getCatalog(),
    ]);
    setShelves(shelfList);
    setPrimalQueue(queue);
    setCatalog(cats);

    if (shelfList.length > 0) {
      selectShelf(shelfList[0]);
    }
  };

  const selectShelf = async (shelf: Shelf) => {
    setCurrentShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsData(cells);
    setSelectedCellLoc(null);
    setSelectedRow(null);
    setSelectedCol(null);
  };

  // Barcode search
  const handleSearchChange = (val: string) => {
    const formatted = formatProductId(val);
    setSearchQuery(formatted);

    const term = normalizeSearch(formatted);
    const found = catalog.find(
      (p) =>
        normalizeSearch(p.product_id) === term ||
        normalizeSearch(p.barcode) === term ||
        p.product_id.replace(/-/g, '').toLowerCase() === term.replace(/-/g, '')
    );

    if (found && found.loc_id) {
      const parsed = parseSlotName(found.loc_id);
      if (parsed) {
        const matchShelf = shelves.find(
          (s) =>
            s.floor === parsed.floor &&
            s.side === parsed.side &&
            s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
        );
        if (matchShelf && matchShelf.id !== currentShelf?.id) {
          selectShelf(matchShelf);
        }
        setSelectedCellLoc(found.loc_id);
        setSelectedRow(parsed.row);
        setSelectedCol(parsed.col);
      }
    }
  };

  const handleSelectProduct = (locId?: string) => {
    if (!locId) return;
    const parsed = parseSlotName(locId);
    if (!parsed) return;

    const matchShelf = shelves.find(
      (s) =>
        s.floor === parsed.floor &&
        s.side === parsed.side &&
        s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
    );

    if (matchShelf) {
      if (matchShelf.id !== currentShelf?.id) {
        selectShelf(matchShelf);
      }
      setSelectedCellLoc(locId);
      setSelectedRow(parsed.row);
      setSelectedCol(parsed.col);
    }
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
      const updatedCats = await ApiService.getCatalog();
      setCatalog(updatedCats);
    }
  };

  const deferredSearch = useDeferredValue(searchQuery);
  const filteredQueue = useMemo(() => {
    const term = normalizeSearch(deferredSearch);
    if (!term) return primalQueue;
    return primalQueue.filter((item) =>
      normalizeSearch(item.barcode).includes(term) ||
      normalizeSearch(item.product_name).includes(term) ||
      Boolean(item.target_location && normalizeSearch(item.target_location).includes(term)),
    );
  }, [primalQueue, deferredSearch]);

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
    activeCellItems,
  };
}
