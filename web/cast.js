// Showrunner Refmods Integration -- RefMod pickers on each cast card.
//
// Loaded by an import this plugin's middleware appends to Showrunner's own
// app.js (WanGP serves its shell at the app root, so a script tag in
// Showrunner's index.html would never run). Showrunner's modules are imported
// rather than copied, so saving goes through the same update_cast path as
// every other cast edit, and the card re-renders the way Showrunner expects.
//
// Showrunner redraws the cast grid as you work, so the rows are re-attached by
// a MutationObserver. Nothing here replaces Showrunner's own markup: the rows
// are appended to the card. If a Showrunner update changes the card's shape
// and they can no longer be placed, the pickers quietly stop appearing -- the
// server side (the cast fields and the render hook) keeps working on its own.

// Resolved from this module's own URL, not document.baseURI: WanGP's shell
// sets <base href="/">, and the page hosting Showrunner is not Showrunner's
// own. This file is served at <mount>/__refmods/cast.js, so '../assets/js/…'
// lands on Showrunner's assets wherever WanGP mounted the app.
const base = new URL('../', import.meta.url).href;
const app = await import(new URL('assets/js/app.js', base).href);
const { state, actions } = app;

let mods = null;
try {
  const response = await fetch(new URL('__refmods/mods', base).href);
  mods = (await response.json()).mods || [];
} catch (error) {
  console.warn('[Showrunner Refmods] could not read the mod list', error);
  mods = [];
}

const escape = text => String(text ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// One picker per kind: a member's look, their motion and their voice are three
// different mods, and a single list mixing them could not say which was which.
// Each row offers only the mods of its own kind, so what you pick is what the
// shot's prompt will name it.
const KINDS = [
  { field: 'refmod', kind: 'image', label: 'Picture',
    hint: "A picture RefMod: this cast member's likeness, named <Picture N> in their shots" },
  { field: 'refmod_video', kind: 'video', label: 'Video',
    hint: "A video RefMod: their likeness in motion, named <Video N> in their shots" },
  { field: 'refmod_audio', kind: 'audio', label: 'Voice',
    hint: "An audio RefMod: their voice, named <Audio N> in their shots" },
];

function options(list, current) {
  const known = !current || list.some(mod => mod.name === current.mod);
  return [`<option value="">None</option>`]
    .concat(!known ? [`<option value="${escape(current.mod)}" selected>${escape(current.mod)} (not installed)</option>`] : [])
    .concat(list.map(mod => `<option value="${escape(mod.name)}"${current && current.mod === mod.name ? ' selected' : ''}>${escape(mod.name)}</option>`))
    .join('');
}

function modRow(member, spec) {
  const current = member[spec.field] && member[spec.field].mod ? member[spec.field] : null;
  const list = mods.filter(mod => mod.kind === spec.kind);
  if (!list.length && !current) return '';
  const f = spec.field;
  const visual = spec.kind !== 'audio';
  const detail = current ? `<div class="row">
      ${spec.kind === 'image' ? `<label class="muted" style="font-size:12.5px;display:flex;align-items:center;gap:4px">
        <input type="checkbox" data-mod-check="${f}:sheet"${current.sheet ? ' checked' : ''}> One picture</label>` : ''}
      ${visual ? `<label class="muted" style="font-size:12.5px;display:flex;align-items:center;gap:4px">
        <input type="checkbox" data-mod-check="${f}:use_audio"${current.use_audio ? ' checked' : ''}> Its sound</label>` : ''}
      <span class="grow"></span>
      ${visual ? `<input class="input" data-mod-field="${f}:max_short" type="number" min="0" max="2048" step="64"
        value="${Number(current.max_short ?? 0)}" title="Max size (short edge, px). 0 = the mod's own size, capped by the render default."
        style="width:84px">` : ''}
      <input class="input" data-mod-field="${f}:strength" type="number" min="0" max="2" step="0.05"
        value="${Number(current.strength ?? 1)}" title="Strength" style="width:74px">
    </div>` : '';
  return `<div class="row" style="margin-top:4px">
      <span class="muted" style="font-size:12.5px;min-width:48px">${spec.label}</span>
      <select class="select grow" data-mod-select="${f}" title="${spec.hint}">${options(list, current)}</select>
    </div>${detail}`;
}

function row(member) {
  const rows = KINDS.map(spec => modRow(member, spec)).join('');
  if (!rows) return '';
  return `<div class="cast-refmod" data-refmod-row>
    <div class="row"><span class="muted" style="font-size:12.5px">RefMods</span><span class="grow"></span></div>
    ${rows}</div>`;
}

function entry(card, field, current) {
  const value = name => card.querySelector(`[data-mod-field="${field}:${name}"]`);
  const check = name => card.querySelector(`[data-mod-check="${field}:${name}"]`);
  const saved = { mod: current.mod, strength: Number(value('strength')?.value) || 0 };
  if (value('max_short')) saved.max_short = Math.max(0, Number(value('max_short').value) || 0);
  if (check('sheet')) saved.sheet = !!check('sheet').checked;
  if (check('use_audio')) saved.use_audio = !!check('use_audio').checked;
  return saved;
}

function mount(card) {
  if (card.querySelector('[data-refmod-row]')) return;
  const body = card.querySelector('.cast-body');
  const member = (state.doc?.cast || []).find(item => item.id === card.dataset.cast);
  if (!body || !member) return;
  // Places get pickers too: a location can have a mod as much as a person can.
  // Shown whether or not Showrunner's "LoRAs on cast cards" setting is on --
  // the block goes after the LoRA row when there is one, else at the end.
  const markup = row(member);
  if (!markup) return;
  const anchor = body.querySelector('.cast-lora') || null;
  const holder = document.createElement('div');
  holder.innerHTML = markup;
  const element = holder.firstElementChild;
  if (anchor && anchor.parentNode === body) anchor.insertAdjacentElement('afterend', element);
  else body.append(element);

  element.querySelectorAll('[data-mod-select]').forEach(select => select.addEventListener('change', event => {
    const field = select.dataset.modSelect;
    const name = event.target.value;
    const current = member[field] || {};
    actions.ops([{ op: 'update_cast', cast: member.id, fields: { [field]: name
      ? { ...current, mod: name, strength: current.strength ?? 1 } : null } }]);
  }));
  element.querySelectorAll('[data-mod-field], [data-mod-check]').forEach(input => {
    const field = (input.dataset.modField || input.dataset.modCheck).split(':')[0];
    input.addEventListener('change', () => {
      const current = member[field];
      if (!current?.mod) return;
      actions.ops([{ op: 'update_cast', cast: member.id,
                     fields: { [field]: entry(element, field, current) } }], { quiet: true });
    });
  });
}

function mountAll() {
  try {
    document.querySelectorAll('[data-cast]').forEach(mount);
  } catch (error) {
    console.warn('[Showrunner Refmods] could not place the pickers', error);
  }
}

new MutationObserver(mountAll).observe(document.body, { childList: true, subtree: true });
mountAll();
