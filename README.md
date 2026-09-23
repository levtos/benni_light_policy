# benni_light_policy

Licht-Policy als eigenständige HACS-Custom-Integration.

## Gaming-/Musik-Subentry-Diagnose

`sensor.light_policy_living_room_debug` zeigt bei wirkungslosen Gaming- oder
Musik-Subentries einen Diagnosehinweis im Zustand und die vollständige Liste
unter `subentry_diagnostics`. Derselbe Wert steht im Plan-Snapshot des Sensors
und in `benni_light_policy/get_status` unter `plan.subentry_diagnostics`.
`missing_mappings` bezeichnet eine fehlende oder leere Mapping-Tabelle,
`missing_source_id` eine leere/ungültige Gaming-Quelle und
`classifier_unmapped` einen aktiven Classifier-Wert ohne wirksamen Look-Eintrag.
`classifier_unavailable` kennzeichnet einen fehlenden Classifier-Wert bei
passendem Gaming-/Musik-Gate. Eine leere Diagnoseliste kann auch bedeuten, dass
keine entsprechende Subentry vorhanden oder ihre Quelle gerade inaktiv ist.
Diese Hinweise sperren den normalen Tagesphasen-Fallback nicht.

## PS/S sleep context (#59)

`provisional_sleep` und `sleep` sind gleichwertige terminale
Schlaf-Hard-Off-Kontexte. Sie schlagen Entertainment/TV, Gaming, Bewegung und
die reguläre Tagesphasen-Policy; deshalb kann TV-Aus während PS weder eine
Awake-Szene noch ein Resume auslösen. Der tatsächliche Activity-State darf
parallel `entertainment` bleiben. Erst Core States regulärer Wechsel aus PS/S
öffnet die normalen Licht-Policies wieder.

## FLEET-54 source migration

Seit `0.2.5` migriert die Integration bekannte alte Toolbox/YAML-Quellen in
bestehenden ConfigEntries automatisch auf die Core-Integrationen:

- `sensor.garden_illuminance_atomic` -> `sensor.benni_device_garden_lux`
- `sensor.weather_season_meteorological_atomic` ->
  `sensor.benni_device_weather_season_meteorological`
- `sensor.benni_context_day_context` /
  `sensor.benni_combined_context_day_context` ->
  `sensor.benni_core_state_day_context`
- Legacy Core-State context/activity/presence entities -> their matching
  `sensor.benni_core_state_*` clean IDs
- `binary_sensor.benni_media_context_entertainment_active` ->
  `binary_sensor.benni_media_state_entertainment_active`
