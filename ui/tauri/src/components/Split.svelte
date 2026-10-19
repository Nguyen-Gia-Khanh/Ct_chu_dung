<script lang="ts">
  import type { Snippet } from "svelte";

  /**
   * Panes separated by draggable dividers, like Tk's Panedwindow. Sizes are
   * fractions remembered per `id` on this computer.
   */
  interface Props {
    id: string;
    panes: Snippet[];
    sizes: number[];
    direction?: "row" | "column";
    minPx?: number;
  }
  let { id, panes, sizes, direction = "row", minPx = 160 }: Props = $props();

  const storageKey = () => `split:${id}`;
  let container = $state<HTMLDivElement>();
  let current = $state<number[]>(restore());

  function restore(): number[] {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey()) ?? "null");
      if (Array.isArray(saved) && saved.length === sizes.length && saved.every((value) => value > 0)) return saved;
    } catch {
      // Saved sizes are only a convenience.
    }
    return defaults();
  }

  function defaults(): number[] {
    const total = sizes.reduce((a, b) => a + b, 0);
    return sizes.map((size) => size / total);
  }

  function drag(event: PointerEvent, index: number) {
    if (!container) return;
    event.preventDefault();
    const gutter = event.currentTarget as HTMLElement;
    gutter.setPointerCapture(event.pointerId);
    const box = container.getBoundingClientRect();
    const length = direction === "row" ? box.width : box.height;
    const start = direction === "row" ? event.clientX : event.clientY;
    const [first, second] = [current[index], current[index + 1]];
    const minimum = Math.min(minPx / length, (first + second) / 2);

    const move = (moveEvent: PointerEvent) => {
      const position = direction === "row" ? moveEvent.clientX : moveEvent.clientY;
      const delta = Math.max(minimum - first, Math.min(second - minimum, (position - start) / length));
      current[index] = first + delta;
      current[index + 1] = second - delta;
    };
    const stop = () => {
      gutter.removeEventListener("pointermove", move);
      gutter.removeEventListener("pointerup", stop);
      try {
        localStorage.setItem(storageKey(), JSON.stringify(current));
      } catch {
        // Not saved; the layout still works.
      }
    };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", stop);
  }

  function reset(index: number) {
    const initial = defaults();
    const pair = current[index] + current[index + 1];
    const share = initial[index] / (initial[index] + initial[index + 1]);
    current[index] = pair * share;
    current[index + 1] = pair - current[index];
  }
</script>

<div class="split" class:across={direction === "row"} class:down={direction === "column"} bind:this={container}>
  {#each panes as pane, index (index)}
    <div class="pane" style:flex="{current[index]} 1 0px">{@render pane()}</div>
    {#if index < panes.length - 1}
      <div
        class="gutter"
        role="separator"
        aria-orientation={direction === "row" ? "vertical" : "horizontal"}
        title="Drag to resize · double-click to reset"
        onpointerdown={(event) => drag(event, index)}
        ondblclick={() => reset(index)}
      ></div>
    {/if}
  {/each}
</div>

<style>
  .split { display: flex; height: 100%; width: 100%; min-height: 0; min-width: 0; }
  .split.down { flex-direction: column; }
  .pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; }
  .pane > :global(.panel) { flex: 1 1 auto; }
  .gutter { flex: none; background: transparent; position: relative; z-index: 1; }
  .across > .gutter { width: 10px; cursor: col-resize; }
  .down > .gutter { height: 10px; cursor: row-resize; }
  .gutter::after { content: ""; position: absolute; border-radius: 2px; background: var(--line-strong); opacity: 0; }
  .across > .gutter::after { top: 40%; bottom: 40%; left: 4px; width: 2px; }
  .down > .gutter::after { left: 40%; right: 40%; top: 4px; height: 2px; }
  .gutter:hover::after { opacity: 1; }
</style>
