<script lang="ts">
  import ShelfGrid from "./ShelfGrid.svelte";
  import ShelfPicker from "./ShelfPicker.svelte";
  import VirtualTable from "./VirtualTable.svelte";
  import { app, errorText, setStatus } from "../lib/app.svelte";
  import { contentColumns } from "../lib/columns";
  import { notify } from "../lib/dialogs.svelte";
  import { call } from "../lib/rpc";
  import { normalizeSku } from "../lib/scanner";
  import type { GridCell, ShelfView, SlotAddress } from "../lib/types";

  /** One side of Tab 5: find a shelf cell by product ID, location ID, or shelf name. */
  interface Props {
    title: string;
    address: SlotAddress | null;
    onfocus?: () => void;
  }
  let { title, address = $bindable(), onfocus }: Props = $props();

  let shelf = $state<ShelfView | null>(null);
  let query = $state("");
  let seen = -1;

  const rows = $derived(shelf && address ? shelf.contents.filter((row) => row.slot === address!.slot_name) : []);

  $effect(() => {
    if (app.tab === "transfer" && app.changes.seq !== seen) {
      seen = app.changes.seq;
      if (shelf) load(shelf.shelf_id, address?.slot_id ?? null);
    }
  });

  export async function load(shelfId: number, slotId: number | null = null) {
    try {
      shelf = await call<ShelfView>("shelves.grid", { shelf_id: shelfId });
      address = slotId === null ? null : await call<SlotAddress | null>("cells.get", { slot_id: slotId });
      if (address && address.shelf_id !== shelfId) address = null;
    } catch (problem) {
      setStatus(errorText(problem));
      [shelf, address] = [null, null];
    }
  }

  async function select(cell: GridCell) {
    if (!shelf) return;
    address = await call<SlotAddress | null>("cells.address", { floor: shelf.floor, side: shelf.side, code: shelf.code, row: cell.row, cell: cell.cell });
  }

  export async function find(text = query) {
    if (!text.trim()) return;
    query = normalizeSku(text);
    const found = await call<{ address: SlotAddress | null; shelves: { shelf_id: number; label: string }[] }>("cells.find", { query: text });
    if (found.address) await load(found.address.shelf_id, found.address.slot_id);
    else if (found.shelves.length === 1) await load(found.shelves[0].shelf_id);
    else if (found.shelves.length) await notify("More than one shelf matches. Use the shelf list above to select the exact shelf.");
    else await notify(`Product ID or location '${text.trim()}' was not found on any shelf.`);
  }
</script>

<div class="panel pane" role="group" onfocusin={() => onfocus?.()}>
  <h3>{title}</h3>
  <ShelfPicker shelfId={shelf?.shelf_id ?? null} onload={(id) => load(id)} />
  <form class="row nowrap" onsubmit={(event) => (event.preventDefault(), find())}>
    <input class="grow" bind:value={query} placeholder="Product ID, location ID, or shelf name" />
    <button type="submit">Find</button>
  </form>
  <div class="grid"><ShelfGrid grid={shelf} selected={address?.slot_name ?? null} onselect={select} /></div>
  <strong>{address ? `${address.slot_name} · ${rows.length} product${rows.length === 1 ? "" : "s"}` : "No cell selected"}</strong>
  <div class="contents">
    <VirtualTable columns={contentColumns.slice(0, 3)} {rows} rowKey={(row) => row.product_id} onactivate={(row) => find(row.product_id)} />
  </div>
</div>

<style>
  .pane { min-height: 0; }
  .grid { flex: 3 1 0; min-height: 0; }
  .contents { flex: 2 1 0; min-height: 0; }
</style>
