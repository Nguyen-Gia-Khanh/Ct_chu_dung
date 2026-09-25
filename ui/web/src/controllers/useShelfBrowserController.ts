import { useState, useEffect } from 'react';
import { Shelf, ShelfCell } from '../types';
import { ApiService } from '../services/api';
import { getShelfCode } from '../utils/coordinates';

export function useShelfBrowserController(active: boolean) {
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [selectedShelf, setSelectedShelf] = useState<Shelf | null>(null);
  const [cellsData, setCellsData] = useState<Record<string, ShelfCell>>({});
  const [selectedCellLoc, setSelectedCellLoc] = useState<string | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);

  useEffect(() => {
    if (!active) return;
    loadShelves();
  }, [active]);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      loadShelfCells(list[0]);
    }
  };

  const loadShelfCells = async (shelf: Shelf) => {
    setSelectedShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsData(cells);
    setSelectedCellLoc(null);
    setSelectedRow(null);
    setSelectedCol(null);
  };

  const handleCellClick = (row: number, col: number, locId: string) => {
    setSelectedRow(row);
    setSelectedCol(col);
    setSelectedCellLoc(locId);
  };

  const selectedCell = selectedCellLoc ? cellsData[selectedCellLoc] : null;
  const items = selectedCell ? selectedCell.items : [];

  // Stats
  let totalUnits = 0;
  let occupiedCount = 0;
  Object.values(cellsData).forEach((cell) => {
    if (cell.items && cell.items.length > 0) {
      occupiedCount++;
      totalUnits += cell.total_quantity;
    }
  });

  return {
    shelves,
    selectedShelf,
    cellsData,
    selectedCellLoc,
    selectedRow,
    selectedCol,
    loadShelfCells,
    handleCellClick,
    selectedCell,
    items,
    totalUnits,
    occupiedCount,
  };
}
