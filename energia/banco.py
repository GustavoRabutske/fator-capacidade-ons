from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .configuracao import URL_BANCO


class Base(DeclarativeBase):
    pass


def _opcoes_conexao(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(URL_BANCO, connect_args=_opcoes_conexao(URL_BANCO))
Sessao = sessionmaker(bind=engine, expire_on_commit=False)


def criar_tabelas() -> None:
    from . import modelos  # noqa: F401  garante o registro dos modelos no metadata

    Base.metadata.create_all(engine)


def obter_sessao():
    """Dependencia do FastAPI."""
    with Sessao() as sessao:
        yield sessao
