export const UX_CONTRACT_VERSION = "light-policy-ux.v1" as const;

// These values mirror the existing websocket catalog contract. They are not a
// second day-state calculation; they only keep the UI order stable and mark
// compatibility values explicitly.
export const CANONICAL_PHASES = [
  "early_night",
  "late_night",
  "early_morning",
  "forenoon",
  "midday",
  "afternoon",
  "late_afternoon",
  "evening",
  "late_evening",
] as const;

export const LEGACY_PHASES = ["late_morning", "early_evening"] as const;

export const FIXED_MODES = ["idle", "cinema", "private_time", "waking", "work_home"] as const;

export const SEASON_KEYS = ["spring", "summer", "autumn", "winter"] as const;
export const EVENT_KEYS = [
  "christmas",
  "easter",
  "halloween",
  "carnival",
  "geburtstag",
  "silvester",
  "pride",
  "advent_1",
  "advent_2",
  "advent_3",
  "advent_4",
  "stpatricks",
] as const;

export type CanonicalPhase = (typeof CANONICAL_PHASES)[number];
export type LegacyPhase = (typeof LEGACY_PHASES)[number];
export type FixedMode = (typeof FIXED_MODES)[number];

export type UiState =
  | "loading"
  | "ready"
  | "empty"
  | "stale"
  | "degraded"
  | "unavailable"
  | "reconnecting"
  | "offline"
  | "error"
  | "blocked";

export type MutationState = "idle" | "pending" | "success" | "error" | "blocked";

export type LightPolicyView = "overview" | "matrix" | "fixed-modes" | "rules" | "brightness" | "diagnostics";

export interface HassState {
  state: string;
  attributes: Record<string, unknown>;
}

export interface HassConnection {
  sendMessagePromise<T = unknown>(message: Record<string, unknown>): Promise<T>;
}

export interface HassLike {
  connection?: HassConnection;
  states?: Record<string, HassState>;
}

export interface Look {
  id?: string | number;
  name?: string;
  slug?: string;
  category?: string;
  transition?: number;
  bindings?: unknown[];
  [key: string]: unknown;
}

export interface PlanSnapshot {
  mode?: string | null;
  preset_enum?: string | null;
  brightness?: number | null;
  color_temp?: number | null;
  apply_kind?: string | null;
  apply_allowed?: boolean;
  reason?: string | null;
  scene_hash?: string | null;
  blockers?: string[];
  targets?: string[];
  exclusive_off?: string[];
  [key: string]: unknown;
}

export interface GateSnapshot {
  startup_ready?: boolean;
  lux_gate_on?: boolean;
  tmc_set?: boolean;
  weather_dark?: boolean;
  lux_samples?: number;
  thresholds?: { dark?: number; bright?: number; [key: string]: unknown };
  [key: string]: unknown;
}

export interface FoundationSnapshot {
  ok?: number;
  total?: number;
  missing?: string[];
  [key: string]: unknown;
}

export interface SubentryRule {
  subentry_id?: string;
  type?: string;
  title?: string;
  source_id?: string;
  classifier_entity?: string;
  mappings?: Record<string, string>;
  [key: string]: unknown;
}

export interface AreaRule {
  subentry_id?: string;
  type?: string;
  title?: string;
  data?: Record<string, unknown>;
  via_look?: boolean;
  [key: string]: unknown;
}

export interface LightPolicyStatus {
  version?: number | string | null;
  plan: PlanSnapshot;
  gate: GateSnapshot;
  apply_enabled: boolean;
  manual_off: boolean;
  ring_mode?: string | null;
  activity?: string | null;
  day_state?: string | null;
  desired_policy_key?: string | null;
  desired_look_ref?: string | null;
  foundation: FoundationSnapshot;
  subentry_rules: SubentryRule[];
  areas: AreaRule[];
  brightness_profile: Record<string, number>;
  [key: string]: unknown;
}

export interface LightPolicyCatalog {
  look_map: Record<string, string>;
  fixed_modes: string[];
  themes: string[];
  custom_themes: string[];
  phases: CanonicalPhase[];
  legacy_phases: LegacyPhase[];
  matrix_keys: string[];
  legacy_matrix_keys: string[];
  supported_phases: string[];
  supported_matrix_keys: string[];
  subentry_rules: SubentryRule[];
}

export interface LooksResponse {
  looks: Look[];
  [key: string]: unknown;
}

export interface MutationSnapshot {
  state: MutationState;
  action: string | null;
  message: string | null;
}

export type CoverageAssignment = "mapped" | "fallback" | "unassigned";
export type CoverageAvailability = "available" | "missing" | "unavailable" | "stale";

export interface Coverage {
  key: string;
  ref: string;
  assignment: CoverageAssignment;
  availability: CoverageAvailability;
  status: "ready" | "missing" | "invalid" | "unavailable" | "stale";
  look: Look | null;
  isShared: boolean;
  notIndividuallyMaintained: boolean;
}
