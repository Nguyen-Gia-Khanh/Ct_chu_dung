import React, { useState, useEffect } from 'react';
import { ActiveTab } from './types';
import { ShelfDesignerView } from './views/ShelfDesignerView';
import { LocationAssignmentView } from './views/LocationAssignmentView';
import { PrimalQueueView } from './views/PrimalQueueView';
import { ShelfBrowserView } from './views/ShelfBrowserView';
import { CellTransferView } from './views/CellTransferView';
import { ApiService } from './services/api';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('assignment');
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [catalogCount, setCatalogCount] = useState<number>(0);

  useEffect(() => {
    loadCounts();
  }, [activeTab]);

  const loadCounts = async () => {
    try {
      const [pending, catalog] = await Promise.all([
        ApiService.getPendingQueue(),
        ApiService.getCatalog(),
      ]);
      setPendingCount(pending.length);
      setCatalogCount(catalog.length);
    } catch {
      // Ignore count load errors
    }
  };

  return (
    <div className="vscode-workbench">
      <div className="vscode-main-area">
        {/* VS Code Left Activity Bar */}
        <nav className="vscode-activity-bar" aria-label="Activity Bar">
          <button
            className={`activity-item ${activeTab === 'designer' ? 'active' : ''}`}
            onClick={() => setActiveTab('designer')}
            title="1. Shelf Designer"
          >
            {/* Codicon: layout-grid */}
            <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1 2.5A1.5 1.5 0 0 1 2.5 1h11A1.5 1.5 0 0 1 15 2.5v11a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 2.5zM2.5 2a.5.5 0 0 0-.5.5V7h5V2H2.5zM8 2v5h6V2.5a.5.5 0 0 0-.5-.5H8zm6 6H8v6h5.5a.5.5 0 0 0 .5-.5V8zm-7 6V8H2v5.5a.5.5 0 0 0 .5.5H7z"/>
            </svg>
          </button>

          <button
            className={`activity-item ${activeTab === 'assignment' ? 'active' : ''}`}
            onClick={() => setActiveTab('assignment')}
            title="2. Assign Locations"
          >
            {/* Codicon: list-selection */}
            <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
              <path d="M2.5 3a.5.5 0 0 0 0 1h11a.5.5 0 0 0 0-1h-11zm0 5a.5.5 0 0 0 0 1h11a.5.5 0 0 0 0-1h-11zm0 5a.5.5 0 0 0 0 1h11a.5.5 0 0 0 0-1h-11zM1 3.5a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0zm0 5a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0zm0 5a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0z"/>
            </svg>
            {pendingCount > 0 && <span className="activity-badge">{pendingCount}</span>}
          </button>

          <button
            className={`activity-item ${activeTab === 'primal_queue' ? 'active' : ''}`}
            onClick={() => setActiveTab('primal_queue')}
            title="3. Primal Queue / Shelves"
          >
            {/* Codicon: package */}
            <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8.1 1.05a1 1 0 0 0-.2 0l-6 2.5A1 1 0 0 0 1.5 4.5v7a1 1 0 0 0 .56.9l6 2.5a1 1 0 0 0 .88 0l6-2.5a1 1 0 0 0 .56-.9v-7a1 1 0 0 0-.6-.92l-6-2.53zM8 2.14l5.14 2.14L8 6.43 2.86 4.28 8 2.14zM2.5 5.37l5 2.14v6.2l-5-2.08V5.37zm6 8.34v-6.2l5-2.14v6.26l-5 2.08z"/>
            </svg>
          </button>

          <button
            className={`activity-item ${activeTab === 'browser' ? 'active' : ''}`}
            onClick={() => setActiveTab('browser')}
            title="4. Browse Shelves"
          >
            {/* Codicon: search */}
            <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
              <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001c.03.04.062.078.098.115l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85a1.007 1.007 0 0 0-.115-.1zM12 6.5a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0z"/>
            </svg>
          </button>

          <button
            className={`activity-item ${activeTab === 'cell_transfer' ? 'active' : ''}`}
            onClick={() => setActiveTab('cell_transfer')}
            title="5. Switch / Combine Cells"
          >
            {/* Codicon: arrow-swap */}
            <svg width="22" height="22" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1 11.5a.5.5 0 0 0 .5.5h11.793l-3.147 3.146a.5.5 0 0 0 .708.708l4-4a.5.5 0 0 0 0-.708l-4-4a.5.5 0 0 0-.708.708L13.293 11H1.5a.5.5 0 0 0-.5.5zm14-7a.5.5 0 0 0-.5-.5H2.707l3.147-3.146a.5.5 0 1 0-.708-.708l-4 4a.5.5 0 0 0 0 .708l4 4a.5.5 0 1 0 .708-.708L2.707 4H14.5a.5.5 0 0 0 .5-.5z"/>
            </svg>
          </button>

          <div className="activity-spacer"></div>

          <button className="activity-item" title="Settings / DB Status">
            {/* Codicon: settings-gear */}
            <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor">
              <path d="M9.1 4.4L8.6 2H7.4l-.5 2.4-.7.3-2-1.3-.9.8 1.3 2-.2.7-2.4.5v1.2l2.4.5.3.8-1.3 2 .8.8 2-1.3.8.3.4 2.3h1.2l.5-2.4.8-.3 2 1.3.8-.8-1.3-2 .3-.8 2.3-.4V7.4l-2.4-.5-.3-.7 1.3-2-.8-.9-2 1.3-.7-.3zM8 10a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/>
            </svg>
          </button>
        </nav>

        {/* Main Editor Part */}
        <div className="vscode-editor-part">
          {/* Editor Tab Bar */}
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
          </div>

          {/* Editor Workspace View */}
          <main className="vscode-content-view">
            {activeTab === 'designer' && <ShelfDesignerView />}
            {activeTab === 'assignment' && <LocationAssignmentView />}
            {activeTab === 'primal_queue' && <PrimalQueueView />}
            {activeTab === 'browser' && <ShelfBrowserView />}
            {activeTab === 'cell_transfer' && <CellTransferView />}
          </main>
        </div>
      </div>

      {/* VS Code Bottom Status Bar (#007acc) */}
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
          <div className="status-item">
            <span>UTF-8</span>
          </div>
          <div className="status-item">
            <span>CRLF</span>
          </div>
          <div className="status-item">
            <span>VS Code Light+</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default App;
