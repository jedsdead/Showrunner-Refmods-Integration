"""
Showrunner Refmods Integration -- the WanGP plugin shell. Everything it does is in
patch.py; this only decides when to apply it.

Showrunner and the Refmods plugin must both be loaded first, so the patch is
applied in post_ui_setup (every plugin is imported by then) and again, harm-
lessly, the first time the Refmods tab is opened. The web half is applied by
wrapping Showrunner's own app factory, which WanGP calls later still, so it
does not matter which of the two plugins WanGP loads first.
"""

import gradio as gr
from shared.utils.plugins import WAN2GPPlugin

from . import patch

PlugIn_Name = "Showrunner Refmods Integration"
PlugIn_Id = "ShowrunnerRefMods"


class ShowrunnerRefModsPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = PlugIn_Name
        self.version = "0.7.0"
        self.description = ("RefMods on Showrunner's cast cards, applied to the shots that show "
                            "them. Patches Showrunner from outside; removing this folder undoes it.")
        self._ready = False

    def setup_ui(self):
        self.add_tab(tab_id=PlugIn_Id, label="Showrunner Refmods Integration",
                     component_constructor=self.create_ui)

    def post_ui_setup(self, components):
        self._ready = patch.install()
        return {}

    def create_ui(self, api_session=None):
        mods = patch.available_mods()
        gr.Markdown("## Showrunner Refmods Integration\n"
                    "Gives each Showrunner cast member a **RefMod**, picked on their cast card. "
                    "Every shot that shows them gets that mod, with its `<Picture N>` label "
                    "written into the shot's prompt — so the showrunner does not have to know "
                    "mods exist.\n\n"
                    "Nothing in Showrunner's own folder is changed: this plugin wraps its cast "
                    "fields, its render path and its web page at runtime. Delete this plugin's "
                    "folder and Showrunner is exactly as it was.")
        gr.Markdown(f"**State:** {'hooked into Showrunner.' if self._ready else 'not hooked — see the console at startup.'}  \n"
                    f"**Mods installed:** {len(mods)}"
                    + (" — " + ", ".join(mod["name"] for mod in mods[:12])
                       + (" …" if len(mods) > 12 else "") if mods else ""))
        values = patch.defaults()
        with gr.Accordion("Settings for every shot this plugin arms", open=True):
            gr.Markdown("A mod's own options -- strength, max size, copies, contact sheet, sound -- "
                        "are per cast member, on their card. These apply to the whole render, so "
                        "they are set once here.")
            with gr.Row():
                fit_to_output = gr.Checkbox(bool(values["fit_to_output"]), label="Fit mods to the output size",
                                            info="Shrinks mods bigger than the shot. Much faster; less detail.")
                phase1 = gr.Dropdown(choices=[("Fit to phase 1", "fit"), ("Full size", "full")],
                                     value=values["phase1_mods"], label="Mods in phase 1 (two-phase)",
                                     info="Fit: shrink to phase 1's half canvas.")
                phase2 = gr.Dropdown(choices=[("Full", "full"), ("Fit to tile", "tile"), ("Off", "off")],
                                     value=values["phase2_mods"], label="Mods in phase 2 (two-phase)")
            with gr.Row():
                shrink = gr.Dropdown(choices=[("Re-encode (better)", "reencode"), ("Fast (rougher)", "fast")],
                                     value=values["shrink_method"], label="Shrink method")
                max_short = gr.Slider(0, 2048, value=int(values["max_short"]), step=64,
                                      label="Max size for every mod (short edge, px)",
                                      info="0 = each mod's own size. A card's own max size wins.")
                save_btn = gr.Button("Save", variant="primary", scale=0)
            saved = gr.Markdown("")

        def save(fit, p1, p2, method, cap):
            try:
                path = patch.save_defaults({"fit_to_output": bool(fit), "phase1_mods": p1,
                                            "phase2_mods": p2, "shrink_method": method,
                                            "max_short": int(cap or 0)})
            except Exception as e:
                return f"❌ Could not save: {e}"
            return f"✅ Saved to `{path}`. Applies to the next shot rendered."

        save_btn.click(fn=save, inputs=[fit_to_output, phase1, phase2, shrink, max_short],
                       outputs=[saved], queue=False)

        gr.Markdown("### How to use it\n"
                    "1. Open a production's **Cast** tab in Showrunner.\n"
                    "2. Pick their mods on the cast card: **Picture**, **Video** and **Voice**, "
                    "each listing only the mods of that kind. A member can have all three. "
                    "*One picture* sends a multi-picture mod as a single contact sheet; *Its "
                    "sound* keeps that mod's own soundtrack; the numbers are max size and "
                    "strength.\n"
                    "3. Render a shot that shows them. The console names the label each mod got.\n\n"
                    "A shot that sets `h3_refmod_state` itself (the Inspector's Generation settings) "
                    "keeps its own selection — this never overrides it.")
