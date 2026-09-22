import {
  CANONICAL_PHASES,
  EVENT_KEYS,
  FIXED_MODES,
  LEGACY_PHASES,
  SEASON_KEYS,
  type Coverage,
  type HassState,
  type LightPolicyCatalog,
  type LightPolicyStatus,
  type Look,
  type LooksResponse,
  type UiState,
} from "./types";

export {
  CANONICAL_PHASES,
  EVENT_KEYS,
  FIXED_MODES,
  LEGACY_PHASES,
  SEASON_KEYS,
  UX_CONTRACT_VERSION,
} from "./types";

export const PHASE_LABELS: Record<string, string> = {
  early_night: "Früh-Nacht",
  late_night: "Spät-Nacht",
  early_morning: "Früh-Morgen",
  late_morning: "Spät-Morgen",
  forenoon: "Vormittag",
  midday: "Mittag",
  afternoon: "Nachmittag",
  late_afternoon: "Später Nachmittag",
  evening: "Abend",
  early_evening: "Früh-Abend",
  late_evening: "Spät-Abend",
};

export const THEME_LABELS: Record<string, string> = {
  spring: "Frühling",
  summer: "Sommer",
  autumn: "Herbst",
  winter: "Winter",
  christmas: "Weihnachten",
  easter: "Ostern",
  halloween: "Halloween",
  carnival: "Karneval",
  geburtstag: "Geburtstag",
  silvester: "Silvester",
  pride: "Pride",
  advent_1: "1. Advent",
  advent_2: "2. Advent",
  advent_3: "3. Advent",
  advent_4: "4. Advent",
  stpatricks: "St. Patrick's Day",
};

export const MODE_LABELS: Record<string, string> = {
  idle: "Idle / Hard-Off",
  cinema: "Cinema",
  private_time: "Private Time",
  waking: "Wecklicht",
  work_home: "Work-Home",
};

// The existing backend returns the merged profile, not explicit override
// metadata. These values mirror its published DEFAULT_BRIGHTNESS contract so
// the UI can explain effective values without inventing a new command.
export const DEFAULT_BRIGHTNESS: Record<string, number> = {
  early_night: 150,
  late_night: 100,
  early_morning: 255,
  forenoon: 255,
  midday: 255,
  afternoon: 255,
  late_afternoon: 220,
  evening: 220,
  late_evening: 200,
  waking: 255,
  work_home: 220,
  private_time: 80,
};

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const text = String(value).trim();
  return text || null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(asString).filter((item): item is string => Boolean(item))
    : [];
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asNumberMap(value: unknown): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [key, raw] of Object.entries(asRecord(value))) {
    const number = typeof raw === "number" ? raw : Number(raw);
    if (Number.isFinite(number)) result[key] = Math.max(0, Math.min(255, number));
  }
  return result;
}

function normalisePlan(value: unknown): LightPolicyStatus["plan"] {
  const plan = asRecord(value);
  return {
    ...plan,
    mode: asString(plan.mode),
    preset_enum: asString(plan.preset_enum),
    brightness: typeof plan.brightness === "number" ? plan.brightness : null,
    apply_allowed: asBoolean(plan.apply_allowed),
    blockers: asStringArray(plan.blockers),
    targets: asStringArray(plan.targets),
    exclusive_off: asStringArray(plan.exclusive_off),
  };
}

function normaliseGate(value: unknown): LightPolicyStatus["gate"] {
  const gate = asRecord(value);
  return {
    ...gate,
    startup_ready: asBoolean(gate.startup_ready),
    lux_gate_on: asBoolean(gate.lux_gate_on),
    tmc_set: asBoolean(gate.tmc_set),
    weather_dark: asBoolean(gate.weather_dark),
    lux_samples: typeof gate.lux_samples === "number" ? gate.lux_samples : 0,
    thresholds: asRecord(gate.thresholds) as LightPolicyStatus["gate"]["thresholds"],
  };
}

function normaliseFoundation(value: unknown): LightPolicyStatus["foundation"] {
  const foundation = asRecord(value);
  const ok = typeof foundation.ok === "number" ? foundation.ok : 0;
  const total = typeof foundation.total === "number" ? foundation.total : 0;
  return {
    ...foundation,
    ok,
    total,
    missing: asStringArray(foundation.missing),
  };
}

function normaliseRules(value: unknown): LightPolicyStatus["subentry_rules"] {
  return Array.isArray(value) ? value.map((item) => asRecord(item)) : [];
}

