
from __future__ import annotations
import os, json, datetime, html
from typing import List, Dict

def slugify(name: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_ " else "-" for c in name).strip()
    s = "-".join(s.split())
    return s.lower() or "album"

def build_album(album_name: str, uploads: List[Dict[str,str]], out_dir: str = "saida/albums") -> str:
    os.makedirs(out_dir, exist_ok=True)
    slug = slugify(album_name)
    album_path = os.path.join(out_dir, slug)
    os.makedirs(album_path, exist_ok=True)

    meta = {
        "album": album_name,
        "slug": slug,
        "count": len(uploads),
        "generated_at": datetime.datetime.now().isoformat(),
        "items": uploads,
    }
    with open(os.path.join(album_path, "album.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    html_items = []
    for u in uploads:
        url = html.escape(u.get("url",""))
        thumb = html.escape(u.get("thumbnail_url", url))
        fname = html.escape(u.get("file",""))
        html_items.append(
            '<div class="card">'
            f'<a href="{url}" target="_blank" rel="noopener">'
            f'<img src="{thumb}" alt="{fname}"/>'
            '</a>'
            f'<div class="caption">{fname}</div>'
            '</div>'
        )
    page = (
        '<!DOCTYPE html>\n'
        '<html lang="pt-br">\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        f'<title>Album - {html.escape(album_name)}</title>\n'
        '<style>\n'
        'body{font-family:Arial,Helvetica,sans-serif;background:#111;color:#eee;margin:0;padding:24px}\n'
        'h1{margin:0 0 16px 0;font-size:20px}\n'
        '.wrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}\n'
        '.card{background:#1b1b1b;border:1px solid #2a2a2a;border-radius:8px;padding:8px}\n'
        '.card img{width:100%;height:160px;object-fit:cover;border-radius:6px;display:block}\n'
        '.caption{font-size:12px;margin-top:6px;color:#aaa;word-break:break-all}\n'
        '.meta{color:#9e9e9e;font-size:12px;margin-bottom:16px}\n'
        'a{color:#9cd3ff}\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        f'<h1>Album: {html.escape(album_name)}</h1>\n'
        f'<div class="meta">Imagens: {len(uploads)}</div>\n'
        '<div class="wrap">\n'
        + "".join(html_items) +
        '\n</div>\n'
        '</body>\n'
        '</html>\n'
    )
    out_html = os.path.join(album_path, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)
    return out_html
