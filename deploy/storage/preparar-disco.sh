#!/bin/bash
# Prepara o segundo disco (hoje vazio) e monta em /mnt/dados.
#
# Os nomes sdX TROCAM entre reboots -- em 28/09/2026 a raiz saiu de sdb2 para
# sda2 num unico reinicio. Por isso este script NAO confia no nome: ele descobre
# o disco da raiz na hora, exige que o alvo seja outro, e so segue se o alvo
# estiver comprovadamente vazio. E o fstab usa UUID, nunca /dev/sdX.
set -euo pipefail

# parted, wipefs, mkfs.ext4 e blkid vivem em /sbin. O `su -c` (sem hifen) herda
# o PATH do usuario que chamou, que nao tem /sbin -- o script morria em
# "command not found" antes de fazer qualquer coisa. Fixar aqui resolve tanto
# para `su -c` quanto para cron.
export PATH=/sbin:/usr/sbin:/usr/bin:/bin:$PATH

ALVO=/dev/sdb
PONTO=/mnt/dados

# Se algo falhar, dizer ONDE -- em vez de sair calado por causa do set -e.
trap 'echo ""; echo "!!! FALHOU na linha $LINENO. Nada foi formatado se a mensagem acima veio antes de PARTICIONANDO."' ERR

echo "=== TRAVAS DE SEGURANCA ==="

# 1. o disco da raiz, descoberto agora
RAIZ_PART=$(findmnt -n -o SOURCE /)
RAIZ_DISCO=$(lsblk -no PKNAME "$RAIZ_PART")
echo "  raiz esta em $RAIZ_PART (disco /dev/$RAIZ_DISCO)"

if [ "/dev/$RAIZ_DISCO" = "$ALVO" ]; then
  echo "  ABORTADO: $ALVO e o disco do SISTEMA"; exit 1
fi
echo "  ok: $ALVO nao e o disco do sistema"

# 2. nenhuma particao
N_PART=$(lsblk -no NAME "$ALVO" | tail -n +2 | wc -l)
if [ "$N_PART" != "0" ]; then
  echo "  ABORTADO: $ALVO tem $N_PART particao(oes)"; exit 1
fi
echo "  ok: $ALVO nao tem particao"

# 3. nenhuma assinatura de DADOS (filesystem / RAID / LVM).
# Uma tabela de particao vazia (gpt/dos/PMBR) nao e dado: e a casca que sobra
# de um uso anterior depois que as particoes foram removidas. Com a trava 2 ja
# garantindo zero particoes, o disco esta comprovadamente vazio. O que NAO pode
# passar e assinatura de ext4/xfs/LVM/RAID -- essas indicam dado de verdade.
SUJEIRA=$(wipefs -n "$ALVO" 2>/dev/null | tail -n +2 | awk '{print $3}' \
          | grep -viE '^(gpt|dos|PMBR)$' || true)
if [ -n "$SUJEIRA" ]; then
  echo "  ABORTADO: $ALVO tem assinatura de DADOS:"; wipefs -n "$ALVO"; exit 1
fi
if wipefs -n "$ALVO" 2>/dev/null | grep -qiE 'gpt|PMBR'; then
  echo "  ok: so tabela de particao VAZIA (sera sobrescrita), sem dado"
else
  echo "  ok: $ALVO sem nenhuma assinatura"
fi

# 4. nada montado a partir dele
if lsblk -no MOUNTPOINT "$ALVO" | grep -q .; then
  echo "  ABORTADO: $ALVO tem algo montado"; exit 1
fi
echo "  ok: $ALVO nao tem nada montado"

echo
echo "=== PARTICIONANDO E FORMATANDO $ALVO ==="
# Limpa a tabela antiga inteira, inclusive a copia do GPT no FIM do disco --
# senao ela ressuscita depois e o disco fica com duas tabelas divergentes.
wipefs -a "$ALVO" >/dev/null 2>&1 || true
parted -s "$ALVO" mklabel gpt
parted -s "$ALVO" mkpart primary ext4 1MiB 100%
sleep 2
partprobe "$ALVO" 2>/dev/null || true
sleep 2

PART="${ALVO}1"
[ -b "$PART" ] || { echo "  ERRO: $PART nao apareceu"; exit 1; }

# -m 1: reserva 1% para root em vez dos 5% padrao. Em 1TB isso devolve ~40GB
# que nao servem para nada num disco que so guarda dados.
mkfs.ext4 -q -m 1 -L sightops-dados "$PART"
echo "  formatado: $PART"

UUID=$(blkid -s UUID -o value "$PART")
echo "  UUID: $UUID"

echo
echo "=== MONTANDO EM $PONTO ==="
mkdir -p "$PONTO"

# nofail: se um dia este disco falhar ou sair, o servidor ainda BOOTA.
# Sem isso, um disco com problema deixa a maquina presa no modo de emergencia.
cp -a /etc/fstab "/etc/fstab.bak-$(date +%Y%m%d-%H%M%S)"
sed -i "\|$PONTO|d" /etc/fstab
echo "UUID=$UUID  $PONTO  ext4  defaults,noatime,nofail  0  2" >> /etc/fstab

mount "$PONTO"
echo "  montado"

echo
echo "=== VALIDANDO O FSTAB (se estiver errado, o servidor nao boota) ==="
umount "$PONTO"
mount -a
findmnt "$PONTO" >/dev/null && echo "  fstab OK: monta sozinho" || { echo "  ERRO no fstab"; exit 1; }

echo
echo "=== RESULTADO ==="
df -h "$PONTO" | tail -1
echo "  dono: definindo para central"
chown central:central "$PONTO"
echo "  linha no fstab:"
grep "$PONTO" /etc/fstab | sed 's/^/    /'
