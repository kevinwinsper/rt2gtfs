from rt2gtfs.rt_to_csv import _rt_filepaths_to_list


def test_rt_file_discovery_includes_next_calendar_day_filename(tmp_path):
    service_date_dir = tmp_path / "20260722"
    service_date_dir.mkdir()
    service_day_file = service_date_dir / "vehicle_positions_20260722_235500.bin"
    next_day_file = service_date_dir / "vehicle_positions_20260723_020000.bin"
    ignored_file = service_date_dir / "vehicle_positions_20260723_020500.zip"
    service_day_file.touch()
    next_day_file.touch()
    ignored_file.touch()

    result = _rt_filepaths_to_list(service_date_dir)

    assert result == [service_day_file, next_day_file]
