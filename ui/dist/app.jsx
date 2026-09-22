// Warehouse Shelf Mapper - IntelliJ Desktop App Runtime
const { useState, useEffect, useRef } = React;

// --- UTILITIES ---
function normalizeSearch(value) {
  if (!value) return '';
  return value
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

function cleanLocationSegment(value) {
  if (!value) return '';
  const normalized = normalizeSearch(String(value)).trim().toUpperCase();
  const hyphenated = normalized.replace(/\s+/g, '-');
  return hyphenated.replace(/[^A-Z0-9_-]/g, '');
}

function makeSlotName(floor, shelfCode, rowNumber, slotNumber, side = '1') {
  let floorCode = cleanLocationSegment(String(floor));
  if (!/^L[0-9]+$/i.test(floorCode)) {
    floorCode = `L${floorCode}`;
  }
  return `${floorCode}-${cleanLocationSegment(String(side))}${cleanLocationSegment(shelfCode)}${rowNumber}-${slotNumber}`;
}

function getShelfCode(floor, side, shelf) {
  let floorCode = cleanLocationSegment(String(floor));
  if (!/^L[0-9]+$/i.test(floorCode)) {
    floorCode = `L${floorCode}`;
  }
  return `${floorCode}-${cleanLocationSegment(String(side))}${cleanLocationSegment(shelf)}`;
}

function parseSlotName(locId) {
  if (!locId) return null;
  const match = locId.trim().match(/^L(\d+)-(\d+)([A-Za-z]+)(\d+)-(\d+)$/i);
  if (!match) return null;
  return {
    floor: parseInt(match[1], 10),
    side: parseInt(match[2], 10),
    shelf: match[3].toUpperCase(),
    row: parseInt(match[4], 10),
    col: parseInt(match[5], 10),
  };
}

function formatProductId(value) {
  if (!value) return '';
  const compact = value.trim().replace(/-/g, '');
  if (compact.length === 11 && /^[a-zA-Z0-9]+$/.test(compact)) {
    return `${compact.slice(0, 5)}-${compact.slice(5, 8)}-${compact.slice(8)}`;
  }
  return value.trim();
}

// --- API CLIENT ---
const API_BASE = '/api';

const ApiService = {
  async getShelves() {
    try {
      const res = await fetch(`${API_BASE}/shelves`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getShelves error:', e);
    }
    return [];
  },

  async saveShelf(shelf) {
    const res = await fetch(`${API_BASE}/shelves`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(shelf),
    });
    return await res.json();
  },

  async deleteShelf(shelfId) {
    const res = await fetch(`${API_BASE}/shelves/${shelfId}`, { method: 'DELETE' });
    return await res.json();
  },

  async getCatalog() {
    try {
      const res = await fetch(`${API_BASE}/products/catalog`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getCatalog error:', e);
    }
    return [];
  },

  async getPendingQueue() {
    try {
      const res = await fetch(`${API_BASE}/products/pending-queue`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getPendingQueue error:', e);
    }
    return [];
  },

  async getPrimalQueue() {
    try {
      const res = await fetch(`${API_BASE}/products/primal-queue`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getPrimalQueue error:', e);
    }
    return [];
  },

  async getShelfCells(shelfCode) {
    try {
      const res = await fetch(`${API_BASE}/shelves/${encodeURIComponent(shelfCode)}/cells`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getShelfCells error:', e);
    }
    return {};
  },

  async assignLocation(payload) {
    const res = await fetch(`${API_BASE}/assignments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return await res.json();
  },

  async directMoveLocation(productId, targetSlot) {
    const res = await fetch(`${API_BASE}/assignments/direct-move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, slot: targetSlot }),
    });
    return await res.json();
  },

  async transferCells(payload) {
    const res = await fetch(`${API_BASE}/assignments/transfer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return await res.json();
  },

  async removePlacement(productId, locId) {
    const res = await fetch(`${API_BASE}/assignments/remove`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, loc_id: locId }),
    });
    return await res.json();
  },

  async importCSV(csvData, mapping, mode) {
    const res = await fetch(`${API_BASE}/import-csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: csvData, mapping, mode }),
    });
    return await res.json();
  },

  async findProductLocation(query) {
    try {
      const res = await fetch(`${API_BASE}/products/find?q=${encodeURIComponent(query)}`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API findProductLocation error:', e);
    }
    return { product: null, location: null };
  },

  async getOnHandProducts() {
    try {
      const res = await fetch(`${API_BASE}/products/on-hand`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getOnHandProducts error:', e);
    }
    return [];
  },

  async addToOnHand(productIds, quantities = {}) {
    const items = productIds.map((pid) => ({
      product_id: pid,
      quantity: quantities[pid] !== undefined ? quantities[pid] : null,
    }));
    const res = await fetch(`${API_BASE}/on-hand/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    return await res.json();
  },

  async dequeueOnHand(productIds) {
    const res = await fetch(`${API_BASE}/on-hand/dequeue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async updateOnHandStock(productId, quantity) {
    const res = await fetch(`${API_BASE}/on-hand/update-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, quantity }),
    });
    return await res.json();
  },

  async getSlotAddress(floor, side, shelf, row, col) {
    const query = new URLSearchParams({
      floor: String(floor),
      side: String(side),
      shelf: String(shelf),
      row: String(row),
      col: String(col),
    });
    const res = await fetch(`${API_BASE}/slot-address?${query}`);
    return await res.json();
  },

  async assignOnHandToSlot(slotId, productIds) {
    const res = await fetch(`${API_BASE}/assignments/assign-on-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async moveSlotToOnHand(slotId, productIds = null) {
    const res = await fetch(`${API_BASE}/slot-contents/move-to-hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_ids: productIds }),
    });
    return await res.json();
  },

  async updateSlotStock(slotId, productId, quantity) {
    const res = await fetch(`${API_BASE}/slot-contents/update-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot_id: slotId, product_id: productId, quantity }),
    });
    return await res.json();
  },

  async transferCatalogToQueue(productIds) {
    const res = await fetch(`${API_BASE}/catalog/transfer-to-queue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds }),
    });
    return await res.json();
  },

  async connectChrome() {
    const res = await fetch(`${API_BASE}/web/connect-chrome`, { method: 'POST' });
    return await res.json();
  },

  async modifyLocationWeb(target, slotName) {
    const body =
      Array.isArray(target) && target.length > 0 && typeof target[0] === 'object'
        ? { items: target }
        : { product_ids: target, slot_name: slotName };
    const res = await fetch(`${API_BASE}/web/modify-location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  },

  async getPendingExceptions() {
    try {
      const res = await fetch(`${API_BASE}/exceptions/pending`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn('API getPendingExceptions error:', e);
    }
    return { success: true, count: 0, items: [] };
  },

  async assignException(payload) {
    const res = await fetch(`${API_BASE}/exceptions/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return await res.json();
  },

  async appendExceptionsToCSV(csvPath) {
    const res = await fetch(`${API_BASE}/exceptions/append-csv`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_path: csvPath }),
    });
    return await res.json();
  },
};

// --- COMPONENTS ---

function Navbar({ activeTab, onSelectTab, pendingCount = 0, catalogCount = 0 }) {
  return (
    <header className="navbar">
      <div className="brand-container">
        <span className="brand-title">Warehouse Shelf Mapper</span>
      </div>

      <nav className="nav-tabs">
        <button
          className={`nav-tab ${activeTab === 'designer' ? 'active' : ''}`}
          onClick={() => onSelectTab('designer')}
        >
          Tab 1: Shelf Designer
        </button>

        <button
          className={`nav-tab ${activeTab === 'assignment' ? 'active' : ''}`}
          onClick={() => onSelectTab('assignment')}
        >
          Tab 2: Assign Locations
          {pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
        </button>

        <button
          className={`nav-tab ${activeTab === 'primal_queue' ? 'active' : ''}`}
          onClick={() => onSelectTab('primal_queue')}
        >
          Tab 3: Primal Queue / Shelves
        </button>

        <button
          className={`nav-tab ${activeTab === 'browser' ? 'active' : ''}`}
          onClick={() => onSelectTab('browser')}
        >
          Tab 4: Browse Shelves
        </button>

        <button
          className={`nav-tab ${activeTab === 'cell_transfer' ? 'active' : ''}`}
          onClick={() => onSelectTab('cell_transfer')}
        >
          Tab 5: Switch / Combine Cells
        </button>

        <button
          className={`nav-tab ${activeTab === 'exceptions' ? 'active' : ''}`}
          onClick={() => onSelectTab('exceptions')}
        >
          Tab 6: Special Exceptions
        </button>
      </nav>

      <div className="navbar-actions">
        <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
          Catalog: <strong>{catalogCount}</strong> items
        </span>
      </div>
    </header>
  );
}

function ShelfCanvas({
  floor,
  side,
  shelf,
  rowsCount,
  colsCount = 10,
  rowColsMap = {},
  cellsData = {},
  selectedRow = null,
  selectedCol = null,
  onCellClick,
  title,
}) {
  const rows = Array.from({ length: rowsCount }, (_, i) => i + 1);
  let totalCells = 0;
  let occupiedCount = 0;

  rows.forEach((r) => {
    const cols = rowColsMap[r] || colsCount;
    totalCells += cols;
    for (let c = 1; c <= cols; c++) {
      const locId = makeSlotName(floor, shelf, r, c, side);
      if (cellsData[locId] && cellsData[locId].is_occupied) {
        occupiedCount++;
      }
    }
  });

  return (
    <div className="shelf-canvas-container">
      <div className="shelf-canvas-header">
        <div>
          <strong>{title || `Shelf: L${floor}-${side}${shelf}`}</strong>
          <span style={{ marginLeft: '0.75rem', color: 'var(--text-muted)' }}>
            ({rowsCount} rows × ~{colsCount} cols)
          </span>
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <span>
            Occupied: <strong style={{ color: '#2e7d32' }}>{occupiedCount}</strong> / {totalCells}
          </span>
          <span>({totalCells > 0 ? Math.round((occupiedCount / totalCells) * 100) : 0}%)</span>
        </div>
      </div>

      <div className="shelf-canvas-grid">
        {rows.map((rowNum) => {
          const numCols = rowColsMap[rowNum] || colsCount;
          const cols = Array.from({ length: numCols }, (_, i) => i + 1);

          return (
            <div key={rowNum} className="shelf-canvas-row">
              <div className="shelf-row-label">R{rowNum}</div>
              <div className="shelf-cells-row">
                {cols.map((colNum) => {
                  const locId = makeSlotName(floor, shelf, rowNum, colNum, side);
                  const cell = cellsData[locId];
                  const isOccupied = !!(cell && cell.items && cell.items.length > 0);
                  const itemCount = cell ? cell.items.length : 0;
                  const isSelected = selectedRow === rowNum && selectedCol === colNum;

                  return (
                    <div
                      key={colNum}
                      className={`shelf-cell ${isOccupied ? 'occupied' : ''} ${
                        isSelected ? 'selected' : ''
                      }`}
                      onClick={() => onCellClick && onCellClick(rowNum, colNum, locId)}
                      title={`${locId} ${isOccupied ? `(${itemCount} items)` : '(Empty)'}`}
                    >
                      <span className="shelf-cell-num">{colNum}</span>
                      {isOccupied && <span className="shelf-cell-badge">{itemCount}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StockQuantityDialog({
  isOpen,
  slotName,
  products,
  onConfirm,
  onCancel,
  title,
  destinationLabel,
  buttonText = 'Assign products',
}) {
  const [quantities, setQuantities] = useState(() => {
    const init = {};
    products.forEach((p) => {
      init[p.id] = p.initialQuantity || 1;
    });
    return init;
  });

  if (!isOpen) return null;

  const handleQtyChange = (productId, val) => {
    const parsed = parseInt(val, 10);
    setQuantities((prev) => ({
      ...prev,
      [productId]: isNaN(parsed) || parsed < 0 ? 0 : parsed,
    }));
  };

  const handlePreset = (productId, delta) => {
    setQuantities((prev) => ({
      ...prev,
      [productId]: Math.max(0, (prev[productId] || 0) + delta),
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onConfirm(quantities);
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: '640px' }}>
        <div className="modal-header">
          <h3 className="modal-title">{title || `Assign products to ${slotName}`}</h3>
          <button className="modal-close" onClick={onCancel}>
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>
                {destinationLabel || `Destination: ${slotName}`}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Enter each product's stock quantity (whole units, 0 or more).
              </div>
            </div>

            <div className="table-container" style={{ maxHeight: '300px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Product ID</th>
                    <th>Product Name</th>
                    <th style={{ width: '150px' }}>Stock Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((p) => (
                    <tr key={p.id}>
                      <td className="font-mono">
                        <strong>{p.id}</strong>
                      </td>
                      <td>{p.name}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                          <input
                            type="number"
                            min="0"
                            className="input-text font-mono"
                            style={{ width: '65px', padding: '0.25rem 0.4rem' }}
                            value={quantities[p.id] ?? 1}
                            onChange={(e) => handleQtyChange(p.id, e.target.value)}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handlePreset(p.id, 1)}
                            title="Add 1"
                          >
                            +1
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handlePreset(p.id, 5)}
                            title="Add 5"
                          >
                            +5
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              {buttonText}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ColumnMappingDialog({ isOpen, csvData, onConfirm, onCancel, modeTitle = 'Import CSV' }) {
  const [codeCol, setCodeCol] = useState('');
  const [nameCol, setNameCol] = useState('');
  const [qtyCol, setQtyCol] = useState('');
  const [locCol, setLocCol] = useState('');

  useEffect(() => {
    if (!csvData || csvData.headers.length === 0) return;
    const headers = csvData.headers;
    const normalized = headers.map((h) => h.toLowerCase().replace(/[^a-z0-9]/g, ''));

    const findMatch = (candidates, fallbackIdx) => {
      for (const candidate of candidates) {
        const idx = normalized.indexOf(candidate);
        if (idx !== -1) return headers[idx];
      }
      return headers[Math.min(fallbackIdx, headers.length - 1)] || '';
    };

    setCodeCol(
      findMatch(['productid', 'productcode', 'sku', 'itemid', 'itemcode', 'id', 'code', 'mahang', 'masanpham', 'barcode'], 0)
    );
    setNameCol(
      findMatch(['productname', 'itemname', 'name', 'description', 'productdescription', 'tenhang', 'tensanpham'], 1)
    );
    setQtyCol(
      findMatch(['stockqty', 'quantity', 'tonkho', 'soluong', 'onhand', 'soluongton', 'qty'], 2)
    );
    setLocCol(
      findMatch(['location', 'vitri', 'slot', 'bin', 'locid', 'vitrikho'], -1)
    );
  }, [csvData]);

  if (!isOpen || !csvData) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!codeCol || !nameCol) {
      alert('Please select both Product Code and Product Name columns.');
      return;
    }
    onConfirm({
      code_col: codeCol,
      name_col: nameCol,
      qty_col: qtyCol,
      loc_col: locCol || undefined,
    });
  };

  const previewRows = csvData.rows.slice(0, 5);

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: '680px' }}>
        <div className="modal-header">
          <h3 className="modal-title">{modeTitle} - Match Columns</h3>
          <button className="modal-close" onClick={onCancel}>
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Product ID / Barcode *</label>
                <select className="input-select" value={codeCol} onChange={(e) => setCodeCol(e.target.value)} required>
                  <option value="">-- Select Column --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Product Name *</label>
                <select className="input-select" value={nameCol} onChange={(e) => setNameCol(e.target.value)} required>
                  <option value="">-- Select Column --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Stock Quantity</label>
                <select className="input-select" value={qtyCol} onChange={(e) => setQtyCol(e.target.value)}>
                  <option value="">-- Select Column (Optional) --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Location ID</label>
                <select className="input-select" value={locCol} onChange={(e) => setLocCol(e.target.value)}>
                  <option value="">-- Select Column (Optional) --</option>
                  {csvData.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              CSV Preview (first 5 of {csvData.rows.length} rows):
            </div>
            <div className="table-container" style={{ maxHeight: '200px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {csvData.headers.map((h) => (
                      <th key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, idx) => (
                    <tr key={idx}>
                      {csvData.headers.map((h) => (
                        <td key={h}>{row[h] || ''}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              Confirm & Import
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- VIEWS ---

function ShelfDesignerView() {
  const [shelves, setShelves] = useState([]);
  const [floor, setFloor] = useState(1);
  const [side, setSide] = useState(1);
  const [shelfLetter, setShelfLetter] = useState('A');
  const [rowsCount, setRowsCount] = useState(8);
  const [defaultCols, setDefaultCols] = useState(10);
  const [rowCols, setRowCols] = useState({});
  const [selectedRow, setSelectedRow] = useState(null);
  const [selectedCol, setSelectedCol] = useState(null);
  const [statusMsg, setStatusMsg] = useState(null);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
  };

  const handleRowsCountChange = (newCount) => {
    const clamped = Math.max(1, Math.min(25, newCount));
    setRowsCount(clamped);
    const updated = {};
    for (let r = 1; r <= clamped; r++) {
      updated[r] = rowCols[r] || defaultCols;
    }
    setRowCols(updated);
  };

  const handleAddRowAtTop = () => {
    const next = rowsCount + 1;
    setRowsCount(next);
    setRowCols((prev) => ({ ...prev, [next]: defaultCols }));
  };

  const handleRemoveTopRow = () => {
    if (rowsCount <= 1) return;
    const next = rowsCount - 1;
    setRowsCount(next);
    setRowCols((prev) => {
      const copy = { ...prev };
      delete copy[rowsCount];
      return copy;
    });
  };

  const handleRowColOverride = (rowNum, cols) => {
    const clamped = Math.max(1, Math.min(50, cols));
    setRowCols((prev) => ({ ...prev, [rowNum]: clamped }));
  };

  const handleSelectExisting = (s) => {
    setFloor(s.floor);
    setSide(s.side);
    setShelfLetter(s.shelf);
    setRowsCount(s.rows_count);
    setDefaultCols(s.default_cols);
    setRowCols(s.custom_row_cols || {});
    setStatusMsg({ text: `Loaded shelf ${getShelfCode(s.floor, s.side, s.shelf)}`, type: 'info' });
  };

  const handleSaveShelf = async () => {
    if (!shelfLetter.trim()) {
      setStatusMsg({ text: 'Shelf code letter is required', type: 'error' });
      return;
    }
    try {
      const shelfPayload = {
        floor,
        side,
        shelf: shelfLetter.trim().toUpperCase(),
        rows_count: rowsCount,
        default_cols: defaultCols,
        custom_row_cols: rowCols,
      };
      await ApiService.saveShelf(shelfPayload);
      setStatusMsg({
        text: `Successfully saved Shelf ${getShelfCode(floor, side, shelfLetter)} (${rowsCount} rows)`,
        type: 'success',
      });
      loadShelves();
    } catch (err) {
      setStatusMsg({ text: `Error saving shelf: ${String(err)}`, type: 'error' });
    }
  };

  const handleDeleteShelf = async (id) => {
    if (!id) return;
    if (confirm('Are you sure you want to delete this shelf definition?')) {
      await ApiService.deleteShelf(id);
      loadShelves();
      setStatusMsg({ text: 'Shelf deleted.', type: 'info' });
    }
  };

  return (
    <div className="view-container">
      <div className="split-pane">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div className="panel">
            <div className="panel-header">
              <span className="panel-title">Shelf Metadata</span>
              <button className="btn btn-primary btn-sm" onClick={handleSaveShelf}>
                Save Shelf to DB
              </button>
            </div>

            <div className="panel-body">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                <div className="form-group">
                  <label className="form-label">Floor</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    className="input-text font-mono"
                    value={floor}
                    onChange={(e) => setFloor(parseInt(e.target.value, 10) || 1)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Side</label>
                  <select className="input-select" value={side} onChange={(e) => setSide(parseInt(e.target.value, 10) || 1)}>
                    <option value={1}>Side 1</option>
                    <option value={2}>Side 2</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Shelf code</label>
                  <input
                    type="text"
                    maxLength={4}
                    className="input-text font-mono"
                    value={shelfLetter}
                    onChange={(e) => setShelfLetter(e.target.value.toUpperCase())}
                    placeholder="e.g. A"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Number of rows</label>
                  <input
                    type="number"
                    min="1"
                    max="25"
                    className="input-text font-mono"
                    value={rowsCount}
                    onChange={(e) => handleRowsCountChange(parseInt(e.target.value, 10) || 1)}
                  />
                </div>
              </div>

              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                Row 1 is at ground level. New rows are added at the top. Location example: L1-1A8-10.
                Changing a loaded shelf's metadata renames it on Commit. Use New shelf for another side.
              </div>
            </div>
          </div>

          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-header">
              <span className="panel-title">Rows — Front View</span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button className="btn btn-secondary btn-sm" onClick={handleAddRowAtTop}>
                  Add row at top
                </button>
                <button className="btn btn-secondary btn-sm" onClick={handleRemoveTopRow}>
                  Remove top row
                </button>
              </div>
            </div>

            <div className="panel-body">
              <div className="table-container" style={{ maxHeight: '240px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: '120px' }}>Row</th>
                      <th>Slots in row</th>
                      <th style={{ width: '100px' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: rowsCount }, (_, i) => rowsCount - i).map((rowNum) => (
                      <tr key={rowNum}>
                        <td className="font-mono">
                          <strong>Row {rowNum}</strong>
                        </td>
                        <td>
                          <input
                            type="number"
                            min="1"
                            max="40"
                            className="input-text font-mono"
                            style={{ width: '70px', height: '22px', padding: '0 0.3rem' }}
                            value={rowCols[rowNum] || defaultCols}
                            onChange={(e) => handleRowColOverride(rowNum, parseInt(e.target.value, 10) || defaultCols)}
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleRowColOverride(rowNum, defaultCols)}
                          >
                            Reset
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div style={{ marginTop: '0.5rem' }}>
                <span className="form-label" style={{ display: 'block', marginBottom: '0.3rem' }}>
                  Existing Shelves in Database:
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                  {shelves.map((s) => (
                    <div
                      key={s.id}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        background: 'var(--bg-subtle)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '2px',
                        padding: '0.15rem 0.45rem',
                        fontSize: '11.5px',
                      }}
                    >
                      <span style={{ cursor: 'pointer', fontWeight: 600 }} onClick={() => handleSelectExisting(s)}>
                        {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}×{s.default_cols})
                      </span>
                      <button
                        onClick={() => handleDeleteShelf(s.id)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)' }}
                        title="Delete shelf"
                      >
                        &times;
                      </button>
                    </div>
                  ))}
                  {shelves.length === 0 && (
                    <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>No shelves saved.</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              2D Front-View Preview: {getShelfCode(floor, side, shelfLetter)}
            </span>
            {selectedRow && selectedCol && (
              <span className="loc-pill assigned">
                Selected: R{selectedRow}-C{selectedCol}
              </span>
            )}
          </div>

          <div className="panel-body">
            <ShelfCanvas
              floor={floor}
              side={side}
              shelf={shelfLetter}
              rowsCount={rowsCount}
              colsCount={defaultCols}
              rowColsMap={rowCols}
              selectedRow={selectedRow}
              selectedCol={selectedCol}
              onCellClick={(r, c) => {
                setSelectedRow(r);
                setSelectedCol(c);
              }}
              title={`Preview: L${floor}-${side}${shelfLetter}`}
            />

            {statusMsg && (
              <div
                style={{
                  marginTop: '0.5rem',
                  padding: '0.4rem 0.6rem',
                  borderRadius: '3px',
                  fontSize: '11.5px',
                  background:
                    statusMsg.type === 'success'
                      ? 'var(--success-subtle)'
                      : statusMsg.type === 'error'
                      ? 'var(--danger-subtle)'
                      : 'var(--primary-subtle)',
                  color:
                    statusMsg.type === 'success'
                      ? 'var(--success)'
                      : statusMsg.type === 'error'
                      ? 'var(--danger)'
                      : 'var(--primary)',
                }}
              >
                {statusMsg.text}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function LocationAssignmentView() {
  const [catalog, setCatalog] = useState([]);
  const [pendingQueue, setPendingQueue] = useState([]);
  const [onHandProducts, setOnHandProducts] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchLocationText, setSearchLocationText] = useState('');

  const [selectedQueueIds, setSelectedQueueIds] = useState([]);
  const [selectedCatalogIds, setSelectedCatalogIds] = useState([]);
  const [selectedOnHandIds, setSelectedOnHandIds] = useState([]);
  const [selectedContentIds, setSelectedContentIds] = useState([]);

  // Address inputs
  const [floor, setFloor] = useState('1');
  const [side, setSide] = useState('1');
  const [shelf, setShelf] = useState('A');
  const [row, setRow] = useState(1);
  const [col, setCol] = useState(1);

  // Loaded slot state
  const [loadedSlot, setLoadedSlot] = useState(null);
  const [loadedContents, setLoadedContents] = useState([]);
  const [addressStatusText, setAddressStatusText] = useState('Enter an existing shelf address and load it.');

  // Web options
  const [webBatchMode, setWebBatchMode] = useState(false);
  const [uploadStatusText, setUploadStatusText] = useState('');
  const [copyStatusText, setCopyStatusText] = useState('Double-click a row to copy its Product ID.');

  useEffect(() => {
    refreshData();
    handleLoadAddressDirect('1', '1', 'A', 1, 1);
  }, []);

  const refreshData = async () => {
    const [cats, pends, hands] = await Promise.all([
      ApiService.getCatalog(),
      ApiService.getPendingQueue(),
      ApiService.getOnHandProducts(),
    ]);
    setCatalog(cats);
    setPendingQueue(pends);
    setOnHandProducts(hands);
  };

  // Live location check based on search query
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchLocationText('');
      return;
    }
    const term = normalizeSearch(q);
    const inHand = onHandProducts.find(
      (h) => normalizeSearch(h.product_id) === term || normalizeSearch(h.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inHand) {
      setSearchLocationText(`In on-hand queue · stock ${inHand.stock_qty != null ? inHand.stock_qty : 'Unknown'}`);
      return;
    }
    const inCat = catalog.find(
      (c) => normalizeSearch(c.product_id) === term || normalizeSearch(c.product_id.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inCat && inCat.loc_id) {
      setSearchLocationText(`Already at ${inCat.loc_id}`);
      return;
    }
    const inPend = pendingQueue.find(
      (p) => normalizeSearch(p.code) === term || normalizeSearch(p.code.replace(/-/g, '')) === term.replace(/-/g, '')
    );
    if (inPend && inPend.returned) {
      setSearchLocationText(`In total queue · returned stock ${inPend.on_hand != null ? inPend.on_hand : 'Unknown'}`);
      return;
    }
    if (inCat && !inCat.loc_id) {
      setSearchLocationText('Not assigned to any location.');
      return;
    }
    setSearchLocationText('');
  }, [searchQuery, catalog, pendingQueue, onHandProducts]);

  const lastQueueIdRef = useRef(null);
  const lastCatIdRef = useRef(null);
  const lastHandIdRef = useRef(null);
  const lastContentIdRef = useRef(null);

  const handleTableSelect = (id, allIds, selectedList, setSelectedList, lastRef, e) => {
    if (e && e.shiftKey && lastRef.current && allIds.includes(lastRef.current)) {
      const startIdx = allIds.indexOf(lastRef.current);
      const endIdx = allIds.indexOf(id);
      if (startIdx !== -1 && endIdx !== -1) {
        const [low, high] = startIdx < endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
        const range = allIds.slice(low, high + 1);
        const combined = Array.from(new Set([...selectedList, ...range]));
        setSelectedList(combined);
        return;
      }
    }
    lastRef.current = id;
    if (e && (e.ctrlKey || e.metaKey)) {
      setSelectedList(selectedList.includes(id) ? selectedList.filter((x) => x !== id) : [...selectedList, id]);
    } else {
      setSelectedList(selectedList.length === 1 && selectedList[0] === id ? [] : [id]);
    }
  };

  const handleMoveSelectedToOnHand = async () => {
    if (selectedQueueIds.length === 0) return;
    const res = await ApiService.addToOnHand(selectedQueueIds);
    if (res.success) {
      setSelectedQueueIds([]);
      await refreshData();
    }
  };

  const handleTransferSelectedToQueue = async () => {
    if (selectedCatalogIds.length === 0) return;
    const res = await ApiService.transferCatalogToQueue(selectedCatalogIds);
    if (res.success) {
      setSelectedCatalogIds([]);
      await refreshData();
    }
  };

  const handleCatalogDoubleClick = (productId) => {
    setSearchQuery(productId);
  };

  const handleEditSelectedQuantity = async () => {
    if (selectedOnHandIds.length !== 1) return;
    const pid = selectedOnHandIds[0];
    const item = onHandProducts.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : '';
    const val = window.prompt(`Product: ${pid}\nCurrent stock: ${curr !== '' ? curr : '(null)'}\n\nEnter the new whole-number quantity (or empty for null):`, String(curr));
    if (val === null) return;
    const newQty = val.trim() === '' ? 0 : parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateOnHandStock(pid, newQty);
      await refreshData();
    }
  };

  const handleDequeueOnHand = async () => {
    if (selectedOnHandIds.length === 0) return;
    const res = await ApiService.dequeueOnHand(selectedOnHandIds);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
    }
  };

  const handleLoadAddressDirect = async (f, s, sh, r, c) => {
    const res = await ApiService.getSlotAddress(f, s, sh, r, c);
    if (res.success && res.slot) {
      setLoadedSlot(res.slot);
      setLoadedContents(res.contents || []);
      setAddressStatusText(res.message);
    } else {
      setLoadedSlot(null);
      setLoadedContents([]);
      setAddressStatusText(res.message || `No saved cell at Floor ${f} / Side ${s} / Shelf ${sh} / Row ${r} / Cell ${c}.`);
    }
  };

  const handleLoadAddress = async () => {
    await handleLoadAddressDirect(floor, side, shelf, row, col);
  };

  const handleAssignAddress = async () => {
    if (!loadedSlot) {
      alert('Enter the shelf address and press Load address first.');
      return;
    }
    const pids = selectedOnHandIds.length > 0 ? selectedOnHandIds : onHandProducts.map((p) => p.product_id);
    if (pids.length === 0) {
      alert('Select one or more on-hand products with click first.');
      return;
    }
    const res = await ApiService.assignOnHandToSlot(loadedSlot.slot_id, pids);
    if (res.success) {
      setSelectedOnHandIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    } else {
      alert(res.error || 'Assignment failed');
    }
  };

  const handleCopyProductId = (productId) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(productId);
      setCopyStatusText(`Copied ${productId} to clipboard.`);
    }
  };

  const handleModifyLoadedStock = async () => {
    if (selectedContentIds.length !== 1 || !loadedSlot) return;
    const pid = selectedContentIds[0];
    const item = loadedContents.find((p) => p.product_id === pid);
    const curr = item && item.stock_qty != null ? item.stock_qty : '';
    const val = window.prompt(
      `Product: ${pid}\nLocation: ${loadedSlot.slot_name}\nCurrent stock: ${curr !== '' ? curr : '(null)'}\n\nEnter the new whole-number quantity (or empty for null):`,
      String(curr)
    );
    if (val === null) return;
    const newQty = val.trim() === '' ? 0 : parseInt(val, 10);
    if (!isNaN(newQty) && newQty >= 0) {
      await ApiService.updateSlotStock(loadedSlot.slot_id, pid, newQty);
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleSelectedToHand = async () => {
    if (!loadedSlot || selectedContentIds.length === 0) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id, selectedContentIds);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleShelfAllToHand = async () => {
    if (!loadedSlot || loadedContents.length === 0) return;
    if (!window.confirm(`Move all ${loadedContents.length} product(s) from ${loadedSlot.slot_name} to on-hand?`)) return;
    const res = await ApiService.moveSlotToOnHand(loadedSlot.slot_id);
    if (res.success) {
      setSelectedContentIds([]);
      await refreshData();
      await handleLoadAddressDirect(loadedSlot.floor, loadedSlot.side, loadedSlot.shelf, loadedSlot.row, loadedSlot.col);
    }
  };

  const handleModifyLocationWeb = async () => {
    if (!loadedSlot) return;
    const targetPids = webBatchMode ? loadedContents.map((c) => c.product_id) : selectedContentIds;
    if (targetPids.length === 0) return;
    const res = await ApiService.modifyLocationWeb(targetPids, loadedSlot.slot_name);
    setUploadStatusText(res.message || 'Updated web location.');
  };

  const handleConnectChrome = async () => {
    const res = await ApiService.connectChrome();
    setUploadStatusText(res.message || 'Chrome connection initiated.');
  };

  const filteredPending = pendingQueue.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return normalizeSearch(p.code).includes(s) || normalizeSearch(p.name).includes(s);
  });

  const filteredCatalog = catalog.filter((p) => {
    if (!searchQuery) return true;
    const s = normalizeSearch(searchQuery);
    return (
      normalizeSearch(p.product_id).includes(s) ||
      normalizeSearch(p.barcode).includes(s) ||
      normalizeSearch(p.product_name).includes(s) ||
      (p.loc_id && normalizeSearch(p.loc_id).includes(s))
    );
  });

  return (
    <div className="view-container">
      {/* Top Header matching Tkinter */}
      <div className="tab-sub-header">
        <span className="tab-heading">
          Build a persistent on-hand batch, then assign it to one exact shelf address.
        </span>
        <button className="btn btn-secondary btn-sm" onClick={handleConnectChrome}>
          Connect Chrome
        </button>
      </div>

      {/* Main 3-column split pane */}
      <div className="split-pane three-column">
        {/* PANEL 1: Products (weight 4) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            {/* Box 1: Total unassigned product queue */}
            <div className="group-card" style={{ flex: 1 }}>
              <div className="group-card-title">Total unassigned product queue</div>
              <div className="form-group">
                <label className="form-label">Search code, full name, or shortened name</label>
                <div className="input-search-wrapper">
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Type or scan product ID..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                  {searchQuery && (
                    <button className="search-clear-btn" onClick={() => setSearchQuery('')}>
                      &times;
                    </button>
                  )}
                </div>
                <div className="search-location-hint">{searchLocationText}</div>
              </div>

              <div className="table-container" style={{ flex: 1, maxHeight: '160px' }}>
                <table className="data-table selectable">
                  <thead>
                    <tr>
                      <th style={{ width: '110px' }}>Product ID</th>
                      <th>Product name</th>
                      <th style={{ width: '65px', textAlign: 'right' }}>Stock</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPending.slice(0, 100).map((item) => (
                      <tr
                        key={item.code}
                        className={`${selectedQueueIds.includes(item.code) ? 'selected-row' : ''} ${
                          item.returned ? 'returned-row' : ''
                        }`}
                        onClick={(e) => handleTableSelect(item.code, filteredPending.slice(0, 100).map(x => x.code), selectedQueueIds, setSelectedQueueIds, lastQueueIdRef, e)}
                      >
                        <td className="font-mono">
                          <strong>{item.code}</strong>
                        </td>
                        <td>{item.name}</td>
                        <td style={{ textAlign: 'right' }}>{item.on_hand != null ? item.on_hand : ''}</td>
                      </tr>
                    ))}
                    {filteredPending.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '16px' }}>
                          No unassigned products.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="group-card-footer">
                <span className="count-label">{filteredPending.length.toLocaleString()} products</span>
                <button
                  className="btn btn-secondary"
                  style={{ width: '100%' }}
                  onClick={handleMoveSelectedToOnHand}
                  disabled={selectedQueueIds.length === 0}
                >
                  Move selected → on-hand
                </button>
              </div>
            </div>

            {/* Box 2: Full product catalog */}
            <div className="group-card" style={{ flex: 1 }}>
              <div className="group-card-title">Full product catalog</div>

              <div className="table-container" style={{ flex: 1, maxHeight: '160px' }}>
                <table className="data-table selectable">
                  <thead>
                    <tr>
                      <th style={{ width: '110px' }}>Product ID</th>
                      <th>Product name</th>
                      <th style={{ width: '120px' }}>Location ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCatalog.slice(0, 100).map((prod) => (
                      <tr
                        key={prod.product_id}
                        className={selectedCatalogIds.includes(prod.product_id) ? 'selected-row' : ''}
                        onClick={(e) => handleTableSelect(prod.product_id, filteredCatalog.slice(0, 100).map(x => x.product_id), selectedCatalogIds, setSelectedCatalogIds, lastCatIdRef, e)}
                        onDoubleClick={() => handleCatalogDoubleClick(prod.product_id)}
                      >
                        <td className="font-mono">
                          <strong>{prod.product_id}</strong>
                        </td>
                        <td>{prod.product_name}</td>
                        <td>
                          {prod.loc_id ? (
                            <span className="loc-pill assigned">{prod.loc_id}</span>
                          ) : (
                            <span className="loc-pill">Unassigned</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filteredCatalog.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '16px' }}>
                          No catalog products.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="group-card-footer">
                <span className="count-label">{filteredCatalog.length.toLocaleString()} products</span>
                <button
                  className="btn btn-secondary"
                  style={{ width: '100%' }}
                  onClick={handleTransferSelectedToQueue}
                  disabled={selectedCatalogIds.length === 0}
                >
                  Transfer selected to total queue
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* PANEL 2: On-hand queue and shelf address (weight 3) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">On-hand queue and shelf address</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            {/* On-hand Treeview */}
            <div className="table-container" style={{ flex: 1, minHeight: '190px' }}>
              <table className="data-table selectable">
                <thead>
                  <tr>
                    <th style={{ width: '110px' }}>Product ID</th>
                    <th>Product name</th>
                    <th style={{ width: '65px', textAlign: 'right' }}>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {onHandProducts.map((item) => (
                    <tr
                      key={item.product_id}
                      className={selectedOnHandIds.includes(item.product_id) ? 'selected-row' : ''}
                      onClick={(e) => handleTableSelect(item.product_id, onHandProducts.map(x => x.product_id), selectedOnHandIds, setSelectedOnHandIds, lastHandIdRef, e)}
                    >
                      <td className="font-mono">
                        <strong>{item.product_id}</strong>
                      </td>
                      <td>{item.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{item.stock_qty != null ? item.stock_qty : ''}</td>
                    </tr>
                  ))}
                  {onHandProducts.length === 0 && (
                    <tr>
                      <td colSpan={3} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '24px' }}>
                        0 products ready to assign
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="count-label" style={{ fontWeight: 600 }}>
              {onHandProducts.length} products ready to assign
            </div>

            {/* Hand Action Buttons */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleEditSelectedQuantity}
                disabled={selectedOnHandIds.length !== 1}
              >
                Edit selected quantity
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleDequeueOnHand}
                disabled={selectedOnHandIds.length === 0}
              >
                Dequeue selected → total queue
              </button>
            </div>

            {/* Shelf Address Card */}
            <div className="group-card" style={{ marginTop: '2px' }}>
              <div className="group-card-title">Shelf address</div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '4px' }}>
                <div className="form-group">
                  <label className="form-label">Floor</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={floor}
                    onChange={(e) => setFloor(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Side</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={side}
                    onChange={(e) => setSide(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Shelf</label>
                  <input
                    type="text"
                    className="input-text font-mono"
                    value={shelf}
                    onChange={(e) => setShelf(e.target.value.toUpperCase())}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Row</label>
                  <input
                    type="number"
                    min="1"
                    className="input-text font-mono"
                    value={row}
                    onChange={(e) => setRow(parseInt(e.target.value, 10) || 1)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Col / cell</label>
                  <input
                    type="number"
                    min="1"
                    className="input-text font-mono"
                    value={col}
                    onChange={(e) => setCol(parseInt(e.target.value, 10) || 1)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLoadAddress()}
                  />
                </div>
              </div>

              <button
                className="btn btn-secondary"
                style={{ width: '100%', marginTop: '4px' }}
                onClick={handleLoadAddress}
              >
                Load address →
              </button>

              <button
                className="btn btn-primary commit-btn"
                style={{ width: '100%', marginTop: '4px' }}
                onClick={handleAssignAddress}
                disabled={!loadedSlot || onHandProducts.length === 0}
              >
                Assign selected on-hand → loaded address
              </button>

              <div className="address-status-label">{addressStatusText}</div>
            </div>
          </div>
        </div>

        {/* PANEL 3: Loaded address contents (weight 3) */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Loaded address contents</span>
          </div>
          <div className="panel-body" style={{ gap: '8px' }}>
            <div className="slot-heading">
              {loadedSlot ? loadedSlot.slot_name : 'No address loaded'}
            </div>

            <div className="table-container" style={{ flex: 1, minHeight: '220px' }}>
              <table className="data-table selectable">
                <thead>
                  <tr>
                    <th style={{ width: '110px' }}>Product ID</th>
                    <th>Product name</th>
                    <th style={{ width: '55px', textAlign: 'right' }}>Stock</th>
                    <th style={{ width: '150px' }}>Added to shelf</th>
                  </tr>
                </thead>
                <tbody>
                  {loadedContents.map((it) => (
                    <tr
                      key={it.product_id}
                      className={selectedContentIds.includes(it.product_id) ? 'selected-row' : ''}
                      onClick={(e) => handleTableSelect(it.product_id, loadedContents.map(x => x.product_id), selectedContentIds, setSelectedContentIds, lastContentIdRef, e)}
                      onDoubleClick={() => handleCopyProductId(it.product_id)}
                      title="Double-click to copy Product ID"
                    >
                      <td className="font-mono">
                        <strong>{it.product_id}</strong>
                      </td>
                      <td>{it.product_name}</td>
                      <td style={{ textAlign: 'right' }}>{it.stock_qty != null ? it.stock_qty : ''}</td>
                      <td>{it.assigned_at}</td>
                    </tr>
                  ))}
                  {loadedContents.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', color: 'var(--vscode-text-muted)', padding: '24px' }}>
                        {loadedSlot ? `Slot ${loadedSlot.slot_name} is empty.` : 'No address loaded.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <button
              className="btn btn-secondary"
              style={{ width: '100%' }}
              onClick={handleModifyLoadedStock}
              disabled={selectedContentIds.length !== 1}
            >
              Modify selected stock
            </button>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleSelectedToHand}
                disabled={selectedContentIds.length === 0}
              >
                Selected product(s) → on-hand
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleShelfAllToHand}
                disabled={!loadedSlot || loadedContents.length === 0}
              >
                Shelf → on-hand (all)
              </button>
            </div>

            <div style={{ marginTop: '2px' }}>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  className="toggle-checkbox"
                  checked={webBatchMode}
                  onChange={(e) => setWebBatchMode(e.target.checked)}
                />
                <span>Process and save all products in loaded address</span>
              </label>
            </div>

            <button
              className="btn btn-secondary"
              style={{ width: '100%' }}
              onClick={handleModifyLocationWeb}
              disabled={
                !loadedSlot ||
                (!webBatchMode && selectedContentIds.length === 0) ||
                (webBatchMode && loadedContents.length === 0)
              }
            >
              {webBatchMode ? "Modify all products' web location" : "Modify selected product's web location"}
            </button>

            {uploadStatusText && <div className="upload-status-label">{uploadStatusText}</div>}

            <div className="hint-label">{copyStatusText}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PrimalQueueView() {
  const [shelves, setShelves] = useState([]);
  const [currentShelf, setCurrentShelf] = useState(null);
  const [cellsData, setCellsData] = useState({});
  const [primalQueue, setPrimalQueue] = useState([]);
  const [catalog, setCatalog] = useState([]);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCellLoc, setSelectedCellLoc] = useState(null);
  const [selectedRow, setSelectedRow] = useState(null);
  const [selectedCol, setSelectedCol] = useState(null);

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

  const selectShelf = async (shelf) => {
    setCurrentShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsData(cells);
    setSelectedCellLoc(null);
    setSelectedRow(null);
    setSelectedCol(null);
  };

  const handleSearchChange = (val) => {
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
          (s) => s.floor === parsed.floor && s.side === parsed.side && s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
        );
        if (matchShelf && matchShelf.id !== (currentShelf && currentShelf.id)) {
          selectShelf(matchShelf);
        }
        setSelectedCellLoc(found.loc_id);
        setSelectedRow(parsed.row);
        setSelectedCol(parsed.col);
      }
    }
  };

  const handleSelectProduct = (locId) => {
    if (!locId) return;
    const parsed = parseSlotName(locId);
    if (!parsed) return;
    const matchShelf = shelves.find(
      (s) => s.floor === parsed.floor && s.side === parsed.side && s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
    );
    if (matchShelf) {
      if (matchShelf.id !== (currentShelf && currentShelf.id)) {
        selectShelf(matchShelf);
      }
      setSelectedCellLoc(locId);
      setSelectedRow(parsed.row);
      setSelectedCol(parsed.col);
    }
  };

  const handleCellClick = (row, col, locId) => {
    setSelectedRow(row);
    setSelectedCol(col);
    setSelectedCellLoc(locId);
  };

  const handleRemoveProduct = async (productId) => {
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
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Products (Primal Queue & Full Catalog)</span>
            <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>{filteredQueue.length} items</span>
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
                  {filteredQueue.slice(0, 100).map((item) => (
                    <tr
                      key={item.barcode}
                      style={{ cursor: 'pointer' }}
                      className={selectedCellLoc && item.target_location === selectedCellLoc ? 'selected' : ''}
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
                  {filteredQueue.length > 100 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: '#616161', padding: '6px', fontSize: '11px', background: '#f8f8f8' }}>
                        Showing top 100 of {filteredQueue.length} items. Refine search to see more.
                      </td>
                    </tr>
                  )}
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
                <span>{activeCellItems.length} product(s)</span>
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
                          {selectedCellLoc ? 'Cell is empty.' : 'Click a cell above to view contents.'}
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
}

function ShelfBrowserView() {
  const [shelves, setShelves] = useState([]);
  const [selectedShelf, setSelectedShelf] = useState(null);
  const [cellsData, setCellsData] = useState({});
  const [selectedCellLoc, setSelectedCellLoc] = useState(null);
  const [selectedRow, setSelectedRow] = useState(null);
  const [selectedCol, setSelectedCol] = useState(null);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      loadShelfCells(list[0]);
    }
  };

  const loadShelfCells = async (shelf) => {
    setSelectedShelf(shelf);
    const code = getShelfCode(shelf.floor, shelf.side, shelf.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsData(cells);
    setSelectedCellLoc(null);
    setSelectedRow(null);
    setSelectedCol(null);
  };

  const handleCellClick = (row, col, locId) => {
    setSelectedRow(row);
    setSelectedCol(col);
    setSelectedCellLoc(locId);
  };

  const selectedCell = selectedCellLoc ? cellsData[selectedCellLoc] : null;
  const items = selectedCell ? selectedCell.items : [];

  let totalUnits = 0;
  let occupiedCount = 0;
  Object.values(cellsData).forEach((cell) => {
    if (cell.items && cell.items.length > 0) {
      occupiedCount++;
      totalUnits += cell.total_quantity;
    }
  });

  return (
    <div className="view-container">
      <div className="panel" style={{ marginBottom: '0.4rem' }}>
        <div
          style={{
            padding: '0.45rem 0.75rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <label className="form-label" style={{ margin: 0 }}>
              Existing shelf:
            </label>
            <select
              className="input-select"
              style={{ fontWeight: 600, minWidth: '220px' }}
              value={selectedShelf ? selectedShelf.id : ''}
              onChange={(e) => {
                const found = shelves.find((s) => s.id === parseInt(e.target.value, 10));
                if (found) loadShelfCells(found);
              }}
            >
              {shelves.map((s) => (
                <option key={s.id} value={s.id}>
                  {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count} Rows × {s.default_cols} Cols)
                </option>
              ))}
            </select>
            <button className="btn btn-secondary btn-sm" onClick={() => selectedShelf && loadShelfCells(selectedShelf)}>
              Refresh
            </button>
          </div>

          <div style={{ display: 'flex', gap: '1.25rem', fontSize: '12px', color: 'var(--text-secondary)' }}>
            <div>
              Occupied: <strong style={{ color: 'var(--success)' }}>{occupiedCount}</strong> cells
            </div>
            <div>
              Total Products: <strong>{totalUnits}</strong> units
            </div>
            <div style={{ color: 'var(--text-muted)' }}>Read-only view</div>
          </div>
        </div>
      </div>

      <div className="split-pane right-heavy">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">
              {selectedShelf ? getShelfCode(selectedShelf.floor, selectedShelf.side, selectedShelf.shelf) : 'Shelf'} Layout
            </span>
            {selectedCellLoc && <span className="loc-pill assigned">Selected: {selectedCellLoc}</span>}
          </div>

          <div className="panel-body">
            {selectedShelf ? (
              <ShelfCanvas
                floor={selectedShelf.floor}
                side={selectedShelf.side}
                shelf={selectedShelf.shelf}
                rowsCount={selectedShelf.rows_count}
                colsCount={selectedShelf.default_cols}
                rowColsMap={selectedShelf.custom_row_cols}
                cellsData={cellsData}
                selectedRow={selectedRow}
                selectedCol={selectedCol}
                onCellClick={handleCellClick}
              />
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>No shelf selected.</div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Cell Details: {selectedCellLoc || 'Select a Cell'}</span>
            {selectedCellLoc && (
              <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
                {items.length} item(s) / {selectedCell ? selectedCell.total_quantity : 0} units
              </span>
            )}
          </div>

          <div className="panel-body">
            {selectedCellLoc ? (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.4rem', marginBottom: '0.6rem' }}>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Row (Ground Up)</div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>Row {selectedRow}</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Slot / Column</div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>Col {selectedCol}</div>
                  </div>
                  <div style={{ background: 'var(--bg-subtle)', padding: '0.4rem', borderRadius: '2px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</div>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: items.length > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
                      {items.length > 0 ? 'Occupied' : 'Empty'}
                    </div>
                  </div>
                </div>

                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th style={{ width: '55px' }}>Qty</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it) => (
                        <tr key={it.product_id}>
                          <td className="font-mono">
                            <strong>{it.product_id}</strong>
                          </td>
                          <td>{it.product_name}</td>
                          <td className="font-mono">{it.barcode}</td>
                          <td>
                            <strong>{it.quantity}</strong>
                          </td>
                        </tr>
                      ))}
                      {items.length === 0 && (
                        <tr>
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '1.5rem' }}>
                            Cell is empty.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '3rem 1rem' }}>
                <div>Click on any slot in the shelf grid to view contents.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CellTransferPane({
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
}) {
  const lastClickedPidRef = useRef(null);

  const slotName = currentShelf
    ? makeSlotName(currentShelf.floor, currentShelf.shelf, currentRow, currentCol, currentShelf.side)
    : '';

  const cell = slotName && cellsData ? cellsData[slotName] : null;
  const currentItems = cell?.items || [];
  const shelfLabel = currentShelf ? cleanLocationSegment(currentShelf.shelf) : '';
  const rowsCount = currentShelf?.rows_count || 1;

  const handleTableClick = (e, pid) => {
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
}

function CellTransferView() {
  const [shelves, setShelves] = useState([]);

  // Pane A (Left)
  const [shelfA, setShelfA] = useState(null);
  const [rowA, setRowA] = useState(1);
  const [colA, setColA] = useState(1);
  const [cellsDataA, setCellsDataA] = useState({});
  const [searchA, setSearchA] = useState('');
  const [selectedIdsA, setSelectedIdsA] = useState([]);

  // Pane B (Right)
  const [shelfB, setShelfB] = useState(null);
  const [rowB, setRowB] = useState(1);
  const [colB, setColB] = useState(1);
  const [cellsDataB, setCellsDataB] = useState({});
  const [searchB, setSearchB] = useState('');
  const [selectedIdsB, setSelectedIdsB] = useState([]);

  // Center & Global Actions
  const [lastChangedProducts, setLastChangedProducts] = useState([]);
  const [statusText, setStatusText] = useState('Choose two cells.');
  const [webStatusText, setWebStatusText] = useState('');
  const [isModifyingWeb, setIsModifyingWeb] = useState(false);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
    if (list.length > 0) {
      await handleSelectShelfA(list[0]);
      await handleSelectShelfB(list.length > 1 ? list[1] : list[0]);
    }
  };

  const handleSelectShelfA = async (s) => {
    setShelfA(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataA(cells);
    setRowA(1);
    setColA(1);
    setSelectedIdsA([]);
  };

  const handleSelectShelfB = async (s) => {
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

  const handleFindA = async (query) => {
    await executeFind(query, 'A');
  };

  const handleFindB = async (query) => {
    await executeFind(query, 'B');
  };

  const executeFind = async (rawQuery, targetSide) => {
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
    } catch (err) {
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
    } catch (err) {
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
    } catch (err) {
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
    } catch (err) {
      setWebStatusText(`Error modifying web location: ${err.message || err}`);
    } finally {
      setIsModifyingWeb(false);
    }
  };

  const handleRefreshBoth = async () => {
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
}

// --- TAB 6: SPECIAL EXCEPTIONS VIEW ---

function ExceptionsView() {
  const [productId, setProductId] = useState('');
  const [stockQty, setStockQty] = useState('');
  const [floor, setFloor] = useState('1');
  const [side, setSide] = useState('1');
  const [shelf, setShelf] = useState('A');
  const [row, setRow] = useState('1');
  const [col, setCol] = useState('1');

  const [loadedSlotName, setLoadedSlotName] = useState('');
  const [loadedSlotId, setLoadedSlotId] = useState(null);
  const [loadedSlotItems, setLoadedSlotItems] = useState([]);
  const [loadedSlotMessage, setLoadedSlotMessage] = useState('No cell loaded. Enter address and click Load address.');

  const [onHandList, setOnHandList] = useState([]);
  const [onHandSearch, setOnHandSearch] = useState('');
  const [pendingItems, setPendingItems] = useState([]);
  const [statusMessage, setStatusMessage] = useState('Ready. Enter product ID and load an address to assign.');
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    loadOnHand();
    loadPending();
  }, []);

  const loadOnHand = async () => {
    try {
      const items = await ApiService.getOnHandProducts();
      setOnHandList(items || []);
    } catch (e) {
      console.warn(e);
    }
  };

  const loadPending = async () => {
    try {
      const res = await ApiService.getPendingExceptions();
      if (res && res.items) {
        setPendingItems(res.items);
      }
    } catch (e) {
      console.warn(e);
    }
  };

  const handleLoadAddress = async () => {
    const r = parseInt(row, 10);
    const c = parseInt(col, 10);
    if (isNaN(r) || isNaN(c) || r < 1 || c < 1) {
      alert('Row and cell must be positive whole numbers.');
      return;
    }

    try {
      const res = await ApiService.getSlotAddress(floor, side, shelf, r, c);
      if (res && res.success && res.slot) {
        setLoadedSlotId(res.slot.slot_id);
        setLoadedSlotName(res.slot.slot_name);
        setLoadedSlotItems(res.contents || []);
        setLoadedSlotMessage(`Loaded: ${res.slot.slot_name} · ${(res.contents || []).length} product(s)`);
      } else {
        setLoadedSlotId(null);
        setLoadedSlotName('');
        setLoadedSlotItems([]);
        setLoadedSlotMessage(res?.message || `No cell found at Floor ${floor} / Side ${side} / Shelf ${shelf} / R${r}-C${c}.`);
      }
    } catch (e) {
      alert(`Failed to load address: ${e.message}`);
    }
  };

  const handleAssignException = async () => {
    const trimmedId = productId.trim();
    if (!trimmedId) {
      alert('Please enter or scan a product ID.');
      return;
    }

    const r = parseInt(row, 10);
    const c = parseInt(col, 10);
    if (isNaN(r) || isNaN(c) || r < 1 || c < 1) {
      alert('Row and cell must be positive whole numbers.');
      return;
    }

    const qty = stockQty.trim() !== '' ? parseInt(stockQty, 10) : null;
    if (qty !== null && (isNaN(qty) || qty < 0)) {
      alert('Stock quantity must be a whole number of 0 or greater, or left blank.');
      return;
    }

    setIsBusy(true);
    try {
      const res = await ApiService.assignException({
        product_id: trimmedId,
        floor,
        side,
        shelf,
        row: r,
        col: c,
        quantity: qty,
      });

      if (res && res.success) {
        setStatusMessage(res.message || `Assigned ${trimmedId} to ${res.slot_name}.`);
        setProductId('');
        setStockQty('');
        await handleLoadAddress();
        await loadPending();
        await loadOnHand();
      } else {
        alert(res?.error || res?.message || 'Failed to assign exception.');
      }
    } catch (e) {
      alert(`Assignment error: ${e.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const handleAppendToCSV = async () => {
    if (pendingItems.length === 0) {
      alert('There are no staged exception products waiting to update.');
      return;
    }

    const targetCsv = prompt('Enter CSV filename or path to append exception products (leave blank for full_catalogue.csv):', '');
    if (targetCsv === null) {
      return;
    }

    setIsBusy(true);
    try {
      const res = await ApiService.appendExceptionsToCSV(targetCsv.trim() || undefined);
      if (res && res.success) {
        alert(res.message || `Successfully appended ${res.count} exception(s) to CSV with name 'Exc - added later'.`);
        setStatusMessage(res.message || 'Appended exceptions to CSV.');
        await loadPending();
        await loadOnHand();
      } else {
        alert(res?.error || res?.message || 'Failed to append to CSV.');
      }
    } catch (e) {
      alert(`Append to CSV error: ${e.message}`);
    } finally {
      setIsBusy(false);
    }
  };

  const filteredOnHand = onHandList.filter(
    (item) =>
      !onHandSearch ||
      item.code.toLowerCase().includes(onHandSearch.toLowerCase()) ||
      item.name.toLowerCase().includes(onHandSearch.toLowerCase())
  );

  return (
    <div className="tab-pane-container" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', borderBottom: '1px solid #d0d7de', paddingBottom: '8px' }}>
        <div>
          <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0', color: '#1f2328' }}>
            Special Exceptions & Multi-Location Products
          </h2>
          <div style={{ fontSize: '12px', color: '#656d76' }}>
            Assign items requiring multiple locations or stage unregistered products safely. Staged items will not modify CSV files until appended.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#0969da' }}>
            {pendingItems.length} staged CSV update(s)
          </span>
          <button
            className="vscode-btn vscode-btn-primary"
            onClick={handleAppendToCSV}
            disabled={isBusy || pendingItems.length === 0}
            style={{ fontSize: '12px', padding: '4px 12px' }}
          >
            Append back to CSV
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '12px', flex: 1, minHeight: 0 }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '10px' }}>
            <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '8px', color: '#1f2328' }}>
              Assign Special Exception / Unregistered Product
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <label style={{ fontSize: '12px', minWidth: '130px', fontWeight: 500 }}>Product ID / Barcode:</label>
              <input
                type="text"
                className="vscode-input"
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAssignException(); }}
                placeholder="e.g. 06410-KAN-640 or new code"
                style={{ flex: 1, height: '26px' }}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Floor:</span>
              <input
                type="text"
                className="vscode-input"
                value={floor}
                onChange={(e) => setFloor(e.target.value)}
                style={{ width: '40px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Side:</span>
              <input
                type="text"
                className="vscode-input"
                value={side}
                onChange={(e) => setSide(e.target.value)}
                style={{ width: '40px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Shelf:</span>
              <input
                type="text"
                className="vscode-input"
                value={shelf}
                onChange={(e) => setShelf(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Row:</span>
              <input
                type="number"
                min="1"
                className="vscode-input"
                value={row}
                onChange={(e) => setRow(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <span style={{ fontSize: '12px', fontWeight: 500 }}>Cell:</span>
              <input
                type="number"
                min="1"
                className="vscode-input"
                value={col}
                onChange={(e) => setCol(e.target.value)}
                style={{ width: '45px', height: '24px', textAlign: 'center' }}
              />
              <button
                className="vscode-btn"
                onClick={handleLoadAddress}
                style={{ height: '24px', padding: '0 8px', fontSize: '11px', marginLeft: '4px' }}
              >
                Load address
              </button>
            </div>

            <div style={{ fontSize: '11px', fontWeight: 600, color: loadedSlotId ? '#0969da' : '#656d76', marginBottom: '8px' }}>
              {loadedSlotMessage}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '12px', fontWeight: 500 }}>Stock Qty (optional):</label>
              <input
                type="text"
                className="vscode-input"
                value={stockQty}
                onChange={(e) => setStockQty(e.target.value)}
                placeholder="null"
                style={{ width: '60px', height: '26px', textAlign: 'center' }}
              />
              <button
                className="vscode-btn vscode-btn-primary"
                onClick={handleAssignException}
                disabled={isBusy}
                style={{ flex: 1, height: '28px', fontSize: '12px', fontWeight: 600 }}
              >
                Assign to loaded address
              </button>
            </div>
          </div>

          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#1f2328' }}>Shared On-Hand Products</span>
              <input
                type="text"
                className="vscode-input"
                value={onHandSearch}
                onChange={(e) => setOnHandSearch(e.target.value)}
                placeholder="Search on-hand..."
                style={{ width: '180px', height: '22px', fontSize: '11px' }}
              />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'right', padding: '4px 6px' }}>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOnHand.map((item) => (
                    <tr
                      key={item.code}
                      onClick={() => {
                        setProductId(item.code);
                        if (item.on_hand !== null && item.on_hand !== undefined) {
                          setStockQty(String(item.on_hand));
                        }
                      }}
                      style={{
                        cursor: 'pointer',
                        background: productId === item.code ? '#e8f0fe' : 'transparent',
                        borderBottom: '1px solid #f0f2f5',
                      }}
                    >
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.code}</td>
                      <td style={{ padding: '4px 6px', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.name}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                        {item.on_hand !== null && item.on_hand !== undefined ? item.on_hand : ''}
                      </td>
                    </tr>
                  ))}
                  {filteredOnHand.length === 0 && (
                    <tr>
                      <td colSpan={3} style={{ textAlign: 'center', padding: '12px', color: '#8c959f' }}>
                        No on-hand products found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '6px', color: '#1f2328' }}>
              Current Loaded Cell Contents {loadedSlotName ? `(${loadedSlotName})` : ''}
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'right', padding: '4px 6px' }}>Stock</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Assigned Time</th>
                  </tr>
                </thead>
                <tbody>
                  {loadedSlotItems.map((item, idx) => (
                    <tr key={`${item.product_id}-${idx}`} style={{ borderBottom: '1px solid #f0f2f5' }}>
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.product_id}</td>
                      <td style={{ padding: '4px 6px', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.product_name}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                        {item.stock_qty !== null && item.stock_qty !== undefined ? item.stock_qty : ''}
                      </td>
                      <td style={{ padding: '4px 6px', fontSize: '11px', color: '#555' }}>
                        {item.assigned_at}
                      </td>
                    </tr>
                  ))}
                  {loadedSlotItems.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: '#8c959f' }}>
                        {loadedSlotId ? 'Cell is currently empty.' : 'Load a shelf address to inspect its contents.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ background: '#ffffff', border: '1px solid #d0d7de', borderRadius: '4px', padding: '8px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#1f2328' }}>
                Wait to Update Back to CSV (Staged)
              </span>
              <button
                className="vscode-btn vscode-btn-primary"
                onClick={handleAppendToCSV}
                disabled={isBusy || pendingItems.length === 0}
                style={{ fontSize: '11px', padding: '2px 8px' }}
              >
                Append back to CSV
              </button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #e1e4e8', borderRadius: '2px' }}>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f6f8fa', borderBottom: '1px solid #d0d7de', position: 'sticky', top: 0 }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product ID</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Product Name</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Target Cell</th>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Staged At</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingItems.map((item) => (
                    <tr key={item.id} style={{ borderBottom: '1px solid #f0f2f5' }}>
                      <td style={{ padding: '4px 6px', fontWeight: 500 }}>{item.product_id}</td>
                      <td style={{ padding: '4px 6px', color: '#656d76' }}>{item.product_name}</td>
                      <td style={{ padding: '4px 6px', fontWeight: 600, color: '#0969da' }}>{item.slot_name}</td>
                      <td style={{ padding: '4px 6px', fontSize: '11px', color: '#555' }}>
                        {item.created_at ? item.created_at.replace('T', ' ') : ''}
                      </td>
                    </tr>
                  ))}
                  {pendingItems.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: '#8c959f' }}>
                        No pending exceptions staged.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: '11px', color: '#656d76', marginTop: '6px' }}>
              Newly added exception products wait here safely. Appending will write them with name "Exc - added later" to your chosen CSV file.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- MAIN APP ---

