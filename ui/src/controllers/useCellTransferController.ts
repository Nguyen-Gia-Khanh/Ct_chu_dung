import { useState, useEffect } from 'react';
import { Shelf, ShelfCell } from '../types';
import { ApiService } from '../services/api';
import { makeSlotName, parseSlotName, formatProductId, getShelfCode, normalizeSearch } from '../utils/coordinates';

export function useCellTransferController(active: boolean) {
  const [shelves, setShelves] = useState<Shelf[]>([]);

  // Pane A (Left)
  const [shelfA, setShelfA] = useState<Shelf | null>(null);
  const [rowA, setRowA] = useState<number>(1);
  const [colA, setColA] = useState<number>(1);
  const [cellsDataA, setCellsDataA] = useState<Record<string, ShelfCell>>({});
  const [searchA, setSearchA] = useState<string>('');
  const [selectedIdsA, setSelectedIdsA] = useState<string[]>([]);

  // Pane B (Right)
  const [shelfB, setShelfB] = useState<Shelf | null>(null);
  const [rowB, setRowB] = useState<number>(1);
  const [colB, setColB] = useState<number>(1);
  const [cellsDataB, setCellsDataB] = useState<Record<string, ShelfCell>>({});
  const [searchB, setSearchB] = useState<string>('');
  const [selectedIdsB, setSelectedIdsB] = useState<string[]>([]);

  // Center & Global Actions
  const [lastChangedProducts, setLastChangedProducts] = useState<Array<{ product_id: string; slot_name: string }>>([]);
  const [statusText, setStatusText] = useState<string>('Choose two cells.');
  const [webStatusText, setWebStatusText] = useState<string>('');
  const [isModifyingWeb, setIsModifyingWeb] = useState<boolean>(false);

  useEffect(() => {
    if (!active) return;
    loadShelves();
  }, [active]);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      if (!shelfA || !list.some((s) => s.id === shelfA.id)) {
        await handleSelectShelfA(list[0]);
      }
      if (!shelfB || !list.some((s) => s.id === shelfB.id)) {
        await handleSelectShelfB(list.length > 1 ? list[1] : list[0]);
      }
    }
  };

  const handleSelectShelfA = async (s: Shelf) => {
    setShelfA(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataA(cells);
    setRowA(1);
    setColA(1);
    setSelectedIdsA([]);
  };

  const handleSelectShelfB = async (s: Shelf) => {
    setShelfB(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataB(cells);
    setRowB(1);
    setColB(1);
    setSelectedIdsB([]);
  };

  const reloadBoth = async () => {
    if (shelfA) {
      const codeA = getShelfCode(shelfA.floor, shelfA.side, shelfA.shelf);
      const cA = await ApiService.getShelfCells(codeA);
      setCellsDataA(cA);
    }
    if (shelfB) {
      const codeB = getShelfCode(shelfB.floor, shelfB.side, shelfB.shelf);
      const cB = await ApiService.getShelfCells(codeB);
      setCellsDataB(cB);
    }
  };

  const slotLocA = shelfA ? makeSlotName(shelfA.floor, shelfA.shelf, rowA, colA, shelfA.side) : '';
  const slotLocB = shelfB ? makeSlotName(shelfB.floor, shelfB.shelf, rowB, colB, shelfB.side) : '';

  const cellA = slotLocA ? cellsDataA[slotLocA] : null;
  const cellB = slotLocB ? cellsDataB[slotLocB] : null;

  const itemsA = cellA?.items || [];
  const itemsB = cellB?.items || [];

  const handleFindA = async (query: string) => {
    await executeFind(query, 'A');
  };

  const handleFindB = async (query: string) => {
    await executeFind(query, 'B');
  };

  const executeFind = async (rawQuery: string, targetSide: 'A' | 'B') => {
    const q = rawQuery.trim();
    if (!q) return;
    const formatted = formatProductId(q);

    // 1. Try product search
    let res = await ApiService.findProductLocation(formatted);
    if ((!res.product || !res.location) && formatted !== q) {
      res = await ApiService.findProductLocation(q);
    }

    if (res.product && res.location) {
      const parsed = parseSlotName(res.location);
      if (parsed) {
        const foundShelf = shelves.find(
          (s) =>
            String(s.floor) === String(parsed.floor) &&
            String(s.side).toUpperCase() === String(parsed.side).toUpperCase() &&
            String(s.shelf).toUpperCase() === String(parsed.shelf).toUpperCase()
        );
        if (foundShelf) {
          if (targetSide === 'A') {
            await handleSelectShelfA(foundShelf);
            setRowA(parsed.row);
            setColA(parsed.col);
            setSelectedIdsA([res.product.product_id]);
            setSearchA(formatted);
          } else {
            await handleSelectShelfB(foundShelf);
            setRowB(parsed.row);
            setColB(parsed.col);
            setSelectedIdsB([res.product.product_id]);
            setSearchB(formatted);
          }
          return;
        }
      }
    }

    // 2. Try slot address
    const parsedSlot = parseSlotName(q);
    if (parsedSlot) {
      const foundShelf = shelves.find(
        (s) =>
          String(s.floor) === String(parsedSlot.floor) &&
          String(s.side).toUpperCase() === String(parsedSlot.side).toUpperCase() &&
          String(s.shelf).toUpperCase() === String(parsedSlot.shelf).toUpperCase()
      );
      if (foundShelf) {
        if (targetSide === 'A') {
          await handleSelectShelfA(foundShelf);
          setRowA(parsedSlot.row);
          setColA(parsedSlot.col);
        } else {
          await handleSelectShelfB(foundShelf);
          setRowB(parsedSlot.row);
          setColB(parsedSlot.col);
        }
        return;
      }
    }

    // 3. Try shelf name
    const norm = normalizeSearch(q);
    const matchedShelves = shelves.filter((s) => {
      const desc = normalizeSearch(`floor ${s.floor} side ${s.side} shelf ${s.shelf} ${s.floor}${s.side}${s.shelf}`);
      return desc.includes(norm);
    });
    if (matchedShelves.length === 1) {
      if (targetSide === 'A') {
        await handleSelectShelfA(matchedShelves[0]);
      } else {
        await handleSelectShelfB(matchedShelves[0]);
      }
      return;
    } else if (matchedShelves.length > 1) {
      alert('More than one shelf found. Use the Shelf dropdown to select the exact shelf.');
      return;
    }

    alert(`Product ID or location '${q}' was not found on any shelf.`);
  };

  const handleSwitchCells = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('The left and right selections point to the same shelf cell.');
      return;
    }

    const countA = itemsA.length;
    const countB = itemsB.length;
    const ok = window.confirm(
      `Switch complete cell contents?\n\n` +
        `Exchange all products in ${slotLocA} and ${slotLocB}?\n\n` +
        `${slotLocA}: ${countA} product(s)\n` +
        `${slotLocB}: ${countB} product(s)`
    );
    if (!ok) return;

    try {
      const res = await ApiService.transferCells({
        source_shelf: getShelfCode(shelfA.floor, shelfA.side, shelfA.shelf),
        source_row: rowA,
        source_col: colA,
        target_shelf: getShelfCode(shelfB.floor, shelfB.side, shelfB.shelf),
        target_row: rowB,
        target_col: colB,
        action: 'switch',
      });

      if (res.success) {
        setLastChangedProducts(res.changed_products || []);
        setStatusText(res.message || `Switched ${slotLocA} (${countA}) with ${slotLocB} (${countB}).`);
        setWebStatusText('');
        await reloadBoth();
      } else {
        setStatusText(`Error: ${res.error || 'Cells could not be switched.'}`);
      }
    } catch (err: any) {
      setStatusText(`Error: ${err.message || err}`);
    }
  };

  const handleCombineLeftRight = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('The left and right selections point to the same shelf cell.');
      return;
    }
    const countA = itemsA.length;
    const countB = itemsB.length;
    if (countA === 0) {
      setStatusText(`${slotLocA} is already empty.`);
      return;
    }

    const ok = window.confirm(
      `Combine complete cell contents?\n\n` +
        `Move all ${countA} product(s) from ${slotLocA} into ${slotLocB}?\n\n` +
        `The target's ${countB} current product(s) will remain.`
    );
    if (!ok) return;

    try {
      const res = await ApiService.transferCells({
        source_shelf: getShelfCode(shelfA.floor, shelfA.side, shelfA.shelf),
        source_row: rowA,
        source_col: colA,
        target_shelf: getShelfCode(shelfB.floor, shelfB.side, shelfB.shelf),
        target_row: rowB,
        target_col: colB,
        action: 'combine',
      });

      if (res.success) {
        setLastChangedProducts(res.changed_products || []);
        setStatusText(res.message || `Combined ${countA} product(s) from ${slotLocA} into ${slotLocB}.`);
        setWebStatusText('');
        await reloadBoth();
      } else {
        setStatusText(`Error: ${res.error || 'Cells could not be combined.'}`);
      }
    } catch (err: any) {
      setStatusText(`Error: ${err.message || err}`);
    }
  };

  const handleCombineRightLeft = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('The left and right selections point to the same shelf cell.');
      return;
    }
    const countA = itemsA.length;
    const countB = itemsB.length;
    if (countB === 0) {
      setStatusText(`${slotLocB} is already empty.`);
      return;
    }

    const ok = window.confirm(
      `Combine complete cell contents?\n\n` +
        `Move all ${countB} product(s) from ${slotLocB} into ${slotLocA}?\n\n` +
        `The target's ${countA} current product(s) will remain.`
    );
    if (!ok) return;

    try {
      const res = await ApiService.transferCells({
        source_shelf: getShelfCode(shelfB.floor, shelfB.side, shelfB.shelf),
        source_row: rowB,
        source_col: colB,
        target_shelf: getShelfCode(shelfA.floor, shelfA.side, shelfA.shelf),
        target_row: rowA,
        target_col: colA,
        action: 'combine',
      });

      if (res.success) {
        setLastChangedProducts(res.changed_products || []);
        setStatusText(res.message || `Combined ${countB} product(s) from ${slotLocB} into ${slotLocA}.`);
        setWebStatusText('');
        await reloadBoth();
      } else {
        setStatusText(`Error: ${res.error || 'Cells could not be combined.'}`);
      }
    } catch (err: any) {
      setStatusText(`Error: ${err.message || err}`);
    }
  };

  const handleModifyLocationWeb = async () => {
    if (!lastChangedProducts || lastChangedProducts.length === 0) {
      alert('No recent cell changes to modify on web. Please switch or combine cells first.');
      return;
    }
    setIsModifyingWeb(true);
    try {
      const res = await ApiService.modifyLocationWeb(lastChangedProducts);
      setWebStatusText(res.message || `Updated web location for ${lastChangedProducts.length} product(s).`);
    } catch (err: any) {
      setWebStatusText(`Error modifying web location: ${err.message || err}`);
    } finally {
      setIsModifyingWeb(false);
    }
  };

  const handleRefreshBoth = async () => {
    await loadShelves();
    await reloadBoth();
    setStatusText('Refreshed both shelves.');
  };

  return {
    shelves,
    shelfA,
    rowA,
    setRowA,
    colA,
    setColA,
    cellsDataA,
    searchA,
    setSearchA,
    selectedIdsA,
    setSelectedIdsA,
    shelfB,
    rowB,
    setRowB,
    colB,
    setColB,
    cellsDataB,
    searchB,
    setSearchB,
    selectedIdsB,
    setSelectedIdsB,
    statusText,
    webStatusText,
    isModifyingWeb,
    handleSelectShelfA,
    handleSelectShelfB,
    handleFindA,
    handleFindB,
    handleSwitchCells,
    handleCombineLeftRight,
    handleCombineRightLeft,
    handleModifyLocationWeb,
    handleRefreshBoth,
  };
}
