from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.core.paths import OUTPUT_DIR

A4_W = 2480
A4_H = 3508
MARGIN = 110


def _text(value: Any) -> str:
    return str(value or "").strip()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, value: Any, font: ImageFont.ImageFont, width: int) -> str:
    text = _text(value) or "-"
    if draw.textlength(text, font=font) <= width:
        return text
    base = text
    while base:
        base = base[:-1]
        candidate = base + "..."
        if draw.textlength(candidate, font=font) <= width:
            return candidate
    return "..."


def _new_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page = Image.new("RGB", (A4_W, A4_H), "#f6f8fc")
    return page, ImageDraw.Draw(page)


def _draw_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> int:
    draw.rounded_rectangle((MARGIN, 80, A4_W - MARGIN, 270), radius=28, fill="#0f2748")
    draw.text((MARGIN + 45, 118), title, font=_font(48, True), fill="#ffffff")
    draw.text((MARGIN + 45, 188), subtitle, font=_font(24), fill="#cbd5e1")
    return 330


def _line(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: Any, width: int = 700) -> None:
    label_font = _font(21, True)
    value_font = _font(24)
    draw.text((x, y), label, font=label_font, fill="#64748b")
    draw.text((x, y + 30), _fit(draw, value, value_font, width), font=value_font, fill="#0f172a")


def _yesno(value: Any) -> str:
    if value is True:
        return "Sim"
    if value is False:
        return "Nao"
    text = _text(value)
    return text if text else "-"


def _draw_items(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, items: List[str], font_size: int = 20, line_h: int = 42, limit: int = 10) -> int:
    font = _font(font_size)
    for item in items[:limit]:
        draw.text((x, y), _fit(draw, item, font, width), font=font, fill="#0f172a")
        y += line_h
    if len(items) > limit:
        draw.text((x, y), f"+ {len(items) - limit} itens adicionais", font=_font(font_size), fill="#64748b")
        y += line_h
    return y


def _box(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str) -> None:
    draw.rounded_rectangle(xy, radius=22, fill="#ffffff", outline="#d9e2ef", width=2)
    draw.text((xy[0] + 24, xy[1] + 18), title, font=_font(24, True), fill="#0f2748")


def _compact_kv(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: Any, width: int, value_size: int = 20) -> int:
    draw.text((x, y), label, font=_font(16, True), fill="#64748b")
    draw.text((x, y + 22), _fit(draw, value, _font(value_size), width), font=_font(value_size), fill="#0f172a")
    return y + 58


def _draw_photo_card(page: Image.Image, draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], asset: Dict[str, Any]) -> None:
    _box(draw, xy, _text(asset.get("label")) or "Foto")
    img_box = (xy[0] + 24, xy[1] + 62, xy[2] - 24, xy[3] - 66)
    path = Path(_text(asset.get("local_path")))
    if path.exists():
        try:
            with Image.open(path) as raw:
                img = ImageOps.exif_transpose(raw).convert("RGB")
                img.thumbnail((img_box[2] - img_box[0], img_box[3] - img_box[1]))
                px = img_box[0] + ((img_box[2] - img_box[0]) - img.width) // 2
                py = img_box[1] + ((img_box[3] - img_box[1]) - img.height) // 2
                page.paste(img, (px, py))
        except Exception:
            draw.text((img_box[0], img_box[1]), "Imagem indisponivel", font=_font(20), fill="#64748b")
    title = _fit(draw, asset.get("title") or asset.get("query"), _font(15), xy[2] - xy[0] - 48)
    source = _fit(draw, asset.get("source_url"), _font(13), xy[2] - xy[0] - 48)
    draw.text((xy[0] + 24, xy[3] - 54), title, font=_font(15), fill="#0f172a")
    draw.text((xy[0] + 24, xy[3] - 30), source, font=_font(13), fill="#64748b")


