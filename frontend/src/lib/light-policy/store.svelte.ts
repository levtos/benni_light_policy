import { LightPolicyClient } from "./client";
import {
  asRecord,
  coverageFor,
  indexLooks,
  normaliseCatalog,
  normaliseLooks,
  normaliseStatus,
  toStateError,
} from "./contract";
import type {
  Coverage,
  HassLike,
  LightPolicyCatalog,
  LightPolicyStatus,
  LightPolicyView,
  Look,
  MutationSnapshot,
  UiState,
} from "./types";

const POLL_INTERVAL_MS = 30_000;

function isAuthorisationError(message: string): boolean {
  return /admin|authori[sz]|permission|forbidden|not allowed|unauthor/i.test(message);
}

export class LightPolicyStore {
  hass = $state<HassLike | null>(null);
  activeView = $state<LightPolicyView>("overview");
  status = $state<LightPolicyStatus | null>(null);
  catalog = $state<LightPolicyCatalog | null>(null);
  looks = $state<Look[]>([]);
  dataState = $state<UiState>("loading");
  looksState = $state<UiState>("unavailable");
  connectionState = $state<"connected" | "reconnecting" | "offline">("offline");
  lastSync = $state<number | null>(null);
  error = $state<string | null>(null);
  mutation = $state<MutationSnapshot>({ state: "idle", action: null, message: null });
  indexedLooks = $derived(indexLooks(this.looks));

  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private refreshPromise: Promise<void> | null = null;

  setHass(hass: HassLike | null): void {
    const connectionChanged = this.hass?.connection !== hass?.connection;
    this.hass = hass;
    if (!hass?.connection) {
      this.connectionState = "offline";
      if (!this.status || !this.catalog) this.dataState = "offline";
      return;
    }
    this.connectionState = "connected";
    if (connectionChanged || !this.status || !this.catalog) void this.refresh();
  }

  start(): void {
    if (this.pollTimer !== null) return;
    this.pollTimer = setInterval(() => void this.refresh(), POLL_INTERVAL_MS);
  }

  stop(): void {
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  get overallState(): UiState {
    if (this.connectionState === "offline") return this.status && this.catalog ? "offline" : "offline";
    if (!this.status || !this.catalog) return this.dataState;
    if (this.looksState === "unavailable") return "degraded";
    if (this.looksState === "stale") return "stale";
    if (this.looksState === "empty") return "empty";
    return this.dataState === "loading" ? "ready" : this.dataState;
  }

  get lookMap(): Record<string, string> {
    return this.catalog?.look_map ?? {};
  }

  coverage(keys: string[]): Coverage[] {
    const allKeys = this.catalog
      ? [...this.catalog.fixed_modes, ...this.catalog.matrix_keys, ...this.catalog.legacy_matrix_keys]
      : keys;
    return keys.map((key) => coverageFor(key, this.lookMap, this.indexedLooks, this.looksState, allKeys));
  }

  async refresh(): Promise<void> {
    if (this.refreshPromise) return this.refreshPromise;
    const connection = this.hass?.connection;
    if (!connection) {
      this.connectionState = "offline";
      if (!this.status || !this.catalog) this.dataState = "offline";
      return;
    }
    this.connectionState = "connected";
    if (!this.status || !this.catalog) this.dataState = "loading";
    this.error = null;
    const client = new LightPolicyClient(connection);
    this.refreshPromise = Promise.allSettled([client.getStatus(), client.getCatalog(), client.listLooks()])
      .then(([statusResult, catalogResult, looksResult]) => {
        const failures: string[] = [];
        if (statusResult.status === "fulfilled") {
          this.status = normaliseStatus(statusResult.value);
        } else {
          failures.push(`Status: ${toStateError(statusResult.reason)}`);
        }
        if (catalogResult.status === "fulfilled") {
          this.catalog = normaliseCatalog(catalogResult.value);
        } else {
          failures.push(`Look-Mapping: ${toStateError(catalogResult.reason)}`);
        }
        if (looksResult.status === "fulfilled") {
          this.looks = normaliseLooks(looksResult.value);
          this.looksState = this.looks.length ? "ready" : "empty";
        } else {
          this.looksState = this.looks.length ? "stale" : "unavailable";
          failures.push(`Scene Presets: ${toStateError(looksResult.reason)}`);
        }
        this.lastSync = Date.now();
        this.error = failures.length ? failures.join(" · ") : null;
        if (this.status && this.catalog) {
          this.dataState = failures.length > 1 ? "degraded" : "ready";
        } else {
          this.dataState = this.status || this.catalog ? "degraded" : "error";
        }
      })
      .catch((reason) => {
        this.dataState = this.status && this.catalog ? "degraded" : "error";
        this.error = toStateError(reason);
      })
      .finally(() => {
        this.refreshPromise = null;
      });
    return this.refreshPromise;
  }

  async setLookMap(lookMap: Record<string, string>): Promise<void> {
    await this.mutate("Look-Zuordnung speichern", async (client) => {
      await client.setLookMap(lookMap);
    });
  }

  async setSubentryMappings(subentryId: string, mappings: Record<string, string>): Promise<void> {
    await this.mutate("Gaming-Zuordnung speichern", async (client) => {
      await client.setSubentryMappings(subentryId, mappings);
    });
  }

  async setApplyEnabled(enabled: boolean): Promise<void> {
    await this.mutate(enabled ? "Apply aktivieren" : "Apply in Shadow setzen", async (client) => {
      await client.setApplyEnabled(enabled);
    });
  }

  async setBrightnessProfile(profile: Record<string, number>): Promise<void> {
    await this.mutate("Helligkeitsprofil speichern", async (client) => {
      await client.setBrightnessProfile(profile);
    });
  }

  async setCustomThemes(themes: string[]): Promise<void> {
    await this.mutate("Benutzerdefinierte Themen speichern", async (client) => {
      await client.setCustomThemes(themes);
    });
  }

  clearMutation(): void {
    this.mutation = { state: "idle", action: null, message: null };
  }

  private async mutate(action: string, operation: (client: LightPolicyClient) => Promise<void>): Promise<void> {
    const connection = this.hass?.connection;
    if (!connection) {
      this.mutation = { state: "blocked", action, message: "Keine Home-Assistant-Verbindung." };
      return;
    }
    if (this.mutation.state === "pending") return;
    this.mutation = { state: "pending", action, message: "Warte auf Home Assistant …" };
    try {
      await operation(new LightPolicyClient(connection));
      this.mutation = { state: "success", action, message: "Gespeichert; Daten werden resynchronisiert." };
      await this.refresh();
    } catch (reason) {
      const message = toStateError(reason);
      this.mutation = {
        state: isAuthorisationError(message) ? "blocked" : "error",
        action,
        message,
      };
    }
  }
}

export function cloneStringMap(value: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(asRecord(value)).flatMap(([key, raw]) => {
      const text = typeof raw === "string" ? raw.trim() : "";
      return text ? [[key, text]] : [];
    }),
  );
}
