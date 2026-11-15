import pytest

from marswalk import radiation

LABEL = '''
^OBS000_TOT_DOSE_B_ELEMENT =
              ("RAD_RDR_2025_132_07_57_4538_V00.TXT",18892 <BYTES>)
^OBS002_TOT_DOSE_B_ELEMENT =
              ("RAD_RDR_2025_132_07_57_4538_V00.TXT",830483 <BYTES>)
'''

TEXT = """
[DOSIMETRY_TOTAL_DOSE_B: 00]

7.09261

[DOSIMETRY_TOTAL_DOSE_E: 00]

6.71253

[DOSIMETRY_TOTAL_DOSE_B: 02]

7.36058
"""


def test_dose_pointers_are_read_from_the_label():
    assert radiation.dose_pointers(LABEL) == {0: 18892, 2: 830483}


def test_doses_are_parsed_per_observation_and_detector():
    doses = radiation.parse_doses(TEXT)
    assert doses[0] == {"B": 7.09261, "E": 6.71253}
    assert doses[2] == {"B": 7.36058}


def test_daily_dose_skips_dropouts_and_converts_to_milligray():
    rows = [(4538, 0, 7.0, 6.0), (4538, 2, 7.0, 8.0), (4538, 4, 0.1, 0.02), (4539, 0, 7.0, None)]
    daily = radiation.daily_dose_mgy(rows)
    assert daily == {4538: pytest.approx(7.0 * radiation.HOURS_PER_SOL / 1000)}
