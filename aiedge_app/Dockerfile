FROM python:3.14.7-slim-trixie AS native-build
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY native.cpp package_assets.py ./
COPY assets ./assets
RUN python package_assets.py && g++ -std=c++17 -O2 -ffp-contract=off -fPIC -shared -Iassets/include native.cpp -o libaiedge_native.so

FROM python:3.14.7-slim-trixie
ARG BUILD_VERSION
ARG BUILD_ARCH
LABEL io.hass.type="app" io.hass.version="${BUILD_VERSION}" io.hass.arch="${BUILD_ARCH}"
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/aiedge
COPY requirements-linux-amd64.lock ./
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements-linux-amd64.lock && pip check
COPY --from=native-build /build/libaiedge_native.so ./
COPY assets ./assets
COPY service.py capture.py recognition.py reader.py reading_format.py mqtt_output.py native.py calibration.py calibration_builder.py setup_store.py setup.js reading-format.js dashboard.js index.html package_assets.py verify_runtime.py ./
RUN python verify_runtime.py --library /opt/aiedge/libaiedge_native.so
ENV PYTHONUNBUFFERED=1
CMD ["python", "service.py", "--data", "/data", "--bind", "0.0.0.0", "--ingress", "--native-library", "/opt/aiedge/libaiedge_native.so", "--models", "/opt/aiedge/assets/models"]
