import asyncio
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from app.api.endpoints import tools


def _make_kmz(path: Path, name: str = "CAM 01") -> None:
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>{name}</name>
      <Point><coordinates>-37.1,-9.1,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)


def _make_kmz_with_inline_icon_style(path: Path, name: str = "CAM 01") -> None:
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>{name}</name>
      <Style>
        <IconStyle>
          <Icon><href>files/old-red-x.png</href></Icon>
        </IconStyle>
      </Style>
      <Point><coordinates>-37.1,-9.1,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)


def test_imported_layer_can_be_renamed_and_downloaded_enriched(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        layers_dir = root / "layers"
        generated_dir = root / "generated"
        imported_current = root / "imported.kmz"
        imported_geojson = root / "imported.geojson"
        input_dir = root / "input"
        output_dir = root / "output"
        for p in (layers_dir, generated_dir, input_dir, output_dir):
            p.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: layers_dir)
        monkeypatch.setattr(tools, "_kmz_generated_layers_dir", lambda: generated_dir)
        monkeypatch.setattr(tools, "tenant_kmz_imported_path", lambda: imported_current)
        monkeypatch.setattr(tools, "tenant_kmz_imported_geojson_path", lambda: imported_geojson)
        monkeypatch.setattr(tools, "tenant_kmz_input_dir", lambda: input_dir)
        monkeypatch.setattr(tools, "tenant_kmz_output_dir", lambda: output_dir)
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "teste")
        monkeypatch.setattr(
            tools,
            "_load_rows_by_source",
            lambda source, mode="": [{
                "ip": "10.0.0.10",
                "titulo": "CAM 01",
                "title": "CAM 01",
                "status": "online",
                "local": "LOCAL TESTE",
                "modelo": "IPC-TESTE",
                "mac": "aa:bb:cc:dd:ee:ff",
            }],
        )

        layer_id = "layer-01"
        kmz_path, geojson_path, meta_path = tools._kmz_layer_paths(layer_id)
        _make_kmz(kmz_path)
        geojson_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "CAM 01"},
                "geometry": {"type": "Point", "coordinates": [-37.1, -9.1]},
            }],
        }), encoding="utf-8")
        meta_path.write_text(json.dumps({
            "id": layer_id,
            "label": "Nome errado",
            "original_name": "original.kmz",
        }), encoding="utf-8")

        rename = asyncio.run(tools.api_kmz_import_layer_update(layer_id, {"label": "Nome certo"}))
        assert rename["ok"] is True
        assert rename["layer"]["label"] == "Nome certo"

        download = asyncio.run(tools.api_kmz_import_layer_download_enriched(layer_id, source="ip", mode="olt"))
        assert download.media_type == "application/vnd.google-earth.kmz"
        with zipfile.ZipFile(Path(download.path)) as zf:
            text = zf.read("doc.kml").decode("utf-8")
        assert "<href>cctv-green.png</href>" in text
        assert "aa:bb:cc:dd:ee:ff" in text
        assert "10.0.0.10" in text

        generated_layers = tools._list_kmz_generated_layers(include_features=False)
        assert generated_layers == []


def test_enriched_download_removes_inline_icon_style_that_overrides_camera_icons(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        layers_dir = root / "layers"
        generated_dir = root / "generated"
        imported_current = root / "imported.kmz"
        imported_geojson = root / "imported.geojson"
        input_dir = root / "input"
        output_dir = root / "output"
        for p in (layers_dir, generated_dir, input_dir, output_dir):
            p.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: layers_dir)
        monkeypatch.setattr(tools, "_kmz_generated_layers_dir", lambda: generated_dir)
        monkeypatch.setattr(tools, "tenant_kmz_imported_path", lambda: imported_current)
        monkeypatch.setattr(tools, "tenant_kmz_imported_geojson_path", lambda: imported_geojson)
        monkeypatch.setattr(tools, "tenant_kmz_input_dir", lambda: input_dir)
        monkeypatch.setattr(tools, "tenant_kmz_output_dir", lambda: output_dir)
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "teste")
        monkeypatch.setattr(
            tools,
            "_load_rows_by_source",
            lambda source, mode="": [{
                "ip": "10.0.0.10",
                "titulo": "CAM 01",
                "title": "CAM 01",
                "status": "online",
                "local": "LOCAL TESTE",
            }],
        )

        layer_id = "inline-style"
        kmz_path, geojson_path, meta_path = tools._kmz_layer_paths(layer_id)
        _make_kmz_with_inline_icon_style(kmz_path)
        geojson_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "CAM 01"},
                "geometry": {"type": "Point", "coordinates": [-37.1, -9.1]},
            }],
        }), encoding="utf-8")
        meta_path.write_text(json.dumps({"id": layer_id, "label": "Inline"}), encoding="utf-8")

        download = asyncio.run(tools.api_kmz_import_layer_download_enriched(layer_id, source="ip", mode="olt"))
        with zipfile.ZipFile(Path(download.path)) as zf:
            text = zf.read("doc.kml").decode("utf-8")

        first_placemark = text.split("<Placemark", 1)[1].split("</Placemark>", 1)[0]
        assert "old-red-x.png" not in text
        assert "<Style>" not in first_placemark
        assert "<href>cctv-green.png</href>" in text


