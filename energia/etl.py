"""Ingestao dos arquivos mensais de fator de capacidade do ONS.

Uso:
    python -m energia.etl --ano 2025
    python -m energia.etl --ano 2025 --meses 1 2 3 --formato csv

A carga e idempotente: cada mes apaga as medicoes do proprio intervalo antes de
inserir, entao rodar duas vezes o mesmo mes nao duplica nada.
"""

import argparse
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from .banco import Sessao, criar_tabelas
from .configuracao import ANO_PADRAO, DIRETORIO_DADOS, URL_BASE_ONS
from .modelos import MedicaoHoraria, Subsistema, Usina

COLUNAS = {
    "id_subsistema": "subsistema_id",
    "nom_subsistema": "subsistema_nome",
    "id_estado": "uf",
    "nom_localizacao": "localizacao",
    "val_latitudepontoconexao": "latitude",
    "val_longitudepontoconexao": "longitude",
    "val_latitudesecoletora": "latitude_coletora",
    "val_longitudesecoletora": "longitude_coletora",
    "cod_pontoconexao": "cod_ponto_conexao",
    "nom_modalidadeoperacao": "modalidade",
    "nom_tipousina": "fonte",
    "nom_usina_conjunto": "nome",
    "id_ons": "usina_id",
    "din_instante": "instante",
    "val_geracaoprogramada": "geracao_programada_mw",
    "val_geracaoverificada": "geracao_verificada_mw",
    "val_capacidadeinstalada": "capacidade_instalada_mw",
    "val_fatorcapacidade": "fator_capacidade",
}

NUMERICAS = [
    "geracao_programada_mw",
    "geracao_verificada_mw",
    "capacidade_instalada_mw",
    "fator_capacidade",
    "latitude",
    "longitude",
    "latitude_coletora",
    "longitude_coletora",
]

# Sobregeracao leve e real em parques eolicos (a capacidade nominal nao e um teto
# fisico rigido), mas acima disso e inconsistencia da fonte e nao entra na base.
FATOR_MAXIMO = 1.5

LOTE_INSERCAO = 20_000


def _sem_acento(valor) -> str:
    return (
        unicodedata.normalize("NFKD", str(valor))
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        .upper()
    )


def nome_arquivo(ano: int, mes: int, formato: str) -> str:
    return f"FATOR_CAPACIDADE-2_{ano}_{mes:02d}.{formato}"


def baixar_mes(ano: int, mes: int, formato: str, refazer: bool = False) -> Path:
    DIRETORIO_DADOS.mkdir(parents=True, exist_ok=True)
    destino = DIRETORIO_DADOS / nome_arquivo(ano, mes, formato)
    if destino.exists() and not refazer:
        return destino

    url = f"{URL_BASE_ONS}/{destino.name}"
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    with requests.get(url, stream=True, timeout=120) as resposta:
        resposta.raise_for_status()
        with parcial.open("wb") as arquivo:
            for pedaco in resposta.iter_content(chunk_size=1 << 20):
                arquivo.write(pedaco)
    parcial.replace(destino)
    return destino


def ler_arquivo(caminho: Path) -> pd.DataFrame:
    if caminho.suffix == ".parquet":
        bruto = pd.read_parquet(caminho)
    else:
        bruto = pd.read_csv(caminho, sep=";", encoding="utf-8", low_memory=False)
    return bruto.rename(columns=COLUNAS)


def limpar(bruto: pd.DataFrame) -> pd.DataFrame:
    """Aplica as regras de consistencia e reporta o que foi descartado."""
    df = bruto.copy()
    total = len(df)

    for coluna in NUMERICAS:
        if coluna in df:
            df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df["instante"] = pd.to_datetime(df["instante"], errors="coerce")
    df["fonte"] = df["fonte"].map(_sem_acento)

    obrigatorias = [
        "usina_id",
        "instante",
        "geracao_verificada_mw",
        "capacidade_instalada_mw",
        "fator_capacidade",
    ]
    descartes = {}
    df, descartes["campo obrigatorio vazio"] = _descartar(df, df[obrigatorias].isna().any(axis=1))
    df, descartes["fonte desconhecida"] = _descartar(df, ~df["fonte"].isin(["EOLICA", "SOLAR"]))
    df, descartes["capacidade nao positiva"] = _descartar(df, df["capacidade_instalada_mw"] <= 0)
    df, descartes["fator fora de faixa"] = _descartar(
        df, (df["fator_capacidade"] < 0) | (df["fator_capacidade"] > FATOR_MAXIMO)
    )
    df, descartes["duplicata usina/instante"] = _descartar(
        df, df.duplicated(["usina_id", "instante"], keep="last")
    )

    # Latitude/longitude do ponto de conexao faltam em ~1% das linhas; a subestacao
    # coletora e a melhor aproximacao disponivel.
    df["latitude"] = df["latitude"].fillna(df["latitude_coletora"])
    df["longitude"] = df["longitude"].fillna(df["longitude_coletora"])

    # O ONS grava texto ausente como string vazia, nao como nulo: sem normalizar,
    # a coluna acabaria com "" no banco e nenhum IS NULL acharia essas usinas.
    for coluna in ("localizacao", "cod_ponto_conexao"):
        texto = df[coluna].fillna("").astype(str).str.strip()
        df[coluna] = texto.where(texto != "", None)

    perdidas = total - len(df)
    detalhe = ", ".join(f"{motivo}: {qtd}" for motivo, qtd in descartes.items() if qtd)
    print(f"    {total} linhas lidas, {perdidas} descartadas" + (f" ({detalhe})" if detalhe else ""))
    return df


