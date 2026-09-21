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

  // Quick Jump Search (with auto-clear/select on focus)
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
          addLog(`Found product ${res.product.product_id} at ${res.location}`);
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
      alert('Choose two different cells to switch.');
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
      addLog(`Swapped: ${slotLocA} <-> ${slotLocB}`);
      await reloadBoth();
    } else {
      addLog(`Error: ${res.error}`);
    }
  };

  const handleCombineCells = async () => {
    if (!shelfA || !shelfB) return;
    if (slotLocA === slotLocB) {
      alert('Choose two different cells to combine.');
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
      addLog(`Combined: ${slotLocA} -> ${slotLocB}`);
      await reloadBoth();
    } else {
      addLog(`Error: ${res.error}`);
    }
  };

  return (
    <div className="view-container">
      {/* Search Header */}
      <div className="panel" style={{ padding: '0.45rem 0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
            Find product ID:
          </label>
          <div className="input-search-wrapper" style={{ maxWidth: '400px' }}>
            <input
              type="text"
              className="input-text font-mono"
              placeholder="Enter product ID to locate in Shelf A (clears on focus)..."
              value={jumpQuery}
              onChange={(e) => handleQuickJump(e.target.value)}
              onFocus={(e) => e.target.select()}
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
        {/* Left Side: Shelf A (Matching Tkinter CellTransferPane) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Source Cell (Shelf A) — {slotLocA}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <label className="form-label" style={{ margin: 0 }}>Shelf:</label>
              <select
                className="input-select"
                style={{ height: '24px', padding: '0 0.3rem' }}
                value={shelfA ? shelfA.id : ''}
                onChange={(e) => {
                  const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                  if (found) handleSelectShelfA(found);
                }}
              >
                {shelves.map((s) => (
                  <option key={s.id} value={s.id}>
                    {getShelfCode(s.floor, s.side, s.shelf)}
                  </option>
                ))}
              </select>

              <label className="form-label" style={{ margin: 0, marginLeft: '0.2rem' }}>Row:</label>
              <select
                className="input-select"
                style={{ height: '24px', width: '50px', padding: '0 0.2rem' }}
                value={rowA}
                onChange={(e) => setRowA(parseInt(e.target.value, 10))}
              >
                {Array.from({ length: shelfA?.rows_count || 1 }, (_, i) => i + 1).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>

              <label className="form-label" style={{ margin: 0, marginLeft: '0.2rem' }}>Col:</label>
              <select
                className="input-select"
                style={{ height: '24px', width: '50px', padding: '0 0.2rem' }}
                value={colA}
                onChange={(e) => setColA(parseInt(e.target.value, 10))}
              >
                {Array.from(
                  { length: (shelfA?.custom_row_cols?.[rowA] || shelfA?.default_cols || 10) },
                  (_, i) => i + 1
                ).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
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

            <div style={{ marginTop: '0.3rem' }}>
              <span className="form-label" style={{ fontWeight: 600, display: 'block', marginBottom: '0.2rem' }}>
                Contents in Slot A ({itemsA.length} items)
              </span>
              <div className="table-container" style={{ maxHeight: '130px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '55px' }}>Qty</th>
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

        {/* Right Side: Shelf B (Matching Tkinter CellTransferPane) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Destination Cell (Shelf B) — {slotLocB}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <label className="form-label" style={{ margin: 0 }}>Shelf:</label>
              <select
                className="input-select"
                style={{ height: '24px', padding: '0 0.3rem' }}
                value={shelfB ? shelfB.id : ''}
                onChange={(e) => {
                  const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                  if (found) handleSelectShelfB(found);
                }}
              >
                {shelves.map((s) => (
                  <option key={s.id} value={s.id}>
                    {getShelfCode(s.floor, s.side, s.shelf)}
                  </option>
                ))}
              </select>

              <label className="form-label" style={{ margin: 0, marginLeft: '0.2rem' }}>Row:</label>
              <select
                className="input-select"
                style={{ height: '24px', width: '50px', padding: '0 0.2rem' }}
                value={rowB}
                onChange={(e) => setRowB(parseInt(e.target.value, 10))}
              >
                {Array.from({ length: shelfB?.rows_count || 1 }, (_, i) => i + 1).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>

              <label className="form-label" style={{ margin: 0, marginLeft: '0.2rem' }}>Col:</label>
              <select
                className="input-select"
                style={{ height: '24px', width: '50px', padding: '0 0.2rem' }}
                value={colB}
                onChange={(e) => setColB(parseInt(e.target.value, 10))}
              >
                {Array.from(
                  { length: (shelfB?.custom_row_cols?.[rowB] || shelfB?.default_cols || 10) },
                  (_, i) => i + 1
                ).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
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

            <div style={{ marginTop: '0.3rem' }}>
              <span className="form-label" style={{ fontWeight: 600, display: 'block', marginBottom: '0.2rem' }}>
                Contents in Slot B ({itemsB.length} items)
              </span>
              <div className="table-container" style={{ maxHeight: '130px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '55px' }}>Qty</th>
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

      {/* Action Bar & Log */}
      <div className="panel" style={{ padding: '0.6rem 0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap', marginBottom: '0.4rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleSwitchCells}
          >
            Switch cells ({slotLocA} &lt;-&gt; {slotLocB})
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleCombineCells}
          >
            Combine cell A into cell B ({slotLocA} -&gt; {slotLocB})
          </button>
          <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
            Both operations are executed atomically.
          </span>
        </div>

        <div className="status-log" style={{ height: '60px' }}>
          {logs.map((log, i) => (
            <div key={i}>{log}</div>
          ))}
          {logs.length === 0 && <div>Ready to switch or combine cells.</div>}
        </div>
      </div>
    </div>
  );
};
