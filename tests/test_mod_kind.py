"""Showrunner Refmods Integration -- mod_kind.

A mod's kind decides whether its prompt label is <Picture N> or <Video N>,
*and* which sequence its number is counted on, so it has to be the answer the
plugin that injects the mod would give:

  * the fork reclassifies a stack of stills saved as kind "video" and injects
    it as pictures, and exposes that rule as storage.is_still_stack;
  * g3n3rativ3's original has no such function and goes by the stored kind.

Two bugs are covered here, both seen in real renders:

  1. A missing is_still_stack raised inside the same try that read the kind,
     so with the original plugin every video mod came back "image".
  2. The plugins load in no fixed order. A mod asked about before the Refmods
     plugin was importable fell back to "image" AND that was cached for the
     session, so a video mod was numbered on the picture sequence -- which is
     how a real render asked for <Video 2> with only one video reference in it.
"""
import json, os, pathlib, struct, sys, tempfile, types

ADDON = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADDON.parent))  # the folder holding the plugin

pkg = types.ModuleType("srefmods")
pkg.__path__ = [str(ADDON)]
sys.modules["srefmods"] = pkg
from srefmods import patch  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        FAILS.append(name)


# Real metadata, copied from the mods in the user's own folder.
MODS = {
    "Siren_Picture": {"kind": "image", "latent_t": 1, "tags": ["1 img, 0 vid"], "source": "image"},
    "Siren_Stack": {"kind": "image", "latent_t": 19, "tags": ["19 img, 0 vid"], "source": "stack"},
    "Elizabeth_Olsen": {"kind": "video", "latent_t": 27, "tags": ["0 img, 1 vid", "with soundtrack"],
                        "source": "video"},
    # What ComfyUI writes for stacked stills: kind "video", source "stack",
    # and only the tags say there was no real video in it.
    "Comfy_Stack": {"kind": "video", "latent_t": 20, "tags": ["20 img, 0 vid"], "source": "stack"},
    "eolsen_aud": {"kind": "audio", "latent_t": 159, "tags": ["audio"], "source": "audio"},
}

