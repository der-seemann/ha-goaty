# ha-goaty

Custom Home Assistant integration for Ecovacs GOAT zone control.

## What this repo contains

- `custom_components/goaty_zone/`
- `custom_components/goaty_zone/www/goaty-zones-card.js`
- `example_packages/goaty_automations.yaml`
- `hacs.json`

## First setup in Home Assistant

1. Install the integration via HACS or copy it into `/config/custom_components/goaty_zone/`.
2. Restart Home Assistant.
3. Add `Goaty Zone Control` via Settings -> Devices & services.
4. Open Developer Tools -> Services and run `goaty_zone.get_zones` once.
5. Open Developer Tools -> Services and run `goaty_zone.create_dashboard` once.

Example:

```yaml
service: goaty_zone.get_zones
data: {}
```

Dashboard creation:

```yaml
service: goaty_zone.create_dashboard
data:
  dashboard_title: "Goaty"
  overwrite: false
```

After a browser reload the dashboard appears in the sidebar as `Goaty`.

If zones change later, run `goaty_zone.create_dashboard` again with `overwrite: true`.

## Notes

- Zone data is persisted in HA storage under `goaty_zone.zone_config`.
- `sensor.goaty_zones` is the source of truth for the cards and exposes the derived config attributes.
- `input_text.goaty_zones_json` and `input_text.goaty_zones_hash` remain only as compatibility/debug mirrors.
- `goaty_zone.get_due_zones` is the service to use from automations.
- `goaty_zone.create_dashboard` writes a dynamic Lovelace dashboard with `goaty-map-card`, `goaty-zones-card`, zone status, and maintenance sections.
- `example_packages/goaty_automations.yaml` is a template and must be adapted to the real zone IDs.
- There are no per-zone scripts or `shell_command.goaty_*` helpers left in the repo.
