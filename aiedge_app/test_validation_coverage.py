"""Prevent a green validation result when required native coverage is skipped."""
import unittest
from types import SimpleNamespace
from run_validation import coverage_errors,inventory_errors,ARCHIVE_CHECKS,PACKAGED_CHECK,SAMPLING_CHECKS

def result(skips=(),count=1):
    return SimpleNamespace(testsRun=count,skipped=[(SimpleNamespace(id=lambda name=name:name),'fixture missing') for name in skips])
NEW_COVERAGE={*(f'test_reading_bounds.BoundTests.test_{i}' for i in range(8)),
              *(f'test_meter_profile.MeterTests.test_{i}' for i in range(8)),
              *(f'test_reading_consistency.ConsistencyTests.test_{i}' for i in range(5)),
              'test_reading_consistency.IntegrationTests.test_0',
              *(f'test_temporal_reading.TemporalTests.test_{i}' for i in range(10)),
              *(f'test_temporal_reading.PublicationTests.test_{i}' for i in range(4)),
              *(f'test_reading_bounds.IntegrationTests.test_{i}' for i in range(3)),
              *(f'test_startup_shutdown.StartupTests.test_{i}' for i in range(3)),
              *(f'test_startup_shutdown.RuntimeTests.test_{i}' for i in range(5)),
              *(f'test_runtime_copy.RuntimeCopyTests.test_{i}' for i in range(4)),
              *(f'test_lifecycle.LifecycleTests.test_{i}' for i in range(2)),
              *(f'test_camera_setup.CameraSetupTests.test_{i}' for i in range(8)),
              *(f'test_camera_lighting.ConfigTests.test_{i}' for i in range(7)),
              *(f'test_camera_lighting.LightingTransactions.test_{i}' for i in range(12)),
              *(f'test_camera_image.ImageConfigTests.test_{i}' for i in range(5)),
              *(f'test_camera_image.ImageTransactions.test_{i}' for i in range(10)),
              *(f'test_camera_setup.ImageSetupTests.test_{i}' for i in range(3)),
              *(f'test_camera_auto.AutoTransactions.test_{i}' for i in range(23)),
              *(f'test_camera_auto.AutoSetupTests.test_{i}' for i in range(7)),
              *(f'test_archive.ArchiveTests.test_{i}' for i in range(15)),
              *(f'test_archive.ArchiveCopyTests.test_{i}' for i in range(6)),
              *(f'test_archive.ArchiveLinuxTests.test_{i}' for i in range(2)),
              *(f'test_archive_http.ArchiveHttpTests.test_{i}' for i in range(3)),*SAMPLING_CHECKS}
class ValidationCoverageTests(unittest.TestCase):
    def test_archive_omission_requires_explicit_permission(self):
        value=result(ARCHIVE_CHECKS)
        self.assertEqual(coverage_errors(value,True,False),[])
        self.assertEqual(len(coverage_errors(value,False,False)),6)
    def test_accounting_and_generated_model_skips_are_never_accepted(self):
        for name in ('test_consumption.AccountingTests.test_unique_intervals_and_many_turns_survive_restart',
                     'test_synthetic_pipeline.GeneratedPipelineTests.test_both_model_routes_estimate_without_accuracy_or_label_claims',
                     'test_changed_dials.ChangedDialTests.test_changed_dial_only_recomputes_its_crop'):
            self.assertEqual(len(coverage_errors(result([name]),True,False)),1)
    def test_packaged_startup_skip_is_rejected_when_container_required(self):
        value=result([PACKAGED_CHECK]);self.assertEqual(coverage_errors(value,True,False),[])
        self.assertEqual(len(coverage_errors(value,True,True)),1)
    def test_no_tests_or_new_unexpected_archive_skip_fails(self):
        self.assertEqual(len(coverage_errors(result(count=0),True,False)),1)
        self.assertEqual(len(coverage_errors(result(['test_native_profile.Tests.test_new_coverage']),True,False)),1)
    def test_missing_accounting_or_generated_test_file_cannot_look_successful(self):
        complete={*('test_consumption.AccountingTests.test_'+str(i) for i in range(20)),
                  *('test_consumption.FormatBoundTests.test_'+str(i) for i in range(3)),
                  *('test_synthetic_pipeline.GeneratedPipelineTests.test_'+str(i) for i in range(3)),
                  *('test_reading_format.Tests.test_'+str(i) for i in range(13)),
                  *('test_reviews.ReviewTests.test_'+str(i) for i in range(13)),
                  *('test_review_http.HttpReviewTests.test_'+str(i) for i in range(3)),
                  *('test_marker_suggestions.SuggestionTests.test_'+str(i) for i in range(5)),
                  *('test_changed_dials.ChangedDialTests.test_'+str(i) for i in range(12))}
        complete|=NEW_COVERAGE
        self.assertEqual(inventory_errors(complete,True,False),[])
        for prefix in ('test_meter_profile.','test_consumption.','test_synthetic_pipeline.','test_reviews.','test_review_http.','test_marker_suggestions.','test_changed_dials.',
                       'test_reading_bounds.','test_reading_consistency.','test_temporal_reading.','test_startup_shutdown.','test_runtime_copy.','test_lifecycle.','test_camera_setup.','test_camera_lighting.','test_camera_image.','test_camera_auto.'):
            self.assertTrue(inventory_errors({i for i in complete if not i.startswith(prefix)},True,False))
    def test_duplicate_ids_cannot_satisfy_required_coverage(self):
        self.assertTrue(inventory_errors(['test_consumption.AccountingTests.test_one']*23,True,False))
    def test_requested_packaged_or_archive_checks_must_exist(self):
        complete={*('test_consumption.AccountingTests.test_'+str(i) for i in range(20)),
                  *('test_consumption.FormatBoundTests.test_'+str(i) for i in range(3)),
                  *('test_synthetic_pipeline.GeneratedPipelineTests.test_'+str(i) for i in range(3)),
                  *('test_reading_format.Tests.test_'+str(i) for i in range(13)),
                  *('test_reviews.ReviewTests.test_'+str(i) for i in range(13)),
                  *('test_review_http.HttpReviewTests.test_'+str(i) for i in range(3)),
                  *('test_marker_suggestions.SuggestionTests.test_'+str(i) for i in range(5)),
                  *('test_changed_dials.ChangedDialTests.test_'+str(i) for i in range(12))}
        complete|=NEW_COVERAGE
        self.assertEqual(len(inventory_errors(complete,True,True)),1)
        self.assertEqual(len(inventory_errors(complete,False,False)),1)
        self.assertEqual(inventory_errors(complete|ARCHIVE_CHECKS|{PACKAGED_CHECK},False,True),[])
if __name__=='__main__':unittest.main()
