<script lang="ts">
  import type { GridCell, GridModel } from "../lib/types";

  /** A shelf front view: rows top-down, each row's cells sharing its full width. */
  interface Props {
    grid: GridModel | null;
    selected?: string | null;
    compact?: boolean;
    message?: string;
    label?: (cell: GridCell) => string;
    onselect?: (cell: GridCell) => void;
  }

  let { grid, selected = null, compact = false, message = "Choose a shelf.", label, onselect }: Props = $props();

  const widest = $derived(grid ? Math.max(1, ...grid.rows.map((row) => row.length)) : 1);
  const cellWidth = $derived(compact ? 44 : 64);
  const defaultLabel = (cell: GridCell) => (compact ? `${cell.row}-${String(cell.cell).padStart(2, "0")}` : `${grid?.code ?? ""}${cell.row}-${cell.cell}`);
  const countText = (count: number) => (compact ? String(count) : `${count} product${count === 1 ? "" : "s"}`);
  let element = $state<HTMLDivElement>();

  // Centre the selected cell inside this grid's own scroll area after each redraw.
  $effect(() => {
    void grid;
    const box = element;
    if (!selected || !box) return;
    const slot = selected;
    requestAnimationFrame(() => {
      const cell = box.querySelector<HTMLElement>(`[data-slot="${CSS.escape(slot)}"]`);
      if (!cell) return;
      const view = box.getBoundingClientRect();
      const target = cell.getBoundingClientRect();
      box.scrollTop += target.top + target.height / 2 - (view.top + view.height / 2);
      box.scrollLeft += target.left + target.width / 2 - (view.left + view.width / 2);
    });
  });
</script>

<div class="shelf" bind:this={element}>
  {#if !grid}
    <p class="muted">{message}</p>
  {:else}
    {#if !compact}
      <div class="title">FLOOR {grid.floor} · SIDE {grid.side} · SHELF {grid.code}</div>
    {/if}
    <div class="rows" style:min-width="{widest * cellWidth + (compact ? 40 : 70)}px">
      {#each grid.rows as row, index (index)}
        <div class="line">
          <div class="row-label">R{row[0]?.row ?? ""}{row[0]?.row === 1 && !compact ? " · ground" : ""}</div>
          <div class="cells">
            {#each row as cell (cell.slot_name)}
              <button
                class="cell"
                class:filled={cell.count > 0}
                class:selected={cell.slot_name === selected}
                class:compact
                data-slot={cell.slot_name}
                title={cell.slot_name}
                onclick={() => onselect?.(cell)}
              >
                <span>{(label ?? defaultLabel)(cell)}</span>
                <span class="count">{countText(cell.count)}</span>
              </button>
            {/each}
          </div>
        </div>
      {/each}
      <div class="ground"></div>
    </div>
  {/if}
</div>

<style>
  .shelf { overflow: auto; height: 100%; min-height: 0; padding: 4px; }
  .title { font-weight: 600; color: var(--accent); text-align: center; margin: 2px 0 8px; }
  .rows { display: flex; flex-direction: column; gap: 4px; }
  .line { display: flex; align-items: stretch; gap: 6px; }
  .row-label { width: 64px; flex: none; text-align: right; align-self: center; color: var(--muted); font-size: 12px; }
  .cells { flex: 1; display: flex; gap: 2px; }
  .cell {
    flex: 1 1 0; min-width: 0; height: 54px; padding: 2px; border-radius: 3px; display: flex; flex-direction: column;
    align-items: center; justify-content: center; background: var(--cell-empty); border: 1px solid var(--cell-border); font-size: 12px; line-height: 1.25;
  }
  .cell.compact { height: 40px; font-size: 11px; font-weight: 600; }
  .cell.filled { background: var(--cell-filled); }
  .cell.selected { background: var(--cell-selected); border: 2px solid var(--accent); font-weight: 700; }
  .cell:hover { filter: brightness(0.96); }
  .count { color: var(--muted); font-size: 11px; }
  .ground { height: 1px; background: var(--line-strong); margin: 6px 0 0 70px; }
</style>
