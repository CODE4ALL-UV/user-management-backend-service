"""Traducción de celdas Braille a texto (Braille español, grado 1).

Una celda es el conjunto de puntos levantados, del 1 al 6:

    1 ● ● 4
    2 ● ● 5
    3 ● ● 6

La app manda las celdas tal cual las escribió la persona y aquí se decide qué
significan. Además del texto se devuelve, celda a celda, qué se entendió y cómo
decirlo en voz alta: quien escribe en Braille con esta app normalmente no ve la
pantalla, y necesita oír qué letra acaba de confirmar.

Se sigue la signografía de la Comisión Braille Española, que es la que se usa
en América Latina:

- Signo de mayúscula (46): la letra siguiente va en mayúscula. Dos seguidos
  ponen en mayúscula la palabra entera.
- Signo de número (3456): las letras de la «a» a la «j» pasan a ser los
  dígitos 1‑9 y 0 hasta que llega un espacio u otro signo.
"""

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


def _cell(*dots: int) -> frozenset:
    return frozenset(dots)


# Letras. La «w» y la «ñ» van aparte en el Braille español, igual que las
# vocales acentuadas: no son una variante de otra letra.
LETTERS = {
    _cell(1): "a",
    _cell(1, 2): "b",
    _cell(1, 4): "c",
    _cell(1, 4, 5): "d",
    _cell(1, 5): "e",
    _cell(1, 2, 4): "f",
    _cell(1, 2, 4, 5): "g",
    _cell(1, 2, 5): "h",
    _cell(2, 4): "i",
    _cell(2, 4, 5): "j",
    _cell(1, 3): "k",
    _cell(1, 2, 3): "l",
    _cell(1, 3, 4): "m",
    _cell(1, 3, 4, 5): "n",
    _cell(1, 2, 4, 5, 6): "ñ",
    _cell(1, 3, 5): "o",
    _cell(1, 2, 3, 4): "p",
    _cell(1, 2, 3, 4, 5): "q",
    _cell(1, 2, 3, 5): "r",
    _cell(2, 3, 4): "s",
    _cell(2, 3, 4, 5): "t",
    _cell(1, 3, 6): "u",
    _cell(1, 2, 3, 6): "v",
    _cell(2, 4, 5, 6): "w",
    _cell(1, 3, 4, 6): "x",
    _cell(1, 3, 4, 5, 6): "y",
    _cell(1, 3, 5, 6): "z",
    _cell(1, 2, 3, 5, 6): "á",
    _cell(2, 3, 4, 6): "é",
    _cell(3, 4): "í",
    _cell(3, 4, 6): "ó",
    _cell(2, 3, 4, 5, 6): "ú",
    _cell(1, 2, 5, 6): "ü",
}

# Con el signo de número delante, de la «a» a la «j» son dígitos.
DIGITS = {
    "a": "1",
    "b": "2",
    "c": "3",
    "d": "4",
    "e": "5",
    "f": "6",
    "g": "7",
    "h": "8",
    "i": "9",
    "j": "0",
}

# Signos de puntuación con el nombre con que se leen en voz alta. El de
# interrogación y el de exclamación sirven para abrir y para cerrar; aquí se
# escribe el de cierre, que es el que se entiende sin contexto.
PUNCTUATION = {
    _cell(3): (".", "punto"),
    _cell(2): (",", "coma"),
    _cell(2, 3): (";", "punto y coma"),
    _cell(2, 5): (":", "dos puntos"),
    _cell(2, 6): ("?", "interrogación"),
    _cell(2, 3, 5): ("!", "exclamación"),
    _cell(2, 3, 6): ('"', "comillas"),
    _cell(1, 2, 6): ("(", "abre paréntesis"),
    _cell(3, 4, 5): (")", "cierra paréntesis"),
    _cell(3, 6): ("-", "guion"),
    # La arroba hace falta para escribir el correo en el login.
    _cell(5): ("@", "arroba"),
}

