import os

# Precisa vir antes de importar o pacote: evita que o app de teste toque o banco real.
os.environ["ENERGIA_URL_BANCO"] = "sqlite://"

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from energia.api import app  # noqa: E402
from energia.banco import Base, obter_sessao  # noqa: E402
from energia.modelos import MedicaoHoraria, Subsistema, Usina  # noqa: E402

PRIMEIRO_DIA = datetime(2025, 6, 1)
DIAS = 3

# (id_ons, nome, fonte, subsistema, capacidade_mw, escala do fator)
USINAS = [
    ("EOL_NE_A", "Conj. Ventos do Sertao", "EOLICA", "NE", 100.0, 1.0),
    ("EOL_NE_B", "Conj. Serra Branca", "EOLICA", "NE", 300.0, 0.5),
    ("SOL_NE", "Conj. Sol do Vale", "SOLAR", "NE", 100.0, 1.0),
    ("EOL_S", "Elebras Cidreira 1", "EOLICA", "S", 50.0, 1.0),
]


def fator_base(fonte: str, hora: int) -> float:
    """Curvas sinteticas com pico unico: eolica as 21h, solar as 12h."""
    if fonte == "EOLICA":
        return 0.50 - abs(hora - 21) / 100
    return max(0.0, 0.60 - abs(hora - 12) / 12)


@pytest.fixture
def sessao():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as aberta:
        yield aberta
    engine.dispose()


@pytest.fixture
def sessao_populada(sessao):
    sessao.add_all(
        [Subsistema(id="NE", nome="Nordeste"), Subsistema(id="S", nome="Sul")]
    )
    for id_ons, nome, fonte, subsistema, capacidade, escala in USINAS:
        sessao.add(
            Usina(
                id_ons=id_ons,
                nome=nome,
                fonte=fonte,
                modalidade="Conjunto de Usinas",
                uf="BA" if subsistema == "NE" else "RS",
                localizacao="Interior",
                latitude=-12.0,
                longitude=-42.0,
                cod_ponto_conexao=f"{id_ons}-230",
                subsistema_id=subsistema,
            )
        )
        for dia in range(DIAS):
            for hora in range(24):
                fator = fator_base(fonte, hora) * escala
                sessao.add(
                    MedicaoHoraria(
                        usina_id=id_ons,
                        instante=PRIMEIRO_DIA + timedelta(days=dia, hours=hora),
                        geracao_programada_mw=None,
                        geracao_verificada_mw=round(fator * capacidade, 6),
                        capacidade_instalada_mw=capacidade,
                        fator_capacidade=fator,
                    )
                )
    sessao.commit()
    return sessao


@pytest.fixture
def cliente(sessao_populada):
    app.dependency_overrides[obter_sessao] = lambda: sessao_populada
    with TestClient(app) as testador:
        yield testador
    app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_dados(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    with TestClient(app) as testador:
        yield testador
    app.dependency_overrides.clear()
