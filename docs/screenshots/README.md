# UI screenshots

Captured with Chromium from the current application, using a fresh room with two
isolated human browser contexts and five offline mock opponents. No real provider,
API credential, existing save or private human conversation was used.

- `lobby.png`: landing page
- `classic-table.png`: Classic 3D board and three drafted French orders
- `mobile-orders.png`: responsive layout at a 430-pixel viewport

Reproduce against a server started with `conf/mock.json` using
`uv run python scripts/capture_readme.py`. The script verifies mock mode and loaded
Blender assets. These are UI demonstrations, not evidence of LLM playing strength.
