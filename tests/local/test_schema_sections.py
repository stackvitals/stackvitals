"""Each settings table appears once on the settings page: entries of one table sit together in the schema."""
from stackvitals.core import schema


def test_no_settings_table_is_split_in_two():
    heads = [line for line in schema.markdown().splitlines() if line.startswith("## [")]
    assert len(heads) == len(set(heads)), sorted(h for h in heads if heads.count(h) > 1)
