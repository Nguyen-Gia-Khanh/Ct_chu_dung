import React from 'react';
import { ShelfCanvas } from '../components/ShelfCanvas';
import { ColumnMappingDialog } from '../components/ColumnMappingDialog';
import { getShelfCode } from '../utils/coordinates';
import { useShelfDesignerController } from '../controllers/useShelfDesignerController';

export const ShelfDesignerView: React.FC<{ active: boolean }> = React.memo(({ active }: { active: boolean }) => {
  const {
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
  } = useShelfDesignerController(active);
  return (
    <div className="view-container">
      <div className="designer-toolbar">
        <label className="btn csv-file-button">
          Import working products CSV
          <input type="file" accept=".csv,text/csv" onChange={(event) => {
            void handleCsvFile(event.target.files?.[0] ?? null, 'new');
            event.target.value = '';
          }} />
        </label>
        <label className="btn csv-file-button">
          Import full catalog CSV
          <input type="file" accept=".csv,text/csv" onChange={(event) => {
            void handleCsvFile(event.target.files?.[0] ?? null, 'return');
            event.target.value = '';
          }} />
        </label>
        <button className="btn" onClick={handleNewShelf}>New shelf</button>
        <button className="btn" aria-expanded={previewOpen} onClick={() => setPreviewOpen((open) => !open)}>
          {previewOpen ? 'Hide 2D preview' : 'Preview 2D shelf'}
        </button>
        <label className="form-label" htmlFor="designer-shelf-selector">Edit existing shelf:</label>
        <select
          id="designer-shelf-selector"
          className="input-select"
          value={editingShelfId ?? ''}
          onChange={(event) => {
            const selected = shelves.find((item) => item.id === Number(event.target.value));
            if (selected) handleSelectExisting(selected);
          }}
        >
          <option value="">Select a shelf</option>
          {shelves.map((item) => (
            <option key={item.id} value={item.id}>{getShelfCode(item.floor, item.side, item.shelf)}</option>
          ))}
        </select>
        <button className="btn btn-primary commit-btn" onClick={handleSaveShelf}>Commit shelf design</button>
      </div>
      {statusMsg && <div className={`designer-status ${statusMsg.type}`} role="status">{statusMsg.text}</div>}
      <div className="designer-layout">
        {/* Left Side: Shelf Metadata & Row Customizer (Exact Tkinter format) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div className="panel">
            <div className="panel-header">
              <span className="panel-title">Shelf Metadata</span>
            </div>

            <div className="panel-body">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
                <div className="form-group">
                  <label className="form-label">Floor</label>
                  <input
                    type="number"
                    min="1"
                    max="100"
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
                    max="100"
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
                            max="200"
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
                <div className="saved-shelves">
                  {shelves.map((s) => (
                    <div key={s.id} className="saved-shelf">
                      <button type="button" className="saved-shelf-name" onClick={() => handleSelectExisting(s)}>
                        {getShelfCode(s.floor, s.side, s.shelf)} ({s.rows_count}×{s.default_cols})
                      </button>
                      <button
                        type="button"
                        className="saved-shelf-remove"
                        onClick={() => handleDeleteShelf(s.id)}
                        title="Delete shelf"
                        aria-label={`Delete shelf ${getShelfCode(s.floor, s.side, s.shelf)}`}
                      >
                        ×
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

        {previewOpen && (
        /* Optional 2D preview follows the Tkinter row editor. */
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

          </div>
        </div>
        )}
      </div>
      <ColumnMappingDialog
        isOpen={csvData !== null}
        csvData={csvData}
        modeTitle={csvMode === 'new' ? 'Import working products CSV' : 'Import full catalog CSV'}
        onConfirm={handleCsvConfirm}
        onCancel={() => setCsvData(null)}
      />
    </div>
  );
});
