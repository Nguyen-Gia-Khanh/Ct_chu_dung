import React from 'react';
import { useCellTransferPaneSelection } from '../controllers/useCellTransferPaneSelection';
import { Shelf, ShelfCell } from '../types';
import { makeSlotName, cleanLocationSegment } from '../utils/coordinates';
import { useCellTransferController } from '../controllers/useCellTransferController';

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
  const slotName = currentShelf
    ? makeSlotName(currentShelf.floor, currentShelf.shelf, currentRow, currentCol, currentShelf.side)
    : '';

  const cell = slotName && cellsData ? cellsData[slotName] : null;
  const currentItems = cell?.items || [];
  const shelfLabel = currentShelf ? cleanLocationSegment(currentShelf.shelf) : '';
  const rowsCount = currentShelf?.rows_count || 1;

  const handleTableClick = useCellTransferPaneSelection(currentItems, setSelectedProductIds);

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


export const CellTransferView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
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
  } = useCellTransferController(active);
  return (
    <div className="view-container transfer-view">
      <div className="transfer-note">
        <span>
          Select one cell on each side, then switch or combine their committed products.
        </span>
        <small>
          Local SQLite locations are updated immediately; KiotViet is not changed by this tab.
        </small>
      </div>

      {/* 3-Column Workspace */}
      <div className="transfer-workspace">
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
            className="btn btn-secondary cell-action-button"
            onClick={handleSwitchCells}
          >
            Switch cells ↔
          </button>
          <button
            className="btn btn-secondary cell-action-button"
            onClick={handleCombineLeftRight}
          >
            Combine left → right
          </button>
          <button
            className="btn btn-secondary cell-action-button"
            onClick={handleCombineRightLeft}
          >
            Combine right → left
          </button>

          <div className="cell-actions-separator" />

          <button
            className="btn btn-secondary cell-action-button"
            onClick={handleModifyLocationWeb}
            disabled={isModifyingWeb}
          >
            Modify location ID on web
          </button>

          <div className="cell-actions-separator" />

          <button
            className="btn btn-secondary cell-action-button"
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
});
