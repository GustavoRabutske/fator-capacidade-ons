from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Fonte(str, Enum):
    EOLICA = "EOLICA"
    SOLAR = "SOLAR"


class Granularidade(str, Enum):
    HORA = "hora"
    DIA = "dia"


class UltimaMedicao(BaseModel):
    subsistema: str = Field(examples=["NE"])
    nome_subsistema: str = Field(examples=["Nordeste"])
    fonte: Fonte
    instante: datetime
    fator_capacidade: float = Field(description="Ponderado pela capacidade instalada")
    geracao_verificada_mw: float
    capacidade_instalada_mw: float
    usinas: int


class PontoSerie(BaseModel):
    instante: datetime
    subsistema: str
    fonte: Fonte
    fator_capacidade: float
    geracao_media_mw: float
    capacidade_instalada_mw: float
    usinas: int


class SerieHistorica(BaseModel):
    granularidade: Granularidade
    inicio: datetime
    fim: datetime
    total_pontos: int
    pontos: list[PontoSerie]


class ResumoFonte(BaseModel):
    fator_capacidade: float
    geracao_media_mw: float
    capacidade_instalada_mw: float
    usinas: int
    hora_pico: int = Field(description="Hora do dia (0-23) de maior fator medio")
    fator_no_pico: float


class ComparativoSubsistema(BaseModel):
    subsistema: str
    nome_subsistema: str
    eolica: ResumoFonte | None
    solar: ResumoFonte | None
    diferenca_fator: float | None = Field(
        default=None, description="fator eolico menos fator solar no periodo"
    )
