# Showrunner Refmods Integration

**Version 1.0.0** · a WanGP extension plugin · repo:
https://github.com/jedsdead/Showrunner-Refmods-Integration

Gives Showrunner's cast members a **RefMod**, picked on their cast card and
applied to every shot that shows them, with the mod's `<Picture N>` label
written into that shot's prompt.

Showrunner's model of identity is "a cast member has pictures". RefMods are a
different carrier of identity that Showrunner knows nothing about, so a mod
could only be used by hand, per shot, through the Inspector's Generation
settings JSON — and the showrunner, writing prompts, never named the mod's
label, which is what makes a mod take effect at all.

## What it does

* **A RefMod on the cast card**, beside the LoRA picker: the mod, its
  strength, whether a multi-picture mod goes in as one contact sheet,
  whether its soundtrack comes with it, its max size and its copies.
* **Applied to the shots that show that member**, decided by the shot's own
  cast list — not by guessing from the prompt.
* **Audio only where there are lines.** A voice mod, and the soundtrack inside
  a visual mod, go in only on the shots where that member actually speaks. An
  audio reference is an instruction as much as a likeness: give H3 a voice and
  it finds something for that voice to say, so a silent shot is rendered
  without one.
* **Labels pinned and named.** The mods are numbered after the shot's own
  pictures (start and end frames, then its reference images), and if the
  prompt does not already name a mod's `<Picture N>`, a sentence saying who it
  is is added to the prompt's `subject_definitions` line.
* **A shot that sets `h3_refmod_state` itself always wins.** This never
  overrides a hand-written per-shot selection.
* **One mod of each kind per cast member**, picked in three lists on their
  card -- Picture, Video and Voice -- each offering only the mods of that kind.
  A member can carry all three.
* **Each mod takes the label of its own kind** -- `<Picture N>`, `<Video N>`
  or `<Audio N>` -- counted after the shot's own references of that kind.
  Showrunner itself only ever hands a template reference *images*, so without
  this a video mod would be named `<Picture N>` and the prompt would point at
  something else entirely.
* **Showrunner's directing skill is amended** so the showrunner does not make
  a master image for a cast member who has a mod (that portrait would
  otherwise take `<Picture 1>` and compete with the mod). The amendment is a
  copy: Showrunner's own file is never written to, and the copy is rebuilt
  from it at every start.
* **Render-wide settings in the plugin's own tab** -- fit to output, mods in
  phase 1 and 2, shrink method, and a max size for every mod. Those apply to
  the whole render rather than to one character, so they are not on the cast
  card; a card's own max size still wins over the default. Defaults: fit to
  output on, phase 1 fit.

Requires a RefMods plugin for the mods themselves, and MiniMax H3 — mods are
not applied to shots whose template is on another model.

### Which RefMods plugin

Either. The plugin is found by the functions it defines, not by its folder
name, and the arming itself goes through WanGP's own `h3_refmod_state` custom
setting, which both use identically.

With **Refmods For Wan GP** (the fork) every option on a cast card and in the
plugin tab takes effect. With **g3n3rativ3's MiniMax H3 RefMods** (0.43.0) the
mods go in at their strength and in order, and these fork-only options are
read but ignored, because that plugin has nothing to do with them: *its sound*
(a soundtrack carried inside a visual mod), *one picture* (contact sheet) and
send-as-one-video, *max size*, the chosen label numbers, *fit to output* and
*mods in phase 2*. It does read shrink method, mods in phase 1, retention and
copies. Unknown keys are ignored rather than rejected, so nothing errors.

A mod's kind — which decides whether its label is `<Picture N>` or
`<Video N>`, *and* which sequence its number is counted on — is taken from the
mod itself, and the plugin is asked about the one case the two disagree on (a
stack of stills saved as kind "video", which the fork injects as pictures).
Only the plugin's own answer is remembered: the plugins load in no fixed
order, so a mod read off disk before the RefMods plugin is importable is
answered for that call alone and asked about again afterwards. See `mod_kind`
in `patch.py`.

Which field on the cast card a mod sits in does not change its kind. Deepy can
write any mod name into any of the three fields, so a video mod put in the
Picture field still goes in as `<Video N>` — the card's pickers filter by kind,
but Deepy does not.

## How it is done

Nothing in Showrunner's folder is changed. At startup this plugin finds
Showrunner's already-imported modules and wraps four things:

| What | Why |
| --- | --- |
| `production.CAST_FIELDS` | so `refmod` is a field Showrunner accepts, stores and versions |
| `ProductionService.with_cast_loras` | the one seam both render paths share, and the only place that knows the shot, its cast and its settings together |
| the shot's prompt | a mod reaches the model only through its label |
| `api.create_app` | the picker: two routes (its script, and the mod list) and a middleware that appends the loader to Showrunner's `app.js` -- WanGP 19.14 serves its own shell at the app root, so its `index.html` never reaches the browser |
| WanGP's plugin skill registry | the directing skill's record is pointed at an amended copy, so the showrunner stops making a master image for cast who have a mod |

Each piece is applied only if it still fits; anything that does not is skipped
with a line in the console, and the rest carries on. **Deleting this folder
removes all of it.**

The picker is the fragile half: it finds the cast card in Showrunner's own
markup and re-attaches itself when Showrunner redraws. A Showrunner update
that changes that markup would stop the picker appearing — the server side
(cast field, render wiring, prompt labels) is unaffected.

## License

MIT (see `LICENSE`) — copyright (c) 2026 jedsdead.

Every file here is original code written against WanGP's plugin API and
Showrunner's own modules: Showrunner's JavaScript is imported at runtime
rather than copied, and nothing from WanGP, Showrunner or the RefMods plugin
is reproduced in it. WanGP itself stays under the WanGP Community License 2.0,
which governs WanGP's code and not this plugin's.

MIT is deliberate rather than incidental: permissive terms are what let any
of this be reused or taken further by anyone, WanGP included.
