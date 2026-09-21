from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .banco import Base


class Subsistema(Base):
    """Os quatro subsistemas do SIN: N, NE, S e SE."""

    __tablename__ = "subsistema"

    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    nome: Mapped[str] = mapped_column(String(40), nullable=False)

    usinas: Mapped[list["Usina"]] = relationship(back_populates="subsistema")


class Usina(Base):
    """Usina ou conjunto de usinas despachado pelo ONS.

    A chave e o id_ons publicado na fonte: e estavel entre os arquivos mensais e
    unico, ao contrario do nome do conjunto, que colide (dois id_ons diferentes
    chegam a compartilhar o mesmo nome).
    """

    __tablename__ = "usina"

    id_ons: Mapped[str] = mapped_column(String(30), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    fonte: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    modalidade: Mapped[str] = mapped_column(String(30), nullable=False)
    uf: Mapped[str] = mapped_column(String(2), nullable=False)
    localizacao: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    cod_ponto_conexao: Mapped[str | None] = mapped_column(String(30))
    subsistema_id: Mapped[str] = mapped_column(
        ForeignKey("subsistema.id"), nullable=False, index=True
    )

    subsistema: Mapped[Subsistema] = relationship(back_populates="usinas")
    medicoes: Mapped[list["MedicaoHoraria"]] = relationship(
        back_populates="usina", cascade="all, delete-orphan"
    )


class MedicaoHoraria(Base):
    """Uma hora de operacao de uma usina.

    A capacidade instalada fica aqui e nao na usina de proposito: ela muda ao longo
    do ano conforme os parques sao ampliados, e amarra-la a dimensao produziria
    fator de capacidade errado no retroativo.
    """

    __tablename__ = "medicao_horaria"

    id: Mapped[int] = mapped_column(primary_key=True)
    usina_id: Mapped[str] = mapped_column(ForeignKey("usina.id_ons"), nullable=False)
    instante: Mapped[datetime] = mapped_column(nullable=False)
    geracao_programada_mw: Mapped[float | None] = mapped_column(Float)
    geracao_verificada_mw: Mapped[float] = mapped_column(Float, nullable=False)
    capacidade_instalada_mw: Mapped[float] = mapped_column(Float, nullable=False)
    fator_capacidade: Mapped[float] = mapped_column(Float, nullable=False)

    usina: Mapped[Usina] = relationship(back_populates="medicoes")

    __table_args__ = (
        UniqueConstraint("usina_id", "instante", name="uq_medicao_usina_instante"),
        Index("ix_medicao_instante", "instante"),
    )
