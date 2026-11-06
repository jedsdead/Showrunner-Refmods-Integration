"""
Showrunner Refmods Integration -- RefMods as a property of the cast, patched in from
outside Showrunner.

Nothing in Showrunner's own folder is touched. This module finds Showrunner's
already-imported modules and wraps four things:

  1. ``production.CAST_FIELDS``  -- "refmod" becomes a cast field Showrunner
     accepts, stores in the production document and versions like any other.
  2. ``ProductionService.with_cast_loras`` -- the one seam both render paths
     share (``toolbox._generation_with_loras`` for the showrunner's own
     renders, ``service.rerun`` for "Same again"). It is handed the production,
     the shot and the settings, so it knows exactly which cast members are in
     the shot -- no guessing from the prompt. The mods of those members are
     written into ``custom_settings`` for the Refmods plugin to pick up, with
     their prompt labels pinned.
  3. The shot's prompt -- a mod is useless unless the prompt names its
     ``<Picture N>``; if the showrunner didn't write one, it is added.
  4. ``ShowrunnerPlugin.create_web_app`` -- the picker on the cast card: a
     middleware adds one <script> tag to Showrunner's page, and two routes
     serve that script and the list of installed mods.

If any of those is missing or shaped differently -- a Showrunner update, say --
the piece that cannot be applied is skipped with a line in the console and
everything else carries on. Deleting this plugin's folder removes all of it.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import traceback

LOG = "[Showrunner Refmods]"
MARKER = "_showrunner_refmods_patched"
SETTING = "h3_refmod_state"          # the Refmods plugin's own custom setting
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
SCRIPT_PATH = "__refmods/cast.js"    # served beside Showrunner's own assets
MODS_PATH = "__refmods/mods"


def _log(message: str) -> None:
    print(f"{LOG} {message}", flush=True)


# ── the render-wide settings ──────────────────────────────────────────────
#
# Strength, size and the rest of a mod's own options belong to the cast member
# and live on their card. These belong to the whole render -- two cast members
# in one shot cannot each have their own -- so they are set once, in this
# plugin's tab, and written into every shot it arms. Kept beside the mods
# rather than inside this folder, so reinstalling the plugin keeps them.

DEFAULTS = {"fit_to_output": True, "phase1_mods": "fit", "phase2_mods": "full",
            "shrink_method": "reencode", "max_short": 0}
PHASE1 = ("full", "fit")
PHASE2 = ("full", "tile", "off")
SHRINK = ("reencode", "fast")


def defaults_path() -> str:
    return os.path.join(os.getcwd(), "loras", "refmods_plugin", "showrunner_defaults.json")


def defaults() -> dict:
    values = dict(DEFAULTS)
    try:
        with open(defaults_path(), encoding="utf-8") as handle:
            saved = json.load(handle)
        if isinstance(saved, dict):
            values.update({key: saved[key] for key in DEFAULTS if key in saved})
    except FileNotFoundError:
        pass
    except Exception as e:
        _log(f"could not read the saved defaults ({e!r}); using the built-in ones")
    if values.get("phase1_mods") not in PHASE1:
        values["phase1_mods"] = DEFAULTS["phase1_mods"]
    if values.get("phase2_mods") not in PHASE2:
        values["phase2_mods"] = DEFAULTS["phase2_mods"]
    if values.get("shrink_method") not in SHRINK:
        values["shrink_method"] = DEFAULTS["shrink_method"]
    return values


def save_defaults(values: dict) -> str:
    path = defaults_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: values.get(key, DEFAULTS[key]) for key in DEFAULTS}, handle, indent=2)
    return path


# ── finding the other two plugins, without importing them by name ─────────
#
# WanGP loads plugins under package names of its own choosing, so neither
# Showrunner nor the Refmods plugin can be imported by a fixed path. Both are
# already in sys.modules by the time this runs; they are found by the names
# they define rather than by where they live.

def _loaded_modules():
    """Every real module, named. Entries that are not modules are skipped:
    sys.modules holds placeholders and stand-ins too."""
    import types as _types
    for name, module in list(sys.modules.items()):
        if isinstance(module, _types.ModuleType):
            yield name, module


def _module_where(test, prefer: str):
    """The module ``test`` accepts, preferring one whose own name contains
    ``prefer``.

    ``test`` checks the shape of what it finds -- that CAST_FIELDS really is a
    set, that ProductionService really is a class -- rather than merely that
    the name exists. Some modules answer every attribute request (lazy import
    shims do), so asking hasattr() and believing the answer finds the wrong
    module and then reports Showrunner as broken, which is exactly what this
    got wrong before."""
    fallback = None
    for name, module in _loaded_modules():
        try:
            if not test(module):
                continue
        except Exception:
            continue
        if prefer in name.split("."):
            return module
        fallback = fallback or module
    return fallback


def _is_production(module) -> bool:
    return isinstance(getattr(module, "CAST_FIELDS", None), set) \
        and isinstance(getattr(module, "SHOT_FIELDS", None), set)


def _service_class(module):
    """The class that carries with_cast_loras, found by that method rather
    than by name -- Showrunner calls the class `Showrunner`, and a rename is
    likelier than the method moving off it."""
    for value in vars(module).values():
        if isinstance(value, type) and callable(getattr(value, "with_cast_loras", None)):
            return value
    return None


def _is_service(module) -> bool:
    return _service_class(module) is not None


def _is_api(module) -> bool:
    return callable(getattr(module, "create_app", None)) and hasattr(module, "WEB")


TESTS = {"production": _is_production, "service": _is_service, "api": _is_api}


def _showrunner_modules() -> dict:
    found = {part: _module_where(test, "showrunner") for part, test in TESTS.items()}
    # Showrunner imports its own service and api modules lazily -- api inside
    # create_web_app, so neither is loaded yet when this runs. Whichever module
    # was found names the package; the rest are imported from it by hand rather
    # than waited for, since by the time Showrunner imports api itself the page
    # is already being built.
    package = next((module.__name__.rsplit(".", 1)[0] for module in found.values()
                    if module is not None and "." in module.__name__), None)
    if package:
        import importlib
        for part, test in TESTS.items():
            if found[part] is not None:
                continue
            try:
                module = importlib.import_module(f"{package}.{part}")
            except Exception as e:
                _log(f"could not import {package}.{part} ({e!r})")
                continue
            found[part] = module if test(module) else None
            if found[part] is None:
                _log(f"{package}.{part} is not shaped as expected; skipping that part")
    for part, module in found.items():
        if module is not None:
            _log(f"found Showrunner's {part} as {module.__name__}")
    return {name: module for name, module in found.items() if module is not None}


def _refmod_storage():
    """The Refmods plugin's own storage module, when it is installed."""
    return _module_where(lambda module: all(callable(getattr(module, name, None))
                                            for name in ("list_refmods_info", "refmods_dir", "mod_path")),
                         "Refmod-Fork")