export function normaliseStatus(value: unknown): LightPolicyStatus {
  const raw = asRecord(value);
  return {
    ...raw,
    version: typeof raw.version === "number" || typeof raw.version === "string" ? raw.version : null,
    plan: normalisePlan(raw.plan),
    gate: normaliseGate(raw.gate),
    apply_enabled: asBoolean(raw.apply_enabled),
    manual_off: asBoolean(raw.manual_off),
    ring_mode: asString(raw.ring_mode),
    activity: asString(raw.activity),
    day_state: asString(raw.day_state),
    desired_policy_key: asString(raw.desired_policy_key),
    desired_look_ref: asString(raw.desired_look_ref),
    foundation: normaliseFoundation(raw.foundation),
    subentry_rules: normaliseRules(raw.subentry_rules),
    areas: normaliseRules(raw.areas),
    brightness_profile: asNumberMap(raw.brightness_profile),
  };
}

function matrixKeys(themes: string[], phases: string[]): string[] {
  return themes.flatMap((theme) => phases.map((phase) => `${theme}_${phase}`));
}

export function normaliseCatalog(value: unknown): LightPolicyCatalog {
  const raw = asRecord(value);
  const themes = asStringArray(raw.themes);
  const phases = asStringArray(raw.phases).filter((phase): phase is (typeof CANONICAL_PHASES)[number] =>
    (CANONICAL_PHASES as readonly string[]).includes(phase),
  );
  const legacyPhases = asStringArray(raw.legacy_phases).filter((phase): phase is (typeof LEGACY_PHASES)[number] =>
    (LEGACY_PHASES as readonly string[]).includes(phase),
  );
  const effectiveThemes = themes.length ? themes : [...SEASON_KEYS, ...EVENT_KEYS];
  const effectivePhases = phases.length ? phases : [...CANONICAL_PHASES];
  return {
    ...raw,
    look_map: Object.fromEntries(
      Object.entries(asRecord(raw.look_map)).flatMap(([key, ref]) => {
        const text = asString(ref);
        return text ? [[key, text]] : [];
      }),
    ),
    fixed_modes: asStringArray(raw.fixed_modes).length ? asStringArray(raw.fixed_modes) : [...FIXED_MODES],
    themes: effectiveThemes,
    custom_themes: asStringArray(raw.custom_themes),
    phases: effectivePhases,
    legacy_phases: legacyPhases.length ? legacyPhases : [...LEGACY_PHASES],
    matrix_keys: asStringArray(raw.matrix_keys).length
      ? asStringArray(raw.matrix_keys)
      : matrixKeys(effectiveThemes, effectivePhases),
    legacy_matrix_keys: asStringArray(raw.legacy_matrix_keys),
    supported_phases: asStringArray(raw.supported_phases),
    supported_matrix_keys: asStringArray(raw.supported_matrix_keys),
    subentry_rules: normaliseRules(raw.subentry_rules),
  };
}

export function normaliseLooks(value: unknown): Look[] {
  const response = asRecord(value) as LooksResponse;
  const rawLooks = Array.isArray(response.looks)
    ? response.looks
    : Array.isArray(response.items)
      ? response.items
      : [];
  return rawLooks.map((look) => asRecord(look) as Look);
}

export function lookRef(look: Look | null | undefined): string | null {
  if (!look) return null;
  return asString(look.slug) ?? asString(look.name) ?? asString(look.id);
}

export function lookLabel(look: Look | null | undefined): string {
  if (!look) return "Kein Look gefunden";
  return asString(look.name) ?? asString(look.slug) ?? asString(look.id) ?? "Unbenannter Look";
}

export function indexLooks(looks: Look[]): Map<string, Look> {
  const result = new Map<string, Look>();
  for (const look of looks) {
    for (const value of [look.slug, look.name, look.id]) {
      const key = asString(value);
      if (key) result.set(key.toLowerCase(), look);
    }
  }
  return result;
}

export function findLook(ref: string | null | undefined, indexedLooks: Map<string, Look>): Look | null {
  const key = asString(ref);
  return key ? indexedLooks.get(key.toLowerCase()) ?? null : null;
}

