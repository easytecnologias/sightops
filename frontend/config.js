// URL base da API — ajuste para o ambiente
//
// Homologacao (v3) e servida em producao como sub-caminho (/v3/), atras do
// mesmo dominio publico. Sem essa checagem, o frontend do v3 chamaria
// window.location.origin + '/api/...' -- que e o /api/ de PRODUCAO
// (compartilhado no mesmo dominio) -- e a tela de teste acabaria lendo/
// escrevendo dados reais de cliente. /v3-api/ e a rota que o nginx de
// producao redireciona especificamente pro backend do v3.
const API_BASE = window.location.pathname.startsWith('/v3/')
  ? window.location.origin + '/v3-api'
  : window.location.origin;