def _descartar(df: pd.DataFrame, mascara: pd.Series) -> tuple[pd.DataFrame, int]:
    quantidade = int(mascara.sum())
    return (df[~mascara] if quantidade else df), quantidade


def sincronizar_dimensoes(sessao: Session, df: pd.DataFrame) -> None:
    subsistemas = df[["subsistema_id", "subsistema_nome"]].drop_duplicates("subsistema_id")
    for linha in subsistemas.itertuples(index=False):
        sessao.merge(Subsistema(id=linha.subsistema_id, nome=linha.subsistema_nome))

    colunas = [
        "usina_id",
        "nome",
        "fonte",
        "modalidade",
        "uf",
        "localizacao",
        "latitude",
        "longitude",
        "cod_ponto_conexao",
        "subsistema_id",
    ]
    # keep="last": se a usina mudou de atributo no meio do mes, vale o registro mais recente.
    usinas = df[colunas].drop_duplicates("usina_id", keep="last")
    for linha in usinas.itertuples(index=False):
        sessao.merge(
            Usina(
                id_ons=linha.usina_id,
                nome=linha.nome,
                fonte=linha.fonte,
                modalidade=linha.modalidade,
                uf=linha.uf,
                localizacao=linha.localizacao,
                latitude=None if pd.isna(linha.latitude) else float(linha.latitude),
                longitude=None if pd.isna(linha.longitude) else float(linha.longitude),
                cod_ponto_conexao=linha.cod_ponto_conexao,
                subsistema_id=linha.subsistema_id,
            )
        )
    sessao.commit()


def carregar_medicoes(sessao: Session, df: pd.DataFrame) -> int:
    inicio = df["instante"].min().to_pydatetime()
    fim = df["instante"].max().to_pydatetime()
    sessao.execute(
        delete(MedicaoHoraria).where(
            MedicaoHoraria.instante >= inicio, MedicaoHoraria.instante <= fim
        )
    )

    medicoes = df[
        [
            "usina_id",
            "instante",
            "geracao_programada_mw",
            "geracao_verificada_mw",
            "capacidade_instalada_mw",
            "fator_capacidade",
        ]
    ].copy()
    # pd.Timestamp e subclasse de datetime e vai direto para o driver; NaN nao,
    # precisa virar None para gravar NULL na geracao programada.
    programada = medicoes["geracao_programada_mw"]
    medicoes["geracao_programada_mw"] = programada.astype(object).where(programada.notna(), None)

    registros = medicoes.to_dict("records")
    for comeco in range(0, len(registros), LOTE_INSERCAO):
        sessao.execute(insert(MedicaoHoraria), registros[comeco : comeco + LOTE_INSERCAO])
    sessao.commit()
    return len(registros)


def executar(ano: int, meses: list[int], formato: str, refazer: bool = False) -> int:
    criar_tabelas()
    carregadas = 0
    with Sessao() as sessao:
        for mes in meses:
            print(f"[{ano}-{mes:02d}] baixando...")
            try:
                caminho = baixar_mes(ano, mes, formato, refazer)
            except requests.HTTPError as erro:
                print(f"    indisponivel no ONS ({erro.response.status_code}), pulando")
                continue

            df = limpar(ler_arquivo(caminho))
            if df.empty:
                print("    nada a carregar")
                continue

            sincronizar_dimensoes(sessao, df)
            inseridas = carregar_medicoes(sessao, df)
            carregadas += inseridas
            print(f"    {inseridas} medicoes gravadas")
    return carregadas


def principal(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carrega o fator de capacidade do ONS.")
    parser.add_argument("--ano", type=int, default=ANO_PADRAO)
    parser.add_argument(
        "--meses", type=int, nargs="+", default=list(range(1, 13)), choices=range(1, 13)
    )
    parser.add_argument("--formato", choices=["parquet", "csv"], default="parquet")
    parser.add_argument(
        "--refazer-download", action="store_true", help="ignora os arquivos ja baixados em dados/"
    )
    args = parser.parse_args(argumentos)

    comeco = datetime.now()
    total = executar(args.ano, args.meses, args.formato, args.refazer_download)
    print(f"\n{total} medicoes carregadas em {(datetime.now() - comeco).total_seconds():.0f}s")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(principal())
