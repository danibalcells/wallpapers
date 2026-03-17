import unittest

from mosaic_selector import build_mosaics, mosaics_containing_seed
from tiles import Subtile


class MosaicSelectorTests(unittest.TestCase):
    def test_build_mosaics_spans_tile_boundaries(self) -> None:
        subtiles = [
            Subtile("28RBS", 9, 3),
            Subtile("28RCS", 0, 3),
            Subtile("28RCS", 1, 3),
            Subtile("28RCS", 2, 3),
            Subtile("28RBS", 9, 2),
            Subtile("28RCS", 0, 2),
            Subtile("28RCS", 1, 2),
            Subtile("28RCS", 2, 2),
            Subtile("28RBS", 9, 1),
            Subtile("28RCS", 0, 1),
            Subtile("28RCS", 1, 1),
            Subtile("28RCS", 2, 1),
        ]

        mosaics = build_mosaics(subtiles, width=4, height=3)

        self.assertEqual(len(mosaics), 1)
        mosaic = mosaics[0]
        self.assertEqual(mosaic.top_left_subtile, Subtile("28RBS", 9, 3))
        self.assertEqual(
            [f"{subtile.tile_id}{subtile.suffix()}" for subtile in mosaic.subtiles],
            [
                "28RBS93",
                "28RCS03",
                "28RCS13",
                "28RCS23",
                "28RBS92",
                "28RCS02",
                "28RCS12",
                "28RCS22",
                "28RBS91",
                "28RCS01",
                "28RCS11",
                "28RCS21",
            ],
        )

    def test_mosaics_containing_seed_matches_non_anchor_tile(self) -> None:
        subtiles = [
            Subtile("28RBS", 9, 3),
            Subtile("28RCS", 0, 3),
            Subtile("28RCS", 1, 3),
            Subtile("28RCS", 2, 3),
            Subtile("28RBS", 9, 2),
            Subtile("28RCS", 0, 2),
            Subtile("28RCS", 1, 2),
            Subtile("28RCS", 2, 2),
            Subtile("28RBS", 9, 1),
            Subtile("28RCS", 0, 1),
            Subtile("28RCS", 1, 1),
            Subtile("28RCS", 2, 1),
        ]

        mosaics = build_mosaics(subtiles, width=4, height=3)
        matches = mosaics_containing_seed(mosaics, Subtile("28RCS", 1, 2))

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].top_left_subtile, Subtile("28RBS", 9, 3))


if __name__ == "__main__":
    unittest.main()
