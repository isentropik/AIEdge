"""Identity of the capture operation used to review a missing photo."""
import hashlib
from contextlib import nullcontext
from pathlib import Path

from capture_recovery import digest


def capture_trial_context(setup, recognition, reading_format):
    calibration = setup.status()
    fixed_pipeline = getattr(recognition,'observation_pipeline_id',None)
    # Event mode fixes the pipeline for the lifetime of the context. In mutable
    # mode, calibration activation and this read still share the reader lock.
    with nullcontext() if fixed_pipeline is not None else recognition.lock:
        pipeline = fixed_pipeline if fixed_pipeline is not None else (
            recognition.reader.pipeline_id if recognition.reader else None)
        context = dict(calibration_revision=calibration.get('revision'),
                       pipeline_id=pipeline,
                       format_revision=reading_format.status()['revision'])
        if getattr(recognition, 'observation_context', None):
            context['observation_context'] = recognition.observation_context
        return context


def capture_context(options, data_dir, setup, recognition, reading_format, first_event):
    # These options select historical series for the chart. New or unknown
    # options remain bound unless explicitly identified as display-only.
    history = ('meter_history_entity', 'nominal_history_entity', 'daily_history_entity', 'recent_history_entity')
    sources = ('capture_context.py', 'capture_recovery.py', 'capture.py', 'lifecycle.py',
               'camera_status.py', 'camera_transport.py', 'capture_clock.py')
    control_files = ('camera-lighting-operation.json', 'camera-image-operation.json',
                     'camera-auto-operation.json', 'camera-auto.json')
    return {
        'options_sha256': digest({key: value for key, value in options.items() if key not in history}),
        'recognition': capture_trial_context(setup, recognition, reading_format),
        'first_event': first_event,
        'source': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                   for name in sources},
        'camera_controls': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                            for path in (Path(data_dir) / name for name in control_files)},
    }
