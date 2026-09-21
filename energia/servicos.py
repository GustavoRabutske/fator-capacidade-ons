"""Regra de negocio: valida os parametros, monta as janelas de tempo e traduz as
linhas agregadas do repositorio nos esquemas expostos pela API."""

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from . import repositorio
from .configuracao import MAX_DIAS_SERIE_HORARIA
from .esquemas import (
    ComparativoSubsistema,
    Fonte,
    Granularidade,
    PontoSerie,
    ResumoFonte,
    SerieHistorica,
    UltimaMedicao,
)


class ParametroInvalido(Exception):
    pass


class DadosIndisponiveis(Exception):
    pass


def _validar_intervalo(inicio: date, fim: date, granularidade: Granularidade) -> None:
    if inicio > fim:
        raise ParametroInvalido("inicio nao pode ser posterior a fim")
    dias = (fim - inicio).days + 1
    if granularidade is Granularidade.HORA and dias > MAX_DIAS_SERIE_HORARIA:
        raise ParametroInvalido(
            f"a serie horaria aceita no maximo {MAX_DIAS_SERIE_HORARIA} dias por "
            f"requisicao ({dias} solicitados); use granularidade=dia"
        )


def _validar_subsistema(sessao: Session, subsistema: str | None) -> None:
    if subsistema is None:
        return
    validos = {s.id for s in repositorio.listar_subsistemas(sessao)}
    if subsistema not in validos:
        raise ParametroInvalido(
            f"subsistema '{subsistema}' desconhecido; validos: {sorted(validos)}"
        )


def _janela(inicio: date, fim: date) -> tuple[datetime, datetime]:
    """Fim e inclusivo para quem chama, exclusivo na consulta."""
    return datetime.combine(inicio, time.min), datetime.combine(fim + timedelta(days=1), time.min)


def obter_ultima_medicao(sessao: Session, fonte: Fonte | None = None) -> list[UltimaMedicao]:
    instante = repositorio.ultimo_instante(sessao)
    if instante is None:
        raise DadosIndisponiveis("nenhuma medicao carregada; rode o ETL primeiro")

    linhas = repositorio.agregar_por_subsistema_fonte(
        sessao,
        inicio=instante,
        fim=instante + timedelta(hours=1),
        fonte=fonte.value if fonte else None,
    )
    return [
        UltimaMedicao(
            subsistema=linha.subsistema_id,
            nome_subsistema=linha.nome,
            fonte=linha.fonte,
            instante=instante,
            fator_capacidade=round(linha.fator, 4),
            geracao_verificada_mw=round(linha.geracao, 3),
            capacidade_instalada_mw=round(linha.capacidade, 3),
            usinas=linha.usinas,
        )
        for linha in linhas
    ]


def obter_historico(
    sessao: Session,
    inicio: date,
    fim: date,
    granularidade: Granularidade = Granularidade.DIA,
    subsistema: str | None = None,
    fonte: Fonte | None = None,
) -> SerieHistorica:
    _validar_intervalo(inicio, fim, granularidade)
    _validar_subsistema(sessao, subsistema)

    inicio_dt, fim_dt = _janela(inicio, fim)
    por_dia = granularidade is Granularidade.DIA
    linhas = repositorio.serie_agregada(
        sessao,
        inicio=inicio_dt,
        fim=fim_dt,
        por_dia=por_dia,
        subsistema=subsistema,
        fonte=fonte.value if fonte else None,
    )

    pontos = [
        PontoSerie(
            instante=(
                datetime.combine(repositorio.como_data(linha.periodo), time.min)
                if por_dia
                else linha.periodo
            ),
            subsistema=linha.subsistema_id,
            fonte=linha.fonte,
            fator_capacidade=round(linha.fator, 4),
            geracao_media_mw=round(linha.geracao, 3),
            capacidade_instalada_mw=round(linha.capacidade, 3),
            usinas=linha.usinas,
        )
        for linha in linhas
    ]
    return SerieHistorica(
        granularidade=granularidade,
        inicio=inicio_dt,
        fim=fim_dt,
        total_pontos=len(pontos),
        pontos=pontos,
    )


def comparar_fontes(
    sessao: Session,
    inicio: date,
    fim: date,
    subsistema: str | None = None,
) -> list[ComparativoSubsistema]:
    if inicio > fim:
        raise ParametroInvalido("inicio nao pode ser posterior a fim")
    _validar_subsistema(sessao, subsistema)

    inicio_dt, fim_dt = _janela(inicio, fim)
    agregados = repositorio.agregar_por_subsistema_fonte(
        sessao, inicio_dt, fim_dt, subsistema=subsistema
    )
    if not agregados:
        raise DadosIndisponiveis("nenhuma medicao no periodo informado")

    picos = _picos_por_subsistema_fonte(sessao, inicio_dt, fim_dt, subsistema)

    nomes = {linha.subsistema_id: linha.nome for linha in agregados}
    resumos: dict[tuple[str, str], ResumoFonte] = {}
    for linha in agregados:
        hora, fator_pico = picos.get((linha.subsistema_id, linha.fonte), (0, 0.0))
        resumos[(linha.subsistema_id, linha.fonte)] = ResumoFonte(
            fator_capacidade=round(linha.fator, 4),
            geracao_media_mw=round(linha.geracao, 3),
            capacidade_instalada_mw=round(linha.capacidade, 3),
            usinas=linha.usinas,
            hora_pico=hora,
            fator_no_pico=round(fator_pico, 4),
        )

    comparativo = []
    for sigla in sorted(nomes):
        eolica = resumos.get((sigla, Fonte.EOLICA.value))
        solar = resumos.get((sigla, Fonte.SOLAR.value))
        diferenca = None
        if eolica and solar:
            diferenca = round(eolica.fator_capacidade - solar.fator_capacidade, 4)
        comparativo.append(
            ComparativoSubsistema(
                subsistema=sigla,
                nome_subsistema=nomes[sigla],
                eolica=eolica,
                solar=solar,
                diferenca_fator=diferenca,
            )
        )
    return comparativo


def _picos_por_subsistema_fonte(
    sessao: Session, inicio: datetime, fim: datetime, subsistema: str | None
) -> dict[tuple[str, str], tuple[int, float]]:
    picos: dict[tuple[str, str], tuple[int, float]] = {}
    for linha in repositorio.perfil_horario(sessao, inicio, fim, subsistema=subsistema):
        chave = (linha.subsistema_id, linha.fonte)
        atual = picos.get(chave)
        if atual is None or linha.fator > atual[1]:
            picos[chave] = (int(linha.hora), float(linha.fator))
    return picos
