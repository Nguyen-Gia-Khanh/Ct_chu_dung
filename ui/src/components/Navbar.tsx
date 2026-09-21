import React from 'react';
import { ActiveTab } from '../types';

interface NavbarProps {
  activeTab: ActiveTab;
  onSelectTab: (tab: ActiveTab) => void;
  pendingCount?: number;
  catalogCount?: number;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  onSelectTab,
  pendingCount = 0,
  catalogCount = 0,
}) => {
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
      </nav>

      <div className="navbar-actions">
        <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
          Catalog: <strong>{catalogCount}</strong> items
        </span>
      </div>
    </header>
  );
};
