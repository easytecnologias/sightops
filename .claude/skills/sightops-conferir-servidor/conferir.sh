#!/usr/bin/env bash
# Confere se o SightOps esta sincronizado entre git, imagem e disco, e se um
# reboot ou recreate nao vai apagar trabalho.
#
# Rode NO SERVIDOR (10.10.12.7), como o usuario central:
#     bash /tmp/conferir.sh
#
# Nao altera nada: so le. Sai com codigo 1 se achou alguma divergencia, para
# poder ser usado como portao antes de um deploy.

set -u

REPO=/home/central/sightops-v3
REL=/home/central/sightops-v3-release
API=sightops-v3-api
BKP=/mnt/dados/backups/sightops-db

problemas=0
aviso() { echo "  [!] $*"; problemas=$((problemas + 1)); }
ok()    { echo "  [ok] $*"; }
titulo(){ echo; echo "=== $* ==="; }

# --------------------------------------------------------------- 1. git
titulo "1. Git do servidor"
cd "$REPO" || { aviso "repositorio $REPO nao encontrado"; exit 1; }
sujo=$(git status --short)
if [ -n "$sujo" ]; then
  aviso "working tree sujo:"
  echo "$sujo" | sed 's/^/      /'
  echo "      (o Codex trabalha em paralelo -- nao commite arquivo alheio)"
else
  ok "working tree limpo"
fi
git fetch origin -q 2>/dev/null
frente=$(git log --oneline origin/main..HEAD 2>/dev/null | wc -l)
if [ "$frente" -gt 0 ]; then
  ok "$frente commit(s) para subir:"
  git log --oneline origin/main..HEAD | sed 's/^/      /'
else
  ok "nada para subir"
fi

# ----------------------------------------------------- 2. imagem x .env.v3
titulo "2. Imagem no ar x .env.v3"
noar=$(docker inspect "$API" --format '{{.Config.Image}}' 2>/dev/null)
esperada=$(grep '^CAM_SNAPSHOT_IMAGE=' "$REL/.env.v3" 2>/dev/null | cut -d= -f2)
echo "      no ar   : ${noar:-<container fora>}"
echo "      .env.v3 : ${esperada:-<nao definida>}"
if [ -n "$noar" ] && [ "$noar" = "$esperada" ]; then
  ok "batem -- um reboot sobe a mesma versao"
else
  aviso "DIVERGEM: o proximo 'up -d' ou boot troca a versao sem avisar"
fi
if [ -n "$esperada" ] && ! docker image inspect "$esperada" >/dev/null 2>&1; then
  aviso "a imagem de $esperada NAO existe no disco -- o container nao voltaria"
fi

