// =============================================================================
// Maquete 3D (Integracoes > Maquete 3D)
//
// O cliente envia a planta em PDF (exportado do CAD); o servidor le as paredes
// (app/services/maquete_planta.py) e aqui vira maquete 3D. Nela o cliente
// posiciona cameras (do cadastro ou de projeto), eletrocalha, caixas de
// passagem, prumada e rack; os cabos sao medidos pelo caminho da calha.
//
// Tudo o que e montado vai em `layout` (PUT /api/maquete/projetos/{id}),
// salvo sozinho 1,5 s depois da ultima mudanca.
//
// three.js 0.128 so e baixado ao abrir a tela. CSS fica aqui (prefixo mq-),
// para nao disputar o styles.css com outras telas.
// =============================================================================
(function () {
  'use strict';

  const THREE_URL = 'https://unpkg.com/three@0.128.0/build/three.min.js';
  const ORBIT_URL = 'https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js';

  // ---------- catálogos (valores típicos de folha de dados) ----------
  const MOD = {
    d2_28: { nome: 'Dome 2 MP · 2,8 mm', tipo: 'dome', res: 1920, fov: 103, ir: 20, w: 4.0 },
    d2_36: { nome: 'Dome 2 MP · 3,6 mm', tipo: 'dome', res: 1920, fov: 87, ir: 20, w: 4.0 },
    b2_28: { nome: 'Bullet 2 MP · 2,8 mm', tipo: 'bullet', res: 1920, fov: 103, ir: 30, w: 4.5 },
    b4_6: { nome: 'Bullet 4 MP · 6 mm', tipo: 'bullet', res: 2560, fov: 54, ir: 40, w: 6.0 },
    b8_4: { nome: 'Bullet 4K · 4 mm', tipo: 'bullet', res: 3840, fov: 88, ir: 40, w: 7.5 },
    v2_12: { nome: 'Bullet 2 MP · 2,8–12 mm motorizada', tipo: 'bullet', res: 1920, vari: [2.8, 12], ir: 50, w: 9.0 },
    f5: { nome: 'Fisheye 5 MP · 360°', tipo: 'fisheye', res: 2592, fov: 360, ir: 10, w: 6.0 },
  };
  const RACKS = {
    '12': { nome: 'Parede 12U', u: 12, w: .55, d: .45, base: 1.40 },
    '22': { nome: 'Piso 22U', u: 22, w: .60, d: .60, base: .10 },
    '44': { nome: 'Piso 44U', u: 44, w: .60, d: .80, base: .10 },
  };
  const IT = {
    dio: { g: 'Cabeamento', nome: 'DIO 12 fibras', u: 1, t: 'dio' },
    pp5: { g: 'Cabeamento', curto: 'Patch panel Cat5e', nome: 'Patch panel 24 portas Cat5e', u: 1, t: 'patch', portas: 24, cat: 'cat5e' },
    pp6: { g: 'Cabeamento', curto: 'Patch panel Cat6', nome: 'Patch panel 24 portas Cat6', u: 1, t: 'patch', portas: 24, cat: 'cat6' },
    pp6a: { g: 'Cabeamento', curto: 'Patch panel Cat6A', nome: 'Patch panel 24 portas Cat6A', u: 1, t: 'patch', portas: 24, cat: 'cat6a' },
    org: { g: 'Cabeamento', nome: 'Organizador de cabos', u: 1, t: 'org' },
    mt328: { g: 'MikroTik', curto: 'MikroTik CRS328', nome: 'MikroTik CRS328-24P-4S+RM · switch PoE 24 portas + 4 SFP+', u: 1, t: 'switch', portas: 24, sfp: 4, poe: 450 },
    mt326: { g: 'MikroTik', curto: 'MikroTik CRS326', nome: 'MikroTik CRS326-24G-2S+RM · switch 24 portas sem PoE + 2 SFP+', u: 1, t: 'switch', portas: 24, sfp: 2, poe: 0 },
    mtccr: { g: 'MikroTik', curto: 'MikroTik CCR2004', nome: 'MikroTik CCR2004-16G-2S+ · roteador 16 portas + 2 SFP+', u: 1, t: 'router', portas: 16, sfp: 2 },
    mt4011: { g: 'MikroTik', curto: 'MikroTik RB4011', nome: 'MikroTik RB4011iGS+RM · roteador 10 portas + 1 SFP+', u: 1, t: 'router', portas: 10, sfp: 1 },
    mt750: { g: 'MikroTik', curto: 'MikroTik hEX RB750Gr3', nome: 'MikroTik hEX RB750Gr3 · roteador 5 portas (de mesa, em bandeja)', u: 1, t: 'router', portas: 5 },
    sw8: { g: 'Switch PoE', curto: 'Switch PoE 8p', nome: 'Switch PoE 8 portas · 120 W', u: 1, t: 'switch', portas: 8, poe: 120 },
    sw16: { g: 'Switch PoE', curto: 'Switch PoE 16p', nome: 'Switch PoE 16 portas · 150 W', u: 1, t: 'switch', portas: 16, poe: 150 },
    sw24: { g: 'Switch PoE', curto: 'Switch PoE 24p', nome: 'Switch PoE 24 portas · 370 W', u: 1, t: 'switch', portas: 24, poe: 370 },
    nvr8: { g: 'Gravação', nome: 'Gravador NVR 8 canais', u: 1, t: 'nvr', canais: 8 },
    nvr16: { g: 'Gravação', nome: 'Gravador NVR 16 canais', u: 1, t: 'nvr', canais: 16 },
    nvr32: { g: 'Gravação', nome: 'Gravador NVR 32 canais · 8 HDs', u: 2, t: 'nvr', canais: 32 },
    band: { g: 'Outros', nome: 'Bandeja · ONU e roteador', u: 1, t: 'band' },
    ff1: { g: 'Acabamento', nome: 'Frente falsa', u: 1, t: 'blank' },
    ff2: { g: 'Acabamento', nome: 'Frente falsa', u: 2, t: 'blank' },
    ffv: { g: 'Acabamento', nome: 'Frente falsa ventilada', u: 1, t: 'blank', vent: true },
    regua: { g: 'Energia', nome: 'Régua 8 tomadas', u: 1, t: 'power' },
    nb: { g: 'Energia', nome: 'Nobreak 1,5 kVA', u: 2, t: 'power' },
  };
  const CAT = { cat5e: 'Cat5e', cat6: 'Cat6', cat6a: 'Cat6A' };
  const JAN = { J1: [1.00, 1.40], J2: [1.00, 1.40], J3: [1.90, 0.50], J4: [1.00, 1.40] };
  const COR = { on: 0x087f5b, off: 0xc92a2a, unk: 0x66747e, new: 0x1971c2 };
  const ST = { on: ['Online', 'mq-p-ok', 'mq-d-on'], off: ['Offline', 'mq-p-off', 'mq-d-off'], unk: ['Sem status', 'mq-p-grey', 'mq-d-unk'], new: ['Projeto', 'mq-p-blue', 'mq-d-new'] };

  const $ = id => document.getElementById(id);
  const fmt = (n, d = 1) => Number(n || 0).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
  const h = s => (typeof esc === 'function' ? esc(s) : String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
  const toast = (m, erro) => (typeof showToast === 'function' ? showToast(m, erro) : console.log(m));

  // ---------- estado ----------
  let projetos = [], proj = null, L = null;   // L = layout em edição
  // Câmera do cadastro: chave = local + IP (mesma faixa de IP em dois locais
  // atrás de conectores diferentes não pode ligar na câmera errada).
  let cadastro = { porChave: {}, porRotulo: {}, porIp: {}, lista: [] };
  let poll = null, salvarTimer = null, salvando = false, semPermissao = false, sujo = false;

  // ======================================================================
  // CSS
  // ======================================================================
  const CSS = `
#viewMaquete{--mq-gap:20px}
#viewMaquete .mq-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:var(--mq-gap)}
#viewMaquete .mq-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px;min-width:0}
#viewMaquete .mq-pcard{display:flex;flex-direction:column;gap:10px;cursor:pointer;text-align:left;font:inherit;color:inherit}
#viewMaquete .mq-pcard:hover{border-color:var(--primary)}
#viewMaquete .mq-pcard b{font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-pcard small{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-pcard .mq-row{display:flex;align-items:center;gap:8px;min-width:0}
#viewMaquete .mq-vazio{text-align:center;padding:48px 20px;color:var(--muted);font-size:14px;line-height:1.6}
#viewMaquete .mq-vazio b{display:block;color:var(--text);font-size:15px;margin-bottom:6px}
#viewMaquete .mq-pill{font-size:11px;font-weight:700;border-radius:10px;padding:2px 8px;white-space:nowrap;display:inline-block}
#viewMaquete .mq-p-ok{background:var(--primary-soft);color:var(--primary)} #viewMaquete .mq-p-warn{background:var(--amber-soft);color:var(--amber)}
#viewMaquete .mq-p-off{background:var(--danger-soft);color:var(--danger)} #viewMaquete .mq-p-blue{background:var(--blue-soft);color:var(--blue)}
#viewMaquete .mq-p-grey{background:var(--surface-soft);color:var(--muted);border:1px solid var(--border)}
#viewMaquete .mq-dot{width:8px;height:8px;border-radius:50%;flex:none;display:inline-block}
#viewMaquete .mq-d-on{background:var(--primary)} #viewMaquete .mq-d-off{background:var(--danger)} #viewMaquete .mq-d-unk{background:var(--muted)} #viewMaquete .mq-d-new{background:var(--blue)}
#viewMaquete .mq-sw{width:14px;height:3px;border-radius:2px;display:inline-block}
#viewMaquete .mq-btn{height:34px;padding:0 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);display:inline-flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;font-weight:600;font-size:13px;white-space:nowrap;color:var(--text);font-family:inherit}
#viewMaquete .mq-btn:hover{background:var(--surface-soft)}
#viewMaquete .mq-btn.pri{background:var(--primary);border-color:var(--primary);color:#fff}
#viewMaquete .mq-btn.on{background:var(--primary-soft);border-color:var(--primary);color:var(--primary)}
#viewMaquete .mq-btn.sm{height:28px;padding:0 10px;font-size:12px}
#viewMaquete .mq-btn.del{color:var(--danger)}
#viewMaquete .mq-btn:disabled{opacity:.45;cursor:default}
#viewMaquete .mq-btn:focus-visible,#viewMaquete .mq-tab:focus-visible,#viewMaquete .mq-seg button:focus-visible,#viewMaquete .mq-ri:focus-visible,#viewMaquete .mq-cam:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
#viewMaquete .mq-ehead{display:flex;align-items:center;gap:12px;margin-bottom:12px;min-width:0}
#viewMaquete .mq-ehead .mq-nome{font-size:22px;font-weight:700;border:1px solid transparent;border-radius:6px;padding:2px 6px;min-width:0;flex:1;background:transparent;color:var(--text);font-family:inherit}
#viewMaquete .mq-ehead .mq-nome:hover,#viewMaquete .mq-ehead .mq-nome:focus{border-color:var(--border);background:var(--surface)}
#viewMaquete .mq-salvo{font-size:12px;color:var(--muted);white-space:nowrap}
#viewMaquete .mq-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:var(--mq-gap);overflow-x:auto}
#viewMaquete .mq-tab{height:38px;padding:0 14px;border:0;background:none;border-bottom:2px solid transparent;color:var(--muted);font-weight:600;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;gap:6px;font-family:inherit;font-size:13px}
#viewMaquete .mq-tab.on{color:var(--primary);border-bottom-color:var(--primary)}
#viewMaquete .mq-tab .mq-cnt{font-size:11px;background:var(--surface-soft);border:1px solid var(--border);border-radius:10px;padding:0 7px;color:var(--muted)}
#viewMaquete .mq-content{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:var(--mq-gap);align-content:start}
#viewMaquete #mqAbaMaquete{grid-template-rows:minmax(0,1fr);height:calc(100vh - 230px);min-height:560px}
#viewMaquete .mq-view{grid-column:span 9;position:relative;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;min-height:520px}
#viewMaquete #mqCv{position:absolute;inset:0;display:block;width:100%;height:100%;cursor:grab;touch-action:none}
#viewMaquete #mqCv.add{cursor:crosshair} #viewMaquete #mqCv.mover{cursor:move}
#viewMaquete .mq-bar{position:absolute;top:12px;left:12px;right:12px;display:flex;gap:8px;flex-wrap:wrap;pointer-events:none}
#viewMaquete .mq-bar>*{pointer-events:auto}
#viewMaquete .mq-seg{display:inline-flex;background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden;box-shadow:0 2px 8px rgba(23,32,38,.06);max-width:100%;overflow-x:auto}
#viewMaquete .mq-seg button{height:32px;padding:0 12px;border:0;background:none;cursor:pointer;font-weight:600;font-size:12px;color:var(--muted);white-space:nowrap;display:inline-flex;align-items:center;gap:6px;font-family:inherit}
#viewMaquete .mq-seg button+button{border-left:1px solid var(--border)}
#viewMaquete .mq-seg button.on{background:var(--primary-soft);color:var(--primary)}
#viewMaquete .mq-grow{flex:1}
#viewMaquete .mq-hint{position:absolute;left:12px;bottom:12px;font-size:12px;color:var(--muted);background:rgba(255,255,255,.94);border:1px solid var(--border);border-radius:6px;padding:6px 10px;pointer-events:none;max-width:calc(100% - 24px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-legend{position:absolute;right:12px;bottom:12px;display:flex;gap:12px;font-size:12px;color:var(--muted);background:rgba(255,255,255,.94);border:1px solid var(--border);border-radius:6px;padding:6px 10px}
#viewMaquete .mq-legend span{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
#viewMaquete #mqLabels{position:absolute;inset:0;pointer-events:none;overflow:hidden}
#viewMaquete .mq-lb{position:absolute;transform:translate(-50%,-50%);font-size:11px;font-weight:700;white-space:nowrap;padding:2px 7px;border-radius:4px;background:rgba(255,255,255,.94);border:1px solid var(--border);color:var(--text);display:flex;align-items:center;gap:5px}
#viewMaquete .mq-lb.obj{transform:translate(-50%,-150%);font-weight:600}
#viewMaquete .mq-lb.cx{font-size:10px;padding:1px 5px;color:var(--muted)}
#viewMaquete .mq-lb.sel{border-color:var(--blue);box-shadow:0 0 0 2px var(--blue-soft);color:var(--text)}
#viewMaquete .mq-panel{grid-column:span 3;display:flex;flex-direction:column;gap:var(--mq-gap);min-width:0;min-height:0;overflow:auto}
#viewMaquete .mq-panel>.mq-card{flex:none}
#viewMaquete .mq-card h2{font-size:15px;margin:0 0 12px;display:flex;align-items:center;gap:8px;min-width:0}
#viewMaquete .mq-card h2 .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-card h2 .r{margin-left:auto;display:flex;gap:6px;align-items:center;flex:none}
#viewMaquete .mq-x{border:0;background:none;cursor:pointer;color:var(--muted);font-size:20px;line-height:1;padding:0 2px}
#viewMaquete dl.mq-dl{margin:0;display:grid;grid-template-columns:minmax(0,1fr) auto}
#viewMaquete .mq-dl dt,#viewMaquete .mq-dl dd{margin:0;min-height:32px;display:flex;align-items:center;border-top:1px solid var(--border);font-size:12px}
#viewMaquete .mq-dl dt{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;padding-right:8px}
#viewMaquete .mq-dl dd{justify-content:flex-end;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
#viewMaquete .mq-dl.top0>dt:first-child,#viewMaquete .mq-dl.top0>dt:first-child+dd{border-top:0}
#viewMaquete .mq-dl dd input[type=number]{width:70px;height:26px;text-align:right;border:1px solid var(--border);border-radius:4px;padding:0 6px;font-weight:600;font-family:inherit}
#viewMaquete .mq-dl dd select{height:26px;border:1px solid var(--border);border-radius:4px;padding:0 6px;font-weight:600;background:var(--surface);font-family:inherit}
#viewMaquete .mq-fld{display:flex;flex-direction:column;gap:6px;margin-bottom:12px}
#viewMaquete .mq-fld label{font-size:12px;color:var(--muted)}
#viewMaquete .mq-fld input,#viewMaquete .mq-fld select,#viewMaquete .mq-inp{height:34px;border:1px solid var(--border);border-radius:6px;padding:0 10px;background:var(--surface);width:100%;min-width:0;font-family:inherit;font-size:13px;color:var(--text)}
#viewMaquete .mq-row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
#viewMaquete .mq-rng{display:grid;grid-template-columns:72px minmax(0,1fr) 52px;align-items:center;gap:8px;font-size:12px;color:var(--muted);height:32px}
#viewMaquete .mq-rng output{text-align:right;color:var(--text);font-variant-numeric:tabular-nums;font-weight:600}
#viewMaquete input[type=range]{width:100%;accent-color:var(--primary)}
#viewMaquete .mq-dori{border:1px solid var(--border);border-radius:6px;background:var(--surface-soft);padding:4px 12px;margin:8px 0 12px}
#viewMaquete .mq-dori dt,#viewMaquete .mq-dori dd{min-height:28px}
#viewMaquete .mq-bard{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
#viewMaquete .mq-cabo{font-size:12px;line-height:1.5;color:var(--muted);border-top:1px solid var(--border);padding-top:12px;margin-bottom:12px}
#viewMaquete .mq-cabo b{color:var(--text)}
#viewMaquete .mq-acts2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
#viewMaquete .mq-chk{display:flex;align-items:center;gap:10px;height:34px;border-top:1px solid var(--border);font-size:13px;cursor:pointer}
#viewMaquete .mq-chk:first-of-type{border-top:0}
#viewMaquete .mq-chk input{width:16px;height:16px;accent-color:var(--primary);margin:0}
#viewMaquete .mq-chk .mq-sw{margin-left:auto}
#viewMaquete .mq-note{font-size:12px;color:var(--amber);background:var(--amber-soft);border-radius:6px;padding:8px 10px;margin-top:12px;line-height:1.45}
#viewMaquete .mq-muted{color:var(--muted);font-size:12px;line-height:1.5}
#viewMaquete .mq-cams{display:flex;flex-direction:column;margin:0 -6px}
#viewMaquete .mq-cam{display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:10px;height:46px;border:0;border-top:1px solid var(--border);background:none;text-align:left;cursor:pointer;padding:0 6px;width:100%;font-family:inherit;color:inherit}
#viewMaquete .mq-cam:first-child{border-top:0}
#viewMaquete .mq-cam:hover{background:var(--surface-soft)} #viewMaquete .mq-cam.sel{background:var(--blue-soft)}
#viewMaquete .mq-cam .t{min-width:0;display:flex;flex-direction:column;gap:2px}
#viewMaquete .mq-cam .t b,#viewMaquete .mq-cam .t small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-cam .t b{font-size:12px;font-weight:600} #viewMaquete .mq-cam .t small{font-size:11px;color:var(--muted)}
#viewMaquete .mq-cam em{font-style:normal;font-size:12px;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:48px;text-align:right}
#viewMaquete .mq-kpi{grid-column:span 3;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px;display:flex;flex-direction:column;gap:6px;min-width:0}
#viewMaquete .mq-kpi small{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-kpi b{font-size:22px;font-variant-numeric:tabular-nums;white-space:nowrap}
#viewMaquete .mq-kpi b span{font-size:13px;color:var(--muted);font-weight:500}
#viewMaquete .mq-meter{height:6px;border-radius:3px;background:var(--surface-soft);border:1px solid var(--border);overflow:hidden}
#viewMaquete .mq-meter i{display:block;height:100%;background:var(--primary)}
#viewMaquete .mq-meter i.warn{background:var(--amber)} #viewMaquete .mq-meter i.off{background:var(--danger)}
#viewMaquete .mq-kpi em{font-style:normal;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-s4{grid-column:span 4} #viewMaquete .mq-s8{grid-column:span 8} #viewMaquete .mq-s12{grid-column:span 12}
#viewMaquete .mq-rkwrap{display:flex;flex-direction:column;gap:12px}
#viewMaquete .mq-rk{background:var(--sidebar,#13252d);border-radius:6px;padding:10px 10px 10px 34px;position:relative}
#viewMaquete .mq-rk::before{content:"";position:absolute;left:28px;top:10px;bottom:10px;width:2px;background:#2c4a56}
#viewMaquete .mq-ri{position:relative;display:flex;align-items:center;gap:8px;border-radius:3px;margin:0 0 2px;padding:0 8px;font-size:11px;font-weight:600;cursor:pointer;min-width:0;border:1px solid transparent;width:100%;text-align:left}
#viewMaquete .mq-ri .un{position:absolute;left:-30px;width:22px;text-align:right;color:#7f949d;font-size:10px;font-weight:500;font-variant-numeric:tabular-nums}
#viewMaquete .mq-ri .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:70px;flex:1}
#viewMaquete .mq-ri.sel{border-color:#74c0fc;box-shadow:0 0 0 2px rgba(116,192,252,.35)}
#viewMaquete .mq-ri.t-patch{background:#e9edf0;color:#172026} #viewMaquete .mq-ri.t-switch{background:#33464f;color:#e9edf0} #viewMaquete .mq-ri.t-nvr{background:#0f1c22;color:#e9edf0;border-color:#2c4a56}
#viewMaquete .mq-ri.t-router{background:#0e5a69;color:#e3fafc}
#viewMaquete .mq-ri.t-dio,#viewMaquete .mq-ri.t-band{background:#5b6b73;color:#fff} #viewMaquete .mq-ri.t-org{background:#25363e;color:#9fb0b8} #viewMaquete .mq-ri.t-power{background:#172026;color:#e9edf0;border-color:#2c4a56}
#viewMaquete .mq-ri.t-blank{background:#2a3b43;color:#9fb0b8;font-weight:500}
#viewMaquete .mq-ri.t-blank.vent{background:repeating-linear-gradient(90deg,#2a3b43 0 6px,#22323a 6px 9px)}
#viewMaquete .mq-ri.t-vazio{background:transparent;border:1px dashed #2c4a56;color:#7f949d;font-weight:500;height:24px}
#viewMaquete .mq-ri.t-vazio:hover{border-color:#51cf66;color:#c9d4d9}
#viewMaquete .mq-ri.t-vazio.pick{border:1px solid #51cf66;color:#b2f2bb;background:rgba(81,207,102,.08)}
#viewMaquete .mq-ri.over{background:var(--danger-soft);color:var(--danger)}
#viewMaquete .mq-ri.drag{opacity:.35}
#viewMaquete .mq-ri.alvo-ok{background:rgba(81,207,102,.18);border:1px solid #51cf66}
#viewMaquete .mq-ri.alvo-no{background:rgba(255,135,135,.18);border:1px solid #ff8787}
#viewMaquete .mq-ri[draggable=true]{cursor:grab}
#viewMaquete #mqRkFora .mq-ri{margin-bottom:4px}
#viewMaquete .mq-ports{display:grid;grid-template-rows:repeat(2,8px);grid-auto-flow:column;grid-auto-columns:7px;gap:2px;flex:none}
#viewMaquete .mq-ports i{border-radius:1px;background:#c3ccd2;display:block}
#viewMaquete .t-switch .mq-ports i,#viewMaquete .t-nvr .mq-ports i{background:#5b6b73} #viewMaquete .t-router .mq-ports i{background:#2f7d8c}
#viewMaquete .mq-ports i.on{background:var(--primary)} #viewMaquete .t-switch .mq-ports i.on{background:#51cf66}
#viewMaquete .mq-ports.sfp{grid-auto-columns:10px;margin-left:2px} #viewMaquete .mq-ports.sfp i{background:#9fb0b8}
#viewMaquete .mq-rkbox{border:1px solid var(--border);border-radius:6px;padding:12px;display:flex;flex-direction:column;gap:10px;background:var(--surface-soft)}
#viewMaquete .mq-rkhead{display:flex;align-items:center;gap:8px;min-width:0}
#viewMaquete .mq-rkhead b{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}
#viewMaquete .mq-rktools{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
#viewMaquete .mq-rktools label{flex:none}
#viewMaquete .mq-rktools .mq-inp{flex:1;min-width:90px;height:30px}
#viewMaquete .mq-tw{overflow-x:auto}
#viewMaquete .mq-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12px}
#viewMaquete .mq-table th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600;text-align:left;height:36px;border-bottom:1px solid var(--border);padding:0 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-table td{height:40px;border-bottom:1px solid var(--border);padding:0 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-table .n{text-align:right;font-variant-numeric:tabular-nums}
#viewMaquete .mq-table tr.click{cursor:pointer} #viewMaquete .mq-table tr.click:hover td{background:var(--surface-soft)}
#viewMaquete .mq-table tfoot td{font-weight:700;border-bottom:0}
#viewMaquete .mq-lhead{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--border)}
#viewMaquete .mq-lhead .search-box{min-width:240px}
#viewMaquete .mq-lsel{width:auto;min-width:170px;height:36px}
#viewMaquete .mq-ltab td{vertical-align:middle;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-ltab tbody tr[data-mq-linha]:hover{background:var(--surface-soft)}
#viewMaquete .mq-lnome{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-lsub{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
#viewMaquete .mq-lsub.erro{color:var(--danger)}
#viewMaquete .mq-n{text-align:right;font-variant-numeric:tabular-nums}
#viewMaquete .mq-lacoes{display:flex;gap:6px;justify-content:flex-end;align-items:center}
#viewMaquete .mq-ico{width:28px;height:28px;border-radius:6px;border:1px solid var(--border);background:var(--surface);display:inline-grid;place-items:center;cursor:pointer;color:var(--muted);flex:none}
#viewMaquete .mq-ico svg{width:14px;height:14px}
#viewMaquete .mq-ico:hover{background:var(--surface-soft);color:var(--text)} #viewMaquete .mq-ico.del:hover{color:var(--danger)}
#viewMaquete .mq-etit{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}
#viewMaquete .mq-etit b{font-size:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-etit small{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#viewMaquete .mq-piso{border-top:1px solid var(--border);padding:10px 0;display:grid;grid-template-columns:minmax(0,1fr) 80px;gap:6px 10px;align-items:center}
#viewMaquete .mq-piso input{height:30px}
#viewMaquete .mq-piso small{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
#viewMaquete .mq-piso label{font-size:11px;color:var(--muted);text-align:right}
#viewMaquete .mq-orc td{height:36px;padding:0 6px}
#viewMaquete .mq-orc tr.mq-orc-g td{background:var(--surface-soft);font-weight:700;font-size:12px;height:30px}
#viewMaquete .mq-oin{width:100%;height:28px;border:1px solid transparent;border-radius:4px;padding:0 6px;background:transparent;font:inherit;font-size:12px;color:var(--text)}
#viewMaquete .mq-oin:hover{border-color:var(--border)} #viewMaquete .mq-oin:focus{border-color:var(--primary);background:var(--surface);outline:none}
#viewMaquete .mq-oin.n{text-align:right;font-variant-numeric:tabular-nums}
#viewMaquete .mq-oin.alt{background:var(--amber-soft)} #viewMaquete .mq-oin.vazio{border-color:var(--border);background:var(--surface)}
#viewMaquete .mq-orc .mq-x{font-size:16px;padding:0 4px}
#viewMaquete .mq-orc-pe{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
#viewMaquete .mq-carregando{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:13px;background:var(--surface)}
@media (max-width:1280px){#viewMaquete .mq-kpi{grid-column:span 6}#viewMaquete .mq-s4,#viewMaquete .mq-s8{grid-column:span 12}}
@media (max-width:1180px){#viewMaquete #mqAbaMaquete{grid-template-rows:none;height:auto}#viewMaquete .mq-view{grid-column:span 12;min-height:560px}#viewMaquete .mq-panel{grid-column:span 12;overflow:visible;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));align-items:start}}
@media (max-width:860px){#viewMaquete{--mq-gap:16px}#viewMaquete .mq-legend,#viewMaquete .mq-seg button .lbl{display:none}#viewMaquete .mq-kpi{grid-column:span 12}#viewMaquete .mq-view{min-height:460px}}
`;
  function injetarCss() {
    if ($('mqCss')) return;
    const st = document.createElement('style');
    st.id = 'mqCss';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function carregarScript(src) {
    return new Promise((ok, falha) => {
      if (document.querySelector(`script[src="${src}"]`)) return ok();
      const s = document.createElement('script');
      s.src = src; s.onload = ok; s.onerror = () => falha(new Error('Não foi possível baixar ' + src));
      document.head.appendChild(s);
    });
  }
  async function garantirThree() {
    if (!window.THREE) await carregarScript(THREE_URL);
    if (!window.THREE.OrbitControls) await carregarScript(ORBIT_URL);
  }

  // ======================================================================
  // LISTA DE PROJETOS
  // ======================================================================
  function secao() { return $('viewMaquete'); }

  window.loadMaquete = async function () {
    injetarCss();
    pararEditor();
    proj = null;
    renderLista(true);
    await atualizarLista();
  };

  async function atualizarLista() {
    const r = await api('/api/maquete/projetos');
    const d = r && r.ok ? await r.json() : null;
    projetos = d?.projetos || [];
    if (!proj) renderLista(false);
    clearTimeout(poll);
    if (!proj && projetos.some(p => p.status === 'processando')) poll = setTimeout(atualizarLista, 3000);
  }

  // filtro e ordem da lista (busca + local + situação, ordem natural)
  let filtro = { q: '', local: '', st: '', ordem: 'nome' };
  const ST_PROJ = { pronto: ['Pronta', 'mq-p-ok'], processando: ['Lendo a planta…', 'mq-p-warn'], erro: ['Não deu para ler', 'mq-p-off'] };
  const natural = (a, b) => String(a || '').localeCompare(String(b || ''), 'pt', { numeric: true, sensitivity: 'base' });
  const quando = s => { try { return new Date(s).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }); } catch (_) { return s || ''; } };

  function renderLista(carregando) {
    const sec = secao(); if (!sec) return;
    const total = projetos.length;
    const cams = projetos.reduce((a, p) => a + (p.cameras || 0), 0);
    const metros = projetos.reduce((a, p) => a + (p.metros || 0), 0);
    const pend = projetos.filter(p => p.status !== 'pronto').length;
    sec.innerHTML = `
      <div class="page-heading">
        <div><p class="eyebrow">Integrações</p><h1>Maquete 3D</h1>
          <p>Envie a planta em PDF exportado do CAD. O SightOps levanta as paredes em 3D e você posiciona câmeras, eletrocalha e rack, com a metragem de cabo.</p></div>
        <div class="page-heading-actions">
          <input type="file" id="mqArquivo" accept="application/pdf,.pdf" style="display:none">
          <button class="primary-action" type="button" id="mqEnviar"><i data-lucide="upload"></i> Enviar planta</button>
        </div>
      </div>
      <div class="rotas-kpis">
        <article class="rotas-kpi"><span>Projetos</span><strong>${total}</strong></article>
        <article class="rotas-kpi"><span>Câmeras posicionadas</span><strong>${cams}</strong></article>
        <article class="rotas-kpi"><span>Cabo projetado</span><strong>${fmt(metros, 0)} <small>m</small></strong></article>
        <article class="rotas-kpi${pend ? ' is-amber' : ''}"><span>Plantas sendo lidas ou com erro</span><strong>${pend}</strong></article>
      </div>
      <section class="panel" style="padding:0;overflow:hidden">
        <div class="mq-lhead">
          <label class="search-box"><i data-lucide="search"></i><input id="mqBusca" type="search" placeholder="Buscar projeto, local ou arquivo" value="${h(filtro.q)}"></label>
          <select class="mq-inp mq-lsel" id="mqFLocal" aria-label="Local"></select>
          <select class="mq-inp mq-lsel" id="mqFSt" aria-label="Situação"></select>
          <select class="mq-inp mq-lsel" id="mqFOrdem" aria-label="Ordem">
            <option value="nome">Nome A–Z</option><option value="recente">Mais recentes</option><option value="local">Local A–Z</option>
          </select>
        </div>
        <div class="table-wrap" style="overflow-x:auto">
          <table class="data-table mq-ltab" style="table-layout:fixed;width:100%;min-width:900px">
            <colgroup><col><col style="width:16%"><col style="width:17%"><col style="width:84px"><col style="width:92px"><col style="width:132px"><col style="width:132px"><col style="width:132px"></colgroup>
            <thead><tr><th>Projeto</th><th>Local</th><th>Pavimentos</th><th class="mq-n">Câmeras</th><th class="mq-n">Cabo</th><th>Situação</th><th>Atualizado</th><th></th></tr></thead>
            <tbody id="mqLBody"></tbody>
          </table>
        </div>
      </section>`;
    if (window.lucide) lucide.createIcons();
    $('mqEnviar').onclick = () => $('mqArquivo').click();
    $('mqArquivo').onchange = escolherArquivo;
    $('mqBusca').oninput = e => { filtro.q = e.target.value; renderLinhas(carregando); };
    $('mqFLocal').onchange = e => { filtro.local = e.target.value; renderLinhas(carregando); };
    $('mqFSt').onchange = e => { filtro.st = e.target.value; renderLinhas(carregando); };
    $('mqFOrdem').value = filtro.ordem;
    $('mqFOrdem').onchange = e => { filtro.ordem = e.target.value; renderLinhas(carregando); };
    renderLinhas(carregando);
  }

  function renderLinhas(carregando) {
    const q = filtro.q.trim().toLowerCase();
    const casaBusca = p => !q || [p.nome, p.local, p.arquivo, p.observacao].some(x => String(x || '').toLowerCase().includes(q));
    // contagem de cada opção considera os outros filtros
    const base = projetos.filter(casaBusca);
    const locais = [...new Set(projetos.map(p => p.local || ''))].sort(natural);
    const SEM = '__sem__', chaveLocal = p => p.local || SEM, casaLocal = p => !filtro.local || chaveLocal(p) === filtro.local;
    const nLocal = l => base.filter(p => (!filtro.st || p.status === filtro.st) && (p.local || '') === l).length;
    const nSt = s => base.filter(p => casaLocal(p) && p.status === s).length;
    $('mqFLocal').innerHTML = `<option value="">Todos os locais (${base.filter(p => !filtro.st || p.status === filtro.st).length})</option>` +
      locais.map(l => `<option value="${h(l || SEM)}"${(l || SEM) === filtro.local ? ' selected' : ''}>${h(l || 'Sem local')} (${nLocal(l)})</option>`).join('');
    $('mqFSt').innerHTML = `<option value="">Todas as situações (${base.filter(casaLocal).length})</option>` +
      Object.entries(ST_PROJ).map(([k, v]) => `<option value="${k}"${k === filtro.st ? ' selected' : ''}>${v[0]} (${nSt(k)})</option>`).join('');
    let lista = base.filter(p => casaLocal(p) && (!filtro.st || p.status === filtro.st));
    if (filtro.ordem === 'recente') lista.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    else if (filtro.ordem === 'local') lista.sort((a, b) => natural(a.local, b.local) || natural(a.nome, b.nome));
    else lista.sort((a, b) => natural(a.nome, b.nome));
    const body = $('mqLBody');
    if (carregando) { body.innerHTML = '<tr class="empty-row"><td colspan="8">Carregando projetos…</td></tr>'; return; }
    if (!projetos.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="8"><b>Nenhuma maquete ainda.</b><br>Clique em <b>Enviar planta</b> e escolha o PDF da planta baixa, exportado do CAD (AutoCAD, Revit, SketchUp). PDF escaneado e foto ainda não são lidos.</td></tr>';
      return;
    }
    if (!lista.length) { body.innerHTML = '<tr class="empty-row"><td colspan="8">Nenhum projeto com esse filtro.</td></tr>'; return; }
    body.innerHTML = lista.map(p => {
      const st = ST_PROJ[p.status] || ST_PROJ.processando;
      const detalhe = p.status === 'erro' ? p.erro : p.arquivo;
      return `<tr data-mq-linha="${h(p.id)}" style="cursor:${p.status === 'pronto' ? 'pointer' : 'default'}">
        <td><div class="mq-lnome" title="${h(p.nome)}">${h(p.nome)}</div><div class="mq-lsub${p.status === 'erro' ? ' erro' : ''}" title="${h(detalhe)}">${h(detalhe)}</div></td>
        <td title="${h(p.local)}">${p.local ? h(p.local) : '<span class="mq-muted">Sem local</span>'}</td>
        <td title="${h(p.pisos.join(', '))}">${p.status === 'pronto' ? h(p.pisos.join(', ')) : '—'}</td>
        <td class="mq-n">${p.cameras || 0}</td>
        <td class="mq-n">${p.metros ? fmt(p.metros, 0) + ' m' : '—'}</td>
        <td><span class="mq-pill ${st[1]}">${st[0]}</span></td>
        <td>${h(quando(p.updated_at))}</td>
        <td><div class="mq-lacoes">
          <button class="mq-btn sm" type="button" data-mq-abrir="${h(p.id)}"${p.status === 'pronto' ? '' : ' disabled'}>Abrir</button>
          <button class="mq-ico" type="button" data-mq-editar="${h(p.id)}" title="Editar dados" aria-label="Editar dados de ${h(p.nome)}"><i data-lucide="pencil"></i></button>
          <button class="mq-ico del" type="button" data-mq-excluir="${h(p.id)}" title="Excluir" aria-label="Excluir ${h(p.nome)}"><i data-lucide="trash-2"></i></button>
        </div></td></tr>`;
    }).join('');
    if (window.lucide) lucide.createIcons();
    body.querySelectorAll('[data-mq-linha]').forEach(tr => tr.onclick = e => {
      if (e.target.closest('button, .mq-lacoes')) return;
      const p = projetos.find(x => x.id === tr.dataset.mqLinha); if (p && p.status === 'pronto') abrir(p.id);
    });
    body.querySelectorAll('[data-mq-abrir]').forEach(b => b.onclick = e => { e.stopPropagation(); abrir(b.dataset.mqAbrir); });
    body.querySelectorAll('[data-mq-editar]').forEach(b => b.onclick = e => {
      e.stopPropagation();
      const p = projetos.find(x => x.id === b.dataset.mqEditar); if (p) editarDados(p);
    });
    body.querySelectorAll('[data-mq-excluir]').forEach(b => b.onclick = e => {
      e.stopPropagation();
      const p = projetos.find(x => x.id === b.dataset.mqExcluir);
      if (p && window.confirm(`Excluir a maquete "${p.nome}"? Isso apaga a planta e tudo o que foi montado.`)) excluirProjeto(p.id);
    });
  }

  // "v7_[Prancha A0]_LEGAL_Apto Carlos Silva_02-03.pdf" -> "LEGAL Apto Carlos Silva"
  function nomeDoArquivo(f) {
    let s = String(f || '').replace(/\.pdf$/i, '');
    s = s.replace(/[\[(][^\])]*[\])]/g, ' ').replace(/^v\d+\b/i, ' ').replace(/[_]+/g, ' ');
    s = s.replace(/\b(rev|r)\s?\d+\b/ig, ' ').replace(/\b\d{1,2}\s*[-de]+\s*\d{1,2}\s*$/i, ' ');
    return s.replace(/\s+/g, ' ').trim() || 'Planta';
  }

  async function sugestoesLocal() {
    if (!cadastro.lista.length) await carregarCadastro().catch(() => {});
    return [...new Set([...projetos.map(p => p.local), ...cadastro.lista.map(c => c.site)].filter(Boolean))].sort(natural);
  }

  // Janela "Dados do projeto": nova planta (com arquivo) ou editar. Fecha só por X, Cancelar ou Esc.
  async function modalDados({ titulo, sub, nome, local, observacao, botao }) {
    const locais = await sugestoesLocal();
    return new Promise(resolve => {
      document.getElementById('mqModalDados')?.remove();
      const wrap = document.createElement('div');
      wrap.id = 'mqModalDados'; wrap.className = 'modal-backdrop';
      wrap.innerHTML = `
        <div class="modal" style="max-width:520px" role="dialog" aria-modal="true" aria-labelledby="mqMdTitulo">
          <div class="modal-header">
            <div><h2 id="mqMdTitulo">${h(titulo)}</h2>${sub ? `<p>${h(sub)}</p>` : ''}</div>
            <button class="icon-button" type="button" data-mq-md-fechar aria-label="Fechar"><i data-lucide="x"></i></button>
          </div>
          <form class="modal-body" id="mqMdForm" autocomplete="off">
            <div class="form-group"><label for="mqMdNome">Nome do projeto</label><input id="mqMdNome" maxlength="120" required value="${h(nome)}"></div>
            <div class="form-group"><label for="mqMdLocal">Local</label><input id="mqMdLocal" list="mqMdLocais" maxlength="120" placeholder="Ex.: Condomínio Jardins I" value="${h(local)}">
              <datalist id="mqMdLocais">${locais.map(l => `<option value="${h(l)}"></option>`).join('')}</datalist></div>
            <div class="form-group"><label for="mqMdObs">Observação</label><textarea id="mqMdObs" rows="3" maxlength="1000" placeholder="Endereço, responsável, o que falta…">${h(observacao)}</textarea></div>
          </form>
          <div class="modal-actions">
            <button type="button" class="secondary-action" data-mq-md-fechar>Cancelar</button>
            <button type="submit" form="mqMdForm" class="primary-action">${h(botao)}</button>
          </div>
        </div>`;
      document.body.appendChild(wrap);
      if (window.lucide) lucide.createIcons();
      const fechar = v => { document.removeEventListener('keydown', onKey, true); wrap.remove(); resolve(v); };
      const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); fechar(null); } };
      document.addEventListener('keydown', onKey, true);
      wrap.querySelectorAll('[data-mq-md-fechar]').forEach(b => b.onclick = () => fechar(null));
      wrap.querySelector('#mqMdForm').onsubmit = e => {
        e.preventDefault();
        const n = wrap.querySelector('#mqMdNome').value.trim(); if (!n) return;
        fechar({ nome: n, local: wrap.querySelector('#mqMdLocal').value.trim(), observacao: wrap.querySelector('#mqMdObs').value.trim() });
      };
      setTimeout(() => { const i = wrap.querySelector('#mqMdNome'); i.focus(); i.select(); }, 30);
    });
  }

  async function escolherArquivo(e) {
    const f = e.target.files && e.target.files[0]; e.target.value = '';
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) return toast('Envie a planta em PDF.', true);
    const dados = await modalDados({ titulo: 'Nova maquete', sub: f.name, nome: nomeDoArquivo(f.name), local: '', observacao: '', botao: 'Enviar planta' });
    if (!dados) return;
    const fd = new FormData();
    fd.append('arquivo', f); fd.append('nome', dados.nome); fd.append('local', dados.local); fd.append('observacao', dados.observacao);
    toast('Enviando a planta…');
    const r = await api('/api/maquete/projetos', { method: 'POST', body: fd });
    const d = r ? await r.json().catch(() => ({})) : {};
    if (!r || !r.ok) return toast(d.detail || 'Não foi possível enviar a planta.', true);
    toast('Planta enviada. Lendo as paredes…');
    await atualizarLista();
  }

  async function editarDados(p) {
    const dados = await modalDados({ titulo: 'Dados do projeto', sub: p.arquivo, nome: p.nome, local: p.local || '', observacao: p.observacao || '', botao: 'Salvar' });
    if (!dados) return null;
    const r = await api(`/api/maquete/projetos/${encodeURIComponent(p.id)}`, { method: 'PUT', body: JSON.stringify(dados) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não foi possível salvar.', true); return null; }
    Object.assign(p, dados);
    toast('Dados salvos.');
    if (!proj) renderLista(false);
    return dados;
  }

  async function excluirProjeto(id) {
    const r = await api(`/api/maquete/projetos/${encodeURIComponent(id)}`, { method: 'DELETE', body: '' });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; return toast(d.detail || 'Não foi possível excluir.', true); }
    toast('Projeto excluído.');
    proj = null; pararEditor(); renderLista(false); atualizarLista();
  }

  // ======================================================================
  // EDITOR
  // ======================================================================
  async function abrir(id) {
    clearTimeout(poll);
    const sec = secao();
    sec.innerHTML = '<div class="mq-card mq-vazio">Abrindo a maquete…</div>';
    try {
      const [r] = await Promise.all([api(`/api/maquete/projetos/${encodeURIComponent(id)}`), garantirThree(), carregarCadastro(), carregarPrecos()]);
      const d = r && r.ok ? await r.json() : null;
      if (!d?.projeto) throw new Error('Projeto não encontrado.');
      proj = d.projeto;
    } catch (err) {
      toast(err.message || 'Não foi possível abrir.', true);
      return window.loadMaquete();
    }
    L = normalizarLayout(proj.layout || {}, proj.leitura);
    semPermissao = false; sujo = false;
    montarEditor();
  }

  async function carregarCadastro() {
    const porChave = {}, porRotulo = {}, porIp = {}, lista = [];
    for (const m of ['basico', 'switch', 'olt']) {
      const d = await apiJson(`/api/cameras?mode=${m}`).catch(() => null);
      (d?.cameras || []).forEach(c => {
        const ip = String(c.ip || '').trim(); if (!ip) return;
        const site = String(c.site || c.site_name || c.local || '').trim();
        const chave = site + '|' + ip; if (porChave[chave]) return;
        const titulo = String(c.titulo || c.name || ip);
        const item = { chave, ip, titulo, site, status: String(c.status || '').toLowerCase(), rotulo: `${titulo} — ${ip}${site ? ' — ' + site : ''}` };
        porChave[chave] = item; porRotulo[item.rotulo] = item; (porIp[ip] = porIp[ip] || []).push(item); lista.push(item);
      });
    }
    lista.sort((a, b) => (a.site + a.titulo).localeCompare(b.site + b.titulo, 'pt', { numeric: true }));
    cadastro = { porChave, porRotulo, porIp, lista };
  }

  function normalizarLayout(l, leitura) {
    const pisos = leitura.pisos || [];
    const p0 = pisos[0] || { id: 'p0', largura: 10, profundidade: 10 };
    const out = {
      versao: 1,
      pd: Object.assign({}, l.pd || {}),
      cams: Array.isArray(l.cams) ? l.cams : [],
      nodes: Array.isArray(l.nodes) ? l.nodes : [],
      rack: l.rack && Array.isArray(l.rack.itens) ? l.rack : { tam: '12', rot: 180, itens: [{ k: 'pp6', u: 12 }, { k: 'org', u: 11 }, { k: 'sw16', u: 10 }, { k: 'nvr16', u: 9 }, { k: 'regua', u: 8 }] },
      catCabo: CAT[l.catCabo] ? l.catCabo : 'cat6',
      nomes: l.nomes && typeof l.nomes === 'object' ? Object.assign({}, l.nomes) : {},
      orc: Object.assign({ precos: {}, qtd: {}, desc: {}, ocultos: [], avulsos: [], desconto_pct: 0, validade_dias: 15,
        condicoes: ['Pagamento: 50% na aprovação e 50% na entrega.', 'Prazo de instalação: a combinar.',
          'Garantia: 12 meses para equipamentos e 90 dias para a instalação.'].join('\n'), noRelatorio: true },
        l.orc && typeof l.orc === 'object' ? l.orc : {}),
      seq: Number(l.seq || 1),
    };
    pisos.forEach((p, i) => { if (!(out.pd[p.id] > 0)) out.pd[p.id] = i === 0 ? 3.0 : 2.8; });
    if (!out.nodes.some(n => n.tipo === 'rack')) out.nodes.unshift({ id: 'rack', tipo: 'rack', nome: 'Rack', piso: p0.id, x: Math.max(0.5, p0.largura - 0.8), y: Math.max(0.5, p0.profundidade - 0.8), pai: null });
    // uma prumada por pavimento acima do primeiro, ligada ao de baixo
    for (let i = 1; i < pisos.length; i++) {
      if (out.nodes.some(n => n.tipo === 'prumada' && n.piso === pisos[i].id)) continue;
      const abaixo = i === 1 ? 'rack' : (out.nodes.find(n => n.tipo === 'prumada' && n.piso === pisos[i - 1].id) || {}).id || 'rack';
      out.nodes.push({ id: 'pr_' + pisos[i].id, tipo: 'prumada', nome: 'Prumada ' + pisos[i].nome, piso: pisos[i].id, x: pisos[i].largura / 2, y: pisos[i].profundidade / 2, pai: abaixo });
    }
    // remove o que aponta para pavimento que não existe mais
    const ids = new Set(pisos.map(p => p.id));
    out.cams = out.cams.filter(c => ids.has(c.piso));
    out.nodes = out.nodes.filter(n => ids.has(n.piso));
    return out;
  }

  function marcarMudanca() {
    if (semPermissao) return;
    sujo = true;
    $('mqSalvo') && ($('mqSalvo').textContent = 'Alterações não salvas');
    clearTimeout(salvarTimer);
    salvarTimer = setTimeout(salvar, 1500);
  }
  async function salvar() {
    if (!proj || salvando) { if (proj) salvarTimer = setTimeout(salvar, 800); return; }
    salvando = true;
    const el = $('mqSalvo'); if (el) el.textContent = 'Salvando…';
    try {
      L.resumo = { metros: Math.round([...caminhos.values()].reduce((a, x) => a + x.len, 0) * 10) / 10, caixas: L.nodes.filter(n => n.tipo === 'caixa').length };
      const r = await api(`/api/maquete/projetos/${encodeURIComponent(proj.id)}`, { method: 'PUT', body: JSON.stringify({ layout: L }) });
      if (r && r.status === 403) { semPermissao = true; if (el) el.textContent = 'Sem permissão para salvar'; return; }
      if (!r || !r.ok) throw new Error();
      sujo = false;
      if (el) el.textContent = 'Salvo ' + new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } catch (_) {
      if (el) el.textContent = 'Não salvou. Tentando de novo…';
      salvarTimer = setTimeout(salvar, 5000);
    } finally { salvando = false; }
  }


  // ---------- 3D: variáveis do editor ----------
  let R3 = null; // { renderer, scene, camera, controls, ... }
  let PISOS = [], W = 10, P = 10, OX = 0, OZ = 0;
  let grupos = {}, pisoMesh = {}, vis = {}, din = null, alvos = [], labels = [], caminhos = new Map(), contagem = {};
  let sel = null, modoAdd = null, drag = null, downPt = null, pend = false, voo = null, abaAtual = 'maquete';
  let rkSel = null, rkArr = null, catSel = 'pp6', addTop = null, addBase = null;
  let tex = {};

  function pararEditor() {
    clearTimeout(salvarTimer);
    if (sujo && proj) salvar();
    if (R3) {
      cancelAnimationFrame(R3.raf);
      window.removeEventListener('pointermove', R3.onMove);
      window.removeEventListener('pointerup', R3.onUp);
      if (R3.onKey) window.removeEventListener('keydown', R3.onKey);
      R3.ro && R3.ro.disconnect();
      try { R3.renderer.dispose(); } catch (_) {}
      Object.values(tex).forEach(t => { try { t.dispose(); } catch (_) {} });
      Object.values(R3.urls || {}).forEach(u => URL.revokeObjectURL(u));
      R3 = null;
    }
    tex = {};
  }

  function subTitulo() { return [proj.local || 'Sem local', proj.arquivo].filter(Boolean).join(' · '); }

  function montarEditor() {
    const sec = secao();
    PISOS = (proj.leitura.pisos || []).map(p => Object.assign({}, p, { nomeLido: p.nome, nome: L.nomes[p.id] || p.nome }));
    W = Math.max(...PISOS.map(p => p.largura)); P = Math.max(...PISOS.map(p => p.profundidade));
    OX = -W / 2; OZ = -P / 2;
    sel = null; modoAdd = null; rkSel = null; abaAtual = 'maquete';
    vis = {}; PISOS.forEach(p => vis[p.id] = true);
    const legenda = '<span><i class="mq-dot mq-d-on"></i>Online</span><span><i class="mq-dot mq-d-off"></i>Offline</span><span><i class="mq-dot mq-d-new"></i>Projeto</span><span><i class="mq-sw" style="background:var(--cyan,#0b7285)"></i>Cabo UTP</span>';
    sec.innerHTML = `
      <div class="mq-ehead">
        <button class="mq-btn sm" type="button" id="mqVoltar" title="Voltar para os projetos">← Projetos</button>
        <div class="mq-etit"><b id="mqNome" title="${h(proj.nome)}">${h(proj.nome)}</b><small id="mqSubTit">${h(subTitulo())}</small></div>
        <span class="mq-salvo" id="mqSalvo">Salvo</span>
        <button class="mq-btn sm" type="button" id="mqPdf" title="Relatório A4 com as vistas da maquete, câmeras, cabos e rack">Relatório PDF</button>
        <button class="mq-btn sm" type="button" id="mqEditar">Editar dados</button>
        <button class="mq-btn sm del" type="button" id="mqExcluir">Excluir</button>
      </div>
      <div class="mq-tabs" role="tablist">
        <button class="mq-tab on" role="tab" data-mq-aba="maquete" type="button">Maquete</button>
        <button class="mq-tab" role="tab" data-mq-aba="rack" type="button">Rack <span class="mq-cnt" id="mqTRack"></span></button>
        <button class="mq-tab" role="tab" data-mq-aba="cabos" type="button">Cabos <span class="mq-cnt" id="mqTCabos"></span></button>
        <button class="mq-tab" role="tab" data-mq-aba="orc" type="button">Orçamento <span class="mq-cnt" id="mqTOrc"></span></button>
      </div>

      <div class="mq-content" id="mqAbaMaquete">
        <section class="mq-view" aria-label="Maquete 3D">
          <canvas id="mqCv"></canvas>
          <div id="mqLabels"></div>
          <div class="mq-bar">
            <div class="mq-seg" role="group" aria-label="Pavimento">
              <button type="button" data-mq-f="todos" class="on">Todos</button>
              ${PISOS.map(p => `<button type="button" data-mq-f="${h(p.id)}">${h(p.nome)}</button>`).join('')}
            </div>
            <div class="mq-seg" role="group" aria-label="Vista">
              <button type="button" data-mq-v="3d" class="on">3D</button>
              <button type="button" data-mq-v="top">De cima</button>
            </div>
            <span class="mq-grow"></span>
            <div class="mq-seg" role="group" aria-label="Adicionar">
              <button type="button" data-mq-add="cam">+ <span class="lbl">Câmera</span></button>
              <button type="button" data-mq-add="caixa">+ <span class="lbl">Caixa de passagem</span></button>
            </div>
          </div>
          <div class="mq-hint" id="mqHint">Puxe o cabo ou a calha para mudar o caminho · duplo clique numa curva desfaz · arraste o fundo para girar</div>
          <div class="mq-legend">${legenda}</div>
        </section>
        <aside class="mq-panel">
          <div class="mq-card" id="mqSelCard"></div>
          <div class="mq-card"><h2><span class="nm">Câmeras</span><span class="r"><span class="mq-pill mq-p-blue" id="mqNCam"></span></span></h2><div class="mq-cams" id="mqCams"></div></div>
          <div class="mq-card">
            <h2>Mostrar</h2>
            <label class="mq-chk"><input type="checkbox" id="mqCPlanta" checked>Desenho da planta no piso</label>
            <label class="mq-chk"><input type="checkbox" id="mqCCones" checked>Campo de visão</label>
            <label class="mq-chk"><input type="checkbox" id="mqCCabos" checked>Cabos<i class="mq-sw" style="background:var(--cyan,#0b7285)"></i></label>
            <label class="mq-chk"><input type="checkbox" id="mqCCalha" checked>Eletrocalha e caixas<i class="mq-sw" style="background:#9aa5ad"></i></label>
            <label class="mq-chk"><input type="checkbox" id="mqCApto" checked>Nome das unidades</label>
            <div class="mq-rng" style="margin-top:8px"><label for="mqExp">Afastar</label><input type="range" id="mqExp" min="0" max="8" step="0.1" value="0"><output id="mqOExp">0 m</output></div>
          </div>
          <div class="mq-card">
            <h2><span class="nm">Leitura da planta</span><span class="r"><span class="mq-pill mq-p-ok">Pronta</span></span></h2>
            <div class="mq-muted" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:8px" title="${h(proj.arquivo)}">${h(proj.arquivo)}</div>
            <dl class="mq-dl">
              <dt>Escala</dt><dd>${h(proj.leitura.escala || '')}</dd>
            </dl>
            ${PISOS.map(p => `<div class="mq-piso">
              <input class="mq-inp" data-mq-nomepiso="${h(p.id)}" value="${h(p.nome)}" maxlength="40" aria-label="Nome do pavimento" title="Lido na planta: ${h(p.nomeLido)}">
              <input class="mq-inp" data-mq-pd="${h(p.id)}" type="number" step="0.05" min="2.2" max="8" value="${Number(L.pd[p.id]).toFixed(2)}" aria-label="Pé-direito de ${h(p.nome)} em metros" style="text-align:right">
              <small>${fmt(p.largura, 2)} × ${fmt(p.profundidade, 2)} m</small><label>pé-direito (m)</label>
            </div>`).join('')}
            <div class="mq-note">Dê nome aos pavimentos e confira as medidas com a cota da planta. O pé-direito normalmente está no corte; ajuste aqui.</div>
          </div>
        </aside>
      </div>

      <div class="mq-content" id="mqAbaRack" hidden>
        <div class="mq-kpi"><small>Câmeras com porta</small><b id="mqKPortas"></b><div class="mq-meter"><i id="mqMPortas"></i></div><em id="mqEPortas"></em></div>
        <div class="mq-kpi"><small>Consumo PoE</small><b id="mqKPoe"></b><div class="mq-meter"><i id="mqMPoe"></i></div><em id="mqEPoe"></em></div>
        <div class="mq-kpi"><small>Canais do gravador</small><b id="mqKNvr"></b><div class="mq-meter"><i id="mqMNvr"></i></div><em id="mqENvr"></em></div>
        <div class="mq-kpi"><small>Espaço no rack</small><b id="mqKU"></b><div class="mq-meter"><i id="mqMU"></i></div><em id="mqEU"></em></div>
        <div class="mq-card mq-s4">
          <h2><span class="nm">Montagem</span><span class="r"><select class="mq-inp" id="mqRkTam" style="height:30px;width:auto" aria-label="Tamanho do rack"></select></span></h2>
          <div class="mq-rkwrap">
            <div class="mq-rk" id="mqRk"></div>
            <div id="mqRkFora"></div>
            <div class="mq-rkbox" id="mqRkSelBox" hidden>
              <div class="mq-rkhead"><b id="mqRkSelNome"></b><span class="mq-pill mq-p-grey" id="mqRkSelU"></span></div>
              <div class="mq-rktools">
                <label class="mq-muted" for="mqRkPos">Mover para</label>
                <select class="mq-inp" id="mqRkPos"></select>
                <button class="mq-btn sm" id="mqRkUp" type="button" title="Subir" aria-label="Subir para a próxima posição livre">↑</button>
                <button class="mq-btn sm" id="mqRkDn" type="button" title="Descer" aria-label="Descer para a próxima posição livre">↓</button>
                <button class="mq-btn sm del" id="mqRkRm" type="button">Remover</button>
              </div>
            </div>
            <div class="mq-rkbox">
              <div class="mq-rkhead"><b>Adicionar equipamento</b></div>
              <select class="mq-inp" id="mqRkCat" aria-label="Equipamento"></select>
              <div class="mq-rktools">
                <label class="mq-muted" for="mqRkAddPos">Na posição</label>
                <select class="mq-inp" id="mqRkAddPos"></select>
                <button class="mq-btn sm pri" id="mqRkAdd" type="button">Adicionar</button>
              </div>
            </div>
            <div class="mq-muted">Arraste um equipamento para qualquer U livre ou escolha a posição na lista. Clique numa U livre para adicionar ali.</div>
          </div>
        </div>
        <div class="mq-card mq-s8">
          <h2><span class="nm">Cabos chegando no rack</span><span class="r"><span class="mq-pill mq-p-grey" id="mqRkLoc"></span></span></h2>
          <div class="mq-note" id="mqRkAviso" hidden style="margin:0 0 12px"></div>
          <div class="mq-tw"><table class="mq-table">
            <colgroup><col style="width:64px"><col><col style="width:110px"><col style="width:110px"><col style="width:100px"><col style="width:80px"><col style="width:80px"></colgroup>
            <thead><tr><th>Cabo</th><th>Câmera</th><th>Patch panel</th><th>Switch</th><th>Gravador</th><th class="n">PoE</th><th class="n">Metros</th></tr></thead>
            <tbody id="mqTbRack"></tbody>
          </table></div>
        </div>
      </div>

      <div class="mq-content" id="mqAbaOrc" hidden></div>

      <div class="mq-content" id="mqAbaCabos" hidden>
        <div class="mq-kpi"><small>Cabos</small><b id="mqKCab"></b><em id="mqECab"></em></div>
        <div class="mq-kpi"><small>Metragem</small><b id="mqKM"></b><em id="mqEM"></em></div>
        <div class="mq-kpi"><small>Com 10% de perda</small><b id="mqKM10"></b><em>Para compra</em></div>
        <div class="mq-kpi"><small>Caixas de 305 m</small><b id="mqKBob"></b><em id="mqEBob"></em></div>
        <div class="mq-card mq-s12">
          <h2><span class="nm">Caminho de cada cabo</span><span class="r"><label class="mq-muted" for="mqCabCat" style="font-weight:500">Categoria</label><select class="mq-inp" id="mqCabCat" style="height:30px;width:auto">${Object.entries(CAT).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></span></h2>
          <div class="mq-note" id="mqCabAviso" hidden style="margin:0 0 12px"></div>
          <div class="mq-tw"><table class="mq-table" style="min-width:820px">
            <colgroup><col style="width:64px"><col style="width:220px"><col style="width:110px"><col style="width:200px"><col><col style="width:90px"><col style="width:80px"></colgroup>
            <thead><tr><th>Cabo</th><th>Câmera</th><th>Pavimento</th><th>Modelo</th><th>Passa por</th><th>Porta</th><th class="n">Metros</th></tr></thead>
            <tbody id="mqTbCabos"></tbody>
            <tfoot><tr><td colspan="6">Total (inclui 3 m de folga no rack e 0,5 m na câmera)</td><td class="n" id="mqTfM"></td></tr></tfoot>
          </table></div>
          <div class="mq-muted" style="margin-top:12px">Medida pelo caminho da eletrocalha: sobe da câmera até a calha, segue pelas caixas, desce pela prumada e entra no rack. Arraste as caixas na maquete e a metragem muda.</div>
        </div>
      </div>`;
    ligarEventosFixos();
    iniciar3D();
  }

  // ======================================================================
  // CÂMERAS: cálculo
  // ======================================================================
  function fovDe(c) { const m = MOD[c.mod] || MOD.d2_28; return m.vari ? 2 * Math.atan(3.337 / (c.foco || m.vari[0])) * 180 / Math.PI : m.fov; }
  function dori(c) {
    const m = MOD[c.mod] || MOD.d2_28, f = fovDe(c); if (f >= 180) return null;
    const t = 2 * Math.tan(f * Math.PI / 360);
    return { ident: m.res / (t * 250), recon: m.res / (t * 125), obs: m.res / (t * 62) };
  }
  function alcance(c) { const d = dori(c), m = MOD[c.mod] || MOD.d2_28; return d ? Math.min(d.obs, m.ir, 22) : 6; }
  function cadDe(c) {
    if (c.cad && cadastro.porChave[c.cad]) return cadastro.porChave[c.cad];
    const doIp = c.ip ? cadastro.porIp[c.ip] || [] : [];
    return doIp.length === 1 ? doIp[0] : null;   // IP repetido em dois locais: não chuta
  }
  function stDe(c) {
    if (!c.ip && !c.cad) return 'new';
    const k = cadDe(c); if (!k) return 'unk';
    return k.status === 'online' ? 'on' : k.status === 'offline' ? 'off' : 'unk';
  }
  const pisoById = id => PISOS.find(p => p.id === id) || PISOS[0];
  const pisoIdx = id => Math.max(0, PISOS.findIndex(p => p.id === id));
  const Hp = id => Math.max(2.2, Number(L.pd[id]) || 2.8);
  const trayH = id => Hp(id) - 0.25;
  function base(id) { return grupos[id] ? grupos[id].position.y : 0; }
  function camAlt(c) { return Math.min(c.alt ?? (Hp(c.piso) - 0.3), Hp(c.piso) - 0.1); }

  // ======================================================================
  // RACK: posições
  // ======================================================================
  const topo = o => o.u + IT[o.k].u - 1;
  const rotU = (k, u) => IT[k].u > 1 ? 'U' + (u + IT[k].u - 1) + '–' + u : 'U' + u;
  const ordemRack = () => L.rack.itens.filter(o => IT[o.k]).slice().sort((a, b) => topo(b) - topo(a));
  const dentro = o => topo(o) <= RACKS[L.rack.tam].u;
  function cabe(k, b, ignorar) {
    const R = RACKS[L.rack.tam], hh = IT[k].u; if (b < 1 || b + hh - 1 > R.u) return false;
    return L.rack.itens.every(o => o === ignorar || !IT[o.k] || topo(o) < b || o.u > b + hh - 1);
  }
  function posicoes(k, ignorar) { const out = []; for (let b = RACKS[L.rack.tam].u - IT[k].u + 1; b >= 1; b--) if (cabe(k, b, ignorar)) out.push(b); return out; }
  function baseEm(k, u, ignorar) { for (let b = u - IT[k].u + 1; b <= u; b++) if (cabe(k, b, ignorar)) return b; return null; }

  // ======================================================================
  // 3D
  // ======================================================================
  const V = (x, y, z) => new THREE.Vector3(x, y, z);
  function iniciar3D() {
    const cv = $('mqCv'), view = cv.parentElement;
    const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputEncoding = THREE.sRGBEncoding;
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0xf3f5f7);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 600);
    const controls = new THREE.OrbitControls(camera, cv);
    controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.495;
    scene.add(new THREE.HemisphereLight(0xffffff, 0xc9d1d6, 0.75));
    const sun = new THREE.DirectionalLight(0xffffff, 0.55);
    const ext = Math.max(W, P) / 2 + 8;
    sun.position.set(-ext, ext * 1.4, ext * 0.6); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 1, far: ext * 4 });
    scene.add(sun);
    const chao = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshLambertMaterial({ color: 0xe9edf0 }));
    chao.rotation.x = -Math.PI / 2; chao.position.y = -0.02; chao.receiveShadow = true; scene.add(chao);
    const grade = new THREE.GridHelper(400, 400, 0xd5dbe0, 0xdfe4e8); grade.position.y = -0.01; scene.add(grade);
    grupos = {}; PISOS.forEach(p => { grupos[p.id] = new THREE.Group(); scene.add(grupos[p.id]); });
    din = new THREE.Group(); scene.add(din);
    R3 = {
      renderer, scene, camera, controls, view, cv, urls: {},
      mat: {
        parede: new THREE.MeshLambertMaterial({ color: 0xf8fafb }),
        topo: new THREE.MeshBasicMaterial({ color: 0x13252d }),
        vidro: new THREE.MeshLambertMaterial({ color: 0x9fd3e6, transparent: true, opacity: 0.45, depthWrite: false }),
        laje: new THREE.MeshLambertMaterial({ color: 0xdfe4e8 }),
        calha: new THREE.MeshLambertMaterial({ color: 0x9aa5ad }),
        caixa: new THREE.MeshLambertMaterial({ color: 0x66747e }),
        cabo: new THREE.LineBasicMaterial({ color: 0x0b7285 }),
        inv: new THREE.MeshBasicMaterial({ visible: false }),
      },
      caixa: new THREE.BoxGeometry(1, 1, 1),
    };
    // texturas: busca com o token e vira blob local
    PISOS.forEach(p => {
      tex[p.id] = new THREE.Texture();
      api(`/api/maquete/projetos/${encodeURIComponent(proj.id)}/textura/${encodeURIComponent(p.textura)}`).then(async r => {
        if (!r || !r.ok || !R3) return;
        const url = URL.createObjectURL(await r.blob()); R3.urls[p.id] = url;
        new THREE.TextureLoader().load(url, t => {
          if (!R3) return;
          t.encoding = THREE.sRGBEncoding; t.anisotropy = renderer.capabilities.getMaxAnisotropy();
          tex[p.id] = t; if (pisoMesh[p.id] && $('mqCPlanta')?.checked) { pisoMesh[p.id].material.map = t; pisoMesh[p.id].material.needsUpdate = true; }
        });
      });
    });
    reconstruir();
    aplicaPisos('todos');
    painelSel();
    const d = Math.max(W, P);
    camera.position.set(-d * 0.55, d * 0.6, d * 0.75); controls.target.set(0, 1.5, 0);
    R3.ro = new ResizeObserver(tamanho); R3.ro.observe(view);
    ligarPonteiro();
    tamanho();
    const reduz = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const laco = () => {
      if (!R3) return;
      R3.raf = requestAnimationFrame(laco);
      if (!secao() || secao().classList.contains('hidden') || abaAtual !== 'maquete') return;
      if (pend) { pend = false; montarDin(); }
      if (voo) {
        voo.t = reduz ? 1 : Math.min(1, voo.t + 0.035); const k = 1 - Math.pow(1 - voo.t, 3);
        controls.target.lerpVectors(voo.a0, voo.a1, k); camera.position.lerpVectors(voo.p0, voo.p1, k); if (voo.t >= 1) voo = null;
      }
      controls.update(); renderer.render(scene, camera); posRotulos();
    };
    laco();
  }
  function tamanho() {
    if (!R3) return; const w = R3.view.clientWidth, hh = R3.view.clientHeight; if (!w || !hh) return;
    R3.renderer.setSize(w, hh, false); R3.camera.aspect = w / hh; R3.camera.updateProjectionMatrix();
  }
  function instanciar(lista, mat, sombra) {
    const im = new THREE.InstancedMesh(R3.caixa, mat, Math.max(lista.length, 1)), m = new THREE.Matrix4();
    lista.forEach((b, i) => { m.compose(V(b[0], b[1], b[2]), new THREE.Quaternion(), V(b[3], b[4], b[5])); im.setMatrixAt(i, m); });
    im.count = lista.length; im.castShadow = im.receiveShadow = sombra; return im;
  }
  function montarPiso(p) {
    const g = grupos[p.id], Hh = Hp(p.id), mat = R3.mat;
    while (g.children.length) { const c = g.children[0]; g.remove(c); if (c.geometry && c.geometry !== R3.caixa) c.geometry.dispose(); }
    const piso = new THREE.Mesh(new THREE.PlaneGeometry(p.largura, p.profundidade), new THREE.MeshLambertMaterial({ map: $('mqCPlanta').checked && tex[p.id].image ? tex[p.id] : null }));
    piso.rotation.x = -Math.PI / 2; piso.position.set(OX + p.largura / 2, 0.005, OZ + p.profundidade / 2);
    piso.receiveShadow = true; piso.userData.piso = p.id; g.add(piso); pisoMesh[p.id] = piso;
    if (pisoIdx(p.id) > 0) {
      const laje = new THREE.Mesh(R3.caixa, mat.laje);
      laje.scale.set(p.largura, 0.12, p.profundidade); laje.position.set(OX + p.largura / 2, -0.06, OZ + p.profundidade / 2);
      laje.castShadow = laje.receiveShadow = true; g.add(laje);
    }
    const corpo = [], top = [], vidro = [];
    const bloco = (b, y0, y1, arr) => arr.push([OX + (b[0] + b[2]) / 2, (y0 + y1) / 2, OZ + (b[1] + b[3]) / 2, b[2] - b[0], y1 - y0, b[3] - b[1]]);
    (p.paredes || []).forEach(b => { bloco(b, 0, Hh, corpo); bloco(b, Hh, Hh + 0.012, top); });
    (p.vaos || []).forEach(v => {
      const j = JAN[v[4]] || (/^J\d/.test(v[4]) ? [1.0, 1.4] : null);
      if (j) {
        bloco(v, 0, j[0], corpo);
        const t = Math.min(v[2] - v[0], v[3] - v[1]);
        const fino = v[2] - v[0] < v[3] - v[1] ? [v[0] + t * 0.4, v[1], v[2] - t * 0.4, v[3]] : [v[0], v[1] + t * 0.4, v[2], v[3] - t * 0.4];
        bloco(fino, j[0], Math.min(j[0] + j[1], Hh - 0.05), vidro);
        if (j[0] + j[1] < Hh) bloco(v, j[0] + j[1], Hh, corpo);
      } else if (Hh > 2.1) bloco(v, 2.10, Hh, corpo);
      bloco(v, Hh, Hh + 0.012, top);
    });
    g.add(instanciar(corpo, mat.parede, true), instanciar(top, mat.topo, false), instanciar(vidro, mat.vidro, false));
  }
  function reconstruir() {
    const e = Number($('mqExp')?.value || 0); let y = 0;
    PISOS.forEach((p, i) => { montarPiso(p); grupos[p.id].position.y = y; y += Hp(p.id) + 0.12 + e; });
    montarDin();
  }

  // ---------- caminho dos cabos ----------
  const byId = id => L.nodes.find(n => n.id === id);
  const rackNode = () => L.nodes.find(n => n.tipo === 'rack');
  function trayPt(n, piso) { return V(OX + n.x, base(piso) + trayH(piso), OZ + n.y); }
  function rackDim() { const R = RACKS[L.rack.tam]; return Object.assign({}, R, { h: R.u * 0.0445 + 0.12 }); }
  function rackTop() { const r = rackNode(), R = rackDim(); return V(OX + r.x, base(r.piso) + R.base + R.h, OZ + r.y); }
  function segmentos(piso) {
    const out = [];
    L.nodes.forEach(n => {
      if (!n.pai) return; const p = byId(n.pai); if (!p) return;
      const f = n.tipo === 'prumada' ? p.piso : n.piso;
      if (f === piso) out.push({ n, p, A: trayPt(n, f), B: trayPt(p, f) });
    });
    if (!out.length) {
      const alvo = L.nodes.find(n => n.tipo === 'prumada' && n.piso === piso) || rackNode();
      out.push({ n: alvo, p: alvo, A: trayPt(alvo, piso), B: trayPt(alvo, piso) });
    }
    return out;
  }
  function rumo(node, f) {
    const pts = [trayPt(node, f)], via = []; let cur = node, cf = f, guarda = 0;
    while (cur.pai && guarda++ < 200) {
      const p = byId(cur.pai); if (!p) break;
      if (cur.tipo === 'prumada') { pts.push(trayPt(cur, p.piso)); cf = p.piso; via.push('Prumada'); }
      else via.push(cur.nome);
      pts.push(trayPt(p, cf)); cur = p;
    }
    pts.push(rackTop());
    return { pts, via };
  }
  // Onde o cabo pode entrar na calha neste pavimento: caixas do andar, a
  // prumada que chega nele e o rack (se o rack estiver neste andar).
  function entradasDe(piso) {
    return L.nodes.filter(n => (n.tipo === 'caixa' && n.piso === piso) || (n.tipo === 'prumada' && n.piso === piso) || (n.tipo === 'rack' && n.piso === piso));
  }
  function caminho(c, idx) {
    const f = c.piso, cp = V(OX + c.x, base(f) + camAlt(c), OZ + c.y), ty = base(f) + trayH(f);
    const wps = (Array.isArray(c.pts) ? c.pts : []).map(p => V(OX + p.x, ty, OZ + p.y));
    const ref = wps.length ? wps[wps.length - 1] : cp;   // a entrada é procurada a partir do último ponto
    const alvo = c.entrada ? entradasDe(f).find(n => n.id === c.entrada) : null;
    let entrada, r;
    if (alvo) {
      entrada = trayPt(alvo, f); r = rumo(alvo, f);
    } else {
      let best = null;
      segmentos(f).forEach(s => {
        const ab = s.B.clone().sub(s.A), l2 = ab.x * ab.x + ab.z * ab.z;
        let t = l2 ? ((ref.x - s.A.x) * ab.x + (ref.z - s.A.z) * ab.z) / l2 : 0; t = Math.max(0, Math.min(1, t));
        const q = V(s.A.x + ab.x * t, ty, s.A.z + ab.z * t), d = Math.hypot(q.x - ref.x, q.z - ref.z);
        if (!best || d < best.d) best = { d, q, s };
      });
      entrada = best.q; r = rumo(best.s.p, f);
    }
    // da câmera sobe até a altura da calha; sem pontos, faz um "L" até a entrada
    let pts = [cp, V(cp.x, ty, cp.z)];
    const cust = [];   // trechos do cabo antes da calha: puxar um deles cria uma curva no índice `ins`
    if (wps.length) {
      pts.push(...wps, entrada);
      const seq = [pts[1], ...wps, entrada];
      for (let i = 0; i < seq.length - 1; i++) cust.push({ A: seq[i], B: seq[i + 1], ins: i });
    } else {
      const canto = Math.abs(entrada.x - cp.x) > Math.abs(entrada.z - cp.z) ? V(cp.x, ty, entrada.z) : V(entrada.x, ty, cp.z);
      pts.push(canto, entrada);
      cust.push({ A: pts[1], B: canto, ins: 0 }, { A: canto, B: entrada, ins: 0 });
    }
    pts.push(...r.pts);
    pts = pts.filter((p, i) => i === 0 || p.distanceToSquared(pts[i - 1]) > 1e-6);
    let len = 0; for (let i = 1; i < pts.length; i++) len += pts[i].distanceTo(pts[i - 1]);
    const o = ((idx % 7) - 3) * 0.022;
    return { pts: pts.map((p, i) => (i === 0 ? p.clone() : p.clone().add(V(o, 0, o)))), len: len + 3.5, via: r.via, cust };
  }
  const ordenadas = () => L.cams.slice().sort((a, b) => String(a.nome).localeCompare(String(b.nome), 'pt', { numeric: true }));
  function ligacoes() {
    const pp = [], sw = [], nv = [];
    ordemRack().filter(dentro).forEach(o => {
      const it = IT[o.k];
      if (it.t === 'patch') pp.push({ o, n: it.portas }); if (it.t === 'switch' && it.poe > 0) sw.push({ o, n: it.portas, poe: it.poe }); if (it.t === 'nvr') nv.push({ o, n: it.canais });
    });
    const plano = lst => lst.flatMap(x => Array.from({ length: x.n }, (_, p) => ({ o: x.o, top: topo(x.o), porta: p + 1, varios: lst.length > 1 })));
    const P1 = plano(pp), S1 = plano(sw), N1 = plano(nv), m = new Map();
    // porta escolhida à mão primeiro; o resto ocupa as livres, na ordem das câmeras
    const usadas = new Set(), escolhida = new Map();
    ordenadas().forEach(c => {
      if (!c.pp) return;
      const o = L.rack.itens[c.pp.i];
      const slot = P1.find(s => s.o === o && s.porta === c.pp.porta);
      if (slot && !usadas.has(slot)) { usadas.add(slot); escolhida.set(c.id, slot); }
    });
    const livres = P1.filter(s => !usadas.has(s));
    let k = 0;
    ordenadas().forEach((c, i) => {
      const pSlot = escolhida.get(c.id) || livres[k++] || null;
      m.set(c.id, { cabo: 'C-' + String(i + 1).padStart(2, '0'), pp: pSlot, ppManual: escolhida.has(c.id), sw: S1[i] || null, nvr: N1[i] || null });
    });
    return { m, slots: P1, pp: P1.length, sw: S1.length, nvr: N1.length, poe: sw.reduce((a, s) => a + s.poe, 0) };
  }
  const rotPorta = p => p ? (p.varios ? 'U' + p.top + ' · ' : '') + 'porta ' + p.porta : '—';

  // ---------- objetos dinâmicos ----------
  function caixaEntre(a, b, larg, alt, mat) {
    const dx = b.x - a.x, dz = b.z - a.z, l = Math.hypot(dx, dz); if (l < 0.01) return null;
    const m = new THREE.Mesh(R3.caixa, mat); m.scale.set(l, alt, larg);
    m.position.set((a.x + b.x) / 2, a.y, (a.z + b.z) / 2); m.rotation.y = -Math.atan2(dz, dx); return m;
  }
  function arco(r, a0, a1, y, cor, op) {
    const pts = []; for (let i = 0; i <= 32; i++) { const t = a0 + (a1 - a0) * i / 32; pts.push(V(Math.cos(t) * r, y, Math.sin(t) * r)); }
    return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: cor, transparent: true, opacity: op }));
  }
  function objCam(c) {
    const m = MOD[c.mod] || MOD.d2_28, hh = camAlt(c), st = stDe(c), cor = COR[st], eSel = sel && sel.o === c;
    const o = new THREE.Group(); o.position.set(OX + c.x, base(c.piso), OZ + c.y);
    const cab = new THREE.Group(); cab.position.y = hh; cab.rotation.y = -c.dir * Math.PI / 180;
    const branco = new THREE.MeshLambertMaterial({ color: 0xffffff }), preto = new THREE.MeshBasicMaterial({ color: 0x172026 });
    if (m.tipo === 'bullet') {
      const corpo = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.15, 0.15), branco); corpo.rotation.z = -0.3;
      const lente = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.04, 16), preto); lente.rotation.z = Math.PI / 2; lente.position.x = 0.17;
      corpo.add(lente); cab.add(corpo);
      const braco = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.3, 8), new THREE.MeshLambertMaterial({ color: 0x66747e }));
      braco.position.y = hh + 0.15; o.add(braco);
    } else if (m.tipo === 'dome') {
      cab.add(new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.04, 24), branco));
      const bolha = new THREE.Mesh(new THREE.SphereGeometry(0.1, 20, 10, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), new THREE.MeshLambertMaterial({ color: 0x33464f, transparent: true, opacity: 0.85 }));
      bolha.position.y = -0.02; cab.add(bolha); cab.position.y = Hp(c.piso) - 0.02;
    } else {
      cab.add(new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.05, 28), branco));
      const l = new THREE.Mesh(new THREE.CircleGeometry(0.06, 20), preto); l.rotation.x = Math.PI / 2; l.position.y = -0.026; cab.add(l);
      cab.position.y = Hp(c.piso) - 0.03;
    }
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 8), new THREE.MeshBasicMaterial({ color: cor })); led.position.set(-0.05, 0.1, 0); cab.add(led);
    o.add(cab);
    const alvo = new THREE.Mesh(new THREE.SphereGeometry(0.5, 8, 6), R3.mat.inv); alvo.position.y = cab.position.y; alvo.userData.ref = { k: 'cam', o: c }; o.add(alvo); alvos.push(alvo);
    if ($('mqCCones').checked || eSel) {
      const f = fovDe(c) * Math.PI / 180, r = alcance(c), d = dori(c), y = 0.03, full = f >= Math.PI * 1.99;
      const g = full ? new THREE.CircleGeometry(r, 48) : new THREE.CircleGeometry(r, 40, -f / 2, f);
      const leque = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: cor, transparent: true, opacity: eSel ? 0.26 : 0.13, depthWrite: false, side: THREE.DoubleSide }));
      leque.rotation.x = -Math.PI / 2; leque.position.y = y; leque.scale.y = -1;
      const cone = new THREE.Group(); cone.add(leque); cone.rotation.y = full ? 0 : -c.dir * Math.PI / 180;
      if (!full) {
        cone.add(arco(r, -f / 2, f / 2, y + 0.005, cor, eSel ? 0.9 : 0.5));
        if (d && d.ident < r) cone.add(arco(d.ident, -f / 2, f / 2, y + 0.006, 0x1971c2, eSel ? 1 : 0.55));
        if (d && d.recon < r) cone.add(arco(d.recon, -f / 2, f / 2, y + 0.006, 0x0b7285, eSel ? 1 : 0.5));
        if (eSel) {
          const tp = V(0, cab.position.y, 0), pts = [];
          [-f / 2, f / 2].forEach(t => pts.push(tp, V(Math.cos(t) * r, y, Math.sin(t) * r)));
          cone.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: cor, transparent: true, opacity: 0.6 })));
        }
      } else cone.add(arco(r, 0, Math.PI * 2, y + 0.005, cor, eSel ? 0.9 : 0.5));
      o.add(cone);
    }
    o.userData.piso = c.piso; din.add(o);
    labels.push({ txt: (String(c.nome || 'Câmera').length > 22 ? String(c.nome).slice(0, 21) + '…' : String(c.nome || 'Câmera')), dot: ST[st][2], pos: V(OX + c.x, base(c.piso) + cab.position.y + 0.35, OZ + c.y), piso: c.piso, sel: eSel, cls: 'obj' });
  }
  function objRack() {
    const r = rackNode(), R = rackDim(), eSel = sel && sel.o === r;
    const o = new THREE.Group(); o.position.set(OX + r.x, base(r.piso), OZ + r.y); o.rotation.y = -(L.rack.rot || 0) * Math.PI / 180;
    const corpo = new THREE.Mesh(R3.caixa, new THREE.MeshLambertMaterial({ color: 0x13252d })); corpo.scale.set(R.w, R.h, R.d); corpo.position.y = R.base + R.h / 2;
    corpo.castShadow = true; o.add(corpo);
    const corT = { patch: 0xe9edf0, switch: 0x33464f, router: 0x0e5a69, nvr: 0x0f1c22, dio: 0x5b6b73, band: 0x5b6b73, org: 0x25363e, power: 0x172026, blank: 0x2a3b43 };
    L.rack.itens.filter(x => IT[x.k] && dentro(x)).forEach(x => {
      const it = IT[x.k];
      const s = new THREE.Mesh(R3.caixa, new THREE.MeshLambertMaterial({ color: corT[it.t] }));
      s.scale.set(R.w * 0.82, it.u * 0.0445 * 0.9, 0.02);
      s.position.set(0, R.base + 0.06 + (x.u - 1 + it.u / 2) * 0.0445, R.d / 2 + 0.011); o.add(s);
    });
    const alvo = new THREE.Mesh(R3.caixa, R3.mat.inv); alvo.scale.set(R.w + 0.3, R.h + 0.3, R.d + 0.3); alvo.position.y = R.base + R.h / 2;
    alvo.userData.ref = { k: 'node', o: r }; o.add(alvo); din.add(o); o.updateMatrixWorld(); alvos.push(alvo);
    o.userData.piso = r.piso;
    labels.push({ txt: 'Rack ' + R.u + 'U', pos: V(OX + r.x, base(r.piso) + R.base + R.h + 0.4, OZ + r.y), piso: r.piso, sel: eSel, cls: 'obj' });
  }
  function montarDin() {
    if (!R3) return;
    din.traverse(k => { if (k.geometry && k.geometry !== R3.caixa) k.geometry.dispose(); });
    while (din.children.length) din.remove(din.children[0]);
    alvos = []; labels = []; caminhos = new Map(); contagem = {};
    const calha = $('mqCCalha').checked, mat = R3.mat;
    metrosCalha = 0;
    PISOS.forEach(pv => segmentos(pv.id).forEach(s => {
      metrosCalha += s.A.distanceTo(s.B);
      const m = caixaEntre(s.A, s.B, 0.16, 0.05, mat.calha); if (m && calha) { m.userData.piso = pv.id; din.add(m); }
      const hb = calha && s.n !== s.p ? caixaEntre(s.A, s.B, 0.6, 0.45, mat.inv) : null;
      if (hb) { hb.userData.ref = { k: 'calha', s, piso: pv.id }; hb.userData.piso = pv.id; din.add(hb); alvos.push(hb); }
    }));
    L.nodes.forEach(n => {
      if (n.tipo === 'rack') return;
      const p = byId(n.pai), eSel = sel && sel.o === n;
      const pt = trayPt(n, n.piso);
      if (n.tipo === 'prumada' && p) {
        const a = trayPt(n, p.piso);
        metrosCalha += Math.max(0, pt.y - a.y);
        if (calha) { const v = new THREE.Mesh(R3.caixa, mat.calha); v.scale.set(0.16, Math.max(0.01, pt.y - a.y), 0.1); v.position.set(a.x, (a.y + pt.y) / 2, a.z); v.userData.piso = 'ambos'; din.add(v); }
        const alvo = new THREE.Mesh(R3.caixa, mat.inv); alvo.scale.set(0.6, Math.max(0.5, pt.y - a.y + 0.4), 0.6); alvo.position.set(a.x, (a.y + pt.y) / 2, a.z);
        alvo.userData.ref = { k: 'node', o: n }; alvo.userData.piso = 'ambos'; din.add(alvo); alvos.push(alvo);
      } else {
        const m = new THREE.Mesh(R3.caixa, eSel ? new THREE.MeshLambertMaterial({ color: 0x1971c2 }) : mat.caixa); m.scale.set(0.32, 0.14, 0.32); m.position.copy(pt); m.userData.piso = n.piso; din.add(m);
        const alvo = new THREE.Mesh(R3.caixa, mat.inv); alvo.scale.set(1.0, 0.7, 1.0); alvo.position.copy(pt);
        alvo.userData.ref = { k: 'node', o: n }; alvo.userData.piso = n.piso; din.add(alvo); alvos.push(alvo);
      }
      labels.push({ txt: n.nome, pos: pt.clone().add(V(0, 0.3, 0)), piso: n.piso, sel: eSel, cls: 'cx', calha: true });
    });
    // rack desce até a calha
    { const r = rackNode(), rt = rackTop(), rp = trayPt(r, r.piso);
      metrosCalha += Math.max(0, rp.y - rt.y);
      if (calha && rp.y > rt.y) { const d2 = new THREE.Mesh(R3.caixa, mat.calha); d2.scale.set(0.12, rp.y - rt.y, 0.08); d2.position.set(rt.x, (rt.y + rp.y) / 2, rt.z); d2.userData.piso = r.piso; din.add(d2); } }
    objRack();
    ordenadas().forEach((c, i) => {
      const r = caminho(c, i); caminhos.set(c.id, r);
      if ($('mqCCabos').checked || (sel && sel.o === c)) r.cust.forEach((t, j) => {
        let A = t.A; const d = t.A.distanceTo(t.B);
        if (j === 0) { if (d < 1.2) return; A = t.A.clone().lerp(t.B, 0.6 / d); }   // perto da câmera, pega a câmera
        const hb = caixaEntre(A, t.B, 0.45, 0.45, mat.inv);
        if (hb) { hb.userData.ref = { k: 'cabo', cam: c, ins: t.ins }; hb.userData.piso = c.piso; din.add(hb); alvos.push(hb); }
      });
      r.via.forEach(v => contagem[v] = (contagem[v] || 0) + 1);
      const eSel = sel && sel.o === c;
      if (!$('mqCCabos').checked && !eSel) return;
      let obj;
      if (eSel) {
        const path = new THREE.CurvePath(); for (let k = 1; k < r.pts.length; k++) path.add(new THREE.LineCurve3(r.pts[k - 1], r.pts[k]));
        obj = new THREE.Mesh(new THREE.TubeGeometry(path, r.pts.length * 8, 0.03, 6, false), new THREE.MeshBasicMaterial({ color: 0x1971c2 }));
      } else obj = new THREE.Line(new THREE.BufferGeometry().setFromPoints(r.pts), mat.cabo);
      obj.userData.piso = c.piso; din.add(obj);
    });
    L.cams.forEach(objCam);
    if (sel && sel.k === 'cam' && Array.isArray(sel.o.pts)) {
      const c = sel.o, ty = base(c.piso) + trayH(c.piso);
      c.pts.forEach((p, i) => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(0.12, 14, 10), new THREE.MeshBasicMaterial({ color: 0x1971c2 }));
        m.position.set(OX + p.x, ty, OZ + p.y); m.userData.piso = c.piso; din.add(m);
        const alvo = new THREE.Mesh(new THREE.SphereGeometry(0.45, 8, 6), R3.mat.inv);
        alvo.position.copy(m.position); alvo.userData.ref = { k: 'wp', o: p, cam: c }; alvo.userData.piso = c.piso; din.add(alvo); alvos.push(alvo);
        labels.push({ txt: String(i + 1), pos: m.position.clone().add(V(0, 0.35, 0)), piso: c.piso, sel: false, cls: 'cx' });
      });
    }
    aplicaVis(); montarRotulos(); resumoAbas(); listaCams();
    din.updateMatrixWorld(true);   // clique logo em seguida (duplo clique) já acerta os objetos novos
  }
  const redesenhar = () => { pend = true; };

  // ---------- rótulos ----------
  function montarRotulos() {
    const el = $('mqLabels'); if (!el) return;
    el.innerHTML = '';
    PISOS.forEach(p => (p.rotulos || []).forEach(a => labels.push({ txt: a[2], pos: V(OX + a[0], base(p.id) + 1.4, OZ + a[1]), piso: p.id, apto: true, cls: '' })));
    labels.forEach(Lb => {
      const d = document.createElement('div'); d.className = 'mq-lb ' + Lb.cls + (Lb.sel ? ' sel' : '');
      d.innerHTML = (Lb.dot ? `<i class="mq-dot ${Lb.dot}"></i>` : '') + h(Lb.txt); el.appendChild(d); Lb.el = d;
    });
  }
  function posRotulos() {
    const v3 = new THREE.Vector3(), w = R3.cv.clientWidth, hh = R3.cv.clientHeight, showA = $('mqCApto').checked, showC = $('mqCCalha').checked;
    labels.forEach(Lb => {
      let ok = (!grupos[Lb.piso] || grupos[Lb.piso].visible) && (!Lb.apto || showA) && (!Lb.calha || showC || Lb.sel);
      if (ok) { v3.copy(Lb.pos).project(R3.camera); ok = v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05; }
      Lb.el.style.display = ok ? '' : 'none';
      if (ok) { Lb.el.style.left = ((v3.x + 1) / 2 * w) + 'px'; Lb.el.style.top = ((1 - v3.y) / 2 * hh) + 'px'; }
    });
  }
  function aplicaVis() {
    din.children.forEach(o => { const p = o.userData.piso; o.visible = p === 'ambos' || !p || !grupos[p] || grupos[p].visible; });
  }
  function aplicaPisos(f) {
    PISOS.forEach(p => { vis[p.id] = f === 'todos' || f === p.id; grupos[p.id].visible = vis[p.id]; });
    document.querySelectorAll('#viewMaquete [data-mq-f]').forEach(b => b.classList.toggle('on', b.dataset.mqF === f));
    aplicaVis();
  }

  // ---------- painel lateral ----------
  function painelSel() {
    if (!sel) return painelProjeto();
    if (sel.k === 'cam') return painelCam(sel.o);
    if (sel.o.tipo === 'rack') return painelRack();
    return painelNo(sel.o);
  }
  function selecionar(k, o) {
    if (modoAdd === 'wp' && !(k === 'cam' && sel && sel.o === o)) { modoAdd = null; const cv = $('mqCv'); if (cv) cv.classList.remove('add'); }
    sel = k ? { k, o } : null; montarDin(); painelSel();
  }
  function painelProjeto() {
    const card = $('mqSelCard'); const lig = ligacoes(), tot = [...caminhos.values()].reduce((a, r) => a + r.len, 0);
    const poe = L.cams.reduce((a, c) => a + (lig.m.get(c.id)?.sw ? (MOD[c.mod] || MOD.d2_28).w : 0), 0);
    card.innerHTML = `<h2><span class="nm">Projeto de CFTV</span></h2>
      <dl class="mq-dl top0">
        <dt>Câmeras</dt><dd>${L.cams.length}</dd>
        <dt>Cabo UTP ${CAT[L.catCabo]}</dt><dd>${fmt(tot, 0)} m</dd>
        <dt>Categoria do cabo</dt><dd><select id="mqPCat" aria-label="Categoria do cabo">${Object.entries(CAT).map(([k, v]) => `<option value="${k}"${k === L.catCabo ? ' selected' : ''}>${v}</option>`).join('')}</select></dd>
        <dt>Caixas de passagem</dt><dd>${L.nodes.filter(n => n.tipo === 'caixa').length}</dd>
        <dt>Rack</dt><dd>${RACKS[L.rack.tam].nome}</dd>
        <dt>PoE usado</dt><dd>${fmt(poe, 1)} de ${lig.poe} W</dd>
      </dl>
      <div class="mq-acts2" style="margin-top:12px"><button class="mq-btn" type="button" data-mq-ir="rack">Montar rack</button><button class="mq-btn" type="button" data-mq-ir="cabos">Lista de cabos</button></div>
      <div class="mq-muted" style="margin-top:12px">Clique numa câmera, caixa ou no rack para editar. Use <b>+ Câmera</b> e <b>+ Caixa de passagem</b> no alto da maquete.</div>`;
    card.querySelectorAll('[data-mq-ir]').forEach(b => b.onclick = () => aba(b.dataset.mqIr));
    $('mqPCat').onchange = e => setCat(e.target.value);
  }
  function setCat(v) { L.catCabo = v; montarDin(); painelSel(); marcarMudanca(); toast('Cabo ' + CAT[v] + ' em todo o projeto'); }
  function painelCam(c) {
    const card = $('mqSelCard'), m = MOD[c.mod] || MOD.d2_28, d = dori(c), f = fovDe(c), r = caminhos.get(c.id), lig = ligacoes().m.get(c.id), st = stDe(c);
    const k = cadDe(c);
    const opts = Object.entries(MOD).map(([kk, v]) => `<option value="${kk}"${kk === c.mod ? ' selected' : ''}>${h(v.nome)}</option>`).join('');
    const optsCad = cadastro.lista.map(x => `<option value="${h(x.rotulo)}"></option>`).join('');
    const dir = ((Math.round(c.dir) % 360) + 360) % 360;
    card.innerHTML = `<h2><i class="mq-dot ${ST[st][2]}"></i><span class="nm" title="${h(c.nome)}">${h(c.nome)}</span><span class="r"><span class="mq-pill ${ST[st][1]}">${ST[st][0]}</span><button class="mq-x" type="button" id="mqSX" aria-label="Fechar">×</button></span></h2>
      <div class="mq-fld"><label for="mqSCad">Câmera do cadastro</label>
        <input id="mqSCad" list="mqSCadLista" placeholder="Digite o nome ou IP (vazio = câmera de projeto)" value="${h(k ? k.rotulo : (c.ip || ''))}" autocomplete="off">
        <datalist id="mqSCadLista">${optsCad}</datalist>
        ${k ? '' : c.ip ? `<span class="mq-muted" style="color:var(--danger)">${(cadastro.porIp[c.ip] || []).length > 1 ? 'IP repetido em mais de um local: escolha na lista' : 'Câmera não está no cadastro deste cliente'}</span>` : ''}
      </div>
      <div class="mq-fld"><label for="mqSNome">Nome na maquete</label><input id="mqSNome" value="${h(c.nome)}" maxlength="80"></div>
      <div class="mq-fld"><label for="mqSMod">Modelo da câmera</label><select id="mqSMod">${opts}</select></div>
      ${m.vari ? `<div class="mq-rng"><label for="mqSFoco">Lente</label><input type="range" id="mqSFoco" min="${m.vari[0]}" max="${m.vari[1]}" step="0.1" value="${c.foco || m.vari[0]}"><output>${fmt(c.foco || m.vari[0])} mm</output></div>` : ''}
      ${f < 360 ? `<div class="mq-rng"><label for="mqSDir">Direção</label><input type="range" id="mqSDir" min="0" max="359" value="${dir}"><output>${dir}°</output></div>` : ''}
      <div class="mq-dori"><dl class="mq-dl top0">
        <dt>Abertura</dt><dd>${fmt(f, 0)}°</dd>
        ${d ? `<dt><span class="mq-bard" style="background:var(--blue)"></span>Identifica rosto até</dt><dd>${fmt(d.ident)} m</dd>
        <dt><span class="mq-bard" style="background:var(--cyan,#0b7285)"></span>Reconhece pessoa até</dt><dd>${fmt(d.recon)} m</dd>
        <dt>Observa até</dt><dd>${fmt(d.obs)} m</dd>` : '<dt>Visão</dt><dd>360° do ambiente</dd>'}
        <dt>Infravermelho</dt><dd>${m.ir} m</dd>
        <dt>Consumo PoE</dt><dd>${fmt(m.w)} W</dd>
      </dl></div>
      <div class="mq-row2" style="margin-bottom:12px">
        <div class="mq-fld" style="margin:0"><label for="mqSPiso">Pavimento</label><select id="mqSPiso">${PISOS.map(p => `<option value="${h(p.id)}"${p.id === c.piso ? ' selected' : ''}>${h(p.nome)}</option>`).join('')}</select></div>
        <div class="mq-fld" style="margin:0"><label for="mqSAlt">Altura (m)</label><input inputmode="decimal" id="mqSAlt" value="${fmt(camAlt(c), 2)}"></div>
      </div>
      <div class="mq-cabo">Cabo <b>${lig ? lig.cabo : '—'}</b> · <b>${fmt(r ? r.len : 0)} m</b> até o rack<br>Passa por ${h((r && r.via.join(' › ')) || 'direto')}<br>Switch ${h(rotPorta(lig && lig.sw))}</div>
      <div class="mq-fld"><label for="mqSEnt">Entra na calha por</label><select id="mqSEnt">
        <option value="">Automático (ponto mais perto)</option>
        ${entradasDe(c.piso).map(n => `<option value="${h(n.id)}"${n.id === c.entrada ? ' selected' : ''}>${h(n.tipo === 'rack' ? 'Direto no rack' : n.nome)}</option>`).join('')}
      </select></div>
      <div class="mq-fld"><label>Pontos do caminho</label>
        <div class="mq-acts2" style="grid-template-columns:1fr auto auto">
          <button class="mq-btn sm${modoAdd === 'wp' ? ' on' : ''}" type="button" id="mqSWp">${modoAdd === 'wp' ? 'Concluir' : (c.pts && c.pts.length ? '+ Ponto' : 'Desenhar caminho')}</button>
          <button class="mq-btn sm" type="button" id="mqSWpUndo"${c.pts && c.pts.length ? '' : ' disabled'} title="Tirar o último ponto">↶</button>
          <button class="mq-btn sm" type="button" id="mqSWpLimpa"${c.pts && c.pts.length ? '' : ' disabled'}>Limpar</button>
        </div>
        <span class="mq-muted">${c.pts && c.pts.length ? `${c.pts.length} curva(s). Arraste os pontos azuis; duplo clique tira.` : 'Ou puxe o cabo direto na maquete.'}</span>
      </div>
      <div class="mq-fld"><label for="mqSPorta">Porta no patch panel</label><select id="mqSPorta">${opcoesPorta(c, lig)}</select></div>
      <div class="mq-acts2"><button class="mq-btn" type="button" id="mqSOlhar">Ver daqui</button><button class="mq-btn del" type="button" id="mqSRm">Remover</button></div>`;
    $('mqSX').onclick = () => selecionar(null);
    $('mqSCad').onchange = e => {
      const v = e.target.value.trim();
      const doIp = cadastro.porIp[v] || [];
      const kk = cadastro.porRotulo[v] || (doIp.length === 1 ? doIp[0] : null);
      if (!v) { c.ip = null; c.cad = null; }
      else if (kk) { c.ip = kk.ip; c.cad = kk.chave; c.nome = kk.titulo; }
      else { c.ip = v; c.cad = null; }
      montarDin(); painelSel(); marcarMudanca();
    };
    $('mqSNome').onchange = e => { c.nome = e.target.value.trim() || c.nome; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSMod').onchange = e => { c.mod = e.target.value; c.foco = MOD[c.mod].vari ? MOD[c.mod].vari[0] : undefined; montarDin(); painelSel(); marcarMudanca(); };
    if ($('mqSFoco')) $('mqSFoco').oninput = e => { c.foco = +e.target.value; e.target.nextElementSibling.textContent = fmt(c.foco) + ' mm'; redesenhar(); atualizaDori(c); marcarMudanca(); };
    if ($('mqSDir')) $('mqSDir').oninput = e => { c.dir = +e.target.value; e.target.nextElementSibling.textContent = c.dir + '°'; redesenhar(); marcarMudanca(); };
    $('mqSPiso').onchange = e => { c.piso = e.target.value; c.alt = undefined; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSAlt').onchange = e => { const v = parseFloat(String(e.target.value).replace(',', '.')); if (v > 0.5) c.alt = v; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSOlhar').onclick = () => olharDe(c);
    $('mqSEnt').onchange = e => { c.entrada = e.target.value || null; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSWp').onclick = () => {
      if (modoAdd === 'wp') { fimDesenho(); return; }
      modoAdd = 'wp'; $('mqCv').classList.add('add');
      document.querySelectorAll('#viewMaquete [data-mq-add]').forEach(k => k.classList.remove('on'));
      $('mqHint').textContent = 'Clique no piso para marcar o caminho do cabo · Esc ou "Concluir" para terminar';
      painelSel();
    };
    $('mqSWpUndo').onclick = () => { if (c.pts && c.pts.length) { c.pts.pop(); montarDin(); painelSel(); marcarMudanca(); } };
    $('mqSWpLimpa').onclick = () => { c.pts = []; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSPorta').onchange = e => {
      const v = e.target.value;
      if (!v) c.pp = null; else { const [i, porta] = v.split(':').map(Number); c.pp = { i, porta }; }
      montarDin(); painelSel(); marcarMudanca();
    };
    $('mqSRm').onclick = () => { L.cams = L.cams.filter(x => x !== c); sel = null; montarDin(); painelSel(); marcarMudanca(); toast('Câmera removida da maquete.'); };
  }
  function opcoesPorta(c, lig) {
    const tudo = ligacoes(), dono = new Map();
    const chave = s => L.rack.itens.indexOf(s.o) + ':' + s.porta;
    L.cams.forEach(k => { const l = tudo.m.get(k.id); if (l && l.pp && k !== c) dono.set(chave(l.pp), String(k.nome).split(' ')[0]); });
    const atual = lig && lig.pp;
    let html = `<option value="">Automática${atual && !lig.ppManual ? ' (' + h(rotPorta(atual)) + ')' : ''}</option>`;
    tudo.slots.forEach(s => {
      const i = L.rack.itens.indexOf(s.o), ocup = dono.get(chave(s));
      const sel = lig && lig.ppManual && atual && atual.o === s.o && atual.porta === s.porta;
      html += `<option value="${i}:${s.porta}"${sel ? ' selected' : ''}${ocup ? ' disabled' : ''}>${h(rotPorta(s))}${ocup ? ' · ' + h(ocup) : ''}</option>`;
    });
    return html;
  }
  function removerCaixa(n) {
    L.nodes.forEach(k => { if (k.pai === n.id) k.pai = n.pai; });
    L.cams.forEach(c => { if (c.entrada === n.id) c.entrada = null; });
    L.nodes = L.nodes.filter(k => k !== n);
    if (sel && sel.o === n) sel = null;
  }
  function fimDesenho() {
    modoAdd = null; const cv = $('mqCv'); if (cv) cv.classList.remove('add');
    $('mqHint').textContent = 'Puxe o cabo ou a calha para mudar o caminho · duplo clique numa curva desfaz · arraste o fundo para girar';
    painelSel();
  }
  function atualizaDori(c) {
    const d = dori(c), dds = $('mqSelCard').querySelectorAll('.mq-dori dd');
    dds[0].textContent = fmt(fovDe(c), 0) + '°'; if (d) { dds[1].textContent = fmt(d.ident) + ' m'; dds[2].textContent = fmt(d.recon) + ' m'; dds[3].textContent = fmt(d.obs) + ' m'; }
  }
  function painelRack() {
    const card = $('mqSelCard'), R = RACKS[L.rack.tam], lig = ligacoes(), usados = L.rack.itens.filter(o => IT[o.k] && dentro(o)).reduce((a, o) => a + IT[o.k].u, 0);
    card.innerHTML = `<h2><span class="nm">Rack</span><span class="r"><button class="mq-x" type="button" id="mqSX" aria-label="Fechar">×</button></span></h2>
      <div class="mq-fld"><label for="mqSTam">Tamanho</label><select id="mqSTam">${Object.entries(RACKS).map(([k, v]) => `<option value="${k}"${k === L.rack.tam ? ' selected' : ''}>${v.nome}</option>`).join('')}</select></div>
      <div class="mq-rng"><label for="mqSRot">Frente</label><input type="range" id="mqSRot" min="0" max="359" value="${L.rack.rot || 0}"><output>${L.rack.rot || 0}°</output></div>
      <dl class="mq-dl" style="margin-top:8px">
        <dt>Cabos chegando</dt><dd>${L.cams.length}</dd>
        <dt>Portas no patch panel</dt><dd>${Math.min(L.cams.length, lig.pp)} de ${lig.pp}</dd>
        <dt>Espaço usado</dt><dd>${usados} de ${R.u} U</dd>
      </dl>
      <button class="mq-btn pri" type="button" id="mqSMontar" style="width:100%;margin-top:12px">Montar rack</button>`;
    $('mqSX').onclick = () => selecionar(null);
    $('mqSTam').onchange = e => { L.rack.tam = e.target.value; montarDin(); painelSel(); marcarMudanca(); };
    $('mqSRot').oninput = e => { L.rack.rot = +e.target.value; e.target.nextElementSibling.textContent = L.rack.rot + '°'; redesenhar(); marcarMudanca(); };
    $('mqSMontar').onclick = () => aba('rack');
  }
  function painelNo(n) {
    const card = $('mqSelCard'), passa = contagem[n.tipo === 'prumada' ? 'Prumada' : n.nome] || 0;
    card.innerHTML = `<h2><span class="nm">${h(n.nome)}</span><span class="r"><span class="mq-pill mq-p-grey">${h(pisoById(n.piso).nome)}</span><button class="mq-x" type="button" id="mqSX" aria-label="Fechar">×</button></span></h2>
      <dl class="mq-dl top0">
        <dt>Tipo</dt><dd>${n.tipo === 'prumada' ? 'Prumada (sobe/desce)' : 'Caixa de passagem'}</dd>
        <dt>Cabos passando</dt><dd>${passa}</dd>
        <dt>Posição na planta</dt><dd>${fmt(n.x, 2)} × ${fmt(n.y, 2)} m</dd>
      </dl>
      <div class="mq-muted" style="margin:12px 0">Arraste na maquete para mudar o caminho da calha; os cabos e a metragem acompanham. Duplo clique na caixa tira a curva.</div>
      ${n.tipo === 'caixa' ? '<button class="mq-btn del" type="button" id="mqSRm" style="width:100%">Remover caixa</button>' : ''}`;
    $('mqSX').onclick = () => selecionar(null);
    if ($('mqSRm')) $('mqSRm').onclick = () => { removerCaixa(n); montarDin(); painelSel(); marcarMudanca(); };
  }
  function listaCams() {
    const el = $('mqCams'); if (!el) return;
    const off = L.cams.filter(c => stDe(c) === 'off').length;
    $('mqNCam').textContent = L.cams.length + (off ? ' · ' + off + ' offline' : '');
    el.innerHTML = L.cams.length ? ordenadas().map(c => {
      const r = caminhos.get(c.id), eSel = sel && sel.o === c, st = stDe(c);
      return `<button type="button" class="mq-cam${eSel ? ' sel' : ''}" data-id="${h(c.id)}" title="${h(c.nome)}"><i class="mq-dot ${ST[st][2]}"></i><span class="t"><b>${h(c.nome)}</b><small>${h(pisoById(c.piso).nome)} · ${h((MOD[c.mod] || MOD.d2_28).nome)}</small></span><em title="Cabo até o rack">${fmt(r ? r.len : 0)} m</em></button>`;
    }).join('') : '<div class="mq-muted">Nenhuma câmera ainda. Use <b>+ Câmera</b> e clique no piso.</div>';
    el.querySelectorAll('.mq-cam').forEach(b => b.onclick = () => {
      const c = L.cams.find(k => String(k.id) === b.dataset.id); if (!c) return;
      if (!grupos[c.piso].visible) aplicaPisos(c.piso);
      selecionar('cam', c);
      const p = V(OX + c.x, base(c.piso), OZ + c.y); voarPara(p, V(p.x + 9, p.y + 11, p.z + 9));
    });
  }

  // ---------- abas Rack e Cabos ----------
  function aba(nome) {
    abaAtual = nome;
    document.querySelectorAll('#viewMaquete .mq-tab').forEach(t => t.classList.toggle('on', t.dataset.mqAba === nome));
    $('mqAbaMaquete').hidden = nome !== 'maquete'; $('mqAbaRack').hidden = nome !== 'rack'; $('mqAbaCabos').hidden = nome !== 'cabos'; $('mqAbaOrc').hidden = nome !== 'orc';
    if (nome === 'rack') renderRack(); if (nome === 'cabos') renderCabos(); if (nome === 'orc') renderOrcamento();
  }
  function meter(id, v, cap) { const p = cap ? Math.min(100, v / cap * 100) : 100; const el = $(id); el.style.width = p + '%'; el.className = v > cap ? 'off' : p > 85 ? 'warn' : ''; }
  function resumoAbas() {
    const tot = [...caminhos.values()].reduce((a, r) => a + r.len, 0);
    $('mqTRack').textContent = RACKS[L.rack.tam].u + 'U'; $('mqTCabos').textContent = fmt(tot, 0) + ' m';
    const to = totaisOrc(linhasOrcamento()).total; $('mqTOrc').textContent = to ? brl(to) : '—';
    if (abaAtual === 'rack') renderRack(); if (abaAtual === 'cabos') renderCabos();
  }
  function avisoCat() {
    const dif = ordemRack().filter(o => dentro(o) && IT[o.k].t === 'patch' && IT[o.k].cat !== L.catCabo);
    if (!dif.length) return '';
    return 'Cabo ' + CAT[L.catCabo] + ' chegando em patch panel ' + dif.map(o => CAT[IT[o.k].cat] + ' (' + rotU(o.k, o.u) + ')').join(', ') + '. A ligação fica na categoria menor; use patch panel ' + CAT[L.catCabo] + '.';
  }
  function portasHTML(it, occ) {
    if (!it.portas) return '';
    let s = '<span class="mq-ports">' + Array.from({ length: it.portas }, (_, p) => `<i class="${occ && occ[p + 1] ? 'on' : ''}" title="Porta ${p + 1}${occ && occ[p + 1] ? ' → ' + h(occ[p + 1]) : ' livre'}"></i>`).join('') + '</span>';
    if (it.sfp) s += '<span class="mq-ports sfp">' + Array.from({ length: it.sfp }, (_, p) => `<i title="SFP+ ${p + 1}"></i>`).join('') + '</span>';
    return s;
  }
  function renderRack() {
    const R = RACKS[L.rack.tam], lig = ligacoes(), n = L.cams.length, itens = L.rack.itens.filter(o => IT[o.k]);
    if (rkSel && !itens.includes(rkSel)) rkSel = null;
    const poe = L.cams.reduce((a, c) => a + (lig.m.get(c.id).sw ? (MOD[c.mod] || MOD.d2_28).w : 0), 0);
    const fora = itens.filter(o => !dentro(o)), usados = itens.filter(dentro).reduce((a, o) => a + IT[o.k].u, 0);
    const comPorta = L.cams.filter(c => lig.m.get(c.id).pp).length;
    $('mqKPortas').innerHTML = comPorta + ' <span>de ' + n + '</span>'; meter('mqMPortas', n, lig.pp);
    $('mqEPortas').textContent = n > lig.pp ? 'Faltam ' + (n - lig.pp) + ' portas no patch panel' : (lig.pp - n) + ' portas livres no patch panel';
    $('mqKPoe').innerHTML = fmt(poe, 1) + ' <span>de ' + lig.poe + ' W</span>'; meter('mqMPoe', poe, lig.poe);
    $('mqEPoe').textContent = lig.sw < n ? 'Faltam ' + (n - lig.sw) + ' portas PoE no switch' : 'Sobram ' + fmt(lig.poe - poe, 0) + ' W para expansão';
    $('mqKNvr').innerHTML = Math.min(n, lig.nvr) + ' <span>de ' + lig.nvr + '</span>'; meter('mqMNvr', n, lig.nvr);
    $('mqENvr').textContent = n > lig.nvr ? 'Faltam ' + (n - lig.nvr) + ' canais no gravador' : (lig.nvr - n) + ' canais livres';
    $('mqKU').innerHTML = usados + ' <span>de ' + R.u + ' U</span>'; meter('mqMU', usados + fora.reduce((a, o) => a + IT[o.k].u, 0), R.u);
    $('mqEU').textContent = fora.length ? fora.length + ' equipamento(s) não cabem neste rack' : (R.u - usados) + ' U livres · ' + R.nome;
    $('mqRkTam').innerHTML = Object.entries(RACKS).map(([k, v]) => `<option value="${k}"${k === L.rack.tam ? ' selected' : ''}>${v.nome}</option>`).join('');
    const gruposCat = [...new Set(Object.values(IT).map(v => v.g))];
    $('mqRkCat').innerHTML = gruposCat.map(g => `<optgroup label="${g}">` + Object.entries(IT).filter(([, v]) => v.g === g).map(([k, v]) => `<option value="${k}"${k === catSel ? ' selected' : ''}>${h(v.nome)} · ${v.u}U</option>`).join('') + '</optgroup>').join('');
    const hh = IT[catSel].u, pos = posicoes(catSel);
    if (addTop != null) { addBase = baseEm(catSel, addTop); addTop = null; }
    if (addBase == null || !pos.includes(addBase)) addBase = pos.length ? pos[0] : null;
    $('mqRkAddPos').innerHTML = pos.length ? pos.map(b => `<option value="${b}"${b === addBase ? ' selected' : ''}>${rotU(catSel, b)}</option>`).join('') : '<option>Sem espaço</option>';
    $('mqRkAddPos').disabled = $('mqRkAdd').disabled = !pos.length;
    const uso = new Map();
    L.cams.forEach(c => { const l = lig.m.get(c.id); [l.pp, l.sw, l.nvr].forEach(p => { if (p) { const m = uso.get(p.o) || {}; m[p.porta] = String(c.nome).split(' ')[0]; uso.set(p.o, m); } }); });
    const linha = (o, extraCls) => {
      const it = IT[o.k], i = L.rack.itens.indexOf(o);
      const extra = it.t === 'nvr' ? `<span style="flex:none;color:#9fb0b8">${Object.keys(uso.get(o) || {}).length}/${it.canais} canais</span>` : portasHTML(it, uso.get(o));
      return `<div role="button" tabindex="0" draggable="true" class="mq-ri t-${it.t}${it.vent ? ' vent' : ''}${extraCls || ''}${o === rkSel ? ' sel' : ''}" data-i="${i}" data-top="${topo(o)}" style="height:${it.u * 26 - 2}px" title="${h(it.nome)} · ${rotU(o.k, o.u)}"><span class="un">${topo(o)}</span><span class="nm">${h(it.curto || it.nome)}</span>${extra}</div>`;
    };
    let html = '';
    for (let u = R.u; u >= 1; u--) {
      const o = itens.find(x => dentro(x) && topo(x) === u);
      if (o) { html += linha(o); continue; }
      if (itens.some(x => dentro(x) && x.u <= u && topo(x) >= u)) continue;
      const pick = !rkSel && addBase != null && u >= addBase && u <= addBase + hh - 1;
      html += `<div class="mq-ri t-vazio${pick ? ' pick' : ''}" data-u="${u}" role="button" tabindex="0" title="Adicionar na U${u}"><span class="un">${u}</span><span class="nm">${pick ? h(IT[catSel].curto || IT[catSel].nome) + ' entra aqui' : 'livre'}</span></div>`;
    }
    $('mqRk').innerHTML = html;
    $('mqRkFora').innerHTML = fora.length ? '<div class="mq-muted" style="color:var(--danger);margin-bottom:6px">Não cabem neste rack. Mova ou troque o tamanho:</div>' + fora.map(o => linha(o, ' over')).join('') : '';
    document.querySelectorAll('#mqRk [data-i], #mqRkFora [data-i]').forEach(el => {
      el.onclick = () => { rkSel = L.rack.itens[+el.dataset.i]; renderRack(); };
      el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); } };
      el.ondragstart = e => { rkArr = L.rack.itens[+el.dataset.i]; e.dataTransfer.setData('text/plain', el.dataset.i); e.dataTransfer.effectAllowed = 'move'; setTimeout(() => el.classList.add('drag')); };
      el.ondragend = () => { rkArr = null; renderRack(); };
    });
    $('mqRk').querySelectorAll('[data-u]').forEach(el => {
      el.onclick = () => { rkSel = null; addTop = +el.dataset.u; renderRack(); };
      el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); } };
    });
    $('mqRkSelBox').hidden = !rkSel;
    if (rkSel) {
      const it = IT[rkSel.k], ps = posicoes(rkSel.k, rkSel);
      $('mqRkSelNome').textContent = it.nome; $('mqRkSelNome').title = it.nome;
      $('mqRkSelU').textContent = dentro(rkSel) ? rotU(rkSel.k, rkSel.u) : 'fora do rack';
      $('mqRkPos').innerHTML = (dentro(rkSel) ? '' : '<option value="">Escolha a U</option>') + ps.map(b => `<option value="${b}"${b === rkSel.u && dentro(rkSel) ? ' selected' : ''}>${rotU(rkSel.k, b)}</option>`).join('');
      $('mqRkUp').disabled = !ps.some(b => b > rkSel.u); $('mqRkDn').disabled = !ps.some(b => b < rkSel.u);
    }
    const rn = rackNode(); $('mqRkLoc').textContent = pisoById(rn.piso).nome + ' · ' + fmt(rn.x, 1) + ' × ' + fmt(rn.y, 1) + ' m';
    const av = avisoCat(); $('mqRkAviso').hidden = !av; $('mqRkAviso').textContent = av;
    $('mqTbRack').innerHTML = ordenadas().map(c => {
      const l = lig.m.get(c.id), r = caminhos.get(c.id), st = stDe(c);
      return `<tr class="click" data-id="${h(c.id)}"><td>${l.cabo}</td><td title="${h(c.nome)}"><i class="mq-dot ${ST[st][2]}" style="margin-right:6px"></i>${h(c.nome)}</td><td${l.pp ? '' : ' style="color:var(--danger)"'}>${h(rotPorta(l.pp))}</td><td${l.sw ? '' : ' style="color:var(--danger)"'}>${h(rotPorta(l.sw))}</td><td${l.nvr ? '' : ' style="color:var(--danger)"'}>${l.nvr ? 'canal ' + l.nvr.porta : '—'}</td><td class="n">${fmt((MOD[c.mod] || MOD.d2_28).w)} W</td><td class="n">${fmt(r ? r.len : 0)}</td></tr>`;
    }).join('');
    $('mqTbRack').querySelectorAll('tr').forEach(tr => tr.onclick = () => irCam(tr.dataset.id));
  }
  function renderCabos() {
    const lig = ligacoes(); let tot = 0;
    $('mqTbCabos').innerHTML = ordenadas().map(c => {
      const l = lig.m.get(c.id), r = caminhos.get(c.id); tot += r ? r.len : 0;
      const via = r ? r.via.join(' › ') : '';
      return `<tr class="click" data-id="${h(c.id)}"><td>${l.cabo}</td><td title="${h(c.nome)}">${h(c.nome)}</td><td>${h(pisoById(c.piso).nome)}</td><td title="${h((MOD[c.mod] || MOD.d2_28).nome)}">${h((MOD[c.mod] || MOD.d2_28).nome)}</td><td title="${h(via)}">${h(via || 'direto no rack')}</td><td>${h(rotPorta(l.pp))}</td><td class="n">${fmt(r ? r.len : 0)}</td></tr>`;
    }).join('');
    $('mqTbCabos').querySelectorAll('tr').forEach(tr => tr.onclick = () => irCam(tr.dataset.id));
    $('mqTfM').textContent = fmt(tot) + ' m';
    $('mqKCab').textContent = L.cams.length;
    $('mqECab').textContent = 'Um cabo UTP ' + CAT[L.catCabo] + ' por câmera';
    $('mqCabCat').value = L.catCabo;
    const av = avisoCat(); $('mqCabAviso').hidden = !av; $('mqCabAviso').textContent = av;
    $('mqKM').innerHTML = fmt(tot, 0) + ' <span>m</span>';
    const maior = L.cams.reduce((a, c) => Math.max(a, (caminhos.get(c.id) || { len: 0 }).len), 0);
    $('mqEM').textContent = 'Maior lance ' + fmt(maior) + ' m' + (maior > 90 ? ' · passa de 90 m' : ' · dentro dos 90 m');
    $('mqKM10').innerHTML = fmt(tot * 1.1, 0) + ' <span>m</span>';
    const bob = Math.ceil(tot * 1.1 / 305); $('mqKBob').textContent = bob;
    $('mqEBob').textContent = 'Sobram ' + fmt(bob * 305 - tot * 1.1, 0) + ' m';
  }
  function irCam(id) {
    const c = L.cams.find(k => String(k.id) === String(id)); if (!c) return;
    aba('maquete'); aplicaPisos(c.piso); selecionar('cam', c);
    const p = V(OX + c.x, base(c.piso), OZ + c.y); voarPara(p, V(p.x + 9, p.y + 11, p.z + 9));
  }

  // ======================================================================
  // ORÇAMENTO
  // Lista de material sai da maquete (chave estável por item); o cliente põe
  // preço (tabela do cliente em /api/maquete/precos), pode mudar quantidade e
  // descrição, ocultar item e somar itens avulsos. Fica em L.orc.
  // ======================================================================
  let tabelaPrecos = {}, metrosCalha = 0;
  const brl = v => 'R$ ' + fmt(v, 2);
  // número guardado (289.9) passa direto; texto digitado em pt-BR ("1.234,56") vira número
  const numIn = v => {
    if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
    const s = String(v ?? '').trim();
    const n = parseFloat(s.includes(',') ? s.replace(/\./g, '').replace(',', '.') : s);
    return Number.isFinite(n) ? n : 0;
  };

  function totaisCabo() {
    const tot = [...caminhos.values()].reduce((a, r) => a + r.len, 0);
    const maior = [...caminhos.values()].reduce((a, r) => Math.max(a, r.len), 0);
    return { tot, maior, m10: tot * 1.1, cx305: Math.ceil(tot * 1.1 / 305) };
  }

  function itensAuto() {
    const n = L.cams.length, cab = totaisCabo(), cat = CAT[L.catCabo], out = [];
    const porMod = {};
    L.cams.forEach(c => { porMod[c.mod] = (porMod[c.mod] || 0) + 1; });
    Object.entries(porMod).sort((a, b) => natural((MOD[a[0]] || {}).nome, (MOD[b[0]] || {}).nome))
      .forEach(([k, q]) => out.push({ key: 'cam:' + k, grupo: 'Câmeras', descricao: 'Câmera IP ' + ((MOD[k] || MOD.d2_28).nome), qtd: q, un: 'un' }));
    if (n) {
      out.push({ key: 'cabo:' + L.catCabo, grupo: 'Cabeamento', descricao: `Cabo UTP ${cat} · caixa 305 m`, qtd: cab.cx305, un: 'cx' });
      out.push({ key: 'rj45:' + L.catCabo, grupo: 'Cabeamento', descricao: `Conector RJ45 ${cat}`, qtd: Math.ceil(n * 2 * 1.1), un: 'un' });
      out.push({ key: 'patch:' + L.catCabo, grupo: 'Cabeamento', descricao: `Patch cord ${cat} 1,5 m`, qtd: n, un: 'un' });
    }
    const cx = L.nodes.filter(x => x.tipo === 'caixa').length;
    if (cx) out.push({ key: 'caixa', grupo: 'Infraestrutura', descricao: 'Caixa de passagem', qtd: cx, un: 'un' });
    if (metrosCalha > 0.5) out.push({ key: 'calha', grupo: 'Infraestrutura', descricao: `Eletrocalha perfurada · barra 3 m (${fmt(metrosCalha, 0)} m no traçado)`, qtd: Math.ceil(metrosCalha / 3), un: 'br' });
    out.push({ key: 'rack:' + L.rack.tam, grupo: 'Rack', descricao: 'Rack ' + RACKS[L.rack.tam].nome, qtd: 1, un: 'un' });
    const porIt = {};
    L.rack.itens.filter(o => IT[o.k] && dentro(o)).forEach(o => { porIt[o.k] = (porIt[o.k] || 0) + 1; });
    Object.entries(porIt).forEach(([k, q]) => out.push({ key: 'it:' + k, grupo: 'Rack', descricao: IT[k].nome + (IT[k].u > 1 ? ` (${IT[k].u}U)` : ''), qtd: q, un: 'un' }));
    if (n) {
      out.push({ key: 'mo:cam', grupo: 'Mão de obra', descricao: 'Instalação e configuração de câmera', qtd: n, un: 'un' });
      out.push({ key: 'mo:cabo', grupo: 'Mão de obra', descricao: 'Passagem de cabo', qtd: Math.ceil(cab.tot), un: 'm' });
    }
    out.push({ key: 'mo:rack', grupo: 'Mão de obra', descricao: 'Montagem e organização do rack', qtd: 1, un: 'vb' });
    return out;
  }

  function linhasOrcamento() {
    const o = L.orc;
    const auto = itensAuto().filter(i => !o.ocultos.includes(i.key)).map(i => {
      const tab = tabelaPrecos[i.key] || {};
      return Object.assign({}, i, {
        auto: true, qtdAuto: i.qtd,
        qtd: o.qtd[i.key] != null ? o.qtd[i.key] : i.qtd,
        descricao: o.desc[i.key] || tab.descricao || i.descricao,
        preco: o.precos[i.key] != null ? o.precos[i.key] : (tab.preco || 0),
      });
    });
    const avulsos = o.avulsos.map(a => Object.assign({ auto: false, key: a.id }, a));
    return auto.concat(avulsos).map(i => Object.assign(i, { total: Math.round(numIn(i.qtd) * numIn(i.preco) * 100) / 100 }));
  }
  function totaisOrc(linhas) {
    const sub = linhas.reduce((a, i) => a + i.total, 0), dp = Math.min(100, Math.max(0, numIn(L.orc.desconto_pct)));
    const desc = Math.round(sub * dp) / 100;
    return { sub, dp, desc, total: sub - desc, semPreco: linhas.filter(i => numIn(i.qtd) > 0 && !numIn(i.preco)).length };
  }

  function renderOrcamento() {
    const el = $('mqAbaOrc'); if (!el) return;
    const linhas = linhasOrcamento(), t = totaisOrc(linhas), o = L.orc;
    if ($('mqTOrc')) $('mqTOrc').textContent = t.total ? brl(t.total) : '—';
    const grupos = [];
    linhas.forEach(i => { let g = grupos.find(x => x.nome === i.grupo); if (!g) grupos.push(g = { nome: i.grupo, itens: [] }); g.itens.push(i); });
    const ocultos = itensAuto().filter(i => o.ocultos.includes(i.key));
    el.innerHTML = `
      <div class="mq-kpi"><small>Itens</small><b>${linhas.filter(i => numIn(i.qtd) > 0).length}</b><em>${t.semPreco ? t.semPreco + ' sem preço' : 'todos com preço'}</em></div>
      <div class="mq-kpi"><small>Subtotal</small><b>${brl(t.sub)}</b><em>material e mão de obra</em></div>
      <div class="mq-kpi"><small>Desconto</small><b>${brl(t.desc)}</b><em>${fmt(t.dp, 1)}%</em></div>
      <div class="mq-kpi"><small>Total</small><b>${brl(t.total)}</b><em>válido por ${o.validade_dias} dias</em></div>
      <div class="mq-card mq-s12">
        <h2><span class="nm">Itens do orçamento</span><span class="r">
          <button class="mq-btn sm" type="button" id="mqOrcSalvarPrecos" title="Usa estes preços nos próximos orçamentos deste cliente">Salvar preços como padrão</button>
          <button class="mq-btn sm pri" type="button" id="mqOrcPdf">Baixar PDF do orçamento</button></span></h2>
        <div class="mq-muted" style="margin-bottom:10px">As quantidades saem da maquete e mudam quando você mexe nela. Altere o que precisar; o que você alterar fica fixo (↺ volta ao calculado).</div>
        <div class="mq-tw"><table class="mq-table mq-orc" style="min-width:860px">
          <colgroup><col><col style="width:110px"><col style="width:56px"><col style="width:140px"><col style="width:130px"><col style="width:64px"></colgroup>
          <thead><tr><th>Item</th><th class="n">Qtd</th><th>Un</th><th class="n">Preço unit.</th><th class="n">Total</th><th></th></tr></thead>
          <tbody>${grupos.map(g => `<tr class="mq-orc-g"><td colspan="4">${h(g.nome)}</td><td class="n">${brl(g.itens.reduce((a, i) => a + i.total, 0))}</td><td></td></tr>` +
            g.itens.map(i => `<tr data-k="${h(i.key)}" data-auto="${i.auto ? 1 : 0}">
              <td><input class="mq-oin" data-f="descricao" value="${h(i.descricao)}" maxlength="200" aria-label="Descrição"></td>
              <td><input class="mq-oin n${i.auto && o.qtd[i.key] != null ? ' alt' : ''}" data-f="qtd" inputmode="decimal" value="${h(fmt(numIn(i.qtd), Number.isInteger(numIn(i.qtd)) ? 0 : 2))}" aria-label="Quantidade" title="${i.auto ? 'Calculado: ' + i.qtdAuto : ''}"></td>
              <td>${i.auto ? h(i.un) : `<input class="mq-oin" data-f="un" value="${h(i.un)}" maxlength="10" aria-label="Unidade">`}</td>
              <td><input class="mq-oin n${numIn(i.preco) ? '' : ' vazio'}" data-f="preco" inputmode="decimal" value="${numIn(i.preco) ? h(fmt(numIn(i.preco), 2)) : ''}" placeholder="0,00" aria-label="Preço unitário"></td>
              <td class="n">${numIn(i.preco) ? brl(i.total) : '<span class="mq-muted">a definir</span>'}</td>
              <td class="n">${i.auto && (o.qtd[i.key] != null || o.desc[i.key]) ? '<button class="mq-x" type="button" data-acao="reset" title="Voltar ao calculado">↺</button>' : ''}<button class="mq-x" type="button" data-acao="del" title="${i.auto ? 'Tirar do orçamento' : 'Remover'}">×</button></td>
            </tr>`).join('')).join('')}</tbody>
        </table></div>
        <div class="mq-orc-pe">
          <button class="mq-btn sm" type="button" id="mqOrcAvulso">+ Item avulso</button>
          ${ocultos.length ? `<select class="mq-inp" id="mqOrcVoltar" style="width:auto;height:28px"><option value="">Devolver item tirado (${ocultos.length})</option>${ocultos.map(i => `<option value="${h(i.key)}">${h(i.descricao)}</option>`).join('')}</select>` : ''}
        </div>
      </div>
      <div class="mq-card mq-s8">
        <h2>Condições</h2>
        <textarea class="mq-inp" id="mqOrcCond" rows="5" maxlength="2000" style="height:auto;padding:8px 10px;resize:vertical" placeholder="Forma de pagamento, prazo de instalação, garantia…">${h(o.condicoes)}</textarea>
      </div>
      <div class="mq-card mq-s4">
        <h2>Fechamento</h2>
        <dl class="mq-dl top0">
          <dt><label for="mqOrcDesc">Desconto (%)</label></dt><dd><input type="number" id="mqOrcDesc" min="0" max="100" step="0.5" value="${numIn(o.desconto_pct)}"></dd>
          <dt><label for="mqOrcVal">Validade (dias)</label></dt><dd><input type="number" id="mqOrcVal" min="1" max="365" value="${o.validade_dias}"></dd>
          <dt>Subtotal</dt><dd>${brl(t.sub)}</dd>
          <dt>Total</dt><dd style="font-size:15px">${brl(t.total)}</dd>
        </dl>
        <label class="mq-chk" style="margin-top:8px"><input type="checkbox" id="mqOrcNoRel"${o.noRelatorio ? ' checked' : ''}>Incluir no relatório PDF da maquete</label>
      </div>`;
    el.querySelectorAll('tr[data-k] .mq-oin').forEach(inp => inp.onchange = () => {
      const tr = inp.closest('tr'), k = tr.dataset.k, auto = tr.dataset.auto === '1', f = inp.dataset.f, v = inp.value.trim();
      if (auto) {
        if (f === 'qtd') { if (v === '') delete o.qtd[k]; else o.qtd[k] = numIn(v); }
        if (f === 'preco') o.precos[k] = numIn(v);
        if (f === 'descricao') { if (v) o.desc[k] = v; else delete o.desc[k]; }
      } else {
        const a = o.avulsos.find(x => x.id === k); if (!a) return;
        a[f] = f === 'qtd' || f === 'preco' ? numIn(v) : v;
      }
      marcarMudanca(); renderOrcamento();
    });
    el.querySelectorAll('tr[data-k] [data-acao]').forEach(b => b.onclick = () => {
      const tr = b.closest('tr'), k = tr.dataset.k, auto = tr.dataset.auto === '1';
      if (b.dataset.acao === 'reset') { delete o.qtd[k]; delete o.desc[k]; }
      else if (auto) o.ocultos.push(k);
      else o.avulsos = o.avulsos.filter(x => x.id !== k);
      marcarMudanca(); renderOrcamento();
    });
    $('mqOrcAvulso').onclick = () => { o.avulsos.push({ id: 'a' + (L.seq++), grupo: 'Outros', descricao: 'Item avulso', qtd: 1, un: 'un', preco: 0 }); marcarMudanca(); renderOrcamento(); };
    if ($('mqOrcVoltar')) $('mqOrcVoltar').onchange = e => { o.ocultos = o.ocultos.filter(k => k !== e.target.value); marcarMudanca(); renderOrcamento(); };
    $('mqOrcCond').onchange = e => { o.condicoes = e.target.value; marcarMudanca(); };
    $('mqOrcDesc').onchange = e => { o.desconto_pct = Math.min(100, Math.max(0, numIn(e.target.value))); marcarMudanca(); renderOrcamento(); };
    $('mqOrcVal').onchange = e => { o.validade_dias = Math.min(365, Math.max(1, Math.round(numIn(e.target.value)) || 15)); marcarMudanca(); renderOrcamento(); };
    $('mqOrcNoRel').onchange = e => { o.noRelatorio = e.target.checked; marcarMudanca(); };
    $('mqOrcPdf').onclick = () => gerarPdf('orcamento');
    $('mqOrcSalvarPrecos').onclick = salvarPrecosPadrao;
  }

  async function carregarPrecos() {
    const r = await api('/api/maquete/precos').catch(() => null);
    const d = r && r.ok ? await r.json().catch(() => ({})) : {};
    tabelaPrecos = d.precos || {};
  }
  async function salvarPrecosPadrao() {
    const novos = Object.assign({}, tabelaPrecos);
    linhasOrcamento().filter(i => i.auto && numIn(i.preco) > 0).forEach(i => { novos[i.key] = { preco: numIn(i.preco), descricao: L.orc.desc[i.key] || '', un: i.un }; });
    const r = await api('/api/maquete/precos', { method: 'PUT', body: JSON.stringify({ precos: novos }) });
    if (!r || !r.ok) return toast('Não foi possível salvar a tabela de preços.', true);
    tabelaPrecos = novos;
    toast('Preços salvos. Valem para os próximos orçamentos deste cliente.');
  }

  // ======================================================================
  // PDF (relatório da maquete ou orçamento)
  // ======================================================================
  function capturar() {
    // tira fotos do 3D: vista geral + vista de cima de cada pavimento
    const { renderer, camera, controls } = R3;
    const salvo = { pos: camera.position.clone(), alvo: controls.target.clone(), fov: camera.fov, aspect: camera.aspect, vis: PISOS.map(p => grupos[p.id].visible) };
    const W0 = 1600, H0 = 1000;
    renderer.setSize(W0, H0, false); camera.aspect = W0 / H0;
    const fotos = [];
    const foto = (titulo, rotulosDoPiso) => {
      camera.updateProjectionMatrix(); camera.lookAt(controls.target);
      renderer.render(R3.scene, camera);
      const cv = document.createElement('canvas'); cv.width = W0; cv.height = H0;
      const g = cv.getContext('2d'); g.drawImage(renderer.domElement, 0, 0, W0, H0);
      g.font = '600 22px Inter, Arial, sans-serif'; g.textBaseline = 'middle';
      const v3 = new THREE.Vector3();
      labels.filter(lb => !lb.apto && !lb.calha && (!rotulosDoPiso || lb.piso === rotulosDoPiso) && grupos[lb.piso] && grupos[lb.piso].visible).forEach(lb => {
        v3.copy(lb.pos).project(camera); if (v3.z > 1 || Math.abs(v3.x) > 1 || Math.abs(v3.y) > 1) return;
        const x = (v3.x + 1) / 2 * W0, y = (1 - v3.y) / 2 * H0 - 18, txt = lb.txt, w = g.measureText(txt).width + (lb.dot ? 40 : 20);
        g.fillStyle = 'rgba(255,255,255,0.95)'; g.strokeStyle = '#c9d1d6'; g.lineWidth = 2;
        g.beginPath(); g.rect(x - w / 2, y - 16, w, 32); g.fill(); g.stroke();
        if (lb.dot) { g.fillStyle = { 'mq-d-on': '#087f5b', 'mq-d-off': '#c92a2a', 'mq-d-new': '#1971c2' }[lb.dot] || '#66747e'; g.beginPath(); g.arc(x - w / 2 + 16, y, 6, 0, Math.PI * 2); g.fill(); }
        g.fillStyle = '#172026'; g.fillText(txt, x - w / 2 + (lb.dot ? 30 : 10), y);
      });
      fotos.push({ titulo, jpg: cv.toDataURL('image/jpeg', 0.82).split(',')[1] });
    };
    const d = Math.max(W, P);
    PISOS.forEach(p => { grupos[p.id].visible = true; }); aplicaVis();
    camera.fov = 40; controls.target.set(0, 1.5, 0); camera.position.set(-d * 0.55, d * 0.6, d * 0.75);
    foto('Vista geral da maquete', null);
    PISOS.forEach(p => {
      PISOS.forEach(q => { grupos[q.id].visible = q.id === p.id; }); aplicaVis();
      const y = base(p.id), dd = Math.max(p.largura, p.profundidade);
      // vista de cima com o prédio "deitado" na folha (lado maior na horizontal)
      controls.target.set(0, y, 0); camera.up.set(p.profundidade > p.largura ? 1 : 0, p.profundidade > p.largura ? 0 : 0, p.profundidade > p.largura ? 0 : -1);
      camera.position.set(0, y + dd * 1.05, 0.001);
      foto('Vista de cima · ' + p.nome, p.id);
      camera.up.set(0, 1, 0);
    });
    PISOS.forEach((p, i) => { grupos[p.id].visible = salvo.vis[i]; }); aplicaVis();
    camera.fov = salvo.fov; camera.position.copy(salvo.pos); controls.target.copy(salvo.alvo); camera.up.set(0, 1, 0);
    tamanho();
    return fotos;
  }

  function dadosPdf(tipo) {
    const lig = ligacoes(), cab = totaisCabo(), R = RACKS[L.rack.tam];
    const usados = L.rack.itens.filter(o => IT[o.k] && dentro(o)).reduce((a, o) => a + IT[o.k].u, 0);
    const poe = L.cams.reduce((a, c) => a + (lig.m.get(c.id).sw ? (MOD[c.mod] || MOD.d2_28).w : 0), 0);
    const cams = ordenadas().map(c => {
      const l = lig.m.get(c.id), r = caminhos.get(c.id), d = dori(c), st = stDe(c);
      return { cabo: l.cabo, nome: c.nome, piso: pisoById(c.piso).nome, modelo: (MOD[c.mod] || MOD.d2_28).nome, abertura: fmt(fovDe(c), 0) + '°',
        ident: d ? fmt(d.ident, 1) + ' m' : '360°', situacao: ST[st][0], porta: rotPorta(l.pp), via: r ? r.via.join(' › ') : '', metros: r ? Math.round(r.len * 10) / 10 : 0 };
    });
    const uso = new Map();
    L.cams.forEach(c => { const l = lig.m.get(c.id); [l.pp, l.sw, l.nvr].forEach(p => { if (p) uso.set(p.o, (uso.get(p.o) || 0) + 1); }); });
    const rack = ordemRack().filter(dentro).map(o => {
      const it = IT[o.k], n = uso.get(o) || 0;
      return { u: rotU(o.k, o.u), nome: it.nome, uso: it.portas ? `${n} de ${it.portas} portas` : it.canais ? `${n} de ${it.canais} canais` : '' };
    });
    const linhas = linhasOrcamento();
    return {
      tipo,
      incluirOrcamento: !!L.orc.noRelatorio,
      resumo: {
        cameras: L.cams.length, online: L.cams.filter(c => stDe(c) === 'on').length, projeto: L.cams.filter(c => stDe(c) === 'new').length,
        metros: Math.round(cab.tot * 10) / 10, metros10: Math.round(cab.m10), caixas305: cab.cx305, maior: Math.round(cab.maior * 10) / 10,
        categoria: CAT[L.catCabo], caixasPassagem: L.nodes.filter(n => n.tipo === 'caixa').length, eletrocalha: Math.round(metrosCalha),
        rack: R.nome, rackUsado: `${usados} de ${R.u} U usados`, poe: `${fmt(poe, 1)} de ${lig.poe} W`,
      },
      cameras: cams, rack,
      orcamento: { itens: linhas.map(i => ({ grupo: i.grupo, descricao: i.descricao, qtd: numIn(i.qtd), un: i.un, preco: numIn(i.preco) })),
        desconto_pct: numIn(L.orc.desconto_pct), condicoes: L.orc.condicoes, validade_dias: L.orc.validade_dias },
    };
  }

  async function gerarPdf(tipo) {
    if (!R3) return;
    toast(tipo === 'orcamento' ? 'Gerando o PDF do orçamento…' : 'Gerando o relatório com as vistas da maquete…');
    const dados = dadosPdf(tipo);
    if (tipo !== 'orcamento') { try { dados.imagens = capturar(); } catch (e) { console.warn('maquete: falha ao capturar', e); dados.imagens = []; } }
    const r = await api(`/api/maquete/pdf/${encodeURIComponent(proj.id)}`, { method: 'POST', body: JSON.stringify(dados) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; return toast(d.detail || 'Não foi possível gerar o PDF.', true); }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '', m = cd.match(/filename="([^"]+)"/);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = m ? m[1] : (tipo + '.pdf');
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    toast('PDF pronto.');
  }

  // ---------- câmera do 3D ----------
  function voarPara(alvo, pos) { voo = { t: 0, a0: R3.controls.target.clone(), p0: R3.camera.position.clone(), a1: alvo, p1: pos }; }
  function olharDe(c) {
    const p = V(OX + c.x, base(c.piso) + camAlt(c), OZ + c.y), t = c.dir * Math.PI / 180;
    const f = fovDe(c); R3.camera.fov = Math.min(f >= 180 ? 100 : f * 0.75, 80); R3.camera.updateProjectionMatrix();
    if (f >= 180) return voarPara(V(p.x, base(c.piso), p.z + 0.01), V(p.x, p.y, p.z));
    voarPara(V(p.x + Math.cos(t) * 4, p.y - 1.3, p.z + Math.sin(t) * 4), p.clone().add(V(-Math.cos(t) * 0.25, 0, -Math.sin(t) * 0.25)));
  }
  function vista(v) {
    document.querySelectorAll('#viewMaquete [data-mq-v]').forEach(t => t.classList.toggle('on', t.dataset.mqV === v));
    R3.camera.fov = 40; R3.camera.updateProjectionMatrix();
    const d = Math.max(W, P);
    const vis1 = PISOS.filter(p => grupos[p.id].visible).pop() || PISOS[0];
    const y = base(vis1.id);
    if (v === '3d') voarPara(V(0, y + 1.5, 0), V(-d * 0.55, y + d * 0.6, d * 0.75));
    if (v === 'top') voarPara(V(0, y, 0.01), V(0, y + d * 1.45, 0.4));
  }

  // ---------- eventos ----------
  function ligarEventosFixos() {
    $('mqVoltar').onclick = () => window.loadMaquete();
    $('mqPdf').onclick = () => gerarPdf('relatorio');
    $('mqEditar').onclick = async () => {
      const d = await editarDados(proj); if (!d) return;
      $('mqNome').textContent = proj.nome; $('mqNome').title = proj.nome; $('mqSubTit').textContent = subTitulo();
    };
    $('mqExcluir').onclick = () => { if (window.confirm(`Excluir a maquete "${proj.nome}"? Isso apaga a planta e tudo o que foi montado.`)) excluirProjeto(proj.id); };
    document.querySelectorAll('#viewMaquete .mq-tab').forEach(t => t.onclick = () => aba(t.dataset.mqAba));
    document.querySelectorAll('#viewMaquete [data-mq-f]').forEach(b => b.onclick = () => {
      aplicaPisos(b.dataset.mqF);
      if (b.dataset.mqF !== 'todos') { const y = base(b.dataset.mqF), d = Math.max(W, P); voarPara(V(0, y, 0), V(-d * 0.6, y + d * 0.75, d * 0.9)); }
    });
    document.querySelectorAll('#viewMaquete [data-mq-v]').forEach(b => b.onclick = () => vista(b.dataset.mqV));
    document.querySelectorAll('#viewMaquete [data-mq-nomepiso]').forEach(i => i.onchange = () => {
      const id = i.dataset.mqNomepiso, p = PISOS.find(x => x.id === id), v = i.value.trim();
      if (!p) return;
      if (!v) { i.value = p.nome; return; }
      p.nome = v; L.nomes[id] = v;
      L.nodes.forEach(n => { if (n.tipo === 'prumada' && n.piso === id) n.nome = 'Prumada ' + v; });
      const b = [...document.querySelectorAll('#viewMaquete [data-mq-f]')].find(x => x.dataset.mqF === id); if (b) b.textContent = v;
      montarDin(); painelSel(); marcarMudanca();
    });
    document.querySelectorAll('#viewMaquete [data-mq-pd]').forEach(i => i.onchange = () => {
      const v = parseFloat(String(i.value).replace(',', '.')); if (v >= 2.2 && v <= 8) L.pd[i.dataset.mqPd] = v;
      reconstruir(); painelSel(); marcarMudanca();
    });
    $('mqExp').oninput = () => { $('mqOExp').textContent = String($('mqExp').value).replace('.', ',') + ' m'; reconstruir(); };
    $('mqCPlanta').onchange = reconstruir;
    ['mqCCones', 'mqCCabos', 'mqCCalha'].forEach(id => $(id).onchange = montarDin);
    $('mqCApto').onchange = posRotulos;
    document.querySelectorAll('#viewMaquete [data-mq-add]').forEach(b => b.onclick = () => {
      modoAdd = modoAdd === b.dataset.mqAdd ? null : b.dataset.mqAdd;
      if (sel && sel.k === 'cam') painelSel();
      document.querySelectorAll('#viewMaquete [data-mq-add]').forEach(k => k.classList.toggle('on', k.dataset.mqAdd === modoAdd));
      $('mqCv').classList.toggle('add', !!modoAdd);
      $('mqHint').textContent = modoAdd === 'cam' ? 'Clique no piso onde a câmera vai ficar' : modoAdd === 'caixa' ? 'Clique perto da eletrocalha onde a caixa vai ficar' : 'Puxe o cabo ou a calha para mudar o caminho · duplo clique numa curva desfaz · arraste o fundo para girar';
    });
    // rack
    $('mqRkTam').onchange = e => { L.rack.tam = e.target.value; montarDin(); painelSel(); marcarMudanca(); };
    $('mqRkPos').onchange = e => { if (e.target.value) moverPara(+e.target.value); };
    $('mqRkUp').onclick = () => { const ps = posicoes(rkSel.k, rkSel).filter(b => b > rkSel.u); if (ps.length) moverPara(Math.min(...ps)); };
    $('mqRkDn').onclick = () => { const ps = posicoes(rkSel.k, rkSel).filter(b => b < rkSel.u); if (ps.length) moverPara(Math.max(...ps)); };
    $('mqRkRm').onclick = () => { if (rkSel) { L.rack.itens = L.rack.itens.filter(o => o !== rkSel); rkSel = null; montarDin(); painelSel(); marcarMudanca(); } };
    $('mqRkCat').onchange = e => { catSel = e.target.value; addBase = null; renderRack(); };
    $('mqRkAddPos').onchange = e => { addBase = +e.target.value; renderRack(); };
    $('mqRkAdd').onclick = () => { if (addBase == null) return; const o = { k: catSel, u: addBase }; L.rack.itens.push(o); rkSel = o; addBase = null; montarDin(); painelSel(); marcarMudanca(); toast(IT[o.k].nome.split(' · ')[0] + ' na ' + rotU(o.k, o.u)); };
    $('mqCabCat').onchange = e => setCat(e.target.value);
    const uSob = e => {
      const el = e.target.closest && e.target.closest('[data-u],[data-top]'); if (!el) return null;
      if (el.dataset.u) return +el.dataset.u;
      return +el.dataset.top - Math.floor((e.clientY - el.getBoundingClientRect().top) / 26);
    };
    $('mqRk').addEventListener('dragover', e => {
      if (!rkArr) return; const u = uSob(e); if (u == null) return; e.preventDefault();
      const b0 = baseEm(rkArr.k, u, rkArr), ok = b0 != null, b = ok ? b0 : u - IT[rkArr.k].u + 1, t = b + IT[rkArr.k].u - 1;
      $('mqRk').querySelectorAll('.alvo-ok,.alvo-no').forEach(x => x.classList.remove('alvo-ok', 'alvo-no'));
      $('mqRk').querySelectorAll('[data-u]').forEach(x => { const v = +x.dataset.u; if (v >= b && v <= t) x.classList.add(ok ? 'alvo-ok' : 'alvo-no'); });
      const alvo = e.target.closest('[data-i]'); if (alvo && L.rack.itens[+alvo.dataset.i] !== rkArr) alvo.classList.add('alvo-no');
    });
    $('mqRk').addEventListener('drop', e => {
      e.preventDefault(); if (!rkArr) return;
      const o = rkArr, u = uSob(e), b = u == null ? null : baseEm(o.k, u, o); rkArr = null;
      if (b != null) { o.u = b; rkSel = o; montarDin(); painelSel(); marcarMudanca(); toast(IT[o.k].nome.split(' · ')[0] + ' na ' + rotU(o.k, b)); }
      else { toast('Não cabe na U' + u, true); renderRack(); }
    });
  }
  function moverPara(b) { if (!rkSel || !cabe(rkSel.k, b, rkSel)) return; rkSel.u = b; montarDin(); painelSel(); marcarMudanca(); }

  function ligarPonteiro() {
    const cv = R3.cv, ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), plano = new THREE.Plane(), pt = new THREE.Vector3();
    const snap = v => Math.round(v / 0.05) * 0.05;
    const raio = e => { const r = cv.getBoundingClientRect(); mouse.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1); ray.setFromCamera(mouse, R3.camera); };
    const acerto = e => {
      raio(e);
      const ok = alvos.filter(a => { let o = a; while (o && !o.userData.piso) o = o.parent; const p = o && o.userData.piso; return !p || p === 'ambos' || !grupos[p] || grupos[p].visible; });
      const hits = ray.intersectObjects(ok);
      // câmera, caixa, rack e curvas têm preferência sobre puxar cabo/calha
      return hits.find(x => !['cabo', 'calha'].includes(x.object.userData.ref.k)) || hits[0];
    };
    R3.view.addEventListener('pointerdown', e => {
      if (e.target !== cv || e.button !== 0) return;
      downPt = [e.clientX, e.clientY];
      if (modoAdd) return;
      const hit = acerto(e);
      if (hit) {
        const ref = hit.object.userData.ref;
        if (ref.k === 'cabo' || ref.k === 'calha') drag = { ref, y: hit.point.y, off: { x: 0, z: 0 }, moved: false, criar: true, em: hit.point.clone() };
        else { const o = ref.o; drag = { ref, y: hit.point.y, off: { x: (OX + o.x) - hit.point.x, z: (OZ + o.y) - hit.point.z }, moved: false }; }
        R3.controls.enabled = false;
      }
    }, true);
    R3.onMove = e => {
      if (!R3) return;
      if (!drag) { if (e.target === cv && !modoAdd) cv.classList.toggle('mover', !!acerto(e)); return; }
      if (!drag.moved && Math.hypot(e.clientX - downPt[0], e.clientY - downPt[1]) < 4) return;
      drag.moved = true;
      if (drag.criar) criarCurva(drag);
      raio(e); plano.set(V(0, 1, 0), -drag.y);
      if (!ray.ray.intersectPlane(plano, pt)) return;
      const o = drag.ref.o;
      o.x = Math.max(-2, Math.min(W + 2, snap(pt.x + drag.off.x - OX)));
      o.y = Math.max(-2, Math.min(P + 2, snap(pt.z + drag.off.z - OZ)));
      redesenhar();
    };
    R3.onUp = e => {
      if (!R3) return;
      const click = downPt && Math.hypot(e.clientX - downPt[0], e.clientY - downPt[1]) < 5;
      if (drag) {
        const r = drag.ref, moved = drag.moved, soClique = drag.criar; drag = null; R3.controls.enabled = true;
        if (soClique) { if (r.k === 'cabo') selecionar('cam', r.cam); downPt = null; return; }
        if (r.k === 'wp') { sel = { k: 'cam', o: r.cam }; montarDin(); painelSel(); if (moved) marcarMudanca(); }
        else if (!moved) selecionar(r.k, r.o); else { sel = { k: r.k, o: r.o }; montarDin(); painelSel(); marcarMudanca(); }
        downPt = null; return;
      }
      if (click && e.target === cv) { if (modoAdd) adicionar(e); else if (sel) selecionar(null); }
      downPt = null;
    };
    window.addEventListener('pointermove', R3.onMove);
    window.addEventListener('pointerup', R3.onUp);
    // puxou o cabo: vira um ponto do caminho dele; puxou a calha: vira uma caixa (curva da calha)
    function criarCurva(d) {
      const x = snap(d.em.x - OX), y = snap(d.em.z - OZ), r = d.ref;
      if (r.k === 'cabo') {
        const c = r.cam, p = { x, y };
        c.pts = Array.isArray(c.pts) ? c.pts : [];
        c.pts.splice(r.ins, 0, p);
        d.ref = { k: 'wp', o: p, cam: c }; sel = { k: 'cam', o: c };
      } else {
        const s = r.s, piso = r.piso;
        const num = L.nodes.filter(n => n.tipo === 'caixa').reduce((a, n) => Math.max(a, +String(n.nome).slice(3) || 0), 0) + 1;
        const n = { id: 'n' + (L.seq++), tipo: 'caixa', nome: 'CX-' + String(num).padStart(2, '0'), piso, x, y, pai: s.p.id };
        s.n.pai = n.id; L.nodes.push(n);
        d.ref = { k: 'node', o: n }; sel = { k: 'node', o: n };
      }
      d.criar = false; d.off = { x: 0, z: 0 };
    }
    // duplo clique numa curva: tira o ponto do cabo ou a caixa da calha
    R3.view.addEventListener('dblclick', e => {
      if (e.target !== cv) return;
      const hit = acerto(e); if (!hit) return;
      const r = hit.object.userData.ref;
      if (r.k === 'wp') { r.cam.pts = r.cam.pts.filter(p => p !== r.o); sel = { k: 'cam', o: r.cam }; }
      else if (r.k === 'node' && r.o.tipo === 'caixa') { removerCaixa(r.o); }
      else return;
      montarDin(); painelSel(); marcarMudanca();
    });
    R3.onKey = e => { if (e.key === 'Escape' && modoAdd === 'wp') fimDesenho(); };
    window.addEventListener('keydown', R3.onKey);
    function adicionar(e) {
      raio(e);
      const hit = ray.intersectObjects(PISOS.filter(p => grupos[p.id].visible).map(p => pisoMesh[p.id]))[0];
      if (!hit) return toast('Clique dentro da planta.', true);
      const piso = hit.object.userData.piso, x = snap(hit.point.x - OX), y = snap(hit.point.z - OZ);
      if (modoAdd === 'wp') {
        const c = sel && sel.k === 'cam' ? sel.o : null;
        if (!c) { fimDesenho(); return; }
        if (piso !== c.piso) return toast('Marque o caminho no pavimento da câmera (' + pisoById(c.piso).nome + ').', true);
        (c.pts = Array.isArray(c.pts) ? c.pts : []).push({ x, y });
        montarDin(); painelSel(); marcarMudanca();
        return;   // continua desenhando até "Concluir" ou Esc
      }
      if (modoAdd === 'cam') {
        const num = L.cams.length + 1;
        const c = { id: 'c' + (L.seq++), nome: 'CAM-' + String(num).padStart(2, '0') + ' Nova câmera', ip: null, piso, x, y, dir: Math.round(Math.atan2(P / 2 - y, W / 2 - x) * 180 / Math.PI), mod: 'd2_28' };
        L.cams.push(c); sel = { k: 'cam', o: c }; toast('Escolha a câmera do cadastro e o modelo no painel.');
      } else {
        let best = null;
        segmentos(piso).forEach(s => {
          if (s.n === s.p) return; const ab = s.B.clone().sub(s.A), l2 = ab.x * ab.x + ab.z * ab.z;
          const t = Math.max(0, Math.min(1, ((hit.point.x - s.A.x) * ab.x + (hit.point.z - s.A.z) * ab.z) / l2));
          const d = Math.hypot(s.A.x + ab.x * t - hit.point.x, s.A.z + ab.z * t - hit.point.z); if (!best || d < best.d) best = { d, s };
        });
        const num = L.nodes.filter(n => n.tipo === 'caixa').reduce((a, n) => Math.max(a, +String(n.nome).slice(3) || 0), 0) + 1;
        const ancora = L.nodes.find(n => n.tipo === 'prumada' && n.piso === piso) || rackNode();
        const n = { id: 'n' + (L.seq++), tipo: 'caixa', nome: 'CX-' + String(num).padStart(2, '0'), piso, x, y, pai: best ? best.s.p.id : ancora.id };
        if (best) best.s.n.pai = n.id;
        L.nodes.push(n); sel = { k: 'node', o: n }; toast(n.nome + ' criada: a eletrocalha agora passa por ela.');
      }
      modoAdd = null; document.querySelectorAll('#viewMaquete [data-mq-add]').forEach(k => k.classList.remove('on')); cv.classList.remove('add');
      $('mqHint').textContent = 'Puxe o cabo ou a calha para mudar o caminho · duplo clique numa curva desfaz · arraste o fundo para girar';
      montarDin(); painelSel(); marcarMudanca();
    }
  }
})();
