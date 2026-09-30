"""Round-trip load every exported GLB and verify its browser asset contract.

Run with: blender --background --python assets/blender/validate_assets.py
"""

import json
import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "diplomind" / "static" / "assets"
manifest = json.loads((OUT / "manifest.json").read_text())
results = {}
for name, asset in manifest["assets"].items():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Keep names stable across imports for the material contract check.
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)
    path = OUT / asset["file"]
    assert path.stat().st_size == asset["bytes"], f"{name}: byte count mismatch"
    assert path.stat().st_size < 300_000, f"{name}: exceeds per-model budget"
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert meshes, f"{name}: missing mesh"
    assert not any(o.type in ("LIGHT", "CAMERA") for o in bpy.context.scene.objects)
    materials = {m.name for o in meshes for m in o.data.materials}
    assert "Nation" in materials, f"{name}: missing Nation tint slot"
    points = [o.matrix_world @ Vector(v.co) for o in meshes for v in o.data.vertices]
    assert all(math.isfinite(c) for p in points for c in p), f"{name}: invalid coordinates"
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    # Blender's importer converts glTF Y-up back to Z-up automatically.
    assert abs(lo[2]) < 1e-5, f"{name}: does not sit on ground"
    assert abs(lo[0] + hi[0]) < 1e-5 and abs(lo[1] + hi[1]) < 1e-5, f"{name}: off-center"
    actual_size = [hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]]
    assert all(abs(a - b) < 2e-5 for a, b in zip(actual_size, asset["size"])), f"{name}: bounds differ"
    triangles = 0
    for obj in meshes:
        obj.data.calc_loop_triangles()
        triangles += len(obj.data.loop_triangles)
        assert all(math.isfinite(c) for face in obj.data.polygons for c in face.normal)
    assert triangles == asset["triangles"], f"{name}: triangle count changed"
    results[name] = {"status": "PASS", "bytes": path.stat().st_size,
                     "triangles": triangles, "meshObjects": len(meshes),
                     "gltfSizeXYZ": [round(v, 5) for v in actual_size],
                     "materials": sorted(materials)}

report = {"status": "PASS", "validation": "Blender glTF importer round-trip",
          "blender": bpy.app.version_string, "assets": results,
          "combinedBytes": sum(a["bytes"] for a in results.values())}
(ROOT / "assets" / "blender" / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
print("DIPLOMIND_ASSET_VALIDATION " + json.dumps(report))