def _summary_page(rows: List[Dict[str, Any]]) -> Image.Image:
    page, draw = _new_page()
    y = _draw_header(
        draw,
        "Inventario Windows",
        "Relatorio de computadores, hardware, armazenamento e memoria",
    )
    total = len(rows)
    online = sum(1 for r in rows if _text(r.get("status")) in ("online", "agent_reported"))
    with_ssd = sum(1 for r in rows if r.get("has_ssd"))
    cards = [
        ("Computadores", total),
        ("Online", online),
        ("Com SSD", with_ssd),
        ("Sem SSD", max(0, online - with_ssd)),
    ]
    card_w = (A4_W - (MARGIN * 2) - 45) // 4
    for idx, (label, value) in enumerate(cards):
        x = MARGIN + idx * (card_w + 15)
        draw.rounded_rectangle((x, y, x + card_w, y + 210), radius=22, fill="#ffffff", outline="#d9e2ef", width=2)
        draw.text((x + 28, y + 34), label, font=_font(24, True), fill="#64748b")
        draw.text((x + 28, y + 90), str(value), font=_font(62, True), fill="#0f2748")
    y += 290

    draw.text((MARGIN, y), "Resumo dos computadores", font=_font(34, True), fill="#0f172a")
    y += 62
    head = ["IP", "Host", "Modelo", "Memoria", "Disco", "AnyDesk", "MAC"]
    widths = [190, 260, 360, 360, 420, 260, 310]
    x = MARGIN
    draw.rounded_rectangle((MARGIN, y, A4_W - MARGIN, y + 54), radius=10, fill="#e2e8f0")
    for label, width in zip(head, widths):
        draw.text((x + 12, y + 14), label, font=_font(18, True), fill="#334155")
        x += width
    y += 62
    row_font = _font(18)
    for row in rows[:28]:
        x = MARGIN
        values = [
            row.get("ip"),
            row.get("hostname"),
            " ".join(v for v in [_text(row.get("manufacturer")), _text(row.get("model"))] if v),
            row.get("memory_summary") or (str(row.get("ram_gb") or "") + " GB"),
            row.get("disk_summary") or row.get("disk_kind"),
            row.get("anydesk_id"),
            row.get("mac"),
        ]
        draw.line((MARGIN, y - 8, A4_W - MARGIN, y - 8), fill="#e2e8f0", width=1)
        for value, width in zip(values, widths):
            draw.text((x + 12, y), _fit(draw, value, row_font, width - 24), font=row_font, fill="#0f172a")
            x += width
        y += 48
    return page