# ---------------------------------------------------- 3. backend x git
titulo "3. Backend: o que roda x o que esta no git"
dif=0
# 'deploy/**' entra aqui porque o provisioner de isolamento mora la, e ele
# controla roteamento e firewall dos tuneis. Em 30/09/2026 ele ficou
# desatualizado no git enquanto rodava corrigido -- e este script deu
# "0 divergentes", porque so olhava app/ e tools/.
for f in $(git ls-files 'app/**/*.py' 'tools/*.py' 'deploy/**/*.py' 'deploy/**/*.sh' 2>/dev/null); do
  case "$f" in
    deploy/iso-provisioner/*)
      a=$(docker exec sightops-v3-iso-provisioner md5sum "/app/$(basename "$f")" 2>/dev/null | cut -d' ' -f1) ;;
    deploy/backup/*)
      a=$(md5sum "/home/central/scripts/$(basename "$f")" 2>/dev/null | cut -d' ' -f1) ;;
    deploy/*)
      # Sem lugar conhecido para comparar: versionado e so isso.
      continue ;;
    *)
      a=$(docker exec "$API" md5sum "/app/$f" 2>/dev/null | cut -d' ' -f1) ;;
  esac
  b=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
  if [ -z "$a" ]; then
    echo "      SO NO GIT (nunca deployado): $f"; dif=$((dif + 1))
  elif [ "$a" != "$b" ]; then
    echo "      DIFERE: $f"; dif=$((dif + 1))
  fi
done
[ "$dif" -eq 0 ] && ok "0 arquivos .py divergentes" || aviso "$dif arquivo(s) .py fora de sincronia"

# --------------------------------------------------- 4. frontend x git
titulo "4. Frontend: o que o /v3/ serve x o git"
# compara SEM \r: os arquivos vem misturados (CRLF do Windows, LF do servidor)
# e sem normalizar tudo parece diferente
dfront=0; total=0
for f in $(cd "$REL/frontend" 2>/dev/null && find . -type f \
           \( -name '*.js' -o -name '*.html' -o -name '*.css' \) | sed 's|^\./||'); do
  total=$((total + 1))
  if [ ! -f "$REPO/frontend/$f" ]; then
    echo "      SO NO RELEASE (fora do git): $f"; dfront=$((dfront + 1))
  elif ! diff -q <(tr -d '\r' < "$REL/frontend/$f") \
                 <(tr -d '\r' < "$REPO/frontend/$f") >/dev/null 2>&1; then
    echo "      DIFERE: $f"; dfront=$((dfront + 1))
  fi
done
[ "$dfront" -eq 0 ] && ok "0 de $total divergentes" \
                    || aviso "$dfront de $total divergentes -- some se alguem publicar do repo"

# -------------------------------------------- 5. codigo solto no container
titulo "5. Codigo solto dentro do container (morre no recreate)"
solto=$(docker diff "$API" 2>/dev/null | grep -E '^[AC] /app/(app|tools)/.*\.py$' | grep -v __pycache__)
if [ -n "$solto" ]; then
  aviso "arquivos .py que so existem no container:"
  echo "$solto" | sed 's/^/      /'
else
  ok "nenhum -- todo o codigo vem da imagem"
fi

# ------------------------------------------------------- 6. montagens
titulo "6. Montagens do disco (a armadilha do banco vazio)"
nf=$(grep -cE "/mnt/dados" /etc/fstab 2>/dev/null)
nm=$(mount | grep -cE "/mnt/dados|docker/volumes" 2>/dev/null)
echo "      fstab: $nf entrada(s)   montadas: $nm"
[ "$nf" -ge 3 ] && [ "$nm" -ge 3 ] && ok "disco montado" \
                                   || aviso "faltam montagens (esperado 3 e 3)"
rmf=$(systemctl show docker.service -p RequiresMountsFor 2>/dev/null | cut -d= -f2-)
if echo "$rmf" | grep -q "/mnt/dados"; then
  ok "Docker espera as montagens (nao sobe com banco vazio)"
else
  aviso "docker.service NAO espera as montagens."
  echo "      Se o disco falhar no boot, o Postgres roda initdb num diretorio"
  echo "      vazio e o sistema sobe com banco em branco."
  echo "      Correcao: deploy/storage/systemd/10-espera-os-volumes.conf"
fi

# --------------------------------------------------- 7. restart policy
titulo "7. Restart policy dos containers"
for c in $(docker ps --format '{{.Names}}' | grep -E 'sightops|zabbix'); do
  p=$(docker inspect "$c" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null)
  if [ "$p" = "unless-stopped" ] || [ "$p" = "always" ]; then
    printf "      %-26s %s\n" "$c" "$p"
  else
    aviso "$c com restart='$p' -- nao volta sozinho apos reboot"
  fi
done

# ------------------------------------------------------- 8. backup
titulo "8. Backup -- e se a CHAVE esta dentro dele"
if [ -f "$BKP/backup.log" ]; then
  ultimo=$(grep -c "" "$BKP/backup.log")
  tail -1 "$BKP/backup.log" | sed 's/^/      /'
  if tail -20 "$BKP/backup.log" | grep -q "falhas: 0"; then
    ok "ultima execucao sem falhas"
  else
    aviso "a ultima execucao teve falha -- leia $BKP/backup.log"
  fi
fi
CFG=$(ls -1t "$BKP"/diario/v3-config-*.tar.gz 2>/dev/null | head -1)
if [ -z "$CFG" ]; then
  aviso "nenhum backup de configuracao encontrado"
else
  echo "      config: $(basename "$CFG")"
  if tar tzf "$CFG" 2>/dev/null | grep -q '^\.env\.v3$'; then
    chave_bkp=$(tar xzf "$CFG" -O .env.v3 2>/dev/null | grep '^SIGHTOPS_SECRET_KEY=' | md5sum | cut -c1-8)
    chave_ar=$(grep '^SIGHTOPS_SECRET_KEY=' "$REL/.env.v3" 2>/dev/null | md5sum | cut -c1-8)
    if [ -n "$chave_bkp" ] && [ "$chave_bkp" = "$chave_ar" ]; then
      ok "SIGHTOPS_SECRET_KEY no backup e igual a de producao"
    else
      aviso "a chave do backup NAO bate com a de producao ($chave_bkp vs $chave_ar)"
      echo "      Sem a chave certa o dump do banco nao restaura: as senhas das"
      echo "      OLTs ficam cifradas com uma chave que nao existe mais."
    fi
  else
    aviso ".env.v3 NAO esta dentro do backup de configuracao"
    echo "      O dump do banco continua saindo, entao o backup PARECE vivo --"
    echo "      mas sem a chave ele nao restaura nada de util."
  fi
fi

# ------------------------------------------- 9. camadas da imagem
titulo "9. Camadas da imagem (o build morre em ~130)"
# Cada correcao publicada e um "FROM a anterior + COPY", entao empilha uma
# camada. O Docker para por volta de 130 e o build falha com "max depth
# exceeded" -- e falha na hora de PUBLICAR, o pior momento possivel.
# Aconteceu em 29/09/2026 no meio de uma correcao, com 131 camadas.
if [ -n "${esperada:-}" ] && docker image inspect "$esperada" >/dev/null 2>&1; then
  camadas=$(docker history -q "$esperada" 2>/dev/null | grep -c .)
  echo "      $esperada: $camadas camada(s)"
  if [ "${camadas:-0}" -ge 110 ]; then
    aviso "perto do limite -- achate a imagem ANTES do proximo deploy:"
    echo "      bash deploy/imagem/achatar-imagem.sh <imagem-atual> <nova-achatada>"
  else
    ok "longe do limite"
  fi
fi

# -------------------------------------------------------- 10. disco
titulo "10. Espaco em disco"
df -h / /mnt/dados 2>/dev/null | awk 'NR==1 || /\/$|\/mnt\/dados/ {printf "      %s\n", $0}'
# Sem awk: as linhas do 'docker system df' tem numero de colunas diferente
# ("Local Volumes", "Build Cache", e um "(78%)" que aparece so em algumas).
# Toda tentativa de alinhar por indice trocou os numeros de lugar.
docker system df 2>/dev/null | sed 's/^/      /'
echo "      (build cache recupera com 'docker builder prune -f', sem risco;"
echo "       'docker image prune -a' apaga tags de rollback -- so com o usuario)"

# ------------------------------- 11. container que nenhum compose recria
titulo "11. Containers que nenhum compose recria"
# Sobrevivem a reboot (restart: unless-stopped), entao nao doem no dia a dia.
# O risco e REMOCAO: portas, volumes e comando moram so em /var/lib/docker.
# Em 30/09/2026 eram cinco, inclusive o tunnel cujo token do Cloudflare existia
# apenas na linha de comando -- sem ele o site nao responde pela internet e nao
# ha onde consultar o valor. Ver deploy/compose/docker-compose.extras.yml.
orfaos=0
for c in $(docker ps --format '{{.Names}}' 2>/dev/null | grep -vE '^backup-'); do
  arq=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$c" 2>/dev/null)
  if [ -z "$arq" ]; then
    echo "      SEM COMPOSE: $c"
    orfaos=$((orfaos + 1))
  fi
done
EXTRAS=/home/central/sightops-v3/deploy/compose/docker-compose.extras.yml
if [ "$orfaos" -eq 0 ]; then
  ok "todo container em execucao vem de um compose"
elif [ -f "$EXTRAS" ]; then
  # Estar no extras.yml nao e problema: ele existe justamente para descrever
  # esses containers. O aviso e para quem NAO esta em lugar nenhum.
  fora=0
  for c in $(docker ps --format '{{.Names}}' 2>/dev/null | grep -vE '^backup-'); do
    arq=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$c" 2>/dev/null)
    [ -n "$arq" ] && continue
    grep -qE "^[[:space:]]*container_name: ${c}[[:space:]]*$" "$EXTRAS" 2>/dev/null || { echo "      NAO DESCRITO EM LUGAR NENHUM: $c"; fora=$((fora + 1)); }
  done
  if [ "$fora" -eq 0 ]; then
    ok "$orfaos criado(s) a mao, todos descritos em docker-compose.extras.yml"
  else
    aviso "$fora container(es) sem compose e fora do extras.yml -- se sumirem, nao ha como recriar"
  fi
else
  aviso "$orfaos container(es) sem compose e sem extras.yml -- se sumirem, nao ha como recriar"
fi

# ------------------------------- 12. o backup leva o que nao e do compose
titulo "12. Backup dos extras (CA, go2rtc, definicao dos containers)"
EXTRA_TAR=$(ls -1t /mnt/dados/backups/sightops-db/diario/v3-extras-*.tar.gz 2>/dev/null | head -1)
if [ -z "$EXTRA_TAR" ]; then
  aviso "nenhum v3-extras-*.tar.gz -- certificados da CA e definicao dos containers ficam de fora do backup"
else
  echo "      $(basename "$EXTRA_TAR")"
  faltam=""
  for item in sightops-ca go2rtc containers-sem-compose.json docker-compose.extras.yml; do
    tar tzf "$EXTRA_TAR" 2>/dev/null | grep -q "$item" || faltam="$faltam $item"
  done
  if [ -n "$faltam" ]; then
    aviso "o backup dos extras nao tem:$faltam"
  else
    ok "leva CA, go2rtc, definicao dos containers e o compose deles"
  fi
  # O JSON guarda o token do tunnel em claro -- o tar TEM que ser 600.
  perm=$(stat -c '%a' "$EXTRA_TAR" 2>/dev/null)
  [ "$perm" = "600" ] && ok "permissao 600 (contem o token do tunnel)"     || aviso "permissao $perm -- este arquivo tem o token do tunnel, devia ser 600"
fi

# -------------------------------------------------------- veredito
echo
if [ "$problemas" -eq 0 ]; then
  echo "=== TUDO CERTO: pode dar push e reiniciar sem perder nada ==="
  exit 0
fi
echo "=== $problemas ponto(s) de atencao acima -- resolva antes de push/reboot ==="
exit 1
