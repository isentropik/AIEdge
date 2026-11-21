import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from camera_control_snapshot import CameraControlSnapshot
from camera_image import Config as ImageConfig, capabilities as image_caps
from camera_lighting import Config as LightingConfig, capabilities as light_caps
from camera_setup import CameraSetup
from test_camera_image import CAPS as IMAGE_CAPS, CONFIG as IMAGE_CONFIG
from test_camera_lighting import CAPS as LIGHT_CAPS, CONFIG as LIGHT_CONFIG


class ControlSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.camera = SimpleNamespace(origin='http://camera.test')
        self.setup = SimpleNamespace(root=self.root)
        self.light = Mock()
        self.image = Mock()
        self.light.needs_attention.return_value = self.image.needs_attention.return_value = False
        self.image.requires_reference.return_value = False
        self.lighting = dict(revision='a'*64, lighting=LightingConfig(LIGHT_CONFIG).lighting(),
                             capabilities=light_caps(LIGHT_CAPS))
        self.sensor = dict(revision='a'*64, controls=ImageConfig(IMAGE_CONFIG, 'OV2640').controls(),
                           capabilities=image_caps(IMAGE_CAPS))
        self.light.load.return_value = self.lighting
        self.image.load.return_value = self.sensor
        self.worker = self.reopen()

    def reopen(self):
        return CameraSetup(self.camera, self.setup, 10, True, self.light, self.image)

    def job(self, action, **kwargs):
        self.worker.start(action, **kwargs)
        self.worker.once()
        return self.worker.status()

    def backup(self):
        panels = {key: {**value, 'backup_date': '2026-09-25'} for key, value in (
            ('settings', self.lighting), ('image_settings', self.sensor))}
        for value in panels.values():
            value.pop('capabilities')
        (self.root / 'camera-setup-backup.json').write_text(json.dumps(dict(
            version=1, source=self.worker.controls.source, panels=panels)))
        return panels

    def test_saved_panels_survive_other_jobs_restart_and_busy_camera(self):
        self.job('lighting-load')
        self.job('image-load')
        expected = dict(settings=self.lighting, image_settings=self.sensor)
        self.worker = self.reopen()
        self.assertEqual(self.worker.status()['saved_controls'], expected)
        self.worker.start('check')
        self.assertEqual(self.worker.status()['saved_controls'], expected)
        self.camera.readiness = Mock(side_effect=ValueError('camera_busy'))
        self.worker.once()
        self.assertEqual(self.worker.status()['error'], 'camera_busy')
        self.assertEqual(self.worker.status()['saved_controls'], expected)
        self.light.load.assert_called_once()
        self.image.load.assert_called_once()

    def test_legacy_backup_first_open_and_per_panel_upgrade(self):
        archive = self.backup()
        self.worker = self.reopen()
        self.assertEqual(self.worker.status()['saved_controls'], archive)
        self.light.load.assert_not_called()
        self.image.load.assert_not_called()
        self.job('image-load')
        self.assertEqual(self.reopen().status()['saved_controls'],
                         dict(settings=archive['settings'], image_settings=self.sensor))
        self.camera.origin='http://different.test'
        self.assertEqual(self.reopen().status()['saved_controls'], {})

    def test_confirmed_edit_rebases_only_an_exact_peer(self):
        self.job('lighting-load')
        self.job('image-load')
        self.light.apply.return_value = {**self.lighting, 'revision':'b'*64, 'active_verified':True}
        self.job('lighting-apply',revision='a'*64,lighting=self.lighting['lighting'])
        self.assertEqual(self.reopen().status()['saved_controls']['image_settings']['revision'],'b'*64)
        self.light.apply.return_value = {**self.lighting, 'revision':'c'*64, 'active_verified':True}
        self.job('lighting-apply',revision='d'*64,lighting=self.lighting['lighting'])
        self.assertEqual(self.reopen().status()['saved_controls']['image_settings']['revision'],'b'*64)
        self.image.apply.side_effect = ValueError('camera_image_conflict')
        self.job('image-apply',revision='b'*64,controls=self.sensor['controls'])
        self.assertEqual(self.reopen().status()['saved_controls']['image_settings']['revision'],'b'*64)

    def test_invalid_or_oversized_cache_falls_back_to_scoped_backup(self):
        archive = self.backup()
        self.job('image-load')
        path = self.worker.controls.path
        good = json.loads(path.read_bytes())
        good['panels']['image_settings']['controls']['gain'] = 999
        for bad in (json.dumps(good), '[]', 'x'*8193, '{"', 'null'):
            path.write_text(bad)
            self.assertEqual(self.reopen().status()['saved_controls'], archive)

    def test_disk_failure_keeps_last_success_and_does_not_retry_camera(self):
        self.job('lighting-load')
        with patch('setup_store.Setup._atomic', side_effect=OSError):
            result = self.job('image-load')
        self.assertEqual(result['state'],'ready')
        self.assertTrue(result['controls_save_failed'])
        self.assertEqual(result['saved_controls']['image_settings'], self.sensor)
        self.assertEqual(self.reopen().status()['saved_controls'], {'settings':self.lighting})
        self.assertFalse(self.worker.once())
        self.image.load.assert_called_once()

    def test_original_lowercase_gain_label(self):
        raw = IMAGE_CONFIG.replace(b'CamGainceiling = X4', b'CamGainceiling = x8')
        self.assertEqual(ImageConfig(raw,'OV2640').controls()['gain_limit'],2)