def _detail_page(row: Dict[str, Any]) -> Image.Image:
    page, draw = _new_page()
    host = _text(row.get("hostname")) or _text(row.get("ip")) or "Computador"
    y = _draw_header(draw, host, "Ficha tecnica consolidada do computador")
    left = MARGIN
    right = A4_W // 2 + 20
    col_w = (A4_W - (MARGIN * 2) - 28) // 2
    os_info = row.get("os") if isinstance(row.get("os"), dict) else {}
    cpu = row.get("cpu") if isinstance(row.get("cpu"), dict) else {}
    security = row.get("security") if isinstance(row.get("security"), dict) else {}
    gpu_names = ", ".join(_text(g.get("name")) for g in (row.get("gpus") or []) if isinstance(g, dict) and _text(g.get("name")))

    _box(draw, (left, y, left + col_w, y + 390), "Identificacao")
    yy = y + 68
    yy = _compact_kv(draw, left + 24, yy, "Fabricante / modelo", " ".join(v for v in [_text(row.get("manufacturer")), _text(row.get("model"))] if v), col_w - 48, 22)
    yy = _compact_kv(draw, left + 24, yy, "Serial / SKU", " / ".join(v for v in [_text(row.get("serial")), _text(row.get("system_sku"))] if v), col_w - 48)
    yy = _compact_kv(draw, left + 24, yy, "IP / MAC", " / ".join(v for v in [_text(row.get("ip")), _text(row.get("mac"))] if v), col_w - 48)
    yy = _compact_kv(draw, left + 24, yy, "AnyDesk", row.get("anydesk_id"), col_w - 48)
    _compact_kv(draw, left + 24, yy, "Usuario", row.get("logged_user"), col_w - 48)

    _box(draw, (right, y, A4_W - MARGIN, y + 390), "Sistema, CPU e seguranca")
    yy = y + 68
    yy = _compact_kv(draw, right + 24, yy, "Windows", " / ".join(v for v in [_text(os_info.get("name")), _text(os_info.get("build"))] if v), col_w - 48, 22)
    yy = _compact_kv(draw, right + 24, yy, "CPU", cpu.get("name"), col_w - 48)
    yy = _compact_kv(draw, right + 24, yy, "GPU", gpu_names, col_w - 48)
    _compact_kv(draw, right + 24, yy, "TPM / Secure Boot / Defender", f"{_yesno(security.get('tpm_ready'))} / {_yesno(security.get('secure_boot'))} / {_yesno(security.get('defender_realtime'))}", col_w - 48)
    y += 424

    _box(draw, (left, y, A4_W - MARGIN, y + 260), "Resumo de capacidade")
    _compact_kv(draw, left + 24, y + 70, "Memoria", row.get("memory_summary") or row.get("ram_gb"), 650, 22)
    _compact_kv(draw, left + 740, y + 70, "Armazenamento", row.get("disk_summary") or row.get("disk_kind"), 950, 22)
    batteries = row.get("batteries") if isinstance(row.get("batteries"), list) else []
    battery_txt = ""
    if batteries and isinstance(batteries[0], dict):
        battery_txt = f"{batteries[0].get('name') or 'Bateria'} - {batteries[0].get('estimated_charge') or '-'}%"
    _compact_kv(draw, left + 1760, y + 70, "Bateria", battery_txt or "Nao informada", 420)
    y += 294

    _box(draw, (left, y, right - 14, y + 430), "Modulos de memoria")
    mem_items = []
    for module in (row.get("memory_modules") or [])[:6]:
        if not isinstance(module, dict):
            continue
        mem_items.append(" - ".join(v for v in [
            _text(module.get("slot")),
            f"{module.get('capacity_gb')} GB" if module.get("capacity_gb") else "",
            _text(module.get("ddr")),
            (str(module.get("configured_speed_mhz") or module.get("speed_mhz")) + " MHz") if (module.get("configured_speed_mhz") or module.get("speed_mhz")) else "",
            _text(module.get("manufacturer")),
            _text(module.get("part_number")),
        ] if v))
    _draw_items(draw, left + 24, y + 64, col_w - 50, mem_items or ["Memoria nao detalhada"], font_size=18, line_h=38, limit=8)

    _box(draw, (right, y, A4_W - MARGIN, y + 430), "Discos e volumes")
    disk_items = []
    for disk in (row.get("disks") or [])[:3]:
        if not isinstance(disk, dict):
            continue
        size = disk.get("size_gb")
        size_txt = ""
        try:
            value = float(size)
            size_txt = f"{round(value / 1024, 2)} TB" if value >= 1024 else f"{round(value)} GB"
        except Exception:
            pass
        disk_items.append(" - ".join(v for v in [size_txt, _text(disk.get("media_type")), _text(disk.get("manufacturer")), _text(disk.get("model")), _text(disk.get("serial"))] if v))
    for volume in (row.get("volumes") or [])[:3]:
        if isinstance(volume, dict):
            disk_items.append(f"{volume.get('drive')} {volume.get('file_system') or ''}: {volume.get('size_gb') or '-'} GB / livre {volume.get('free_gb') or '-'} GB ({volume.get('free_percent') or '-'}%)")
    _draw_items(draw, right + 24, y + 64, col_w - 50, disk_items or ["Disco nao detalhado"], font_size=18, line_h=38, limit=8)
    y += 464

    _box(draw, (left, y, right - 14, y + 360), "Rede")
    network_items = []
    for net in (row.get("network") or [])[:5]:
        if not isinstance(net, dict):
            continue
        ips = ", ".join(_text(v) for v in (net.get("ip") or []) if _text(v))
        network_items.append(" - ".join(v for v in [_text(net.get("description")), _text(net.get("mac")), ips] if v))
    _draw_items(draw, left + 24, y + 64, col_w - 50, network_items or ["Nenhuma interface informada"], font_size=18, line_h=38, limit=6)

    _box(draw, (right, y, A4_W - MARGIN, y + 360), "Pontos de atencao")
    flags = [str(x) for x in (row.get("health_flags") or []) if str(x).strip()]
    updates = []
    for hf in (row.get("hotfixes") or [])[:3]:
        if isinstance(hf, dict):
            updates.append(f"Update {hf.get('id') or '-'} - {hf.get('installed_on') or ''}")
    _draw_items(draw, right + 24, y + 64, col_w - 50, (flags or ["Nenhum ponto critico detectado"]) + updates, font_size=18, line_h=38, limit=7)
    y += 400

    photos = [a for a in (row.get("photo_assets") or []) if isinstance(a, dict)]
    if photos:
        draw.text((left, y), "Fotos de referencia", font=_font(26, True), fill="#0f172a")
        y += 44
        card_w = (A4_W - (MARGIN * 2) - 42) // 3
        card_h = 360
        for idx, asset in enumerate(photos[:3]):
            x = left + idx * (card_w + 21)
            _draw_photo_card(page, draw, (x, y, x + card_w, y + card_h), asset)
    return page