def _mods_root() -> str:
    """The folder H3 mods live in: the Refmods plugin's own answer when it can
    be asked, and the standard location otherwise."""
    storage = _refmod_storage()
    if storage is not None:
        try:
            root = storage.refmods_dir()
            if root and os.path.isdir(root):
                return root
        except Exception:
            pass
    return os.path.join(os.getcwd(), "loras", "refmods_plugin", "minimax_h3")


def _meta_from_disk(name: str) -> dict:
    """A mod's metadata read out of the file itself, for when the Refmods
    plugin cannot be reached. Its own reader is the preferred route; this
    exists so that the order the plugins happen to load in cannot decide a
    mod's kind. A safetensors file starts with the header's length as eight
    little-endian bytes, then that much JSON, with the mod's metadata as a
    JSON string under "__metadata__"."""
    base = os.path.join(_mods_root(), *str(name).split("/"))
    try:
        with open(base + ".safetensors", "rb") as handle:
            length = struct.unpack("<Q", handle.read(8))[0]
            if not 0 < length <= 64 * 1024 * 1024:
                return {}
            header = json.loads(handle.read(length).decode("utf-8"))
        for value in (header.get("__metadata__") or {}).values():
            if not isinstance(value, str) or not value.lstrip().startswith("{"):
                continue
            try:
                blob = json.loads(value)
            except Exception:
                continue
            if isinstance(blob, dict) and blob.get("kind"):
                return blob
    except Exception:
        pass
    try:                       # some mods keep their metadata in a sidecar
        with open(base + ".json", encoding="utf-8") as handle:
            blob = json.load(handle)
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


def available_mods() -> list:
    """Installed H3 mods as [{"name", "kind", "pictures"}]. Read through the
    Refmods plugin when it is there, and straight off disk when it is not, so
    the picker still works if the plugins load in an unexpected order."""
    storage = _refmod_storage()
    mods = []
    if storage is not None:
        try:
            for info in storage.list_refmods_info(recursive=True):
                mods.append({"name": info["name"], "kind": mod_kind(info["name"])})
            return mods
        except Exception:
            _log("could not list mods through the Refmods plugin; reading the folder instead")
    root = _mods_root()
    for folder, _, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(".safetensors"):
                relative = os.path.relpath(os.path.join(folder, name), root)
                name = relative.replace(os.sep, "/")[: -len(".safetensors")]
                mods.append({"name": name, "kind": mod_kind(name)})
    return mods


