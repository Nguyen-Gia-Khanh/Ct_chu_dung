<script lang="ts">
  import ShelfGrid from "../components/ShelfGrid.svelte";
  import Split from "../components/Split.svelte";
  import VirtualTable from "../components/VirtualTable.svelte";
  import { app, applied, errorText, setStatus, stale } from "../lib/app.svelte";
  import { idColumn, productColumns, stockText } from "../lib/columns";
  import { askNumber, askStock, confirm, fail, notify } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import { normalizeSku } from "../lib/scanner";
  import { startWebJob } from "../lib/web.svelte";
  import type { Column, ContentRow, GridModel, OnHandRow, ProductRow, SearchResult, ShelfView, SlotAddress, WriteResult } from "../lib/types";

  /** Tab 2: put products on a shelf address. Every action saves immediately. */
  const CONFIRM_CLICKS = 3;

  let query = $state("");
  let queue = $state<SearchResult | null>(null);
  let catalog = $state<SearchResult | null>(null);
  let queueSelected = $state<string[]>([]);
  let catalogSelected = $state<string[]>([]);
  let searchStatus = $state("");
  let searchHasPlace = $state(false);
  let exact = $state<ProductRow | null>(null);
  let quickIndex = 0;

  let handView = $state<"queue" | "shelf">("queue");
  let onHand = $state<OnHandRow[]>([]);
  let handSelected = $state<string[]>([]);
  let preview = $state<GridModel | null>(null);
  let previewMessage = $state("Enter Floor, Side, and Shelf below.");

  let floor = $state("");
  let side = $state("");
  let code = $state("");
  let rowText = $state("");
  let cellText = $state("");
  let address = $state<SlotAddress | null>(null);
  let addressMessage = $state("Enter a shelf address and press Load address.");
  let contents = $state<ContentRow[]>([]);
  let contentSelected = $state<string[]>([]);
  let wholeCell = $state(false);

  let whole = $state(false);
  let shiftClicks = $state(0);
  let canRevert = $state(false);
  let seen = -1;
  let scanSeen = 0;
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let previewTimer: ReturnType<typeof setTimeout> | undefined;
  let clickTimer: ReturnType<typeof setTimeout> | undefined;

  const queueColumns: Column<ProductRow>[] = [idColumn<ProductRow>(), productColumns.name, productColumns.location];
  const catalogColumns = queueColumns;
  const handColumns: Column<OnHandRow>[] = [
    idColumn<OnHandRow>(),
    { key: "name", label: "Product name", width: "minmax(120px, 1fr)", value: (row) => row.name },
    { key: "stock", label: "Stock", width: "80px", align: "right", value: (row) => stockText(row.stock) },
  ];
  const contentColumns: Column<ContentRow>[] = [
    idColumn<ContentRow>(),
    { key: "name", label: "Product name", width: "minmax(120px, 1fr)", value: (row) => row.name },
    { key: "stock", label: "Stock", width: "70px", align: "right", value: (row) => stockText(row.stock) },
    { key: "added", label: "Added to shelf", width: "160px", value: (row) => row.assigned_at || "Unknown" },
    { key: "modified", label: "Latest stock change", width: "160px", value: (row) => row.modified_at },
  ];

  const ready = (row: ProductRow) => !row.location && !row.on_hand;
  const queueLabel = $derived(
    whole ? (shiftClicks ? `Click ${CONFIRM_CLICKS - shiftClicks} more time${CONFIRM_CLICKS - shiftClicks === 1 ? "" : "s"}` : "Shift: whole queue → loaded address")
      : "Assign selected queue → loaded address");

  $effect(() => {
    if (stale("assign", seen)) {
      seen = app.changes.seq;
      refresh();
    }
  });

  $effect(() => {
    if (app.tab === "assign" && app.scan.seq !== scanSeen) {
      scanSeen = app.scan.seq;
      query = app.scan.code;
      search();
    }
  });

  async function refresh() {
    await Promise.all([search(), loadOnHand(), reloadAddress(), refreshPreview(), call<boolean>("assign.can_revert").then((v) => (canRevert = v))]);
  }

  function typed() {
    clearTimeout(searchTimer);
    resetClicks();
    searchTimer = setTimeout(search, 150);
  }

  async function search() {
    try {
      [queue, catalog] = await Promise.all([
        call<SearchResult>("products.search", { query, scope: "hot", order: "queue" }),
        call<SearchResult>("products.search", { query, scope: "catalog", match_locations: true }),
      ]);
      exact = query.trim() ? await call<ProductRow | null>("products.lookup", { query }) : null;
      quickIndex = 0;
      if (!exact) [searchStatus, searchHasPlace] = [query.trim() ? "Not in" : "", false];
      else if (exact.on_hand) [searchStatus, searchHasPlace] = [`In on-hand queue · stock ${stockText(exact.stock)}`, true];
      else if (exact.location) [searchStatus, searchHasPlace] = [`Already at ${exact.location}`, true];
      else [searchStatus, searchHasPlace] = ["Not in", false];
    } catch (problem) {
      setStatus(errorText(problem));
    }
  }

  async function loadOnHand() {
    onHand = await call<OnHandRow[]>("onhand.list");
    handSelected = handSelected.filter((id) => onHand.some((row) => row.product_id === id));
  }

  // --- address ---------------------------------------------------------------
  function addressChanged() {
    rowText = "";
    cellText = "";
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 250);
  }

  async function refreshPreview() {
    if (!floor.trim() || !side.trim() || !code.trim()) {
      [preview, previewMessage] = [null, "Enter Floor, Side, and Shelf below."];
      return;
    }
    const id = await call<number | null>("shelves.find", { floor, side, code });
    if (id === null) {
      [preview, previewMessage] = [null, `No saved shelf at Floor ${floor} / Side ${side} / Shelf ${code}.`];
      return;
    }
    preview = await call<ShelfView>("shelves.grid", { shelf_id: id });
  }

  async function loadAddress() {
    const [row, cell] = [Number(rowText), Number(cellText)];
    if (!floor.trim() || !side.trim() || !code.trim()) return notify("Enter floor, side, and shelf code.");
    if (!Number.isInteger(row) || !Number.isInteger(cell) || row < 1 || cell < 1) return notify("Row and cell must be positive whole numbers.");
    address = await call<SlotAddress | null>("cells.address", { floor, side, code, row, cell });
    if (!address) {
      addressMessage = `No saved cell at Floor ${floor} / Side ${side} / Shelf ${code} / Row ${row} / Cell ${cell}.`;
      contents = [];
      return;
    }
    await loadContents();
    setStatus(`Loaded ${address.slot_name}.`);
  }

  async function loadContents() {
    if (!address) return;
    contents = await call<ContentRow[]>("cells.contents", { slot_id: address.slot_id });
    contentSelected = contentSelected.filter((id) => contents.some((row) => row.product_id === id));
    addressMessage = `Loaded ${address.slot_name} · ${contents.length} product(s)`;
  }

  async function reloadAddress() {
    if (!address) return;
    const current = await call<SlotAddress | null>("cells.get", { slot_id: address.slot_id });
    if (!current) {
      address = null;
      contents = [];
      addressMessage = "The loaded address changed or was removed. Enter and load it again.";
      return;
    }
    if (current.slot_name !== address.slot_name) {
      [floor, side, code, rowText, cellText] = [current.floor, current.side, current.shelf_code, String(current.row_number), String(current.slot_number)];
    }
    address = current;
    await loadContents();
  }

  function pickCell(row: number, cell: number) {
    rowText = String(row);
    cellText = String(cell);
    loadAddress();
  }

  async function goTo(target: SlotAddress) {
    [floor, side, code, rowText, cellText] = [target.floor, target.side, target.shelf_code, String(target.row_number), String(target.slot_number)];
    handView = "shelf";
    await refreshPreview();
    address = target;
    await loadContents();
  }

  async function quickMove() {
    if (!exact) return;
    const addresses = await call<SlotAddress[]>("products.locations", { product_id: exact.product_id });
    if (!addresses.length) return notify(`${exact.product_id} has no saved location.`);
    const target = addresses[quickIndex % addresses.length];
    quickIndex += 1;
    await goTo(target);
    setStatus(addresses.length > 1 ? `Location ${((quickIndex - 1) % addresses.length) + 1} of ${addresses.length} for ${exact.product_id}.` : `Loaded ${target.slot_name}.`);
  }

  // --- writes ------------------------------------------------------------------
  async function run<T extends WriteResult>(method: string, params: Record<string, unknown>, status: (result: T) => string) {
    try {
      const result = applied(await call<T>(method, params));
      setStatus(status(result));
      return result;
    } catch (problem) {
      await fail(errorText(problem), "Not saved");
      return null;
    }
  }

  function requireAddress(): SlotAddress | null {
    if (!address) notify("Enter the shelf address and press Load address first.");
    return address;
  }

  async function assignWithStock(rows: ProductRow[]) {
    const target = requireAddress();
    if (!target || !rows.length) return;
    const quantities = await askStock({
      title: `Assign products to ${target.slot_name}`, destination: target.slot_name,
      products: rows.map((row) => ({ product_id: row.product_id, name: row.name, stock: row.stock })),
    });
    if (!quantities) return;
    await run("assign.products", { slot_id: target.slot_id, quantities },
      (r) => `Assigned ${r.count} product(s) to ${target.slot_name}. Saved immediately.`);
  }

  function resetClicks() {
    clearTimeout(clickTimer);
    shiftClicks = 0;
  }

  async function assignQueue(event: MouseEvent) {
    const rows = queue?.rows ?? [];
    if (!(whole || event.shiftKey)) {
      resetClicks();
      const chosen = rows.filter((row) => queueSelected.includes(row.product_id) && ready(row));
      if (!chosen.length) return notify("Select one or more ready products from the queue. Products already on-hand or assigned cannot move again.");
      return assignWithStock(chosen);
    }
    const target = requireAddress();
    const ids = rows.filter(ready).map((row) => row.product_id);
    if (!target || !ids.length) {
      [searchStatus, searchHasPlace] = [target ? "No products in queue to transfer." : searchStatus, true];
      return resetClicks();
    }
    if (ids.length > 1) {
      shiftClicks += 1;
      clearTimeout(clickTimer);
      if (shiftClicks < CONFIRM_CLICKS) {
        clickTimer = setTimeout(resetClicks, 3000);
        return;
      }
    }
    resetClicks();
    const result = await run<WriteResult & { can_revert: boolean }>("assign.shift_queue", { slot_id: target.slot_id, product_ids: ids },
      (r) => `Transferred ${r.count} queue product(s) to ${target.slot_name} with retained stock (999 when uncounted).`);
    if (result) canRevert = true;
  }

  async function assignCatalog(event: MouseEvent) {
    const chosen = (catalog?.rows ?? []).filter((row) => catalogSelected.includes(row.product_id));
    if (!chosen.length) return notify("Select one or more products from the full catalog first.");
    if (!(whole || event.shiftKey)) return assignWithStock(chosen);
    const target = requireAddress();
    if (!target) return;
    const result = await run<WriteResult>("assign.shift_catalog", { slot_id: target.slot_id, product_ids: chosen.map((row) => row.product_id) },
      (r) => `Assigned ${r.count} catalog product(s) directly to ${target.slot_name}.`);
    if (result) canRevert = true;
  }

  async function assignOnHand(event: MouseEvent) {
    const target = requireAddress();
    if (!target) return;
    const all = whole || event.shiftKey;
    if (all && !onHand.length) return notify("There are no products in the on-hand queue to assign.");
    if (!all && !handSelected.length) return notify("Select one or more on-hand products (Ctrl-click), or hold Shift for all.");
    const result = await run<WriteResult & { can_revert: boolean }>("assign.on_hand", { slot_id: target.slot_id, product_ids: all ? null : handSelected },
      (r) => `Assigned ${all ? "all " : ""}${r.count} on-hand product(s) to ${target.slot_name}. Saved immediately.`);
    if (result?.can_revert) canRevert = true;
  }

  async function revert() {
    if (!(await confirm("Revert the latest Shift transfer?"))) return;
    if (await run("assign.revert", {}, () => "Reverted the latest Shift transfer.")) canRevert = false;
  }

  async function editOnHand() {
    const row = onHand.find((item) => item.product_id === handSelected[0]);
    if (handSelected.length !== 1 || !row) return notify("Select exactly one product in the on-hand queue.");
    const quantity = await askNumber({ title: "Modify on-hand stock", text: `Product: ${row.product_id}\nCurrent stock: ${stockText(row.stock)}`, initial: row.stock ?? 0 });
    if (quantity === null || quantity === row.stock) return;
    await run("onhand.set_stock", { product_id: row.product_id, quantity }, () => `Updated on-hand stock for ${row.product_id} to ${quantity}.`);
  }

  async function editStock() {
    const target = requireAddress();
    const row = contents.find((item) => item.product_id === contentSelected[0]);
    if (!target) return;
    if (contentSelected.length !== 1 || !row) return notify("Select exactly one product in the loaded address contents.");
    const quantity = await askNumber({ title: "Modify stock quantity", text: `Product: ${row.product_id}\nLocation: ${target.slot_name}\nCurrent stock: ${stockText(row.stock)}`, initial: row.stock ?? 0 });
    if (quantity === null || quantity === row.stock) return;
    await run("placements.set_stock", { product_id: row.product_id, quantity, slot_id: target.slot_id },
      () => `Updated ${row.product_id} stock at ${target.slot_name}: ${stockText(row.stock)} → ${quantity}.`);
  }

  async function toOnHand(all: boolean) {
    const target = requireAddress();
    if (!target) return;
    if (all) {
      if (!contents.length) return setStatus(`${target.slot_name} is already empty.`);
      if (!(await confirm(`Move all ${contents.length} product(s) from ${target.slot_name} to on-hand?`))) return;
    } else if (!contentSelected.length) {
      return notify("Select one or more products in the loaded address (Ctrl-click) first.");
    }
    await run("cells.to_on_hand", { slot_id: target.slot_id, product_ids: all ? null : contentSelected },
      (r) => `Moved ${r.count} product(s) from ${target.slot_name} to on-hand.`);
  }

  async function modifyWebLocation() {
    const target = requireAddress();
    if (!target) return;
    const ids = wholeCell ? contents.map((row) => row.product_id) : contentSelected;
    if (!ids.length || (!wholeCell && ids.length !== 1)) {
      return notify(wholeCell ? `${target.slot_name} does not contain any products.` : "Select exactly one product in the loaded address contents.");
    }
    await startWebJob("web.update_locations", { product_ids: ids, save_each: wholeCell }, `Updating web location${ids.length > 1 ? "s" : ""} for ${ids.length} product(s)…`);
  }

  function keys(event: KeyboardEvent) {
    if (app.tab !== "assign" || event.key !== "Shift") return;
    whole = event.type === "keydown";
    if (!whole) resetClicks();
  }
