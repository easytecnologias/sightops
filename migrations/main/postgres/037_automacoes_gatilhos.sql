-- Automacoes "Se... entao...": varios gatilhos (pessoa, camera offline, usina
-- sem comunicacao, horario, sol, toque no app), periodo em que valem e quando
-- cada gatilho agendado rodou pela ultima vez (para nao repetir no mesmo dia).
ALTER TABLE automacoes ADD COLUMN gatilhos TEXT NOT NULL DEFAULT '';
ALTER TABLE automacoes ADD COLUMN periodo TEXT NOT NULL DEFAULT '';
ALTER TABLE automacoes ADD COLUMN agenda TEXT NOT NULL DEFAULT '';
