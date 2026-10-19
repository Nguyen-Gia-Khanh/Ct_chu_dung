<script lang="ts">
  import ShelfGrid from "../components/ShelfGrid.svelte";
  import ShelfPicker from "../components/ShelfPicker.svelte";
  import VirtualTable from "../components/VirtualTable.svelte";
  import { app, errorText, setStatus, stale } from "../lib/app.svelte";
  import { contentColumns, idColumn, productColumns } from "../lib/columns";
  import { call } from "../lib/rpc";
  import { normalizeSku } from "../lib/scanner";
  import type { Column, ProductRow, SearchResult, ShelfView, SlotAddress } from "../lib/types";

  /** Tab 3: is a product a hot seller, and where is it? Read-only. */
  let query = $state("");
  let primal = $state<SearchResult | null>(null);
  let catalog = $state<SearchResult | null>(null);
  let status = $state("Type or scan a product ID to check if it is a hot seller.");
  let shelf = $state<ShelfView | null>(null);
  let shelfId = $state<number | null>(null);
  let slot = $state<string | null>(null);
  let input = $state<HTMLInputElement>();
  let seen = -1;
  let scanSeen = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const primalColumns: Column<ProductRow>[] = [
    idColumn<ProductRow>(), productColumns.name,
    { key: "where", label: "Location", width: "minmax(100px, 0.6fr)", value: (row) => row.location || (row.on_hand ? "On-hand" : "Unassigned") },
    productColumns.stock,
  ];
  const catalogColumns: Column<ProductRow>[] = [idColumn<ProductRow>(), productColumns.name, productColumns.brand];
  const cellRows = $derived(shelf && slot ? shelf.contents.filter((row) => row.slot === slot) : []);

  $effect(() => {
    if (stale("primal", seen)) {
      seen = app.changes.seq;
      search(false);
      if (shelfId !== null) loadShelf(shelfId, slot);
    }
  });

  $effect(() => {
    if (app.tab === "primal" && app.scan.seq !== scanSeen) {
      scanSeen = app.scan.seq;
      query = app.scan.code;
      search(true);
    }
  });

  function typed() {
    clearTimeout(timer);
    timer = setTimeout(() => search(true), 150);
  }

  async function search(navigate: boolean) {
    try {
      [primal, catalog] = await Promise.all([
        call<SearchResult>("products.search", { query, scope: "hot", order: "primal" }),
        call<SearchResult>("products.search", { query, scope: "catalog" }),
      ]);
      await describe(navigate);
    } catch (problem) {
      setStatus(errorText(problem));
    }
  }

  async function describe(navigate: boolean) {
    if (!query.trim()) {
      status = "Type or scan a product ID to check if it is a hot seller.";
      return;
    }
    const product = await call<ProductRow | null>("products.lookup", { query });
    if (!product) {
      status = `No exact match for '${query.trim()}'.`;
      return;
    }
    const where = product.location ? ` · Located at ${product.location}` : "";
    if (product.hot) {
      const stock = product.stock !== null ? ` · Stock: ${product.stock}` : "";
      status = `✓ HOT SELLER (in Primal Queue): ${product.product_id} — ${product.name}` +
        (product.location ? `${where}${stock}` : product.on_hand ? ` · Currently On-hand${stock}` : " · Currently Unassigned in queue");
    } else {
      status = `✗ NOT a hot seller (Full Catalog only): ${product.product_id} — ${product.name}${where}`;
    }
    if (navigate && product.location) await showProduct(product.product_id);
  }

  async function showProduct(productId: string) {
    const addresses = await call<SlotAddress[]>("products.locations", { product_id: productId });
    if (addresses.length) await loadShelf(addresses[0].shelf_id, addresses[0].slot_name);
  }

  async function loadShelf(id: number, select: string | null = null) {
    shelf = await call<ShelfView>("shelves.grid", { shelf_id: id });
    shelfId = id;
    slot = select;
  }

  function fill(productId: string) {
    query = productId;
    search(true);
    input?.select();
  }
</script>

<div class="tab-body" style:grid-template-columns="minmax(420px, 5fr) 6fr">
  <div class="panel">
    <h3>Search hot sellers and catalog</h3>
    <input
      bind:this={input}
      bind:value={query}
      oninput={typed}
      onkeydown={(event) => event.key === "Enter" && ((query = normalizeSku(query)), search(true))}
      placeholder="Product ID, full name, or brand name"
    />
    <span class="status" class:ok={status.startsWith("✓")} class:error={status.startsWith("✗")}>{status}</span>
    <h3>Primal queue (hot sellers)</h3>
    <div class="fill">
      <VirtualTable columns={primalColumns} rows={primal?.rows ?? []} rowKey={(row) => row.product_id}
        rowClass={(row) => (row.location ? "" : "muted")}
        onselect={([id]) => id && showProduct(id)} onactivate={(row) => fill(row.product_id)} />
    </div>
    <span class="muted small">{primal ? `${primal.total.toLocaleString()} matching hot seller(s) · showing ${primal.rows.length}` : ""}</span>
    <h3>Full catalog</h3>
    <div class="fill">
      <VirtualTable columns={catalogColumns} rows={catalog?.rows ?? []} rowKey={(row) => row.product_id}
        onselect={([id]) => id && showProduct(id)} onactivate={(row) => fill(row.product_id)} />
    </div>
    <span class="muted small">{catalog ? `${catalog.total.toLocaleString()} matching catalog product(s) · showing ${catalog.rows.length}` : ""}</span>
  </div>
  <div class="panel">
    <ShelfPicker {shelfId} onload={(id) => loadShelf(id)} />
    <div class="grid-area"><ShelfGrid grid={shelf} selected={slot} message="Choose a shelf above or search a product on the left." onselect={(cell) => (slot = cell.slot_name)} /></div>
    <h3>{slot ? `${slot} — ${cellRows.length} product${cellRows.length === 1 ? "" : "s"}` : "No cell selected"}</h3>
    <div class="contents"><VirtualTable columns={contentColumns.slice(0, 3)} rows={cellRows} rowKey={(row) => row.product_id} onactivate={(row) => fill(row.product_id)} /></div>
  </div>
</div>

<style>
  .status { min-height: 18px; }
  .grid-area { flex: 3 1 0; min-height: 0; }
  .contents { flex: 2 1 0; min-height: 0; }
</style>
