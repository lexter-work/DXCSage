# DXC Sage — UI redesign spec

Date: 2026-11-24. Status: mockup done and checked, nothing built in `sage_web`.

Reskin of `sage_web` to the DXC 2026 brand. Layout, pages, routes and wording stay as they are in the current Vue app. Reference: `DXCSage_brand_mockup.html` in this folder (self-contained, opens in any browser). Palette and font follow the brand work already validated for CalendarViewer (`docs/archive/dxc-brand-ui-validation.md` in that repo).

## Decisions

| Topic | Decision |
|---|---|
| Palette | DXC 2026 brand colours only, plus named derived UI shades (below) |
| Status green | `#107C41` / `#6FD08C` for pass and ok. Not in the DXC palette: same exception as CalendarViewer, needs brand review |
| Fonts | Inter for UI text (stands in for GT Standard, as in CalendarViewer). JetBrains Mono for SAP identifiers, numbers, JSON |
| Header | 56px Midnight brand bar: official DXC logo, divider, "Sage". Replaces the green "S" badge |
| Dark mode | Navy shades built from Midnight, True Blue as accent. CalendarViewer uses grey neutrals instead |
| Themes | Light, dark and system, same switch as today (`theme.ts`, `data-theme` on `<html>`) |
| Main menu | Collapsible: 216px, or a 60px icon strip. State remembered. Ctrl+B |
| Chat list | Collapsible on desktop: 296px, or a 56px strip with one status dot per chat. Ctrl+Shift+B. Below 1000px it becomes a 320px slide-in panel opened from a "Chats" button |
| Status labels | Written in sentence case in the markup. No CSS capitalisation |

## Colour tokens

Named for the existing `moss.css` variables so the theme file can swap values without touching component CSS.

| moss.css | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F6F3F0` Canvas | `#0E1020` Midnight | Page background |
| `--panel` | `#FFFFFF` | `#171A2E` | Cards, tables, drawers |
| `--sunken` | `#FBF9F7` | `#20243A` | Code blocks, table hover, meta rows |
| `--hover` | `#FBF9F7` | `#20243A` | Same as `--sunken` (the mockup has no separate hover shade) |
| `--ink` | `#0E1020` Midnight | `#F6F3F0` Canvas | Primary text |
| `--ink-2` | `#4B4D5E` | `#B4B2C0` | Secondary text, labels |
| `--ink-3` | `#4B4D5E` | `#B4B2C0` | Same as `--ink-2` (a lighter third grey fails contrast) |
| `--line` | `#E4DFDA` | `#2E3350` | Dividers |
| `--line-2` | `#D3CDC6` | `#3B4163` | Input and button borders, table header rule |
| `--accent` | `#004AAC` Royal | `#4995FF` True Blue | Primary buttons, current menu item, focus ring |
| `--accent-ink` | `#FFFFFF` | `#0E1020` | Text on accent |
| `--accent-soft` | Royal 8% on White | True Blue 14% on `#171A2E` | Current menu item, info callouts |
| `--ok` / `--ok-soft` | `#107C41` / 10% tint | `#6FD08C` / 14% tint | Pass, active, enabled |
| `--warn` / `--warn-soft` | `#8A5300` / Gold 16% tint | `#FFAE41` Gold / 14% tint | Waiting, setup, warn |
| `--bad` / `--bad-soft` | White on `#D14600` Red | `#FF7E51` Melon on 16% tint | Fail, disabled, error |

Extra tokens the mockup adds: header `#0E1020` (dark `#0B0D1A`), header line `#2E3350`, header divider `rgb(246 243 240 / .28)`, primary hover `#003A87` (dark `#6AA9FF`), user message bubble Midnight (dark `#20243A`). Red text on Canvas is 4.14:1, so red is only used as a filled background with White text.

## Components

