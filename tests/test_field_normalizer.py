import unittest
from pathlib import Path

from services.comparison_engine import ComparisonEngine
from services.document_parser import DocumentParser
from services.field_normalizer import (
    compare_ports,
    names_match,
    normalize_party_name,
    normalize_shipment_json,
    parse_container_count,
    parse_gross_weight_kg,
    parse_port,
)

ATTACHMENTS_DIR = Path(__file__).resolve().parent.parent.parent / "attachments"
HAS_SAMPLE_DATA = ATTACHMENTS_DIR.is_dir()


class NormalizePartyNameTests(unittest.TestCase):
    def test_strips_period_punctuation_around_suffix(self):
        self.assertEqual(normalize_party_name("Vital Solutions Pte. Ltd."), "VITAL SOLUTIONS PTE LTD")

    def test_drops_comma_before_suffix(self):
        self.assertEqual(normalize_party_name("Moorim SP Co., Ltd"), "MOORIM SP CO LTD")

    def test_folds_trailing_suffix_parenthetical(self):
        self.assertEqual(normalize_party_name("Orient Links Co (LLC)"), "ORIENT LINKS CO LLC")

    def test_does_not_fold_non_suffix_parenthetical(self):
        # "(M)" here is part of the legal name (Malaysia), not a trailing suffix token.
        self.assertEqual(normalize_party_name("April Far East (M) Sdn Bhd"), "APRIL FAR EAST (M) SDN BHD")

    def test_maps_suffix_synonyms(self):
        self.assertEqual(normalize_party_name("Acme Trading Limited"), "ACME TRADING LTD")
        self.assertEqual(normalize_party_name("Acme Trading Corporation"), "ACME TRADING CORP")


class NamesMatchTests(unittest.TestCase):
    def test_matches_after_normalization(self):
        self.assertTrue(names_match("VITAL SOLUTIONS PTE LTD", "Vital Solutions Pte. Ltd."))
        self.assertTrue(names_match("Moorim SP Co., Ltd", "MOORIM SP CO LTD"))

    def test_rejects_genuinely_different_names(self):
        self.assertFalse(names_match("MOORIM SP CO., LTD", "UAB NOVAKOPA"))


class PortNormalizationTests(unittest.TestCase):
    def test_parses_locode_and_city_country(self):
        parsed = parse_port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")
        self.assertEqual(parsed["locode"], "MYPKG")
        self.assertEqual(parsed["city"], "PORT KLANG")
        self.assertEqual(parsed["country"], "MALAYSIA")

    def test_splits_multi_port_slash_list(self):
        parsed = parse_port("RUGAO/NANTONG/SHANGHAI, CHINA (CNSHA)")
        self.assertEqual(parsed["cities"], ["RUGAO", "NANTONG", "SHANGHAI"])

    def test_same_locode_matches_despite_different_labels(self):
        result = compare_ports("Port of Loading (POL): ".split(": ", 1)[-1] + "SINGAPORE (SGSIN)", "SINGAPORE (SGSIN)")
        self.assertTrue(result["match"])

    def test_flags_locode_city_mismatch_for_known_code(self):
        # INNSA is Nhava Sheva, India -- "Buatan, Indonesia" is a real
        # data-quality error seen in the sample BL for email_128.
        result = compare_ports("NHAVA SHEVA, INDIA (INNSA)", "BUATAN, INDONESIA (INNSA)")
        self.assertTrue(result["match"])  # same LOCODE on both sides
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["reason"], "locode_city_mismatch")

    def test_unknown_locode_does_not_trigger_false_review(self):
        result = compare_ports("CONAKRY, GUINEA (GNCKY)", "CONAKRY, GUINEA (GNCKY)")
        self.assertTrue(result["match"])
        self.assertFalse(result["needs_review"])

    def test_different_locode_is_a_mismatch(self):
        result = compare_ports("SINGAPORE (SGSIN)", "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")
        self.assertFalse(result["match"])


class ContainerCountTests(unittest.TestCase):
    def test_parses_compound_quantity_and_type(self):
        self.assertEqual(parse_container_count("1 x 40'HC"), 1)
        self.assertEqual(parse_container_count("5 x 20'GP"), 5)

    def test_sums_multiple_container_lines(self):
        self.assertEqual(parse_container_count("2 x 40'HC + 3 x 20'GP"), 5)

    def test_parses_parenthetical_form(self):
        self.assertEqual(parse_container_count("TWO (2) CONTAINERS"), 2)

    def test_falls_back_to_leading_integer(self):
        self.assertEqual(parse_container_count("4 containers"), 4)


