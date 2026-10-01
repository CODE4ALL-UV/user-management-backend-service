"""Teclado Braille: recibe celdas y devuelve el texto que forman.

La app no traduce nada por su cuenta: manda la lista de celdas tal cual se
escribió y aquí se interpreta. Así la tabla vive en un solo sitio y, si hay que
corregir un signo, basta con desplegar el backend.

No hace falta sesión. Traducir Braille no expone datos de nadie, y exigirla
dejaría sin teclado justo a quien tiene problemas para iniciar sesión.
"""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from application.services.braille_translator import MAX_CELLS, translate

router = APIRouter(prefix="/api/braille", tags=["Braille"])


class BrailleTranslateRequest(BaseModel):
    cells: List[List[int]] = Field(
        ...,
        description="Cada celda es la lista de puntos levantados (1 a 6). "
        "Una celda vacía es un espacio.",
        examples=[[[1, 2, 5], [1, 3, 5], [1, 2, 3], [1]]],
    )


class BrailleCellResponse(BaseModel):
    index: int
    dots: List[int]
    kind: str
    value: str
    spoken: str


class BrailleTranslateResponse(BaseModel):
    text: str
    cells: List[BrailleCellResponse]
    unrecognized: List[int]


@router.post("/translate", response_model=BrailleTranslateResponse)
def translate_cells(request: BrailleTranslateRequest) -> BrailleTranslateResponse:
    if len(request.cells) > MAX_CELLS:
        raise HTTPException(
            status_code=413,
            detail=f"Como mucho se traducen {MAX_CELLS} celdas a la vez.",
        )

    try:
        result = translate(request.cells)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc

    return BrailleTranslateResponse(
        text=result.text,
        cells=[BrailleCellResponse(**vars(cell)) for cell in result.cells],
        unrecognized=result.unrecognized,
    )
