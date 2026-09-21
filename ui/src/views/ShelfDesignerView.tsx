import React, { useState, useEffect } from 'react';
import { Shelf } from '../types';
import { ApiService } from '../services/api';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { getShelfCode } from '../utils/coordinates';

export const ShelfDesignerView: React.FC = () => {
  const [shelves, setShelves] = useState<Shelf[]>([]);
  const [floor, setFloor] = useState<number>(1);
  const [side, setSide] = useState<number>(1);
  const [shelfLetter, setShelfLetter] = useState<string>('A');
  const [rowsCount, setRowsCount] = useState<number>(8);
  const [defaultCols, setDefaultCols] = useState<number>(10);
  const [rowCols, setRowCols] = useState<Record<number, number>>({});
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ text: string; type: 'info' | 'success' | 'error' } | null>(null);

  useEffect(() => {
    loadShelves();
  }, []);

  const loadShelves = async () => {
    const list = await ApiService.getShelves();
    setShelves(list);
  };

  // Sync rowCols whenever rowsCount or defaultCols changes
  const handleRowsCountChange = (newCount: number) => {
    const clamped = Math.max(1, Math.min(25, newCount));
    setRowsCount(clamped);
    const updated: Record<number, number> = {};
    for (let r = 1; r <= clamped; r++) {
      updated[r] = rowCols[r] || defaultCols;
    }
    setRowCols(updated);
  };

  const handleDefaultColsChange = (newDefault: number) => {
    const clamped = Math.max(1, Math.min(40, newDefault));
    setDefaultCols(clamped);
    const updated: Record<number, number> = {};
    for (let r = 1; r <= rowsCount; r++) {
      updated[r] = clamped;
    }
    setRowCols(updated);
  };

  const handleRowColOverride = (rowNum: number, cols: number) => {
    const clamped = Math.max(1, Math.min(50, cols));
    setRowCols((prev) => ({ ...prev, [rowNum]: clamped }));
  };

  const handleSelectExisting = (s: Shelf) => {
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
      const shelfPayload: Shelf = {
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
    } catch (err: unknown) {
      setStatusMsg({ text: `Error saving shelf: ${String(err)}`, type: 'error' });
    }
  };

  const handleDeleteShelf = async (id?: number) => {
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
        {/* Left Side: Shelf Parameters & Row Customizer */}
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
                <select
                  className="input-select"
                  value={side}
                  onChange={(e) => setSide(parseInt(e.target.value, 10) || 1)}
                >
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
                          onChange={(e) =>
                            handleRowColOverride(rowNum, parseInt(e.target.value, 10) || defaultCols)
                          }
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

            {/* Existing Shelves Quick Loader */}
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
                  <span
                    style={{ cursor: 'pointer', fontWeight: 600 }}
                    onClick={() => handleSelectExisting(s)}
                  >
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

        {/* Right Side: 2D Interactive Preview */}
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
                  background:
                    statusMsg.type === 'success'
                      ? '#dcfce7'
                      : statusMsg.type === 'error'
                      ? '#fee2e2'
                      : '#eff6ff',
                  color:
                    statusMsg.type === 'success'
                      ? '#166534'
                      : statusMsg.type === 'error'
                      ? '#991b1b'
                      : '#1e40af',
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
};
