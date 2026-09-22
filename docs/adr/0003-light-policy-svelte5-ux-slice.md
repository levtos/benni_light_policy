# ADR 0003: Light-Policy Svelte-5 UX Slice

Status: accepted for Issue #26 implementation scope
Date: 2026-08-08
Owner: Codex (`owner/codex`)
Scope: `Levtos/benni_light_policy#26`

## Context

Issue [#26](https://github.com/Levtos/benni_light_policy/issues/26) is the first
Umbrella-fähige UX slice for the existing Light Policy integration. The binding
decisions are [Issue #25](https://github.com/Levtos/benni_light_policy/issues/25),
[Levtos/control#17](https://github.com/Levtos/control/issues/17),
[ADR 0001](https://github.com/Levtos/control/blob/main/docs/adr/0001-ux-frontend-standard.md)
and [ADR 0002](https://github.com/Levtos/control/blob/main/docs/adr/0002-github-only-governance.md).
The integration-specific briefing remains
[`docs/UX_REWORK_BRIEFING.md`](../UX_REWORK_BRIEFING.md); the functional source
is the reviewed Lichtlogik specification in `Levtos/einhornzentrale`.

The current backend already exposes status, look-map, look-catalog and brightness
profile WebSocket commands. The status response is a merged brightness profile
and does not expose `applied_look`, an acknowledgement, or explicit override
metadata.

## Decision

1. The frontend is a static Svelte 5/Vite/TypeScript module compiled to
   `custom_components/benni_light_policy/frontend/app/main.js` and registered by
   the existing `blp-app` host element. The host/gateway owns the HA connection,
   authorization and locale boundary; the module does not create an account,
   profile or global navigation.
2. `frontend/src/lib/light-policy/client.ts` is the only transport adapter. It
   wraps only existing commands: `get_status`, `get_look_map`,
   `benni_scene_presets/list_looks`, `set_look_map`, `set_subentry_mappings`,
   `set_apply_enabled`, `set_brightness_profile` and `set_custom_themes`. No
   backend command, mock, fixture or future generation API is introduced.
3. The module exposes six internal views: Übersicht, Look-Zuordnung,
   Feste Modi, Regeln, Helligkeit and Diagnose. The Rules view added by Issue
   [#46](https://github.com/Levtos/benni_light_policy/issues/46) edits only the
   existing Gaming-subentry classifier-to-look mappings. Source creation,
   classifier binding and priority remain in the native HA subentry flow.
   Calendar/event CRUD, scene generation,
   domain renaming, Core State changes, Scene Presets changes and Event Ownership
   remain outside this issue.
4. The primary matrix uses exactly the nine canonical phase IDs from the existing
   catalog. `late_morning` and `early_evening` remain separately visible as
   legacy compatibility values. Every theme/event-phase cell is an independent
   look reference; repeated references are valid and are shown as shared, not as
   inheritance. Saving is a local draft plus one conscious full-map mutation.
5. Brightness is a separate profile model. The UI edits percentages, keeps
   standard/fallback values separate from explicit overrides, and offers reset per
   override. Backend raw values remain visible only in Diagnose. Because the
   backend returns merged values, an explicit value equal to the standard cannot
   be proven as explicit; the UI documents this limit instead of fabricating
   provenance.
6. No applied-look claim is made. The Übersicht labels the actual running look
   as unverified/degraded until an authoritative backend contract exists. HA
   entity switches are not used as execution proof.
7. CSS is injected into the module's ShadowRoot and separately into the document
   for portaled Bits UI tooltip content. The design uses Graphite Dark semantic
   tokens, controlled Bits UI, Tailwind, Lucide, 44px touch targets, de-DE/
   Europe-Berlin formatting and reduced-motion rules.

## Consequences and gates

- The slice is implementable and testable without changing Core State,
  `benni_scene_presets`, Event Ownership, domain behavior, the live system or
  deployment.
- Missing, invalid, stale, unavailable, degraded, reconnecting, offline, error
  and blocked states remain explicit; a failed look catalog is not reported as a
  false missing look.
- Build, type, lint, unit, Python, contract and documentation checks are
  technical evidence only. Draft PR, review/merge and release remain separate
  gates; HA reload, real browser acceptance, Live and Live Verified remain
  Benni's gates.
- Open follow-up gates are the authoritative applied-look/ack contract, event
  ownership/CRUD, central shell/gateway integration, Scene Presets generation,
  priority decisions and any Light Control rename.
