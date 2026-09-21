import React, { useState, useEffect } from 'react';
import { Shelf, Product, ShelfCell, PrimalQueueItem } from '../types';
import { ApiService } from '../services/api';
import { ShelfCanvas } from '../components/ShelfCanvas';
import {
  parseSlotName,
  formatProductId,
  normalizeSearch,
  getShelfCode,
} from '../utils/coordinates';

export const PrimalQueueView: React.FC = () => {
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
    loadInitialData();
  }, []);

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

  const filteredQueue = primalQueue.filter((item) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return (
      normalizeSearch(item.barcode).includes(s) ||
      normalizeSearch(item.product_name).includes(s) ||
      (item.target_location && normalizeSearch(item.target_location).includes(s))
    );
  });

  const activeCellItems = selectedCellLoc && cellsData[selectedCellLoc] ? cellsData[selectedCellLoc].items : [];

  return (
    <div className="view-container">
      <div className="split-pane left-heavy">
        {/* Left Side: Products (Primal Queue & Full Catalog) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products (Primal Queue & Full Catalog)</span>
            <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
              {filteredQueue.length} items
            </span>
          </div>

          <div className="panel-body">
            <div className="form-group">
              <label className="form-label">Search barcode or product ID (auto-formats 5-3-3)</label>
              <div className="input-search-wrapper">
                <input
                  type="text"
                  className="input-text font-mono"
                  placeholder="Scan or type barcode (selects text on focus)..."
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  onFocus={(e) => e.target.select()}
                  autoFocus
                />
                {searchQuery && (
                  <button className="search-clear-btn" onClick={() => setSearchQuery('')}>
                    &times;
                  </button>
                )}
              </div>
            </div>

            <div className="table-container" style={{ flex: 1, maxHeight: '520px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Barcode / ID</th>
                    <th>Product Name</th>
                    <th style={{ width: '50px' }}>Qty</th>
                    <th>Location</th>
                    <th style={{ width: '80px' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredQueue.map((item) => (
                    <tr
                      key={item.barcode}
                      style={{ cursor: 'pointer' }}
                      className={
                        selectedCellLoc && item.target_location === selectedCellLoc ? 'selected' : ''
                      }
                      onClick={() => handleSelectProduct(item.target_location)}
                    >
                      <td className="font-mono">
                        <strong>{formatProductId(item.barcode)}</strong>
                      </td>
                      <td>{item.product_name}</td>
                      <td>{item.quantity}</td>
                      <td>
                        {item.target_location ? (
                          <span className="loc-pill assigned">{item.target_location}</span>
                        ) : (
                          <span className="loc-pill">Pending</span>
                        )}
                      </td>
                      <td>
                        {item.target_location && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelectProduct(item.target_location);
                            }}
                          >
                            View
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filteredQueue.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        No items found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Side: Shelf View */}
        <div className="panel">
          <div className="panel-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span className="panel-title">Shelf View:</span>
              <select
                className="input-select"
                style={{ height: '24px', padding: '0 0.4rem', fontWeight: 600 }}
                value={currentShelf ? currentShelf.id : ''}
                onChange={(e) => {
                  const s = shelves.find((x) => x.id === parseInt(e.target.value, 10));
                  if (s) selectShelf(s);
                }}
              >
                {shelves.map((s) => (
                  <option key={s.id} value={s.id}>
                    {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}R × {s.default_cols}C)
                  </option>
                ))}
              </select>
            </div>

            {selectedCellLoc && (
              <span className="loc-pill assigned">
                {selectedCellLoc}
              </span>
            )}
          </div>

          <div className="panel-body">
            {currentShelf ? (
              <ShelfCanvas
                floor={currentShelf.floor}
                side={currentShelf.side}
                shelf={currentShelf.shelf}
                rowsCount={currentShelf.rows_count}
                colsCount={currentShelf.default_cols}
                rowColsMap={currentShelf.custom_row_cols}
                cellsData={cellsData}
                selectedRow={selectedRow}
                selectedCol={selectedCol}
                onCellClick={handleCellClick}
              />
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                No shelves created.
              </div>
            )}

            {/* Cell Contents */}
            <div style={{ marginTop: '0.4rem' }}>
              <div
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  marginBottom: '0.3rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  color: 'var(--text-secondary)',
                }}
              >
                <span>
                  Contents in <strong className="font-mono">{selectedCellLoc || 'None'}</strong>:
                </span>
                <span>
                  {activeCellItems.length} product(s)
                </span>
              </div>

              <div className="table-container" style={{ maxHeight: '180px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Product Name</th>
                      <th style={{ width: '55px' }}>Qty</th>
                      <th style={{ width: '60px' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeCellItems.map((item) => (
                      <tr key={item.product_id}>
                        <td className="font-mono">
                          <strong>{item.product_id}</strong>
                        </td>
                        <td>{item.product_name}</td>
                        <td>{item.quantity}</td>
                        <td>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleRemoveProduct(item.product_id)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                    {activeCellItems.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          {selectedCellLoc
                            ? 'Cell is empty.'
                            : 'Click a cell above to view contents.'}
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
    </div>
  );
};