def test_generated_layer_download_repairs_missing_icon_package(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        layers_dir = root / "layers"
        generated_dir = root / "generated"
        imported_current = root / "imported.kmz"
        imported_geojson = root / "imported.geojson"
        input_dir = root / "input"
        output_dir = root / "output"
        for p in (layers_dir, generated_dir, input_dir, output_dir):
            p.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: layers_dir)
        monkeypatch.setattr(tools, "_kmz_generated_layers_dir", lambda: generated_dir)
        monkeypatch.setattr(tools, "tenant_kmz_imported_path", lambda: imported_current)
        monkeypatch.setattr(tools, "tenant_kmz_imported_geojson_path", lambda: imported_geojson)
        monkeypatch.setattr(tools, "tenant_kmz_input_dir", lambda: input_dir)
        monkeypatch.setattr(tools, "tenant_kmz_output_dir", lambda: output_dir)
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "teste")
        monkeypatch.setattr(
            tools,
            "_load_rows_by_source",
            lambda source, mode="": [{
                "ip": "10.0.0.10",
                "titulo": "CAM 01",
                "title": "CAM 01",
                "status": "offline",
                "local": "LOCAL TESTE",
                "modelo": "IPC-TESTE",
                "mac": "aa:bb:cc:dd:ee:ff",
            }],
        )

        import_id = "import-01"
        import_kmz, import_geojson_path, import_meta = tools._kmz_layer_paths(import_id)
        _make_kmz(import_kmz)
        import_geojson_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "CAM 01"},
                "geometry": {"type": "Point", "coordinates": [-37.1, -9.1]},
            }],
        }), encoding="utf-8")
        import_meta.write_text(json.dumps({"id": import_id, "label": "Original"}), encoding="utf-8")

        generated_id = "generated-old"
        generated_kmz, generated_geojson, generated_meta = tools._kmz_generated_layer_paths(generated_id)
        _make_kmz(generated_kmz)
        generated_geojson.write_text(import_geojson_path.read_text(encoding="utf-8"), encoding="utf-8")
        generated_meta.write_text(json.dumps({
            "id": generated_id,
            "label": "Mapa antigo",
            "original_name": "mapa-antigo.kmz",
            "source_layer_id": import_id,
            "source": "ip",
            "mode": "olt",
        }), encoding="utf-8")

        download = asyncio.run(tools.api_kmz_generated_layer_download(generated_id))
        with zipfile.ZipFile(Path(download.path)) as zf:
            names = zf.namelist()
            text = zf.read("doc.kml").decode("utf-8")

        assert "cctv-green.png" in names
        assert "cctv-red.png" in names
        assert "<href>cctv-red.png</href>" in text
        assert "aa:bb:cc:dd:ee:ff" in text


def test_latest_generated_download_repairs_missing_icon_package(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        layers_dir = root / "layers"
        generated_dir = root / "generated"
        imported_current = root / "imported.kmz"
        imported_geojson = root / "imported.geojson"
        input_dir = root / "input"
        output_dir = root / "output"
        for p in (layers_dir, generated_dir, input_dir, output_dir):
            p.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: layers_dir)
        monkeypatch.setattr(tools, "_kmz_generated_layers_dir", lambda: generated_dir)
        monkeypatch.setattr(tools, "tenant_kmz_imported_path", lambda: imported_current)
        monkeypatch.setattr(tools, "tenant_kmz_imported_geojson_path", lambda: imported_geojson)
        monkeypatch.setattr(tools, "tenant_kmz_input_dir", lambda: input_dir)
        monkeypatch.setattr(tools, "tenant_kmz_output_dir", lambda: output_dir)
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "teste")
        monkeypatch.setattr(
            tools,
            "_load_rows_by_source",
            lambda source, mode="": [{
                "ip": "10.0.0.10",
                "titulo": "CAM 01",
                "title": "CAM 01",
                "status": "online",
                "local": "LOCAL TESTE",
                "modelo": "IPC-TESTE",
                "mac": "aa:bb:cc:dd:ee:ff",
            }],
        )

        import_id = "import-01"
        import_kmz, import_geojson_path, import_meta = tools._kmz_layer_paths(import_id)
        _make_kmz(import_kmz)
        import_geojson_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "CAM 01"},
                "geometry": {"type": "Point", "coordinates": [-37.1, -9.1]},
            }],
        }), encoding="utf-8")
        import_meta.write_text(json.dumps({"id": import_id, "label": "Original"}), encoding="utf-8")

        generated_id = "generated-latest"
        generated_kmz, generated_geojson, generated_meta = tools._kmz_generated_layer_paths(generated_id)
        _make_kmz(generated_kmz)
        shutil.copyfile(generated_kmz, output_dir / generated_kmz.name)
        generated_geojson.write_text(import_geojson_path.read_text(encoding="utf-8"), encoding="utf-8")
        generated_meta.write_text(json.dumps({
            "id": generated_id,
            "label": "Mapa antigo",
            "original_name": "mapa-antigo.kmz",
            "source_layer_id": import_id,
            "source": "ip",
            "mode": "olt",
        }), encoding="utf-8")

        download = asyncio.run(tools.api_kmz_generated_download())
        with zipfile.ZipFile(Path(download.path)) as zf:
            names = zf.namelist()
            text = zf.read("doc.kml").decode("utf-8")

        assert "cctv-green.png" in names
        assert "cctv-red.png" in names
        assert "<href>cctv-green.png</href>" in text
        assert "aa:bb:cc:dd:ee:ff" in text
