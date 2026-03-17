import unittest

from mosaic_reference import build_mosaic_positions, parse_top_left_subtile
from scripts.build_tile_candidates import _expand_tile_ids, _support_subtiles
from tiles import Subtile


class BuildTileCandidatesTests(unittest.TestCase):
    def test_expand_tile_ids_adds_one_tile_halo(self) -> None:
        expanded = _expand_tile_ids(["28RFT"], halo=1)

        self.assertIn("28RET", expanded)
        self.assertIn("28RFS", expanded)
        self.assertIn("28RFU", expanded)
        self.assertIn("28RGT", expanded)

    def test_support_subtiles_keep_full_mosaic_with_single_land_subtile(self) -> None:
        positions = build_mosaic_positions(parse_top_left_subtile("28RET90"), mosaic_width=4, mosaic_height=3)
        subtiles = [subtile for subtile, _, _ in positions]
        land_fractions = {subtile: 0.0 for subtile in subtiles}
        land_fractions[Subtile("28RFT", 0, 0)] = 0.2

        kept = _support_subtiles(
            subtiles,
            land_fractions,
            support_mosaic_width=4,
            support_mosaic_height=3,
            min_land_per_subtile=0.05,
            min_land_subtiles_per_mosaic=1,
        )

        self.assertEqual(kept, set(subtiles))


if __name__ == "__main__":
    unittest.main()
