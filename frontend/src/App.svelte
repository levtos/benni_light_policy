<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "./lib/light-policy/bridge.svelte";
  import DiagnosticsView from "./views/DiagnosticsView.svelte";
  import BrightnessView from "./views/BrightnessView.svelte";
  import FixedModesView from "./views/FixedModesView.svelte";
  import OverviewView from "./views/OverviewView.svelte";
  import PhaseMatrixView from "./views/PhaseMatrixView.svelte";
  import RulesView from "./views/RulesView.svelte";
  import ModuleShell from "./lib/light-policy/ModuleShell.svelte";
  import { LightPolicyStore } from "./lib/light-policy/store.svelte";

  const store = new LightPolicyStore();

  onMount(() => {
    store.start();
    return () => store.stop();
  });

  $effect(() => {
    store.setHass(bridge.hass);
  });
</script>

<ModuleShell {store}>
  {#if store.activeView === "overview"}
    <OverviewView {store} />
  {:else if store.activeView === "matrix"}
    <PhaseMatrixView {store} />
  {:else if store.activeView === "fixed-modes"}
    <FixedModesView {store} />
  {:else if store.activeView === "rules"}
    <RulesView {store} />
  {:else if store.activeView === "brightness"}
    <BrightnessView {store} />
  {:else}
    <DiagnosticsView {store} />
  {/if}
</ModuleShell>
