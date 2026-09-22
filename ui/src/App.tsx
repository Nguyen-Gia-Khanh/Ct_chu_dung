import React, { useState, useEffect } from 'react';
import { ActiveTab } from './types';
import { ShelfDesignerView } from './views/ShelfDesignerView';
import { LocationAssignmentView } from './views/LocationAssignmentView';
import { PrimalQueueView } from './views/PrimalQueueView';
import { ShelfBrowserView } from './views/ShelfBrowserView';
import { CellTransferView } from './views/CellTransferView';
import { ExceptionsView } from './views/ExceptionsView';
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

      {/* Editor Workspace View */}
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
};

export default App;