def _mod_capable(model_type: str) -> bool:
    """Whether mods apply to a shot's model. The Refmods plugin's own answer
    when it can be asked, a MiniMax H3 prefix check otherwise."""
    patches = _module_where(
        lambda module: callable(getattr(module, "is_minimax_h3_refmod_capable", None))
        and isinstance(getattr(module, "SETTING_GENERATE", None), str), "Refmod-Fork")
    if patches is not None:
        try:
            return bool(patches.is_minimax_h3_refmod_capable(model_type))
        except Exception:
            pass
    return str(model_type or "").startswith("minimax_h3")


# ── the cast's mods, on the shots that show them ──────────────────────────

# One mod of each kind per cast member: their look, their motion, their voice.
# "refmod" keeps its old name so cards saved before this still work -- what
# goes in it is read by the mod's own kind, not by which field holds it.
CAST_MOD_FIELDS = ("refmod", "refmod_video", "refmod_audio")

_KINDS = {}


def mod_kind(name: str) -> str:
    """"image", "video" or "audio" for a mod. A mod decides which label it
    takes -- a video mod is <Video N>, not <Picture N> -- and getting that
    wrong points the prompt at something else entirely, so this has to be the
    answer the plugin that will inject the mod would give, not a guess.

    The mod's stored ``kind`` is that answer, with one exception: a picture
    stack saved as kind "video" (what some extractors write for stacked
    stills). The fork reclassifies those and injects them as pictures, and
    exposes the rule as ``storage.is_still_stack``; so it is asked when it is
    there. A plugin without that function -- g3n3rativ3's original -- goes by
    the stored kind, and there the stored kind is already right. Either way
    the stored kind survives: a plugin that cannot be asked must not collapse
    every video mod to a picture.

    Only the plugin's own answer is remembered. The plugins load in no fixed
    order, so a mod asked about before the Refmods plugin is importable used
    to be filed as a picture and stay that way for the whole session -- which
    put a video mod's label on the picture sequence and numbered it from
    there. Now a mod read off disk, or one that could not be read at all, is
    answered for this call only and asked about again next time, by which
    point the plugin is there to settle it."""
    if name in _KINDS:
        return _KINDS[name]
    storage = _refmod_storage()
    meta = {}
    if storage is not None:
        try:
            meta = storage.read_refmod_meta(storage.mod_path(name)) or {}
        except Exception:
            meta = {}
    if not meta:
        meta = _meta_from_disk(name)
    kind = str(meta.get("kind") or "")
    still_stack = getattr(storage, "is_still_stack", None) if storage is not None else None
    if kind == "video" and callable(still_stack):
        try:
            if still_stack("video", int(meta.get("latent_t", 1) or 1),
                           meta.get("tags"), meta.get("source", "")):
                kind = "image"
        except Exception:
            pass
    if kind not in LABEL_WORDS:
        _log(f"could not read what kind of mod {name!r} is; treating it as a picture "
             f"this once, and asking again next time")
        return "image"
    if storage is not None:
        _KINDS[name] = kind
    return kind


LABEL_WORDS = {"image": "Picture", "video": "Video", "audio": "Audio"}


def _own_labels(settings: dict) -> dict:
    """How many labels of each kind the shot's own inputs take before the mods."""
    references = settings.get("image_refs") or []
    pictures = (1 if settings.get("image_start") or settings.get("video_source") else 0) \
        + (1 if settings.get("image_end") else 0) \
        + (len(references) if isinstance(references, list) else 0)
    videos = sum(1 for key in ("video_guide", "video_guide2", "video_guide3") if settings.get(key))
    audio = sum(1 for key in ("audio_guide", "audio_guide2", "audio_guide3") if settings.get(key))
    return {"image": pictures, "video": videos, "audio": audio}


def _number(value) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _member_mod(member: dict, field: str = "refmod") -> dict | None:
    """A cast member's mod entry, as the cast card saves it. ``field`` picks
    the visual mod or the separate audio one."""
    mod = member.get(field)
    if not isinstance(mod, dict) or not mod.get("mod"):
        return None
    return mod