CAPITAL_SIGN = _cell(4, 6)
NUMBER_SIGN = _cell(3, 4, 5, 6)
SPACE = frozenset()

# Dentro de un número, el punto y la coma separan cifras y no lo cortan.
_NUMBER_SEPARATORS = {_cell(3): ".", _cell(2): ","}

MAX_CELLS = 2000


@dataclass
class CellReading:
    """Lo que se entendió de una celda."""

    index: int
    dots: List[int]
    kind: str
    """letter, digit, punctuation, capital_sign, number_sign, space o unknown."""
    value: str
    """Lo que aporta al texto. Vacío en los signos que solo cambian la siguiente."""
    spoken: str
    """Cómo decirlo en voz alta."""


@dataclass
class Translation:
    text: str
    cells: List[CellReading] = field(default_factory=list)

    @property
    def unrecognized(self) -> List[int]:
        return [cell.index for cell in self.cells if cell.kind == "unknown"]


def normalize_cell(dots: Iterable[int]) -> frozenset:
    """Valida una celda. Los puntos repetidos o desordenados no importan."""
    cell = frozenset(int(dot) for dot in dots)
    invalid = [dot for dot in cell if dot < 1 or dot > 6]
    if invalid:
        raise ValueError(f"Los puntos van del 1 al 6; llegó {sorted(invalid)}.")
    return cell


def translate(raw_cells: Sequence[Iterable[int]]) -> Translation:
    """Convierte una secuencia de celdas en texto."""
    if len(raw_cells) > MAX_CELLS:
        raise ValueError(f"Como mucho se traducen {MAX_CELLS} celdas a la vez.")

    cells = [normalize_cell(dots) for dots in raw_cells]

    text: List[str] = []
    readings: List[CellReading] = []

    number_mode = False
    capital_next = False
    capital_word = False
    previous: Optional[frozenset] = None

    for index, cell in enumerate(cells):
        dots = sorted(cell)

        def add(kind: str, value: str, spoken: str) -> None:
            readings.append(CellReading(index, dots, kind, value, spoken))
            text.append(value)

        if cell == SPACE:
            number_mode = capital_next = capital_word = False
            add("space", " ", "espacio")

        elif cell == CAPITAL_SIGN:
            number_mode = False
            # Dos signos de mayúscula seguidos: toda la palabra.
            if previous == CAPITAL_SIGN and capital_next:
                capital_word = True
                capital_next = False
                add("capital_sign", "", "palabra en mayúsculas")
            else:
                capital_next = True
                add("capital_sign", "", "mayúscula")

        elif cell == NUMBER_SIGN:
            number_mode = True
            capital_next = capital_word = False
            add("number_sign", "", "signo de número")

        elif number_mode and cell in LETTERS and LETTERS[cell] in DIGITS:
            digit = DIGITS[LETTERS[cell]]
            add("digit", digit, digit)

        elif number_mode and cell in _NUMBER_SEPARATORS:
            # Se queda en modo número: 1.000 o 3,5 siguen siendo un número.
            mark = _NUMBER_SEPARATORS[cell]
            add("punctuation", mark, PUNCTUATION[cell][1])

        elif cell in LETTERS:
            number_mode = False
            letter = LETTERS[cell]
            if capital_next or capital_word:
                letter = letter.upper()
                capital_next = False
                add("letter", letter, f"{letter} mayúscula")
            else:
                add("letter", letter, letter)

        elif cell in PUNCTUATION:
            number_mode = capital_next = capital_word = False
            mark, name = PUNCTUATION[cell]
            add("punctuation", mark, name)

        else:
            number_mode = capital_next = False
            dots_text = ", ".join(str(dot) for dot in dots)
            readings.append(
                CellReading(
                    index,
                    dots,
                    "unknown",
                    "",
                    f"combinación no reconocida, puntos {dots_text}",
                )
            )

        previous = cell

    return Translation(text="".join(text), cells=readings)
