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

  const handleRowsCountChange = (newCount: number) => {
    const clamped = Math.max(1, Math.min(25, newCount));
    setRowsCount(clamped);
    const updated: Record<number, number> = {};
    for (let r = 1; r <= clamped; r++) {
      updated[r] = rowCols[r] || defaultCols;
    }
    setRowCols(updated);
  };

  const handleAddRowAtTop = () => {
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
      const res = await ApiService.saveShelf(shelfPayload);
      if (res && res.error) {
        setStatusMsg({ text: `Error saving shelf: ${res.error}`, type: 'error' });
        return;
      }
      setStatusMsg({
        text: `Successfully saved Shelf ${getShelfCode(floor, side, shelfLetter)} (${rowsCount} rows)`,
        type: 'success',
      });
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

  return (
    <div className="view-container">
      <div className="split-pane">
        {/* Left Side: Shelf Metadata & Row Customizer (Exact Tkinter format) */}
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
                      <span
                        style={{ cursor: 'pointer', fontWeight: 600 }}
                        onClick={() => handleSelectExisting(s)}
                      >
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
                    <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                      No shelves saved.
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side: 2D Front-View Preview */}
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
};
