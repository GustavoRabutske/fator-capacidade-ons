"""Acesso a dados. Nada aqui conhece HTTP ou regra de negocio.

O fator de capacidade agregado e sempre soma(geracao) / soma(capacidade), nunca a
media dos fatores individuais: usinas tem portes muito diferentes e a media simples
daria o mesmo peso a um parque de 500 MW e a um de 30 MW.
"""

from datetime import date, datetime

from sqlalchemy import Select, distinct, extract, func, select
from sqlalchemy.orm import Session

from .modelos import MedicaoHoraria, Subsistema, Usina

_HORAS = func.count(distinct(MedicaoHoraria.instante))
_FATOR = func.sum(MedicaoHoraria.geracao_verificada_mw) / func.sum(
    MedicaoHoraria.capacidade_instalada_mw
)
_GERACAO_MEDIA = func.sum(MedicaoHoraria.geracao_verificada_mw) / _HORAS
_CAPACIDADE_MEDIA = func.sum(MedicaoHoraria.capacidade_instalada_mw) / _HORAS
_USINAS = func.count(distinct(MedicaoHoraria.usina_id))


def _filtrar(
    consulta: Select,
    inicio: datetime,
    fim: datetime,
    subsistema: str | None,
    fonte: str | None,
) -> Select:
    consulta = consulta.join(Usina, MedicaoHoraria.usina_id == Usina.id_ons).where(
        MedicaoHoraria.instante >= inicio, MedicaoHoraria.instante < fim
    )
    if subsistema:
        consulta = consulta.where(Usina.subsistema_id == subsistema)
    if fonte:
        consulta = consulta.where(Usina.fonte == fonte)
    return consulta


def listar_subsistemas(sessao: Session) -> list[Subsistema]:
    return list(sessao.scalars(select(Subsistema).order_by(Subsistema.id)))


def ultimo_instante(sessao: Session) -> datetime | None:
    return sessao.scalar(select(func.max(MedicaoHoraria.instante)))


def agregar_por_subsistema_fonte(
    sessao: Session,
    inicio: datetime,
    fim: datetime,
    subsistema: str | None = None,
    fonte: str | None = None,
) -> list:
    consulta = select(
        Usina.subsistema_id,
        Subsistema.nome,
        Usina.fonte,
        _FATOR.label("fator"),
        _GERACAO_MEDIA.label("geracao"),
        _CAPACIDADE_MEDIA.label("capacidade"),
        _USINAS.label("usinas"),
    )
    consulta = _filtrar(consulta, inicio, fim, subsistema, fonte).join(
        Subsistema, Usina.subsistema_id == Subsistema.id
    )
    consulta = consulta.group_by(Usina.subsistema_id, Subsistema.nome, Usina.fonte)
    return list(sessao.execute(consulta.order_by(Usina.subsistema_id, Usina.fonte)))


def serie_agregada(
    sessao: Session,
    inicio: datetime,
    fim: datetime,
    por_dia: bool,
    subsistema: str | None = None,
    fonte: str | None = None,
) -> list:
    # func.date roda igual em SQLite e PostgreSQL; em base horaria o proprio instante
    # ja e a chave do periodo e nao precisa de truncamento.
    periodo = func.date(MedicaoHoraria.instante) if por_dia else MedicaoHoraria.instante

    consulta = select(
        periodo.label("periodo"),
        Usina.subsistema_id,
        Usina.fonte,
        _FATOR.label("fator"),
        _GERACAO_MEDIA.label("geracao"),
        _CAPACIDADE_MEDIA.label("capacidade"),
        _USINAS.label("usinas"),
    )
    consulta = _filtrar(consulta, inicio, fim, subsistema, fonte)
    consulta = consulta.group_by(periodo, Usina.subsistema_id, Usina.fonte)
    return list(sessao.execute(consulta.order_by(periodo, Usina.subsistema_id, Usina.fonte)))


def perfil_horario(
    sessao: Session,
    inicio: datetime,
    fim: datetime,
    subsistema: str | None = None,
    fonte: str | None = None,
) -> list:
    """Fator medio por hora do dia (0-23), agrupado tambem por fonte e subsistema."""
    hora = extract("hour", MedicaoHoraria.instante)

    consulta = select(
        hora.label("hora"),
        Usina.subsistema_id,
        Usina.fonte,
        _FATOR.label("fator"),
        _GERACAO_MEDIA.label("geracao"),
        _CAPACIDADE_MEDIA.label("capacidade"),
        _USINAS.label("usinas"),
    )
    consulta = _filtrar(consulta, inicio, fim, subsistema, fonte)
    consulta = consulta.group_by(hora, Usina.subsistema_id, Usina.fonte)
    return list(sessao.execute(consulta.order_by(hora, Usina.subsistema_id, Usina.fonte)))


def periodo_disponivel(sessao: Session) -> tuple[datetime | None, datetime | None]:
    linha = sessao.execute(
        select(func.min(MedicaoHoraria.instante), func.max(MedicaoHoraria.instante))
    ).one()
    return linha[0], linha[1]


def como_data(valor) -> date:
    """SQLite devolve func.date como texto; PostgreSQL, como date."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])
