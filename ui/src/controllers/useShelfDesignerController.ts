import { useState, useEffect } from 'react';
import { Shelf, CSVData, CSVColumnMapping } from '../types';
import { ApiService } from '../services/api';
import { getShelfCode } from '../utils/coordinates';
import { readCsv } from '../utils/csv';

export function useShelfDesignerController(active: boolean) {
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [floor, setFloor] = useState<number>(1);
  const [side, setSide] = useState<number>(1);
  const [shelfLetter, setShelfLetter] = useState<string>('A');
  const [rowsCount, setRowsCount] = useState<number>(3);
  const [defaultCols, setDefaultCols] = useState<number>(4);
  const [editingShelfId, setEditingShelfId] = useState<number | null>(null);
  const [rowCols, setRowCols] = useState<Record<number, number>>({});
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ text: string; type: 'info' | 'success' | 'error' } | null>(null);
  const [csvData, setCsvData] = useState<CSVData | null>(null);
  const [csvMode, setCsvMode] = useState<'new' | 'return'>('new');
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    if (!active) return;
    loadShelves();
  }, [active]);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
  };

  const handleRowsCountChange = (newCount: number) => {
    const clamped = Math.max(1, Math.min(100, newCount));
    setRowsCount(clamped);
    const updated: Record<number, number> = {};
    for (let r = 1; r <= clamped; r++) {
      updated[r] = rowCols[r] || defaultCols;
    }
    setRowCols(updated);
  };

  const handleAddRowAtTop = () => {
    if (rowsCount >= 100) return;
    const nextCount = rowsCount + 1;
    setRowsCount(nextCount);
    setRowCols((prev) => ({ ...prev, [nextCount]: defaultCols }));
  };

  const handleRemoveTopRow = () => {
    if (rowsCount <= 1) return;
    const nextCount = rowsCount - 1;
    setRowsCount(nextCount);
    setRowCols((prev) => {
      const copy = { ...prev };
      delete copy[rowsCount];
      return copy;
    });
  };

  const handleRowColOverride = (rowNum: number, cols: number) => {
    const clamped = Math.max(1, Math.min(200, cols));
    setRowCols((prev) => ({ ...prev, [rowNum]: clamped }));
  };

  const handleSelectExisting = (s: Shelf) => {
    setEditingShelfId(s.id ?? null);
    setFloor(s.floor);
    setSide(s.side);
    setShelfLetter(s.shelf);
    setRowsCount(s.rows_count);
    setDefaultCols(s.default_cols);
    setRowCols(s.custom_row_cols || {});
    setStatusMsg({ text: `Loaded shelf ${getShelfCode(s.floor, s.side, s.shelf)}`, type: 'info' });
  };

  const handleNewShelf = () => {
    setEditingShelfId(null);
    setFloor(1);
    setSide(1);
    setShelfLetter('A');
    setRowsCount(3);
    setDefaultCols(4);
    setRowCols({});
    setStatusMsg(null);
  };

  const handleCsvFile = async (file: File | null, mode: 'new' | 'return') => {
    if (!file) return;
    try {
      setCsvData(await readCsv(file));
      setCsvMode(mode);
    } catch (error) {
      setStatusMsg({ text: `CSV import: ${String(error)}`, type: 'error' });
    }
  };

  const handleCsvConfirm = async (mapping: CSVColumnMapping) => {
    if (!csvData) return;
    const result = await ApiService.importCSV(csvData, mapping, csvMode);
    setCsvData(null);
    setStatusMsg({
      text: result.message || result.error || 'CSV import failed.',
      type: result.success ? 'success' : 'error',
    });
  };

  const handleSaveShelf = async () => {
    if (!shelfLetter.trim()) {
      setStatusMsg({ text: 'Shelf code letter is required', type: 'error' });
      return;
    }
    try {
      const shelfPayload: Shelf = {
        ...(editingShelfId ? { id: editingShelfId } : {}),
        floor,
        side,
        shelf: shelfLetter.trim().toUpperCase(),
        rows_count: rowsCount,
        default_cols: defaultCols,
        custom_row_cols: rowCols,
      };
      const res = await ApiService.saveShelf(shelfPayload);
      if (res && res.error) {
        setStatusMsg({ text: `Error saving shelf: ${res.error}`, type: 'error' });
        return;
      }
      setStatusMsg({
        text: `Successfully saved Shelf ${getShelfCode(floor, side, shelfLetter)} (${rowsCount} rows)`,
        type: 'success',
      });
      setEditingShelfId(res.id ?? null);
      await loadShelves();
    } catch (err: unknown) {
      setStatusMsg({ text: `Error saving shelf: ${String(err)}`, type: 'error' });
    }
  };

  const handleDeleteShelf = async (id?: number) => {
    if (!id) return;
    if (confirm('Are you sure you want to delete this shelf definition?')) {
      const res = await ApiService.deleteShelf(id);
      if (res && res.error) {
        setStatusMsg({ text: `Error deleting shelf: ${res.error}`, type: 'error' });
        return;
      }
      await loadShelves();
      setStatusMsg({ text: 'Shelf deleted.', type: 'info' });
    }
  };

  return {
    shelves,
    floor,
    setFloor,
    side,
    setSide,
    shelfLetter,
    setShelfLetter,
    rowsCount,
    defaultCols,
    rowCols,
    selectedRow,
    setSelectedRow,
    selectedCol,
    statusMsg,
    editingShelfId,
    csvData,
    csvMode,
    setCsvData,
    previewOpen,
    setPreviewOpen,
    handleCsvFile,
    handleCsvConfirm,
    handleNewShelf,
    handleRowsCountChange,
    handleAddRowAtTop,
    handleRemoveTopRow,
    handleRowColOverride,
    handleSelectExisting,
    handleSaveShelf,
    handleDeleteShelf,
  };
}
