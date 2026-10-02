import sys
from pathlib import Path

# Las rutas importan como lo hace main.py, con app/ en el camino.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import pytest
from fastapi import HTTPException

from app.application.services.braille_translator import translate
from app.presentation.api.braille_routes import (
    BrailleTranslateRequest,
    translate_cells,
)


def test_translates_a_word():
    # h o l a
    assert translate([[1, 2, 5], [1, 3, 5], [1, 2, 3], [1]]).text == "hola"


def test_empty_cell_is_a_space():
    assert translate([[1], [], [1, 2]]).text == "a b"


def test_spanish_specific_letters():
    assert translate([[1, 2, 4, 5, 6], [1, 2, 3, 5, 6], [3, 4, 6]]).text == "ñáó"


def test_dot_order_and_repeats_do_not_matter():
    assert translate([[5, 2, 1, 1]]).text == "h"


def test_capital_sign_affects_only_next_letter():
    assert translate([[4, 6], [1], [1]]).text == "Aa"


def test_double_capital_sign_affects_whole_word():
    cells = [[4, 6], [4, 6], [1], [1, 2], [], [1]]
    assert translate(cells).text == "AB a"


def test_number_sign_turns_letters_into_digits_until_space():
    # #abc espacio a
    cells = [[3, 4, 5, 6], [1], [1, 2], [1, 4], [], [1]]
    assert translate(cells).text == "123 a"


def test_number_keeps_its_decimal_separator():
    # #c,e -> 3,5
    assert translate([[3, 4, 5, 6], [1, 4], [2], [1, 5]]).text == "3,5"


def test_punctuation():
    assert translate([[1], [2, 6]]).text == "a?"


def test_unknown_combination_is_reported_not_invented():
    # 4-5 sola no es nada en grado 1.
    result = translate([[1], [4, 5]])
    assert result.text == "a"
    assert result.unrecognized == [1]
    assert "4, 5" in result.cells[1].spoken


def test_each_cell_says_how_to_read_it_aloud():
    spoken = [cell.spoken for cell in translate([[4, 6], [1], [], [3]]).cells]
    assert spoken == ["mayúscula", "A mayúscula", "espacio", "punto"]


def test_dots_out_of_range_are_rejected():
    with pytest.raises(ValueError):
        translate([[7]])


def test_endpoint_returns_text_and_cells():
    body = translate_cells(BrailleTranslateRequest(cells=[[1, 2, 5], [1, 3, 5]]))
    assert body.text == "ho"
    assert [cell.value for cell in body.cells] == ["h", "o"]
    assert body.unrecognized == []


def test_endpoint_rejects_invalid_dots():
    with pytest.raises(HTTPException) as error:
        translate_cells(BrailleTranslateRequest(cells=[[0]]))
    assert error.value.status_code == 422


def test_writes_an_email():
    # ana@x.co
    a, n, x, c, o = [1], [1, 3, 4, 5], [1, 3, 4, 6], [1, 4], [1, 3, 5]
    cells = [a, n, a, [5], x, [3], c, o]
    assert translate(cells).text == "ana@x.co"


def test_email_with_digits():
    # ana1@x -> el signo de número no se come la arroba
    cells = [[1], [1, 3, 4, 5], [1], [3, 4, 5, 6], [1], [5], [1, 3, 4, 6]]
    assert translate(cells).text == "ana1@x"