def _has_lines(shot: dict, member: dict) -> bool:
    """Does this shot give this member something to say?"""
    return any(line.get("speaker") == member.get("id") for line in shot.get("dialogue") or [])


def selection_for(doc: dict, shot: dict, settings: dict) -> tuple[dict | None, list]:
    """(the selection payload, [(member name, label)]) for the cast members a
    shot shows, or (None, []) when none of them has a mod."""
    cast = shot.get("cast") or []
    members = [member for member in doc.get("cast") or [] if member.get("id") in cast]
    settings_wide = defaults()
    counts = _own_labels(settings)
    rows, labelled, silent = [], [], []
    for member in members:
        who = str(member.get("name") or member.get("id"))
        # An audio reference is an instruction as much as a likeness: give H3 a
        # voice and it finds something for that voice to say. A member's voice
        # mod, and the soundtrack inside a visual mod, go in only on the shots
        # where this member actually has lines; elsewhere they are left out and
        # the shot keeps the sound the model would have made anyway.
        speaks = _has_lines(shot, member)
        for field in CAST_MOD_FIELDS:
            mod = _member_mod(member, field)
            if mod is None:
                continue
            audio_only = field == "refmod_audio"
            if audio_only and not speaks:
                silent.append(who)
                continue
            kind = "audio" if audio_only else mod_kind(str(mod["mod"]))
            counts[kind] = counts.get(kind, 0) + 1
            label = counts[kind]
            row = {"mod": str(mod["mod"]), "strength": float(mod.get("strength", 1.0) or 1.0),
                   "label": label}
            if not audio_only:
                # the visual mod's own soundtrack, when the card asks for it
                row["use_audio"] = bool(mod.get("use_audio", False)) and speaks
                if row["use_audio"]:
                    counts["audio"] = counts.get("audio", 0) + 1
                    row["audio_label"] = counts["audio"]
                if mod.get("sheet") and kind == "image":
                    row["send_as"] = "sheet"   # several pictures in one <Picture N>
                cap = _number(mod.get("max_short")) or _number(settings_wide.get("max_short"))
                if cap:
                    row["max_short"] = int(cap)
                copies = int(_number(mod.get("copies")) or 1)
                if copies > 1:
                    row["copies"] = min(10, copies)
            rows.append(row)
            labelled.append((who, LABEL_WORDS.get(kind, "Picture"), label))
    if silent:
        _log(f"{shot.get('id')}: no lines for {', '.join(sorted(set(silent)))} in this shot, so "
             f"their voice stays out of it")
    if not rows:
        return None, []
    return {"rows": rows, "fit_to_output": bool(settings_wide["fit_to_output"]),
            "phase1_mods": settings_wide["phase1_mods"], "phase2_mods": settings_wide["phase2_mods"],
            "shrink_method": settings_wide["shrink_method"]}, labelled


def with_labels(prompt: str, labelled: list) -> str:
    """The prompt, with each mod's label named in it. A mod only reaches the
    model's attention through its label, so a prompt that never mentions it
    wastes it -- and the showrunner, which knows nothing about mods, writes
    such prompts by default. Anything already naming the label is left alone."""
    text = str(prompt or "")
    missing = [(f"{name}'s voice is <Audio {label}>." if word == "Audio"
                else f"{name} is <{word} {label}>.")
               for name, word, label in labelled if f"<{word} {label}>" not in text]
    if not missing:
        return text
    addition = " ".join(missing)
    lines = text.splitlines()
    for index, line in enumerate(lines):       # H3's own prompt shape, when the showrunner used it
        if line.strip().lower().startswith("subject_definitions:"):
            lines[index] = line.rstrip() + " " + addition
            return "\n".join(lines)
    return (addition + "\n" + text) if text else addition


def _install_cast_field(production) -> None:
    fields = getattr(production, "CAST_FIELDS", None)
    if not isinstance(fields, set):
        _log("Showrunner's cast fields are not a set any more; the picker cannot save. Skipped.")
        return
    fields.update(CAST_MOD_FIELDS)
    _log(f"{', '.join(repr(name) for name in CAST_MOD_FIELDS)} added to Showrunner's cast fields")


