from __future__ import annotations

import pytest

from bot.keyboards import paginate


class TestPaginate:
    def test_first_page(self):
        items = list(range(12))
        page_items, total = paginate(items, page=0, page_size=5)
        assert page_items == [0, 1, 2, 3, 4]
        assert total == 3

    def test_middle_page(self):
        items = list(range(12))
        page_items, total = paginate(items, page=1, page_size=5)
        assert page_items == [5, 6, 7, 8, 9]
        assert total == 3

    def test_last_partial_page(self):
        items = list(range(12))
        page_items, total = paginate(items, page=2, page_size=5)
        assert page_items == [10, 11]
        assert total == 3

    def test_empty_list(self):
        page_items, total = paginate([], page=0, page_size=5)
        assert page_items == []
        assert total == 1

    def test_exact_multiple(self):
        page_items, total = paginate(list(range(10)), page=1, page_size=5)
        assert page_items == [5, 6, 7, 8, 9]
        assert total == 2

    def test_page_clamped_to_last(self):
        page_items, total = paginate(list(range(5)), page=99, page_size=5)
        assert page_items == [0, 1, 2, 3, 4]
        assert total == 1

    def test_negative_page_clamped_to_zero(self):
        page_items, total = paginate(list(range(5)), page=-3, page_size=5)
        assert page_items == [0, 1, 2, 3, 4]
        assert total == 1

    def test_invalid_page_size(self):
        with pytest.raises(ValueError):
            paginate([1, 2, 3], page=0, page_size=0)
