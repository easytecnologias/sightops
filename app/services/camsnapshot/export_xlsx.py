# camsnapshot/export_xlsx.py (v1.11  estilo + ordem status/ping)
from __future__ import annotations
import pandas as pd
from pathlib import Path

def _pick_ping_col(cols):
    # compat: alguns CSVs têm 'ping', outros 'ping_ms'
    return "ping" if "ping" in cols else ("ping_ms" if "ping_ms" in cols else None)

def create_xlsx_from_csv(csv_path: str, xlsx_path: str):
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, encoding="utf-8")

    ping_col = _pick_ping_col(df.columns)

    # ordem desejada (status ANTES do ping)
    base_order = ["ip","mac","fabricante","modelo","titulo","snapshot_path","status"]
    if ping_col:
        base_order.append(ping_col)
    base_order += ["snapshot_url","thumb_url"]

    order = [c for c in base_order if c in df.columns]
    rest  = [c for c in df.columns if c not in order]
    df = df[order + rest]

    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="inventario")
        ws  = writer.sheets["inventario"]
        wb  = writer.book

        # larguras + quebra de linha
        widths = {"ip":14,"mac":18,"modelo":16,"fabricante":16,"titulo":28,"snapshot_path":30,
                  "status":10, "ping":10, "ping_ms":10, "snapshot_url":40,"thumb_url":40}
        header = list(df.columns)
        wrap = wb.add_format({"text_wrap": True})
        for col_idx, col_name in enumerate(header):
            ws.set_column(col_idx, col_idx, widths.get(col_name, 14), wrap)

        # formatação condicional de status
        if "status" in header:
            c = header.index("status"); nrows = len(df)
            fmt_on  = wb.add_format({"font_color": "green"})
            fmt_off = wb.add_format({"font_color": "red"})
            ws.conditional_format(1, c, nrows, c, {"type":"text","criteria":"containing","value":"online","format":fmt_on})
            ws.conditional_format(1, c, nrows, c, {"type":"text","criteria":"containing","value":"offline","format":fmt_off})

        # deixar links clicáveis
        for link_col in ("snapshot_url","thumb_url"):
            if link_col in header:
                c = header.index(link_col)
                for i, url in enumerate(df[link_col].fillna("").astype(str).tolist(), start=1):
                    if url.startswith("http"):
                        ws.write_url(i, c, url, string=url)

        # aplicar Tabela com estilo verde (igual ao seu print)
        # estilos válidos: "Table Style Medium 1..28"  o 9 é o verde clássico
        nrows, ncols = len(df)+1, len(header)  # +1 por causa do cabeçalho
        ws.add_table(0, 0, nrows-1, ncols-1, {
            "name": "cam_inventory",
            "style": "Table Style Medium 9",
            "columns": [{"header": h} for h in header],
            # sem filtros extras aqui (o estilo já aplica cabeçalho)
        })