def _install_render_hook(service) -> None:
    owner = _service_class(service)
    original = getattr(owner, "with_cast_loras", None) if owner is not None else None
    if original is None:
        _log("Showrunner has no with_cast_loras to hook; mods will not be applied. Skipped.")
        return
    if getattr(original, MARKER, False):
        return

    def with_cast_loras(self, doc, shot, entry, settings):
        result = original(self, doc, shot, entry, settings)
        try:
            settings_out, base = result if isinstance(result, tuple) else (result, None)
            if entry is None or not _mod_capable((entry or {}).get("model_type")):
                return settings_out, base
            selection, labelled = selection_for(doc, shot, settings_out)
            if selection is None:
                return settings_out, base
            custom = dict(settings_out.get("custom_settings") or {})
            if custom.get(SETTING):
                return settings_out, base   # the shot sets its own; leave it alone
            custom[SETTING] = json.dumps(selection)
            settings_out = {**settings_out, "custom_settings": custom,
                            "prompt": with_labels(settings_out.get("prompt"), labelled)}
            _log(f"{shot.get('id')}: "
                 + ", ".join(f"{name} -> <{word} {label}>" for name, word, label in labelled))
            return settings_out, base
        except Exception:
            _log("could not attach the cast's mods to this shot:\n" + traceback.format_exc())
            return result

    setattr(with_cast_loras, MARKER, True)
    with_cast_loras.__wrapped__ = original
    owner.with_cast_loras = with_cast_loras
    _log(f"hooked {owner.__name__}.with_cast_loras: the cast's mods go on the shots that show them")


APPENDIX = """

## Reference mods

Some cast members carry a **reference mod**: a saved reference, picked on their
cast card, that holds their likeness (and sometimes their voice). It is a real
reference, the same as a picture handed to the model, and it is attached to
every shot whose cast lists them -- automatically, by the plugin, when the shot
renders. You neither attach it nor see it in the settings.

What this changes for you:

- **A member with a reference mod already has identity. Do not make a master
  image for them**, and do not ask the user for pictures of them: the mod is
  the picture. Make a master only for members that have no mod.
- Their shots still use a template that takes references.
- **A mod is not always a picture.** A member can carry one of each kind, and
  each takes the label of its own kind, after the shot's own references of
  that kind:
  - a picture mod is `<Picture N>` -- their likeness;
  - a video mod is `<Video N>` -- their likeness in motion, and the right one
    to name when the shot is about how they move;
  - an audio mod is `<Audio N>` -- their voice.
  So do not assume `<Picture N>`: a member with a video mod is named
  `<Video N>` in that shot's prompt, and one with both is named twice.
- The plugin writes the missing sentence into the prompt itself if you have
  not named a mod, so write the shot normally; when you do name one, use the
  kind it is.
- Do not record or write a voice sample for a member who has an audio mod.
  Their voice mod is used only in the shots where they have lines: a shot in
  which they are present but silent is rendered without it, so write such a
  shot as you normally would and do not give them a line to "activate" it.
- A place (role "place") can carry a mod too, and then needs no set picture.

Everything else about planning, templates, shooting and the edit is unchanged.
"""


_SKILL_SOURCE = {}


def _install_skill(module) -> None:
    """Showrunner's directing skill tells the showrunner to make a master image
    for anyone without a picture, so Deepy makes a portrait that then competes
    with the cast member's mod for <Picture 1>. That instruction is text, not
    code, so the fix is text: WanGP records each plugin skill's SKILL.md path
    and reads it afresh every time, so pointing that record at an amended copy
    adds a section without touching Showrunner's own file. The copy is rebuilt
    from the original at every start, so a Showrunner update is picked up."""
    import dataclasses
    from pathlib import Path

    skills = getattr(module, "_ACTIVE_DEEPY_SKILLS", None)
    # Where the real SKILL.md was, in case this runs twice in one process: the
    # record then points at our copy, and the copy must not become the source.
    if not isinstance(skills, dict):
        _log("WanGP's skill registry was not found; the showrunner will keep making a master "
             "image for cast who have a mod.")
        return
    for uri, skill in list(skills.items()):
        path = Path(_SKILL_SOURCE.get(uri) or getattr(skill, "path", "") or "")
        if "showrunner" not in str(path).replace("\\", "/").lower() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if MARKER in text:
                return   # Showrunner itself now covers this; leave it alone
            _SKILL_SOURCE[uri] = str(path)
            amended = Path(WEB).parent / "skills" / f"{path.parent.name}.md"
            amended.parent.mkdir(parents=True, exist_ok=True)
            amended.write_text(f"{text}\n<!--{MARKER}-->{APPENDIX}", encoding="utf-8")
            skills[uri] = dataclasses.replace(skill, path=str(amended))
            _log(f"amended Showrunner's {getattr(skill, 'name', 'directing')} skill: a cast member "
                 f"with a mod needs no master image")
            return
        except Exception:
            _log("could not amend Showrunner's skill:\n" + traceback.format_exc())
            return
    _log("Showrunner's directing skill was not found in WanGP's registry; it will keep asking for "
         "a master image for cast who have a mod.")


