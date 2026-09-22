<script lang="ts">
  import {
    Activity,
    Gauge,
    Gamepad2,
    Lightbulb,
    ListChecks,
    RefreshCw,
    SlidersHorizontal,
    Table2,
  } from "@lucide/svelte";
  import type { Component, Snippet } from "svelte";
  import StateBanner from "../ui/StateBanner.svelte";
  import StatusBadge from "../ui/StatusBadge.svelte";
  import { stateLabel } from "./contract";
  import type { LightPolicyView } from "./types";
  import { LightPolicyStore } from "./store.svelte";

  const NAV: Array<{ id: LightPolicyView; label: string; description: string; icon: Component }> = [
    { id: "overview", label: "Übersicht", description: "Aktueller Soll-Zustand und sichere Freigabe", icon: Gauge },
    { id: "matrix", label: "Look-Zuordnung", description: "Neun kanonische Tagesphasen", icon: Table2 },
    { id: "fixed-modes", label: "Feste Modi", description: "Idle, Cinema und bestehende Modi", icon: ListChecks },
    { id: "rules", label: "Regeln", description: "Gaming-Quellen und ihre Look-Zuordnungen", icon: Gamepad2 },
    { id: "brightness", label: "Helligkeit", description: "Profile, Provenienz und Overrides", icon: SlidersHorizontal },
    { id: "diagnostics", label: "Diagnose", description: "Vertrag, Quellen und Degradationen", icon: Activity },
  ];

  const pageCopy: Record<LightPolicyView, { title: string; description: string }> = {
    overview: { title: "Übersicht", description: "Der Light-Policy-Sollzustand aus dem bestehenden Home-Assistant-Vertrag." },
    matrix: { title: "Look-Zuordnung", description: "Neun unabhängige Look-Referenzen je Thema oder Ereignis; Legacy-Werte bleiben sichtbar markiert." },
    "fixed-modes": { title: "Feste Modi", description: "Die bestehenden festen Policy-Modi bleiben vollständig editierbar, einschließlich Idle / Hard-Off." },
    rules: { title: "Regeln", description: "Classifier-gesteuerte Gaming-Quellen ordnen erkannte Werte vorhandenen Looks zu." },
    brightness: { title: "Helligkeit", description: "Effektive Prozentwerte mit Herkunft; Rohwerte bleiben der Diagnose vorbehalten." },
    diagnostics: { title: "Diagnose", description: "Read-only Einsicht in Zustände, Quellen und bekannte Contract-Grenzen." },
  };

  let { store, children }: { store: LightPolicyStore; children?: Snippet } = $props();
  const copy = $derived(pageCopy[store.activeView]);

  const formatSync = (value: number | null) =>
    value
      ? new Intl.DateTimeFormat("de-DE", { timeStyle: "medium", timeZone: "Europe/Berlin" }).format(new Date(value))
      : "noch nicht synchronisiert";
</script>

<div class="lp-module">
  <div class="lp-shell">
    <aside class="lp-sidebar" aria-label="Light-Policy-Modulnavigation">
      <div class="lp-brand">
        <div class="lp-brand-mark"><Lightbulb size={19} strokeWidth={2} /></div>
        <div>
          <strong>Light Policy</strong>
          <small>Umbrella-UX Slice</small>
        </div>
      </div>

      <nav class="lp-nav">
        {#each NAV as item (item.id)}
          {@const Icon = item.icon}
          <button
            type="button"
            class:active={store.activeView === item.id}
            aria-current={store.activeView === item.id ? "page" : undefined}
            title={item.description}
            onclick={() => (store.activeView = item.id)}
          >
            <Icon size={17} strokeWidth={2} />
            <span>{item.label}</span>
          </button>
        {/each}
      </nav>

      <div class="lp-sidebar-foot">benni_light_policy · {store.connectionState}</div>
    </aside>

    <main class="lp-main">
      <header class="lp-page-head">
        <div>
          <h1>{copy.title}</h1>
          <p>{copy.description}</p>
        </div>
        <div class="lp-page-actions">
          <StatusBadge state={store.overallState} />
          <StatusBadge state={store.status?.apply_enabled ? "success" : "info"} label={store.status?.apply_enabled ? "Apply aktiv" : "Apply Shadow"} />
          <button class="lp-button" type="button" onclick={() => store.refresh()} disabled={store.dataState === "loading"}>
            <span class:lp-spin={store.dataState === "loading"}><RefreshCw size={17} strokeWidth={2} /></span>
            Aktualisieren
          </button>
        </div>
      </header>

      {#if store.overallState !== "ready"}
        <StateBanner
          state={store.overallState}
          title={stateLabel(store.overallState)}
          message={store.error ?? (store.overallState === "empty" ? "Der Look-Katalog ist leer; vorhandene Referenzen werden nicht erfunden." : "Die Ansicht zeigt vorhandene Daten weiter, bis Home Assistant wieder synchronisiert ist.")}
        />
      {/if}

      {#if store.mutation.state !== "idle"}
        <StateBanner
          state={store.mutation.state === "pending" ? "loading" : store.mutation.state === "success" ? "ready" : store.mutation.state}
          title={store.mutation.action ?? "Änderung"}
          message={store.mutation.message ?? ""}
        />
      {/if}

      <div class="lp-meta" style="margin-bottom: 14px">Letzte Synchronisation: {formatSync(store.lastSync)} · Host stellt Verbindung und Berechtigung bereit.</div>
      {@render children?.()}
    </main>
  </div>
</div>
