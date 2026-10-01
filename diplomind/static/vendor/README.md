# Vendored renderer dependencies

Three.js **0.186.1** is served locally. There are no runtime CDN or external font requests.

Source: the official `three@0.186.1` package from https://registry.npmjs.org/three
License: MIT, reproduced in `THREE-LICENSE.txt`

Included modules:
- `build/three.module.js` and `build/three.core.js`, locally minified to `*.min.js`
- `examples/jsm/controls/OrbitControls.js`
- `examples/jsm/loaders/GLTFLoader.js` and `SVGLoader.js`
- `examples/jsm/utils/BufferGeometryUtils.js` and `SkeletonUtils.js`

The import map in `diplomind/ui.html` maps the upstream `three` imports to these files. The two core build files are minified with Terser 5.44.0 using standard safe compression/mangling, preserving function/class names and license comments. The module imports/re-exports its minified core sibling. Addon sources are unchanged. Unminified originals were verified byte-for-byte against the pinned official package. No runtime CDN requests are introduced.

Original sources: https://unpkg.com/three@0.186.1/build/three.core.js and https://unpkg.com/three@0.186.1/build/three.module.js.

Reproduce with `npm exec --yes --package=terser@5.44.0 -- terser INPUT --module --compress --mangle --keep-classnames --keep-fnames --comments '/@license|@preserve|^!/' --output OUTPUT`, then change both `./three.core.js` references in the module to `./three.core.min.js`. Full MIT terms remain in `THREE-LICENSE.txt`.
