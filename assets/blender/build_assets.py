"""Build DiploMind's original tabletop pieces with Blender 4.3+.

    blender --background --python assets/blender/build_assets.py
    blender --background --python assets/blender/build_assets.py -- --skip-preview

No third-party assets, add-ons, textures, network access, or GPU are required.
Authoring: Z up / -Y forward. Export: glTF Y up / +Z forward, ground Y=0.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "diplomind" / "static" / "assets"
SOURCE = ROOT / "assets" / "blender"
PALETTE = {
    "AUSTRIA": "#C34E50",
    "ENGLAND": "#314E72",
    "FRANCE": "#538ABF",
    "GERMANY": "#697078",
    "ITALY": "#4B8C70",
    "RUSSIA": "#A080AC",
    "TURKEY": "#CCA65B",
}


def srgb(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def material(name, color, metallic=0.0, roughness=0.4):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    rgba = tuple(srgb(int(color[i:i + 2], 16) / 255) for i in (1, 3, 5)) + (1.0,)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = rgba
    return mat


def assign(obj, mat, bevel=0.0):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new("Crafted edge", "BEVEL")
        mod.width = bevel
        mod.segments = 1
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def cube(name, location, scale, mat, bevel=0.015, rotation=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    if rotation:
        obj.rotation_euler = rotation
    return assign(obj, mat, bevel)


def cylinder(name, location, radius, depth, mat, vertices=24, rotation=None, bevel=0.01):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    if rotation:
        obj.rotation_euler = rotation
    return assign(obj, mat, bevel)


def cone(name, location, radius1, radius2, depth, mat, vertices=24, rotation=None, bevel=0.0):
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius1, radius2=radius2,
                                 depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    if rotation:
        obj.rotation_euler = rotation
    return assign(obj, mat, bevel)


def extruded_polygon(name, points, z0, z1, mat, bevel=0.01):
    n = len(points)
    vertices = [(x, y, z0) for x, y in points] + [(x, y, z1) for x, y in points]
    faces = [tuple(reversed(range(n))), tuple(range(n, n * 2))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return assign(obj, mat, bevel)


def join_pieces(name, pieces):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in pieces:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.data.calc_loop_triangles()
    return obj


def army(m):
    nation, brass, ivory, ink = m
    parts = [
        cylinder("Army · brass foot", (0, 0, .025), .475, .05, brass, 48),
        cylinder("Army · national enamel", (0, 0, .064), .455, .064, nation, 48),
        cylinder("Army · top plate", (0, 0, .103), .405, .022, ivory, 48, bevel=.006),
        # Two splayed carriage trails identify this as a historic field gun.
        cube("Army · left trail", (-.145, .135, .152), (.07, .47, .075), nation,
             rotation=(0, 0, -.18)),
        cube("Army · right trail", (.145, .135, .152), (.07, .47, .075), nation,
             rotation=(0, 0, .18)),
        cube("Army · breech support", (0, -.04, .265), (.17, .22, .2), nation),
        cylinder("Army · axle", (0, -.015, .265), .038, .6, brass, 16,
                 rotation=(0, math.pi / 2, 0), bevel=.005),
    ]
    for x in (-.255, .255):
        # Solid inset wheels read at gameplay scale; no fragile spoked geometry.
        parts += [
            cylinder("Army · tire", (x, -.015, .278), .16, .075, ink, 24,
                     rotation=(0, math.pi / 2, 0), bevel=.009),
            cylinder("Army · wheel face", (x + math.copysign(.044, x), -.015, .278),
                     .129, .018, brass, 24, rotation=(0, math.pi / 2, 0), bevel=.004),
            cylinder("Army · hub", (x + math.copysign(.06, x), -.015, .278),
                     .045, .024, nation, 16, rotation=(0, math.pi / 2, 0), bevel=.004),
        ]
    parts += [
        cone("Army · barrel", (0, -.12, .415), .064, .087, .52, brass, 24,
             rotation=(math.pi / 2 + .13, 0, 0), bevel=.004),
        cylinder("Army · breech", (0, .136, .382), .091, .066, nation, 24,
                 rotation=(math.pi / 2 + .13, 0, 0), bevel=.007),
        cylinder("Army · muzzle band", (0, -.365, .447), .079, .038, brass, 24,
                 rotation=(math.pi / 2 + .13, 0, 0), bevel=.004),
        cylinder("Army · muzzle opening", (0, -.386, .45), .046, .004, ink, 24,
                 rotation=(math.pi / 2 + .13, 0, 0), bevel=0),
    ]
    return join_pieces("Army", parts)


def fleet(m):
    nation, brass, ivory, ink = m
    # The hull points toward -Y in Blender, +Z in the browser.
    hull = [(-.09, -.5), (-.205, -.255), (-.205, .30), (-.15, .45),
            (.15, .45), (.205, .30), (.205, -.255), (.09, -.5)]
    # Use consistent positive winding for clear exterior normals.
    hull.reverse()
    parts = [
        extruded_polygon("Fleet · hull", hull, .052, .15, nation, .017),
        extruded_polygon("Fleet · waterline", hull, .015, .057, ink, .006),
        extruded_polygon("Fleet · brass rail", [(x * .96, y * .96) for x, y in hull], .15, .177, brass, .006),
        extruded_polygon("Fleet · ivory deck", [(x * .86, y * .92) for x, y in hull], .177, .189, ivory, .004),
        cube("Fleet · superstructure", (0, .014, .245), (.225, .39, .125), nation),
        cube("Fleet · bridge", (0, -.092, .334), (.25, .13, .075), ivory, .009),
        cube("Fleet · bridge roof", (0, -.092, .379), (.265, .148, .022), brass, .004),
        cube("Fleet · bridge glazing", (0, -.16, .34), (.195, .005, .025), ink, .001),
    ]
    for y in (.032, .155):
        parts += [
            cylinder("Fleet · funnel", (0, y, .368), .043, .20, brass, 16, bevel=.005),
            cylinder("Fleet · funnel crown", (0, y, .468), .047, .028, ink, 16, bevel=.003),
        ]
    for y in (-.31, .329):
        parts += [
            cylinder("Fleet · turret", (0, y, .231), .073, .076, nation, 12, bevel=.007),
            cube("Fleet · gun", (0, y - .079, .244), (.032, .18, .032), brass, .005),
        ]
    return join_pieces("Fleet", parts)


def center(m):
    nation, brass, ivory, ink = m
    parts = [
        cylinder("Center · foot", (0, 0, .026), .40, .052, brass, 6, bevel=.012),
        cylinder("Center · national enamel", (0, 0, .072), .37, .046, nation, 6, bevel=.009),
        cube("Center · keep", (0, 0, .17), (.33, .30, .16), ivory, .012),
        cube("Center · gate", (0, -.154, .151), (.086, .006, .094), ink, .002),
        cube("Center · roof", (0, 0, .26), (.35, .32, .035), brass, .006),
    ]
    for x in (-.155, .155):
        for y in (-.14, .14):
            parts += [
                cylinder("Center · tower", (x, y, .228), .059, .235, ivory, 12, bevel=.006),
                cylinder("Center · crown", (x, y, .352), .068, .027, brass, 12, bevel=.004),
            ]
    return join_pieces("Center", parts)


def compass(m):
    nation, brass, ivory, ink = m
    parts = [
        cylinder("Compass · rim", (0, 0, .032), .5, .064, brass, 48, bevel=.01),
        cylinder("Compass · face", (0, 0, .071), .459, .027, ink, 48, bevel=.005),
        cylinder("Compass · inner disc", (0, 0, .088), .352, .01, ivory, 48, bevel=.002),
    ]
    for i in range(8):
        angle = i * math.pi / 4
        radius = .315 if i % 2 == 0 else .232
        # Disjoint wedges meet at the center: no coplanar overlaps or z-fighting.
        p = [(0, 0), (.029, .07), (0, radius), (-.029, .07)]
        points = [(x * math.cos(angle) - y * math.sin(angle),
                   x * math.sin(angle) + y * math.cos(angle)) for x, y in p]
        parts.append(extruded_polygon("Compass · rose", points, .095, .105,
                                      brass if i % 2 == 0 else nation, 0))
    for i in range(32):
        angle = i * math.pi / 16
        parts.append(cube("Compass · graduation", (.417 * math.sin(angle), .417 * math.cos(angle), .088),
                          (.007, .043 if i % 4 == 0 else .024, .006), brass, 0,
                          rotation=(0, 0, -angle)))
    parts.append(cylinder("Compass · pin", (0, 0, .119), .026, .033, brass, 16, bevel=.004))
    return join_pieces("BoardProp", parts)


def bounds(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = [min(c[i] for c in corners) for i in range(3)]
    hi = [max(c[i] for c in corners) for i in range(3)]
    return lo, hi


def normalize(obj):
    lo, hi = bounds(obj)
    diameter = max(hi[0] - lo[0], hi[1] - lo[1])
    for vertex in obj.data.vertices:
        vertex.co.x = (vertex.co.x - (hi[0] + lo[0]) / 2) / diameter
        vertex.co.y = (vertex.co.y - (hi[1] + lo[1]) / 2) / diameter
        vertex.co.z = (vertex.co.z - lo[2]) / diameter
    obj.data.update()
    bpy.context.view_layer.update()


def export_asset(name, obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=str(OUT / f"{name}.glb"), export_format="GLB",
                              use_selection=True, export_yup=True, export_apply=True,
                              export_extras=True, export_cameras=False, export_lights=False,
                              export_texcoords=False, export_normals=True,
                              export_materials="EXPORT", export_animations=False)
    lo, hi = bounds(obj)
    obj.data.calc_loop_triangles()
    # Blender z becomes GLTF y; Blender -y becomes GLTF z.
    return {
        "file": f"{name}.glb", "node": obj.name,
        "bytes": (OUT / f"{name}.glb").stat().st_size,
        "triangles": len(obj.data.loop_triangles),
        "size": [round(hi[0] - lo[0], 5), round(hi[2] - lo[2], 5), round(hi[1] - lo[1], 5)],
        "origin": "ground-center", "tintMaterial": "Nation",
    }


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def area_light(name, location, energy, size, color):
    data = bpy.data.lights.new(name, "AREA")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    data.energy, data.size, data.color = energy, size, color
    look_at(obj, (0, 0, 0))


def copy_piece(obj, name, location, scale=1, tint=None, rotation=0):
    new = obj.copy()
    new.data = obj.data.copy()
    new.name = name
    bpy.context.collection.objects.link(new)
    new.location = location
    new.scale = (scale, scale, scale)
    new.rotation_euler.z = rotation
    new.hide_render = False
    if tint:
        for slot in new.material_slots:
            if slot.material.name == "Nation":
                slot.material = tint
    return new


def preview_scene(objects, materials):
    preview = bpy.data.collections.new("Presentation · editable product scene")
    bpy.context.scene.collection.children.link(preview)
    layer = bpy.context.view_layer.layer_collection.children[preview.name]
    bpy.context.view_layer.active_layer_collection = layer
    stone = material("Preview · limestone", "#E0D9CB", roughness=.66)
    felt = material("Preview · deep petrol", "#193D41", roughness=.88)
    walnut = material("Preview · walnut", "#302B29", roughness=.46)
    cube("Presentation table", (0, 0, -.26), (8.2, 6.2, .42), walnut, .12)
    cube("Presentation felt", (0, 0, -.035), (7.86, 5.86, .035), felt, .06)
    # Raised pale slabs and a carefully limited lighting rig give readable silhouettes.
    for x, key, color in ((-1.48, "army", "#C34E50"), (1.48, "fleet", "#538ABF")):
        cylinder("Hero plinth", (x, -.83, .056), 1.01, .15, stone, 64, bevel=.025)
        tint = material(f"Preview · hero {key}", color, .24, .30)
        copy_piece(objects[key], f"Hero · {key}", (x, -.83, .133), 1.72, tint, -.24)
    copy_piece(objects["center"], "Hero · supply center", (-.6, 1.11, .01), 1.12,
               material("Preview · supply", "#4B8C70", .24, .30))
    copy_piece(objects["board-prop"], "Hero · compass", (.73, 1.14, .012), 1.12)
    for idx, (power, hex_color) in enumerate(PALETTE.items()):
        tint = material(f"Preview · {power}", hex_color, .24, .30)
        x = (idx - 3) * .78
        copy_piece(objects["army"], f"Nation · {power}", (x, 2.27, .012), .58, tint, -.12)
    # Typography is baked only into this inspectable presentation scene, not game assets.
    def label(text, location, size, mat):
        data = bpy.data.curves.new("Engraving", "FONT")
        data.body, data.size, data.align_x = text, size, "CENTER"
        data.extrude = .0005
        obj = bpy.data.objects.new(text, data)
        preview.objects.link(obj)
        obj.location = location
        data.materials.append(mat)
    label("D I P L O M I N D", (0, -2.43, -.011), .20, materials[1])
    label("ARMY", (-1.48, -1.99, -.011), .125, materials[2])
    label("FLEET", (1.48, -1.99, -.011), .125, materials[2])
    camera_data = bpy.data.cameras.new("Asset review camera")
    camera = bpy.data.objects.new("Asset review camera", camera_data)
    preview.objects.link(camera)
    camera.location = (6.1, -10.8, 10.9)
    look_at(camera, (0, .02, .03))
    camera_data.type, camera_data.ortho_scale = "ORTHO", 9.15
    bpy.context.scene.camera = camera
    area_light("Key · warm softbox", (-3, -4, 8), 1500, 5, (1, .89, .75))
    area_light("Fill · cool softbox", (4, 1, 6), 1200, 4, (.72, .84, 1))
    area_light("Edge · overhead", (-1, 5, 6), 1600, 3, (1, .95, .84))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-preview", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    OUT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for material_block in list(bpy.data.materials):
        bpy.data.materials.remove(material_block)
    source = bpy.data.collections.new("GAME ASSETS · ground-centered Z-up sources")
    bpy.context.scene.collection.children.link(source)
    bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[source.name]
    mats = [material("Nation", "#D7D7D7", .24, .31),
            material("Brass", "#C6A56C", .68, .31),
            material("Ivory", "#EAE2CA", .06, .43),
            material("Ink", "#27383C", .12, .48)]
    builders = {"army": army, "fleet": fleet, "center": center, "board-prop": compass}
    objects, manifest = {}, {}
    for key, builder in builders.items():
        obj = builder(mats)
        normalize(obj)
        obj["asset_kind"] = key
        obj["authoring"] = "Original procedural model authored in Blender for DiploMind"
        obj["tint_material"] = "Nation"
        obj["forward"] = "-Y Blender / +Z glTF"
        manifest[key] = export_asset(key, obj)
        objects[key] = obj
        obj.hide_render = True
    payload = {
        "generator": f"Blender {bpy.app.version_string}",
        "coordinateSystem": {"up": "+Y", "forward": "+Z", "ground": "Y=0"},
        "palette": PALETTE, "assets": manifest,
        "license": "Original project assets, AGPL-3.0-or-later; no external asset dependencies",
    }
    (OUT / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n")
    preview_scene(objects, mats)
    source.hide_viewport = True
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 160
    # Some official distro builds omit OpenImageDenoise; keep the CPU path portable.
    scene.cycles.use_denoising = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 6
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(SOURCE / "asset-preview.png")
    scene.world.color = (.16, .16, .16)
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = False
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE / "diplomind.blend"), compress=True)
    if not args.skip_preview:
        bpy.ops.render.render(write_still=True)
    print("DIPLOMIND_ASSETS " + json.dumps(payload))


if __name__ == "__main__":
    main()
