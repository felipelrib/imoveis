"""Unit tests for OLX listing-type title/price helpers (BIN-81)."""

from __future__ import annotations

import pytest

from core.olx_listing_type import (
    infer_olx_listing_type,
    listing_type_from_price,
    listing_type_from_title,
    mask_venda_nova,
)


@pytest.mark.unit
class TestOlxListingTypeHelpers:
    def test_mask_venda_nova(self):
        assert "venda" not in mask_venda_nova("Casa em Venda Nova/BH").casefold()
        assert "venda" not in mask_venda_nova("slug-venda-nova-apto").casefold()

    def test_title_venda_nova_alone_not_sale(self):
        assert listing_type_from_title(
            "Casa de 03 quartos no Candelária - Venda Nova/Belo Horizonte"
        ) is None

    def test_title_a_venda_is_sale(self):
        assert listing_type_from_title("Apartamento à venda no Centro") == "sale"

    def test_title_aluguel_is_rent(self):
        assert listing_type_from_title("Casa para aluguel em Venda Nova") == "rent"

    def test_price_bands(self):
        assert listing_type_from_price(1300) == "rent"
        assert listing_type_from_price(450_000) == "sale"
        assert listing_type_from_price(50_000) is None

    def test_infer_venda_nova_cheap_is_rent(self):
        assert (
            infer_olx_listing_type(
                title="Casa de 03 quartos no Candelária - Venda Nova/Belo Horizonte",
                price=1300,
                current="sale",
            )
            == "rent"
        )

    def test_dual_title_defers_to_sale_price(self):
        assert (
            infer_olx_listing_type(
                title="Cobertura para locação ou venda Castelo",
                price=1_350_000,
                current="sale",
            )
            == "sale"
        )

    def test_dual_title_defers_to_rent_price(self):
        assert (
            infer_olx_listing_type(
                title="Venda ou locação Casa Buritis",
                price=12_000,
                current="sale",
            )
            == "rent"
        )

    def test_a_venda_phrase_beats_missing_price(self):
        assert listing_type_from_title("Apartamento à venda no Centro") == "sale"