def _install_web(api_module) -> None:
    """The picker on the cast card: one script tag, two routes.

    ``api.create_app`` is the seam, not ``ShowrunnerPlugin.create_web_app``:
    Showrunner hands WanGP a *bound method* of that at setup time
    (register_web_app(..., self.create_web_app)), so WanGP holds a reference
    taken before this plugin loads and patching the class later changes
    nothing. create_web_app imports create_app inside its own body, which
    resolves here at call time."""
    original = getattr(api_module, "create_app", None)
    if original is None:
        _log("Showrunner exposes no web app to extend; the cast picker is unavailable "
             "(the render hook still works). Skipped.")
        return
    if getattr(original, MARKER, False):
        return

    def create_app(*args, **kwargs):
        app = original(*args, **kwargs)
        try:
            from fastapi.responses import FileResponse, JSONResponse
            from starlette.middleware.base import BaseHTTPMiddleware

            @app.get("/" + MODS_PATH)
            def _mods():
                return JSONResponse({"mods": available_mods()})

            @app.get("/" + SCRIPT_PATH)
            def _script():
                return FileResponse(os.path.join(WEB, "cast.js"), media_type="text/javascript",
                                    headers={"Cache-Control": "no-cache"})

            tag = f'<script type="module" src="{SCRIPT_PATH}"></script>'
            # WanGP 19.14 serves its own shell at a plugin app's root and hosts
            # the app inside it, so Showrunner's index.html never reaches the
            # browser and a script tag there would never run. Its app.js does:
            # whatever draws the UI has to load that module. The import is
            # appended to it, with the mount's own prefix so it resolves
            # wherever WanGP mounted the app. The page injection stays for
            # builds that do serve the index.
            APP_JS = "/assets/js/app.js"

            async def inject(request, call_next):
                response = await call_next(request)
                path = request.url.path
                if response.status_code != 200:
                    return response
                kind = response.headers.get("content-type", "")
                page_request = path in ("/", "") and "text/html" in kind
                script_request = path.endswith(APP_JS) and "javascript" in kind
                if not (page_request or script_request):
                    return response
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                page = body.decode("utf-8", "replace")
                if MARKER not in page:
                    if page_request:
                        page = page.replace("</body>", f"<!--{MARKER}-->{tag}</body>", 1)
                    else:
                        prefix = request.scope.get("root_path") or ""
                        page += (f"\n/*{MARKER}*/\nimport({prefix + '/' + SCRIPT_PATH!r})"
                                 f".catch(error => console.warn('[Showrunner Refmods]', error));\n")
                data = page.encode("utf-8")
                headers = dict(response.headers)
                headers["content-length"] = str(len(data))
                from starlette.responses import Response
                return Response(content=data, status_code=response.status_code, headers=headers,
                                media_type=response.media_type)

            app.add_middleware(BaseHTTPMiddleware, dispatch=inject)
            _log("the cast cards will show a RefMod picker")
        except Exception:
            _log("could not add the cast picker (the render hook is unaffected):\n"
                 + traceback.format_exc())
        return app

    setattr(create_app, MARKER, True)
    create_app.__wrapped__ = original
    api_module.create_app = create_app
    _log("hooked Showrunner's page; the picker is added when it next loads")


def install() -> bool:
    """Apply what can be applied. True when the render hook went in, which is
    the part that makes mods actually reach a shot."""
    modules = _showrunner_modules()
    if "production" not in modules and "service" not in modules:
        _log("Showrunner was not found (is it installed and enabled?); nothing patched.")
        return False
    if "production" in modules:
        _install_cast_field(modules["production"])
    if "service" in modules:
        _install_render_hook(modules["service"])
    else:
        _log("Showrunner's service module was not found; mods will not be applied to shots.")
    registry = _module_where(
        lambda module: isinstance(getattr(module, "_ACTIVE_DEEPY_SKILLS", None), dict)
        and callable(getattr(module, "get_deepy_plugin_skill", None)), "utils")
    if registry is not None:
        _install_skill(registry)
    else:
        _log("WanGP's plugin module was not found; Showrunner's skill is unchanged.")
    if "api" in modules:
        _install_web(modules["api"])
    else:
        _log("Showrunner's api module was not found; the cast picker is unavailable "
             "(the render hook still works).")
    return "service" in modules
