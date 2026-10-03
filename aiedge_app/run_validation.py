"""Required native/model coverage; optional archive omissions must be explicit."""
import argparse,hashlib,json,os,platform,subprocess,sys,unittest
from pathlib import Path

ARCHIVE_CHECKS=frozenset(('test_capture_pipeline.CapturePipelineTests.test_remote_transport_store_infer_restart',
    'test_native_profile.Tests.test_dense_and_sparse_match_frozen',
    'test_native_profile.Tests.test_geometry_and_markers_rejected',
    'test_native_profile.Tests.test_owns_candidate_and_rejects_closed_handle',
    'test_native_profile.Tests.test_reordered_subset','test_native_profile.Tests.test_blank_image_rejected'))
PACKAGED_CHECK='test_container_runtime.ContainerRuntimeTests.test_packaged_service_startup_and_persistent_restart'
SAMPLING_CHECKS=frozenset((
    'test_changed_dials.ChangedDialTests.test_camera_jpeg_defaults_to_full_sampling_with_separate_sparse_identity',
    'test_changed_dials.ChangedDialTests.test_explicit_sparse_reader_and_invalid_sampling_inputs',
    'test_recognition.Tests.test_different_sampling_pipeline_cannot_be_relabelled_as_current'))
NAS_LINUX_CHECKS=frozenset(('test_archive.ArchiveLinuxTests.test_nofollow_directory_files_and_nonregular_rejection',
    'test_archive.ArchiveLinuxTests.test_child_lock_admits_one_process_and_parent_death_stops_it'))

def coverage_errors(result,allow_archive,packaged):
    errors=[]
    if result.testsRun==0:errors.append('No tests ran.')
    allowed=set(ARCHIVE_CHECKS if allow_archive else ())
    if not packaged:allowed.add(PACKAGED_CHECK)
    if platform.system()!='Linux' and not packaged:allowed.update(NAS_LINUX_CHECKS)
    for test,reason in result.skipped:
        if test.id() not in allowed:errors.append('Required check skipped: '+test.id()+': '+reason)
    return errors

def inventory_errors(identifiers,allow_archive,packaged):
    identifiers=set(identifiers);errors=[]
    for prefix,minimum in (('test_consumption.AccountingTests.',20),('test_consumption.FormatBoundTests.',3),
                           ('test_synthetic_pipeline.GeneratedPipelineTests.',3),
                           ('test_reading_format.',13),('test_reviews.ReviewTests.',13),('test_review_http.HttpReviewTests.',3),('test_marker_suggestions.SuggestionTests.',5),
                           ('test_changed_dials.ChangedDialTests.',12),('test_reading_bounds.BoundTests.',8),
                           ('test_reading_bounds.IntegrationTests.',3),('test_startup_shutdown.StartupTests.',3),
                           ('test_temporal_reading.TemporalTests.',10),('test_temporal_reading.PublicationTests.',4),
                           ('test_reading_consistency.ConsistencyTests.',5),('test_reading_consistency.IntegrationTests.',1),
                           ('test_startup_shutdown.RuntimeTests.',5),('test_runtime_copy.RuntimeCopyTests.',4),
                           ('test_lifecycle.LifecycleTests.',2),('test_camera_setup.CameraSetupTests.',8),
                           ('test_camera_lighting.ConfigTests.',7),('test_camera_lighting.LightingTransactions.',12),
                           ('test_camera_image.ImageConfigTests.',5),('test_camera_image.ImageTransactions.',10),
                           ('test_camera_setup.ImageSetupTests.',3),
                           ('test_camera_auto.AutoTransactions.',23),('test_camera_auto.AutoSetupTests.',7),
                           ('test_archive.ArchiveTests.',15),('test_archive.ArchiveCopyTests.',6),
                           ('test_archive.ArchiveLinuxTests.',2),('test_archive_http.ArchiveHttpTests.',3)):
        if sum(name.startswith(prefix) for name in identifiers)<minimum:
            errors.append('Required test coverage is missing: '+prefix)
    if packaged and PACKAGED_CHECK not in identifiers:
        errors.append('Packaged-service startup check is missing.')
    if not SAMPLING_CHECKS<=identifiers:
        errors.append('Required sampling identity coverage is missing.')
    if not allow_archive and not ARCHIVE_CHECKS<=identifiers:
        errors.append('Requested archived-image replay checks are missing.')
    return errors

