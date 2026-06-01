# rt2gtfs

`rt2gtfs` is a Python package for matching real-time vehicle position data with scheduled GTFS data to produce corrected observed GTFS timetables.

It is designed for workflows where scheduled GTFS data and real-time vehicle observations are combined to produce a more realistic representation of service operations.

---

## Features

* Convert raw GTFS-Realtime vehicle position files (PBF) to CSV
* Remove duplicate real-time vehicle observations (optional)
* Match vehicle position observations to scheduled GTFS stops
* Use timetable data from nearby dates to improve matching
* Construct observed GTFS outputs from scheduled and real-time data
* Run the workflow from Python or the command line

---

## Installation

For development:

```bash
git clone https://github.com/kevinwinsper/rt2gtfs.git
cd rt2gtfs
pip install -e .
```

---

## Package structure

The main public API currently includes:

* `MatchingConfig`
* `construct_observed_gtfs`
* `generate_date_range`
* `convert_rt_to_csv`

---

## Python usage

### 1. Convert raw GTFS-Realtime files to CSV

```python
from pathlib import Path
from rt2gtfs import MatchingConfig, convert_rt_to_csv

config = MatchingConfig(
    gtfs_dir=Path("data/gtfs"),
    rt_dir=Path("data/gtfs-rt"),
    result_dir=Path("data/gtfs-rt"),
    unzip_rt=True,
    deduplicate_rt=True,
    output_rt_csv_dirname="csv",
)

convert_rt_to_csv(["20250901", "20250902"], config)
```

---

### 2. Construct observed GTFS outputs

```python
from pathlib import Path
from rt2gtfs import MatchingConfig, construct_observed_gtfs

config = MatchingConfig(
    gtfs_dir=Path("data/gtfs"),
    rt_dir=Path("data/gtfs-rt/csv"),
    result_dir=Path("data/observed_gtfs"),
    check_extra_dates=True,
    time_window_days=7,
    matching_periods=[("06:00:00", "19:00:00")],
)

construct_observed_gtfs(["20250901", "20250902"], config)
```

---

## Command line usage

Show available commands:

```bash
rt2gtfs --help
```

### Convert raw GTFS-Realtime files to CSV

```bash
rt2gtfs rt-to-csv \
  --start-date 20250901 \
  --end-date 20250902 \
  --rt-dir data/gtfs-rt \
  --result-dir data/gtfs-rt
```

### Construct observed GTFS outputs

```bash
rt2gtfs observed-gtfs \
  --start-date 20250901 \
  --end-date 20250902 \
  --gtfs-dir data/gtfs \
  --rt-dir data/gtfs-rt/csv \
  --result-dir data/observed_gtfs \
  --check-extra-dates \
  --time-window-days 7 \
  --matching-period 06:00:00 19:00:00
```

---

## Key inputs

### Scheduled GTFS

`rt2gtfs` expects scheduled GTFS files organised in a date-based structure that matches the templates used in `MatchingConfig`, for example:

* `gtfs_dir`
* `gtfs_filename_template`

### Real-time data

The package supports two main workflows:

1. Raw GTFS-Realtime protobuf or zipped files → converted using `convert_rt_to_csv`
2. Pre-converted CSV files → used directly in the matching pipeline

---

## Key configuration options

Important fields in `MatchingConfig` include:

* `gtfs_dir`: directory containing scheduled GTFS data
* `rt_dir`: directory containing real-time data (csv format)
* `result_dir`: output directory
* `check_extra_dates`: search nearby timetable dates
* `time_window_days`: number of days before/after target date
* `matching_periods`: optional time windows
* `search_radius_m`: stop search radius
* `extrapolate_stop_times`: allow extrapolation
* `n_workers`: number of processes
* `log_to_file`: write logs to file

---

## Outputs

The package produces:

* CSV files converted from GTFS-Realtime data
* Matching outputs and summary statistics
* Observed GTFS timetable outputs
* Logs and optional statistics files

---

## Notes

* Dates must be in `YYYYMMDD` format
* Times must be in `HH:MM:SS` format
* The package assumes file naming conventions defined in `MatchingConfig`

---

## Citation

If you would like to acknowledge `rt2gtfs` in your research or work, please cite the associated arXiv paper:

Chen, Z. and Botta, F. (2026). *rt2gtfs: A scalable framework for correcting public transport timetables using real-time data for accessibility analysis*. arXiv:2603.11477. https://doi.org/10.48550/arXiv.2603.11477

BibTeX:

```bibtex
@misc{chen2026scalable,
  title = {rt2gtfs: A scalable framework for correcting public transport timetables using real-time data for accessibility analysis},
  author = {Chen, Zihao and Botta, Federico},
  year = {2026},
  eprint = {2603.11477},
  archivePrefix = {arXiv},
  primaryClass = {cs.CY},
  doi = {10.48550/arXiv.2603.11477},
  url = {https://arxiv.org/abs/2603.11477}
}
```

---

## Acknowledgements

This work builds on ideas and approaches developed in prior work on GTFS and GTFS-Realtime processing.

In particular, the development of this package was influenced by the work of Luke Strange & Stuart Lowe, whose repository helped shape the workflow and implementation:

* https://github.com/open-innovations/bus-tracking/

This package extends and adapts these ideas for large-scale processing, with optimisations for the UK context.

---

## Development status

This package is under active development. Interfaces and defaults may still change.

---

## License

This project is licensed under the MIT License.
