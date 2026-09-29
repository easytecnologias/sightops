# Disco: preparar o segundo HD e mover os bancos para ele

O servidor de producao tem **4 nucleos, 7,6 GB de RAM e HD MECANICO**. Em
28/09/2026 ele travou com load 50 e o Docker parou de responder: o disco ficava
95% do tempo ocupado, e processo preso em I/O (estado `D`) nao morre nem com
`kill -9`. Havia um **segundo HD de 1 TB parado**, sem uso desde que a maquina
ligou.

Estes dois scripts colocam esse disco para trabalhar.

## `preparar-disco.sh` -- formata e monta em `/mnt/dados`

```bash
su -c 'bash deploy/storage/preparar-disco.sh > /tmp/disco.log 2>&1'
```

**Nunca identifique o disco por `sda`/`sdb`: os nomes TROCAM entre reboots.** No
mesmo dia a raiz saiu de `/dev/sdb2` para `/dev/sda2` num unico reinicio. O
script descobre o disco da raiz na hora e aborta se o alvo for ele. Aborta
tambem se houver qualquer particao, assinatura de filesystem, RAID ou LVM --
tabela de particao vazia nao conta como dado e pode ser sobrescrita.

Monta por **UUID** (nome nao serve) e com **`nofail`**: sem isso, um disco
secundario com defeito prende a maquina no modo de emergencia e voce fica sem
SightOps por causa de um disco que nem e o principal. No fim ele desmonta e roda
`mount -a` para provar que o fstab esta correto ANTES do proximo boot.

## `mover-volumes.sh` -- leva os bancos para o disco novo

```bash
su -c 'bash deploy/storage/mover-volumes.sh zabbix'     # 5,8 GB
su -c 'bash deploy/storage/mover-volumes.sh sightops'   # 1,0 GB
```

Um por vez, de proposito: assim uma falha nunca deixa os dois servicos fora.

Usa **bind mount, nao recriacao de volume**. O volume Docker continua com o
mesmo nome em `/var/lib/docker/volumes/<nome>/_data`, e esse caminho passa a ser
um espelho do diretorio em `/mnt/dados/docker-volumes/<nome>`. O
docker-compose **nao muda** e nenhum container precisa ser recriado -- o que
importa muito aqui, porque ha correcoes que vivem so na imagem em execucao e um
recreate as perderia.

O diretorio original vira `_data.old` e **nao e apagado**. Para desfazer:
`umount`, apagar `_data`, renomear `_data.old` de volta.

## Duas armadilhas que custaram tempo

**Ao conferir uma copia, conte so arquivos regulares.** Diretorio ocupa espaco
proprio, que varia conforme quantas entradas ja teve; somar isso acusou "copia
incompleta" com 1590 arquivos identicos e 4096 bytes de diferenca.

**O codigo de saida do `docker stop` nao e confiavel** quando o container demora
a sair. Confira `docker inspect -f '{{.State.Status}}'` depois.

## Resultado medido em 28/09/2026

| | Antes | Depois |
|---|---|---|
| Disco ocupado | 96% | 3% |
| Carga | 50 | 1,5 |
| `/v3/` por HTTPS | 10,6 s | 0,04 s |

## O Docker tem que esperar o disco (`systemd/10-espera-os-volumes.conf`)

Mover os volumes para `/mnt/dados` cria um risco que nao existia antes: o
diretorio `_data` por baixo do bind fica **vazio**. Se a montagem falhar no boot
-- e ela usa `nofail` de proposito, para um disco secundario com defeito nao
prender a maquina no modo de emergencia -- o Docker subia assim mesmo, o
Postgres encontrava `PGDATA` vazio e rodava `initdb`. Resultado: SightOps e
Zabbix no ar com banco novo em branco, parecendo perda total, e gravando no
diretorio errado.

O drop-in da ao `docker.service` um `RequiresMountsFor` das tres montagens
(`/mnt/dados` e os dois binds). Sem elas o Docker **nao sobe**. E a troca certa:
ficar fora do ar avisando e muito melhor que subir com o banco vazio.

```bash
sudo install -Dm644 deploy/storage/systemd/10-espera-os-volumes.conf \
  /etc/systemd/system/docker.service.d/10-espera-os-volumes.conf
sudo systemctl daemon-reload
```

Conferir (tem que listar as tres montagens):

```bash
systemctl show docker.service -p Requires | tr ' ' '\n' | grep -i mount
```

Para desfazer: apagar o arquivo e `systemctl daemon-reload`.