| Element | Spec |
|---|---|
| Button | 34px high (28px small), 4px radius, 1px `--line-2` border. Primary is filled `--accent` |
| Field | 34px high, 4px radius. Dropdowns draw their own chevron (the browser's arrow clipped "Claude") |
| Pill | 22px high, fully rounded, 6px dot, tinted background in the status colour |
| Panel / card | `--panel`, 1px `--line`, 6px radius. Shadow only on the run trace |
| Table | Thin rules, no boxed cells. Numbers right-aligned, tabular figures. Long tables scroll inside their own container |
| Drawer | Right side, `min(480px, 100%)`, header 56px, footer with Cancel and the primary action. Closes on ✕, backdrop and Esc |
| Callout | 3px left bar: Gold for warnings, accent for info |
| Page | 28px / 32px padding, max width 1240px. Title states the point where there is one (Health, Settings, Usage) |

## Screens

All current routes are covered: Chat, My usage, Account, and admin Systems, Workflows, setup guide, Health, Runs, Audit, Usage (all), Users, Settings, plus the sign-in page.

- **Chat**: the workflow run is the main element. It shows a step list from `RFC_PING` to `ZFM_RC_FETCH_ANALYSIS`, a "Waiting" state with the next check time, and a meta row (started, elapsed, SAP job, tokens).
- **Setup guide**: the 15 requirements `sap_readiness_check` declares, grouped into Connection, Function modules, Tables and Settings. The title gives the count ("14 of 15 checks pass"). Settings and the Basis authorization table sit in a 400px side column. Below 1000px the settings card moves above the steps and the authorization table moves to the end.
- **Settings**: real keys and defaults from `settings_store.py`, grouped by prefix. Secrets open a password field only; JSON values open an editor.
- **Audit**: event family in grey, action in full colour, `auth.fail` in warning colour. Filter suggests the 21 event names `sage_api` writes.

## Responsive

| Width | Behaviour |
|---|---|
| Above 1000px | Main menu and chat list docked, both collapsible |
| 1000px and below | Main menu becomes a scrolling tab row (scrollbar hidden). Chat list becomes a slide-in panel. Setup guide becomes one column |
| 640px and below | Page padding 16px, run meta row in two columns, theme switch and username hidden from the header |

No horizontal page scroll at 320px.

## Checked

Browser checks run on 24 November 2026 against the mockup:

- **Overflow**: all 13 screens, light and dark, at 1440, 834, 390 and 320px. None.
- **Text contrast**: every visible text element on all 13 screens and the open drawers, light and dark, measured against WCAG AA (4.5:1, 3:1 for large text). All pass.
- **Behaviour**: collapse and expand of both sidebars, the phone chat panel (open, close, Esc, pick a chat, focus moves in and back out), and the setup guide order at 390, 834 and 1440px.

Bugs found and fixed in the mockup, worth carrying into the build:

1. Run trace steps rendered timing on the left. Give each grid cell an explicit column.
2. Setup guide side column ran past the screen at 390px. Grid children need `min-width: 0`.
3. A desktop-only grid rule overrode the phone layout and stacked cards on top of each other. Keep desktop column rules inside a `min-width` media query.
4. `display: grid` on labels overrode `[hidden]`, so the Settings drawer showed the secret field under the JSON editor. Add `[hidden]{display:none !important}`.
5. Drawer focus did not move in while the panel was still `visibility: hidden`. Switch visibility with no delay on open and a delayed one on close.
6. `text-transform: capitalize` produced "Not Set" and "Long-Running". Write labels in sentence case.

## Not verified

- The "system" theme option (it only switches when Windows is in dark mode).
- Keyboard shortcuts in a real browser.
- Inter versus GT Standard: Inter is a stand-in pending the licensing decision recorded for CalendarViewer.
- Sample data: users, runs, audit entries, usage and the 5-minute check interval are made up. Event names, setting keys, requirements and authorization rows come from `sage_api`.
- ABAP source in the setup guide is a placeholder; the app reads it from `static/rfc/*.txt`.
