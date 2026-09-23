from detector.tbank_v6.catalog_key_order import check_catalog_key_order


def test_genuine_catalog_order_is_not_a_break():
    pdf = b"1 0 obj\n<</Names 2 0 R/Type/Catalog/Pages 3 0 R>>\nendobj\n"
    result = check_catalog_key_order(pdf)
    assert result.flags == []
    assert result.stats["catalog_names_before_type"] is True


def test_reversed_catalog_key_order_is_a_structural_break():
    pdf = b"1 0 obj\n<</Type/Catalog/Names 2 0 R/Pages 3 0 R>>\nendobj\n"
    result = check_catalog_key_order(pdf)
    assert [flag.code for flag in result.flags] == ["TBANK_CATALOG_KEY_ORDER"]


def test_catalog_without_name_tree_is_not_this_break():
    pdf = b"1 0 obj\n<</Type/Catalog/Pages 3 0 R>>\nendobj\n"
    result = check_catalog_key_order(pdf)
    assert result.flags == []
    assert result.stats["catalog_names_linked"] is False