</script>

<svelte:window onkeydown={keys} onkeyup={keys} onblur={() => ((whole = false), resetClicks())} />

<div class="tab-split">
  <Split id="assign" sizes={[5, 4, 5]} panes={[productsPane, handPane, cellPane]} />
</div>

{#snippet productsPane()}
  <Split id="assign-lists" direction="column" sizes={[1, 1]} minPx={140} panes={[queuePart, catalogPart]} />
{/snippet}

{#snippet queuePart()}
  <div class="panel">
    <h3>Products</h3>
    <input bind:value={query} oninput={typed} placeholder="Search code, full name, or brand name"
      onkeydown={(event) => event.key === "Enter" && ((query = normalizeSku(query)), search())} />
    <div class="row nowrap">
      <span class="grow" class:error={searchHasPlace} class:muted={!searchHasPlace}>{searchStatus}</span>
      <button disabled={!exact?.location} onclick={quickMove}>Quick move to location</button>
    </div>
    <div class="fill">
      <VirtualTable columns={queueColumns} rows={queue?.rows ?? []} rowKey={(row) => row.product_id} multi bind:selected={queueSelected}
        rowClass={(row) => (ready(row) ? "" : "muted")} onactivate={(row) => ((query = row.product_id), search())} />
    </div>
    <span class="muted small">{queue ? `${queue.total.toLocaleString()} matching · ${queue.ready?.toLocaleString()} ready · showing ${queue.rows.length}` : ""}</span>
    <button class:whole onclick={assignQueue}>{queueLabel}</button>
  </div>
{/snippet}

{#snippet catalogPart()}
  <div class="panel">
    <h3>Full catalog</h3>
    <div class="fill">
      <VirtualTable columns={catalogColumns} rows={catalog?.rows ?? []} rowKey={(row) => row.product_id} multi bind:selected={catalogSelected}
        onactivate={(row) => ((query = row.product_id), search())} />
    </div>
    <span class="muted small">{catalog ? `${catalog.total.toLocaleString()} matching / ${catalog.size.toLocaleString()} total · showing ${catalog.rows.length}` : ""}</span>
    <div class="row nowrap">
      <button class="grow" class:whole onclick={assignCatalog}>{whole ? "Shift: one catalog product → loaded address" : "Assign selected catalog → loaded address"}</button>
      <button disabled={!canRevert} onclick={revert}>Revert Shift transfer</button>
    </div>
  </div>
{/snippet}

{#snippet handPane()}
  <div class="panel">
    <div class="segmented">
      <button class:active={handView === "queue"} onclick={() => (handView = "queue")}>On-hand queue</button>
      <button class:active={handView === "shelf"} onclick={() => ((handView = "shelf"), refreshPreview())}>Shelf selection</button>
    </div>
    {#if handView === "queue"}
      <div class="fill">
        <VirtualTable columns={handColumns} rows={onHand} rowKey={(row) => row.product_id} multi bind:selected={handSelected} empty="The on-hand queue is empty." />
      </div>
      <div class="row nowrap">
        <span class="muted small grow">{onHand.length.toLocaleString()} product(s) ready to assign</span>
        <button onclick={editOnHand}>Edit selected quantity</button>
      </div>
    {:else}
      <span class="muted small">{preview ? `Floor ${preview.floor} · Side ${preview.side} · Shelf ${preview.code}` : previewMessage}</span>
      <div class="fill">
        <ShelfGrid grid={preview} compact message={previewMessage} selected={address?.slot_name ?? null} onselect={(cell) => pickCell(cell.row, cell.cell)} />
      </div>
    {/if}
    <h3>Shelf address</h3>
    <form class="address" onsubmit={(event) => (event.preventDefault(), loadAddress())}>
      <label class="field">Floor<input bind:value={floor} oninput={addressChanged} /></label>
      <label class="field">Side<input bind:value={side} oninput={addressChanged} /></label>
      <label class="field">Shelf<input bind:value={code} oninput={addressChanged} /></label>
      <label class="field">Row<input bind:value={rowText} /></label>
      <label class="field">Cell<input bind:value={cellText} /></label>
      <button type="submit">Load address →</button>
    </form>
    <span class="muted small">{addressMessage}</span>
    <button class="primary" class:whole onclick={assignOnHand}>{whole ? "Shift: all on-hand → loaded address" : "Assign selected on-hand → loaded address"}</button>
  </div>
{/snippet}

{#snippet cellPane()}
  <div class="panel">
    <h3>{address?.slot_name ?? "No address loaded"}</h3>
    <div class="fill">
      <VirtualTable columns={contentColumns} rows={contents} rowKey={(row) => row.product_id} multi bind:selected={contentSelected}
        empty="Load an address to see its products." onactivate={(row) => navigator.clipboard.writeText(row.product_id).then(() => setStatus(`Copied ${row.product_id}`))} />
    </div>
    <div class="row">
      <button onclick={editStock}>Modify selected stock</button>
      <button onclick={() => toOnHand(false)}>Selected → on-hand</button>
      <button class="danger" onclick={() => toOnHand(true)}>Shelf → on-hand (all)</button>
    </div>
    <label class="row small"><input type="checkbox" bind:checked={wholeCell} /> Process and save all products in the loaded address</label>
    <button disabled={app.webBusy} onclick={modifyWebLocation}>{wholeCell ? "Modify all web locations in this address" : "Modify selected web location"}</button>
  </div>
{/snippet}

<style>
  .address { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)) auto; gap: 6px; align-items: end; }
  .address input { width: 100%; }
</style>
