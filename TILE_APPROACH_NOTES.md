## Why random bboxes are brittle

- STAC search returns tiles that intersect the bbox, not guaranteed full coverage.
- A single tile can yield nodata inside the bbox; dead pixels appear as black.
- Quality stats are tile-level and don't guarantee bbox-level validity.
- Partial tile coverage or internal nodata makes bbox images unreliable.

## Tile-based direction

- Sentinel-2 items are fixed 100 km MGRS tiles; sub-tiles must be computed.
- 10 km sub-tiles are a natural unit for validity checks and tiling.
- We can compute 10 km sub-tiles in UTM meters to avoid precision issues.
- Sub-tiles can be filtered by valid-pixel coverage (e.g., >= 98%).
- Full wallpaper mosaics should be color-corrected after mosaicing.

## Current hypothesis to test

- Validity is not uniform inside a 100 km tile.
- Some 10 km sub-tiles are valid while others are dead.
- We should build mosaics from contiguous valid 10 km sub-tiles.

## Algorithm (simple version)

### Precompute candidate 10 km tiles

- Build a static list of 10 km subtiles that contain at least a minimum amount of land.
- This list is only for sampling locations; it does not include pixel validity.

### Mosaic selection

- Randomly pick a subtile from the candidate list.
- Try to form a contiguous 4x3 rectangle of tiles that includes the seed.
- If it fails, mark the seed (and any tested neighbors that failed) as invalid and do not sample them again.
- Sampling is without replacement: never re-check a tile once it failed.
- Only change date if no valid 4x3 exists in the entire candidate pool.

### Rendering

- Fetch the 4x3 tiles for the chosen date.
- Mosaic raw bands first, then apply true-color once to the final mosaic.
- Export at full native resolution for the 4x3 area (40 km x 30 km).

### Recency priority

- Use only the most recent date by default.
- Move back in time only if the entire candidate pool fails to produce a 4x3 mosaic.

## Future extension

- Add iterative growth to larger mosaics (5x4, 6x4, etc) when possible.
