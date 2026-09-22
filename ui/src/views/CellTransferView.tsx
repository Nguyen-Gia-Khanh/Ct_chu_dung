import React, { useState, useEffect, useRef } from 'react';
import { Shelf, ShelfCell } from '../types';
import { ApiService } from '../services/api';
import {
  makeSlotName,
  parseSlotName,
  formatProductId,
  getShelfCode,
  cleanLocationSegment,
  normalizeSearch,
} from '../utils/coordinates';

interface CellTransferPaneProps {
  sideLabel: string;
  shelves: Shelf[];
  currentShelf: Shelf | null;
  onChangeShelf: (shelf: Shelf) => void;
  currentRow: number;
  onChangeRow: (row: number) => void;
  currentCol: number;
  onChangeCol: (col: number) => void;
  cellsData: Record<string, ShelfCell>;
  onSelectCell: (row: number, col: number) => void;
  searchVal: string;
  setSearchVal: (val: string) => void;
  onFind: (query: string) => void;
  selectedProductIds: string[];
  setSelectedProductIds: React.Dispatch<React.SetStateAction<string[]>>;
  onDoubleClickProduct: (pid: string) => void;
}

const CellTransferPane: React.FC<CellTransferPaneProps> = ({
  sideLabel,
  shelves,
  currentShelf,
  onChangeShelf,
  currentRow,
  onChangeRow,
  currentCol,
  onChangeCol,
  cellsData,
  onSelectCell,
  searchVal,
  setSearchVal,
  onFind,
  selectedProductIds,
  setSelectedProductIds,
  onDoubleClickProduct,
}) => {
  const lastClickedPidRef = useRef<string | null>(null);

  const slotName = currentShelf
    ? makeSlotName(currentShelf.floor, currentShelf.shelf, currentRow, currentCol, currentShelf.side)
    : '';

  const cell = slotName && cellsData ? cellsData[slotName] : null;
  const currentItems = cell?.items || [];
  const shelfLabel = currentShelf ? cleanLocationSegment(currentShelf.shelf) : '';
  const rowsCount = currentShelf?.rows_count || 1;

  const handleTableClick = (e: React.MouseEvent, pid: string) => {
    const allPids = currentItems.map((it) => it.product_id);
    if (e.shiftKey && lastClickedPidRef.current) {
      const startIdx = allPids.indexOf(lastClickedPidRef.current);
      const endIdx = allPids.indexOf(pid);
      if (startIdx !== -1 && endIdx !== -1) {
        const min = Math.min(startIdx, endIdx);
        const max = Math.max(startIdx, endIdx);
        const range = allPids.slice(min, max + 1);
        const newSel = Array.from(new Set([...selectedProductIds, ...range]));
        setSelectedProductIds(newSel);
      }
    } else if (e.ctrlKey || e.metaKey) {
      if (selectedProductIds.includes(pid)) {
        setSelectedProductIds(selectedProductIds.filter((x) => x !== pid));
      } else {
        setSelectedProductIds([...selectedProductIds, pid]);
      }
      lastClickedPidRef.current = pid;
    } else {
      setSelectedProductIds([pid]);
      lastClickedPidRef.current = pid;
    }
  };

  const rows = [];
  for (let r = rowsCount; r >= 1; r--) {
    const colsCount =
      (currentShelf?.custom_row_cols && currentShelf.custom_row_cols[r]) || currentShelf?.default_cols || 10;
    const cells = [];
    for (let c = 1; c <= colsCount; c++) {
      const cSlotName = currentShelf ? makeSlotName(currentShelf.floor, currentShelf.shelf, r, c, currentShelf.side) : '';
      const pCount = cSlotName && cellsData[cSlotName] ? cellsData[cSlotName].items?.length || 0 : 0;
      const isSelected = currentRow === r && currentCol === c;
      cells.push(
        <button
          key={c}
          type="button"
          className={`shelf-cell-btn ${pCount > 0 ? 'has-products' : ''} ${isSelected ? 'selected' : ''}`}
          onClick={() => onSelectCell(r, c)}
          title={cSlotName}
        >
          <div>
            R{r}-C{String(c).padStart(2, '0')} ({shelfLabel}{r}-{c})
          </div>
          <div>
            {pCount} product{pCount !== 1 ? 's' : ''}
          </div>
        </button>
      );
    }
    rows.push(
      <div key={r} className="matrix-row">
        <div className="matrix-row-label">
          R{r}
          {r === 1 ? ' · ground' : ''}
        </div>
        <div className="matrix-cells-container">{cells}</div>
      </div>
    );
  }

  const colsForCurrentRow =
    (currentShelf?.custom_row_cols && currentShelf.custom_row_cols[currentRow]) || currentShelf?.default_cols || 10;

  return (
    <div
      className="panel"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, padding: '8px' }}
    >
      <div style={{ fontWeight: 700, fontSize: '12px', marginBottom: '6px', color: 'var(--vscode-text-primary)' }}>
        {sideLabel}
      </div>

      {/* Cascade Dropdowns: Shelf, Row, Cell */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
        <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
          Shelf:
        </label>
        <select
          className="input-select"
          style={{ flex: 1, minWidth: 0, height: '26px' }}
          value={currentShelf ? currentShelf.id : ''}
          onChange={(e) => {
            const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
            if (found) onChangeShelf(found);
          }}
        >
          {shelves.map((s) => (
            <option key={s.id} value={s.id}>
              Floor {s.floor} — Side {s.side} — Shelf {s.shelf}
            </option>
          ))}
        </select>

        <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
          Row:
        </label>
        <select
          className="input-select"
          style={{ width: '48px', height: '26px' }}
          value={currentRow}
          onChange={(e) => onChangeRow(parseInt(e.target.value, 10))}
        >
          {Array.from({ length: rowsCount }, (_, i) => i + 1).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>

        <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
          Cell:
        </label>
        <select
          className="input-select"
          style={{ width: '48px', height: '26px' }}
          value={currentCol}
          onChange={(e) => onChangeCol(parseInt(e.target.value, 10))}
        >
          {Array.from({ length: colsForCurrentRow }, (_, i) => i + 1).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {/* Find product ID */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
        <label className="form-label" style={{ margin: 0, whiteSpace: 'nowrap' }}>
          Find product ID:
        </label>
        <input
          type="text"
          className="input-text font-mono"
          style={{ flex: 1, height: '26px' }}
          value={searchVal}
          onChange={(e) => setSearchVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onFind(searchVal);
          }}
          onFocus={(e) => e.target.select()}
          placeholder="Product ID or cell..."
        />
        <button
          className="btn btn-secondary btn-sm"
          style={{ height: '26px', padding: '0 10px' }}
          onClick={() => onFind(searchVal)}
        >
          Find
        </button>
      </div>

      {/* Visual Shelf Grid */}
      <div
        style={{
          border: '1px solid var(--vscode-border)',
          borderRadius: '3px',
          padding: '6px',
          marginBottom: '6px',
          display: 'flex',
          flexDirection: 'column',
          minHeight: '170px',
          maxHeight: '230px',
        }}
      >
        <div
          style={{
            textAlign: 'center',
            fontWeight: 600,
            fontSize: '11px',
            marginBottom: '4px',
            color: 'var(--vscode-text-secondary)',
          }}
        >
          {currentShelf
            ? `FLOOR ${String(currentShelf.floor).toUpperCase()} · SIDE ${String(currentShelf.side).toUpperCase()} · SHELF ${String(currentShelf.shelf).toUpperCase()}`
            : 'Shelf — click a cell'}
        </div>
        <div className="shelf-matrix-scroll" style={{ flex: 1, overflow: 'auto', border: 'none', padding: 0 }}>
          {rows}
        </div>
      </div>

      {/* Selected cell heading */}
      <div style={{ fontWeight: 600, fontSize: '12px', margin: '4px 0', color: 'var(--vscode-text-primary)' }}>
        {slotName
          ? `${slotName} (R${currentRow}-C${String(currentCol).padStart(2, '0')}) · ${currentItems.length} product${currentItems.length !== 1 ? 's' : ''}`
          : 'No cell selected'}
      </div>

      {/* Contents Table */}
      <div className="table-container" style={{ flex: 1, minHeight: '140px', overflow: 'auto' }}>
        <table className="data-table selectable">
          <thead>
            <tr>
              <th style={{ width: '110px' }}>Product ID</th>
              <th>Product name</th>
              <th style={{ width: '65px', textAlign: 'right' }}>Stock</th>
            </tr>
          </thead>
          <tbody>
            {currentItems.map((it) => {
              const isSel = selectedProductIds.includes(it.product_id);
              const stockVal = it.stock_qty != null ? it.stock_qty : it.quantity != null ? it.quantity : '';
              return (
                <tr
                  key={it.product_id}
                  className={isSel ? 'selected' : ''}
                  onClick={(e) => handleTableClick(e, it.product_id)}
                  onDoubleClick={() => onDoubleClickProduct(it.product_id)}
                  title="Double click to find product"
                >
                  <td className="font-mono">
                    <strong>{it.product_id}</strong>
                  </td>
                  <td>{it.product_name}</td>
                  <td style={{ textAlign: 'right' }}>{stockVal}</td>
                </tr>
              );
            })}
            {currentItems.length === 0 && (
              <tr>
                <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '1.5rem' }}>
                  Cell is empty.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const CellTransferView: React.FC = () => {
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
    loadShelves();
  }, []);

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

  return (
    <div className="view-container" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Subheaders matching Tkinter */}
      <div
        className="tab-sub-header"
        style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '3px', padding: '6px 12px' }}
      >
        <span className="tab-heading" style={{ fontSize: '12px', fontWeight: 600 }}>
          Select one cell on each side, then switch or combine their committed products.
        </span>
        <span style={{ color: '#8a6d1d', fontSize: '11.5px' }}>
          Local SQLite locations are updated immediately; KiotViet is not changed by this tab.
        </span>
      </div>

      {/* 3-Column Workspace */}
      <div className="transfer-workspace" style={{ padding: '0 10px 10px 10px' }}>
        {/* Left Cell */}
        <CellTransferPane
          sideLabel="Left cell"
          shelves={shelves}
          currentShelf={shelfA}
          onChangeShelf={handleSelectShelfA}
          currentRow={rowA}
          onChangeRow={(r) => setRowA(r)}
          currentCol={colA}
          onChangeCol={(c) => setColA(c)}
          cellsData={cellsDataA}
          onSelectCell={(r, c) => {
            setRowA(r);
            setColA(c);
          }}
          searchVal={searchA}
          setSearchVal={setSearchA}
          onFind={handleFindA}
          selectedProductIds={selectedIdsA}
          setSelectedProductIds={setSelectedIdsA}
          onDoubleClickProduct={(pid) => {
            setSearchA(pid);
            handleFindA(pid);
          }}
        />

        {/* Center: Cell actions */}
        <div className="cell-actions-card">
          <div className="cell-actions-title">Cell actions</div>
          <button
            className="btn btn-secondary"
            style={{ width: '100%', marginBottom: '4px' }}
            onClick={handleSwitchCells}
          >
            Switch cells ↔
          </button>
          <button
            className="btn btn-secondary"
            style={{ width: '100%', marginBottom: '4px' }}
            onClick={handleCombineLeftRight}
          >
            Combine left → right
          </button>
          <button
            className="btn btn-secondary"
            style={{ width: '100%', marginBottom: '6px' }}
            onClick={handleCombineRightLeft}
          >
            Combine right → left
          </button>

          <div className="cell-actions-separator" />

          <button
            className="btn btn-secondary"
            style={{ width: '100%', marginTop: '4px', marginBottom: '4px' }}
            onClick={handleModifyLocationWeb}
            disabled={isModifyingWeb}
          >
            Modify location ID on web
          </button>

          <div className="cell-actions-separator" />

          <button
            className="btn btn-secondary"
            style={{ width: '100%', marginTop: '4px' }}
            onClick={handleRefreshBoth}
          >
            Refresh both
          </button>

          <div className="cell-actions-desc">
            Switch exchanges both cells.
            <br />
            <br />
            Combine empties the source into the target and keeps the target's current products.
          </div>

          <div className="cell-actions-status">{statusText}</div>
          {webStatusText && <div className="upload-status-label" style={{ marginTop: '6px' }}>{webStatusText}</div>}
        </div>

        {/* Right Cell */}
        <CellTransferPane
          sideLabel="Right cell"
          shelves={shelves}
          currentShelf={shelfB}
          onChangeShelf={handleSelectShelfB}
          currentRow={rowB}
          onChangeRow={(r) => setRowB(r)}
          currentCol={colB}
          onChangeCol={(c) => setColB(c)}
          cellsData={cellsDataB}
          onSelectCell={(r, c) => {
            setRowB(r);
            setColB(c);
          }}
          searchVal={searchB}
          setSearchVal={setSearchB}
          onFind={handleFindB}
          selectedProductIds={selectedIdsB}
          setSelectedProductIds={setSelectedIdsB}
          onDoubleClickProduct={(pid) => {
            setSearchB(pid);
            handleFindB(pid);
          }}
        />
      </div>
    </div>
  );
};
