// Warehouse Shelf Mapper - Browser Runtime
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
};

// --- COMPONENTS ---

function Navbar({ activeTab, onSelectTab, pendingCount = 0, catalogCount = 0 }) {
  return (
    <header className="navbar">
      <div className="brand-container">
        <div className="brand-icon">📦</div>
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
          Tab 5: Switch / Combine
        </button>
      </nav>

      <div className="navbar-actions">
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
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

  const handleDefaultColsChange = (newDefault) => {
    const clamped = Math.max(1, Math.min(40, newDefault));
    setDefaultCols(clamped);
    const updated = {};
    for (let r = 1; r <= rowsCount; r++) {
      updated[r] = clamped;
    }
    setRowCols(updated);
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
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">📐 Shelf Designer & Layout</h2>
            <button className="btn btn-primary btn-sm" onClick={handleSaveShelf}>
              💾 Save Shelf to DB
            </button>
          </div>

          <div className="panel-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
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
                <label className="form-label">Shelf Code</label>
                <input
                  type="text"
                  maxLength={4}
                  className="input-text font-mono"
                  value={shelfLetter}
                  onChange={(e) => setShelfLetter(e.target.value.toUpperCase())}
                  placeholder="e.g. A"
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
              <div className="form-group">
                <label className="form-label">Total Rows</label>
                <input
                  type="number"
                  min="1"
                  max="25"
                  className="input-text font-mono"
                  value={rowsCount}
                  onChange={(e) => handleRowsCountChange(parseInt(e.target.value, 10) || 1)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Default Columns / Row</label>
                <input
                  type="number"
                  min="1"
                  max="35"
                  className="input-text font-mono"
                  value={defaultCols}
                  onChange={(e) => handleDefaultColsChange(parseInt(e.target.value, 10) || 1)}
                />
              </div>
            </div>

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              Per-Row Column Count Customizer:
            </div>
            <div className="table-container" style={{ maxHeight: '220px', marginBottom: '1rem' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Row Number (Ground Up)</th>
                    <th>Columns in this Row</th>
                    <th>Action</th>
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
                          style={{ width: '80px', padding: '0.2rem 0.4rem' }}
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
                          Reset to Default
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              Existing Shelves in Warehouse:
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
              {shelves.map((s) => (
                <div
                  key={s.id}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    background: '#f1f5f9',
                    border: '1px solid #cbd5e1',
                    borderRadius: '4px',
                    padding: '0.2rem 0.5rem',
                    fontSize: '0.8rem',
                  }}
                >
                  <span style={{ cursor: 'pointer', fontWeight: 600 }} onClick={() => handleSelectExisting(s)}>
                    {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}×{s.default_cols})
                  </span>
                  <button
                    onClick={() => handleDeleteShelf(s.id)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444' }}
                    title="Delete shelf"
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              🖼️ 2D Front-View Preview: {getShelfCode(floor, side, shelfLetter)}
            </h2>
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
                  marginTop: '1rem',
                  padding: '0.6rem 0.8rem',
                  borderRadius: '6px',
                  fontSize: '0.825rem',
                  background: statusMsg.type === 'success' ? '#dcfce7' : statusMsg.type === 'error' ? '#fee2e2' : '#eff6ff',
                  color: statusMsg.type === 'success' ? '#166534' : statusMsg.type === 'error' ? '#991b1b' : '#1e40af',
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
  const [batchQueue, setBatchQueue] = useState([]);
  const [activeListTab, setActiveListTab] = useState('pending');

  const [catalogSearch, setCatalogSearch] = useState('');
  const [queueSearch, setQueueSearch] = useState('');

  const [floor, setFloor] = useState(1);
  const [side, setSide] = useState(1);
  const [shelf, setShelf] = useState('A');
  const [row, setRow] = useState(1);
  const [col, setCol] = useState(1);
  const [manualLocInput, setManualLocInput] = useState('');

  const [uploadToKiotViet, setUploadToKiotViet] = useState(false);
  const [logs, setLogs] = useState([]);

  const [stockDialogProducts, setStockDialogProducts] = useState(null);
  const [csvDataToMap, setCsvDataToMap] = useState(null);

  const fileInputRef = useRef(null);
  const importModeRef = useRef('new');

  useEffect(() => {
    refreshData();
  }, []);

  const refreshData = async () => {
    const [cats, pends] = await Promise.all([ApiService.getCatalog(), ApiService.getPendingQueue()]);
    setCatalog(cats);
    setPendingQueue(pends);
  };

  const addLog = (msg, type = 'info') => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${msg}`, ...prev.slice(0, 50)]);
  };

  const handleManualLocChange = (val) => {
    setManualLocInput(val);
    const parsed = parseSlotName(val);
    if (parsed) {
      setFloor(parsed.floor);
      setSide(parsed.side);
      setShelf(parsed.shelf);
      setRow(parsed.row);
      setCol(parsed.col);
    }
  };

  const currentComputedSlot = makeSlotName(floor, shelf, row, col, side);

  const handleAddToBatch = (item) => {
    if (!batchQueue.some((b) => b.code === item.code)) {
      setBatchQueue((prev) => [...prev, item]);
      addLog(`Added ${item.code} to work batch.`);
    }
  };

  const handleRemoveFromBatch = (code) => {
    setBatchQueue((prev) => prev.filter((b) => b.code !== code));
  };

  const handleStartAssign = () => {
    let itemsToAssign = [];
    if (activeListTab === 'batch') {
      itemsToAssign = batchQueue.map((b) => ({ id: b.code, name: b.name, initialQuantity: b.on_hand || 1 }));
    } else if (activeListTab === 'pending') {
      const selected = pendingQueue.filter((p) => p.selected);
      if (selected.length > 0) {
        itemsToAssign = selected.map((p) => ({ id: p.code, name: p.name, initialQuantity: p.on_hand || 1 }));
      }
    }
    if (itemsToAssign.length === 0) {
      alert('Please select at least one product to assign.');
      return;
    }
    setStockDialogProducts(itemsToAssign);
  };

  const handleConfirmStockAssignment = async (quantities) => {
    const slotObj = { floor, side, shelf, row, col };
    for (const [prodId, qty] of Object.entries(quantities)) {
      const found = catalog.find((c) => c.product_id === prodId) || pendingQueue.find((p) => p.code === prodId);
      const res = await ApiService.assignLocation({
        product_id: prodId,
        product_name: found ? (found.name || found.product_name) : prodId,
        barcode: found && found.barcode ? found.barcode : prodId,
        slot: slotObj,
        quantity: qty,
        upload_to_kiotviet: uploadToKiotViet,
      });
      if (res.success) {
        addLog(res.message || `Assigned ${prodId} to ${currentComputedSlot}`);
      } else {
        addLog(res.error || `Failed to assign ${prodId}`);
      }
    }
    setStockDialogProducts(null);
    setBatchQueue([]);
    refreshData();
  };

  const handleDirectMove = async (prod) => {
    const targetSlot = { floor, side, shelf, row, col };
    const res = await ApiService.directMoveLocation(prod.product_id, targetSlot);
    if (res.success) {
      addLog(`Direct moved ${prod.product_id} to ${currentComputedSlot}`);
      refreshData();
    } else {
      addLog(res.error || 'Move failed');
    }
  };

  const handleTriggerCSV = (mode) => {
    importModeRef.current = mode;
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const handleFileSelected = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target.result;
      const lines = text.split(/\r\n|\n/).filter((l) => l.trim().length > 0);
      if (lines.length === 0) return;

      const headers = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
      const rows = [];
      for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',').map((p) => p.trim().replace(/^"|"$/g, ''));
        const rowObj = {};
        headers.forEach((h, idx) => {
          rowObj[h] = parts[idx] || '';
        });
        rows.push(rowObj);
      }
      setCsvDataToMap({ data: { headers, rows }, mode: importModeRef.current });
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleConfirmCSVMapping = async (mapping) => {
    if (!csvDataToMap) return;
    const res = await ApiService.importCSV(csvDataToMap.data, mapping, csvDataToMap.mode);
    if (res.success) {
      addLog(`CSV Import successful: ${res.message}`);
      refreshData();
    } else {
      addLog(`CSV Import error: ${res.error}`);
    }
    setCsvDataToMap(null);
  };

  const filteredPending = pendingQueue.filter((p) => {
    if (!queueSearch) return true;
    const s = normalizeSearch(queueSearch);
    return (
      normalizeSearch(p.code).includes(s) ||
      normalizeSearch(p.name).includes(s) ||
      (p.loc_id && normalizeSearch(p.loc_id).includes(s))
    );
  });

  const filteredCatalog = catalog.filter((p) => {
    if (!catalogSearch) return true;
    const s = normalizeSearch(catalogSearch);
    return (
      normalizeSearch(p.product_id).includes(s) ||
      normalizeSearch(p.barcode).includes(s) ||
      normalizeSearch(p.product_name).includes(s) ||
      (p.loc_id && normalizeSearch(p.loc_id).includes(s))
    );
  });

  return (
    <div className="view-container">
      <input type="file" ref={fileInputRef} accept=".csv" style={{ display: 'none' }} onChange={handleFileSelected} />

      <div className="split-pane left-heavy">
        <div className="panel">
          <div className="panel-header">
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                className={`btn btn-sm ${activeListTab === 'pending' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('pending')}
              >
                Pending Queue ({pendingQueue.length})
              </button>
              <button
                className={`btn btn-sm ${activeListTab === 'catalog' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('catalog')}
              >
                Full Catalog ({catalog.length})
              </button>
              <button
                className={`btn btn-sm ${activeListTab === 'batch' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActiveListTab('batch')}
              >
                Work Batch ({batchQueue.length})
              </button>
            </div>

            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => handleTriggerCSV('new')} title="Import new products from CSV">
                📥 Import CSV
              </button>
              <button className="btn btn-secondary btn-sm" onClick={() => handleTriggerCSV('return')} title="Import returned inventory from CSV">
                ↩️ Return CSV
              </button>
            </div>
          </div>

          <div className="panel-body">
            {activeListTab === 'pending' && (
              <div>
                <div className="input-search-wrapper" style={{ marginBottom: '0.75rem' }}>
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Search pending queue by code or name..."
                    value={queueSearch}
                    onChange={(e) => setQueueSearch(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {queueSearch && (
                    <button className="search-clear-btn" onClick={() => setQueueSearch('')}>
                      &times;
                    </button>
                  )}
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{ width: '36px' }}>
                          <input
                            type="checkbox"
                            onChange={(e) => {
                              const checked = e.target.checked;
                              setPendingQueue((prev) => prev.map((p) => ({ ...p, selected: checked })));
                            }}
                          />
                        </th>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>On Hand</th>
                        <th>Current Loc</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPending.map((item) => (
                        <tr key={item.code} className={item.selected ? 'selected' : ''}>
                          <td>
                            <input
                              type="checkbox"
                              checked={!!item.selected}
                              onChange={(e) => {
                                const checked = e.target.checked;
                                setPendingQueue((prev) =>
                                  prev.map((p) => (p.code === item.code ? { ...p, selected: checked } : p))
                                );
                              }}
                            />
                          </td>
                          <td className="font-mono">
                            <strong>{item.code}</strong>
                          </td>
                          <td>{item.name}</td>
                          <td>{item.on_hand}</td>
                          <td>
                            {item.loc_id ? <span className="loc-pill assigned">{item.loc_id}</span> : <span className="loc-pill">Unassigned</span>}
                          </td>
                          <td>
                            <button className="btn btn-secondary btn-sm" onClick={() => handleAddToBatch(item)}>
                              + Batch
                            </button>
                          </td>
                        </tr>
                      ))}
                      {filteredPending.length === 0 && (
                        <tr>
                          <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                            No pending products in queue.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeListTab === 'catalog' && (
              <div>
                <div className="input-search-wrapper" style={{ marginBottom: '0.75rem' }}>
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Search catalog by code, name, barcode, location..."
                    value={catalogSearch}
                    onChange={(e) => setCatalogSearch(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {catalogSearch && (
                    <button className="search-clear-btn" onClick={() => setCatalogSearch('')}>
                      &times;
                    </button>
                  )}
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>On Hand</th>
                        <th>Location ID</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCatalog.map((prod) => (
                        <tr key={prod.product_id}>
                          <td className="font-mono">
                            <strong>{prod.product_id}</strong>
                          </td>
                          <td>{prod.product_name}</td>
                          <td>{prod.on_hand}</td>
                          <td>
                            {prod.loc_id ? <span className="loc-pill assigned">{prod.loc_id}</span> : <span className="loc-pill">None</span>}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: '0.3rem' }}>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() =>
                                  handleAddToBatch({
                                    code: prod.product_id,
                                    name: prod.product_name,
                                    on_hand: prod.on_hand,
                                    loc_id: prod.loc_id,
                                  })
                                }
                              >
                                + Batch
                              </button>
                              <button
                                className="btn btn-primary btn-sm"
                                onClick={() => handleDirectMove(prod)}
                                title={`Move directly to ${currentComputedSlot}`}
                              >
                                ➔ Move Here
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeListTab === 'batch' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                    Items to be assigned to <strong>{currentComputedSlot}</strong>
                  </span>
                  <button className="btn btn-secondary btn-sm" onClick={() => setBatchQueue([])} disabled={batchQueue.length === 0}>
                    Clear Batch
                  </button>
                </div>

                <div className="table-container" style={{ maxHeight: '420px' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Code</th>
                        <th>Name</th>
                        <th>Qty</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchQueue.map((item) => (
                        <tr key={item.code}>
                          <td className="font-mono">
                            <strong>{item.code}</strong>
                          </td>
                          <td>{item.name}</td>
                          <td>{item.on_hand}</td>
                          <td>
                            <button className="btn btn-danger btn-sm" onClick={() => handleRemoveFromBatch(item.code)}>
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                      {batchQueue.length === 0 && (
                        <tr>
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                            Batch is empty. Select items from Pending or Catalog.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">📍 Target Shelf Address</h2>
            <span className="loc-pill assigned" style={{ fontSize: '0.9rem' }}>
              {currentComputedSlot}
            </span>
          </div>

          <div className="panel-body">
            <div className="form-group" style={{ marginBottom: '1.25rem' }}>
              <label className="form-label">Quick Jump / Manual Location Input</label>
              <input
                type="text"
                className="input-text font-mono"
                placeholder="e.g. L1-1A8-10"
                value={manualLocInput}
                onChange={(e) => handleManualLocChange(e.target.value.toUpperCase())}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
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
                <label className="form-label">Shelf</label>
                <input
                  type="text"
                  maxLength={3}
                  className="input-text font-mono"
                  value={shelf}
                  onChange={(e) => setShelf(e.target.value.toUpperCase())}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Row (From Ground Up)</label>
                <input
                  type="number"
                  min="1"
                  max="25"
                  className="input-text font-mono"
                  value={row}
                  onChange={(e) => setRow(parseInt(e.target.value, 10) || 1)}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Column / Slot</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  className="input-text font-mono"
                  value={col}
                  onChange={(e) => setCol(parseInt(e.target.value, 10) || 1)}
                />
              </div>
            </div>

            <div style={{ marginBottom: '1.25rem' }}>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  className="toggle-checkbox"
                  checked={uploadToKiotViet}
                  onChange={(e) => setUploadToKiotViet(e.target.checked)}
                />
                <span>🌐 Upload / Sync to KiotViet Web Automatically</span>
              </label>
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
              <button className="btn btn-primary" style={{ flex: 1, padding: '0.65rem' }} onClick={handleStartAssign}>
                ✅ Assign Selected to {currentComputedSlot}
              </button>
            </div>

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
              Activity Log:
            </div>
            <div className="status-log">
              {logs.map((log, i) => (
                <div key={i}>{log}</div>
              ))}
              {logs.length === 0 && <div>Waiting for action...</div>}
            </div>
          </div>
        </div>
      </div>

      {stockDialogProducts && (
        <StockQuantityDialog
          isOpen={true}
          slotName={currentComputedSlot}
          products={stockDialogProducts}
          onConfirm={handleConfirmStockAssignment}
          onCancel={() => setStockDialogProducts(null)}
        />
      )}

      {csvDataToMap && (
        <ColumnMappingDialog
          isOpen={true}
          csvData={csvDataToMap.data}
          modeTitle={csvDataToMap.mode === 'new' ? 'Import New Products' : 'Import Returned Stock'}
          onConfirm={handleConfirmCSVMapping}
          onCancel={() => setCsvDataToMap(null)}
        />
      )}
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
            <h2 className="panel-title">⚡ Primal Product Queue & Scanner</h2>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{filteredQueue.length} items</span>
          </div>

          <div className="panel-body">
            <div className="input-search-wrapper" style={{ marginBottom: '0.75rem' }}>
              <input
                type="text"
                className="input-text font-mono"
                placeholder="Scan / enter barcode (clears on click)..."
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

            <div className="table-container" style={{ maxHeight: '520px' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Barcode / Code</th>
                    <th>Product Name</th>
                    <th>Qty</th>
                    <th>Status / Location</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredQueue.map((item) => (
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
                            👁️ View Shelf
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filteredQueue.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                        No matching items found in primal queue.
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h2 className="panel-title">🗄️ Shelf View:</h2>
              <select
                className="input-select"
                style={{ padding: '0.2rem 0.5rem', fontWeight: 600 }}
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
              <span className="loc-pill assigned" style={{ fontSize: '0.85rem' }}>
                Slot: {selectedCellLoc}
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
                No shelves created yet. Use Tab 1: Shelf Designer to create a shelf.
              </div>
            )}

            <div style={{ marginTop: '1.25rem' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.4rem', display: 'flex', justifyContent: 'space-between' }}>
                <span>
                  Contents in <strong className="font-mono">{selectedCellLoc || 'No Cell Selected'}</strong>:
                </span>
                <span style={{ color: 'var(--text-muted)' }}>{activeCellItems.length} product(s)</span>
              </div>

              <div className="table-container" style={{ maxHeight: '180px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Product Name</th>
                      <th>Qty</th>
                      <th>Action</th>
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
                          <button className="btn btn-danger btn-sm" onClick={() => handleRemoveProduct(item.product_id)}>
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                    {activeCellItems.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                          {selectedCellLoc ? 'This cell is empty.' : 'Click any cell on the shelf above to view contents.'}
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
      <div className="panel" style={{ marginBottom: '0.75rem' }}>
        <div style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <label className="form-label" style={{ margin: 0 }}>
              Select Shelf to Browse:
            </label>
            <select
              className="input-select"
              style={{ fontWeight: 600, minWidth: '180px' }}
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
          </div>

          <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem' }}>
            <div>
              Occupied Cells: <strong style={{ color: '#2e7d32' }}>{occupiedCount}</strong>
            </div>
            <div>
              Total Products Stored: <strong>{totalUnits}</strong> units
            </div>
          </div>
        </div>
      </div>

      <div className="split-pane right-heavy">
        <div className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              🏢 {selectedShelf ? getShelfCode(selectedShelf.floor, selectedShelf.side, selectedShelf.shelf) : 'Shelf'} Layout
            </h2>
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
            <h2 className="panel-title">📋 Cell Details: {selectedCellLoc || 'Select a Cell'}</h2>
            {selectedCellLoc && (
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {items.length} item(s) / {selectedCell ? selectedCell.total_quantity : 0} units
              </span>
            )}
          </div>

          <div className="panel-body">
            {selectedCellLoc ? (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '1rem' }}>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>ROW (GROUND UP)</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>Row {selectedRow}</div>
                  </div>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>COLUMN / CELL</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>Col {selectedCol}</div>
                  </div>
                  <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '4px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>STATUS</div>
                    <div style={{ fontSize: '0.9rem', fontWeight: 600, color: items.length > 0 ? '#15803d' : '#64748b' }}>
                      {items.length > 0 ? 'Occupied' : 'Empty'}
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
                  Products Stored in this Cell:
                </div>
                <div className="table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>Barcode</th>
                        <th>Qty</th>
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
                          <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
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
                <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🔍</div>
                <div>Click on any slot in the shelf grid to inspect its contents.</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CellTransferView() {
  const [shelves, setShelves] = useState([]);
  const [shelfA, setShelfA] = useState(null);
  const [rowA, setRowA] = useState(1);
  const [colA, setColA] = useState(1);
  const [cellsDataA, setCellsDataA] = useState({});

  const [shelfB, setShelfB] = useState(null);
  const [rowB, setRowB] = useState(1);
  const [colB, setColB] = useState(1);
  const [cellsDataB, setCellsDataB] = useState({});

  const [jumpQuery, setJumpQuery] = useState('');
  const [logs, setLogs] = useState([]);

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

  const addLog = (msg) => {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [`[${time}] ${msg}`, ...prev.slice(0, 40)]);
  };

  const handleSelectShelfA = async (s) => {
    setShelfA(s);
    const code = getShelfCode(s.floor, s.side, s.shelf);
    const cells = await ApiService.getShelfCells(code);
    setCellsDataA(cells);
    setRowA(1);
    setColA(1);
  };

  const handleSelectShelfB = async (s) => {
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

  const handleQuickJump = async (val) => {
    const formatted = formatProductId(val);
    setJumpQuery(formatted);
    if (!formatted.trim()) return;

    const res = await ApiService.findProductLocation(formatted);
    if (res.product && res.location) {
      const parsed = parseSlotName(res.location);
      if (parsed) {
        const foundShelf = shelves.find(
          (s) => s.floor === parsed.floor && s.side === parsed.side && s.shelf.toUpperCase() === parsed.shelf.toUpperCase()
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

      <div className="panel" style={{ padding: '0.85rem 1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
          <button className="btn btn-primary" style={{ padding: '0.6rem 1.25rem' }} onClick={handleSwitchCells}>
            🔄 Switch Cells ({slotLocA} ⇄ {slotLocB})
          </button>
          <button className="btn btn-secondary" style={{ padding: '0.6rem 1.25rem' }} onClick={handleCombineCells}>
            ➕ Combine Cell A into Cell B ({slotLocA} ➔ {slotLocB})
          </button>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Both operations are executed atomically.</span>
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
    <div className="app-container">
      <Navbar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        pendingCount={pendingCount}
        catalogCount={catalogCount}
      />

      <main className="app-content">
        {activeTab === 'designer' && <ShelfDesignerView />}
        {activeTab === 'assignment' && <LocationAssignmentView />}
        {activeTab === 'primal_queue' && <PrimalQueueView />}
        {activeTab === 'browser' && <ShelfBrowserView />}
        {activeTab === 'cell_transfer' && <CellTransferView />}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