def _legacy_detail_page(row: Dict[str, Any]) -> Image.Image:
    page, draw = _new_page()
    host = _text(row.get("hostname")) or _text(row.get("ip")) or "Computador"
    y = _draw_header(draw, host, "Ficha tecnica do computador")
    left = MARGIN
    right = A4_W // 2 + 20
    _box(draw, (left, y, A4_W - MARGIN, y + 420), "Identificacao")
    _line(draw, left + 30, y + 85, "IP", row.get("ip"))
    _line(draw, left + 500, y + 85, "MAC", row.get("mac"), 520)
    _line(draw, left + 30, y + 185, "Fabricante / modelo", " ".join(v for v in [_text(row.get("manufacturer")), _text(row.get("model"))] if v), 980)
    _line(draw, left + 30, y + 285, "Serial", row.get("serial"))
    _line(draw, left + 500, y + 285, "Usuario logado", row.get("logged_user"), 620)
    _line(draw, left + 1180, y + 285, "SKU", row.get("system_sku"), 500)
    y += 480

    _box(draw, (left, y, A4_W - MARGIN, y + 500), "Sistema e processamento")
    os_info = row.get("os") if isinstance(row.get("os"), dict) else {}
    cpu = row.get("cpu") if isinstance(row.get("cpu"), dict) else {}
    _line(draw, left + 30, y + 85, "Windows", " / ".join(v for v in [_text(os_info.get("name")), _text(os_info.get("build"))] if v), 1000)
    _line(draw, left + 30, y + 185, "CPU", cpu.get("name"), 1000)
    _line(draw, left + 30, y + 285, "Memoria", row.get("memory_summary") or row.get("ram_gb"), 1000)
    _line(draw, left + 30, y + 385, "Armazenamento", row.get("disk_summary") or row.get("disk_kind"), 1000)
    gpu_names = ", ".join(_text(g.get("name")) for g in (row.get("gpus") or []) if isinstance(g, dict) and _text(g.get("name")))
    _line(draw, left + 1180, y + 185, "GPU", gpu_names, 760)
    security = row.get("security") if isinstance(row.get("security"), dict) else {}
    _line(draw, left + 1180, y + 285, "TPM / Secure Boot", f"TPM: {_yesno(security.get('tpm_ready'))} / Secure Boot: {_yesno(security.get('secure_boot'))}", 760)
    _line(draw, left + 1180, y + 385, "Defender", f"Ativo: {_yesno(security.get('defender_enabled'))} / Tempo real: {_yesno(security.get('defender_realtime'))}", 760)
    y += 560

    _box(draw, (left, y, right - 20, y + 780), "Modulos de memoria")
    mem_y = y + 85
    for module in (row.get("memory_modules") or [])[:8]:
        if not isinstance(module, dict):
            continue
        txt = " - ".join(
            v for v in [
                _text(module.get("slot")),
                f"{module.get('capacity_gb')} GB" if module.get("capacity_gb") else "",
                _text(module.get("ddr")),
                (str(module.get("configured_speed_mhz") or module.get("speed_mhz")) + " MHz") if (module.get("configured_speed_mhz") or module.get("speed_mhz")) else "",
                _text(module.get("manufacturer")),
                _text(module.get("part_number")),
            ] if v
        )
        draw.text((left + 28, mem_y), _fit(draw, txt, _font(20), 930), font=_font(20), fill="#0f172a")
        mem_y += 62

    _box(draw, (right, y, A4_W - MARGIN, y + 780), "Discos")
    disk_y = y + 85
    for disk in (row.get("disks") or [])[:8]:
        if not isinstance(disk, dict):
            continue
        size = disk.get("size_gb")
        size_txt = ""
        try:
            value = float(size)
            size_txt = f"{round(value / 1024, 2)} TB" if value >= 1024 else f"{round(value)} GB"
        except Exception:
            pass
        txt = " - ".join(
            v for v in [
                size_txt,
                _text(disk.get("media_type")),
                _text(disk.get("manufacturer")),
                _text(disk.get("model")),
                _text(disk.get("serial")),
            ] if v
        )
        draw.text((right + 28, disk_y), _fit(draw, txt, _font(20), 930), font=_font(20), fill="#0f172a")
        disk_y += 62
    photos = [a for a in (row.get("photo_assets") or []) if isinstance(a, dict)]
    if photos:
        y += 840
        draw.text((left, y), "Fotos de referencia encontradas na internet", font=_font(30, True), fill="#0f172a")
        y += 58
        card_w = (A4_W - (MARGIN * 2) - 28) // 2
        card_h = 500
        for idx, asset in enumerate(photos[:4]):
            x = left + (idx % 2) * (card_w + 28)
            yy = y + (idx // 2) * (card_h + 26)
            _draw_photo_card(page, draw, (x, yy, x + card_w, yy + card_h), asset)
    return page


def _technical_page(row: Dict[str, Any]) -> Image.Image:
    page, draw = _new_page()
    host = _text(row.get("hostname")) or _text(row.get("ip")) or "Computador"
    y = _draw_header(draw, host, "Detalhamento profissional do hardware e seguranca")
    left = MARGIN
    mid = A4_W // 2 + 20
    box_h = 610

    _box(draw, (left, y, mid - 20, y + box_h), "Rede")
    network_items = []
    for net in (row.get("network") or []):
        if not isinstance(net, dict):
            continue
        ips = ", ".join(_text(v) for v in (net.get("ip") or []) if _text(v))
        network_items.append(" - ".join(v for v in [_text(net.get("description")), _text(net.get("mac")), ips] if v))
    _draw_items(draw, left + 28, y + 82, mid - left - 90, network_items or ["Nenhuma interface informada"], limit=9)

    _box(draw, (mid, y, A4_W - MARGIN, y + box_h), "Seguranca")
    security = row.get("security") if isinstance(row.get("security"), dict) else {}
    sec_items = [
        f"TPM presente: {_yesno(security.get('tpm_present'))}",
        f"TPM pronto: {_yesno(security.get('tpm_ready'))}",
        f"Secure Boot: {_yesno(security.get('secure_boot'))}",
        f"Defender ativo: {_yesno(security.get('defender_enabled'))}",
        f"Protecao em tempo real: {_yesno(security.get('defender_realtime'))}",
        f"BitLocker: {security.get('bitlocker_protected_volumes', 0)} de {security.get('bitlocker_total_volumes', 0)} volumes protegidos",
    ]
    _draw_items(draw, mid + 28, y + 82, A4_W - MARGIN - mid - 80, sec_items, limit=10)
    y += box_h + 34

    _box(draw, (left, y, mid - 20, y + box_h), "Volumes")
    volume_items = []
    for volume in (row.get("volumes") or []):
        if not isinstance(volume, dict):
            continue
        volume_items.append(
            f"{volume.get('drive')} {volume.get('label') or ''} - {volume.get('file_system') or ''} - "
            f"{volume.get('size_gb') or '-'} GB / livre {volume.get('free_gb') or '-'} GB ({volume.get('free_percent') or '-'}%)"
        )
    _draw_items(draw, left + 28, y + 82, mid - left - 90, volume_items or ["Nenhum volume informado"], limit=9)

    _box(draw, (mid, y, A4_W - MARGIN, y + box_h), "BIOS, bateria e atualizacoes")
    batteries = row.get("batteries") if isinstance(row.get("batteries"), list) else []
    battery_txt = "Sem bateria informada"
    if batteries and isinstance(batteries[0], dict):
        battery_txt = f"{batteries[0].get('name') or 'Bateria'} - carga estimada {batteries[0].get('estimated_charge') or '-'}%"
    os_info = row.get("os") if isinstance(row.get("os"), dict) else {}
    items = [
        f"BIOS: {row.get('motherboard', {}).get('manufacturer') if isinstance(row.get('motherboard'), dict) else ''} / {row.get('serial') or '-'}",
        f"Ultimo boot: {os_info.get('last_boot') or '-'}",
        f"Timezone: {row.get('timezone') or '-'}",
        battery_txt,
    ]
    for hf in (row.get("hotfixes") or [])[:4]:
        if isinstance(hf, dict):
            items.append(f"Update: {hf.get('id') or '-'} - {hf.get('installed_on') or ''}")
    _draw_items(draw, mid + 28, y + 82, A4_W - MARGIN - mid - 80, items, limit=10)
    y += box_h + 34

    flags = [str(x) for x in (row.get("health_flags") or []) if str(x).strip()]
    _box(draw, (left, y, A4_W - MARGIN, y + 360), "Pontos de atencao")
    _draw_items(draw, left + 28, y + 82, A4_W - (MARGIN * 2) - 70, flags or ["Nenhum ponto critico detectado pelos criterios atuais."], font_size=22, line_h=48, limit=5)
    return page


def build_windows_inventory_pdf(rows: List[Dict[str, Any]], company_name: str = "") -> Path:
    reports_dir = OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_company = "".join(ch for ch in _text(company_name) if ch.isalnum() or ch in ("-", "_")) or "windows"
    out = reports_dir / f"windows-inventory-{safe_company}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    pages = [_summary_page(rows)]
    for row in rows:
        pages.append(_detail_page(row))
    first, rest = pages[0], pages[1:]
    first.save(out, "PDF", resolution=150.0, save_all=True, append_images=rest)
    return out
