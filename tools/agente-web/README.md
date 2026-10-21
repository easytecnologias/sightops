# SightOps Agent (acesso web aos equipamentos)

Roda no PC do operador. A tela do SightOps chama `http://127.0.0.1:47600/open`
e o agente abre uma porta local que repassa os bytes pela ponte
`/ws/web-tunnel/<ip>` (app/api/endpoints/ws.py) ate o IP virtual do conector.
A pagina do equipamento nao e reescrita no caminho.

Trazido de `cam-snapshot-web-v2/agent` em 21/10/2026 (v1.1.0 -> 1.2.0).

## Modos

- padrao (porta): `http://127.0.0.1:<porta aleatoria>/`. Usado no gateway
  Ruijie: sem ":" no endereco o eWeb pula para https.
- `modo=ip` (1.2.0): `http://127.77.0.N/` -- IP de loopback so do equipamento e
  a mesma porta dele. Camera UNV monta `"ws://" + location.host + ":" + porta`
  e com porta no endereco ficava branca depois do login. IP proprio tambem
  separa os cookies (cookie nao olha porta). Se a porta estiver ocupada no PC,
  cai numa aleatoria no mesmo IP.

## Gerar o .exe

```
cd tools/agente-web
npm install
npx --yes pkg@5.8.1 sightops-agent.js --targets node18-win-x64 --output dist/sightops-agent.exe
```

Publicar: copiar `dist/sightops-agent.exe` para
`/home/central/sightops-v3-release/frontend/downloads/sightops-agent.exe`
(o botao "Baixar agente" de Conectores serve esse arquivo).

## Testar sem mexer no agente instalado

`SIGHTOPS_AGENT_PORT=47611` sobe o controle em outra porta.
