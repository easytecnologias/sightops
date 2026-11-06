-- Quantos celulares nao receberam o aviso deste alerta (vai ao Zabbix).
ALTER TABLE termico_alertas ADD COLUMN aviso_falhas INTEGER NOT NULL DEFAULT 0;
