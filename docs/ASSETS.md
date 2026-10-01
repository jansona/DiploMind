# DiploMind Blender asset kit

Original, lightweight tabletop pieces created specifically for this project in
Blender 4.3.2. The art direction is an early-twentieth-century diplomatic war
room: colored enamel, warm brass, ivory decks, dark gunmetal, and unmistakable
army/fleet silhouettes. No downloaded models, external textures, add-ons, or
generative-service dependencies are used.

The Blender preview can be regenerated locally; see the build instructions below.

## Files

| Browser asset | Role | Triangles | Approximate size |
| --- | --- | ---: | ---: |
| `diplomind/static/assets/army.glb` | Field cannon on a national enamel token | 3,052 | 150 KiB |
| `diplomind/static/assets/fleet.glb` | Two-funnel dreadnought with pointed hull | 1,280 | 70 KiB |
| `diplomind/static/assets/center.glb` | Supply-center citadel marker | 1,004 | 55 KiB |
| `diplomind/static/assets/board-prop.glb` | Optional compass-rose medallion | 1,744 | 87 KiB |
| `diplomind/static/assets/manifest.json` | Exact dimensions, triangle counts, sizes, and national palette | | |
| `assets/blender/diplomind.blend` | Editable Blender source and presentation scene | | |
| `assets/blender/build_assets.py` | Reproducible geometry, materials, GLB export, and preview generation | | |
| `assets/blender/validate_assets.py` | Blender glTF import round-trip checks | | |
| `assets/blender/validation.json` | Machine-readable results from the most recent validation | | |
| `assets/blender/asset-preview.png` (generated) | CPU-rendered visual reference; not committed | | |

All four GLBs together are approximately 360 KiB. Each is one joined mesh with
four small opaque PBR material groups. There are no textures, skeletons, cameras,
lights, animation tracks, external URLs, or Draco/runtime decoder requirements.
The `.blend` uses built-in lossless file compression.

## Browser integration contract

- Load through `GLTFLoader` at `/static/assets/{army,fleet,center,board-prop}.glb`
- Units are arbitrary world units; the longest horizontal footprint is exactly 1
- Exported glTF is **+Y up**, **+Z forward**; the base lies at **Y=0**
- The origin is at the horizontal center of the footprint, on the ground
- Do not apply a further Blender-to-Three.js rotation; the exporter already performs it
- Exact `size` in the manifest is glTF `[width X, height Y, depth Z]`
- Army dimensions: `[1.0, 0.55503, 1.0]`
- Fleet dimensions: `[0.43158, 0.49158, 1.0]`
- Center dimensions: `[0.87921, 0.46383, 1.0]`
- Compass dimensions: `[1.0, 0.13550, 1.0]`
- These GLBs do not supply or alter map geography; the board uses the actual
  Diplomacy map separately

Clone the model and each material before assigning a country's color. Replace
the color of the material named **`Nation`** only; leave **`Brass`**, **`Ivory`**,
and **`Ink`** unchanged. Do not multiply the requested color by the neutral
authoring color. Meshes can also be batched/instanced per geometry and material
group for large boards. The optional center and compass should stay small
enough not to compete with province labels and selectable units.

```js
const piece = loaded.scene.clone(true);
piece.traverse((node) => {
  if (!node.isMesh) return;
  const source = Array.isArray(node.material) ? node.material : [node.material];
  const materials = source.map((material) => {
    const clone = material.clone();
    if (clone.name === 'Nation') clone.color.set(countryColor);
    return clone;
  });
  node.material = Array.isArray(node.material) ? materials : materials[0];
});
piece.position.set(boardX, surfaceHeight, boardZ);
piece.scale.setScalar(unitSize);
```

Use sRGB color inputs, a neutral hemisphere fill, and a soft directional key.
An environment map is optional. Unit outlines/selection rings, hit targets,
country text, orders, and accessibility affordances remain application features
and should not depend on color or fine model detail alone.

## National palette

| Nation | Color |
| --- | --- |
| Austria | `#C34E50` |
| England | `#314E72` |
| France | `#538ABF` |
| Germany | `#697078` |
| Italy | `#4B8C70` |
| Russia | `#A080AC` |
| Turkey | `#CCA65B` |

The preview demonstrates all seven variants without duplicating geometry in
downloadable assets. The application can choose its own consistent national
palette using the same `Nation` material contract.

## Rebuild and validate

Run from the project root with Blender 4.3 or later installed:

```sh
blender --background --python assets/blender/build_assets.py
blender --background --python assets/blender/validate_assets.py
```

For a quick geometry/export-only rebuild:

```sh
blender --background --python assets/blender/build_assets.py -- --skip-preview
```

The render uses Cycles on the CPU with six threads and no denoising dependency.
The full script needs no network access. The original game meshes are under
`GAME ASSETS · ground-centered Z-up sources`; the editable presentation scene
contains separate cloned pieces, seven nation swatches, a table, lights, labels,
and an orthographic review camera. The game source collection is hidden in the
viewport and its meshes are hidden in renders so the exported models do not
overlap the presentation pieces. Toggle the collection's viewport visibility
in the Outliner to inspect the source models.

Validation round-trips each file through Blender's glTF importer and asserts:
finite coordinates/normals, nonempty meshes, preserved triangle counts, exact
dimensions, centered origin, floor contact, the `Nation` material contract,
per-asset size budget, and absence of embedded scene cameras/lights. The CPU
preview is also visually inspected for silhouette and material readability.

## License

The original geometry, source scripts, and preview are provided under the
project's AGPL-3.0-or-later license. No third-party art attribution is required.

The generated Blender preview PNG is omitted from Git. The editable `.blend`, build/validation scripts and all GLBs remain included; regenerate the preview with the build script. Current rendered gameplay screenshots are in `docs/screenshots/`.
