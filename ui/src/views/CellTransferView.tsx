import React, { useState, useEffect } from 'react';
import { Shelf, ShelfCell } from '../types';
import { ApiService } from '../services/api';
import { ShelfCanvas } from '../components/ShelfCanvas';
import {
  makeSlotName,
  parseSlotName,
  formatProductId,
  getShelfCode,
} from '../utils/coordinates';

export const CellTransferView: React.FC = () => {
  const [shelves, setShelves] = useState<Shelf[]>([]);

  // Shelf A (Source)
  const [shelfA, setShelfA] = useState<Shelf | null>(null);
  const [rowA, setRowA] = useState<number>(1);
  const [colA, setColA] = useState<number>(1);
  const [cellsDataA, setCellsDataA] = useState<Record<string, ShelfCell>>({});

  // Shelf B (Destination)
  const [shelfB, setShelfB] = useState<Shelf | null>(null);
  const [rowB, setRowB] = useState<number>(1);
  const [colB, setColB] = useState<number>(1);
  const [cellsDataB, setCellsDataB] = useState<Record<string, ShelfCell>>({});

  // Quick Jump Search (with auto-clear/select on focus!)
  const [jumpQuery, setJumpQuery] = useState<string>('');

  // Logs
  const [logs, setLogs] = useState<string[]>([]);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      handleSelectShelfA(list[0]);
      handleSelectShelfB(list.length > 1 ? list[1] : list[0]);
    }
  };

  const addLog = (msg: string) => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${msg}`, ...prev.slice(0, 40)]);
  };

  const handleSelectShelfA = async (s: Shelf) => {
    setShelfA(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataA(cells);
    setRowA(1);
    setColA(1);
  };

  const handleSelectShelfB = async (s: Shelf) => {
    setShelfB(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataB(cells);
    setRowB(1);
    setColB(1);
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

  // Quick Jump Search - user request: auto-wiping / selecting text bar on focus
  const handleQuickJump = async (val: string) => {
    const formatted = formatProductId(val);
    setJumpQuery(formatted);
    if (!formatted.trim()) return;

    const res = await ApiService.findProductLocation(formatted);
    if (res.product && res.location) {
      const parsed = parseSlotName(res.location);
      if (parsed) {
        const foundShelf = shelves.find(
          (s) =>
            s.floor === parsed.floor &&
            s.side === parsed.side &&
            s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
        );
        if (foundShelf) {
          await handleSelectShelfA(foundShelf);
          setRowA(parsed.row);
          setColA(parsed.col);
          addLog(`Jumped Shelf A to ${res.location} for product ${res.product.product_id}`);
        }
      }
    }
  };

  const slotLocA = shelfA ? makeSlotName(shelfA.floor, shelfA.shelf, rowA, colA, shelfA.side) : '';
  const slotLocB = shelfB ? makeSlotName(shelfB.floor, shelfB.shelf, rowB, colB, shelfB.side) : '';

  const cellA = slotLocA ? cellsDataA[slotLocA] : null;
  const cellB = slotLocB ? cellsDataB[slotLocB] : null;

  const itemsA = cellA ? cellA.items : [];
  const itemsB = cellB ? cellB.items : [];

  const handleSwitchCells = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('Source and destination cells must be different.');
      return;
    }

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
      addLog(`Swapped: ${slotLocA} ⇄ ${slotLocB}`);
      await reloadBoth();
    } else {
      addLog(`Error: ${res.error}`);
    }
  };

  const handleCombineCells = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('Source and destination cells must be different.');
      return;
    }
    if (itemsA.length === 0) {
      alert('Source cell is empty. Nothing to combine.');
      return;
    }

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
      addLog(`Combined: ${slotLocA} ➔ ${slotLocB}`);
      await reloadBoth();
    } else {
      addLog(`Error: ${res.error}`);
    }
  };

  return (
    <div className="view-container">
      {/* Top Bar: Quick Jump Search */}
      <div className="panel" style={{ padding: '0.75rem 1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
            🔍 Product Quick Jump (Shelf A):
          </label>
          <div className="input-search-wrapper" style={{ flex: 1, minWidth: '260px' }}>
            <input
              type="text"
              className="input-text font-mono"
              placeholder="Enter or scan Product ID / Barcode to auto-select its cell (clears on focus)..."
              value={jumpQuery}
              onChange={(e) => handleQuickJump(e.target.value)}
              onFocus={(e) => {
                // Auto-select text cleanly on focus
                e.target.select();
              }}
            />
            {jumpQuery && (
              <button className="search-clear-btn" onClick={() => setJumpQuery('')}>
                &times;
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="split-pane">
        {/* Left Side: Source Cell A */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">🅰️ Source Slot A: {slotLocA}</h2>
            <select
              className="input-select"
              value={shelfA ? shelfA.id : ''}
              onChange={(e) => {
                const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                if (found) handleSelectShelfA(found);
              }}
            >
              {shelves.map((s) => (
                <option key={s.id} value={s.id}>
                  {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}R × {s.default_cols}C)
                </option>
              ))}
            </select>
          </div>

          <div className="panel-body">
            {shelfA && (
              <ShelfCanvas
                floor={shelfA.floor}
                side={shelfA.side}
                shelf={shelfA.shelf}
                rowsCount={shelfA.rows_count}
                colsCount={shelfA.default_cols}
                rowColsMap={shelfA.custom_row_cols}
                cellsData={cellsDataA}
                selectedRow={rowA}
                selectedCol={colA}
                onCellClick={(r, c) => {
                  setRowA(r);
                  setColA(c);
                }}
              />
            )}

            <div style={{ marginTop: '0.75rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.3rem' }}>
                Contents in Slot A ({itemsA.length} items):
              </div>
              <div className="table-container" style={{ maxHeight: '130px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Name</th>
                      <th>Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {itemsA.map((it) => (
                      <tr key={it.product_id}>
                        <td className="font-mono">
                          <strong>{it.product_id}</strong>
                        </td>
                        <td>{it.product_name}</td>
                        <td>{it.quantity}</td>
                      </tr>
                    ))}
                    {itemsA.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          Cell A is empty.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side: Destination Cell B */}
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">🅱️ Destination Slot B: {slotLocB}</h2>
            <select
              className="input-select"
              value={shelfB ? shelfB.id : ''}
              onChange={(e) => {
                const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                if (found) handleSelectShelfB(found);
              }}
            >
              {shelves.map((s) => (
                <option key={s.id} value={s.id}>
                  {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}R × {s.default_cols}C)
                </option>
              ))}
            </select>
          </div>

          <div className="panel-body">
            {shelfB && (
              <ShelfCanvas
                floor={shelfB.floor}
                side={shelfB.side}
                shelf={shelfB.shelf}
                rowsCount={shelfB.rows_count}
                colsCount={shelfB.default_cols}
                rowColsMap={shelfB.custom_row_cols}
                cellsData={cellsDataB}
                selectedRow={rowB}
                selectedCol={colB}
                onCellClick={(r, c) => {
                  setRowB(r);
                  setColB(c);
                }}
              />
            )}

            <div style={{ marginTop: '0.75rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.3rem' }}>
                Contents in Slot B ({itemsB.length} items):
              </div>
              <div className="table-container" style={{ maxHeight: '130px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Name</th>
                      <th>Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {itemsB.map((it) => (
                      <tr key={it.product_id}>
                        <td className="font-mono">
                          <strong>{it.product_id}</strong>
                        </td>
                        <td>{it.product_name}</td>
                        <td>{it.quantity}</td>
                      </tr>
                    ))}
                    {itemsB.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          Cell B is empty.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Action Bar & Logs */}
      <div className="panel" style={{ padding: '0.85rem 1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
          <button
            className="btn btn-primary"
            style={{ padding: '0.6rem 1.25rem' }}
            onClick={handleSwitchCells}
          >
            🔄 Switch Cells ({slotLocA} ⇄ {slotLocB})
          </button>
          <button
            className="btn btn-secondary"
            style={{ padding: '0.6rem 1.25rem' }}
            onClick={handleCombineCells}
          >
            ➕ Combine Cell A into Cell B ({slotLocA} ➔ {slotLocB})
          </button>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Both operations are executed atomically.
          </span>
        </div>

        <div className="status-log" style={{ height: '70px' }}>
          {logs.map((log, i) => (
            <div key={i}>{log}</div>
          ))}
          {logs.length === 0 && <div>Ready to switch or combine cells.</div>}
        </div>
      </div>
    </div>
  );
};
