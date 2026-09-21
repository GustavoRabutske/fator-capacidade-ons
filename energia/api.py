from contextlib import asynccontextmanager
from datetime import date

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from . import repositorio, servicos
from .banco import criar_tabelas, obter_sessao
from .esquemas import ComparativoSubsistema, Fonte, Granularidade, SerieHistorica, UltimaMedicao
from .servicos import DadosIndisponiveis, ParametroInvalido

@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    criar_tabelas()
    yield


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="Monitor de Geracao Renovavel",
    version="1.0.0",
    description=(
        "Fator de capacidade horario de usinas eolicas e solares do SIN, a partir do "
        "Portal de Dados Abertos do ONS. Os instantes estao no horario de Brasilia, "
        "sem fuso explicito, como na fonte."
    ),
)

router = APIRouter(prefix="/geracao", tags=["geracao"])


@app.exception_handler(ParametroInvalido)
def _parametro_invalido(request: Request, exc: ParametroInvalido) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(DadosIndisponiveis)
def _dados_indisponiveis(request: Request, exc: DadosIndisponiveis) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/saude", tags=["meta"])
def saude(sessao: Session = Depends(obter_sessao)) -> dict:
    inicio, fim = repositorio.periodo_disponivel(sessao)
    return {
        "status": "ok",
        "periodo_carregado": {"inicio": inicio, "fim": fim},
        "subsistemas": [s.id for s in repositorio.listar_subsistemas(sessao)],
    }


@router.get(
    "/ultima-medicao",
    response_model=list[UltimaMedicao],
    summary="Fator de capacidade da hora mais recente carregada na base",
    description=(
        "Devolve a ultima hora presente no banco, nao o instante corrente: o ONS "
        "publica esta serie em arquivos mensais, com defasagem. Consulte /saude para "
        "saber a que periodo a base carregada corresponde."
    ),
)
def ultima_medicao(
    fonte: Fonte | None = Query(default=None),
    sessao: Session = Depends(obter_sessao),
) -> list[UltimaMedicao]:
    return servicos.obter_ultima_medicao(sessao, fonte=fonte)


@router.get(
    "/historico",
    response_model=SerieHistorica,
    summary="Serie historica filtravel por periodo, subsistema e fonte",
)
def geracao_historico(
    inicio: date = Query(description="Primeiro dia do intervalo (inclusivo)"),
    fim: date = Query(description="Ultimo dia do intervalo (inclusivo)"),
    granularidade: Granularidade = Query(default=Granularidade.DIA),
    subsistema: str | None = Query(default=None, examples=["NE"]),
    fonte: Fonte | None = Query(default=None),
    sessao: Session = Depends(obter_sessao),
) -> SerieHistorica:
    return servicos.obter_historico(
        sessao,
        inicio=inicio,
        fim=fim,
        granularidade=granularidade,
        subsistema=subsistema,
        fonte=fonte,
    )


@router.get(
    "/comparativo",
    response_model=list[ComparativoSubsistema],
    summary="Eolica x solar por subsistema, com a hora de pico de cada fonte",
)
def geracao_comparativo(
    inicio: date = Query(description="Primeiro dia do intervalo (inclusivo)"),
    fim: date = Query(description="Ultimo dia do intervalo (inclusivo)"),
    subsistema: str | None = Query(default=None, examples=["NE"]),
    sessao: Session = Depends(obter_sessao),
) -> list[ComparativoSubsistema]:
    return servicos.comparar_fontes(sessao, inicio=inicio, fim=fim, subsistema=subsistema)


app.include_router(router)