function App() {
  const [activeTab, setActiveTab] = useState('assignment');
  const [pendingCount, setPendingCount] = useState(0);
  const [catalogCount, setCatalogCount] = useState(0);

  useEffect(() => {
    loadCounts();
  }, [activeTab]);

  const loadCounts = async () => {
    try {
      const [pending, catalog] = await Promise.all([ApiService.getPendingQueue(), ApiService.getCatalog()]);
      setPendingCount(pending.length);
      setCatalogCount(catalog.length);
    } catch (e) {
      // Ignore
    }
  };

  return (
    <div className="vscode-workbench">
      {/* Top Navigation Tabs */}
      <div className="vscode-tab-bar" role="tablist">
        <div
          className={`vscode-tab ${activeTab === 'designer' ? 'active' : ''}`}
          onClick={() => setActiveTab('designer')}
          role="tab"
        >
          <span>1. Shelf Designer</span>
        </div>

        <div
          className={`vscode-tab ${activeTab === 'assignment' ? 'active' : ''}`}
          onClick={() => setActiveTab('assignment')}
          role="tab"
        >
          <span>2. Assign Locations</span>
          {pendingCount > 0 && <span className="vscode-tab-badge">{pendingCount}</span>}
        </div>

        <div
          className={`vscode-tab ${activeTab === 'primal_queue' ? 'active' : ''}`}
          onClick={() => setActiveTab('primal_queue')}
          role="tab"
        >
          <span>3. Primal Queue / Shelves</span>
        </div>

        <div
          className={`vscode-tab ${activeTab === 'browser' ? 'active' : ''}`}
          onClick={() => setActiveTab('browser')}
          role="tab"
        >
          <span>4. Browse Shelves</span>
        </div>

        <div
          className={`vscode-tab ${activeTab === 'cell_transfer' ? 'active' : ''}`}
          onClick={() => setActiveTab('cell_transfer')}
          role="tab"
        >
          <span>5. Switch / Combine Cells</span>
        </div>

        <div
          className={`vscode-tab ${activeTab === 'exceptions' ? 'active' : ''}`}
          onClick={() => setActiveTab('exceptions')}
          role="tab"
        >
          <span>6. Special Exceptions</span>
        </div>
      </div>

      {/* Main Content Workspace */}
      <main className="vscode-content-view">
        {activeTab === 'designer' && <ShelfDesignerView />}
        {activeTab === 'assignment' && <LocationAssignmentView />}
        {activeTab === 'primal_queue' && <PrimalQueueView />}
        {activeTab === 'browser' && <ShelfBrowserView />}
        {activeTab === 'cell_transfer' && <CellTransferView />}
        {activeTab === 'exceptions' && <ExceptionsView />}
      </main>

      {/* Bottom Status Bar */}
      <footer className="vscode-status-bar">
        <div className="status-left">
          <div className="status-item">
            <span className="status-dot"></span>
            <span>Ready</span>
          </div>
          <div className="status-item">
            <span>warehouse_locations.db</span>
          </div>
        </div>

        <div className="status-right">
          <div className="status-item">
            <span>Catalog: <strong>{catalogCount}</strong> items</span>
          </div>
          <div className="status-item">
            <span>Queue: <strong>{pendingCount}</strong> pending</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
