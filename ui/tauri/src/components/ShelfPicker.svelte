<script lang="ts">
  import { call } from "../lib/rpc";
  import { app } from "../lib/app.svelte";
  import { notify } from "../lib/dialogs.svelte";
  import type { Shelf } from "../lib/types";

  /** Saved-shelf dropdown plus Floor/Side/Shelf lookup, shared by tabs 3, 4 and 5. */
  interface Props {
    shelfId: number | null;
    onload: (shelfId: number) => void;
  }
  let { shelfId, onload }: Props = $props();

  let shelves = $state<Shelf[]>([]);
  let floor = $state("");
  let side = $state("");
  let code = $state("");
  let seen = -1;

  $effect(() => {
    if (app.changes.seq !== seen) {
      seen = app.changes.seq;
      call<Shelf[]>("shelves.list").then((list) => (shelves = list));
    }
  });

  $effect(() => {
    const current = shelves.find((shelf) => shelf.shelf_id === shelfId);
    if (current) [floor, side, code] = [current.floor, current.side, current.code];
  });

  async function find(event?: Event) {
    event?.preventDefault();
    if (!floor.trim() || !side.trim() || !code.trim()) {
      await notify("Enter floor, side, and shelf name to find a shelf.");
      return;
    }
    const id = await call<number | null>("shelves.find", { floor, side, code });
    if (id === null) await notify(`No saved shelf matches floor ${floor}, side ${side}, shelf ${code}.`);
    else onload(id);
  }
</script>

<div class="row">
  <select
    class="grow"
    value={shelfId ?? ""}
    onchange={(event) => event.currentTarget.value && onload(Number(event.currentTarget.value))}
  >
    <option value="" disabled>Choose a saved shelf…</option>
    {#each shelves as shelf (shelf.shelf_id)}
      <option value={shelf.shelf_id}>{shelf.label}</option>
    {/each}
  </select>
  <form class="row nowrap" onsubmit={find}>
    <input size="3" placeholder="Floor" bind:value={floor} />
    <input size="3" placeholder="Side" bind:value={side} />
    <input size="5" placeholder="Shelf" bind:value={code} />
    <button type="submit">Find shelf</button>
  </form>
</div>
