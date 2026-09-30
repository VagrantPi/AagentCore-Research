FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

# PAD_MB > 0 時塞入不可壓縮的填充檔，用來觀察 image 大小對冷啟動的影響
ARG PAD_MB=0
RUN if [ "$PAD_MB" -gt 0 ]; then head -c "${PAD_MB}M" /dev/urandom > /ballast; fi

WORKDIR /app
COPY main.py .
EXPOSE 8080
CMD ["python", "main.py"]
