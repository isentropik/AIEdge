FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY image_archive_receiver.py image_archive_store.py /app/
USER 65532:65532
EXPOSE 8766
ENTRYPOINT ["python", "/app/image_archive_receiver.py"]
CMD ["--bind", "0.0.0.0", "--port", "8766", "--folder", "/archive", "--token-file", "/run/archive/token.txt", "--certificate", "/run/archive/server.pem", "--private-key", "/run/archive/server-key.pem"]