export function coverageFor(
  key: string,
  lookMap: Record<string, string>,
  indexedLooks: Map<string, Look>,
  looksState: UiState,
  allKeys: string[],
): Coverage {
  const mappedRef = asString(lookMap[key]);
  const ref = mappedRef ?? key;
  const sharedCount = allKeys.filter((candidate) => asString(lookMap[candidate]) === ref).length;
  const availability = looksState === "ready" ? "available" : looksState === "stale" ? "stale" : "unavailable";
  const notIndividuallyMaintained = !mappedRef;
  if (looksState !== "ready") {
    return {
      key,
      ref,
      assignment: mappedRef ? "mapped" : "fallback",
      availability,
      status: looksState === "stale" ? "stale" : "unavailable",
      look: null,
      isShared: mappedRef ? sharedCount > 1 : false,
      notIndividuallyMaintained,
    };
  }
  const look = findLook(ref, indexedLooks);
  if (mappedRef && !look) {
    return {
      key,
      ref,
      assignment: "mapped",
      availability: "available",
      status: "invalid",
      look: null,
      isShared: sharedCount > 1,
      notIndividuallyMaintained: false,
    };
  }
  return {
    key,
    ref,
    assignment: mappedRef ? "mapped" : "fallback",
    availability: "available",
    status: look ? "ready" : "missing",
    look,
    isShared: mappedRef ? sharedCount > 1 : false,
    notIndividuallyMaintained,
  };
}

export function directLookCoverage(
  key: string,
  ref: string | null | undefined,
  indexedLooks: Map<string, Look>,
  looksState: UiState,
): Coverage {
  const mappedRef = asString(ref);
  const availability = looksState === "ready" ? "available" : looksState === "stale" ? "stale" : "unavailable";
  if (looksState !== "ready") {
    return {
      key,
      ref: mappedRef ?? "",
      assignment: mappedRef ? "mapped" : "unassigned",
      availability,
      status: looksState === "stale" ? "stale" : "unavailable",
      look: null,
      isShared: false,
      notIndividuallyMaintained: !mappedRef,
    };
  }
  if (!mappedRef) {
    return {
      key,
      ref: "",
      assignment: "unassigned",
      availability: "available",
      status: "missing",
      look: null,
      isShared: false,
      notIndividuallyMaintained: true,
    };
  }
  const look = findLook(mappedRef, indexedLooks);
  return {
    key,
    ref: mappedRef,
    assignment: "mapped",
    availability: "available",
    status: look ? "ready" : "invalid",
    look,
    isShared: false,
    notIndividuallyMaintained: false,
  };
}

export function rawToPercent(raw: number | null | undefined): number | null {
  if (raw === null || raw === undefined || !Number.isFinite(raw)) return null;
  return Math.round((Math.max(0, Math.min(255, raw)) / 255) * 100);
}

export function percentToRaw(percent: number): number {
  return Math.max(0, Math.min(255, Math.round((percent / 100) * 255)));
}

export function brightnessProvenance(
  key: string,
  profile: Record<string, number>,
): { raw: number | null; percent: number | null; source: "explicit" | "standard" | "unavailable" } {
  const fallbackPhase = [...CANONICAL_PHASES, ...LEGACY_PHASES].find((phase) => key.endsWith(`_${phase}`));
  const fallbackRaw = fallbackPhase ? DEFAULT_BRIGHTNESS[fallbackPhase] : undefined;
  const raw = profile[key] ?? fallbackRaw;
  if (typeof raw !== "number") return { raw: null, percent: null, source: "unavailable" };
  const baseline = DEFAULT_BRIGHTNESS[key] ?? fallbackRaw;
  return {
    raw,
    percent: rawToPercent(raw),
    source: profile[key] === undefined && baseline !== undefined ? "standard" : baseline !== undefined && baseline === raw ? "standard" : "explicit",
  };
}

export function canonicalMatrixKeys(themes: string[]): string[] {
  return matrixKeys(themes, [...CANONICAL_PHASES]);
}

export function legacyMatrixKeys(themes: string[]): string[] {
  return matrixKeys(themes, [...LEGACY_PHASES]);
}

export function stateLabel(state: UiState): string {
  const labels: Record<UiState, string> = {
    loading: "Laden",
    ready: "Bereit",
    empty: "Leer",
    stale: "Veraltet",
    degraded: "Degradiert",
    unavailable: "Nicht verfügbar",
    reconnecting: "Verbinde neu",
    offline: "Offline",
    error: "Fehler",
    blocked: "Blockiert",
  };
  return labels[state];
}

export function keyLabel(key: string): string {
  for (const phase of [...CANONICAL_PHASES, ...LEGACY_PHASES]) {
    if (key === phase) return PHASE_LABELS[phase] ?? phase;
    if (key.endsWith(`_${phase}`)) {
      return `${THEME_LABELS[key.slice(0, -(phase.length + 1))] ?? key.slice(0, -(phase.length + 1))} · ${PHASE_LABELS[phase] ?? phase}`;
    }
  }
  return MODE_LABELS[key] ?? THEME_LABELS[key] ?? key;
}

export function toStateError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error ?? "Unbekannter Fehler");
}

export function hassEntity(hass: { states?: Record<string, HassState> } | null, entityId: string): HassState | null {
  return hass?.states?.[entityId] ?? null;
}
