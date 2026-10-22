"""Importacao de pessoas por planilha (XLSX ou CSV).

O cliente ja tem a lista pronta -- digitar 500 pessoas na tela nao e opcao. A
planilha e lida, conferida e so entao gravada, com pre-visualizacao
obrigatoria: o usuario ve quantos serao criados, quantos atualizados e quais
linhas foram recusadas, antes de qualquer escrita.

Serve escola, condominio, empresa e evento: a coluna "tipo" diz o que cada
pessoa e (aluno, morador, colaborador, participante...); sem ela vale o tipo
principal do local (aluno na escola, morador no condominio...). Matricula so e
obrigatoria para aluno.

Identidade: CPF (sempre) e matricula (quando houver). Linha que bate com uma
pessoa ja cadastrada ATUALIZA em vez de criar outra; se a matricula aponta
para uma pessoa e o CPF para outra, a linha e recusada em vez de adivinhar.

Atualizar NAO apaga nada: save_person grava o cadastro inteiro, entao a
importacao parte do cadastro atual e so troca o que a planilha traz preenchido.
Antes, reimportar sem a coluna de telefone apagava o telefone, sem a coluna do
ID da controladora gerava outro ID (a pessoa mudava de numero no leitor), sem
local apagava o local, e todo mundo virava aluno ativo.

O que a planilha NAO traz e a foto: o rosto vem de upload na tela.
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# Cada campo aceita varios nomes de coluna porque cada cliente escreve do seu
# jeito. A comparacao ignora acento, caixa e espaco extra.
COLUNAS: Dict[str, Tuple[str, ...]] = {
    "enrollment_code": ("matricula", "matriculas", "codigo", "cod", "ra", "registro", "numero"),
    "full_name": ("nome", "nome completo", "aluno", "nome do aluno", "estudante", "morador",
                  "colaborador", "funcionario", "participante", "pessoa"),
    "guardian_phone": ("telefone", "celular", "whatsapp", "contato", "fone",
                       "telefone do responsavel", "celular do responsavel"),
    "guardian_name": ("responsavel", "nome do responsavel", "mae", "pai", "filiacao"),
    "guardian_email": ("email", "e-mail", "e mail", "email do responsavel", "e-mail do responsavel"),
    "class_name": ("turma", "classe", "serie", "ano", "sala", "unidade", "apartamento", "apto",
                   "bloco", "casa", "lote", "setor", "departamento", "credencial", "categoria do ingresso"),
    "document_id": ("cpf", "documento", "doc"),
    "controller_user_id": ("id controladora", "id da controladora", "id catraca",
                           "usuario controladora", "id do equipamento", "id no leitor"),
    "person_type": ("tipo", "tipo de pessoa", "perfil", "vinculo", "categoria"),
    "groups": ("grupo", "grupos", "grupo de acesso", "acesso"),
    "notes": ("observacao", "observacoes", "obs", "notas"),
}
# Ordem de checagem: "nome do responsavel" nao pode cair em "nome".
_ORDEM = ("guardian_email", "guardian_name", "guardian_phone", "controller_user_id", "enrollment_code", "document_id",
          "person_type", "groups", "notes", "class_name", "full_name")

TIPOS: Dict[str, str] = {
    "aluno": "student", "aluna": "student", "estudante": "student", "student": "student",
    "morador": "resident", "moradora": "resident", "resident": "resident", "condomino": "resident",
    "funcionario": "employee", "funcionaria": "employee", "colaborador": "employee", "colaboradora": "employee",
    "professor": "employee", "professora": "employee", "employee": "employee",
    "prestador": "contractor", "prestadora": "contractor", "terceiro": "contractor", "terceirizado": "contractor",
    "contractor": "contractor",
    "visitante": "visitor", "convidado": "visitor", "convidada": "visitor", "visitor": "visitor",
    "participante": "participant", "participant": "participant", "inscrito": "participant",
    "equipe": "staff", "staff": "staff", "organizacao": "staff",
}
TIPO_PADRAO = {"escola": "student", "condominio": "resident", "empresa": "employee", "evento": "participant"}

OBRIGATORIAS = {"full_name": "nome", "document_id": "cpf"}


def _norm(valor: Any) -> str:
    txt = str(valor or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt)


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    # openpyxl devolve numero para celula numerica: matricula 1577 viria 1577.0
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _telefone(valor: Any) -> str:
    """Normaliza para o formato que a Cloud API espera (digitos com DDI).

    Telefone torto passa despercebido e vira notificacao que nunca chega -- e o
    pai quem descobre. Por isso o que nao tem cara de numero brasileiro valido e
    recusado na leitura, em vez de gravado torto.
    """
    digitos = re.sub(r"\D", "", _texto(valor))
    if not digitos:
        return ""
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return "55" + digitos
    return ""


def _cpf(valor: Any) -> str:
    """So digitos -- vazio ou com tamanho diferente de 11 vira linha recusada."""
    return re.sub(r"\D", "", _texto(valor))


def _mapear_colunas(cabecalho: List[Any]) -> Dict[str, int]:
    """Descobre em que coluna esta cada campo, pelos nomes aceitos. Nome exato
    ganha de prefixo ("nome do responsavel" nao vira "nome")."""
    achadas: Dict[str, int] = {}
    nomes = [(_norm(b), i) for i, b in enumerate(cabecalho)]
    for exato in (True, False):
        for nome, i in nomes:
            if not nome or i in achadas.values():
                continue
            for campo in _ORDEM:
                if campo in achadas:
                    continue
                apelidos = COLUNAS[campo]
                if nome in apelidos if exato else any(nome.startswith(a) for a in apelidos):
                    achadas[campo] = i
                    break
    return achadas


def ler_planilha(conteudo: bytes, nome_arquivo: str = "") -> List[List[Any]]:
    """Devolve as linhas cruas, aceitando XLSX ou CSV."""
    parece_xlsx = conteudo[:2] == b"PK"
    if not parece_xlsx:
        texto = None
        for codec in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                texto = conteudo.decode(codec)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise ValueError("Nao foi possivel ler o arquivo: codificacao desconhecida.")
        import csv as _csv

        # Excel brasileiro exporta CSV com ponto e virgula
        separador = ";" if texto.count(";") > texto.count(",") else ","
        return [linha for linha in _csv.reader(io.StringIO(texto), delimiter=separador)]

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    aba = wb[wb.sheetnames[0]]
    return [list(linha) for linha in aba.iter_rows(values_only=True)]


def _tipo_do_local(site: str) -> str:
    try:
        from app.services.access_control_painel import _perfil
        return _perfil(site)["tipo"] if site else ""
    except Exception:
        return ""


def _grupos_do_cliente() -> Dict[str, Dict[str, Any]]:
    from app.services.access_control_store import list_groups
    return {_norm(g.get("name")): g for g in list_groups()}


def analisar_planilha(conteudo: bytes, *, site: str = "", nome_arquivo: str = "",
                      grupo_id: str = "", tipo_padrao: str = "") -> Dict[str, Any]:
    """Le a planilha e diz o que aconteceria, sem gravar nada."""
    from app.services.access_control_store import list_people

    linhas = [l for l in ler_planilha(conteudo, nome_arquivo) if any(_texto(c) for c in l)]
    if not linhas:
        raise ValueError("A planilha esta vazia.")

    colunas = _mapear_colunas(linhas[0])
    tipo_local = _tipo_do_local(site)
    # Condominio: CPF opcional (decisao do usuario em 15/10/2026).
    cpf_opcional = tipo_local == "condominio"
    exigidas = {c: r for c, r in OBRIGATORIAS.items() if not (cpf_opcional and c == "document_id")}
    faltando = [rotulo for campo, rotulo in exigidas.items() if campo not in colunas]
    if faltando:
        vistas = ", ".join(str(c) for c in linhas[0] if _texto(c)) or "nenhuma"
        raise ValueError(
            "A planilha precisa das colunas: %s. Colunas encontradas: %s."
            % (", ".join(faltando), vistas)
        )

    padrao = TIPOS.get(_norm(tipo_padrao), tipo_padrao if tipo_padrao in TIPOS.values() else "") \
        or TIPO_PADRAO.get(tipo_local, "student")
    grupos = _grupos_do_cliente()
    grupos_por_id = {str(g.get("id")): g for g in grupos.values()}
    if grupo_id and grupo_id not in grupos_por_id:
        raise ValueError("Grupo nao encontrado neste cliente.")

    # Duas chaves de identidade, nao so a matricula -- foi so por causa disso
    # que a mesma aluna virou dois cadastros em producao (matricula trocou de
    # um ano pro outro, CPF continuou igual).
    existentes_por_matricula: Dict[str, Any] = {}
    existentes_por_cpf: Dict[str, Any] = {}
    # Sem CPF (condominio), quem ja existe e achado pelo ID no leitor ou pelo
    # nome no mesmo local -- senao reimportar a lista duplicaria todo mundo.
    existentes_por_id_leitor: Dict[str, Any] = {}
    existentes_por_nome: Dict[str, List[Any]] = {}
    for pessoa in (list_people() or []):
        if _texto(pessoa.get("controller_user_id")):
            existentes_por_id_leitor[_texto(pessoa.get("controller_user_id"))] = pessoa
        if _norm(pessoa.get("site")) == _norm(site):
            existentes_por_nome.setdefault(_norm(pessoa.get("full_name")), []).append(pessoa)
        matricula = _texto(pessoa.get("enrollment_code"))
        if matricula:
            existentes_por_matricula[matricula] = pessoa
        cpf = _cpf(pessoa.get("document_id"))
        if cpf:
            existentes_por_cpf[cpf] = pessoa

    criar: List[Dict[str, Any]] = []
    atualizar: List[Dict[str, Any]] = []
    recusados: List[Dict[str, Any]] = []
    avisos: List[Dict[str, Any]] = []
    matriculas_no_arquivo: Dict[str, int] = {}
    cpfs_no_arquivo: Dict[str, int] = {}
    nomes_sem_cpf: Dict[str, int] = {}

    for numero, linha in enumerate(linhas[1:], start=2):

        def campo(nome: str) -> str:
            i = colunas.get(nome)
            return _texto(linha[i]) if i is not None and i < len(linha) else ""

        matricula = campo("enrollment_code")
        nome = re.sub(r"\s+", " ", campo("full_name"))
        recusa = lambda motivo: recusados.append({"linha": numero, "matricula": matricula, "nome": nome, "motivo": motivo})
        if not nome:
            recusa("nome em branco")
            continue

        if matricula and matricula in matriculas_no_arquivo:
            recusa("matricula repetida na planilha (linha %d)" % matriculas_no_arquivo[matricula])
            continue

        cpf = _cpf(campo("document_id"))
        if cpf and len(cpf) != 11:
            recusa("CPF precisa ter 11 digitos")
            continue
        if not cpf and not cpf_opcional:
            recusa("CPF obrigatorio e precisa ter 11 digitos")
            continue
        if cpf and cpf in cpfs_no_arquivo:
            recusa("CPF repetido na planilha (linha %d)" % cpfs_no_arquivo[cpf])
            continue

        pessoa_por_matricula = existentes_por_matricula.get(matricula) if matricula else None
        pessoa_por_cpf = existentes_por_cpf.get(cpf) if cpf else None
        if pessoa_por_matricula and pessoa_por_cpf and pessoa_por_matricula["id"] != pessoa_por_cpf["id"]:
            recusa("matricula %s e CPF %s pertencem a pessoas diferentes ja cadastradas" % (matricula, cpf))
            continue
        existente = pessoa_por_matricula or pessoa_por_cpf
        if not existente and not cpf:
            id_leitor = re.sub(r"\D", "", campo("controller_user_id"))
            mesmo_nome = existentes_por_nome.get(_norm(nome), [])
            if id_leitor and id_leitor in existentes_por_id_leitor:
                existente = existentes_por_id_leitor[id_leitor]
            elif len(mesmo_nome) == 1:
                existente = mesmo_nome[0]
            elif len(mesmo_nome) > 1:
                recusa("sem CPF e com %d pessoas de mesmo nome neste local: informe o CPF ou o ID no leitor" % len(mesmo_nome))
                continue
            if not existente and _norm(nome) in nomes_sem_cpf:
                recusa("sem CPF e com o mesmo nome da linha %d: informe o CPF para separar" % nomes_sem_cpf[_norm(nome)])
                continue

        # Tipo: o da coluna; sem ela, quem ja existe continua o que e, e quem e
        # novo pega o tipo principal do local.
        tipo_bruto = campo("person_type")
        if tipo_bruto:
            tipo = TIPOS.get(_norm(tipo_bruto), "")
            if not tipo:
                recusa("tipo desconhecido: %s (use aluno, morador, funcionario, prestador, visitante, participante ou equipe)" % tipo_bruto)
                continue
        else:
            tipo = _texto((existente or {}).get("person_type")) or padrao
        if tipo == "student" and not (matricula or _texto((existente or {}).get("enrollment_code"))):
            recusa("aluno precisa de matricula")
            continue
        if not existente and not site:
            recusa("pessoa nova precisa de local: escolha o local antes de importar")
            continue

        telefone_bruto = campo("guardian_phone")
        telefone = _telefone(telefone_bruto)
        if telefone_bruto and not telefone:
            recusa("telefone invalido: %s" % telefone_bruto)
            continue

        email_bruto = campo("guardian_email")
        try:
            from app.services.access_control_store import clean_email
            email = clean_email(email_bruto)
        except ValueError:
            recusa("e-mail invalido: %s" % email_bruto)
            continue

        nomes_grupo = [g.strip() for g in re.split(r"[;,|]", campo("groups")) if g.strip()]
        ids_grupo: List[str] = []
        for g in nomes_grupo:
            achado = grupos.get(_norm(g))
            if achado:
                ids_grupo.append(str(achado.get("id")))
            else:
                avisos.append({"linha": numero, "nome": nome, "aviso": "grupo nao existe: %s" % g})
        if grupo_id:
            ids_grupo.append(grupo_id)

        if matricula:
            matriculas_no_arquivo[matricula] = numero
        if cpf:
            cpfs_no_arquivo[cpf] = numero
        else:
            nomes_sem_cpf[_norm(nome)] = numero

        registro = {
            "linha": numero,
            "enrollment_code": matricula,
            "full_name": nome,
            "person_type": tipo,
            "guardian_phone": telefone,
            "guardian_name": campo("guardian_name"),
            "guardian_email": email,
            "class_name": campo("class_name"),
            "document_id": cpf,
            "controller_user_id": re.sub(r"\D", "", campo("controller_user_id")),
            "notes": campo("notes"),
            "site": site,
            "grupos": sorted(set(ids_grupo)),
            "grupos_nomes": [str(grupos_por_id[i].get("name")) for i in sorted(set(ids_grupo)) if i in grupos_por_id],
            "sem_telefone": not telefone and not (existente or {}).get("guardian_phone"),
        }
        if existente:
            registro["id_existente"] = existente["id"]
            registro["nome_atual"] = existente.get("full_name") or ""
            atualizar.append(registro)
        else:
            criar.append(registro)

    return {
        "ok": True,
        "colunas_reconhecidas": sorted(k for k in colunas.keys()),
        "tipo_local": tipo_local,
        "tipo_padrao": padrao,
        "total_linhas": len(linhas) - 1,
        "criar": criar,
        "atualizar": atualizar,
        "recusados": recusados,
        "avisos": avisos,
        "sem_telefone": sum(1 for r in criar + atualizar if r["sem_telefone"] and r["person_type"] == "student"),
    }


# Campos que a planilha pode trazer; vazio na planilha = mantem o atual.
_CAMPOS_PLANILHA = ("full_name", "person_type", "enrollment_code", "guardian_phone", "guardian_name",
                    "class_name", "document_id", "controller_user_id", "notes", "site", "guardian_email")
_CAMPOS_CADASTRO = ("full_name", "person_type", "document_id", "enrollment_code", "class_name", "site",
                    "controller_user_id", "guardian_name", "guardian_phone", "whatsapp_enabled", "active", "notes")


def _payload(registro: Dict[str, Any], atual: Optional[Dict[str, Any]], colunas: List[str]) -> Dict[str, Any]:
    """Novo: o que veio. Existente: o cadastro atual com so o que a planilha
    traz preenchido por cima (coluna ausente ou celula vazia nao apaga nada)."""
    if not atual:
        payload = {k: registro.get(k, "") for k in _CAMPOS_PLANILHA}
        payload.update({"whatsapp_enabled": True, "active": True})
        return payload
    payload = {k: atual.get(k) for k in _CAMPOS_CADASTRO}
    payload["id"] = atual["id"]
    for k in _CAMPOS_PLANILHA:
        valor = registro.get(k)
        trazido = k == "site" or k == "person_type" and "person_type" in colunas or k in _COLUNA_DE and _COLUNA_DE[k] in colunas
        if trazido and valor not in (None, ""):
            payload[k] = valor
    return payload


_COLUNA_DE = {"full_name": "full_name", "enrollment_code": "enrollment_code", "guardian_phone": "guardian_phone",
              "guardian_name": "guardian_name", "class_name": "class_name", "document_id": "document_id",
              "controller_user_id": "controller_user_id", "notes": "notes", "guardian_email": "guardian_email"}


def aplicar_planilha(conteudo: bytes, *, site: str = "", nome_arquivo: str = "",
                     grupo_id: str = "", tipo_padrao: str = "") -> Dict[str, Any]:
    """Grava o que a analise aprovou. Linha recusada nao entra. Grupos sao
    so ACRESCENTADOS (a pessoa nao sai de grupo nenhum por causa da planilha)."""
    from app.services import db_store
    from app.services.access_control_store import list_people, save_person

    analise = analisar_planilha(conteudo, site=site, nome_arquivo=nome_arquivo, grupo_id=grupo_id, tipo_padrao=tipo_padrao)
    colunas = analise["colunas_reconhecidas"]
    atuais = {p["id"]: p for p in list_people()}
    tenant = db_store._current_tenant_slug()
    criados = atualizados = em_grupos = 0
    falhas: List[Dict[str, Any]] = []
    ids: List[str] = []

    for registro in analise["criar"] + analise["atualizar"]:
        atual = atuais.get(registro.get("id_existente") or "")
        payload = _payload(registro, atual, colunas)
        try:
            pessoa = save_person(payload)
        except Exception as exc:
            falhas.append({"linha": registro["linha"], "matricula": registro["enrollment_code"],
                           "nome": registro["full_name"], "motivo": str(exc)})
            continue
        ids.append(pessoa["id"])
        if atual:
            atualizados += 1
        else:
            criados += 1
        if registro["grupos"]:
            with db_store._conn() as c:
                for gid in registro["grupos"]:
                    c.execute("INSERT INTO access_group_members(tenant_slug, group_id, person_id) VALUES(?, ?, ?) "
                              "ON CONFLICT(tenant_slug, group_id, person_id) DO NOTHING", (tenant, gid, pessoa["id"]))
            em_grupos += 1

    return {
        "ok": True,
        "criados": criados,
        "atualizados": atualizados,
        "em_grupos": em_grupos,
        "pessoas": ids,
        "recusados": analise["recusados"],
        "avisos": analise["avisos"],
        "falhas": falhas,
        "sem_telefone": analise["sem_telefone"],
    }