class GrossWeightTests(unittest.TestCase):
    def test_strips_comma_and_unit(self):
        self.assertEqual(parse_gross_weight_kg("21,577 KG"), 21577.0)

    def test_handles_cjk_glued_label_value_is_clean(self):
        self.assertEqual(parse_gross_weight_kg("103,800 KG"), 103800.0)

    def test_converts_pounds_to_kg(self):
        self.assertAlmostEqual(parse_gross_weight_kg("1000 LBS"), 453.592)


class ComparisonNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = ComparisonEngine()

    def test_compares_ocr_style_container_count(self):
        result = self.engine.compare(
            {"container_count": "8x 40HC"},
            {"container_count": "8"},
        )
        self.assertNotIn("container_count", result["defect_fields"])

    def test_compares_weight_with_units_and_commas(self):
        result = self.engine.compare(
            {"gross_weight_kg": "21,577 KG"},
            {"gross_weight_kg": "21577.0"},
        )
        self.assertNotIn("gross_weight_kg", result["defect_fields"])

    def test_unparseable_numeric_values_need_review_instead_of_crashing(self):
        result = self.engine.compare(
            {"container_count": "eight high cubes"},
            {"container_count": "8"},
        )
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIn("container_count", result["missing_fields"])


class NormalizeShipmentJsonTests(unittest.TestCase):
    def test_matches_the_agreed_example(self):
        payload = {
            "Shipper": "April Far East (M) Sdn. Bhd.",
            "Consignee": "MOORIM SP CO., LTD",
            "Notify Party": "Roxcel Trading GmbH",
            "Port of Loading": "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
            "Port of Discharge": "HOCHIMINH CITY, VIETNAM (VNSGN)",
            "Container Count": "5 x 20'GP",
            "Gross Weight (kg)": "21,577 KG",
        }
        expected = {
            "Shipper": "APRIL FAR EAST (M) SDN BHD",
            "Consignee": "MOORIM SP CO LTD",
            "Notify Party": "ROXCEL TRADING GMBH",
            "Port of Loading": "MYPKG",
            "Port of Discharge": "VNSGN",
            "Container Count": "5",
            "Gross Weight (kg)": "21577.0",
        }
        self.assertEqual(normalize_shipment_json(payload), expected)

    def test_port_without_locode_falls_back_to_city_country(self):
        result = normalize_shipment_json({"Port of Loading": "Rotterdam, Netherlands"})
        self.assertEqual(result["Port of Loading"], "ROTTERDAM, NETHERLANDS")

    def test_unparseable_numeric_field_normalizes_to_empty_string(self):
        result = normalize_shipment_json({"Gross Weight (kg)": "N/A"})
        self.assertEqual(result["Gross Weight (kg)"], "")


@unittest.skipUnless(HAS_SAMPLE_DATA, "sample bundle attachments/ not present")
class RealDocumentPairIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.parser = DocumentParser()
        self.engine = ComparisonEngine()

    def _compare_pair(self, email_id: str) -> dict:
        si_text = (ATTACHMENTS_DIR / f"{email_id}_SI.txt").read_text(encoding="utf-8")
        bl_text = (ATTACHMENTS_DIR / f"{email_id}_BL.txt").read_text(encoding="utf-8")
        si_fields = self.parser.parse_text(si_text).model_dump()
        bl_fields = self.parser.parse_text(bl_text).model_dump()
        return self.engine.compare(si_fields, bl_fields)

    def test_email_001_all_fields_match_despite_label_differences(self):
        result = self._compare_pair("email_001")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["defect_fields"], [])
        self.assertEqual(result["missing_fields"], [])

    def test_email_064_matches_with_cjk_label_and_paren_suffix_party(self):
        result = self._compare_pair("email_064")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["defect_fields"], [])

    def test_email_111_flags_container_count_mismatch_only(self):
        result = self._compare_pair("email_111")
        self.assertEqual(result["status"], "MISMATCH")
        self.assertEqual(result["defect_fields"], ["container_count"])
        self.assertEqual(result["mismatch_details"]["container_count"], {"si": "4", "bl": "3"})

    def test_email_128_flags_weight_mismatch_and_port_review(self):
        result = self._compare_pair("email_128")
        self.assertEqual(result["status"], "MISMATCH")
        self.assertEqual(result["defect_fields"], ["gross_weight_kg"])
        self.assertIn("port_of_loading", result["review_details"])
        self.assertEqual(result["review_details"]["port_of_loading"]["reason"], "locode_city_mismatch")


if __name__ == "__main__":
    unittest.main()