# A mods folder on disk, written as safetensors headers, for the fallback.
ROOT = tempfile.mkdtemp(prefix="refmods-")
for mod_name, blob in MODS.items():
    header = json.dumps({"__metadata__": {"refmod_meta": json.dumps(blob)},
                         "latent": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
    with open(os.path.join(ROOT, mod_name + ".safetensors"), "wb") as fh:
        fh.write(struct.pack("<Q", len(header)) + header + b"\0\0\0\0")
# One with its metadata in a sidecar instead, and one that is unreadable.
with open(os.path.join(ROOT, "Sidecar_Mod.json"), "w") as fh:
    json.dump({"kind": "video", "latent_t": 30, "source": "video"}, fh)
open(os.path.join(ROOT, "Sidecar_Mod.safetensors"), "wb").close()
with open(os.path.join(ROOT, "Broken_Mod.safetensors"), "wb") as fh:
    fh.write(b"not a safetensors file at all")

patch._mods_root = lambda: ROOT     # the fallback reads here
LOG = []
patch._log = lambda message: LOG.append(str(message))


def fake_storage(name, still_stack=True, readable=True):
    module = types.ModuleType(name)
    module.refmods_dir = lambda: ROOT
    module.mod_path = lambda mod: mod
    module.list_refmods_info = lambda recursive=False: [{"name": n} for n in MODS]

    def read_refmod_meta(path):
        if not readable:
            raise RuntimeError("unreadable")
        return dict(MODS.get(path) or {})

    module.read_refmod_meta = read_refmod_meta
    if still_stack:
        def is_still_stack(kind, latent_t, tags=None, source=""):
            if int(latent_t or 1) <= 1:
                return False
            if kind == "image":
                return True
            if kind != "video" or source != "stack":
                return False
            for tag in tags or []:
                if "vid" in tag:
                    return tag.split("vid")[0].strip().endswith("0")
            return False
        module.is_still_stack = is_still_stack
    sys.modules[name] = module
    return name


def kinds():
    patch._KINDS.clear()
    return {name: patch.mod_kind(name) for name in MODS}


print("1. with the fork (is_still_stack present)")
key = fake_storage("plugins.Refmod-Fork.storage")
got = kinds()
check("a picture mod", got["Siren_Picture"], "image")
check("a stack saved as pictures", got["Siren_Stack"], "image")
check("a real video mod", got["Elizabeth_Olsen"], "video")
check("a ComfyUI stack saved as video", got["Comfy_Stack"], "image")
check("an audio mod", got["eolsen_aud"], "audio")
check("the plugin's answer is cached", patch._KINDS.get("Elizabeth_Olsen"), "video")
del sys.modules[key]

print("\n2. with the original (no is_still_stack)")
key = fake_storage("plugins.wan2gp-minimax-h3-refmod.storage", still_stack=False)
got = kinds()
check("a real video mod stays a video", got["Elizabeth_Olsen"], "video")
# The original injects by the stored kind, so a ComfyUI stack goes in as a
# video there -- and the label must say the same thing.
check("a ComfyUI stack keeps its stored kind", got["Comfy_Stack"], "video")
check("an audio mod", got["eolsen_aud"], "audio")
check("the mod list still reads", [m["name"] for m in patch.available_mods()], list(MODS))
del sys.modules[key]

print("\n3. no plugin loaded yet -- the bug that shipped in 0.8.0")
patch._KINDS.clear()
check("a video mod is still a video", patch.mod_kind("Elizabeth_Olsen"), "video")
check("a picture mod is still a picture", patch.mod_kind("Siren_Picture"), "image")
check("an audio mod is still audio", patch.mod_kind("eolsen_aud"), "audio")
check("metadata in a sidecar is read too", patch.mod_kind("Sidecar_Mod"), "video")
check("nothing read off disk is cached", dict(patch._KINDS), {})
# The regression itself: the answer given before the plugin loads must not
# outlive it. A ComfyUI stack is the case the two disagree on.
patch._KINDS.clear()
check("before the plugin loads, the stored kind", patch.mod_kind("Comfy_Stack"), "video")
key = fake_storage("plugins.Refmod-Fork.storage")
check("once it loads, the plugin decides", patch.mod_kind("Comfy_Stack"), "image")
check("and that answer is kept", patch._KINDS.get("Comfy_Stack"), "image")
del sys.modules[key]

print("\n4. nothing readable at all")
patch._KINDS.clear()
LOG.clear()
check("an unreadable file falls back to a picture", patch.mod_kind("Broken_Mod"), "image")
check("a mod that is not there at all", patch.mod_kind("No_Such_Mod"), "image")
check("neither is remembered", dict(patch._KINDS), {})
check("and it says so", sum(1 for line in LOG if "could not read what kind" in line), 2)
# The plugin present but its reader raising: the file on disk still answers.
key = fake_storage("plugins.Refmod-Fork.storage", readable=False)
patch._KINDS.clear()
check("plugin reader raising falls back to disk", patch.mod_kind("Elizabeth_Olsen"), "video")
del sys.modules[key]

print("\n5. the label number a real shot would get")
# One image reference of its own (the location) and no video or audio ones,
# exactly the shot that produced the bad render.
settings = {"image_refs": ["media/bar.png"], "video_prompt_type": "I", "audio_prompt_type": ""}
check("own labels", patch._own_labels(settings), {"image": 1, "video": 0, "audio": 0})
key = fake_storage("plugins.Refmod-Fork.storage")
patch._KINDS.clear()
doc = {"cast": [{"id": "c1", "name": "Elizabeth",
                 "refmod": {"mod": "Elizabeth_Olsen", "strength": 1.0, "use_audio": False}}]}
shot = {"id": "s1", "cast": ["c1"], "dialogue": [{"cast": "c1", "line": "hello handsome"}]}
payload, labelled = patch.selection_for(doc, shot, settings)
check("a video mod in the picture field is a video", labelled, [("Elizabeth", "Video", 1)])
check("and asks for <Video 1>, not 2", payload["rows"][0]["label"], 1)
del sys.modules[key]

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
    sys.exit(1)
print("all checks passed")