def suite_identifiers(suite):
    for test in suite:
        if isinstance(test,unittest.TestSuite):yield from suite_identifiers(test)
        else:yield test.id()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--accounting-library',type=Path,required=True)
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--archive-calibration',type=Path)
    parser.add_argument('--archive-rgb',type=Path)
    parser.add_argument('--archive-jpeg',type=Path)
    parser.add_argument('--allow-missing-archive-replay',action='store_true')
    parser.add_argument('--container',action='store_true',help='Require Linux amd64 and the /opt/aiedge packaged-service test.')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    if args.container and (platform.system()!='Linux' or platform.machine().lower() not in ('x86_64','amd64')):
        parser.error('--container requires the Linux amd64 packaged runtime.')
    archive=(args.archive_calibration,args.archive_rgb,args.archive_jpeg)
    if any(archive) and not all(archive):parser.error('Supply all three archive fixture paths, or none.')
    if not all(archive) and not args.allow_missing_archive_replay:
        parser.error('Private archived-image replay needs all three fixture paths. Use --allow-missing-archive-replay to explicitly omit it.')
    files={'recognition':args.library,'accounting':args.accounting_library}
    if all(archive):files.update(zip(('archive_calibration','archive_rgb','archive_jpeg'),archive))
    for name,path in files.items():
        if not path.is_file():parser.error(name+' file is unavailable.')
    for model in ('polar-main-int8.tflite','polar-int8.tflite'):
        if not (args.models/model).is_file():parser.error('Required model is unavailable: '+model)
    os.environ.update(AIEDGE_NATIVE_LIBRARY=str(args.library.resolve()),AIEDGE_READING_LIBRARY=str(args.library.resolve()),
                      AIEDGE_ACCOUNTING_LIBRARY=str(args.accounting_library.resolve()),AIEDGE_MODELS_FIXTURE=str(args.models.resolve()))
    for key,path in zip(('AIEDGE_CALIBRATION_FIXTURE','AIEDGE_RGB_FIXTURE','AIEDGE_JPEG_FIXTURE'),archive):
        if path:os.environ[key]=str(path.resolve())
        else:os.environ.pop(key,None)
    if args.container:os.environ['AIEDGE_CONTAINER_TEST']='1'
    else:os.environ.pop('AIEDGE_CONTAINER_TEST',None)
    command=[sys.executable,str(root/'verify_runtime.py'),'--library',str(args.library.resolve()),'--accounting-library',str(args.accounting_library.resolve())]
    subprocess.run(command,check=True)
    suite=unittest.defaultTestLoader.discover(str(root),pattern='test_*.py')
    identifiers=list(suite_identifiers(suite))
    missing=inventory_errors(identifiers,not all(archive),args.container)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    errors=missing+coverage_errors(result,not all(archive),args.container)
    report={'success':result.wasSuccessful() and not errors,'tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'unexpected_coverage_errors':errors,
            'skipped':[{'test':test.id(),'reason':reason} for test,reason in result.skipped],
            'archive_replay_included':all(bool(p) for p in archive),'packaged_runtime_required':args.container,
            'generated_image_checks':'Synthetic only; not real-image accuracy or training labels.',
            'platform':platform.system(),'machine':platform.machine(),
            'native_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items() if name in ('recognition','accounting')},
            'accuracy_verified':False,'training_allowed':False}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['success'] else 1

if __name__=='__main__':raise SystemExit(main())
