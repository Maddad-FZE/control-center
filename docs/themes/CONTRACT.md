# Theme contract

A pack may replace chrome, tokens, and page arrangement. It must keep the hooks scripts bind to, or omit the ones marked optional. Optional nodes must be absent entirely. Scripts return early when they are missing.

## Required when that chrome is shown

| Hook | Required |
| --- | --- |
| `#main-content` | always |
| `#tva-clock` | only if `layout.show_clock` |
| `#user-menu`, `#user-menu-trigger`, `#user-menu-dropdown` | when the viewer is signed in and actions are shown |
| `#alerts-menu`, `#alerts-bell`, `#alerts-dropdown`, `#alerts-panel` | same |
| `#toast-stack` | only when there are messages |
| `#header-update-btn`, `#footer-update-btn` | optional; updates.js no-ops if both are missing |
| `#ops-stack` | optional; dashboard treats a missing stack as non-admin layout |
| `#service-filter`, `#status-strip` | optional; filter and status simply do not run |
| `[data-helper-dock]` on a dock node (never `body`) | optional; Merlin floats if it is missing |

## Body data attributes

`data-theme`, `data-chrome`, `data-pinned`, `data-helper`, `data-helper-dock-pref`, `data-page`.

`data-helper-dock-pref` on `body` names the preferred dock. The actual mount is a separate node with `data-helper-dock` (`.dashboard-merlin`, `.settings-merlin-dock`, or `.shell-helper`). Do not put `data-helper-dock` on `body`; the helper script would mount into the page root.

`data-helper="hidden"` skips the helper script. `data-helper="docked"` docks into the first dock node. Tip copy is `data-helper-tip` on that dock.

## Stable template paths a pack may override

`core/shell/layouts/topbar.html`, `sidebar.html`, `none.html`, `core/shell/_brand.html`, `_nav.html`, `_actions.html`, `_footer.html`, `_helper.html`, `dashboard/_groups.html`, `dashboard/_launcher.html`, `dashboard/_ops_stack.html`, `dashboard/_status_strip.html`, `core/shell/_rail.html`.
