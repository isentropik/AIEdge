FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS native-build
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY native.cpp accounting_native.cpp package_assets.py check_accounting_core.py test_accounting_core.cpp ./
COPY assets ./assets
RUN python package_assets.py && python check_accounting_core.py && g++ -std=c++17 -O2 -ffp-contract=off -fPIC -shared -Iassets/include native.cpp -o libaiedge_native.so && g++ -std=c++17 -O2 -ffp-contract=off -fPIC -shared -Iassets/include accounting_native.cpp -o libaiedge_accounting.so

FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" io.hass.version="${BUILD_VERSION}" io.hass.arch="${BUILD_ARCH}"
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/aiedge
COPY requirements-linux-amd64.lock verify_notices.py ./
COPY third-party ./third-party
RUN python verify_notices.py
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-linux-amd64.lock && pip check
COPY --from=native-build /build/libaiedge_native.so /build/libaiedge_accounting.so ./
COPY assets ./assets
COPY camera_auto.py auto_capture.py auto_preview.py ./
COPY archive.py archive_copy.py archive.js camera_image.py camera-image.js camera_lighting.py camera-lighting.js camera_setup.py setup-flow.js parity.css service.py http_server.py durable_file.py diagnostics.py lifecycle.py options.py capture.py capture_clock.py camera_transport.py camera_status.py accounting_native.py consumption.py temporal_reading.py recognition.py review_store.py reader.py reading_format.py reading_bounds.py mqtt_output.py native.py calibration.py calibration_builder.py marker_suggestions.py setup_store.py saved_file.py editor-geometry.js reference-image.js setup.js reading-format.js dashboard.js capture-review.js app.css index.html favicon.svg package_assets.py verify_runtime.py ./
RUN python verify_runtime.py --library /opt/aiedge/libaiedge_native.so --accounting-library /opt/aiedge/libaiedge_accounting.so
ENV PYTHONUNBUFFERED=1
CMD ["python", "service.py", "--data", "/data", "--bind", "0.0.0.0", "--ingress", "--native-library", "/opt/aiedge/libaiedge_native.so", "--accounting-library", "/opt/aiedge/libaiedge_accounting.so", "--models", "/opt/aiedge/assets/models"]
