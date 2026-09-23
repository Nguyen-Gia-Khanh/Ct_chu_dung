import React, { useState, useSyncExternalStore } from 'react';
import { ActiveTab } from './types';
import { getBackendStatus, subscribeBackendStatus } from './services/backendStatus';
import { WorkbenchChrome } from './components/WorkbenchChrome';
import { ShelfDesignerView } from './views/ShelfDesignerView';
import { LocationAssignmentView } from './views/LocationAssignmentView';
import { PrimalQueueView } from './views/PrimalQueueView';
import { ShelfBrowserView } from './views/ShelfBrowserView';
import { CellTransferView } from './views/CellTransferView';
import { ExceptionsView } from './views/ExceptionsView';

const screens = {
  designer: ShelfDesignerView,
  assignment: LocationAssignmentView,
  primal_queue: PrimalQueueView,
  browser: ShelfBrowserView,
  cell_transfer: CellTransferView,
  exceptions: ExceptionsView,
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('designer');
  const [visited, setVisited] = useState<ActiveTab[]>(['designer']);
  const backendStatus = useSyncExternalStore(subscribeBackendStatus, getBackendStatus);

  const selectTab = (tab: ActiveTab) => {
    setActiveTab(tab);
    setVisited((current) => current.includes(tab) ? current : [...current, tab]);
  };

  return (
    <WorkbenchChrome activeTab={activeTab} onSelectTab={selectTab} backendStatus={backendStatus}>
      {visited.map((tab) => {
        const Screen = screens[tab];
        return (
          <section
            key={tab}
            id={`panel-${tab}`}
            role="tabpanel"
            className="workspace-tab-panel"
            hidden={activeTab !== tab}
          >
            <Screen active={activeTab === tab} />
          </section>
        );
      })}
    </WorkbenchChrome>
  );
};

export default App;
