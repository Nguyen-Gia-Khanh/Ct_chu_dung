<script lang="ts">
  import ShelfGrid from "../components/ShelfGrid.svelte";
  import ShelfPicker from "../components/ShelfPicker.svelte";
  import VirtualTable from "../components/VirtualTable.svelte";
  import { app, errorText, setStatus, stale } from "../lib/app.svelte";
  import { contentColumns } from "../lib/columns";
  import { call } from "../lib/rpc";
  import type { ShelfView } from "../lib/types";

  /** Tab 4: read-only view of saved shelves. Browsing never writes. */
  let shelf = $state<ShelfView | null>(null);
  let shelfId = $state<number | null>(null);
  let slot = $state<string | null>(null);
  let seen = -1;

  const rows = $derived(shelf && slot ? shelf.contents.filter((row) => row.slot === slot) : []);

  $effect(() => {
    if (stale("browse", seen)) {
      seen = app.changes.seq;
      if (shelfId !== null) load(shelfId);
    }
  });

  async function load(id: number) {
    try {
      shelf = await call<ShelfView>("shelves.grid", { shelf_id: id });
      if (id !== shelfId) slot = null;
      shelfId = id;
    } catch (problem) {
      setStatus(errorText(problem));
      shelf = null;
      shelfId = null;
    }
  }

  async function copy(productId: string) {
    await navigator.clipboard.writeText(productId);
    setStatus(`Copied ${productId}`);
  }
</script>

<div class="tab-body" style:grid-template-rows="auto 1fr">
  <div class="panel">
    <ShelfPicker {shelfId} onload={load} />
    {#if shelf}
      <span class="muted small">Committed SQLite data · {shelf.layout.length} rows · {shelf.layout.reduce((a, b) => a + b, 0)} cells</span>
    {/if}
  </div>
  <div class="split">
    <div class="panel">
      <h3>Saved shelf — click a cell</h3>
      <div class="fill"><ShelfGrid grid={shelf} selected={slot} onselect={(cell) => (slot = cell.slot_name)} /></div>
    </div>
    <div class="panel">
      <h3>{slot ?? "No cell selected"}</h3>
      <div class="fill">
        <VirtualTable columns={contentColumns} {rows} rowKey={(row) => row.product_id} empty="Click a cell to see its products." onactivate={(row) => copy(row.product_id)} />
      </div>
      <span class="muted small">Double-click a product to copy its ID.</span>
    </div>
  </div>
</div>

<style>
  .split { display: grid; grid-template-columns: 3fr 2fr; gap: 10px; min-height: 0; }
</style>
