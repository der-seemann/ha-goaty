class GoatyZonesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {
      title: "Goaty",
      zones_entity: "sensor.goaty_zones",
      mower_entity: "vacuum.goaty_map_proxy",
      battery_entity: "sensor.goaty_batterie",
      status_entity: "sensor.goaty_mahstatus",
      fault_entity: "sensor.goaty_effektiver_fehler",
      active_zone_entity: "input_text.goaty_current_zone_name",
      zone_active_bool: "input_boolean.goaty_zone_active",
      dock_domain: "vacuum",
      dock_service: "return_to_base",
      mow_domain: "goaty_zone",
      mow_service: "mow_zone",
      reload_domain: "goaty_zone",
      reload_service: "reload_zones",
    };
    console.info("GOATY-ZONES-CARD v1.1.0");
  }

  setConfig(config) {
    this._config = { ...this._config, ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    const zones = this._zones().length;
    return Math.max(3, Math.ceil((zones + 2) / 2));
  }

  _zones() {
    const stateObj = this._hass?.states?.[this._config.zones_entity];
    const attrZones = stateObj?.attributes?.zones;
    if (Array.isArray(attrZones)) {
      return attrZones.filter((zone) => zone && zone.id && zone.name);
    }
    if (typeof attrZones === "string" && attrZones.trim().startsWith("[")) {
      try {
        const parsedAttrZones = JSON.parse(attrZones);
        if (Array.isArray(parsedAttrZones)) {
          return parsedAttrZones.filter((zone) => zone && zone.id && zone.name);
        }
      } catch (err) {
        console.warn("GOATY-ZONES-CARD: failed to parse attribute zones JSON", err);
      }
    }

    const raw = stateObj?.state;
    if (typeof raw === "string" && raw.trim().startsWith("[")) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          return parsed.filter((zone) => zone && zone.id && zone.name);
        }
      } catch (err) {
        console.warn("GOATY-ZONES-CARD: failed to parse fallback zones JSON", err);
      }
    }

    const fallback = this._hass?.states?.[this._config.zones_entity]?.attributes?.zone_names;
    if (Array.isArray(fallback) && fallback.length) {
      return fallback.map((name, index) => ({ id: String(index + 1), name }));
    }

    return [];
  }

  _activeZone() {
    const activeZoneEntity = this._hass?.states?.[this._config.active_zone_entity];
    return activeZoneEntity?.state || "";
  }

  _zoneActive() {
    const boolState = this._hass?.states?.[this._config.zone_active_bool];
    return boolState?.state === "on";
  }

  _battery() {
    const stateObj = this._hass?.states?.[this._config.battery_entity];
    return stateObj?.state || "";
  }

  _status() {
    const stateObj = this._hass?.states?.[this._config.status_entity];
    return stateObj?.state || "";
  }

  _fault() {
    const stateObj = this._hass?.states?.[this._config.fault_entity];
    return stateObj?.state || "";
  }

  _guessDockDomain() {
    if (this._config.dock_domain) {
      return this._config.dock_domain;
    }
    const entity = this._config.mower_entity || "";
    return entity.includes(".") ? entity.split(".", 1)[0] : "vacuum";
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async _callService(domain, service, data = {}) {
    if (!this._hass) {
      return;
    }
    await this._hass.callService(domain, service, data);
  }

  async _mowZone(zone) {
    await this._callService(this._config.mow_domain, this._config.mow_service, {
      zone_id: zone.id,
      zone_name: zone.name,
    });
  }

  async _reloadZones() {
    await this._callService(this._config.reload_domain, this._config.reload_service, {});
  }

  async _dock() {
    const domain = this._config.dock_domain || this._guessDockDomain();
    const service = this._config.dock_service || "return_to_base";
    const entityId = this._config.mower_entity;
    await this._callService(domain, service, { entity_id: entityId });
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }

    const zones = this._zones();
    const activeZone = this._activeZone();
    const battery = this._battery();
    const status = this._status();
    const fault = this._fault();
    const zoneActive = this._zoneActive();
    const esc = this._escape.bind(this);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --bg: #0f172a;
          --panel: rgba(15, 23, 42, 0.92);
          --panel-2: rgba(30, 41, 59, 0.9);
          --text: #e2e8f0;
          --muted: #94a3b8;
          --line: rgba(148, 163, 184, 0.22);
          --accent: #22c55e;
          --accent-2: #38bdf8;
          --danger: #f97316;
          font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        ha-card {
          background: linear-gradient(180deg, rgba(2,6,23,0.9), rgba(15,23,42,0.95));
          color: var(--text);
          border: 1px solid var(--line);
          border-radius: 24px;
          overflow: hidden;
          box-shadow: 0 20px 40px rgba(0,0,0,0.25);
        }
        .wrap {
          padding: 16px;
        }
        .top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 16px;
        }
        .title {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .title h1 {
          font-size: 20px;
          line-height: 1.1;
          margin: 0;
          letter-spacing: -0.02em;
        }
        .subtitle {
          color: var(--muted);
          font-size: 13px;
        }
        .badges {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border: 1px solid var(--line);
          background: var(--panel-2);
          color: var(--text);
          border-radius: 999px;
          padding: 8px 12px;
          font-size: 12px;
          font-weight: 600;
        }
        .badge.ok {
          border-color: rgba(34, 197, 94, 0.35);
          color: #bbf7d0;
        }
        .badge.warn {
          border-color: rgba(249, 115, 22, 0.35);
          color: #fdba74;
        }
        .toolbar {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 8px;
          margin-bottom: 16px;
        }
        button {
          appearance: none;
          border: 1px solid var(--line);
          background: rgba(30, 41, 59, 0.95);
          color: var(--text);
          border-radius: 16px;
          padding: 12px 14px;
          font-weight: 700;
          font-size: 13px;
          cursor: pointer;
          transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
        }
        button:hover {
          transform: translateY(-1px);
          border-color: rgba(56, 189, 248, 0.45);
          background: rgba(51, 65, 85, 0.95);
        }
        button.primary {
          background: linear-gradient(135deg, rgba(34,197,94,0.2), rgba(56,189,248,0.18));
          border-color: rgba(56, 189, 248, 0.3);
        }
        button.dock {
          background: linear-gradient(135deg, rgba(249,115,22,0.18), rgba(148,163,184,0.08));
        }
        .zones {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 10px;
        }
        .zone {
          text-align: left;
          min-height: 74px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
        }
        .zone.active {
          border-color: rgba(34, 197, 94, 0.7);
          box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.35) inset, 0 0 0 1px rgba(34, 197, 94, 0.16);
          background: linear-gradient(180deg, rgba(22, 163, 74, 0.2), rgba(30, 41, 59, 0.92));
        }
        .zone .name {
          font-size: 15px;
          font-weight: 800;
        }
        .zone .meta {
          margin-top: 8px;
          color: var(--muted);
          font-size: 12px;
        }
        .empty {
          padding: 18px;
          border-radius: 16px;
          border: 1px dashed var(--line);
          color: var(--muted);
          text-align: center;
        }
        .footer {
          margin-top: 14px;
          display: flex;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          color: var(--muted);
          font-size: 12px;
        }
        .footer strong {
          color: var(--text);
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="top">
            <div class="title">
              <h1>${esc(this._config.title || "Goaty")}</h1>
              <div class="subtitle">Zonen werden aus dem Sensor geladen, nicht aus einem 255-Zeichen-Spielzeug.</div>
            </div>
            <div class="badges">
              <div class="badge ${zoneActive ? "ok" : "warn"}">${zoneActive ? "aktiv" : "bereit"}</div>
              ${status !== "" ? `<div class="badge">${esc(status)}</div>` : ""}
              ${fault !== "" ? `<div class="badge ${String(fault) !== "0" ? "warn" : "ok"}">Fehler ${esc(fault)}</div>` : ""}
              ${battery !== "" ? `<div class="badge">Akku ${esc(battery)}%</div>` : ""}
            </div>
          </div>

          <div class="toolbar">
            <button class="primary" data-action="reload">↻ Zonen neu laden</button>
            <button class="dock" data-action="dock">Zur Station</button>
            <button data-action="refresh">Status aktualisieren</button>
          </div>

          ${
            zones.length
              ? `<div class="zones">
                  ${zones
                    .map((zone) => {
                      const active =
                        zone.name === activeZone ||
                        zone.id === activeZone;
                      return `
                        <button class="zone ${active ? "active" : ""}" data-zone-id="${zone.id}" data-zone-name="${zone.name}">
                          <div class="name">${esc(zone.name)}</div>
                          <div class="meta">ID ${esc(zone.id)}${active ? " · aktiv" : ""}</div>
                        </button>
                      `;
                    })
                    .join("")}
                </div>`
              : `<div class="empty">Keine Zonen im Sensor gefunden.</div>`
          }

          <div class="footer">
            <div><strong>Sensor:</strong> ${esc(this._config.zones_entity)}</div>
            <div><strong>Aktive Zone:</strong> ${esc(activeZone || "keine")}</div>
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.querySelectorAll("button[data-zone-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const zone = {
          id: button.getAttribute("data-zone-id"),
          name: button.getAttribute("data-zone-name") || "",
        };
        try {
          await this._mowZone(zone);
        } catch (err) {
          console.error("GOATY-ZONES-CARD: mow failed", err);
        }
      });
    });

    this.shadowRoot.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const action = button.getAttribute("data-action");
        try {
          if (action === "reload") {
            await this._reloadZones();
          } else if (action === "dock") {
            await this._dock();
          } else if (action === "refresh") {
            this._render();
          }
        } catch (err) {
          console.error("GOATY-ZONES-CARD action failed", action, err);
        }
      });
    });
  }
}

if (!customElements.get("goaty-zones-card")) {
  customElements.define("goaty-zones-card", GoatyZonesCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "goaty-zones-card",
  name: "Goaty Zones Card",
  description: "Control and inspect Goaty mowing zones.",
});
