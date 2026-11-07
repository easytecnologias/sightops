-- Camera offline: desde quando e se o aviso ja saiu (para avisar a volta).
ALTER TABLE termico_cameras ADD COLUMN offline_desde TEXT NOT NULL DEFAULT '';
ALTER TABLE termico_cameras ADD COLUMN offline_avisado INTEGER NOT NULL DEFAULT 0;
