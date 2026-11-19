# Frontend JavaScript Architecture (ES Modules)

Native ES modules architecture (`<script type="module">`) with plain JavaScript and Leaflet GIS. No bundler, no build step, no npm packages required.

## Module Map

| Module Path | Primary Responsibility |
| :--- | :--- |
| `frontend/js/main.js` | Entry point, DOMContentLoaded lifecycle, initialization sequence, polling intervals. |
| `frontend/js/config.js` | System constants, API base URL (same-origin rule), map defaults, polling timers. |
| `frontend/js/state.js` | Single source of truth for mutable UI state, layer groups, and session messages. |
| `frontend/js/api.js` | Centralized backend API client: one exported function per endpoint with error handling. |
| `frontend/js/utils/dom.js` | DOM helpers, HTML escaping (XSS prevention), number and assumption formatting. |
| `frontend/js/map/map.js` | Leaflet map initialization, basemaps, choropleth polygon styling, district selection. |
| `frontend/js/map/layers.js` | Map layers (facility circle markers, buffer polygons, blank-spot polygons, sim layers). |
| `frontend/js/map/actions.js` | Dual-view sync: dispatches AI assistant spatial tool actions to map and panels. |
| `frontend/js/panels/scorecard.js` | Scorecard dial, verbatim composite note, 4-pillar badges & effective weights, metrics audit. |
| `frontend/js/panels/blankspots.js`| Blank spots panel: coverage metrics, cross-border notes, buffer layer triggers. |
| `frontend/js/panels/simulation.js`| What-if shock & superblock sandbox controls, input synchronization, delta rendering. |
| `frontend/js/panels/watchdog.js`  | Watchdog telemetry panel: GPU metrics, AI engine status, PostGIS & Redis container states. |
| `frontend/js/panels/tabs.js`      | Right sidebar tab navigation & view switching. |
| `frontend/js/chat/chat.js`        | Asisten Tata Ruang chat dock, markdown rendering, guardrail badges, citations list. |
| `frontend/js/auth/auth.js`        | Authentication manager: JWT in sessionStorage, modal dialogs, header badge, action gatekeeping. |

## Dependency Direction (Acyclic DAG)

All module dependencies flow strictly unidirectionally without circular references (generated via `scripts/check_frontend_modules.py --graph`):

```
[main.js]
   ├── [config.js]
   ├── [map/map.js]
          ├── [state.js]
          ├── [config.js]
          ├── [api.js] ──> [config.js]
          ├── [utils/dom.js]
          ├── [map/layers.js] ──> [state.js], [utils/dom.js]
          ├── [panels/scorecard.js] ──> [state.js], [config.js], [utils/dom.js]
          ├── [panels/blankspots.js] ──> [api.js], [utils/dom.js], [map/layers.js]
          └── [panels/simulation.js] ──> [state.js], [api.js], [utils/dom.js]
   ├── [panels/tabs.js] ──> [state.js], [panels/blankspots.js], [map/layers.js]
   ├── [panels/simulation.js] ──> [state.js], [api.js], [utils/dom.js]
   ├── [chat/chat.js]
   │      ├── [state.js]
   │      ├── [api.js]
   │      ├── [utils/dom.js]
   │      └── [map/actions.js] ──> [state.js], [map/map.js], [map/layers.js], [panels/tabs.js], [panels/blankspots.js]
   ├── [panels/watchdog.js] ──> [api.js] ──> [config.js]
   └── [auth/auth.js] ──> [api.js]
```

Leaves (zero internal imports or importing other leaves only): `state.js`, `config.js`, `utils/dom.js`, `api.js`.

## How to Add a New Panel

1. **Create panel module:** Add `frontend/js/panels/<panel_name>.js` with a 2-4 line header comment.
2. **Fetch and render data:** Export initialization (`init<Panel>()`) and render (`render<Panel>(data)`) functions. Import needed endpoints from `api.js` and state from `state.js`.
3. **Add HTML tab button and pane:** In `frontend/index.html`, add `<button class="info-tab-btn" data-tab="<panel_name>">` and `<div class="tab-pane-view" id="tab-pane-<panel_name>">`.
4. **Register in tabs switcher:** In `frontend/js/panels/tabs.js`, add handling in `switchToTab` if the panel has associated map layers.
5. **Wire lifecycle:** In `frontend/js/main.js`, import and call `init<Panel>()` during `DOMContentLoaded`.
