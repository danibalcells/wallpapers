import unittest

from mosaic_reference import (
    build_mosaic_positions,
    origin_from_top_left_subtile,
    parse_image_reference,
    parse_top_left_subtile,
    resolve_manual_selection,
    shift_top_left_subtile,
)


class MosaicReferenceTests(unittest.TestCase):
    def test_parse_image_reference(self) -> None:
        reference = parse_image_reference("canary_mosaic_20260315_28RCS02_20260317_003024.png")
        self.assertEqual(reference.date, "2026-03-15")
        self.assertEqual(reference.top_left_subtile.tile_id, "28RCS")
        self.assertEqual(reference.top_left_subtile.easting, 0)
        self.assertEqual(reference.top_left_subtile.northing, 2)

    def test_origin_from_top_left_subtile(self) -> None:
        origin = origin_from_top_left_subtile(parse_top_left_subtile("28RCS02"), mosaic_height=3)
        self.assertEqual(origin.tile_id, "28RCS")
        self.assertEqual(origin.easting, 0)
        self.assertEqual(origin.northing, 0)

    def test_resolve_manual_selection_from_image_with_offset(self) -> None:
        top_left_subtile, exact_date = resolve_manual_selection(
            top_left_subtile=None,
            from_image="canary_mosaic_20260315_28RCS02_20260317_003024.png",
            offset_east=1,
            offset_north=0,
            exact_date=None,
        )
        self.assertEqual(top_left_subtile, "28RCS02")
        self.assertEqual(exact_date, "2026-03-15")

    def test_resolve_manual_selection_rejects_offset_without_reference(self) -> None:
        with self.assertRaises(ValueError):
            resolve_manual_selection(
                top_left_subtile=None,
                from_image=None,
                offset_east=1,
                offset_north=0,
                exact_date=None,
            )

    def test_shift_top_left_subtile_wraps_west_and_south(self) -> None:
        shifted = shift_top_left_subtile(parse_top_left_subtile("28RCS02"), east_offset=-1, north_offset=-1)
        self.assertEqual(shifted.tile_id, "28RBS")
        self.assertEqual(shifted.easting, 9)
        self.assertEqual(shifted.northing, 1)

    def test_build_mosaic_positions_spans_multiple_tiles(self) -> None:
        positions = build_mosaic_positions(parse_top_left_subtile("28RCS02"), mosaic_width=4, mosaic_height=3)
        top_row = [f"{subtile.tile_id}{subtile.suffix()}" for subtile, _, row in positions if row == 0]
        self.assertEqual(top_row, ["28RCS02", "28RCS12", "28RCS22", "28RCS32"])


if __name__ == "__main__":
    unittest.main()
