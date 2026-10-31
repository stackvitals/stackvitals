from mergescout.crawl.seed import WATCHED, apply_watch, read_watch


def test_watched_repos_go_to_the_front_of_the_crawl_queue(tmp_path):
    f = tmp_path / "watch.txt"
    f.write_text("# source repos of packages\nPSF/requests\n\nbabel/babel\n", encoding="utf-8")
    watch = read_watch(f)
    assert watch == {"psf/requests", "babel/babel"}
    rows = [{"name": "psf/requests", "priority": 3}, {"name": "someone/app", "priority": 900}]
    apply_watch(rows, watch)
    assert rows[0]["priority"] == WATCHED and rows[1]["priority"] == 900 and WATCHED > 100000
    assert read_watch(tmp_path / "missing.txt") == set()
