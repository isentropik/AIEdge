"""Runtime export admission with fake libraries; no models or pictures."""
import unittest
from types import SimpleNamespace
import test_reader_observation_mask  # Supplies fake interpreter imports only.
from verify_runtime import require_preparation_exports

class PreparationExportTests(unittest.TestCase):
    def test_matching_library(self):
        require_preparation_exports(SimpleNamespace(aiedge_prepare_profile_reuse=object(),aiedge_prepare_profile_masked=object()))
    def test_missing_reuse(self):
        with self.assertRaisesRegex(ValueError,'changed_dial_runtime_missing'):
            require_preparation_exports(SimpleNamespace(aiedge_prepare_profile_masked=object()))
    def test_old_library_rejected_by_new_package(self):
        with self.assertRaisesRegex(ValueError,'masked_preparation_runtime_missing'):
            require_preparation_exports(SimpleNamespace(aiedge_prepare_profile_reuse=object()))

if __name__=='__main__':unittest.main()
